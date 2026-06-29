from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Callable

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from .translator import Translator

RowProgressCallback = Callable[[int, int], None]


class ExcelProcessingError(Exception):
    """Raised when the downloaded workbook cannot be processed."""


def translate_workbook(
    workbook_path: Path,
    translator: Translator,
    stop_event: Event | None = None,
    progress_callback: RowProgressCallback | None = None,
) -> Path:
    workbook = load_workbook(workbook_path)
    try:
        if "Enrichment" not in workbook.sheetnames:
            raise ExcelProcessingError("结果文件中未找到 Enrichment 工作表，可能因为基因过少未产生富集结果。")

        sheet = workbook["Enrichment"]
        description_column = _find_header_column(sheet, "Description")
        chinese_column = _find_header_column(sheet, "中文描述", raise_if_missing=False)
        if chinese_column is not None:
            raise ExcelProcessingError("该文件已经存在“中文描述”列，已跳过以避免重复写入。")

        target_column = sheet.max_column + 1
        sheet.cell(row=1, column=target_column, value="中文描述")

        total_rows = max(sheet.max_row - 1, 0)
        for offset, row_index in enumerate(range(2, sheet.max_row + 1), start=1):
            if stop_event and stop_event.is_set():
                raise ExcelProcessingError("用户已停止任务。")

            description = sheet.cell(row=row_index, column=description_column).value
            translated = translator.translate("" if description is None else str(description))
            sheet.cell(row=row_index, column=target_column, value=translated)

            if progress_callback:
                progress_callback(offset, total_rows)

        _finalize_workbook_layout(workbook, sheet_name="Enrichment", auto_fit_headers=["Description", "中文描述"])
        workbook.save(workbook_path)
        return workbook_path
    finally:
        workbook.close()


def finalize_workbook_layout(
    workbook_path: Path,
    sheet_name: str = "Enrichment",
    auto_fit_headers: list[str] | None = None,
) -> Path:
    workbook = load_workbook(workbook_path)
    try:
        if sheet_name not in workbook.sheetnames:
            raise ExcelProcessingError("结果文件中未找到 Enrichment 工作表，可能因为基因过少未产生富集结果。")
        headers = auto_fit_headers or ["Description", "中文描述"]
        _finalize_workbook_layout(workbook, sheet_name=sheet_name, auto_fit_headers=headers)
        workbook.save(workbook_path)
        return workbook_path
    finally:
        workbook.close()


def _find_header_column(sheet, header_name: str, raise_if_missing: bool = True) -> int | None:
    for column_index in range(1, sheet.max_column + 1):
        value = sheet.cell(row=1, column=column_index).value
        if str(value).strip() == header_name:
            return column_index

    if raise_if_missing:
        raise ExcelProcessingError(f"未找到列“{header_name}”。")
    return None


def _finalize_workbook_layout(workbook, sheet_name: str, auto_fit_headers: list[str]) -> None:
    sheet = workbook[sheet_name]
    sheet_index = workbook.sheetnames.index(sheet_name)

    for worksheet in workbook.worksheets:
        worksheet.sheet_view.tabSelected = worksheet.title == sheet_name

    workbook.active = sheet_index
    if workbook.views:
        workbook_view = workbook.views[0]
        workbook_view.activeTab = sheet_index
        workbook_view.firstSheet = sheet_index

    _auto_fit_columns(sheet, auto_fit_headers)


def _auto_fit_columns(sheet, headers: list[str]) -> None:
    header_to_index: dict[str, int] = {}
    for column_index in range(1, sheet.max_column + 1):
        value = sheet.cell(row=1, column=column_index).value
        header_to_index[str(value).strip()] = column_index

    for header in headers:
        column_index = header_to_index.get(header)
        if column_index is None:
            continue

        max_length = _display_text_width(header)
        for row_index in range(2, sheet.max_row + 1):
            value = sheet.cell(row=row_index, column=column_index).value
            text = "" if value is None else str(value)
            max_length = max(max_length, _display_text_width(text))

        column_letter = get_column_letter(column_index)
        dimension = sheet.column_dimensions[column_letter]
        dimension.bestFit = True
        dimension.width = min(max(max_length + 2, 12), 80)


def _display_text_width(text: str) -> int:
    width = 0
    for char in text:
        width += 2 if ord(char) > 127 else 1
    return width
