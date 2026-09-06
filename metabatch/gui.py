from __future__ import annotations

import sys
import threading
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTabBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .assets import ensure_app_icon
from .gene_reader import discover_gene_files
from .i18n import UI_LANGUAGES, get_ui_language, set_ui_language, tr
from .logging_utils import get_logs_dir
from .models import (
    TRANSLATION_TARGETS,
    AnalysisMode,
    ApiFormat,
    AppConfig,
    ConnectionMode,
    DownloadType,
    TaskResult,
    TaskStatus,
    normalize_translation_target,
)
from .settings import DEFAULT_PROFILE_NAME, SavedProfile, SettingsStore
from .translator import TranslationError, fetch_available_models, test_translation_connection
from .workflow import WorkflowController


class WheelGuardComboBox(QComboBox):
    """禁止悬停滚动滚轮直接切换选项。

    Qt 默认在鼠标悬停时用滚轮切换 QComboBox 的当前项，容易在滚动页面时
    误改 API 格式、认证字段等配置；这里忽略滚轮并向上传递，
    让外层 QScrollArea 正常滚动，选择必须点开下拉完成。
    打开下拉后列表内的滚轮滚动不受影响（事件由弹出列表自行处理）。
    """

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()


class WheelGuardTabBar(QTabBar):
    """禁止悬停滚动滚轮切换标签页，行为与 WheelGuardComboBox 一致。"""

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()


class WheelGuardTabWidget(QTabWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # setTabBar 必须在加入任何标签页之前调用。
        self.setTabBar(WheelGuardTabBar())


def _parse_proxy_port(text: str) -> int | None:
    value = text.strip()
    if not value:
        return None
    try:
        port = int(value)
    except ValueError:
        raise ValueError(tr("代理端口必须是 1-65535 之间的整数。")) from None
    if not 1 <= port <= 65535:
        raise ValueError(tr("代理端口必须在 1-65535 之间。"))
    return port


def _parse_concurrency(text: str) -> int:
    value = text.strip() or "5"
    try:
        number = int(value)
    except ValueError:
        raise ValueError(tr("并发数量必须是 1-32 之间的整数。")) from None
    if not 1 <= number <= 32:
        raise ValueError(tr("并发数量必须在 1-32 之间。"))
    return number


def _build_config(values: dict[str, Any]) -> AppConfig:
    input_dir = Path(str(values["input_dir"]).strip())
    output_dir = Path(str(values["output_dir"]).strip())
    input_column = str(values.get("input_column", "")).strip()
    enable_translation = bool(values.get("enable_translation", True))
    api_base_url = str(values.get("api_base_url", "")).strip()
    api_key = str(values.get("api_key", "")).strip()
    api_model = str(values.get("api_model", "")).strip()
    api_format = ApiFormat.from_value(str(values.get("api_format", ApiFormat.ANTHROPIC_MESSAGES.value)))
    auth_field = str(values.get("auth_field", "ANTHROPIC_AUTH_TOKEN")).strip() or "ANTHROPIC_AUTH_TOKEN"
    translation_target = normalize_translation_target(values.get("translation_target"))
    proxy_host = str(values.get("proxy_host", "127.0.0.1")).strip() or "127.0.0.1"
    proxy_port = _parse_proxy_port(str(values.get("proxy_port", "")).strip())
    concurrency = _parse_concurrency(str(values.get("concurrency", "")))

    if not input_dir.exists() or not input_dir.is_dir():
        raise ValueError(tr("请输入存在的基因列表文件夹路径。"))
    if not str(output_dir).strip():
        raise ValueError(tr("请输入输出结果文件夹路径。"))
    if not discover_gene_files(input_dir):
        raise ValueError(tr("输入目录中未找到 txt/csv/tsv/xlsx/xls 文件。"))
    if enable_translation:
        if not api_base_url:
            raise ValueError(tr("启用翻译时请输入翻译 API Base URL。"))
        if not api_key:
            raise ValueError(tr("启用翻译时请输入翻译 API Key。"))
        if not api_model:
            raise ValueError(tr("启用翻译时请输入翻译 Model。"))
    if values.get("metascape_connection_mode") == ConnectionMode.PROXY.value and proxy_port is None:
        raise ValueError(tr("Metascape 使用代理时请输入有效端口。"))
    if enable_translation and values.get("translation_connection_mode") == ConnectionMode.PROXY.value and proxy_port is None:
        raise ValueError(tr("翻译 API 使用代理时请输入有效端口。"))

    return AppConfig(
        input_dir=input_dir,
        output_dir=output_dir,
        analysis_mode=AnalysisMode.EXPRESS,
        download_type=DownloadType.from_value(str(values["download_type"])),
        enable_translation=enable_translation,
        api_base_url=api_base_url,
        api_key=api_key,
        api_model=api_model,
        api_format=api_format,
        auth_field=auth_field,
        translation_target=translation_target,
        input_column=input_column,
        headless=bool(values.get("headless", True)),
        metascape_connection_mode=ConnectionMode.from_value(str(values.get("metascape_connection_mode", ConnectionMode.DIRECT.value))),
        translation_connection_mode=ConnectionMode.from_value(str(values.get("translation_connection_mode", ConnectionMode.DIRECT.value))),
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        concurrency=concurrency,
    )


def _build_summary(results: list[TaskResult]) -> str:
    success = sum(1 for item in results if item.status is TaskStatus.SUCCESS)
    skipped = sum(1 for item in results if item.status is TaskStatus.SKIPPED)
    failed = sum(1 for item in results if item.status is TaskStatus.FAILED)
    stopped = sum(1 for item in results if item.status is TaskStatus.STOPPED)
    return tr("任务汇总：成功 {success}，跳过 {skipped}，失败 {failed}，停止 {stopped}。").format(
        success=success, skipped=skipped, failed=failed, stopped=stopped
    )


class WorkflowWorker(QObject):
    log = Signal(object, str)
    progress = Signal(int, int, str, object, object, object, object, object, object)
    done = Signal(list)
    error = Signal(str)

    def __init__(self, config: AppConfig, controller: WorkflowController) -> None:
        super().__init__()
        self._config = config
        self._controller = controller
        self._stop_event = threading.Event()

    def run(self) -> None:
        try:
            results = self._controller.run(
                self._config,
                self._stop_event,
                lambda worker_id, message: self.log.emit(worker_id, message),
                lambda current, total, status, analysis_percent, analysis_status, translation_percent, translation_status, worker_id, current_path: self.progress.emit(
                    current,
                    total,
                    status,
                    analysis_percent,
                    analysis_status,
                    translation_percent,
                    translation_status,
                    worker_id,
                    current_path,
                ),
            )
            self.done.emit(results)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))

    def request_stop(self) -> None:
        self._stop_event.set()


class TranslationProbeWorker(QObject):
    models_loaded = Signal(list)
    succeeded = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        action: str,
        base_url: str,
        api_key: str,
        model: str,
        proxy_url: str | None,
        api_format: ApiFormat,
        auth_field: str,
    ) -> None:
        super().__init__()
        self._action = action
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._proxy_url = proxy_url
        self._api_format = api_format
        self._auth_field = auth_field

    def run(self) -> None:
        try:
            if self._action == "models":
                self.models_loaded.emit(
                    fetch_available_models(
                        self._base_url,
                        self._api_key,
                        self._proxy_url,
                        api_format=self._api_format,
                        auth_field=self._auth_field,
                    )
                )
            else:
                self.succeeded.emit(
                    test_translation_connection(
                        self._base_url,
                        self._api_key,
                        self._model,
                        self._proxy_url,
                        api_format=self._api_format,
                        auth_field=self._auth_field,
                    )
                )
        except (TranslationError, ValueError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(tr("翻译接口检测异常：{error}").format(error=exc))
        finally:
            self.finished.emit()


class ColoredLogView(QTextEdit):
    COLOR_MAP = {
        "error": "#c62828",
        "success": "#2e7d32",
        "warning": "#ef6c00",
        "progress": "#1565c0",
        "action": "#455a64",
        "info": "#212121",
        "muted": "#757575",
    }

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setAcceptRichText(True)
        self.setLineWrapMode(QTextEdit.NoWrap)
        self.setUndoRedoEnabled(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFont(QFont("Consolas", 10))

    def append_message(self, message: str) -> None:
        kind = _classify_log_kind(message)
        color = self.COLOR_MAP.get(kind, self.COLOR_MAP["info"])
        html = f'<span style="color:{color}; white-space: pre-wrap;">{escape(message)}</span>'
        self.append(html)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


def _classify_log_kind(message: str) -> str:
    lowered = message.lower()
    if (
        "失败" in message
        or "异常" in message
        or "error" in lowered
        or "fail" in lowered
        or "timeout" in lowered
        or "refused" in lowered
    ):
        return "error"
    if "完成" in message or "成功" in message or "complete" in lowered or "success" in lowered or "located" in lowered:
        return "success"
    if "跳过" in message or "已关闭" in message or "已停止" in message or "skip" in lowered or "closed" in lowered or "stopped" in lowered:
        return "warning"
    if "进度" in message or "%" in message or "正在" in message or "progress" in lowered or "processing" in lowered or "analyzing" in lowered or "translating" in lowered:
        return "progress"
    if "开始" in message or "打开" in message or "提交" in message or "定位" in message or "start" in lowered or "open" in lowered or "submit" in lowered:
        return "action"
    if "worker" in lowered or "日志文件" in message or "并发数" in message or "log file" in lowered or "concurrency" in lowered:
        return "muted"
    return "info"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MetaBatch")
        self.setMinimumSize(1180, 860)
        self.resize(1280, 920)
        self.setWindowIcon(QIcon(str(ensure_app_icon())))

        self._settings_store = SettingsStore()
        self._settings, self._settings_warning = self._settings_store.load()
        self._worker_thread: QThread | None = None
        self._worker: WorkflowWorker | None = None
        self._translation_probe_thread: QThread | None = None
        self._translation_probe_worker: TranslationProbeWorker | None = None
        self._worker_log_outputs: dict[int, ColoredLogView] = {}
        self._current_worker_count = 0
        self._worker_progress_cards: dict[int, dict[str, object]] = {}
        self._translation_enabled = False
        self._threads_pending_close = 0

        self._build_ui()
        self._load_settings_into_ui()
        if self._settings_warning:
            self.append_log(None, self._settings_warning)

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        self.tabs = WheelGuardTabWidget()
        root_layout.addWidget(self.tabs, 1)

        self.config_tab = self._make_scroll_tab()
        self.run_tab = self._make_scroll_tab()
        self.progress_tab = self._make_scroll_tab()
        self.log_tab = self._make_scroll_tab()
        self.language_tab = self._make_scroll_tab()

        self.tabs.addTab(self.config_tab["container"], tr("配置"))
        self.tabs.addTab(self.run_tab["container"], tr("运行"))
        self.tabs.addTab(self.progress_tab["container"], tr("进度"))
        self.tabs.addTab(self.log_tab["container"], tr("日志"))
        # 标签名固定双语，不随界面语言切换：语言不对的用户也能一眼找到这里。
        self.tabs.addTab(self.language_tab["container"], "语言 / Language")

        self._build_config_tab(self.config_tab["content"])
        self._build_run_tab(self.run_tab["content"])
        self._build_progress_tab(self.progress_tab["content"])
        self._build_log_tab(self.log_tab["content"])
        self._build_language_tab(self.language_tab["content"])
        self._rebuild_worker_progress_cards(0)

    def _make_scroll_tab(self) -> dict[str, QWidget]:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        return {"container": container, "content": content}

    def _build_config_tab(self, parent: QWidget) -> None:
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(12)

        profile_box = QGroupBox(tr("配置管理"))
        profile_layout = QHBoxLayout(profile_box)
        self.profile_combo = WheelGuardComboBox()
        self.profile_combo.setEditable(True)
        self.profile_combo.activated.connect(self._on_profile_activated)
        self.save_profile_button = QPushButton(tr("保存当前"))
        self.save_profile_button.clicked.connect(self._save_profile)
        self.save_as_button = QPushButton(tr("另存为"))
        self.save_as_button.clicked.connect(self._save_profile_as)
        self.delete_profile_button = QPushButton(tr("删除"))
        self.delete_profile_button.clicked.connect(self._delete_profile)
        profile_layout.addWidget(self.profile_combo, 1)
        profile_layout.addWidget(self.save_profile_button)
        profile_layout.addWidget(self.save_as_button)
        profile_layout.addWidget(self.delete_profile_button)
        layout.addWidget(profile_box)

        form_box = QGroupBox(tr("运行设置"))
        form_layout = QGridLayout(form_box)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(10)

        language_for_labels = get_ui_language()

        self.input_dir_edit = QLineEdit()
        self.output_dir_edit = QLineEdit()
        self.input_column_edit = QLineEdit()
        self.enable_translation_checkbox = QCheckBox(tr("启用翻译"))
        self.enable_translation_checkbox.setChecked(True)
        self.api_base_url_edit = QLineEdit()
        self.api_base_url_edit.setPlaceholderText("https://aibz.cc")
        self.api_format_combo = WheelGuardComboBox()
        self.api_format_combo.addItem(tr("Anthropic Messages（原生）"), ApiFormat.ANTHROPIC_MESSAGES.value)
        self.api_format_combo.addItem("OpenAI Chat Completions", ApiFormat.OPENAI_CHAT.value)
        self.api_format_combo.addItem(tr("Responses（原生）"), ApiFormat.OPENAI_RESPONSES.value)
        self.api_format_combo.currentIndexChanged.connect(self._on_api_format_changed)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.auth_field_combo = WheelGuardComboBox()
        self.auth_field_combo.setEditable(True)
        self.auth_field_combo.addItems(["ANTHROPIC_AUTH_TOKEN", "Authorization", "x-api-key"])
        self.auth_field_combo.setCurrentText("ANTHROPIC_AUTH_TOKEN")
        self.api_model_combo = WheelGuardComboBox()
        self.api_model_combo.setEditable(True)
        self.api_model_combo.setInsertPolicy(QComboBox.NoInsert)
        self.fetch_models_button = QPushButton(tr("获取模型"))
        self.fetch_models_button.setToolTip(tr("从当前 API Base URL 获取模型列表"))
        self.fetch_models_button.clicked.connect(lambda: self._start_translation_probe("models"))
        self.test_translation_button = QPushButton(tr("测试连通性"))
        self.test_translation_button.setToolTip(tr("用当前模型发送一次最小翻译请求"))
        self.test_translation_button.clicked.connect(lambda: self._start_translation_probe("test"))
        self.translation_probe_status_label = QLabel(tr("翻译接口：未检测"))
        self.translation_probe_status_label.setStyleSheet("color: #666666;")
        self.analysis_mode_combo = WheelGuardComboBox()
        self.analysis_mode_combo.addItem(AnalysisMode.EXPRESS.value)
        self.download_xlsx_radio = QRadioButton(tr("仅 Excel (xlsx)"))
        self.download_zip_radio = QRadioButton(tr("完整 Zip 包"))
        self.download_xlsx_radio.setChecked(True)
        self.headless_checkbox = QCheckBox(tr("Headless 模式"))
        self.headless_checkbox.setChecked(True)
        self.translation_target_combo = WheelGuardComboBox()
        self.translation_target_combo.setToolTip(
            tr("把 Enrichment 表的 Description 列翻译成所选语言；结果列名也会使用对应语言。")
        )
        for target in TRANSLATION_TARGETS:
            label = target.label_en if language_for_labels == "en" else target.label_zh
            self.translation_target_combo.addItem(label, target.code)

        self.metascape_connection_mode_combo = WheelGuardComboBox()
        self.metascape_connection_mode_combo.addItem(tr("直连"), ConnectionMode.DIRECT.value)
        self.metascape_connection_mode_combo.addItem(tr("代理"), ConnectionMode.PROXY.value)
        self.translation_connection_mode_combo = WheelGuardComboBox()
        self.translation_connection_mode_combo.addItem(tr("直连"), ConnectionMode.DIRECT.value)
        self.translation_connection_mode_combo.addItem(tr("代理"), ConnectionMode.PROXY.value)
        self.proxy_host_edit = QLineEdit("127.0.0.1")
        self.proxy_port_edit = QLineEdit()
        self.proxy_port_edit.setPlaceholderText(tr("例如 51888"))
        self.concurrency_edit = QLineEdit("5")
        self.concurrency_edit.setPlaceholderText("1-32")

        browse_input_button = QPushButton(tr("浏览"))
        browse_input_button.clicked.connect(self._browse_input)
        browse_output_button = QPushButton(tr("浏览"))
        browse_output_button.clicked.connect(self._browse_output)

        row = 0
        self._add_row(form_layout, row, tr("基因列表文件夹"), self.input_dir_edit, browse_input_button)
        row += 1
        self._add_row(form_layout, row, tr("输出结果文件夹"), self.output_dir_edit, browse_output_button)
        row += 1
        self._add_row(form_layout, row, tr("分析模式"), self.analysis_mode_combo)
        row += 1
        download_widget = QWidget()
        download_layout = QHBoxLayout(download_widget)
        download_layout.setContentsMargins(0, 0, 0, 0)
        download_layout.addWidget(self.download_xlsx_radio)
        download_layout.addWidget(self.download_zip_radio)
        download_layout.addStretch(1)
        self._add_row(form_layout, row, tr("下载类型"), download_widget)
        row += 1
        self._add_row(form_layout, row, tr("基因所在列"), self.input_column_edit)
        row += 1
        helper = QLabel(tr("可留空；也支持表头名、1-based 列号、Excel 列字母。"))
        helper.setStyleSheet("color: #666666;")
        form_layout.addWidget(helper, row, 1, 1, 2)
        row += 1
        self._add_row(form_layout, row, tr("是否翻译"), self.enable_translation_checkbox)
        row += 1
        self._add_row(form_layout, row, tr("翻译目标语言"), self.translation_target_combo)
        row += 1
        self._add_row(form_layout, row, tr("API Base URL"), self.api_base_url_edit)
        row += 1
        self._add_row(form_layout, row, tr("API 格式"), self.api_format_combo)
        row += 1
        self._add_row(form_layout, row, tr("API Key"), self.api_key_edit)
        row += 1
        self._add_row(form_layout, row, tr("认证字段"), self.auth_field_combo)
        row += 1
        model_widget = QWidget()
        model_layout = QHBoxLayout(model_widget)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.setSpacing(8)
        model_layout.addWidget(self.api_model_combo, 1)
        model_layout.addWidget(self.fetch_models_button)
        model_layout.addWidget(self.test_translation_button)
        self._add_row(form_layout, row, tr("API Model"), model_widget)
        row += 1
        form_layout.addWidget(self.translation_probe_status_label, row, 1, 1, 2)
        row += 1
        self._add_row(form_layout, row, tr("Metascape 连接方式"), self.metascape_connection_mode_combo)
        row += 1
        self._add_row(form_layout, row, tr("翻译 API 连接方式"), self.translation_connection_mode_combo)
        row += 1
        self._add_row(form_layout, row, tr("代理主机"), self.proxy_host_edit)
        row += 1
        self._add_row(form_layout, row, tr("代理端口"), self.proxy_port_edit)
        row += 1
        self._add_row(form_layout, row, tr("并发数量"), self.concurrency_edit)
        row += 1
        form_layout.addWidget(self.headless_checkbox, row, 1, 1, 2)
        layout.addWidget(form_box)
        layout.addStretch(1)

    def _build_run_tab(self, parent: QWidget) -> None:
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(12)

        action_box = QGroupBox(tr("执行"))
        action_layout = QHBoxLayout(action_box)
        self.start_button = QPushButton(tr("开始处理"))
        self.start_button.clicked.connect(self._start)
        self.stop_button = QPushButton(tr("停止"))
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop)
        self.exit_button = QPushButton(tr("退出"))
        self.exit_button.clicked.connect(self.close)
        action_layout.addWidget(self.start_button)
        action_layout.addWidget(self.stop_button)
        action_layout.addWidget(self.exit_button)
        action_layout.addStretch(1)
        layout.addWidget(action_box)

        info_box = QGroupBox(tr("提示"))
        info_layout = QVBoxLayout(info_box)
        self.run_hint_label = QLabel(tr("开始前请先配置输入目录、输出目录和必要参数。"))
        self.run_hint_label.setWordWrap(True)
        info_layout.addWidget(self.run_hint_label)
        self.log_dir_label = QLabel(tr("日志目录：{path}").format(path=get_logs_dir()))
        self.log_dir_label.setWordWrap(True)
        info_layout.addWidget(self.log_dir_label)
        layout.addWidget(info_box)
        layout.addStretch(1)

    def _build_progress_tab(self, parent: QWidget) -> None:
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(12)

        progress_box = QGroupBox(tr("任务状态"))
        progress_layout = QGridLayout(progress_box)
        progress_layout.setHorizontalSpacing(12)
        progress_layout.setVerticalSpacing(8)

        self.batch_progress = QProgressBar()
        self.batch_progress_text = QLabel("0/0 (0%)")
        self.analysis_progress = QProgressBar()
        self.translation_progress = QProgressBar()
        self.status_label = QLabel(tr("状态：未开始"))
        self.analysis_status_label = QLabel(tr("Metascape 分析进度：等待开始"))
        self.translation_status_label = QLabel(tr("翻译进度：等待开始"))

        self._add_progress_row(progress_layout, 0, tr("批处理进度"), self.batch_progress, self.batch_progress_text)
        self._add_progress_row(progress_layout, 1, tr("Metascape 分析进度"), self.analysis_progress)
        self._add_progress_row(progress_layout, 2, tr("翻译进度"), self.translation_progress)
        progress_layout.addWidget(self.status_label, 3, 0, 1, 2)
        progress_layout.addWidget(self.analysis_status_label, 4, 0, 1, 2)
        progress_layout.addWidget(self.translation_status_label, 5, 0, 1, 2)
        layout.addWidget(progress_box)
        self.worker_progress_box = QGroupBox(tr("Worker 进度"))
        self.worker_progress_layout = QVBoxLayout(self.worker_progress_box)
        self.worker_progress_layout.setContentsMargins(10, 10, 10, 10)
        self.worker_progress_layout.setSpacing(10)
        layout.addWidget(self.worker_progress_box)
        layout.addStretch(1)

    def _build_log_tab(self, parent: QWidget) -> None:
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(12)
        log_box = QGroupBox(tr("日志"))
        log_layout = QVBoxLayout(log_box)
        self.log_tabs = WheelGuardTabWidget()
        self.log_tabs.setDocumentMode(True)
        self.log_output = self._create_log_output()
        self.log_tabs.addTab(self.log_output, tr("总日志"))
        log_layout.addWidget(self.log_tabs)
        layout.addWidget(log_box)
        self._rebuild_worker_log_tabs(0)

    def _build_language_tab(self, parent: QWidget) -> None:
        # 本页文案固定双语，不做 tr 翻译：语言停在错误值的用户也要能看懂本页。
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(12)

        language_box = QGroupBox("界面语言 / UI Language")
        language_layout = QGridLayout(language_box)
        language_layout.setHorizontalSpacing(12)
        language_layout.setVerticalSpacing(10)

        self.ui_language_combo = WheelGuardComboBox()
        self.ui_language_combo.setToolTip("切换界面显示语言，立即生效。/ Switch the UI display language. Takes effect immediately.")
        self.ui_language_combo.blockSignals(True)
        for language_code, language_label in UI_LANGUAGES.items():
            self.ui_language_combo.addItem(language_label, language_code)
        self.ui_language_combo.blockSignals(False)
        self.ui_language_combo.currentIndexChanged.connect(self._on_ui_language_changed)

        self._add_row(language_layout, 0, "界面语言 / UI Language", self.ui_language_combo)
        hint = QLabel("切换后界面立即刷新；界面语言会随应用设置保存。\n"
                      "The interface refreshes immediately after switching; the choice is saved with the app settings.")
        hint.setStyleSheet("color: #666666;")
        hint.setWordWrap(True)
        language_layout.addWidget(hint, 1, 1, 1, 2)
        layout.addWidget(language_box)
        layout.addStretch(1)

    def _create_log_output(self) -> ColoredLogView:
        output = ColoredLogView()
        return output

    def _rebuild_worker_log_tabs(self, worker_count: int) -> None:
        while self.log_tabs.count() > 1:
            widget = self.log_tabs.widget(1)
            self.log_tabs.removeTab(1)
            if widget is not None:
                widget.deleteLater()

        self._worker_log_outputs = {}
        self._current_worker_count = worker_count
        for worker_id in range(1, worker_count + 1):
            output = self._create_log_output()
            self._worker_log_outputs[worker_id] = output
            self.log_tabs.addTab(output, f"Worker {worker_id}")

    def _rebuild_worker_progress_cards(self, worker_count: int) -> None:
        while self.worker_progress_layout.count():
            item = self.worker_progress_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

        self._worker_progress_cards = {}
        if worker_count <= 0:
            empty = QLabel(tr("暂无 worker。"))
            empty.setStyleSheet("color: #757575;")
            self.worker_progress_layout.addWidget(empty)
            return

        for worker_id in range(1, worker_count + 1):
            card = self._create_worker_progress_card(worker_id)
            self._worker_progress_cards[worker_id] = card
            self.worker_progress_layout.addWidget(card["container"])  # type: ignore[arg-type]
        self.worker_progress_layout.addStretch(1)

    def _create_worker_progress_card(self, worker_id: int) -> dict[str, object]:
        container = QGroupBox(f"Worker {worker_id}")
        layout = QGridLayout(container)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)

        current_file = QLabel(tr("当前文件：-"))
        current_stage = QLabel(tr("当前阶段：等待开始"))
        current_path = QLabel(tr("文件路径：-"))
        current_file.setWordWrap(True)
        current_stage.setWordWrap(True)
        current_path.setWordWrap(True)
        metascape_bar = QProgressBar()
        metascape_bar.setRange(0, 100)
        metascape_bar.setValue(0)
        metascape_status = QLabel(tr("Metascape：等待开始"))
        metascape_status.setWordWrap(True)
        translation_bar = QProgressBar()
        translation_bar.setRange(0, 100)
        translation_bar.setValue(0)
        translation_status = QLabel(tr("翻译：等待开始"))
        translation_status.setWordWrap(True)
        last_status = QLabel(tr("最近状态：-"))
        last_status.setWordWrap(True)

        layout.addWidget(current_file, 0, 0, 1, 2)
        layout.addWidget(current_stage, 1, 0, 1, 2)
        layout.addWidget(current_path, 2, 0, 1, 2)
        layout.addWidget(QLabel("Metascape"), 3, 0)
        layout.addWidget(metascape_bar, 3, 1)
        layout.addWidget(metascape_status, 4, 0, 1, 2)
        layout.addWidget(QLabel(tr("翻译")), 5, 0)
        layout.addWidget(translation_bar, 5, 1)
        layout.addWidget(translation_status, 6, 0, 1, 2)
        layout.addWidget(last_status, 7, 0, 1, 2)

        return {
            "container": container,
            "current_file": current_file,
            "current_path": current_path,
            "current_stage": current_stage,
            "metascape_bar": metascape_bar,
            "metascape_status": metascape_status,
            "translation_bar": translation_bar,
            "translation_status": translation_status,
            "last_status": last_status,
        }

    def _add_row(self, layout: QGridLayout, row: int, label: str, widget: QWidget, extra: QWidget | None = None) -> None:
        layout.addWidget(QLabel(label), row, 0)
        layout.addWidget(widget, row, 1)
        if extra is not None:
            layout.addWidget(extra, row, 2)

    def _add_progress_row(self, layout: QGridLayout, row: int, label: str, widget: QProgressBar, extra: QWidget | None = None) -> None:
        widget.setRange(0, 100)
        widget.setValue(0)
        layout.addWidget(QLabel(label), row, 0)
        layout.addWidget(widget, row, 1)
        if extra is not None:
            layout.addWidget(extra, row, 2)

    def _profile_names(self) -> list[str]:
        return list(self._settings.profiles.keys())

    def _collect_form_values(self) -> dict[str, Any]:
        return {
            "input_dir": self.input_dir_edit.text(),
            "output_dir": self.output_dir_edit.text(),
            "input_column": self.input_column_edit.text(),
            "enable_translation": self.enable_translation_checkbox.isChecked(),
            "api_base_url": self.api_base_url_edit.text(),
            "api_format": self.api_format_combo.currentData(),
            "api_key": self.api_key_edit.text(),
            "api_model": self.api_model_combo.currentText(),
            "auth_field": self.auth_field_combo.currentText(),
            "translation_target": self.translation_target_combo.currentData(),
            "headless": self.headless_checkbox.isChecked(),
            "download_type": DownloadType.XLSX_ONLY.value if self.download_xlsx_radio.isChecked() else DownloadType.ZIP_WITH_EXTRACT.value,
            "metascape_connection_mode": self.metascape_connection_mode_combo.currentData(),
            "translation_connection_mode": self.translation_connection_mode_combo.currentData(),
            "proxy_host": self.proxy_host_edit.text(),
            "proxy_port": self.proxy_port_edit.text(),
            "concurrency": self.concurrency_edit.text(),
        }

    def _apply_form_values(self, values: dict[str, Any]) -> None:
        self.input_dir_edit.setText(str(values.get("input_dir", "")))
        self.output_dir_edit.setText(str(values.get("output_dir", "")))
        self.input_column_edit.setText(str(values.get("input_column", "")))
        self.enable_translation_checkbox.setChecked(bool(values.get("enable_translation", True)))
        self.api_base_url_edit.setText(str(values.get("api_base_url", "")))
        self._set_combo_by_data(self.api_format_combo, str(values.get("api_format", ApiFormat.ANTHROPIC_MESSAGES.value)))
        self.api_key_edit.setText(str(values.get("api_key", "")))
        self.api_model_combo.setCurrentText(str(values.get("api_model", "")))
        self._set_combo_by_data(
            self.translation_target_combo,
            normalize_translation_target(values.get("translation_target")),
        )
        self.auth_field_combo.setCurrentText(str(values.get("auth_field", "ANTHROPIC_AUTH_TOKEN")))
        self.headless_checkbox.setChecked(bool(values.get("headless", True)))
        download_type = str(values.get("download_type", DownloadType.XLSX_ONLY.value))
        self.download_xlsx_radio.setChecked(download_type == DownloadType.XLSX_ONLY.value)
        self.download_zip_radio.setChecked(download_type == DownloadType.ZIP_WITH_EXTRACT.value)
        self._set_combo_by_data(self.metascape_connection_mode_combo, str(values.get("metascape_connection_mode", ConnectionMode.DIRECT.value)))
        self._set_combo_by_data(self.translation_connection_mode_combo, str(values.get("translation_connection_mode", ConnectionMode.DIRECT.value)))
        self.proxy_host_edit.setText(str(values.get("proxy_host", "127.0.0.1")))
        self.proxy_port_edit.setText(str(values.get("proxy_port", "")))
        self.concurrency_edit.setText(str(values.get("concurrency", "5")))

    def _build_profile_from_form(self, name: str) -> SavedProfile:
        values = self._collect_form_values()
        return SavedProfile(
            name=name,
            input_dir=str(values["input_dir"]).strip(),
            output_dir=str(values["output_dir"]).strip(),
            download_type=str(values["download_type"]).strip(),
            input_column=str(values["input_column"]).strip(),
            enable_translation=bool(values["enable_translation"]),
            api_base_url=str(values["api_base_url"]).strip(),
            api_key=str(values["api_key"]).strip(),
            api_model=str(values["api_model"]).strip(),
            api_format=str(values["api_format"]),
            auth_field=str(values["auth_field"]).strip() or "ANTHROPIC_AUTH_TOKEN",
            translation_target=normalize_translation_target(values.get("translation_target")),
            headless=bool(values["headless"]),
            metascape_connection_mode=str(values["metascape_connection_mode"]),
            translation_connection_mode=str(values["translation_connection_mode"]),
            proxy_host=str(values["proxy_host"]).strip(),
            proxy_port=_parse_proxy_port(str(values["proxy_port"])),
            concurrency=_parse_concurrency(str(values["concurrency"])),
        )

    def _persist_settings(self) -> None:
        self._settings_store.save(self._settings)

    def _load_settings_into_ui(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItems(self._profile_names())
        current_name = self._settings.last_profile_name or DEFAULT_PROFILE_NAME
        self.profile_combo.setCurrentText(current_name)
        self.profile_combo.blockSignals(False)
        self._sync_ui_language_combo()

        profile = self._settings.profiles.get(current_name)
        if profile is None and self._settings.profiles:
            profile = next(iter(self._settings.profiles.values()))
            self.profile_combo.setCurrentText(profile.name)
        if profile is not None:
            self._apply_profile(profile)

    def _sync_ui_language_combo(self) -> None:
        self.ui_language_combo.blockSignals(True)
        self._set_combo_by_data(self.ui_language_combo, self._settings.ui_language)
        self.ui_language_combo.blockSignals(False)

    def _on_ui_language_changed(self, _index: int) -> None:
        if self._worker_thread is not None and self._worker_thread.isRunning():
            self._sync_ui_language_combo()
            QMessageBox.information(
                self,
                tr("界面语言"),
                tr("任务运行中无法切换界面语言，请等待任务结束后再试。"),
            )
            return
        language = str(self.ui_language_combo.currentData() or "zh")
        if language == self._settings.ui_language:
            return
        self._settings.ui_language = language
        self._persist_settings()
        set_ui_language(language)
        self._rebuild_ui()
        self.append_log(None, tr("界面语言已切换，界面已刷新。"))

    def _rebuild_ui(self) -> None:
        """切换界面语言后整体重建界面，并尽量保留用户未保存的表单内容。"""
        previous_profile_name = self.profile_combo.currentText()
        values = self._collect_form_values()
        old_central = self.centralWidget()
        self._build_ui()
        if old_central is not None:
            old_central.deleteLater()
        self._sync_ui_language_combo()
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentText(previous_profile_name)
        self.profile_combo.blockSignals(False)
        self._apply_form_values(values)

    def _apply_profile(self, profile: SavedProfile) -> None:
        self.input_dir_edit.setText(profile.input_dir)
        self.output_dir_edit.setText(profile.output_dir)
        self.input_column_edit.setText(profile.input_column)
        self.enable_translation_checkbox.setChecked(profile.enable_translation)
        self.api_base_url_edit.setText(profile.api_base_url)
        self._set_combo_by_data(self.api_format_combo, profile.api_format)
        self.api_key_edit.setText(profile.api_key)
        self.api_model_combo.setCurrentText(profile.api_model)
        self._set_combo_by_data(self.translation_target_combo, normalize_translation_target(profile.translation_target))
        self.auth_field_combo.setCurrentText(profile.auth_field)
        self.headless_checkbox.setChecked(profile.headless)
        self.download_xlsx_radio.setChecked(profile.download_type == DownloadType.XLSX_ONLY.value)
        self.download_zip_radio.setChecked(profile.download_type == DownloadType.ZIP_WITH_EXTRACT.value)
        self._set_combo_by_data(self.metascape_connection_mode_combo, profile.metascape_connection_mode)
        self._set_combo_by_data(self.translation_connection_mode_combo, profile.translation_connection_mode)
        self.proxy_host_edit.setText(profile.proxy_host)
        self.proxy_port_edit.setText("" if profile.proxy_port is None else str(profile.proxy_port))
        self.concurrency_edit.setText(str(profile.concurrency))

    @staticmethod
    def _set_combo_by_data(combo: QComboBox, data: str) -> None:
        index = combo.findData(data)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _on_api_format_changed(self, _index: int) -> None:
        format_value = self.api_format_combo.currentData()
        if format_value == ApiFormat.ANTHROPIC_MESSAGES.value:
            self.auth_field_combo.setCurrentText("ANTHROPIC_AUTH_TOKEN")
        else:
            self.auth_field_combo.setCurrentText("Authorization")

    def _on_profile_activated(self, _index: int) -> None:
        profile_name = self.profile_combo.currentText().strip()
        if not profile_name or profile_name not in self._settings.profiles:
            return
        self._settings.last_profile_name = profile_name
        self._persist_settings()
        self._apply_profile(self._settings.profiles[profile_name])
        self.append_log(None, tr("已切换到配置：{name}").format(name=profile_name))

    def _save_profile_common(self, name: str, overwrite: bool) -> bool:
        if not name:
            QMessageBox.critical(self, tr("配置错误"), tr("请先输入或选择配置名称。"))
            return False
        if not overwrite and name in self._settings.profiles:
            QMessageBox.critical(self, tr("配置错误"), tr("配置“{name}”已存在，请换一个名称。").format(name=name))
            return False

        try:
            self._settings.profiles[name] = self._build_profile_from_form(name)
        except ValueError as exc:
            QMessageBox.critical(self, tr("配置错误"), str(exc))
            return False
        self._settings.last_profile_name = name
        self._persist_settings()
        self._load_settings_into_ui()
        self.profile_combo.setCurrentText(name)
        self.append_log(None, tr("配置已保存：{name}").format(name=name))
        return True

    def _save_profile(self) -> None:
        self._save_profile_common(self.profile_combo.currentText().strip(), overwrite=True)

    def _save_profile_as(self) -> None:
        name, accepted = QInputDialog.getText(
            self, tr("另存为"), tr("请输入新的配置名称："), text=self.profile_combo.currentText().strip()
        )
        if not accepted or not name.strip():
            return
        self._save_profile_common(name.strip(), overwrite=False)

    def _delete_profile(self) -> None:
        name = self.profile_combo.currentText().strip()
        if name not in self._settings.profiles:
            return
        if len(self._settings.profiles) == 1:
            QMessageBox.critical(self, tr("配置错误"), tr("至少需要保留一套配置。"))
            return
        if QMessageBox.question(self, tr("删除配置"), tr("确定删除配置“{name}”吗？").format(name=name)) != QMessageBox.Yes:
            return
        del self._settings.profiles[name]
        self._settings.last_profile_name = next(iter(self._settings.profiles))
        self._persist_settings()
        self._load_settings_into_ui()
        self.append_log(None, tr("已删除配置：{name}").format(name=name))

    def _browse_input(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, tr("选择基因列表文件夹"), self.input_dir_edit.text() or "")
        if selected:
            self.input_dir_edit.setText(selected)

    def _browse_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, tr("选择输出结果文件夹"), self.output_dir_edit.text() or "")
        if selected:
            self.output_dir_edit.setText(selected)

    def _start_translation_probe(self, action: str) -> None:
        if self._translation_probe_thread is not None:
            return

        base_url = self.api_base_url_edit.text().strip()
        api_key = self.api_key_edit.text().strip()
        model = self.api_model_combo.currentText().strip()
        if not base_url or not api_key:
            QMessageBox.warning(self, tr("翻译接口"), tr("请先填写 API Base URL 和 API Key。"))
            return
        if action == "test" and not model:
            QMessageBox.warning(self, tr("翻译接口"), tr("测试连通性前请先选择或填写 API Model。"))
            return

        try:
            connection_mode = ConnectionMode.from_value(str(self.translation_connection_mode_combo.currentData()))
            api_format = ApiFormat.from_value(str(self.api_format_combo.currentData()))
            proxy_port = _parse_proxy_port(self.proxy_port_edit.text())
            if connection_mode is ConnectionMode.PROXY and proxy_port is None:
                raise ValueError(tr("翻译 API 使用代理时请输入有效端口。"))
            proxy_url = (
                f"http://{self.proxy_host_edit.text().strip() or '127.0.0.1'}:{proxy_port}"
                if connection_mode is ConnectionMode.PROXY and proxy_port is not None
                else None
            )
        except ValueError as exc:
            QMessageBox.warning(self, tr("翻译接口"), str(exc))
            return

        self.fetch_models_button.setEnabled(False)
        self.test_translation_button.setEnabled(False)
        self.translation_probe_status_label.setStyleSheet("color: #1565c0;")
        self.translation_probe_status_label.setText(tr("翻译接口：正在检测"))
        self.append_log(None, tr("翻译接口检测开始。"))

        self._translation_probe_thread = QThread(self)
        self._translation_probe_worker = TranslationProbeWorker(
            action,
            base_url,
            api_key,
            model,
            proxy_url,
            api_format,
            self.auth_field_combo.currentText().strip() or "ANTHROPIC_AUTH_TOKEN",
        )
        self._translation_probe_worker.moveToThread(self._translation_probe_thread)
        self._translation_probe_thread.started.connect(self._translation_probe_worker.run)
        self._translation_probe_worker.models_loaded.connect(self._on_models_loaded)
        self._translation_probe_worker.succeeded.connect(self._on_translation_probe_succeeded)
        self._translation_probe_worker.failed.connect(self._on_translation_probe_failed)
        self._translation_probe_worker.finished.connect(self._translation_probe_thread.quit)
        self._translation_probe_thread.finished.connect(self._cleanup_translation_probe)
        self._translation_probe_thread.start()

    def _on_models_loaded(self, models: list[str]) -> None:
        selected = self.api_model_combo.currentText().strip()
        self.api_model_combo.blockSignals(True)
        self.api_model_combo.clear()
        self.api_model_combo.addItems(models)
        self.api_model_combo.setCurrentText(selected or models[0])
        self.api_model_combo.blockSignals(False)
        message = tr("已获取 {count} 个模型。").format(count=len(models))
        self.translation_probe_status_label.setStyleSheet("color: #2e7d32;")
        self.translation_probe_status_label.setText(tr("翻译接口：{message}").format(message=message))
        self.append_log(None, tr("翻译接口：{message}").format(message=message))

    def _on_translation_probe_succeeded(self, message: str) -> None:
        self.translation_probe_status_label.setStyleSheet("color: #2e7d32;")
        self.translation_probe_status_label.setText(tr("翻译接口：{message}").format(message=message))
        self.append_log(None, tr("翻译接口：{message}").format(message=message))

    def _on_translation_probe_failed(self, message: str) -> None:
        self.translation_probe_status_label.setStyleSheet("color: #c62828;")
        self.translation_probe_status_label.setText(tr("翻译接口：检测失败"))
        self.append_log(None, tr("翻译接口检测失败：{message}").format(message=message))
        QMessageBox.warning(self, tr("翻译接口检测失败"), message)

    def _cleanup_translation_probe(self) -> None:
        if self._translation_probe_worker is not None:
            self._translation_probe_worker.deleteLater()
            self._translation_probe_worker = None
        if self._translation_probe_thread is not None:
            self._translation_probe_thread.deleteLater()
            self._translation_probe_thread = None
        self.fetch_models_button.setEnabled(True)
        self.test_translation_button.setEnabled(True)

    def _start(self) -> None:
        try:
            config = _build_config(self._collect_form_values())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("配置错误"), str(exc))
            return

        self._save_profile_common(self.profile_combo.currentText().strip() or DEFAULT_PROFILE_NAME, overwrite=True)

        self.log_output.clear()
        self._rebuild_worker_log_tabs(config.concurrency)
        for worker_output in self._worker_log_outputs.values():
            worker_output.clear()
        self._rebuild_worker_progress_cards(config.concurrency)
        self.batch_progress.setValue(0)
        self.batch_progress_text.setText("0/0 (0%)")
        self.analysis_progress.setValue(0)
        self.translation_progress.setValue(0)
        self.status_label.setText(tr("状态：开始处理"))
        self.analysis_status_label.setText(tr("Metascape 分析进度：等待开始"))
        self.translation_status_label.setText(
            tr("翻译进度：等待开始") if config.enable_translation else tr("翻译进度：已关闭")
        )

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.ui_language_combo.setEnabled(False)
        self._translation_enabled = config.enable_translation

        self._worker_thread = QThread(self)
        self._worker = WorkflowWorker(config, WorkflowController())
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.log.connect(self.append_log)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.done.connect(self._worker_thread.quit)
        self._worker.error.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._cleanup_worker)
        self._worker_thread.start()

    def _stop(self) -> None:
        if self._worker is not None:
            self._worker.request_stop()
            self.append_log(None, tr("已请求停止，当前文件将在安全点停止。"))

    def _cleanup_worker(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._worker_thread is not None:
            self._worker_thread.deleteLater()
            self._worker_thread = None

    def _on_progress(
        self,
        current: int,
        total: int,
        status: str,
        analysis_percent: object,
        analysis_status: object,
        translation_percent: object,
        translation_status: object,
        worker_id: object,
        current_path: object,
    ) -> None:
        percent = 0 if total == 0 else int((current / total) * 100)
        self.batch_progress.setValue(percent)
        self.batch_progress_text.setText(f"{current}/{total} ({percent}%)")
        if worker_id is None:
            self.status_label.setText(tr("状态：{status}").format(status=status))
        else:
            self.status_label.setText(tr("状态：Worker {worker} - {status}").format(worker=worker_id, status=status))
        if analysis_percent is not None:
            self.analysis_progress.setValue(int(analysis_percent))
        if analysis_status:
            if worker_id is not None:
                prefix = tr("Metascape 分析进度（Worker {worker}）").format(worker=worker_id)
            else:
                prefix = tr("Metascape 分析进度")
            self.analysis_status_label.setText(tr("{prefix}：{status}").format(prefix=prefix, status=analysis_status))
        if translation_percent is not None:
            self.translation_progress.setValue(int(translation_percent))
        if translation_status:
            if worker_id is not None:
                prefix = tr("翻译进度（Worker {worker}）").format(worker=worker_id)
            else:
                prefix = tr("翻译进度")
            self.translation_status_label.setText(tr("{prefix}：{status}").format(prefix=prefix, status=translation_status))
        if worker_id is not None:
            self._update_worker_progress_card(worker_id, status, analysis_percent, analysis_status, translation_percent, translation_status, current_path)

    def _on_done(self, results: list[TaskResult]) -> None:
        self.append_log(None, _build_summary(results))
        self.batch_progress.setValue(100)
        self.analysis_progress.setValue(100)
        self.status_label.setText(tr("状态：处理结束"))
        self.analysis_status_label.setText(tr("Metascape 分析进度：全部任务已结束"))
        if self._translation_enabled:
            self.translation_progress.setValue(100)
            self.translation_status_label.setText(tr("翻译进度：全部任务已结束"))
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.ui_language_combo.setEnabled(True)

    def _on_error(self, message: str) -> None:
        self.append_log(None, tr("发生未处理异常：{message}").format(message=message))
        self.status_label.setText(tr("状态：发生异常"))
        self.analysis_status_label.setText(tr("Metascape 分析进度：发生异常"))
        self.translation_status_label.setText(tr("翻译进度：发生异常"))
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.ui_language_combo.setEnabled(True)

    def append_log(self, worker_id: object, message: str) -> None:
        self.log_output.append_message(message)
        if worker_id is None:
            return
        try:
            worker_number = int(worker_id)
        except (TypeError, ValueError):
            return
        output = self._worker_log_outputs.get(worker_number)
        if output is None:
            return
        output.append_message(message)

    def _update_worker_progress_card(
        self,
        worker_id: int,
        status: str,
        analysis_percent: object,
        analysis_status: object,
        translation_percent: object,
        translation_status: object,
        current_path: object,
    ) -> None:
        card = self._worker_progress_cards.get(worker_id)
        if card is None:
            return

        current_file_label = card["current_file"]  # type: ignore[assignment]
        current_path_label = card["current_path"]  # type: ignore[assignment]
        current_stage_label = card["current_stage"]  # type: ignore[assignment]
        metascape_bar = card["metascape_bar"]  # type: ignore[assignment]
        metascape_status = card["metascape_status"]  # type: ignore[assignment]
        translation_bar = card["translation_bar"]  # type: ignore[assignment]
        translation_status_label = card["translation_status"]  # type: ignore[assignment]
        last_status = card["last_status"]  # type: ignore[assignment]

        if isinstance(current_stage_label, QLabel):
            current_stage_label.setText(tr("当前阶段：{status}").format(status=status))
        if isinstance(current_file_label, QLabel):
            current_file_label.setText(tr("当前文件：{status}").format(status=status))
        if isinstance(current_path_label, QLabel) and isinstance(current_path, str) and current_path.strip():
            current_path_label.setText(tr("文件路径：{path}").format(path=current_path))
        if isinstance(metascape_bar, QProgressBar) and analysis_percent is not None:
            metascape_bar.setValue(int(analysis_percent))
        if isinstance(metascape_status, QLabel) and analysis_status:
            metascape_status.setText(tr("Metascape：{status}").format(status=analysis_status))
        if isinstance(translation_bar, QProgressBar) and translation_percent is not None:
            translation_bar.setValue(int(translation_percent))
        if isinstance(translation_status_label, QLabel) and translation_status:
            translation_status_label.setText(tr("翻译：{status}").format(status=translation_status))
        if isinstance(last_status, QLabel):
            last_status.setText(tr("最近状态：{status}").format(status=status))

    def closeEvent(self, event) -> None:  # noqa: N802
        running_threads = [
            thread
            for thread in (self._worker_thread, self._translation_probe_thread)
            if thread is not None and thread.isRunning()
        ]
        if running_threads:
            # 后台线程仍在运行时直接退出会导致 QThread 销毁崩溃：请求停止后隐藏窗口，
            # 等全部相关线程结束再真正退出应用。
            if self._worker is not None:
                self._worker.request_stop()
            event.ignore()
            self.hide()
            self._threads_pending_close = len(running_threads)
            for thread in running_threads:
                thread.finished.connect(self._on_close_thread_finished)
            return
        super().closeEvent(event)

    def _on_close_thread_finished(self) -> None:
        self._threads_pending_close = max(0, self._threads_pending_close - 1)
        if self._threads_pending_close == 0:
            QApplication.instance().quit()


def run_app() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("MetaBatch")
    app.setWindowIcon(QIcon(str(ensure_app_icon())))
    app.setFont(QFont("Segoe UI", 11))
    window = MainWindow()
    window.show()
    app.exec()
