from __future__ import annotations

import re
import socket
import time
import zipfile
from datetime import datetime
from urllib.parse import urljoin
from pathlib import Path
from threading import Event
from typing import Callable, Iterable

from playwright.sync_api import (
    Browser,
    Error as PlaywrightError,
    Locator,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    expect,
    sync_playwright,
)

from .i18n import tr
from .logging_utils import get_logs_dir
from .models import DownloadType, DownloadedArtifacts

LogCallback = Callable[[str], None]
AnalysisProgressCallback = Callable[[int | None, str], None]


class MetascapeAutomationError(Exception):
    """Raised when Metascape automation cannot finish successfully."""


# Metascape 维护期的提示：维护页结构完全不同，重试前必须先让用户知道原因
MAINTENANCE_MESSAGE = (
    "Metascape 当前返回的是维护页（maintenance.html），页面结构完全不同，正在等待其恢复；"
    "若长时间不恢复请稍后再试。"
)
# 维护状态最多等待这么久（超过则判该文件失败，并明确写出"维护中"而不是笼统的元素超时）
MAINTENANCE_MAX_WAIT_SECONDS = 900.0
# 维护页多数是 app.js 里 health_check_pull 偶发失败导致的假警报（后端一直是 0），
# 因此先用较短间隔重载几次尝试恢复，再退回较慢的轮询。
MAINTENANCE_FAST_RELOAD_ATTEMPTS = 8
MAINTENANCE_FAST_RELOAD_INTERVAL_MS = 2000


def proxy_is_reachable(proxy_url: str, timeout_seconds: float = 2.0) -> bool:
    """检查代理端口是否真的有人监听（未启动的代理会让整次运行白等）。

    实际教训：配置里选了"代理 127.0.0.1:51888"，但代理软件没开，
    浏览器仍然能加载直连可达的站点，于是分析很慢却又说不出原因。
    """
    try:
        host, _, port = proxy_url.split("//", 1)[-1].partition(":")
        if not port:
            return True  # 没有端口的代理地址交给 Chromium 自己处理
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout_seconds)
            return sock.connect_ex((host.strip("/"), int(port.split("/")[0]))) == 0
    except Exception:  # noqa: BLE001
        return True


class MetascapeClient:
    HOME_URL = "https://metascape.org/gp/index.html"
    TEXTBOX_SELECTOR = "textarea[placeholder*='Gene' i]"
    TEXTBOX_SELECTORS = [
        TEXTBOX_SELECTOR,
        "textarea[aria-label*='Gene' i]",
        "textarea",
    ]
    SUBMIT_SELECTORS = [
        "button:has-text('Submit')",
        "[role='button']:has-text('Submit')",
        "input[type='submit']",
        "text=/Submit/i",
    ]
    XLSX_DOWNLOAD_SELECTORS = [
        "a:has-text('Excel')",
        "button:has-text('Excel')",
        "text=/Excel/i",
        "[href*='.xlsx']",
    ]
    ZIP_DOWNLOAD_SELECTORS = [
        "a:has-text('All in One Zip')",
        "a:has-text('All Files in Zip')",
        "button:has-text('All in One Zip')",
        "button:has-text('All Files in Zip')",
        "text=/zip/i",
        "[href*='.zip']",
    ]
    REPORT_PAGE_SELECTORS = [
        "button:has-text('Analysis Report Page')",
        "a:has-text('Analysis Report Page')",
        "text=/Analysis Report Page/i",
    ]
    PROGRESSBAR_SELECTORS = [
        ".k-progressbar .k-state-selected",
        ".progress-bar",
        "[role='progressbar']",
    ]

    # 选择器 → 可见文本：用于 DOM 点击（实测 locator.click() 在本机会整段挂死 30 秒，
    # 而 DOM 点击 1 秒内完成且能正常驱动 Angular 的 ng-click）
    DOM_CLICK_LABELS = {
        "button:has-text('Submit')": "Submit",
        "button:has-text('Express Analysis')": "Express Analysis",
        "button:has-text('Analysis Report Page')": "Analysis Report Page",
        "button:has-text('Excel')": "Gene List Report Excel Sheets",
        "button:has-text('All in One Zip')": "All in One Zip File",
        "button:has-text('All Files in Zip')": "All in One Zip File",
    }

    # DOM 点击脚本：校验元素可点后派发 click（同时补齐 mousedown/mouseup，兼容 Kendo 组件）
    DOM_CLICK_SCRIPT = """(label) => {
        const candidates = [...document.querySelectorAll('button, [role=button], a')];
        const el = candidates.find(x => (x.textContent || '').trim() === label)
            || candidates.find(x => (x.textContent || '').trim().startsWith(label));
        if (!el) { return {ok: false, reason: 'not-found', label}; }
        if (el.disabled || el.getAttribute('aria-disabled') === 'true') {
            return {ok: false, reason: 'disabled', label};
        }
        const rect = el.getBoundingClientRect();
        if (!rect.width || !rect.height) { return {ok: false, reason: 'invisible', label}; }
        el.click();
        el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
        el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
        return {ok: true, reason: 'clicked', label};
    }"""

    def __init__(self, headless: bool = True, proxy_url: str | None = None) -> None:
        self._headless = headless
        self._proxy_url = proxy_url
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._maintenance_warned = False
        self._maintenance_started_at: float | None = None

    def __enter__(self) -> "MetascapeClient":
        try:
            self._playwright = sync_playwright().start()
            # 5 个并发浏览器同时跑 Angular 页面时，系统饱和会让渲染进程"饿"住、鼠标输入拿不到 ack
            # （Playwright 维护者把这种现象称为 system saturation）。这里关掉后台节流，
            # 并在常规/强制鼠标点击都失败时做命中测试诊断。
            launch_kwargs = {
                "headless": self._headless,
                "args": [
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                ],
            }
            if self._proxy_url:
                launch_kwargs["proxy"] = {"server": self._proxy_url}
            self._browser = self._playwright.chromium.launch(**launch_kwargs)
            return self
        except (PlaywrightError, OSError) as exc:
            self.close()
            raise MetascapeAutomationError(
                tr("无法启动 Chromium，请先安装 Playwright 浏览器：{error}").format(error=exc)
            ) from exc

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def process_gene_list(
        self,
        download_path: Path,
        gene_text: str,
        download_type: DownloadType,
        timeout_seconds: int,
        stop_event: Event,
        log_callback: LogCallback | None = None,
        analysis_progress_callback: AnalysisProgressCallback | None = None,
        extracted_dir: Path | None = None,
    ) -> DownloadedArtifacts:
        if self._browser is None:
            raise MetascapeAutomationError(tr("浏览器尚未启动。"))

        context = self._browser.new_context(accept_downloads=True)
        page = context.new_page()
        self._maintenance_warned = False
        try:
            # 打开首页：DOM 就绪即可，networkidle 只做 5s 尽力等待（Metascape 有长连接，基本不会触发）
            self._log(log_callback, tr("打开 Metascape：{url}").format(url=self.HOME_URL))
            page.goto(self.HOME_URL, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            try:
                page.wait_for_load_state("networkidle", timeout=5_000)
            except PlaywrightTimeoutError:
                pass
            # 记录落地 URL/标题：app.js 的 health_check_pull 失败时会自行跳到 maintenance.html
            self._log(log_callback, self._describe_page(page))

            # 定位并激活基因输入框，确认可编辑后再填入基因列表
            if self._check_maintenance(page, log_callback):
                # 维护页：先用 2 秒间隔重载几次（多为健康检查偶发失败导致的假警报），再退回慢轮询
                self._recover_from_maintenance(page, stop_event, log_callback)

            textbox, textbox_selector = self._find_first_visible(
                page,
                self.TEXTBOX_SELECTORS,
                timeout_seconds=60,
                stop_event=stop_event,
                log_callback=log_callback,
            )
            self._log(log_callback, tr("已定位基因输入框：{selector}").format(selector=textbox_selector))
            self._wait_for_editable_textbox(
                page,
                textbox,
                timeout_seconds=min(timeout_seconds, 60),
                stop_event=stop_event,
            )
            # 基因输入框没有文本标签，DOM 点击只用于取焦点；真正的写入在 _set_textbox_value 里用 JS 赋值完成
            try:
                page.evaluate(
                    """(selector) => {
                        const el = document.querySelector(selector);
                        if (!el) { throw new Error('textarea not found'); }
                        el.focus();
                        el.click();
                    }""",
                    textbox_selector if textbox_selector in self.TEXTBOX_SELECTORS else self.TEXTBOX_SELECTOR,
                )
                self._log(log_callback, tr("基因输入框已就绪（跳过鼠标点击）。"))
            except Exception as exc:  # noqa: BLE001
                self._log(log_callback, tr("基因输入框聚焦失败，改用鼠标点击：{error}").format(error=exc))
                self._click_with_retry(
                    page,
                    textbox_selector,
                    tr("基因输入框"),
                    stop_event,
                    log_callback,
                    timeout_ms=15_000,
                )
            # 大列表（数千基因）用 fill() 会让 Playwright 的动作性检查卡满 30s（实测 8000 基因超时，
            # 但 textarea 其实已经写入），因此改为直接赋值 + 派发 input/change，实测 0.5s 完成。
            self._set_textbox_value(
                page,
                textbox,
                gene_text,
                log_callback,
                selector=textbox_selector if textbox_selector in self.TEXTBOX_SELECTORS else self.TEXTBOX_SELECTOR,
            )

            # 粘贴后 Submit 才由 ng-show 显示：等它可见且可点击，避免误落禁用的 Express 按钮
            submit_button, submit_selector = self._wait_for_clickable(
                page,
                self.SUBMIT_SELECTORS,
                timeout_seconds=60,
                stop_event=stop_event,
                log_callback=log_callback,
            )
            self._log(log_callback, tr("已定位提交按钮：{selector}").format(selector=submit_selector))
            self._click_with_retry(
                page,
                submit_selector,
                tr("Submit 按钮"),
                stop_event,
                log_callback,
            )
            self._report_progress(analysis_progress_callback, 5, tr("已提交基因列表，等待进入分析流程"))

            # Submit 会触发 ID 转换，完成后 Step 3 的 Express Analysis 按钮才变为 enabled
            express_button, express_selector = self._wait_for_enabled(
                page,
                ["button:has-text('Express Analysis')", "text=/Express Analysis/i"],
                timeout_seconds=60,
                stop_event=stop_event,
            )
            self._log(log_callback, tr("已定位 Express Analysis 按钮：{selector}").format(selector=express_selector))
            self._click_with_retry(
                page,
                express_selector,
                tr("Express Analysis 按钮"),
                stop_event,
                log_callback,
            )
            self._report_progress(analysis_progress_callback, 10, tr("已启动 Express Analysis"))

            # 等待分析进度到 100%，Analysis Report Page 按钮变为可点击
            self._log(log_callback, tr("等待 Analysis Report Page 按钮与 Metascape 分析进度。"))
            report_button, report_selector = self._wait_for_report_button(
                page,
                timeout_seconds=timeout_seconds,
                stop_event=stop_event,
                progress_callback=analysis_progress_callback,
            )
            self._log(log_callback, tr("已定位 Analysis Report Page 按钮：{selector}").format(selector=report_selector))

            # 进入报告页：当前版本为同标签页跳转，方法内部兼容新标签页
            report_page = self._open_report_page(context, page, report_selector, stop_event, log_callback)
            self._report_progress(analysis_progress_callback, 90, tr("已进入 Analysis Report Page，等待下载入口"))

            # 在报告页定位下载入口（按下载类型选择 Excel 或 Zip）
            selectors = (
                self.XLSX_DOWNLOAD_SELECTORS
                if download_type is DownloadType.XLSX_ONLY
                else self.ZIP_DOWNLOAD_SELECTORS
            )
            download_path.parent.mkdir(parents=True, exist_ok=True)
            # 优先直接按 URL 取文件：报告页在并发渲染时"可见性"判定会一直等下去
            # （5 个报告页同时渲染 1.5MB 表格实测会卡满分钟的等待），而 HTTP 取文件不需要页面可见。
            direct_done = self._download_from_report_url(
                report_page,
                report_selector_hint=report_selector,
                download_type=download_type,
                download_path=download_path,
                stop_event=stop_event,
                log_callback=log_callback,
                timeout_seconds=180,
            )
            if not direct_done:
                download_target, download_selector = self._find_first_visible(
                    report_page,
                    selectors,
                    timeout_seconds=min(timeout_seconds, 300),
                    stop_event=stop_event,
                    log_callback=log_callback,
                )
                self._log(log_callback, tr("已定位下载入口：{selector}").format(selector=download_selector))

                # 走 Playwright 下载事件（兜底路径）
                if not self._try_direct_download(report_page, download_target, download_path):
                    with report_page.expect_download(timeout=timeout_seconds * 1000) as download_info:
                        self._click_with_retry(
                            report_page,
                            download_selector,
                            tr("下载入口"),
                            stop_event,
                            log_callback,
                            timeout_ms=20_000,
                        )
                    download = download_info.value
                    try:
                        download.save_as(download_path)
                    except Exception:  # noqa: BLE001
                        self._save_download_from_href(report_page, download_target, download_path)
            self._log(log_callback, tr("下载完成：{path}").format(path=download_path))
            self._report_progress(analysis_progress_callback, 100, tr("Metascape 下载完成"))

            # Excel 模式直接返回；Zip 模式解压并在其中定位 Excel
            if download_type is DownloadType.XLSX_ONLY:
                return DownloadedArtifacts(download_path=download_path, excel_path=download_path)

            if extracted_dir is None:
                raise MetascapeAutomationError(tr("Zip 模式缺少解压目录参数。"))
            extracted_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(download_path, "r") as archive:
                archive.extractall(extracted_dir)
            excel_path = self._find_excel_in_directory(extracted_dir)
            self._log(log_callback, tr("已从压缩包定位 Excel：{path}").format(path=excel_path))
            return DownloadedArtifacts(
                download_path=download_path,
                excel_path=excel_path,
                extracted_dir=extracted_dir,
            )
        except PlaywrightTimeoutError as exc:
            raise MetascapeAutomationError(
                tr("等待 Metascape 页面元素超时，请检查网络或页面选择器。原始错误：{error}").format(error=exc)
            ) from exc
        except PlaywrightError as exc:
            # 断网 / 代理拒绝（net::ERR_*）/ 浏览器崩溃：转成可被 worker 正常记录的错误，
            # 否则会绕过 _process_single_file 的异常处理，界面上该 worker 一直停在"正在处理"
            raise MetascapeAutomationError(
                tr("Metascape 页面操作失败（网络或浏览器异常）：{error}").format(error=exc)
            ) from exc
        finally:
            page.close()
            context.close()

    def _wait_for_report_button(
        self,
        page: Page,
        timeout_seconds: int,
        stop_event: Event,
        progress_callback: AnalysisProgressCallback | None = None,
    ) -> tuple[Locator, str]:
        deadline = time.monotonic() + timeout_seconds
        last_percent: int | None = None

        # 每秒轮询：读取进度条百分比并回调，同时检查报告按钮是否已可点击
        while time.monotonic() < deadline:
            if stop_event.is_set():
                raise MetascapeAutomationError(tr("用户已停止任务。"))

            percent = self._read_progress_percent(page)
            if percent is not None and percent != last_percent:
                last_percent = percent
                self._report_progress(progress_callback, percent, tr("Metascape 正在分析：{percent}%").format(percent=percent))

            for selector in self.REPORT_PAGE_SELECTORS:
                locator = page.locator(selector).first
                try:
                    if locator.count() > 0 and locator.is_visible() and locator.is_enabled():
                        return locator, selector
                except Exception:  # noqa: BLE001
                    continue

            page.wait_for_timeout(1000)

        raise MetascapeAutomationError(tr("等待 Analysis Report Page 按钮超时。"))

    def _open_report_page(
        self,
        context,
        page: Page,
        report_selector: str,
        stop_event: Event,
        log_callback: LogCallback | None,
    ) -> Page:
        """进入分析报告页。

        报告按钮的处理器是 ``openReportFinalUrl()``（内部 ``window.open``），在无头/自动化的
        用户手势判定下会被浏览器弹窗策略拦住，点了也打不开——实测就是这样卡住了 5 分钟。
        因此这里先试点击（兼容旧行为），拿不到就**直接按 session_id 跳转**
        ``#/reportfinal/<session_id>``（实测可行，且不再依赖弹窗）。
        """
        self._click_with_retry(
            page,
            report_selector,
            tr("Analysis Report Page 按钮"),
            stop_event,
            log_callback,
            timeout_ms=20_000,
        )

        report_page = self._wait_for_report_page(context, page, pages_before=set(context.pages), stop_event=stop_event, timeout_seconds=15)
        if report_page is not None:
            return report_page

        # 点击没能进入报告页（多半是 window.open 被弹窗策略拦下）：直接按 session_id 跳转
        session_id = self._read_session_id(page)
        if not session_id:
            raise MetascapeAutomationError(tr("等待 Analysis Report Page 超时，且未能取得 session_id。"))
        target = urljoin(page.url, f"#/reportfinal/{session_id}")
        self._log(log_callback, tr("点击未能打开报告页（弹窗被拦截），改用 session_id 直接跳转：{url}").format(url=target))
        page.goto(target, wait_until="domcontentloaded", timeout=60_000)
        report_page = self._wait_for_report_page(
            context, page, pages_before=set(), stop_event=stop_event, timeout_seconds=60
        )
        if report_page is None:
            raise MetascapeAutomationError(tr("等待 Analysis Report Page 超时。"))
        return report_page

    def _wait_for_report_page(
        self,
        context,
        page: Page,
        pages_before: set[Page],
        stop_event: Event,
        timeout_seconds: float,
    ) -> Page | None:
        """等待报告页就绪：新标签页、或当前标签页跳到 /reportfinal 且下载入口可见。"""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if stop_event.is_set():
                raise MetascapeAutomationError(tr("用户已停止任务。"))
            if self._check_maintenance(page, None):
                page.wait_for_timeout(2000)
                continue

            new_pages = [item for item in context.pages if item not in pages_before]
            if new_pages:
                report_page = new_pages[0]
                report_page.wait_for_load_state("domcontentloaded", timeout=30_000)
                return report_page

            if "/reportfinal" in page.url:
                for selector in [*self.XLSX_DOWNLOAD_SELECTORS, *self.ZIP_DOWNLOAD_SELECTORS]:
                    try:
                        locator = page.locator(selector).first
                        if locator.count() > 0 and locator.is_visible():
                            return page
                    except Exception:  # noqa: BLE001
                        continue

            page.wait_for_timeout(500)
        return None

    @staticmethod
    def _read_session_id(page: Page) -> str | None:
        """取当前分析的 session_id：优先看 URL，其次问页面的 Angular 服务。"""
        try:
            match = re.search(r"reportfinal/([A-Za-z0-9]+)", page.url)
            if match:
                return match.group(1)
        except Exception:  # noqa: BLE001
            pass
        try:
            value = page.evaluate(
                """() => {
                    try {
                        const injector = angular.element(document.body).injector();
                        const service = injector.get('inputDataSrv');
                        if (service && service.session_id) return String(service.session_id);
                    } catch (e) { /* 忽略：Angular 未就绪或服务名变了 */ }
                    if (window.inputDataSrv && window.inputDataSrv.session_id) return String(window.inputDataSrv.session_id);
                    return null;
                }"""
            )
            return str(value) if value else None
        except Exception:  # noqa: BLE001
            return None

    def _find_first_visible(
        self,
        page: Page,
        selectors: Iterable[str],
        timeout_seconds: int,
        stop_event: Event,
        log_callback: LogCallback | None = None,
    ) -> tuple[Locator, str]:
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            if stop_event.is_set():
                raise MetascapeAutomationError(tr("用户已停止任务。"))

            if self._check_maintenance(page, log_callback):
                page.wait_for_timeout(3000)
                continue

            for selector in selectors:
                locator = page.locator(selector).first
                try:
                    if locator.count() > 0 and locator.is_visible():
                        return locator, selector
                except Exception as exc:  # noqa: BLE001
                    last_error = exc

            page.wait_for_timeout(1000)

        raise MetascapeAutomationError(
            tr("无法定位页面元素，候选选择器：{selectors}，最后错误：{error}").format(
                selectors=list(selectors), error=last_error
            )
        )

    def _check_maintenance(self, page: Page, log_callback: LogCallback | None) -> bool:
        """维护页出现时记录一次提示并返回 True，调用方应延迟后重试。"""
        if not self._is_maintenance_page(page):
            self._maintenance_started_at = None
            return False
        if not self._maintenance_warned:
            self._maintenance_warned = True
            self._maintenance_started_at = time.monotonic()
            self._log(log_callback, tr(MAINTENANCE_MESSAGE))
        if (
            self._maintenance_started_at is not None
            and time.monotonic() - self._maintenance_started_at > MAINTENANCE_MAX_WAIT_SECONDS
        ):
            raise MetascapeAutomationError(tr("Metascape 维护中，已等待超过 {minutes} 分钟仍未恢复，请稍后再试。").format(
                minutes=int(MAINTENANCE_MAX_WAIT_SECONDS // 60)
            ))
        return True

    def _recover_from_maintenance(self, page: Page, stop_event: Event, log_callback: LogCallback | None) -> None:
        """从维护页恢复：先快速重载几次（假警报），再退回较慢的轮询，超时则报明确的维护错误。"""
        for attempt in range(1, MAINTENANCE_FAST_RELOAD_ATTEMPTS + 1):
            if stop_event.is_set():
                raise MetascapeAutomationError(tr("用户已停止任务。"))
            page.wait_for_timeout(MAINTENANCE_FAST_RELOAD_INTERVAL_MS)
            try:
                page.reload(wait_until="domcontentloaded", timeout=60_000)
            except Exception:  # noqa: BLE001
                continue
            if not self._is_maintenance_page(page):
                self._log(
                    log_callback,
                    tr("Metascape 已从维护页恢复（第 {attempt} 次重载），继续处理。").format(attempt=attempt),
                )
                self._maintenance_started_at = None
                return
            self._log(log_callback, tr("仍停在维护页（第 {attempt}/{total} 次重载）。").format(
                attempt=attempt, total=MAINTENANCE_FAST_RELOAD_ATTEMPTS
            ))

        deadline = time.monotonic() + MAINTENANCE_MAX_WAIT_SECONDS
        while self._is_maintenance_page(page) and time.monotonic() < deadline:
            if stop_event.is_set():
                raise MetascapeAutomationError(tr("用户已停止任务。"))
            page.wait_for_timeout(10_000)
            try:
                page.reload(wait_until="domcontentloaded", timeout=60_000)
            except Exception:  # noqa: BLE001
                continue
        if self._is_maintenance_page(page):
            raise MetascapeAutomationError(tr("Metascape 维护中，已等待超过 {minutes} 分钟仍未恢复，请稍后再试。").format(
                minutes=int(MAINTENANCE_MAX_WAIT_SECONDS // 60)
            ))
        self._log(log_callback, tr("Metascape 已从维护页恢复，继续处理。"))
        self._maintenance_started_at = None

    @staticmethod
    def _is_maintenance_page(page: Page) -> bool:
        """识别 Metascape 维护页：此时页面结构完全不同，任何选择器等待都会白等。

        注意：app.js 里的 ``health_check_pull`` 一旦请求失败，页面也会跳到 maintenance.html，
        所以这里既可能是真维护，也可能是该健康检查的偶发失败（假维护，刷新即恢复）。
        """
        try:
            if "maintenance" in page.url.lower():
                return True
            return "site maintenance" in page.title().lower()
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _describe_page(page: Page) -> str:
        """记录当前页面 URL 与标题，便于判断是否被跳到维护页。"""
        try:
            return tr("当前页面：{url}（标题：{title}）").format(url=page.url, title=page.title() or "-")
        except Exception:  # noqa: BLE001
            return tr("当前页面：{url}").format(url="?")

    def _set_textbox_value(
        self,
        page: Page,
        textbox: Locator,
        gene_text: str,
        log_callback: LogCallback | None = None,
        selector: str | None = None,
    ) -> None:
        """把基因列表写入输入框。

        直接给 ``value`` 赋值再派发 ``input``/``change``（Angular 的 ``ng-model`` 会随事件更新，
        由此让 Step 3 的按钮按 ``ng-show="inputData.textbox"`` 正常出现），避免大列表下
        Playwright ``fill()`` 动作性检查卡满 30 秒的问题；仅在赋值失败时回退到 ``fill()``。
        """
        gene_count = gene_text.count("\n") + 1 if gene_text else 0
        target_selector = selector or self.TEXTBOX_SELECTOR
        self._log(
            log_callback,
            tr("写入基因列表：{count} 个基因（{chars} 字符）。").format(count=gene_count, chars=len(gene_text)),
        )

        try:
            page.evaluate(
                """([selector, text]) => {
                    const el = document.querySelector(selector);
                    if (!el) { throw new Error('textarea not found'); }
                    el.focus();
                    el.value = text;
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }""",
                [target_selector, gene_text],
            )
            written = textbox.input_value(timeout=10_000)
            if written == gene_text:
                return
            self._log(
                log_callback,
                tr("直接赋值未完全写入（{written}/{expected} 字符），回退 fill()。").format(
                    written=len(written), expected=len(gene_text)
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self._log(log_callback, tr("直接赋值失败，回退 fill()：{error}").format(error=exc))

        # 兜底：优先短暂 fill（大列表下会超时），超时后确认文本框内容是否已写入
        try:
            textbox.fill(gene_text, timeout=10_000)
            return
        except Exception as fill_exc:  # noqa: BLE001
            try:
                written = textbox.input_value(timeout=5_000)
            except Exception:  # noqa: BLE001
                written = ""
            if written == gene_text:
                self._log(log_callback, tr("fill() 超时但基因列表已写入，继续执行。"))
                return
            raise MetascapeAutomationError(
                tr("基因列表写入失败：{error}").format(error=fill_exc)
            ) from fill_exc

    def _wait_for_editable_textbox(
        self,
        page: Page,
        textbox: Locator,
        timeout_seconds: int,
        stop_event: Event,
    ) -> None:
        """Wait until Angular has removed the initial read-only state."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if stop_event.is_set():
                raise MetascapeAutomationError(tr("用户已停止任务。"))
            if self._check_maintenance(page, None):
                page.wait_for_timeout(3000)
                continue
            try:
                readonly = textbox.get_attribute("readonly")
                aria_disabled = textbox.get_attribute("aria-disabled")
                if textbox.is_visible() and textbox.is_enabled() and readonly is None and aria_disabled != "true":
                    return
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(250)
        raise MetascapeAutomationError(tr("基因输入框仍不可编辑，请检查 Metascape 页面是否加载完成。"))

    def _wait_for_clickable(
        self,
        page: Page,
        selectors: Iterable[str],
        timeout_seconds: int,
        stop_event: Event,
        log_callback: LogCallback | None = None,
    ) -> tuple[Locator, str]:
        """Wait until one of the selectors is visible and enabled, then return it."""
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None

        # 每 500ms 轮询一次：候选选择器只要可见且可点击就立即返回
        while time.monotonic() < deadline:
            if stop_event.is_set():
                raise MetascapeAutomationError(tr("用户已停止任务。"))

            for selector in selectors:
                locator = page.locator(selector).first
                try:
                    if locator.count() > 0 and locator.is_visible() and locator.is_enabled():
                        return locator, selector
                except Exception as exc:  # noqa: BLE001
                    last_error = exc

            # 兜底：textarea 有值但 Angular 尚未 flush ng-show 时，补派 input 事件触发 digest
            try:
                textarea = page.locator("textarea").first
                if textarea.count() > 0 and textarea.is_visible() and textarea.input_value():
                    textarea.dispatch_event("input")
            except Exception:  # noqa: BLE001
                pass

            page.wait_for_timeout(500)

        raise MetascapeAutomationError(
            tr("无法定位页面元素，候选选择器：{selectors}，最后错误：{error}").format(
                selectors=list(selectors), error=last_error
            )
        )

    def _wait_for_enabled(
        self,
        page: Page,
        selectors: Iterable[str],
        timeout_seconds: int,
        stop_event: Event,
    ) -> tuple[Locator, str]:
        """Wait until one of the selectors becomes visible and enabled."""
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None

        # 每 500ms 轮询：等待按钮从 disabled 变为 enabled（如 Submit 后的 ID 转换）
        while time.monotonic() < deadline:
            if stop_event.is_set():
                raise MetascapeAutomationError(tr("用户已停止任务。"))

            for selector in selectors:
                locator = page.locator(selector).first
                try:
                    if locator.count() > 0 and locator.is_visible() and locator.is_enabled():
                        return locator, selector
                except Exception as exc:  # noqa: BLE001
                    last_error = exc

            page.wait_for_timeout(500)

        raise MetascapeAutomationError(
            tr("无法定位页面元素，候选选择器：{selectors}，最后错误：{error}").format(
                selectors=list(selectors), error=last_error
            )
        )

    def _download_from_report_url(
        self,
        report_page: Page,
        report_selector_hint: str,
        download_type: DownloadType,
        download_path: Path,
        stop_event: Event,
        log_callback: LogCallback | None,
        timeout_seconds: int = 180,
    ) -> bool:
        """不依赖页面可见性，直接用 ``get_file?session_id=…`` 取结果文件。

        并发跑多个报告页时，浏览器渲染线程会被重页面占满，Playwright 的"可见/稳定"判定
        会一直等下去（实测卡满几分钟）；而下载链接的 URL 模式是固定的，直接请求即可。
        成功返回 True；连 session_id 都拿不到时返回 False，交给调用方的可见性兜底路径。
        """
        file_names = (
            ["metascape_result.xlsx", "metascape_result.xls"]
            if download_type is DownloadType.XLSX_ONLY
            else ["all.zip", "metascape_result.zip"]
        )
        deadline = time.monotonic() + timeout_seconds
        session_id = self._read_session_id(report_page)
        if not session_id:
            self._log(log_callback, tr("未在报告页读到 session_id，改用页面可见元素下载。"))
            return False

        last_outcome = "-"
        while time.monotonic() < deadline:
            if stop_event.is_set():
                raise MetascapeAutomationError(tr("用户已停止任务。"))

            for file_name in file_names:
                # 必须用站点根路径 /gp_server/：报告页 URL 是 /gp/index.html#/...，
                # 用相对路径会拼成 /gp/gp_server/...，实测返回 404 HTML，整整白等 180 秒
                url = self._report_file_url(report_page, session_id, file_name)
                try:
                    response = report_page.request.get(url, timeout=120_000)
                except Exception as exc:  # noqa: BLE001
                    self._log(log_callback, tr("直接取结果文件失败：{error}").format(error=str(exc)[:120]))
                    continue
                body = response.body() if response.status < 400 else b""
                last_outcome = f"{url} -> HTTP {response.status}, {len(body)} bytes, head={body[:8]!r}"
                if response.status >= 400 or len(body) < 512 or body[:2] != b"PK":
                    continue
                download_path.parent.mkdir(parents=True, exist_ok=True)
                download_path.write_bytes(body)
                self._log(
                    log_callback,
                    tr("已直接按 session_id 取到结果文件：{name}（{size} 字节）").format(
                        name=file_name, size=len(body)
                    ),
                )
                return True

            report_page.wait_for_timeout(3000)

        self._log(log_callback, tr("直接取结果文件超时，改用页面可见元素下载。"))
        self._log(log_callback, tr("最后一次请求：{detail}").format(detail=last_outcome))
        return False

    @staticmethod
    def _report_file_url(report_page: Page, session_id: str, file_name: str) -> str:
        """结果文件地址：优先用页面上真实下载链接的 href（Excel 链接常被隐藏，但 href 在），否则按站点根路径拼。"""
        try:
            href = report_page.evaluate(
                """(name) => {
                    const a = [...document.querySelectorAll('a[href*="get_file"]')]
                        .find(x => (x.getAttribute('href') || '').includes('file_name=' + name));
                    return a ? a.href : null;
                }""",
                file_name,
            )
            if href:
                return str(href)
        except Exception:  # noqa: BLE001
            pass
        return urljoin(
            report_page.url,
            f"/gp_server/get_file?session_id={session_id}&file_name={file_name}&rename=true",
        )

    def _try_direct_download(self, page: Page, locator: Locator, download_path: Path) -> bool:
        # 读取入口 href；无有效链接（如 javascript: 占位）则交由调用方走下载事件
        try:
            href = locator.get_attribute("href")
        except Exception:  # noqa: BLE001
            href = None
        if not href or href.startswith("javascript:"):
            return False

        # 直接用页面上下文请求该链接，成功即返回 True
        try:
            self._save_download_from_href(page, locator, download_path, href)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _save_download_from_href(self, page: Page, locator: Locator, download_path: Path, href: str | None = None) -> None:
        # 未显式传入 href 时从元素上读取
        target_href = href
        if target_href is None:
            try:
                target_href = locator.get_attribute("href")
            except Exception:  # noqa: BLE001
                target_href = None
        if not target_href:
            raise MetascapeAutomationError(tr("下载入口未提供可直接获取的链接。"))

        # 解析相对链接并发起请求，非 2xx 报错，成功后直接写入磁盘
        resolved = urljoin(page.url, target_href)
        response = page.request.get(resolved, timeout=30_000)
        if response.status >= 400:
            raise MetascapeAutomationError(tr("直接获取下载文件失败：HTTP {status}").format(status=response.status))
        download_path.write_bytes(response.body())

    @staticmethod
    def _find_excel_in_directory(directory: Path) -> Path:
        # 递归收集解压目录下的全部 xlsx
        candidates = sorted(directory.rglob("*.xlsx"))
        if not candidates:
            raise MetascapeAutomationError(tr("压缩包中未找到任何 xlsx 文件。"))

        # 文件名含 enrichment 的优先，其余按名称排序
        prioritized = sorted(
            candidates,
            key=lambda path: (0 if "enrichment" in path.name.lower() else 1, path.name.lower()),
        )
        return prioritized[0]

    @staticmethod
    def _log(log_callback: LogCallback | None, message: str) -> None:
        if log_callback:
            log_callback(message)

    def _read_progress_percent(self, page: Page) -> int | None:
        # 依次尝试各进度条选择器，取第一个可见的
        for selector in self.PROGRESSBAR_SELECTORS:
            locator = page.locator(selector).first
            try:
                if locator.count() == 0 or not locator.is_visible():
                    continue

                # 优先从 style 的 width:NN% 解析百分比
                style = locator.get_attribute("style") or ""
                match = re.search(r"width:\s*([\d.]+)%", style)
                if match:
                    return max(0, min(100, round(float(match.group(1)))))

                # 无 width 时退化为从文本中提取数字
                text = locator.inner_text().strip()
                match = re.search(r"(\d{1,3})", text)
                if match:
                    return max(0, min(100, int(match.group(1))))
            except Exception:  # noqa: BLE001
                continue
        return None

    @staticmethod
    def _report_progress(
        callback: AnalysisProgressCallback | None,
        percent: int | None,
        message: str,
    ) -> None:
        if callback:
            callback(percent, message)

    def _click_with_retry(
        self,
        page: Page,
        selector: str,
        label: str,
        stop_event: Event,
        log_callback: LogCallback | None,
        timeout_ms: int = 8_000,
        max_attempts: int = 2,
    ) -> None:
        last_error: Exception | None = None
        label = tr(label)

        for attempt in range(1, max_attempts + 1):
            if stop_event.is_set():
                raise MetascapeAutomationError(tr("用户已停止任务。"))

            self._log(
                log_callback,
                tr("{label} 点击尝试 {attempt}/{max_attempts}。").format(
                    label=label, attempt=attempt, max_attempts=max_attempts
                ),
            )

            # 首选 DOM 点击：不经鼠标输入派发，实测比 locator.click() 稳定得多
            dom_result = self._dom_click(page, selector, label, timeout_ms)
            if dom_result is None:
                self._log(log_callback, tr("{label} DOM 点击成功。").format(label=label))
                return
            self._log(
                log_callback,
                tr("{label} DOM 点击未生效（{reason}），改用鼠标点击。").format(label=label, reason=dom_result),
            )

            # 常规点击：等可见、可启用，滚动到视口后点击
            locator = page.locator(selector).first
            try:
                expect(locator).to_be_visible(timeout=timeout_ms)
                expect(locator).to_be_enabled(timeout=timeout_ms)
                locator.scroll_into_view_if_needed(timeout=timeout_ms)
                locator.click(timeout=timeout_ms)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                self._log(
                    log_callback,
                    tr("{label} 常规点击失败，第 {attempt} 次：{error}").format(
                        label=label, attempt=attempt, error=exc
                    ),
                )

            # 元素仍禁用时不做 force/JS（会绕过 Angular 状态机），等待后重试
            try:
                if not locator.is_enabled():
                    page.wait_for_timeout(1000 * attempt)
                    continue
            except Exception:  # noqa: BLE001
                pass

            # 元素可点击但常规点击失败：force click 兜底
            try:
                locator.scroll_into_view_if_needed(timeout=timeout_ms)
                locator.click(timeout=timeout_ms, force=True)
                self._log(
                    log_callback,
                    tr("{label} 第 {attempt} 次使用 force click 成功。").format(label=label, attempt=attempt),
                )
                return
            except Exception as force_exc:  # noqa: BLE001
                last_error = force_exc
                self._log(
                    log_callback,
                    tr("{label} force click 失败，第 {attempt} 次：{error}").format(
                        label=label, attempt=attempt, error=force_exc
                    ),
                )

            # 鼠标点击全部失败：再走一次 DOM 点击（此时页面可能刚好恢复响应）
            dom_result = self._dom_click(page, selector, label, timeout_ms)
            if dom_result is None:
                self._log(log_callback, tr("{label} 第 {attempt} 次使用 DOM 点击成功。").format(label=label, attempt=attempt))
                return
            page.wait_for_timeout(1000 * attempt)

        self._log_failure_diagnostics(page, label, log_callback)
        raise MetascapeAutomationError(
            tr("{label} 点击失败，已重试 {max_attempts} 次。最后错误：{error}").format(
                label=label, max_attempts=max_attempts, error=last_error
            )
        )

    def _dom_click(self, page: Page, selector: str, label: str, timeout_ms: int) -> str | None:
        """在页面里直接触发 click。成功返回 None，失败返回原因字符串。

        注意：``page.evaluate`` 没有 timeout 参数（传了会直接 TypeError），这里的超时由
        外层 ``_click_with_retry`` 的鼠标点击兜底保证；文本输入框没有文本标签，跳过即可。
        """
        visible_label = self.DOM_CLICK_LABELS.get(selector)
        if not visible_label:
            return "no-label-mapping"
        try:
            result = page.evaluate(self.DOM_CLICK_SCRIPT, visible_label)
        except Exception as exc:  # noqa: BLE001
            return f"evaluate-failed: {str(exc)[:80]}"
        if not isinstance(result, dict):
            return "unexpected-result"
        if result.get("ok"):
            return None
        return str(result.get("reason") or "unknown")

    def _log_failure_diagnostics(self, page: Page, label: str, log_callback: LogCallback | None) -> None:
        """点击最终失败时记录现场（URL/标题/命中测试/截图），便于下次直接定位。"""
        try:
            diagnostics = page.evaluate(
                """() => {
                    const buttons = [...document.querySelectorAll('button, [role=button], a')]
                        .filter(x => (x.textContent || '').trim())
                        .map(x => {
                            const r = x.getBoundingClientRect();
                            return {
                                text: (x.textContent || '').trim().slice(0, 40),
                                disabled: !!x.disabled,
                                aria: x.getAttribute('aria-disabled'),
                                visible: !!(r.width && r.height),
                                cls: (x.className || '').toString().slice(0, 60),
                            };
                        });
                    const ta = document.querySelector("textarea[placeholder*='Gene' i]");
                    // 命中测试：按钮中心点究竟被哪个元素挡住（定位"被覆盖"类问题）
                    let hit = null;
                    const target = [...document.querySelectorAll('button, [role=button], a')]
                        .find(x => (x.textContent || '').trim() === 'Submit');
                    if (target) {
                        const r = target.getBoundingClientRect();
                        const el = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                        hit = el ? (el.tagName + '.' + (el.className || '').toString().slice(0, 40)) : null;
                    }
                    return {url: location.href, title: document.title, textboxLen: ta ? ta.value.length : null,
                            hitAtSubmitCenter: hit, buttons: buttons.slice(0, 12)};
                }"""
            )
            self._log(log_callback, tr("点击失败现场：URL={url}，标题={title}，输入框长度={length}，按钮中心命中={hit}。").format(
                url=diagnostics.get("url"),
                title=diagnostics.get("title"),
                length=diagnostics.get("textboxLen"),
                hit=diagnostics.get("hitAtSubmitCenter"),
            ))
            for button in diagnostics.get("buttons", []):
                self._log(
                    log_callback,
                    tr("可点元素：{text}（disabled={disabled}, aria={aria}, visible={visible}）").format(
                        text=button.get("text"), disabled=button.get("disabled"), aria=button.get("aria"), visible=button.get("visible")
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            self._log(log_callback, tr("记录点击失败现场时出错：{error}").format(error=exc))

        try:
            screenshot = get_logs_dir() / f"click_failure_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            page.screenshot(path=str(screenshot))
            self._log(log_callback, tr("已保存失败截图：{path}").format(path=screenshot))
        except Exception:  # noqa: BLE001
            pass
