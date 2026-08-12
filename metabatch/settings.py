from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .models import ApiFormat, AppConfig, ConnectionMode, DownloadType
from .runtime import get_app_data_dir

CONFIG_FILENAME = "metabatch_config.json"
DEFAULT_PROFILE_NAME = "默认配置"


@dataclass(slots=True)
class SavedProfile:
    name: str
    input_dir: str = ""
    output_dir: str = ""
    download_type: str = DownloadType.XLSX_ONLY.value
    input_column: str = ""
    enable_translation: bool = True
    api_base_url: str = ""
    api_key: str = ""
    api_model: str = ""
    api_format: str = ApiFormat.ANTHROPIC_MESSAGES.value
    auth_field: str = "ANTHROPIC_AUTH_TOKEN"
    headless: bool = True
    metascape_connection_mode: str = ConnectionMode.DIRECT.value
    translation_connection_mode: str = ConnectionMode.DIRECT.value
    proxy_host: str = "127.0.0.1"
    proxy_port: int | None = None
    concurrency: int = 5

    @classmethod
    def from_app_config(cls, name: str, config: AppConfig) -> "SavedProfile":
        return cls(
            name=name,
            input_dir=str(config.input_dir),
            output_dir=str(config.output_dir),
            download_type=config.download_type.value,
            input_column=config.input_column,
            enable_translation=config.enable_translation,
            api_base_url=config.api_base_url,
            api_key=config.api_key,
            api_model=config.api_model,
            api_format=config.api_format.value,
            auth_field=config.auth_field,
            headless=config.headless,
            metascape_connection_mode=config.metascape_connection_mode.value,
            translation_connection_mode=config.translation_connection_mode.value,
            proxy_host=config.proxy_host,
            proxy_port=config.proxy_port,
            concurrency=config.concurrency,
        )


@dataclass(slots=True)
class AppSettings:
    profiles: dict[str, SavedProfile] = field(default_factory=dict)
    last_profile_name: str | None = None

    @classmethod
    def default(cls) -> "AppSettings":
        return cls(
            profiles={DEFAULT_PROFILE_NAME: SavedProfile(name=DEFAULT_PROFILE_NAME)},
            last_profile_name=DEFAULT_PROFILE_NAME,
        )


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (get_app_data_dir() / CONFIG_FILENAME)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> tuple[AppSettings, str | None]:
        if not self._path.exists():
            return AppSettings.default(), None

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            profiles_raw = raw.get("profiles", {})
            profiles: dict[str, SavedProfile] = {}
            for name, payload in profiles_raw.items():
                profiles[name] = SavedProfile(
                    name=name,
                    input_dir=str(payload.get("input_dir", "")),
                    output_dir=str(payload.get("output_dir", "")),
                    download_type=DownloadType.from_value(
                        str(payload.get("download_type", DownloadType.XLSX_ONLY.value))
                    ).value,
                    input_column=str(payload.get("input_column", "")),
                    enable_translation=bool(payload.get("enable_translation", True)),
                    api_base_url=str(payload.get("api_base_url", "")),
                    api_key=str(payload.get("api_key", "")),
                    api_model=str(payload.get("api_model", "")),
                    api_format=ApiFormat.from_value(
                        str(payload.get("api_format", ApiFormat.ANTHROPIC_MESSAGES.value))
                    ).value,
                    auth_field=str(payload.get("auth_field", "ANTHROPIC_AUTH_TOKEN")),
                    headless=bool(payload.get("headless", True)),
                    metascape_connection_mode=ConnectionMode.from_value(
                        str(payload.get("metascape_connection_mode", ConnectionMode.DIRECT.value))
                    ).value,
                    translation_connection_mode=ConnectionMode.from_value(
                        str(payload.get("translation_connection_mode", ConnectionMode.DIRECT.value))
                    ).value,
                    proxy_host=str(payload.get("proxy_host", "127.0.0.1")),
                    proxy_port=_parse_proxy_port(payload.get("proxy_port")),
                    concurrency=_parse_concurrency(payload.get("concurrency", 5)),
                )

            if not profiles:
                return AppSettings.default(), "配置文件为空，已恢复默认配置。"

            last_profile_name = raw.get("last_profile_name")
            if last_profile_name not in profiles:
                last_profile_name = next(iter(profiles))

            return AppSettings(profiles=profiles, last_profile_name=last_profile_name), None
        except Exception:
            return AppSettings.default(), "配置加载失败，已使用默认界面状态。"

    def save(self, settings: AppSettings) -> None:
        payload = {
            "profiles": {name: asdict(profile) for name, profile in settings.profiles.items()},
            "last_profile_name": settings.last_profile_name,
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _parse_proxy_port(value: object) -> int | None:
    if value in {None, ""}:
        return None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= port <= 65535:
        return port
    return None


def _parse_concurrency(value: object) -> int:
    try:
        concurrency = int(value)
    except (TypeError, ValueError):
        return 5
    return max(1, min(concurrency, 32))
