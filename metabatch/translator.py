from __future__ import annotations

import threading
import time
from typing import Any

import requests


class TranslationError(Exception):
    """Raised when the translation API fails."""


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
        request_interval_seconds: float = 0.1,
        max_retries: int = 4,
        timeout_seconds: int = 60,
        proxy_url: str | None = None,
    ) -> None:
        self._url = self._build_url(base_url)
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
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "temperature": 0,
                        "messages": [
                            {"role": "system", "content": self.SYSTEM_PROMPT},
                            {"role": "user", "content": text},
                        ],
                    },
                    proxies=self._proxies,
                    timeout=self._timeout_seconds,
                )

                if response.status_code in {429, 500, 502, 503, 504}:
                    raise TranslationError(
                        f"翻译接口暂时不可用，HTTP {response.status_code}: {response.text[:300]}"
                    )
                response.raise_for_status()

                payload = response.json()
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

    @staticmethod
    def _build_url(base_url: str) -> str:
        value = base_url.strip().rstrip("/")
        if not value:
            raise TranslationError("翻译 API Base URL 不能为空。")
        if value.endswith("/chat/completions"):
            return value
        if value.endswith("/v1"):
            return f"{value}/chat/completions"
        return f"{value}/chat/completions"

    @staticmethod
    def _extract_message_content(payload: dict[str, Any]) -> str:
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
