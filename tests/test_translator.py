from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from metabatch.gene_reader import GeneReadError, read_gene_list
from metabatch.models import ApiFormat, DownloadType
from metabatch.paths import build_output_paths
from metabatch.translator import (
    OpenAICompatibleTranslator,
    TranslationError,
    fetch_available_models,
    test_translation_connection,
)


class FakeResponse:
    headers = {"content-type": "application/json"}

    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError("raise_for_status should not be reached in these tests")

    def json(self) -> dict[str, object]:
        return self._payload


ANTHROPIC_OK_PAYLOAD = {"content": [{"type": "text", "text": "细胞周期"}]}


class TranslatorEndpointTests(unittest.TestCase):
    def test_anthropic_root_url_does_not_add_v1(self) -> None:
        self.assertEqual(
            OpenAICompatibleTranslator._build_url("https://aibz.cc"),
            "https://aibz.cc/messages",
        )

    def test_openai_base_url_is_not_rewritten_to_v1(self) -> None:
        self.assertEqual(
            OpenAICompatibleTranslator._build_url("https://aibz.cc", ApiFormat.OPENAI_CHAT),
            "https://aibz.cc/chat/completions",
        )

    def test_responses_base_url_is_not_rewritten_to_v1(self) -> None:
        self.assertEqual(
            OpenAICompatibleTranslator._build_url("https://aibz.cc", ApiFormat.OPENAI_RESPONSES),
            "https://aibz.cc/responses",
        )

    def test_explicit_endpoints_are_preserved(self) -> None:
        self.assertEqual(
            OpenAICompatibleTranslator._build_url("https://aibz.cc/messages", ApiFormat.ANTHROPIC_MESSAGES),
            "https://aibz.cc/messages",
        )
        self.assertEqual(
            OpenAICompatibleTranslator._build_url("https://aibz.cc/chat/completions", ApiFormat.OPENAI_CHAT),
            "https://aibz.cc/chat/completions",
        )

    @patch("metabatch.translator.requests.get")
    def test_fetch_models_supports_openai_data_payload(self, mocked_get: object) -> None:
        mocked_get.return_value = FakeResponse({"data": [{"id": "z-model"}, {"id": "a-model"}]})

        models = fetch_available_models("https://aibz.cc", "key")

        self.assertEqual(models, ["a-model", "z-model"])
        self.assertEqual(mocked_get.call_args.args[0], "https://aibz.cc/models")

    @patch.object(OpenAICompatibleTranslator, "translate", return_value="细胞周期")
    def test_connection_uses_selected_model(self, mocked_translate: object) -> None:
        message = test_translation_connection("https://aibz.cc", "key", "deepseek-v4-flash")

        self.assertIn("deepseek-v4-flash", message)
        mocked_translate.assert_called_once_with("cell cycle")


class TranslatorRetryTests(unittest.TestCase):
    def _translator(self, **kwargs: object) -> OpenAICompatibleTranslator:
        options: dict[str, object] = {
            "request_interval_seconds": 0,
            "max_retries": 4,
        }
        options.update(kwargs)
        return OpenAICompatibleTranslator("https://aibz.cc", "key", "model", **options)

    @patch("metabatch.translator.time.sleep", lambda seconds: None)
    @patch("metabatch.translator.requests.post")
    def test_http_4xx_fails_fast(self, mocked_post: object) -> None:
        mocked_post.return_value = FakeResponse({"error": "invalid key"}, status_code=401)

        with self.assertRaises(TranslationError):
            self._translator().translate("cell cycle")

        self.assertEqual(mocked_post.call_count, 1)

    @patch("metabatch.translator.time.sleep", lambda seconds: None)
    @patch("metabatch.translator.requests.post")
    def test_http_429_is_retried_until_success(self, mocked_post: object) -> None:
        mocked_post.side_effect = [
            FakeResponse({}, status_code=429),
            FakeResponse(ANTHROPIC_OK_PAYLOAD),
        ]

        self.assertEqual(self._translator(max_retries=2).translate("cell cycle"), "细胞周期")
        self.assertEqual(mocked_post.call_count, 2)

    @patch("metabatch.translator.time.sleep", lambda seconds: None)
    @patch("metabatch.translator.requests.post")
    def test_http_5xx_exhausts_retries(self, mocked_post: object) -> None:
        mocked_post.return_value = FakeResponse({}, status_code=503)

        with self.assertRaises(TranslationError):
            self._translator(max_retries=3).translate("cell cycle")

        self.assertEqual(mocked_post.call_count, 3)

    def test_translations_are_cached_across_calls(self) -> None:
        with patch("metabatch.translator.requests.post", return_value=FakeResponse(ANTHROPIC_OK_PAYLOAD)) as mocked_post:
            translator = self._translator()
            self.assertEqual(translator.translate("cell cycle"), "细胞周期")
            self.assertEqual(translator.translate("cell cycle"), "细胞周期")

        self.assertEqual(mocked_post.call_count, 1)


class GeneReaderTests(unittest.TestCase):
    def test_txt_supports_gb18030_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "genes.txt"
            path.write_bytes("Zfhx3\nAdamts9\n".encode("gb18030"))
            self.assertEqual(read_gene_list(path), ["Zfhx3", "Adamts9"])

    def test_txt_strips_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "genes.txt"
            path.write_bytes(b"\xef\xbb\xbfCdh13\nNell2\n")
            self.assertEqual(read_gene_list(path), ["Cdh13", "Nell2"])

    def test_undecodable_file_raises_gene_read_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "genes.txt"
            path.write_bytes(b"\x80\x81\x82")
            with self.assertRaises(GeneReadError):
                read_gene_list(path)


class OutputPathTests(unittest.TestCase):
    def test_same_stem_different_suffix_gets_disambiguated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            txt_file = root / "list.txt"
            xlsx_file = root / "list.xlsx"
            txt_paths = build_output_paths(root, root / "out", txt_file, DownloadType.XLSX_ONLY, disambiguate_suffix=True)
            xlsx_paths = build_output_paths(root, root / "out", xlsx_file, DownloadType.XLSX_ONLY, disambiguate_suffix=True)

            self.assertEqual(txt_paths.download_path.name, "list_txt_metascape.xlsx")
            self.assertEqual(xlsx_paths.download_path.name, "list_xlsx_metascape.xlsx")
            self.assertNotEqual(txt_paths.download_path, xlsx_paths.download_path)

    def test_default_keeps_plain_suffix_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_output_paths(root, root / "out", root / "list.txt", DownloadType.XLSX_ONLY)
            self.assertEqual(paths.download_path.name, "list_metascape.xlsx")


if __name__ == "__main__":
    unittest.main()
