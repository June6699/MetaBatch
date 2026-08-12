from __future__ import annotations

import unittest
from unittest.mock import patch

from metabatch.models import ApiFormat
from metabatch.translator import OpenAICompatibleTranslator, fetch_available_models, test_translation_connection


class FakeResponse:
    status_code = 200
    headers = {"content-type": "application/json"}

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


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


if __name__ == "__main__":
    unittest.main()
