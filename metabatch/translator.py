from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable

import requests

from .i18n import tr
from .models import ApiFormat

DEFAULT_TARGET_LANGUAGE = "Simplified Chinese"

SYSTEM_PROMPT_TEMPLATE = (
    "You translate biomedical enrichment term descriptions from English to {language}. "
    "Return only the translated text. Preserve gene symbols, pathway identifiers, "
    "abbreviations, and punctuation when needed."
)


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


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
DEFAULT_BATCH_SIZE = 20
# Adaptive chunking: pending items whose total serialized size fits within
# this budget are sent in a single request; otherwise they are split into the
# minimum number of balanced chunks.
BATCH_CHAR_LIMIT = 4000
MAX_BATCH_ITEMS = 100


class _InflightCall:
    """Shared state for concurrent translate() calls on the same source text."""

    __slots__ = ("done", "error", "result")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.error: BaseException | None = None
        self.result = ""


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
        raise TranslationError(tr("翻译 API Key 不能为空。"))

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
        payload = _response_json(response, tr("模型列表接口"))
    except requests.RequestException as exc:
        raise TranslationError(tr("获取模型失败：{error}").format(error=exc)) from exc

    entries = payload.get("data", payload.get("models", [])) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        raise TranslationError(tr("模型列表接口返回格式异常，未找到 data/models 数组。"))

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
        raise TranslationError(tr("模型列表接口未返回可用模型。"))
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
    return tr("连接成功：模型 {model} 已响应。").format(model=model.strip())


def _response_json(response: requests.Response, operation: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except requests.JSONDecodeError as exc:
        content_type = response.headers.get("content-type", tr("未知"))
        raise TranslationError(
            tr("{operation}未返回 JSON（HTTP {status}，Content-Type: {content_type}）。").format(
                operation=operation,
                status=response.status_code,
                content_type=content_type,
            )
        ) from exc
    if not isinstance(payload, dict):
        raise TranslationError(tr("{operation}返回格式异常，预期 JSON 对象。").format(operation=operation))
    return payload


class Translator:
    def translate(self, text: str) -> str:
        raise NotImplementedError

    def translate_batch(
        self,
        texts: list[str],
        progress_callback: Callable[[int, int], None] | None = None,
        stop_event=None,
    ) -> list[str]:
        """Translate several strings while preserving order."""
        return [self.translate(text) for text in texts]


class OpenAICompatibleTranslator(Translator):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        api_format: str | ApiFormat = ApiFormat.ANTHROPIC_MESSAGES,
        auth_field: str = "ANTHROPIC_AUTH_TOKEN",
        target_language: str = DEFAULT_TARGET_LANGUAGE,
        request_interval_seconds: float = 0.1,
        max_retries: int = 4,
        timeout_seconds: int = 60,
        proxy_url: str | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        # 端点与鉴权配置
        self._api_format = _coerce_api_format(api_format)
        self._auth_field = auth_field.strip() or "ANTHROPIC_AUTH_TOKEN"
        self._url = self._build_url(base_url, self._api_format)
        self._api_key = api_key.strip()
        self._model = model.strip()

        # 翻译提示词、请求节奏与网络参数
        self._system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            language=target_language.strip() or DEFAULT_TARGET_LANGUAGE
        )
        self._request_interval_seconds = request_interval_seconds
        self._max_retries = max_retries
        self._timeout_seconds = timeout_seconds
        self._proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        self._batch_size = max(1, min(int(batch_size), 100))

        # 缓存、在途请求与并发锁（批量锁防止并发 worker 在缓存写入前重复发送同一批）
        self._cache: dict[str, str] = {}
        self._inflight: dict[str, _InflightCall] = {}
        self._lock = threading.Lock()
        self._batch_lock = threading.Lock()
        self._last_request_at = 0.0

    def translate(self, text: str) -> str:
        source = text.strip()
        if not source:
            return ""

        with self._lock:
            cached = self._cache.get(source)
            if cached is not None:
                return cached
            call = self._inflight.get(source)
            if call is None:
                call = _InflightCall()
                self._inflight[source] = call
                owner = True
            else:
                owner = False

        if not owner:
            # 并发 worker 命中同一词条时，跟随首个请求而不是重复调用 API。
            call.done.wait()
            if call.error is not None:
                raise TranslationError(tr("翻译失败：{error}").format(error=call.error)) from call.error
            return call.result

        try:
            translated = self._translate_with_retries(source)
        except BaseException as exc:
            call.error = exc
            with self._lock:
                self._inflight.pop(source, None)
            call.done.set()
            raise
        with self._lock:
            self._cache[source] = translated
            self._inflight.pop(source, None)
        call.result = translated
        call.done.set()
        return translated

    def translate_batch(
        self,
        texts: list[str],
        progress_callback: Callable[[int, int], None] | None = None,
        stop_event=None,
    ) -> list[str]:
        """Translate a batch, deciding the number of requests from its size."""
        normalized = [str(text).strip() for text in texts]
        result = ["" for _ in normalized]

        with self._batch_lock:
            # 去重并跳过已缓存条目，构建真正需要请求的 pending
            pending: list[str] = []
            seen: set[str] = set()
            for source in normalized:
                if not source or source in seen:
                    continue
                with self._lock:
                    cached = self._cache.get(source)
                if cached is None:
                    pending.append(source)
                seen.add(source)

            # 按自适应计划逐块请求，每块写入缓存、回调进度并检查停止
            for chunk in self._plan_chunks(pending):
                if stop_event is not None and stop_event.is_set():
                    raise TranslationError(tr("用户已停止任务。"))

                translated = self._translate_batch_with_retries(chunk)
                if len(translated) != len(chunk):
                    raise TranslationError(tr("翻译接口返回的批量结果数量不匹配。"))

                with self._lock:
                    self._cache.update(dict(zip(chunk, translated, strict=True)))

                if progress_callback is not None:
                    with self._lock:
                        resolved = sum(1 for source in normalized if not source or source in self._cache)
                    progress_callback(resolved, len(normalized))

        # 从缓存按原顺序回填（重复条目也能拿到同一份结果）
        with self._lock:
            for index, source in enumerate(normalized):
                result[index] = self._cache.get(source, "") if source else ""
        return result

    @staticmethod
    def _plan_chunks(pending: list[str]) -> list[list[str]]:
        """Return the minimum number of chunks bounded by chars and item count."""
        if not pending:
            return []

        # 用 JSON 序列化长度近似每条的请求字符开销
        sizes = [len(json.dumps(item, ensure_ascii=False)) for item in pending]

        # 小输入：总字符与条数都在预算内，整块一次发送
        if len(pending) <= MAX_BATCH_ITEMS and sum(sizes) <= BATCH_CHAR_LIMIT:
            return [pending]

        # 大输入：按字符预算贪心打包，不拆分单条，得到最少块
        chunks: list[list[str]] = []
        current: list[str] = []
        current_size = 0
        for item, size in zip(pending, sizes):
            if current and (
                current_size + size > BATCH_CHAR_LIMIT
                or len(current) >= MAX_BATCH_ITEMS
            ):
                chunks.append(current)
                current = []
                current_size = 0
            current.append(item)
            current_size += size
        if current:
            chunks.append(current)
        return chunks

    def _translate_batch_with_retries(self, texts: list[str]) -> list[str]:
        # 构造批量 prompt：要求只返回 translations 数组，顺序与数量严格一致
        prompt = (
            "Translate each item to the target language. Return ONLY a JSON object with key "
            "translations whose value is an array of translated strings in exactly the same order and length.\n"
            + json.dumps(texts, ensure_ascii=False)
        )
        last_error: Exception | None = None

        # 带重试的请求循环
        for attempt in range(1, self._max_retries + 1):
            response: requests.Response | None = None
            try:
                self._respect_rate_limit()
                response = requests.post(self._url, headers=self._headers(), json=self._payload(prompt), proxies=self._proxies, timeout=self._timeout_seconds)
            except requests.RequestException as exc:
                last_error = exc
            else:
                # 可重试状态码（429/5xx）记录错误，稍后退避；其他 4xx 直接失败
                if response.status_code in RETRYABLE_STATUS_CODES:
                    last_error = TranslationError(tr("翻译接口暂时不可用，HTTP {status}: {body}").format(status=response.status_code, body=response.text[:300]))
                elif response.status_code >= 400:
                    raise TranslationError(tr("翻译请求被拒绝，HTTP {status}: {body}").format(status=response.status_code, body=response.text[:300]))
                else:
                    # 提取文本并解析批量 JSON，兼容对象、裸数组与容错格式
                    content = self._extract_message_content(_response_json(response, tr("翻译接口"))).strip()
                    try:
                        parsed = self._parse_batch_json(content)
                        values = parsed.get("translations") if isinstance(parsed, dict) else None
                        if values is None and isinstance(parsed, list):
                            values = parsed
                        if isinstance(values, list) and len(values) == len(texts):
                            return [str(value).strip() for value in values]
                        raise ValueError("invalid translation array")
                    except (json.JSONDecodeError, ValueError, TypeError):
                        last_error = TranslationError(tr("无法解析翻译结果：{payload}").format(payload=content[:300]))

            # 未耗尽尝试次数则按退避策略等待
            if attempt < self._max_retries:
                time.sleep(self._retry_delay(attempt, response))

        raise TranslationError(tr("翻译失败：{error}").format(error=last_error)) from last_error

    @staticmethod
    def _parse_batch_json(content: str) -> Any:
        """Parse JSON while tolerating markdown fences or a short preamble."""
        value = content.strip()
        if value.startswith("```"):
            lines = value.splitlines()
            if lines and lines[0].lstrip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            value = "\n".join(lines).strip()
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            decoder = json.JSONDecoder()
            for marker in ("{", "["):
                start = value.find(marker)
                if start >= 0:
                    try:
                        parsed, _ = decoder.raw_decode(value[start:])
                        return parsed
                    except json.JSONDecodeError:
                        continue
            raise

    def _translate_with_retries(self, text: str) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            response: requests.Response | None = None
            try:
                self._respect_rate_limit()
                response = requests.post(
                    self._url,
                    headers=self._headers(),
                    json=self._payload(text),
                    proxies=self._proxies,
                    timeout=self._timeout_seconds,
                )
            except requests.RequestException as exc:
                last_error = exc
            else:
                if response.status_code in RETRYABLE_STATUS_CODES:
                    last_error = TranslationError(
                        tr("翻译接口暂时不可用，HTTP {status}: {body}").format(
                            status=response.status_code, body=response.text[:300]
                        )
                    )
                elif response.status_code >= 400:
                    # 4xx 属于配置/鉴权问题，重试也不会成功，直接失败。
                    raise TranslationError(
                        tr("翻译请求被拒绝，HTTP {status}: {body}").format(
                            status=response.status_code, body=response.text[:300]
                        )
                    ) from None
                else:
                    translated = self._extract_message_content(_response_json(response, tr("翻译接口"))).strip()
                    if translated:
                        return translated
                    last_error = TranslationError(tr("翻译接口返回了空结果。"))

            if attempt < self._max_retries:
                time.sleep(self._retry_delay(attempt, response))

        raise TranslationError(tr("翻译失败：{error}").format(error=last_error)) from last_error

    @staticmethod
    def _retry_delay(attempt: int, response: requests.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(max(float(retry_after), 0), 30)
                except ValueError:
                    pass
        return min(2 ** (attempt - 1), 8)

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
        # 三种 API 格式共用的消息内容
        messages = [{"role": "user", "content": text}]

        # Anthropic Messages：system 独立、max_tokens 固定
        if self._api_format is ApiFormat.ANTHROPIC_MESSAGES:
            return {"model": self._model, "max_tokens": 4096, "system": self._system_prompt, "messages": messages}

        # OpenAI Responses：instructions、input 结构与 max_output_tokens
        if self._api_format is ApiFormat.OPENAI_RESPONSES:
            return {
                "model": self._model,
                "instructions": self._system_prompt,
                "max_output_tokens": 4096,
                "input": [{"role": "user", "content": [{"type": "input_text", "text": text}]}],
            }

        # OpenAI Chat：system 放在消息列表，temperature 固定 0
        return {
            "model": self._model,
            "temperature": 0,
            "messages": [{"role": "system", "content": self._system_prompt}, *messages],
        }

    @staticmethod
    def _build_api_root(base_url: str) -> str:
        value = base_url.strip().rstrip("/")
        if not value:
            raise TranslationError(tr("翻译 API Base URL 不能为空。"))
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
        # Anthropic Messages：从 content 块中取 text 拼接
        if self._api_format is ApiFormat.ANTHROPIC_MESSAGES:
            content = payload.get("content", [])
            if isinstance(content, list):
                texts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
                return "".join(texts)
            raise TranslationError(tr("Anthropic 接口返回格式异常：{payload}").format(payload=payload))

        # OpenAI Responses：优先 output_text，否则从 output 结构里提取文本
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
            raise TranslationError(tr("Responses 接口返回格式异常：{payload}").format(payload=payload))

        # OpenAI Chat：从 choices[0].message.content 取文本（兼容字符串与数组）
        choices = payload.get("choices")
        if not choices:
            raise TranslationError(tr("翻译接口未返回 choices：{payload}").format(payload=payload))
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [item.get("text", "") for item in content if isinstance(item, dict)]
            return "".join(texts)
        raise TranslationError(tr("无法解析翻译结果：{payload}").format(payload=payload))
