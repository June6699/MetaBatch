from __future__ import annotations

import threading
import time
from typing import Any

import requests

from .models import ApiFormat


def _coerce_api_format(value: str | ApiFormat) -> ApiFormat:
    return value if isinstance(value, ApiFormat) else ApiFormat.from_value(str(value))


def _auth_headers(api_key: str, api_format: str | ApiFormat, auth_field: str) -> dict[str, str]:
    selected = _coerce_api_format(api_format)
    field = auth_field.strip().lower()
    if selected is ApiFormat.ANTHROPIC_MESSAGES:
        if field in {"x-api-key", "anthropic_api_key"}:
            auth = {"x-api-key": api_key}
        else:
            auth = {"Authorization": f"Bearer {api_key}"}
        return {**auth, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {api_key}"}


class TranslationError(Exception):
    """Raised when the translation API fails."""


def fetch_available_models(
    base_url: str,
    api_key: str,
    proxy_url: str | None = None,
    timeout_seconds: int = 20,
    api_format: str | ApiFormat = ApiFormat.ANTHROPIC_MESSAGES,
    auth_field: str = "ANTHROPIC_AUTH_TOKEN",
) -> list[str]:
    """Return model identifiers exposed by an OpenAI-compatible ``/models`` endpoint."""
    key = api_key.strip()
    if not key:
        raise TranslationError("翻译 API Key 不能为空。")

    url = OpenAICompatibleTranslator._build_models_url(base_url, _coerce_api_format(api_format))
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    try:
        response = requests.get(
            url,
            headers=_auth_headers(key, api_format, auth_field),
            proxies=proxies,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = _response_json(response, "模型列表接口")
    except requests.RequestException as exc:
        raise TranslationError(f"获取模型失败：{exc}") from exc

    entries = payload.get("data", payload.get("models", [])) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        raise TranslationError("模型列表接口返回格式异常，未找到 data/models 数组。")

    models: set[str] = set()
    for entry in entries:
        if isinstance(entry, str) and entry.strip():
            models.add(entry.strip())
        elif isinstance(entry, dict):
            for field in ("id", "name", "model"):
                value = entry.get(field)
                if isinstance(value, str) and value.strip():
                    models.add(value.strip())
                    break
    if not models:
        raise TranslationError("模型列表接口未返回可用模型。")
    return sorted(models, key=str.casefold)


def test_translation_connection(
    base_url: str,
    api_key: str,
    model: str,
    proxy_url: str | None = None,
    api_format: str | ApiFormat = ApiFormat.ANTHROPIC_MESSAGES,
    auth_field: str = "ANTHROPIC_AUTH_TOKEN",
) -> str:
    """Verify that the selected model can complete the same request used by translation."""
    translator = OpenAICompatibleTranslator(
        base_url=base_url,
        api_key=api_key,
        model=model,
        api_format=api_format,
        auth_field=auth_field,
        request_interval_seconds=0,
        max_retries=1,
        timeout_seconds=30,
        proxy_url=proxy_url,
    )
    translator.translate("cell cycle")
    return f"连接成功：模型 {model.strip()} 已响应。"


def _response_json(response: requests.Response, operation: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except requests.JSONDecodeError as exc:
        content_type = response.headers.get("content-type", "未知")
        raise TranslationError(
            f"{operation}未返回 JSON（HTTP {response.status_code}，Content-Type: {content_type}）。"
        ) from exc
    if not isinstance(payload, dict):
        raise TranslationError(f"{operation}返回格式异常，预期 JSON 对象。")
    return payload


class Translator:
    def translate(self, text: str) -> str:
        raise NotImplementedError


class OpenAICompatibleTranslator(Translator):
    SYSTEM_PROMPT = (
        "You translate biomedical enrichment term descriptions from English to "
        "Simplified Chinese. Return only the translated Chinese text. Preserve gene "
        "symbols, pathway identifiers, abbreviations, and punctuation when needed."
    )

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        api_format: str | ApiFormat = ApiFormat.ANTHROPIC_MESSAGES,
        auth_field: str = "ANTHROPIC_AUTH_TOKEN",
        request_interval_seconds: float = 0.1,
        max_retries: int = 4,
        timeout_seconds: int = 60,
        proxy_url: str | None = None,
    ) -> None:
        self._api_format = _coerce_api_format(api_format)
        self._auth_field = auth_field.strip() or "ANTHROPIC_AUTH_TOKEN"
        self._url = self._build_url(base_url, self._api_format)
        self._api_key = api_key.strip()
        self._model = model.strip()
        self._request_interval_seconds = request_interval_seconds
        self._max_retries = max_retries
        self._timeout_seconds = timeout_seconds
        self._proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()
        self._last_request_at = 0.0

    def translate(self, text: str) -> str:
        source = text.strip()
        if not source:
            return ""

        with self._lock:
            cached = self._cache.get(source)
            if cached is not None:
                return cached

        translated = self._translate_with_retries(source)
        with self._lock:
            self._cache[source] = translated
        return translated

    def _translate_with_retries(self, text: str) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                self._respect_rate_limit()
                response = requests.post(
                    self._url,
                    headers=self._headers(),
                    json=self._payload(text),
                    proxies=self._proxies,
                    timeout=self._timeout_seconds,
                )

                if response.status_code in {429, 500, 502, 503, 504}:
                    raise TranslationError(
                        f"翻译接口暂时不可用，HTTP {response.status_code}: {response.text[:300]}"
                    )
                response.raise_for_status()

                payload = _response_json(response, "翻译接口")
                translated = self._extract_message_content(payload).strip()
                if not translated:
                    raise TranslationError("翻译接口返回了空结果。")
                return translated
            except (requests.RequestException, TranslationError) as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    break
                time.sleep(min(2 ** (attempt - 1), 8))

        raise TranslationError(f"翻译失败：{last_error}") from last_error

    def _respect_rate_limit(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait_seconds = self._request_interval_seconds - (now - self._last_request_at)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self._last_request_at = time.monotonic()

    def _headers(self) -> dict[str, str]:
        return {**_auth_headers(self._api_key, self._api_format, self._auth_field), "Content-Type": "application/json"}

    def _payload(self, text: str) -> dict[str, Any]:
        messages = [{"role": "user", "content": text}]
        if self._api_format is ApiFormat.ANTHROPIC_MESSAGES:
            return {"model": self._model, "max_tokens": 256, "system": self.SYSTEM_PROMPT, "messages": messages}
        if self._api_format is ApiFormat.OPENAI_RESPONSES:
            return {
                "model": self._model,
                "temperature": 0,
                "instructions": self.SYSTEM_PROMPT,
                "input": [{"role": "user", "content": [{"type": "input_text", "text": text}]}],
            }
        return {
            "model": self._model,
            "temperature": 0,
            "messages": [{"role": "system", "content": self.SYSTEM_PROMPT}, *messages],
        }

    @staticmethod
    def _build_api_root(base_url: str) -> str:
        value = base_url.strip().rstrip("/")
        if not value:
            raise TranslationError("翻译 API Base URL 不能为空。")
        return value

    @classmethod
    def _build_url(cls, base_url: str, api_format: str | ApiFormat = ApiFormat.ANTHROPIC_MESSAGES) -> str:
        value = cls._build_api_root(base_url)
        selected = _coerce_api_format(api_format)
        if selected is ApiFormat.ANTHROPIC_MESSAGES:
            if value.endswith("/messages"):
                return value
            return f"{value}/messages"
        if selected is ApiFormat.OPENAI_RESPONSES:
            if value.endswith("/responses"):
                return value
            return f"{value}/responses"
        if value.endswith("/chat/completions"):
            return value
        return f"{value}/chat/completions"

    @classmethod
    def _build_models_url(cls, base_url: str, api_format: str | ApiFormat) -> str:
        value = cls._build_api_root(base_url)
        selected = _coerce_api_format(api_format)
        if value.endswith("/chat/completions"):
            value = value[: -len("/chat/completions")]
        elif value.endswith("/messages"):
            value = value[: -len("/messages")]
        elif value.endswith("/responses"):
            value = value[: -len("/responses")]
        return f"{value}/models"

    def _extract_message_content(self, payload: dict[str, Any]) -> str:
        if self._api_format is ApiFormat.ANTHROPIC_MESSAGES:
            content = payload.get("content", [])
            if isinstance(content, list):
                texts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
                return "".join(texts)
            raise TranslationError(f"Anthropic 接口返回格式异常：{payload}")

        if self._api_format is ApiFormat.OPENAI_RESPONSES:
            output_text = payload.get("output_text", "")
            if isinstance(output_text, str) and output_text.strip():
                return output_text
            output = payload.get("output", [])
            if isinstance(output, list):
                texts: list[str] = []
                for item in output:
                    if not isinstance(item, dict):
                        continue
                    content = item.get("content", [])
                    if not isinstance(content, list):
                        continue
                    texts.extend(
                        str(block.get("text", ""))
                        for block in content
                        if isinstance(block, dict) and block.get("type") in {"output_text", "text"}
                    )
                if texts:
                    return "".join(texts)
            raise TranslationError(f"Responses 接口返回格式异常：{payload}")

        choices = payload.get("choices")
        if not choices:
            raise TranslationError(f"翻译接口未返回 choices：{payload}")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [item.get("text", "") for item in content if isinstance(item, dict)]
            return "".join(texts)
        raise TranslationError(f"无法解析翻译结果：{payload}")
