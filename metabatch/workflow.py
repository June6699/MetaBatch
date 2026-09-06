from __future__ import annotations

import csv
import random
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from threading import Event
from queue import SimpleQueue
from typing import Callable

from .excel_processor import ExcelProcessingError, finalize_workbook_layout, translate_workbook
from .gene_reader import GeneReadError, discover_gene_files, read_gene_list
from .logging_utils import RunLogger, make_log_path
from .metascape_client import MetascapeAutomationError, MetascapeClient
from .models import AppConfig, DownloadType, TaskResult, TaskStatus
from .paths import OutputPaths, build_output_paths
from .translator import OpenAICompatibleTranslator, TranslationError

LogCallback = Callable[[int | None, str], None]
ProgressCallback = Callable[[int, int, str, int | None, str | None, int | None, str | None, int | None, str | None], None]


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
        gene_files = discover_gene_files(config.input_dir)
        if not gene_files:
            raise ValueError("输入目录中未找到受支持的基因列表文件。")

        run_logger = RunLogger(make_log_path())
        translator = self._build_translator(config)
        try:
            file_log = _compose_file_log_callback(log_callback, run_logger)
            file_log(None, f"日志文件：{run_logger.path}")
            file_log(None, f"并发数：{config.concurrency}")

            results: list[TaskResult] = []
            total = len(gene_files)
            progress_callback(0, total, "准备开始处理", 0, "等待启动", 0 if config.enable_translation else None, "翻译已关闭", None, None)
            file_log(None, f"待处理文件数：{total}")

            max_workers = max(1, config.concurrency)
            output_paths_map = _build_output_paths_map(config, gene_files)
            worker_ids: SimpleQueue[int] = SimpleQueue()
            for worker_id in range(1, max_workers + 1):
                worker_ids.put(worker_id)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                pending: dict[Future[TaskResult], tuple[Path, int]] = {}
                submitted = 0
                while submitted < total or pending:
                    while submitted < total and len(pending) < max_workers and not stop_event.is_set():
                        gene_file = gene_files[submitted]
                        worker_id = worker_ids.get()
                        future = executor.submit(
                            self._process_single_file,
                            index=submitted + 1,
                            total=total,
                            gene_file=gene_file,
                            worker_id=worker_id,
                            config=config,
                            translator=translator,
                            stop_event=stop_event,
                            log_callback=file_log,
                            progress_callback=progress_callback,
                            output_paths=output_paths_map[gene_file],
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
                            results.append(future.result())
                        except Exception as exc:  # noqa: BLE001
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
                            file_log(worker_id, f"处理失败：{gene_file.relative_to(config.input_dir)}，原因：{exc}")

            self._write_summary(config.output_dir, results)
            overall_elapsed = time.perf_counter() - overall_start_time
            file_log(None, f"全部任务完成，总用时 {self._format_seconds(overall_elapsed)}。")
            progress_callback(
                total,
                total,
                "处理结束",
                100,
                "全部任务已结束",
                100 if config.enable_translation else None,
                "全部翻译流程已结束" if config.enable_translation else "翻译已关闭",
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
    ) -> TaskResult:
        relative_name = gene_file.relative_to(config.input_dir)
        start_time = time.perf_counter()
        metascape_elapsed: float | None = None
        translation_elapsed: float | None = None
        downloaded_path: Path | None = None
        translated_path: Path | None = None

        if output_paths.download_path.exists():
            message = f"检测到已有结果文件，已跳过：{output_paths.download_path}"
            log_callback(worker_id, f"[{index}/{total}] {message}")
            return TaskResult(
                source_file=gene_file,
                status=TaskStatus.SKIPPED,
                download_path=output_paths.download_path,
                translated_path=_translated_output_for_skip(output_paths, config.enable_translation),
                message=message,
                elapsed_seconds=0,
                metascape_elapsed_seconds=None,
                translation_elapsed_seconds=None,
            )

        try:
            genes = read_gene_list(gene_file, config.normalized_input_column())
            if not genes:
                raise GeneReadError("文件中未读取到任何有效基因。")

            log_callback(worker_id, f"[{index}/{total}] 开始处理：{relative_name}")
            log_callback(worker_id, f"[{index}/{total}] 读取基因完成：{len(genes)} 个基因。")
            metascape_start = time.perf_counter()
            log_callback(worker_id, f"[{index}/{total}] Metascape 开始。")

            with MetascapeClient(
                headless=config.headless,
                proxy_url=config.proxy_url_for(config.metascape_connection_mode),
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
                            f"正在处理 {relative_name}",
                            percent,
                            stage,
                            0 if config.enable_translation else None,
                            "翻译已关闭" if not config.enable_translation else "等待翻译",
                            worker_id,
                            str(relative_name),
                        ),
                )

            metascape_elapsed = time.perf_counter() - metascape_start
            downloaded_path = artifacts.download_path
            log_callback(worker_id, f"[{index}/{total}] Metascape 完成，用时 {self._format_seconds(metascape_elapsed)}。")

            if stop_event.is_set():
                raise ExcelProcessingError("用户已停止任务。")

            if config.enable_translation:
                if artifacts.excel_path is not None:
                    try:
                        translation_start = time.perf_counter()
                        log_callback(worker_id, f"[{index}/{total}] 翻译开始。")
                        translated_path = translate_workbook(
                            artifacts.excel_path,
                            translator,
                            stop_event=stop_event,
                            progress_callback=lambda current, total_rows: progress_callback(
                                index - 1,
                                total,
                                f"翻译 {relative_name}: {current}/{total_rows}",
                                100,
                                "Metascape 分析完成，正在翻译 Excel",
                                0 if total_rows == 0 else int((current / total_rows) * 100),
                                f"翻译进行中：{current}/{total_rows}",
                                worker_id,
                                str(relative_name),
                            ),
                        )
                        # translate_workbook 内部已完成列宽等布局调整，这里不再重复打开保存一次。
                        translation_elapsed = time.perf_counter() - translation_start
                        log_callback(worker_id, f"[{index}/{total}] 翻译完成：{translated_path}，用时 {self._format_seconds(translation_elapsed)}。")
                    except (ExcelProcessingError, TranslationError, ValueError) as exc:
                        translated_path = None
                        translation_elapsed = 0.0
                        log_callback(worker_id, f"[{index}/{total}] 翻译失败，已跳过：{exc}")
                        progress_callback(
                            index - 1,
                            total,
                            f"翻译失败，已跳过 {gene_file.name}",
                            100,
                            "Metascape 已完成，翻译已跳过",
                            0,
                            f"翻译失败：{exc}",
                            worker_id,
                            str(relative_name),
                        )
            else:
                if artifacts.excel_path is not None and artifacts.excel_path.exists():
                    try:
                        finalize_workbook_layout(artifacts.excel_path, sheet_name="Enrichment", auto_fit_headers=["Description"])
                    except ExcelProcessingError as exc:
                        log_callback(worker_id, f"[{index}/{total}] Excel 后处理跳过：{exc}")
                log_callback(worker_id, f"[{index}/{total}] 翻译已关闭，跳过翻译阶段。")
                translated_path = artifacts.excel_path

            elapsed = time.perf_counter() - start_time
            log_callback(worker_id, f"[{index}/{total}] 当前文件处理完成，总用时 {self._format_seconds(elapsed)}。")
            progress_callback(
                index,
                total,
                f"已完成 {gene_file.name}",
                100,
                "当前文件处理完成",
                100 if config.enable_translation else None,
                "翻译完成" if config.enable_translation else "翻译已关闭",
                worker_id,
                str(relative_name),
            )
            self._pause_between_files(config, stop_event)
            return TaskResult(
                source_file=gene_file,
                status=TaskStatus.SUCCESS,
                download_path=downloaded_path,
                translated_path=translated_path,
                message="处理成功",
                elapsed_seconds=elapsed,
                metascape_elapsed_seconds=metascape_elapsed,
                translation_elapsed_seconds=translation_elapsed,
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
                    f"[{index}/{total}] 翻译阶段失败：{exc}。Metascape 已完成，用时 {self._format_seconds(metascape_elapsed)}。"
                )
            else:
                log_callback(worker_id, f"[{index}/{total}] 处理失败：{exc}")
            progress_callback(
                index,
                total,
                f"失败 {gene_file.name}",
                100 if metascape_elapsed is not None else None,
                str(exc),
                None if not config.enable_translation else 0,
                str(exc) if config.enable_translation else "翻译已关闭",
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
            )

    @staticmethod
    def _format_seconds(seconds: float | None) -> str:
        if seconds is None:
            return "-"
        return f"{seconds:.1f} 秒"

    @staticmethod
    def _pause_between_files(config: AppConfig, stop_event: Event) -> None:
        # mission 要求每个文件之间随机休息，降低被 Metascape 限流的风险；等待期间可被停止事件打断。
        min_delay = max(0, config.min_delay_seconds)
        max_delay = max(min_delay, config.max_delay_seconds)
        if max_delay <= 0:
            return
        stop_event.wait(random.uniform(min_delay, max_delay))

    @staticmethod
    def _write_summary(output_dir: Path, results: list[TaskResult]) -> None:
        summary_path = output_dir / "metabatch_summary.csv"
        with summary_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "source_file",
                    "status",
                    "download_path",
                    "translated_path",
                    "metascape_elapsed_seconds",
                    "translation_elapsed_seconds",
                    "elapsed_seconds",
                    "message",
                ],
            )
            writer.writeheader()
            for item in results:
                writer.writerow(
                    {
                        "source_file": str(item.source_file),
                        "status": item.status.value,
                        "download_path": "" if item.download_path is None else str(item.download_path),
                        "translated_path": "" if item.translated_path is None else str(item.translated_path),
                        "metascape_elapsed_seconds": "" if item.metascape_elapsed_seconds is None else f"{item.metascape_elapsed_seconds:.3f}",
                        "translation_elapsed_seconds": "" if item.translation_elapsed_seconds is None else f"{item.translation_elapsed_seconds:.3f}",
                        "elapsed_seconds": f"{item.elapsed_seconds:.3f}",
                        "message": item.message,
                    }
                )

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
            request_interval_seconds=config.request_interval_seconds,
            max_retries=config.translation_max_retries,
            proxy_url=config.proxy_url_for(config.translation_connection_mode),
        )


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
