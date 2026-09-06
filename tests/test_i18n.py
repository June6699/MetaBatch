from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from metabatch.excel_processor import translate_workbook
from metabatch.i18n import (
    UI_LANGUAGE_EN,
    UI_LANGUAGE_ZH,
    _EN,
    get_ui_language,
    set_ui_language,
    tr,
)
from metabatch.models import (
    TRANSLATION_TARGETS,
    AppConfig,
    normalize_translation_target,
    translation_target_by_code,
)
from metabatch.translator import OpenAICompatibleTranslator
from metabatch.workflow import WorkflowController

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "metabatch"


class I18nCompletenessTests(unittest.TestCase):
    """扫描所有模块的 tr("...") 调用，确保英文词典完整、且没有 tr(f-string) 误用。"""

    def test_every_tr_call_key_is_translated(self) -> None:
        missing: list[str] = []
        for path in sorted(PACKAGE_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"):
                    continue
                if not node.args:
                    missing.append(f"{path.name}:{node.lineno} tr() 调用缺少参数")
                    continue
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if arg.value not in _EN:
                        missing.append(f"{path.name}:{node.lineno} 词典缺少键：{arg.value}")
                elif not isinstance(arg, ast.Name):
                    # tr(变量) 是合法用法（如 metascape_client 的 label），但 f-string / 拼接永远不会命中词典。
                    missing.append(f"{path.name}:{node.lineno} tr() 参数必须是字符串常量或简单变量")
        self.assertEqual(missing, [])

    def test_no_duplicate_keys(self) -> None:
        self.assertEqual(len(_EN), len(set(_EN)))

    def test_tr_returns_source_in_zh_and_dict_in_en(self) -> None:
        set_ui_language(UI_LANGUAGE_ZH)
        self.assertEqual(tr("开始处理"), "开始处理")
        set_ui_language(UI_LANGUAGE_EN)
        self.assertEqual(tr("开始处理"), "Start")
        self.assertEqual(tr("并发数：{count}").format(count=5), "Concurrency: 5")
        set_ui_language(UI_LANGUAGE_ZH)

    def test_unknown_text_falls_back_to_source(self) -> None:
        set_ui_language(UI_LANGUAGE_EN)
        try:
            self.assertEqual(tr("不存在的文案##"), "不存在的文案##")
        finally:
            set_ui_language(UI_LANGUAGE_ZH)

    def test_default_language_is_chinese(self) -> None:
        self.assertEqual(get_ui_language(), UI_LANGUAGE_ZH)


class TranslationTargetTests(unittest.TestCase):
    def test_targets_do_not_include_english(self) -> None:
        for target in TRANSLATION_TARGETS:
            self.assertNotIn("english", target.prompt_name.lower())
            self.assertNotIn("english", target.label_en.lower())

    def test_default_target_is_simplified_chinese(self) -> None:
        self.assertEqual(normalize_translation_target(None), "zh_cn")
        self.assertEqual(normalize_translation_target("zh_cn"), "zh_cn")
        self.assertEqual(normalize_translation_target("unknown_lang"), "zh_cn")
        self.assertEqual(translation_target_by_code("ja").prompt_name, "Japanese")
        self.assertEqual(translation_target_by_code("ja").column_header, "日本語")

    def test_translator_prompt_uses_target_language(self) -> None:
        translator = OpenAICompatibleTranslator("https://aibz.cc", "key", "model", target_language="Japanese")
        self.assertIn("English to Japanese", translator._system_prompt)
        self.assertEqual(translator._payload("x")["system"], translator._system_prompt)

    def test_translator_default_is_simplified_chinese(self) -> None:
        translator = OpenAICompatibleTranslator("https://aibz.cc", "key", "model")
        self.assertIn("English to Simplified Chinese", translator._system_prompt)

    def test_build_translator_passes_target_language(self) -> None:
        config = AppConfig(
            input_dir=Path("."),
            output_dir=Path("."),
            enable_translation=True,
            api_base_url="https://aibz.cc",
            api_key="key",
            api_model="model",
            translation_target="ja",
        )
        translator = WorkflowController._build_translator(config)
        assert translator is not None
        self.assertIn("English to Japanese", translator._system_prompt)

    def test_translate_workbook_uses_target_header(self) -> None:
        from openpyxl import Workbook, load_workbook

        class IdentityTranslator:
            def translate(self, text: str) -> str:
                return text.upper()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            assert sheet is not None
            sheet.title = "Enrichment"
            sheet.append(["Description", "P-value"])
            sheet.append(["cell cycle", "1e-5"])
            workbook.save(path)

            translate_workbook(path, IdentityTranslator(), target_header="日本語")

            saved = load_workbook(path)
            sheet = saved["Enrichment"]
            headers = [cell.value for cell in sheet[1]]
            self.assertIn("日本語", headers)
            self.assertEqual(sheet.cell(row=2, column=headers.index("日本語") + 1).value, "CELL CYCLE")
            saved.close()

    def test_translate_workbook_skips_existing_target_header(self) -> None:
        from openpyxl import Workbook, load_workbook
        from metabatch.excel_processor import ExcelProcessingError

        class IdentityTranslator:
            def translate(self, text: str) -> str:
                return text

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            assert sheet is not None
            sheet.title = "Enrichment"
            sheet.append(["Description", "中文描述"])
            sheet.append(["cell cycle", "细胞周期"])
            workbook.save(path)

            with self.assertRaises(ExcelProcessingError):
                translate_workbook(path, IdentityTranslator(), target_header="中文描述")

            saved = load_workbook(path)
            self.assertEqual(saved["Enrichment"].max_column, 2)
            saved.close()


if __name__ == "__main__":
    unittest.main()
