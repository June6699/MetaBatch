from __future__ import annotations

import csv
import re
from io import StringIO
from pathlib import Path
from typing import Iterable, Sequence

import xlrd
from openpyxl import load_workbook

from .i18n import tr
from .paths import is_generated_result_path

SUPPORTED_INPUT_SUFFIXES = {".txt", ".csv", ".tsv", ".xlsx", ".xls"}


class GeneReadError(Exception):
    """Raised when a gene file cannot be interpreted."""


def discover_gene_files(input_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in input_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_INPUT_SUFFIXES
            and not _looks_like_generated_result(path)
        ],
        key=lambda item: str(item.relative_to(input_dir)).lower(),
    )


def read_gene_list(path: Path, column_selector: str | None = None) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return _normalize_values(_decode_text(path).splitlines())
    if suffix in {".csv", ".tsv"}:
        delimiter = "," if suffix == ".csv" else "\t"
        return _read_delimited(path, delimiter, column_selector)
    if suffix == ".xlsx":
        return _read_xlsx(path, column_selector)
    if suffix == ".xls":
        return _read_xls(path, column_selector)
    raise GeneReadError(tr("不支持的输入格式：{suffix}").format(suffix=path.suffix))


def _normalize_values(values: Iterable[object]) -> list[str]:
    genes: list[str] = []
    for value in values:
        text = str(value).strip()
        if text:
            genes.append(text)
    return genes


def _decode_text(path: Path) -> str:
    # Windows 下常见 UTF-8 BOM 与 GBK/GB2312 编码文件，utf-8-sig 兼容前两者之外的情况交给 gb18030 兜底。
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise GeneReadError(tr("无法解码文件内容，请将文件另存为 UTF-8 编码：{name}").format(name=path.name))


def _looks_like_generated_result(path: Path) -> bool:
    lowered = path.stem.lower()
    if lowered.endswith("_extracted") or lowered.startswith("metascape_result.") or is_generated_result_path(path):
        return True

    if path.suffix.lower() in {".xlsx", ".xls"}:
        try:
            workbook = load_workbook(path, read_only=True, data_only=True)
            try:
                return "Enrichment" in workbook.sheetnames
            finally:
                workbook.close()
        except Exception:
            return False

    return False


def _resolve_column_index(
    selector: str | None,
    header_row: Sequence[object] | None = None,
) -> tuple[int, bool]:
    if not selector:
        return 0, False

    token = selector.strip()

    if header_row is not None:
        normalized_headers = [str(cell).strip() for cell in header_row]
        try:
            return normalized_headers.index(token), True
        except ValueError:
            pass

    if token.isdigit():
        index = int(token) - 1
        if index < 0:
            raise GeneReadError(tr("列号必须从 1 开始。"))
        return index, False

    if re.fullmatch(r"[A-Za-z]+", token):
        excel_index = 0
        for char in token.upper():
            excel_index = excel_index * 26 + (ord(char) - ord("A") + 1)
        return excel_index - 1, False

    if header_row is None:
        raise GeneReadError(tr("按表头名选择列时需要可读取表头的结构化文件。"))

    normalized_headers = [str(cell).strip() for cell in header_row]
    try:
        return normalized_headers.index(token), True
    except ValueError as exc:
        raise GeneReadError(tr("未找到名为“{name}”的列。").format(name=token)) from exc


def _read_delimited(path: Path, delimiter: str, column_selector: str | None) -> list[str]:
    rows = list(csv.reader(StringIO(_decode_text(path)), delimiter=delimiter))

    if not rows:
        return []

    header_row = rows[0]
    column_index, skip_header = _resolve_column_index(column_selector, header_row)
    start_index = 1 if skip_header else 0

    values: list[str] = []
    for row in rows[start_index:]:
        if column_index >= len(row):
            continue
        values.append(row[column_index])
    return _normalize_values(values)


def _read_xlsx(path: Path, column_selector: str | None) -> list[str]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook[workbook.sheetnames[0]]
        rows = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()

    if not rows:
        return []

    header_row = list(rows[0])
    column_index, skip_header = _resolve_column_index(column_selector, header_row)
    start_index = 1 if skip_header else 0

    values: list[object] = []
    for row in rows[start_index:]:
        if column_index >= len(row):
            continue
        values.append(row[column_index])
    return _normalize_values(values)


def _read_xls(path: Path, column_selector: str | None) -> list[str]:
    workbook = xlrd.open_workbook(path.as_posix())
    sheet = workbook.sheet_by_index(0)
    if sheet.nrows == 0:
        return []

    header_row = sheet.row_values(0)
    column_index, skip_header = _resolve_column_index(column_selector, header_row)
    start_index = 1 if skip_header else 0

    values: list[object] = []
    for row_index in range(start_index, sheet.nrows):
        row_values = sheet.row_values(row_index)
        if column_index >= len(row_values):
            continue
        values.append(row_values[column_index])
    return _normalize_values(values)
