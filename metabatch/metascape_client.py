from __future__ import annotations

import re
import time
import zipfile
from urllib.parse import urljoin
from pathlib import Path
from threading import Event
from typing import Callable, Iterable

from playwright.sync_api import Browser, Locator, Page, Playwright, TimeoutError as PlaywrightTimeoutError, expect, sync_playwright

from .models import DownloadType, DownloadedArtifacts

LogCallback = Callable[[str], None]
AnalysisProgressCallback = Callable[[int | None, str], None]


class MetascapeAutomationError(Exception):
    """Raised when Metascape automation cannot finish successfully."""


class MetascapeClient:
    HOME_URL = "https://metascape.org/gp/index.html"
    TEXTBOX_SELECTORS = [
        "textarea[placeholder*='Gene' i]",
        "textarea[aria-label*='Gene' i]",
        "textarea",
    ]
    EXPRESS_TAB_SELECTORS = [
        "text=/Express Analysis/i",
        "button:has-text('Express Analysis')",
        "[role='tab']:has-text('Express Analysis')",
    ]
    SUBMIT_SELECTORS = [
        "button:has-text('Submit')",
        "button:has-text('Express Analysis')",
        "input[type='submit']",
        "[role='button']:has-text('Submit')",
        "text=/Submit/i",
    ]
    XLSX_DOWNLOAD_SELECTORS = [
        "a:has-text('Excel')",
        "button:has-text('Excel')",
        "text=/Excel/i",
        "[href*='.xlsx']",
    ]
    ZIP_DOWNLOAD_SELECTORS = [
        "a:has-text('All Files in Zip')",
        "button:has-text('All Files in Zip')",
        "text=/All Files in Zip/i",
        "[href*='.zip']",
        "text=/zip/i",
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

    def __init__(self, headless: bool = True, proxy_url: str | None = None) -> None:
        self._headless = headless
        self._proxy_url = proxy_url
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    def __enter__(self) -> "MetascapeClient":
        self._playwright = sync_playwright().start()
        launch_kwargs = {"headless": self._headless}
        if self._proxy_url:
            launch_kwargs["proxy"] = {"server": self._proxy_url}
        self._browser = self._playwright.chromium.launch(**launch_kwargs)
        return self

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
            raise MetascapeAutomationError("浏览器尚未启动。")

        context = self._browser.new_context(accept_downloads=True)
        page = context.new_page()
        try:
            self._log(log_callback, f"打开 Metascape：{self.HOME_URL}")
            page.goto(self.HOME_URL, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            page.wait_for_load_state("networkidle", timeout=30_000)

            self._maybe_click_first(page, self.EXPRESS_TAB_SELECTORS, stop_event, log_callback, "Express Analysis 页签")
            textbox, textbox_selector = self._find_first_visible(
                page,
                self.TEXTBOX_SELECTORS,
                timeout_seconds=60,
                stop_event=stop_event,
            )
            self._log(log_callback, f"已定位基因输入框：{textbox_selector}")
            self._click_with_retry(
                page,
                textbox_selector,
                "基因输入框",
                stop_event,
                log_callback,
                timeout_ms=15_000,
            )
            textbox.fill(gene_text)

            submit_button, submit_selector = self._find_first_visible(
                page,
                self.SUBMIT_SELECTORS,
                timeout_seconds=60,
                stop_event=stop_event,
            )
            self._log(log_callback, f"已定位提交按钮：{submit_selector}")
            self._click_with_retry(
                page,
                submit_selector,
                "Submit 按钮",
                stop_event,
                log_callback,
            )
            self._report_progress(analysis_progress_callback, 5, "已提交基因列表，等待进入分析流程")

            express_button, express_selector = self._find_first_visible(
                page,
                ["button:has-text('Express Analysis')", "text=/Express Analysis/i"],
                timeout_seconds=60,
                stop_event=stop_event,
            )
            self._log(log_callback, f"已定位 Express Analysis 按钮：{express_selector}")
            self._click_with_retry(
                page,
                express_selector,
                "Express Analysis 按钮",
                stop_event,
                log_callback,
            )
            self._report_progress(analysis_progress_callback, 10, "已启动 Express Analysis")

            self._log(log_callback, "等待 Analysis Report Page 按钮与 Metascape 分析进度。")
            report_button, report_selector = self._wait_for_report_button(
                page,
                timeout_seconds=timeout_seconds,
                stop_event=stop_event,
                progress_callback=analysis_progress_callback,
            )
            self._log(log_callback, f"已定位 Analysis Report Page 按钮：{report_selector}")

            report_page = self._open_report_page(context, page, report_selector, stop_event, log_callback)
            self._report_progress(analysis_progress_callback, 90, "已进入 Analysis Report Page，等待下载入口")

            selectors = (
                self.XLSX_DOWNLOAD_SELECTORS
                if download_type is DownloadType.XLSX_ONLY
                else self.ZIP_DOWNLOAD_SELECTORS
            )
            download_target, download_selector = self._find_first_visible(
                report_page,
                selectors,
                timeout_seconds=timeout_seconds,
                stop_event=stop_event,
            )
            self._log(log_callback, f"已定位下载入口：{download_selector}")
            download_path.parent.mkdir(parents=True, exist_ok=True)
            if not self._try_direct_download(report_page, download_target, download_path):
                with report_page.expect_download(timeout=timeout_seconds * 1000) as download_info:
                    self._click_with_retry(
                        report_page,
                        download_selector,
                        "下载入口",
                        stop_event,
                        log_callback,
                        timeout_ms=20_000,
                    )
                download = download_info.value
                try:
                    download.save_as(download_path)
                except Exception:  # noqa: BLE001
                    self._save_download_from_href(report_page, download_target, download_path)
            self._log(log_callback, f"下载完成：{download_path}")
            self._report_progress(analysis_progress_callback, 100, "Metascape 下载完成")

            if download_type is DownloadType.XLSX_ONLY:
                return DownloadedArtifacts(download_path=download_path, excel_path=download_path)

            if extracted_dir is None:
                raise MetascapeAutomationError("Zip 模式缺少解压目录参数。")
            extracted_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(download_path, "r") as archive:
                archive.extractall(extracted_dir)
            excel_path = self._find_excel_in_directory(extracted_dir)
            self._log(log_callback, f"已从压缩包定位 Excel：{excel_path}")
            return DownloadedArtifacts(
                download_path=download_path,
                excel_path=excel_path,
                extracted_dir=extracted_dir,
            )
        except PlaywrightTimeoutError as exc:
            raise MetascapeAutomationError(
                f"等待 Metascape 页面元素超时，请检查网络或页面选择器。原始错误：{exc}"
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

        while time.monotonic() < deadline:
            if stop_event.is_set():
                raise MetascapeAutomationError("用户已停止任务。")

            percent = self._read_progress_percent(page)
            if percent is not None and percent != last_percent:
                last_percent = percent
                self._report_progress(progress_callback, percent, f"Metascape 正在分析：{percent}%")

            for selector in self.REPORT_PAGE_SELECTORS:
                locator = page.locator(selector).first
                try:
                    if locator.count() > 0 and locator.is_visible() and locator.is_enabled():
                        return locator, selector
                except Exception:  # noqa: BLE001
                    continue

            page.wait_for_timeout(1000)

        raise MetascapeAutomationError("等待 Analysis Report Page 按钮超时。")

    def _open_report_page(
        self,
        context,
        page: Page,
        report_selector: str,
        stop_event: Event,
        log_callback: LogCallback | None,
    ) -> Page:
        try:
            with context.expect_page(timeout=5_000) as page_info:
                self._click_with_retry(
                    page,
                    report_selector,
                    "Analysis Report Page 按钮",
                    stop_event,
                    log_callback,
                    timeout_ms=20_000,
                )
            report_page = page_info.value
            report_page.wait_for_load_state("domcontentloaded", timeout=30_000)
            return report_page
        except PlaywrightTimeoutError:
            self._click_with_retry(
                page,
                report_selector,
                "Analysis Report Page 按钮",
                stop_event,
                log_callback,
                timeout_ms=20_000,
            )
            page.wait_for_load_state("domcontentloaded", timeout=30_000)
            return page

    def _find_first_visible(
        self,
        page: Page,
        selectors: Iterable[str],
        timeout_seconds: int,
        stop_event: Event,
    ) -> tuple[Locator, str]:
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            if stop_event.is_set():
                raise MetascapeAutomationError("用户已停止任务。")

            for selector in selectors:
                locator = page.locator(selector).first
                try:
                    if locator.count() > 0 and locator.is_visible():
                        return locator, selector
                except Exception as exc:  # noqa: BLE001
                    last_error = exc

            page.wait_for_timeout(1000)

        raise MetascapeAutomationError(
            f"无法定位页面元素，候选选择器：{list(selectors)}，最后错误：{last_error}"
        )

    def _maybe_click_first(
        self,
        page: Page,
        selectors: Iterable[str],
        stop_event: Event,
        log_callback: LogCallback | None,
        label: str,
    ) -> None:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if locator.count() > 0 and locator.is_visible():
                    self._click_with_retry(page, selector, label, stop_event, log_callback, timeout_ms=10_000, max_attempts=2)
                    return
            except Exception:  # noqa: BLE001
                continue

    def _try_direct_download(self, page: Page, locator: Locator, download_path: Path) -> bool:
        href = None
        try:
            href = locator.get_attribute("href")
        except Exception:  # noqa: BLE001
            href = None

        if not href or href.startswith("javascript:"):
            return False

        try:
            self._save_download_from_href(page, locator, download_path, href)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _save_download_from_href(self, page: Page, locator: Locator, download_path: Path, href: str | None = None) -> None:
        target_href = href
        if target_href is None:
            try:
                target_href = locator.get_attribute("href")
            except Exception:  # noqa: BLE001
                target_href = None
        if not target_href:
            raise MetascapeAutomationError("下载入口未提供可直接获取的链接。")

        resolved = urljoin(page.url, target_href)
        response = page.request.get(resolved, timeout=30_000)
        if response.status >= 400:
            raise MetascapeAutomationError(f"直接获取下载文件失败：HTTP {response.status}")
        download_path.write_bytes(response.body())

    @staticmethod
    def _find_excel_in_directory(directory: Path) -> Path:
        candidates = sorted(directory.rglob("*.xlsx"))
        if not candidates:
            raise MetascapeAutomationError("压缩包中未找到任何 xlsx 文件。")

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
        for selector in self.PROGRESSBAR_SELECTORS:
            locator = page.locator(selector).first
            try:
                if locator.count() == 0 or not locator.is_visible():
                    continue
                style = locator.get_attribute("style") or ""
                match = re.search(r"width:\s*([\d.]+)%", style)
                if match:
                    return max(0, min(100, round(float(match.group(1)))))
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
        timeout_ms: int = 30_000,
        max_attempts: int = 3,
    ) -> None:
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            if stop_event.is_set():
                raise MetascapeAutomationError("用户已停止任务。")

            locator = page.locator(selector).first
            try:
                self._log(log_callback, f"{label} 点击尝试 {attempt}/{max_attempts}。")
                expect(locator).to_be_visible(timeout=timeout_ms)
                expect(locator).to_be_enabled(timeout=timeout_ms)
                locator.scroll_into_view_if_needed(timeout=timeout_ms)
                locator.click(timeout=timeout_ms)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                self._log(log_callback, f"{label} 常规点击失败，第 {attempt} 次：{exc}")
                try:
                    locator.scroll_into_view_if_needed(timeout=timeout_ms)
                    locator.click(timeout=timeout_ms, force=True)
                    self._log(log_callback, f"{label} 第 {attempt} 次使用 force click 成功。")
                    return
                except Exception as force_exc:  # noqa: BLE001
                    last_error = force_exc
                    self._log(log_callback, f"{label} force click 失败，第 {attempt} 次：{force_exc}")
                    try:
                        page.evaluate("(el) => el.click()", locator.element_handle(timeout=timeout_ms))
                        self._log(log_callback, f"{label} 第 {attempt} 次使用 JS click 成功。")
                        return
                    except Exception as js_exc:  # noqa: BLE001
                        last_error = js_exc
                        self._log(log_callback, f"{label} JS click 失败，第 {attempt} 次：{js_exc}")
                        page.wait_for_timeout(1000 * attempt)

        raise MetascapeAutomationError(f"{label} 点击失败，已重试 {max_attempts} 次。最后错误：{last_error}")
