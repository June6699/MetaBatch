from __future__ import annotations

import csv
import os
import random
import time
import zipfile
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from queue import SimpleQueue
from typing import Callable

from openpyxl import load_workbook

from .excel_processor import ExcelProcessingError, finalize_workbook_layout, translate_workbook
from .gene_reader import (
    MESSAGE_TOO_MANY_GENES_REASON,
    SKIPPED_REASON_EXISTING,
    SKIPPED_REASON_EXISTING_MESSAGE,
    GeneReadError,
    discover_gene_files,
    exceeds_gene_limit,
    read_gene_list,
    too_many_genes_message,
)
from .i18n import tr
from .logging_utils import RunLogger, make_log_path
from .metascape_client import MetascapeAutomationError, MetascapeClient, proxy_is_reachable
from .models import AppConfig, ConnectionMode, DownloadType, TaskResult, TaskStatus, translation_target_by_code
from .paths import OutputPaths, build_output_paths
from .translator import OpenAICompatibleTranslator, TranslationError

LogCallback = Callable[[int | None, str], None]
ProgressCallback = Callable[[int, int, str, int | None, str | None, int | None, str | None, int | None, str | None], None]

# 连续失败达到该数量即停止提交新文件（已完成的保留在磁盘上，重跑会自动续上）
MAX_CONSECUTIVE_FAILURES = 20
# 翻译预检与单个文件翻译使用的短文本
PREFLIGHT_TEXT = "cell cycle"

# 系统饱和保护：浏览器渲染进程被"饿"住时，Playwright 的鼠标输入会拿不到 ack 而超时
# （Playwright 维护者称之为 system saturation）。系统 CPU 高于该阈值时，新文件先在队列里等一等。
SYSTEM_LOAD_THRESHOLD = 70.0
SYSTEM_LOAD_POLL_SECONDS = 2.0
SYSTEM_LOAD_MAX_WAIT_SECONDS = 120.0
# 每个 Chromium 实例大约要占用 2 个逻辑核；Playwright 社区建议 worker 数 ≈ 逻辑核数 / 2
LOGICAL_CPUS_PER_BROWSER = 2
MAX_RECOMMENDED_CONCURRENCY = 8

# 翻译阶段状态（写入 metabatch_summary.csv 的 translation_status 列）
TRANSLATION_STATUS_TRANSLATED = "translated"
TRANSLATION_STATUS_PARTIAL = "partial"
TRANSLATION_STATUS_FAILED = "failed"
TRANSLATION_STATUS_PAUSED = "paused"
TRANSLATION_STATUS_DISABLED = "disabled"


def _logical_cpu_count() -> int:
    try:
        import psutil  # type: ignore

        return max(1, psutil.cpu_count(logical=True) or 1)
    except Exception:  # noqa: BLE001
        return max(1, os.cpu_count() or 1)


def recommended_concurrency() -> int:
    """按逻辑核数给出并发上限：每个 Chromium 约需 2 个逻辑核。

    Playwright 维护者在 #26739 里把"元素明明在页面上却等到超时"归结为系统饱和，
    社区结论是 worker 数 ≈ 逻辑核数的一半（16 核机器上 5 个并发浏览器已接近饱和）。
    """
    return max(1, min(MAX_RECOMMENDED_CONCURRENCY, _logical_cpu_count() // LOGICAL_CPUS_PER_BROWSER))


def effective_concurrency(requested: int) -> int:
    """用户填写的并发数与推荐上限取小值。"""
    return max(1, min(int(requested), recommended_concurrency()))


def _system_cpu_percent() -> float | None:
    try:
        import psutil  # type: ignore

        return float(psutil.cpu_percent(interval=None))
    except Exception:  # noqa: BLE001
        return None


def wait_for_system_idle(
    stop_event: Event | None = None,
    threshold: float = SYSTEM_LOAD_THRESHOLD,
    max_wait_seconds: float = SYSTEM_LOAD_MAX_WAIT_SECONDS,
    log_callback: Callable[[str], None] | None = None,
) -> bool:
    """系统 CPU 过高时先等待，降低"浏览器被饿住导致点击超时"的概率。

    返回 True 表示等到负载回落或本就空闲；返回 False 表示等到超时（照常继续）。
    """
    first = _system_cpu_percent()
    if first is None or first < threshold:
        return True

    if log_callback is not None:
        log_callback(
            tr("系统 CPU 占用 {percent}% 偏高，先等待负载回落再继续（避免浏览器被饿住导致点击超时）。").format(
                percent=int(first)
            )
        )

    deadline = time.monotonic() + max_wait_seconds
    while time.monotonic() < deadline:
        if stop_event is not None and stop_event.is_set():
            return False
        time.sleep(SYSTEM_LOAD_POLL_SECONDS)
        current = _system_cpu_percent()
        if current is None or current < threshold:
            if log_callback is not None:
                log_callback(tr("系统负载已回落，继续处理。"))
            return True
    return False


@dataclass(slots=True)
class ScanPlan:
    """运行前预扫描结果：待处理与两类跳过的文件。"""

    pending: list[Path] = field(default_factory=list)
    existing: list[tuple[Path, str]] = field(default_factory=list)  # (文件, 跳过说明)
    oversized: list[tuple[Path, str]] = field(default_factory=list)  # (文件, 跳过说明)
    gene_lists: dict[Path, list[str]] = field(default_factory=dict)
    unreadable: list[tuple[Path, str]] = field(default_factory=list)  # (文件, 读取失败原因)

    @property
    def pending_count(self) -> int:
        return len(self.pending)


@dataclass(slots=True)
class AnnotatedGenes:
    """预扫描读到的基因列表：genes 为 None 表示该文件被跳过/读取失败。"""

    genes: list[str] | None
    count: int
    skip_reason: str = ""


@dataclass(slots=True)
class GeneFileRecord:
    """每个输入文件在本次运行中的最终处置，用于生成结果清单。"""

    source_file: Path
    gene_count: int
    status: TaskStatus
    skipped_reason: str = ""
    translation_status: str = ""
    message: str = ""


def scan_gene_files(
    config: AppConfig,
    gene_files: list[Path],
    target_header: str,
    probe_existing: Callable[[Path], str | None] | None = None,
) -> tuple[ScanPlan, list[AnnotatedGenes]]:
    """把基因文件分成「待处理 / 已有结果 / 基因过多 / 读取失败」。

    基因列表在这里只读一次，命中待处理的文件把结果直接交给 worker 复用，
    避免"预扫描 + 正式处理"读两遍文件。``probe_existing`` 用于注入"已有结果判定"，
    默认使用真实的 xlsx 完成度检查。
    """
    probe = probe_existing or _default_existing_result_probe(config, target_header)
    plan = ScanPlan()
    annotated: list[AnnotatedGenes] = []
    limit = config.normalized_max_genes_per_file()
    column = config.normalized_input_column()
    output_paths_map = _build_output_paths_map(config, gene_files)

    for gene_file in gene_files:
        download_path = output_paths_map[gene_file].download_path
        reason = probe(download_path)
        if reason is not None:
            plan.existing.append((gene_file, reason))
            # 已有结果的文件不再读取基因列表，数量记为未知（-1）
            annotated.append(AnnotatedGenes(genes=None, count=-1, skip_reason=reason))
            continue

        try:
            genes = read_gene_list(gene_file, column)
        except (GeneReadError, OSError, ValueError, zipfile.BadZipFile) as exc:
            plan.unreadable.append((gene_file, str(exc)))
            annotated.append(AnnotatedGenes(genes=None, count=0, skip_reason=str(exc)))
            continue

        if exceeds_gene_limit(len(genes), limit):
            message = too_many_genes_message(len(genes), int(limit))
            plan.oversized.append((gene_file, message))
            annotated.append(AnnotatedGenes(genes=None, count=len(genes), skip_reason=message))
            continue

        plan.pending.append(gene_file)
        plan.gene_lists[gene_file] = genes
        annotated.append(AnnotatedGenes(genes=genes, count=len(genes)))

    return plan, annotated


def _default_existing_result_probe(config: AppConfig, target_header: str) -> Callable[[Path], str | None]:
    translate_expected = config.enable_translation

    def _probe(download_path: Path) -> str | None:
        return _existing_result_reason(download_path, translate_expected, target_header)

    return _probe


class WorkflowController:
    def run(
        self,
        config: AppConfig,
        stop_event: Event,
        log_callback: LogCallback,
        progress_callback: ProgressCallback,
    ) -> list[TaskResult]:
        overall_start_time = time.perf_counter()
        config.output_dir.mkdir(parents=True, exist_ok=True)
        gene_files = discover_gene_files(config.input_dir, config.file_pattern)
        if not gene_files:
            raise ValueError(tr("输入目录中未找到受支持的基因列表文件。"))

        run_logger = RunLogger(make_log_path())
        target_header = translation_target_by_code(config.translation_target).column_header
        translator = self._build_translator(config)
        try:
            file_log = _compose_file_log_callback(log_callback, run_logger)
            file_log(None, tr("日志文件：{path}").format(path=run_logger.path))
            max_workers = effective_concurrency(config.concurrency)
            if max_workers < max(1, int(config.concurrency)):
                file_log(
                    None,
                    tr("并发数已按 CPU 核数下调：{requested} → {applied}（{cores} 逻辑核，每个浏览器约需 2 个）。").format(
                        requested=config.concurrency, applied=max_workers, cores=_logical_cpu_count()
                    ),
                )
            file_log(None, tr("并发数：{count}").format(count=max_workers))

            results: list[TaskResult] = []
            plan, annotated = scan_gene_files(config, gene_files, target_header)
            total = plan.pending_count
            # 预扫描已读过的基因列表按文件保存，直接交给对应 worker 复用
            preloaded: dict[Path, list[str]] = dict(plan.gene_lists)
            # 预扫描已拿到待处理/超限文件的基因数（已有结果的文件记为未知 -1）
            gene_counts = {gene_file: item.count for gene_file, item in zip(gene_files, annotated, strict=True)}
            # 结果清单：每个输入文件的基因数与最终处置（含被跳过的文件）
            file_records: dict[Path, GeneFileRecord] = {
                gene_file: GeneFileRecord(
                    source_file=gene_file,
                    gene_count=len(genes),
                    # 占位，处理完成后由 worker 覆盖；没轮到处理（被停止/连续失败中止）的文件保持"中途停止"，
                    # 不能默认成功，否则清单会把没跑的文件算成"已做"
                    status=TaskStatus.STOPPED,
                    message=tr(REPORT_NOT_PROCESSED),
                )
                for gene_file, genes in preloaded.items()
            }
            for gene_file, reason in plan.unreadable:
                file_log(None, tr("预扫描读取失败，已跳过：{name}（{error}）").format(name=gene_file.name, error=reason))

            # 预扫描报告：已有结果与超限文件直接记入汇总，本次只跑待处理文件
            file_log(
                None,
                tr("预扫描完成：待处理 {pending} 个，已有结果跳过 {existing} 个，因基因过多跳过 {oversized} 个。").format(
                    pending=plan.pending_count, existing=len(plan.existing), oversized=len(plan.oversized)
                ),
            )
            for gene_file, reason in plan.existing:
                log_item = tr("跳过已有结果：{name}（{reason}）").format(name=gene_file.name, reason=reason)
                file_log(None, log_item)
                results.append(
                    TaskResult(
                        source_file=gene_file,
                        status=TaskStatus.SKIPPED,
                        download_path=None,
                        translated_path=None,
                        message=reason,
                        elapsed_seconds=0.0,
                        skipped_reason=SKIPPED_REASON_EXISTING,
                    )
                )
                file_records[gene_file] = GeneFileRecord(
                    source_file=gene_file,
                    gene_count=gene_counts.get(gene_file, -1),
                    status=TaskStatus.SKIPPED,
                    skipped_reason=SKIPPED_REASON_EXISTING,
                    message=reason,
                )
            for gene_file, reason in plan.oversized:
                log_item = tr("跳过基因过多的列表：{name}（{reason}）").format(name=gene_file.name, reason=reason)
                file_log(None, log_item)
                results.append(
                    TaskResult(
                        source_file=gene_file,
                        status=TaskStatus.SKIPPED,
                        download_path=None,
                        translated_path=None,
                        message=reason,
                        elapsed_seconds=0.0,
                        skipped_reason=MESSAGE_TOO_MANY_GENES_REASON,
                    )
                )
                file_records[gene_file] = GeneFileRecord(
                    source_file=gene_file,
                    gene_count=gene_counts.get(gene_file, -1),
                    status=TaskStatus.SKIPPED,
                    skipped_reason=MESSAGE_TOO_MANY_GENES_REASON,
                    message=reason,
                )
            for gene_file, reason in plan.unreadable:
                results.append(
                    TaskResult(
                        source_file=gene_file,
                        status=TaskStatus.FAILED,
                        download_path=None,
                        translated_path=None,
                        message=reason,
                        elapsed_seconds=0.0,
                    )
                )
                file_records[gene_file] = GeneFileRecord(
                    source_file=gene_file,
                    gene_count=0,
                    status=TaskStatus.FAILED,
                    message=reason,
                )

            # 翻译预检：只做一次；失败则本次运行暂停翻译，Metascape 照常继续
            translation_active = config.enable_translation
            if translation_active:
                if not self._preflight_translation(translator, log_callback=file_log):
                    translation_active = False
                else:
                    file_log(
                        None,
                        tr("翻译接口预检通过：{url}（模型 {model}）。").format(
                            url=getattr(translator, "_url", None) or config.api_base_url or "-",
                            model=getattr(translator, "_model", None) or config.api_model or "-",
                        ),
                    )

            # 代理可用性预检：代理没启动时浏览器行为会变得莫名其妙（能打开直连站点但整体很慢）
            metascape_connection_mode = config.metascape_connection_mode
            proxy_url = config.proxy_url_for(metascape_connection_mode)
            if proxy_url and not proxy_is_reachable(proxy_url):
                file_log(
                    None,
                    tr("代理 {url} 无法连接（端口没有监听），本次 Metascape 改走直连；请检查代理软件是否已启动。").format(
                        url=proxy_url
                    ),
                )
                metascape_connection_mode = ConnectionMode.DIRECT

            progress_callback(
                0,
                total,
                tr("准备开始处理"),
                0,
                tr("等待启动"),
                0 if translation_active else None,
                tr("等待翻译") if translation_active else tr("翻译已关闭"),
                None,
                None,
            )
            file_log(None, tr("待处理文件数：{count}").format(count=total))

            pending_map = preloaded

            if total > 0:
                output_paths_map = _build_output_paths_map(config, plan.pending)
                worker_ids: SimpleQueue[int] = SimpleQueue()
                for worker_id in range(1, max_workers + 1):
                    worker_ids.put(worker_id)
                submitted = 0
                consecutive_failures = 0
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    pending: dict[Future[TaskResult], tuple[Path, int]] = {}
                    while submitted < total or pending:
                        while (
                            submitted < total
                            and len(pending) < max_workers
                            and not stop_event.is_set()
                            and consecutive_failures < MAX_CONSECUTIVE_FAILURES
                        ):
                            gene_file = plan.pending[submitted]
                            worker_id = worker_ids.get()
                            future = executor.submit(
                                self._process_single_file,
                                index=submitted + 1,
                                total=total,
                                gene_file=gene_file,
                                worker_id=worker_id,
                                config=config,
                                translator=translator if translation_active else None,
                                stop_event=stop_event,
                                log_callback=file_log,
                                progress_callback=progress_callback,
                                output_paths=output_paths_map[gene_file],
                                genes=pending_map[gene_file],
                                gene_count=gene_counts[gene_file],
                                file_records=file_records,
                                metascape_connection_mode=metascape_connection_mode,
                            )
                            pending[future] = (gene_file, worker_id)
                            submitted += 1

                        if not pending:
                            break

                        done, _ = wait(pending.keys(), return_when=FIRST_COMPLETED)
                        for future in done:
                            gene_file, worker_id = pending.pop(future)
                            worker_ids.put(worker_id)
                            try:
                                result = future.result()
                            except Exception as exc:  # noqa: BLE001
                                consecutive_failures += 1
                                results.append(
                                    TaskResult(
                                        source_file=gene_file,
                                        status=TaskStatus.FAILED,
                                        download_path=None,
                                        translated_path=None,
                                        message=str(exc),
                                        elapsed_seconds=0,
                                        metascape_elapsed_seconds=None,
                                        translation_elapsed_seconds=None,
                                    )
                                )
                                record = file_records.get(gene_file)
                                if record is not None:
                                    record.status = TaskStatus.FAILED
                                    record.message = str(exc)
                                file_log(
                                    worker_id,
                                    tr("处理失败：{name}，原因：{error}").format(
                                        name=gene_file.relative_to(config.input_dir), error=exc
                                    ),
                                )
                            else:
                                results.append(result)
                                record = file_records.get(gene_file)
                                if record is not None:
                                    record.gene_count = result.gene_count
                                    record.status = result.status
                                    record.skipped_reason = result.skipped_reason
                                    record.translation_status = result.translation_status
                                    record.message = result.message
                                if result.status in {TaskStatus.SUCCESS, TaskStatus.PARTIAL}:
                                    consecutive_failures = 0

                        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES and not stop_event.is_set():
                            remaining = total - submitted
                            if remaining > 0:
                                file_log(
                                    None,
                                    tr("已连续失败 {count} 个文件，停止提交剩余 {remaining} 个（多为网络或接口配置问题）；修好后再次开始会自动从未完成的文件继续。").format(
                                        count=MAX_CONSECUTIVE_FAILURES, remaining=remaining
                                    ),
                                )
                            # 不直接 break：继续回收已在跑的文件，让它们的结果（停止/失败）写进清单
                            stop_event.set()

            self._write_summary(
                config.output_dir,
                results,
                {gene_file: record.gene_count for gene_file, record in file_records.items()},
            )
            # 结果清单：覆盖全部输入文件（含被跳过的），写到用户指定的输出目录根下
            report_records = [
                file_records.get(gene_file) or GeneFileRecord(source_file=gene_file, gene_count=-1, status=TaskStatus.FAILED)
                for gene_file in gene_files
            ]
            report_path = self._write_gene_report(config.output_dir, report_records, config.input_dir)
            file_log(None, tr("结果清单已写出：{path}").format(path=report_path))
            file_log(
                None,
                tr("清单统计：共 {total} 个文件，已完成 {done} 个，其中已翻译 {translated} 个；已有结果 {existing} 个；因基因过多跳过 {oversized} 个；中途停止 {stopped} 个；失败 {failed} 个。").format(
                    total=len(report_records),
                    done=sum(1 for record in report_records if _metascape_state(record.status, record.skipped_reason) == tr(REPORT_DONE)),
                    translated=sum(1 for record in report_records if _translation_state(record.translation_status, record.status) == tr(REPORT_TRANSLATED)),
                    existing=sum(1 for record in report_records if record.skipped_reason == SKIPPED_REASON_EXISTING),
                    oversized=sum(1 for record in report_records if record.skipped_reason == MESSAGE_TOO_MANY_GENES_REASON),
                    stopped=sum(1 for record in report_records if record.status is TaskStatus.STOPPED),
                    failed=sum(1 for record in report_records if record.status is TaskStatus.FAILED),
                ),
            )
            overall_elapsed = time.perf_counter() - overall_start_time
            file_log(None, tr("全部任务完成，总用时 {duration}。").format(duration=self._format_seconds(overall_elapsed)))
            if not translation_active:
                file_log(None, tr("本次运行未翻译 Excel（翻译接口不可用或被关闭），可用 translate_boundary_metascape.py 之后补翻译。"))
            progress_callback(
                total,
                total,
                tr("处理结束"),
                100,
                tr("全部任务已结束"),
                100 if translation_active else None,
                tr("全部翻译流程已结束") if translation_active else tr("翻译已关闭"),
                None,
                None,
            )
            return results
        finally:
            run_logger.close()

    def _process_single_file(
        self,
        index: int,
        total: int,
        gene_file: Path,
        worker_id: int,
        config: AppConfig,
        translator: OpenAICompatibleTranslator | None,
        stop_event: Event,
        log_callback: LogCallback,
        progress_callback: ProgressCallback,
        output_paths: OutputPaths,
        genes: list[str],
        gene_count: int,
        file_records: dict[Path, GeneFileRecord] | None = None,
        metascape_connection_mode: ConnectionMode | None = None,
    ) -> TaskResult:
        # 由 run() 传入：代理预检失败时这里已被改成直连；未传时按配置走
        if metascape_connection_mode is None:
            metascape_connection_mode = config.metascape_connection_mode
        relative_name = gene_file.relative_to(config.input_dir)
        start_time = time.perf_counter()
        metascape_elapsed: float | None = None
        translation_elapsed: float | None = None
        downloaded_path: Path | None = None
        translated_path: Path | None = None
        translation_status = TRANSLATION_STATUS_PAUSED if translator is None else ""
        translation_message = "" if translator is not None else tr("翻译接口不可用或被关闭，本次未翻译")
        target_header = translation_target_by_code(config.translation_target).column_header
        textbox_limit = config.normalized_max_genes_per_file()

        if output_paths.download_path.exists():
            message = tr("检测到已有结果文件，已跳过：{path}").format(path=output_paths.download_path)
            log_callback(worker_id, f"[{index}/{total}] {message}")
            return TaskResult(
                source_file=gene_file,
                status=TaskStatus.SKIPPED,
                download_path=output_paths.download_path,
                translated_path=_translated_output_for_skip(output_paths, translator is not None),
                message=message,
                elapsed_seconds=0,
                metascape_elapsed_seconds=None,
                translation_elapsed_seconds=None,
                skipped_reason=SKIPPED_REASON_EXISTING,
                gene_count=gene_count,
            )

        # 二次阈值判定：预扫描后又出现大列表（或预扫描被关闭）时仍不提交给 Metascape
        if exceeds_gene_limit(gene_count, textbox_limit):
            message = too_many_genes_message(gene_count, int(textbox_limit))
            log_callback(worker_id, f"[{index}/{total}] {message}")
            progress_callback(
                index,
                total,
                tr("跳过 {name}").format(name=gene_file.name),
                None,
                message,
                None,
                tr("翻译已关闭") if translator is None else tr("等待翻译"),
                worker_id,
                str(relative_name),
            )
            return TaskResult(
                source_file=gene_file,
                status=TaskStatus.SKIPPED,
                download_path=None,
                translated_path=None,
                message=message,
                elapsed_seconds=0,
                metascape_elapsed_seconds=None,
                translation_elapsed_seconds=None,
                skipped_reason=MESSAGE_TOO_MANY_GENES_REASON,
                gene_count=gene_count,
            )

        try:
            if not genes:
                raise GeneReadError(tr("文件中未读取到任何有效基因。"))

            log_callback(worker_id, f"[{index}/{total}] " + tr("开始处理：{name}").format(name=relative_name))
            log_callback(
                worker_id,
                f"[{index}/{total}] " + tr("读取基因完成：{count} 个基因。").format(count=gene_count),
            )
            # 系统饱和时先等一等：浏览器被饿住会让鼠标输入拿不到 ack（Playwright 的 system saturation）
            wait_for_system_idle(
                stop_event,
                log_callback=lambda message: log_callback(worker_id, f"[{index}/{total}] {message}"),
            )
            metascape_start = time.perf_counter()
            log_callback(worker_id, f"[{index}/{total}] " + tr("Metascape 开始。"))

            with MetascapeClient(
                headless=config.headless,
                proxy_url=config.proxy_url_for(metascape_connection_mode),
            ) as client:
                artifacts = client.process_gene_list(
                    download_path=output_paths.download_path,
                    gene_text="\n".join(genes),
                    download_type=config.download_type,
                    timeout_seconds=config.timeout_seconds,
                    stop_event=stop_event,
                    log_callback=lambda message: log_callback(worker_id, message),
                    extracted_dir=output_paths.extracted_dir,
                    analysis_progress_callback=lambda percent, stage: progress_callback(
                        index - 1,
                        total,
                        tr("正在处理 {name}").format(name=relative_name),
                        percent,
                        stage,
                        0 if translator is not None else None,
                        tr("翻译已关闭") if translator is None else tr("等待翻译"),
                        worker_id,
                        str(relative_name),
                    ),
                )

            metascape_elapsed = time.perf_counter() - metascape_start
            downloaded_path = artifacts.download_path
            log_callback(
                worker_id,
                f"[{index}/{total}] " + tr("Metascape 完成，用时 {duration}。").format(duration=self._format_seconds(metascape_elapsed)),
            )

            if stop_event.is_set():
                raise ExcelProcessingError(tr("用户已停止任务。"))

            if translator is not None:
                if artifacts.excel_path is not None:
                    try:
                        translation_start = time.perf_counter()
                        log_callback(worker_id, f"[{index}/{total}] " + tr("翻译开始。"))
                        translated_path = translate_workbook(
                            artifacts.excel_path,
                            translator,
                            stop_event=stop_event,
                            target_header=target_header,
                            progress_callback=lambda current, total_rows: progress_callback(
                                index - 1,
                                total,
                                tr("翻译 {name}: {current}/{total}").format(
                                    name=relative_name, current=current, total=total_rows
                                ),
                                100,
                                tr("Metascape 分析完成，正在翻译 Excel"),
                                0 if total_rows == 0 else int((current / total_rows) * 100),
                                tr("翻译进行中：{current}/{total}").format(current=current, total=total_rows),
                                worker_id,
                                str(relative_name),
                            ),
                        )
                        translation_elapsed = time.perf_counter() - translation_start
                        translation_status = TRANSLATION_STATUS_TRANSLATED
                        log_callback(
                            worker_id,
                            f"[{index}/{total}] "
                            + tr("翻译完成：{path}，用时 {duration}。").format(
                                path=translated_path, duration=self._format_seconds(translation_elapsed)
                            ),
                        )
                    except (ExcelProcessingError, TranslationError, ValueError) as exc:
                        translated_path = None
                        translation_elapsed = 0.0
                        translation_status = TRANSLATION_STATUS_FAILED
                        translation_message = str(exc)
                        log_callback(
                            worker_id,
                            f"[{index}/{total}] " + tr("翻译失败，已跳过：{error}").format(error=exc),
                        )
                        progress_callback(
                            index - 1,
                            total,
                            tr("翻译失败，已跳过 {name}").format(name=gene_file.name),
                            100,
                            tr("Metascape 已完成，翻译已跳过"),
                            0,
                            tr("翻译失败：{error}").format(error=exc),
                            worker_id,
                            str(relative_name),
                        )
                else:
                    translation_status = TRANSLATION_STATUS_PARTIAL
                    translation_message = tr("结果中没有可翻译的 Excel 文件")
            else:
                if artifacts.excel_path is not None and artifacts.excel_path.exists():
                    try:
                        finalize_workbook_layout(artifacts.excel_path, sheet_name="Enrichment", auto_fit_headers=["Description"])
                    except ExcelProcessingError as exc:
                        log_callback(
                            worker_id,
                            f"[{index}/{total}] " + tr("Excel 后处理跳过：{error}").format(error=exc),
                        )
                log_callback(worker_id, f"[{index}/{total}] " + tr("翻译已关闭，跳过翻译阶段。"))
                translated_path = artifacts.excel_path

            elapsed = time.perf_counter() - start_time
            log_callback(
                worker_id,
                f"[{index}/{total}] " + tr("当前文件处理完成，总用时 {duration}。").format(duration=self._format_seconds(elapsed)),
            )
            progress_callback(
                index,
                total,
                tr("已完成 {name}").format(name=gene_file.name),
                100,
                tr("当前文件处理完成"),
                100 if translator is not None else None,
                _translation_status_label(translation_status),
                worker_id,
                str(relative_name),
            )
            self._pause_between_files(config, stop_event)
            failed_translation = translation_status == TRANSLATION_STATUS_FAILED
            return TaskResult(
                source_file=gene_file,
                status=TaskStatus.PARTIAL if failed_translation else TaskStatus.SUCCESS,
                download_path=downloaded_path,
                translated_path=translated_path,
                message=tr("翻译失败：{error}").format(error=translation_message) if failed_translation else tr("处理成功"),
                elapsed_seconds=elapsed,
                metascape_elapsed_seconds=metascape_elapsed,
                translation_elapsed_seconds=translation_elapsed,
                translation_status=translation_status,
                translation_message=translation_message,
                gene_count=gene_count,
            )
        except (
            GeneReadError,
            MetascapeAutomationError,
            ExcelProcessingError,
            TranslationError,
            ValueError,
        ) as exc:
            elapsed = time.perf_counter() - start_time
            status = TaskStatus.STOPPED if stop_event.is_set() else TaskStatus.FAILED
            if isinstance(exc, ExcelProcessingError) and metascape_elapsed is not None:
                log_callback(
                    worker_id,
                    f"[{index}/{total}] "
                    + tr("翻译阶段失败：{error}。Metascape 已完成，用时 {duration}。").format(
                        error=exc, duration=self._format_seconds(metascape_elapsed)
                    ),
                )
            else:
                log_callback(worker_id, f"[{index}/{total}] " + tr("处理失败：{error}").format(error=exc))
            progress_callback(
                index,
                total,
                tr("失败 {name}").format(name=gene_file.name),
                100 if metascape_elapsed is not None else None,
                str(exc),
                None if translator is None else 0,
                str(exc) if translator is not None else tr("翻译已关闭"),
                worker_id,
                str(relative_name),
            )
            if metascape_elapsed is not None:
                self._pause_between_files(config, stop_event)
            return TaskResult(
                source_file=gene_file,
                status=status,
                download_path=downloaded_path,
                translated_path=translated_path,
                message=str(exc),
                elapsed_seconds=elapsed,
                metascape_elapsed_seconds=metascape_elapsed,
                translation_elapsed_seconds=translation_elapsed,
                translation_status=translation_status,
                translation_message=translation_message,
                gene_count=gene_count,
            )

    @staticmethod
    def _preflight_translation(
        translator: OpenAICompatibleTranslator | None,
        log_callback: LogCallback | None = None,
    ) -> bool:
        """运行前只做一次最小翻译请求；失败即本次运行暂停翻译。"""
        if translator is None:
            return False
        try:
            translator.translate(PREFLIGHT_TEXT)
            return True
        except Exception as exc:  # noqa: BLE001
            if log_callback is not None:
                log_callback(
                    None,
                    tr("翻译接口预检失败：{error}。本次运行暂停翻译，先继续下载 Metascape 结果；修好接口后可用 translate_boundary_metascape.py 补翻译。").format(
                        error=exc
                    ),
                )
            return False

    @staticmethod
    def _format_seconds(seconds: float | None) -> str:
        if seconds is None:
            return "-"
        return f"{seconds:.1f} {tr('秒')}"

    @staticmethod
    def _pause_between_files(config: AppConfig, stop_event: Event) -> None:
        # mission 要求每个文件之间随机休息，降低被 Metascape 限流的风险；等待期间可被停止事件打断。
        min_delay = max(0, config.min_delay_seconds)
        max_delay = max(min_delay, config.max_delay_seconds)
        if max_delay <= 0:
            return
        stop_event.wait(random.uniform(min_delay, max_delay))

    @staticmethod
    def _write_summary(
        output_dir: Path,
        results: list[TaskResult],
        gene_counts: dict[Path, int] | None = None,
    ) -> None:
        """写出结果清单：每个输入文件的基因数、是否做了 Metascape、是否翻译了。"""
        summary_path = output_dir / "metabatch_summary.csv"
        counts = gene_counts or {}
        with summary_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
            writer.writeheader()
            for item in results:
                row = _summary_row(item)
                if row["gene_count"] == "":
                    # 预扫描直接跳过的文件（已有结果/基因过多）没有走 worker，这里补上预扫描读到的数量
                    fallback = counts.get(item.source_file, "")
                    row["gene_count"] = "" if fallback in {"", -1} else fallback
                writer.writerow(row)

    @staticmethod
    def _write_gene_report(output_dir: Path, records: list[GeneFileRecord], input_dir: Path) -> Path:
        """把全部输入文件（含被跳过的）汇总成 CSV，写到用户指定的输出目录根下。"""
        report_path = output_dir / "metabatch_gene_report.csv"
        with report_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=GENE_REPORT_FIELDS)
            writer.writeheader()
            for record in records:
                try:
                    relative = record.source_file.relative_to(input_dir).as_posix()
                except ValueError:
                    relative = record.source_file.as_posix()
                writer.writerow(
                    {
                        "source_file": str(record.source_file),
                        "relative_path": relative,
                        "file_name": record.source_file.name,
                        "gene_count": "" if record.gene_count <= 0 else record.gene_count,
                        "metascape": _metascape_state(record.status, record.skipped_reason),
                        "translated": _translation_state(record.translation_status, record.status),
                        "status": record.status.value,
                        "skipped_reason": record.skipped_reason,
                        "translation_status": record.translation_status,
                        "message": record.message,
                    }
                )
        return report_path

    @staticmethod
    def _build_translator(config: AppConfig) -> OpenAICompatibleTranslator | None:
        if not config.enable_translation:
            return None
        return OpenAICompatibleTranslator(
            base_url=config.api_base_url,
            api_key=config.api_key,
            model=config.api_model,
            api_format=config.api_format,
            auth_field=config.auth_field,
            target_language=translation_target_by_code(config.translation_target).prompt_name,
            request_interval_seconds=config.request_interval_seconds,
            max_retries=config.translation_max_retries,
            proxy_url=config.proxy_url_for(config.translation_connection_mode),
        )


def _existing_result_reason(
    download_path: Path,
    translate_expected: bool,
    target_header: str,
) -> str | None:
    """已有输出是否算"完成"：数据文件存在且（启用翻译时）已含目标语言列。"""
    if not download_path.exists():
        return None
    if download_path.suffix.lower() != ".xlsx":
        return tr(SKIPPED_REASON_EXISTING_MESSAGE).format(path=download_path)

    header_column = target_header if translate_expected else None
    if _is_complete_result_workbook(download_path, header_column):
        return tr(SKIPPED_REASON_EXISTING_MESSAGE).format(path=download_path)

    # 存在但没跑完（缺少 Enrichment 表，或启用翻译却还没有目标语言列）→ 重跑该文件
    return None


def _is_complete_result_workbook(path: Path, target_header: str | None) -> bool:
    """xlsx 是否已有 Enrichment 表；给了 target_header 时还要求该列已存在。"""
    try:
        workbook = load_workbook(path, read_only=True)
    except Exception:  # noqa: BLE001
        return False
    try:
        if "Enrichment" not in workbook.sheetnames:
            return False
        if target_header is None:
            return True
        sheet = workbook["Enrichment"]
        for column_index in range(1, sheet.max_column + 1):
            if str(sheet.cell(row=1, column=column_index).value).strip() == target_header:
                return True
        return False
    finally:
        workbook.close()


def _translation_status_label(status: str) -> str:
    if status == TRANSLATION_STATUS_TRANSLATED:
        return tr("翻译完成")
    if status == TRANSLATION_STATUS_PARTIAL:
        return tr("翻译已关闭")
    if status == TRANSLATION_STATUS_FAILED:
        return tr("翻译失败")
    if status == TRANSLATION_STATUS_DISABLED:
        return tr("翻译已关闭")
    return tr("翻译暂停")


SUMMARY_FIELDS = [
    "source_file",
    "status",
    "gene_count",
    "download_path",
    "translated_path",
    "metascape_elapsed_seconds",
    "translation_elapsed_seconds",
    "elapsed_seconds",
    "skipped_reason",
    "translation_status",
    "translation_message",
    "message",
]

GENE_REPORT_FIELDS = [
    "source_file",
    "relative_path",
    "file_name",
    "gene_count",
    "metascape",
    "translated",
    "status",
    "skipped_reason",
    "translation_status",
    "message",
]

# 结果清单里的中文口径（按界面语言翻译）
REPORT_DONE = "已做"
REPORT_NOT_DONE = "未做"
REPORT_PARTIAL = "部分完成"
REPORT_EXISTING = "已有结果"
REPORT_TRANSLATED = "已翻译"
REPORT_NOT_TRANSLATED = "未翻译"
REPORT_TRANSLATION_PAUSED = "已暂停"
REPORT_TRANSLATION_FAILED = "翻译失败"
REPORT_TRANSLATION_DISABLED = "未启用"
REPORT_UNKNOWN = "未知"
REPORT_NOT_PROCESSED = "本次运行未处理该文件"


def _summary_row(item: TaskResult) -> dict[str, object]:
    return {
        "source_file": str(item.source_file),
        "status": item.status.value,
        "gene_count": "" if item.gene_count <= 0 else item.gene_count,
        "download_path": "" if item.download_path is None else str(item.download_path),
        "translated_path": "" if item.translated_path is None else str(item.translated_path),
        "metascape_elapsed_seconds": "" if item.metascape_elapsed_seconds is None else f"{item.metascape_elapsed_seconds:.3f}",
        "translation_elapsed_seconds": "" if item.translation_elapsed_seconds is None else f"{item.translation_elapsed_seconds:.3f}",
        "elapsed_seconds": f"{item.elapsed_seconds:.3f}",
        "skipped_reason": item.skipped_reason,
        "translation_status": item.translation_status,
        "translation_message": item.translation_message,
        "message": item.message,
    }


def _metascape_state(status: TaskStatus, skipped_reason: str) -> str:
    """是否真的向 Metascape 提交并拿到了结果。

    STOPPED 表示中途被停止：不能算"已做"（没有结果文件），标为"部分完成"。
    """
    if status is TaskStatus.SKIPPED:
        if skipped_reason == SKIPPED_REASON_EXISTING:
            return tr(REPORT_EXISTING)
        return tr(REPORT_NOT_DONE)
    if status is TaskStatus.STOPPED:
        return tr(REPORT_PARTIAL)
    if status in {TaskStatus.SUCCESS, TaskStatus.PARTIAL}:
        return tr(REPORT_DONE)
    return tr(REPORT_NOT_DONE)


def _translation_state(translation_status: str, status: TaskStatus) -> str:
    if translation_status == TRANSLATION_STATUS_TRANSLATED:
        return tr(REPORT_TRANSLATED)
    if translation_status == TRANSLATION_STATUS_FAILED:
        return tr(REPORT_TRANSLATION_FAILED)
    if translation_status == TRANSLATION_STATUS_PAUSED:
        return tr(REPORT_TRANSLATION_PAUSED)
    if translation_status == TRANSLATION_STATUS_DISABLED:
        return tr(REPORT_TRANSLATION_DISABLED)
    if translation_status == TRANSLATION_STATUS_PARTIAL:
        return tr(REPORT_NOT_TRANSLATED)
    if status is TaskStatus.SUCCESS:
        return tr(REPORT_NOT_TRANSLATED)
    return tr(REPORT_UNKNOWN)


def _compose_file_log_callback(gui_log: LogCallback, run_logger: RunLogger) -> LogCallback:
    def _log(worker_id: int | None, message: str) -> None:
        prefix = f"[Worker {worker_id}] " if worker_id is not None else "[Main] "
        gui_log(worker_id, run_logger.log(prefix + message))

    return _log


def _build_output_paths_map(config: AppConfig, gene_files: list[Path]) -> dict[Path, OutputPaths]:
    stem_occurrences = Counter(
        (file.relative_to(config.input_dir).parent, file.stem) for file in gene_files
    )
    return {
        file: build_output_paths(
            config.input_dir,
            config.output_dir,
            file,
            config.download_type,
            disambiguate_suffix=stem_occurrences[(file.relative_to(config.input_dir).parent, file.stem)] > 1,
        )
        for file in gene_files
    }


def _translated_output_for_skip(output_paths: OutputPaths, enable_translation: bool) -> Path | None:
    if not enable_translation:
        return None
    return output_paths.download_path if output_paths.download_path.suffix == ".xlsx" else None
