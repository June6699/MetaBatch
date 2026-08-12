from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class DownloadType(str, Enum):
    XLSX_ONLY = "xlsx_only"
    ZIP_WITH_EXTRACT = "zip_with_extract"

    @property
    def extension(self) -> str:
        return ".xlsx" if self is DownloadType.XLSX_ONLY else ".zip"

    @classmethod
    def from_value(cls, value: str) -> "DownloadType":
        normalized = value.strip()
        if normalized == "zip_with_extract_and_translate":
            return cls.ZIP_WITH_EXTRACT
        return cls(normalized)


class AnalysisMode(str, Enum):
    EXPRESS = "Express Analysis"


class ConnectionMode(str, Enum):
    DIRECT = "direct"
    PROXY = "proxy"

    @classmethod
    def from_value(cls, value: str) -> "ConnectionMode":
        normalized = value.strip().lower()
        return cls(normalized or cls.DIRECT.value)


class ApiFormat(str, Enum):
    ANTHROPIC_MESSAGES = "anthropic_messages"
    OPENAI_CHAT = "openai_chat_completions"
    OPENAI_RESPONSES = "openai_responses"

    @classmethod
    def from_value(cls, value: str) -> "ApiFormat":
        normalized = value.strip().lower()
        aliases = {
            "anthropic": cls.ANTHROPIC_MESSAGES,
            "anthropic_messages_native": cls.ANTHROPIC_MESSAGES,
            "openai": cls.OPENAI_CHAT,
            "openai_chat": cls.OPENAI_CHAT,
            "responses": cls.OPENAI_RESPONSES,
            "openai_responses_native": cls.OPENAI_RESPONSES,
        }
        return aliases.get(normalized, cls(normalized or cls.ANTHROPIC_MESSAGES.value))


class TaskStatus(str, Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(slots=True)
class AppConfig:
    input_dir: Path
    output_dir: Path
    analysis_mode: AnalysisMode = AnalysisMode.EXPRESS
    download_type: DownloadType = DownloadType.XLSX_ONLY
    enable_translation: bool = True
    api_base_url: str = ""
    api_key: str = ""
    api_model: str = ""
    api_format: ApiFormat = ApiFormat.ANTHROPIC_MESSAGES
    auth_field: str = "ANTHROPIC_AUTH_TOKEN"
    input_column: str = ""
    headless: bool = True
    metascape_connection_mode: ConnectionMode = ConnectionMode.DIRECT
    translation_connection_mode: ConnectionMode = ConnectionMode.DIRECT
    proxy_host: str = "127.0.0.1"
    proxy_port: int | None = None
    concurrency: int = 5
    timeout_seconds: int = 600
    min_delay_seconds: int = 5
    max_delay_seconds: int = 10
    request_interval_seconds: float = 0.1
    translation_max_retries: int = 4

    def normalized_input_column(self) -> str | None:
        value = self.input_column.strip()
        return value or None

    def proxy_url_for(self, mode: ConnectionMode) -> str | None:
        if mode is ConnectionMode.DIRECT:
            return None
        host = self.proxy_host.strip()
        if not host or self.proxy_port is None:
            return None
        return f"http://{host}:{self.proxy_port}"


@dataclass(slots=True)
class DownloadedArtifacts:
    download_path: Path
    excel_path: Path | None = None
    extracted_dir: Path | None = None


@dataclass(slots=True)
class TaskResult:
    source_file: Path
    status: TaskStatus
    download_path: Path | None
    translated_path: Path | None
    message: str
    elapsed_seconds: float
    metascape_elapsed_seconds: float | None = None
    translation_elapsed_seconds: float | None = None
