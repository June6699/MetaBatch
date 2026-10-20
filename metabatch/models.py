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
    PARTIAL = "partial"  # Metascape 结果已下载，但翻译阶段失败
    SKIPPED = "skipped"
    FAILED = "failed"
    STOPPED = "stopped"


# 基因数上限默认值：超过该数量的列表会让 Metascape 输入框响应变得极慢
DEFAULT_MAX_GENES_PER_FILE = 5000


@dataclass(frozen=True)
class TranslationTarget:
    """翻译目标语言定义：界面显示名、提示词用语与 Excel 列名。"""

    code: str
    label_zh: str
    label_en: str
    prompt_name: str
    column_header: str


# 不提供 English 选项：Metascape 的 Description 本身就是英文。
TRANSLATION_TARGETS: tuple[TranslationTarget, ...] = (
    TranslationTarget("zh_cn", "简体中文", "Simplified Chinese", "Simplified Chinese", "中文描述"),
    TranslationTarget("zh_tw", "繁體中文", "Traditional Chinese", "Traditional Chinese", "繁體中文"),
    TranslationTarget("ja", "日语", "Japanese", "Japanese", "日本語"),
    TranslationTarget("ko", "韩语", "Korean", "Korean", "한국어"),
    TranslationTarget("fr", "法语", "French", "French", "Français"),
    TranslationTarget("de", "德语", "German", "German", "Deutsch"),
    TranslationTarget("es", "西班牙语", "Spanish", "Spanish", "Español"),
    TranslationTarget("pt", "葡萄牙语", "Portuguese", "Portuguese", "Português"),
    TranslationTarget("ru", "俄语", "Russian", "Russian", "Русский"),
    TranslationTarget("it", "意大利语", "Italian", "Italian", "Italiano"),
)

DEFAULT_TRANSLATION_TARGET = "zh_cn"


def normalize_translation_target(value: object) -> str:
    code = str(value or "").strip()
    for target in TRANSLATION_TARGETS:
        if target.code == code:
            return code
    return DEFAULT_TRANSLATION_TARGET


def translation_target_by_code(code: str) -> TranslationTarget:
    normalized = normalize_translation_target(code)
    return next(target for target in TRANSLATION_TARGETS if target.code == normalized)


@dataclass(slots=True)
class AppConfig:
    input_dir: Path
    output_dir: Path
    analysis_mode: AnalysisMode = AnalysisMode.EXPRESS
    download_type: DownloadType = DownloadType.XLSX_ONLY
    file_pattern: str = ""  # 可选通配符，如 *.txt；留空匹配全部支持类型
    enable_translation: bool = True
    skip_large_gene_files: bool = True  # 关闭后不再按基因数上限跳过
    max_genes_per_file: int = DEFAULT_MAX_GENES_PER_FILE  # 超过该基因数的列表直接跳过（Metascape 大列表会让页面卡死）
    api_base_url: str = ""
    api_key: str = ""
    api_model: str = ""
    api_format: ApiFormat = ApiFormat.ANTHROPIC_MESSAGES
    auth_field: str = "ANTHROPIC_AUTH_TOKEN"
    translation_target: str = DEFAULT_TRANSLATION_TARGET
    input_column: str = ""
    headless: bool = True
    metascape_connection_mode: ConnectionMode = ConnectionMode.DIRECT
    translation_connection_mode: ConnectionMode = ConnectionMode.DIRECT
    proxy_host: str = "127.0.0.1"
    proxy_port: int | None = None
    concurrency: int = 5
    timeout_seconds: int = 1800
    min_delay_seconds: int = 5
    max_delay_seconds: int = 10
    request_interval_seconds: float = 0.1
    translation_max_retries: int = 4

    def normalized_input_column(self) -> str | None:
        value = self.input_column.strip()
        return value or None

    def normalized_max_genes_per_file(self) -> int | None:
        """返回生效的基因数上限；未启用或非正数时返回 None（表示不限制）。"""
        if not self.skip_large_gene_files:
            return None
        limit = int(self.max_genes_per_file)
        return limit if limit > 0 else None

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
    # 结果可追踪性：跳过原因与翻译阶段状态（写入 metabatch_summary.csv）
    skipped_reason: str = ""
    translation_status: str = ""
    translation_message: str = ""
    gene_count: int = -1  # -1 表示未统计（文件被跳过且未读取）
