"""轻量级界面文案翻译。

以中文为源文案：``tr`` 在中文模式下原样返回，英文模式下按字典映射，
未收录的文案回退为中文原文。语言切换即时生效（GUI 会重建界面）。
``tests/test_i18n.py`` 会校验所有 ``tr("...")`` 调用的键都在词典中。
"""

from __future__ import annotations

UI_LANGUAGE_ZH = "zh"
UI_LANGUAGE_EN = "en"

UI_LANGUAGES: dict[str, str] = {UI_LANGUAGE_ZH: "中文", UI_LANGUAGE_EN: "English"}

_current_language = UI_LANGUAGE_ZH

_EN: dict[str, str] = {
    # ---- excel_processor ----
    "结果文件中未找到 Enrichment 工作表，可能因为基因过少未产生富集结果。": (
        "Enrichment worksheet not found in the result file; the gene list may be too small to produce enrichment results."
    ),
    "该文件已经存在“{column}”列，已跳过以避免重复写入。": (
        "The file already contains a \"{column}\" column; skipped to avoid duplicate writing."
    ),
    "未找到列“{header}”。": "Column \"{header}\" not found.",
    "用户已停止任务。": "Task stopped by the user.",
    # ---- gene_reader ----
    "按表头名选择列时需要可读取表头的结构化文件。": (
        "Selecting a column by header name requires a structured file with a readable header row."
    ),
    "不支持的输入格式：{suffix}": "Unsupported input format: {suffix}",
    "无法解码文件内容，请将文件另存为 UTF-8 编码：{name}": (
        "Cannot decode file content; please re-save the file as UTF-8: {name}"
    ),
    "列号必须从 1 开始。": "Column number must start from 1.",
    "未找到名为“{name}”的列。": "No column named \"{name}\" found.",
    # ---- gui: validation ----
    "代理端口必须在 1-65535 之间。": "Proxy port must be between 1 and 65535.",
    "并发数量必须在 1-32 之间。": "Concurrency must be between 1 and 32.",
    "请输入存在的基因列表文件夹路径。": "Please enter a gene list folder path that exists.",
    "请输入输出结果文件夹路径。": "Please enter an output folder path.",
    "输入目录中未找到 txt/csv/tsv/xlsx/xls 文件。": "No txt/csv/tsv/xlsx/xls files found in the input directory.",
    "Metascape 使用代理时请输入有效端口。": "Enter a valid port when Metascape uses a proxy.",
    "翻译 API 使用代理时请输入有效端口。": "Enter a valid port when the translation API uses a proxy.",
    "代理端口必须是 1-65535 之间的整数。": "Proxy port must be an integer between 1 and 65535.",
    "并发数量必须是 1-32 之间的整数。": "Concurrency must be an integer between 1 and 32.",
    "启用翻译时请输入翻译 API Base URL。": "Enter the translation API Base URL when translation is enabled.",
    "启用翻译时请输入翻译 API Key。": "Enter the translation API Key when translation is enabled.",
    "启用翻译时请输入翻译 Model。": "Enter the translation Model when translation is enabled.",
    # ---- gui: tabs / layout ----
    "配置": "Settings",
    "运行": "Run",
    "进度": "Progress",
    "日志": "Logs",
    "配置管理": "Profiles",
    "切换界面显示语言，立即生效。": "Switch the UI display language. Takes effect immediately.",
    "保存当前": "Save",
    "另存为": "Save As",
    "删除": "Delete",
    "运行设置": "Run Settings",
    "启用翻译": "Enable translation",
    "Anthropic Messages（原生）": "Anthropic Messages (native)",
    "Responses（原生）": "Responses (native)",
    "获取模型": "Fetch Models",
    "从当前 API Base URL 获取模型列表": "Fetch the model list from the current API Base URL",
    "测试连通性": "Test Connection",
    "用当前模型发送一次最小翻译请求": "Send one minimal translation request with the current model",
    "翻译接口：未检测": "Translation API: not tested",
    "仅 Excel (xlsx)": "Excel only (xlsx)",
    "完整 Zip 包": "Full Zip package",
    "Headless 模式": "Headless mode",
    "把 Enrichment 表的 Description 列翻译成所选语言；结果列名也会使用对应语言。": (
        "Translate the Description column of the Enrichment sheet into the selected language; "
        "the result column header uses the matching language."
    ),
    "直连": "Direct",
    "代理": "Proxy",
    "例如 51888": "e.g. 51888",
    "浏览": "Browse",
    "基因列表文件夹": "Gene list folder",
    "输出结果文件夹": "Output folder",
    "分析模式": "Analysis mode",
    "下载类型": "Download type",
    "基因所在列": "Gene column",
    "可留空；也支持表头名、1-based 列号、Excel 列字母。": (
        "Optional; also supports header names, 1-based column numbers, and Excel column letters."
    ),
    "是否翻译": "Translate",
    "翻译目标语言": "Target language",
    "API 格式": "API format",
    "API Key": "API Key",
    "API Base URL": "API Base URL",
    "API Model": "API Model",
    "认证字段": "Auth field",
    "Metascape 连接方式": "Metascape connection",
    "翻译 API 连接方式": "Translation API connection",
    "代理主机": "Proxy host",
    "代理端口": "Proxy port",
    "并发数量": "Concurrency",
    "执行": "Actions",
    "开始处理": "Start",
    "停止": "Stop",
    "退出": "Exit",
    "提示": "Info",
    "开始前请先配置输入目录、输出目录和必要参数。": (
        "Configure the input folder, output folder, and required parameters before starting."
    ),
    "任务状态": "Task Status",
    "状态：未开始": "Status: not started",
    "Metascape 分析进度：等待开始": "Metascape analysis: waiting to start",
    "翻译进度：等待开始": "Translation: waiting to start",
    "批处理进度": "Batch progress",
    "Metascape 分析进度": "Metascape analysis",
    "翻译进度": "Translation",
    "Worker 进度": "Worker Progress",
    "总日志": "All Logs",
    "当前文件：-": "Current file: -",
    "当前阶段：等待开始": "Current stage: waiting to start",
    "文件路径：-": "File path: -",
    "Metascape：等待开始": "Metascape: waiting to start",
    "翻译：等待开始": "Translation: waiting to start",
    "最近状态：-": "Last status: -",
    "暂无 worker。": "No workers yet.",
    "翻译": "Translation",
    # ---- gui: language switch / profiles ----
    "界面语言已切换，界面已刷新。": "UI language switched; interface refreshed.",
    "请输入新的配置名称：": "Enter a new profile name:",
    "选择基因列表文件夹": "Select gene list folder",
    "选择输出结果文件夹": "Select output folder",
    "界面语言": "UI Language",
    "任务运行中无法切换界面语言，请等待任务结束后再试。": (
        "Cannot switch the UI language while a task is running. Try again after it finishes."
    ),
    "配置错误": "Profile Error",
    "请先输入或选择配置名称。": "Enter or select a profile name first.",
    "至少需要保留一套配置。": "At least one profile must be kept.",
    "删除配置": "Delete Profile",
    "配置“{name}”已存在，请换一个名称。": "Profile \"{name}\" already exists; choose another name.",
    "确定删除配置“{name}”吗？": "Delete profile \"{name}\"?",
    "已切换到配置：{name}": "Switched to profile: {name}",
    "配置已保存：{name}": "Profile saved: {name}",
    "已删除配置：{name}": "Profile deleted: {name}",
    # ---- gui: translation probe ----
    "翻译接口": "Translation API",
    "请先填写 API Base URL 和 API Key。": "Fill in the API Base URL and API Key first.",
    "测试连通性前请先选择或填写 API Model。": "Select or enter an API Model before testing the connection.",
    "翻译接口：正在检测": "Translation API: testing",
    "翻译接口检测开始。": "Translation API check started.",
    "翻译接口：检测失败": "Translation API: check failed",
    "翻译接口检测失败": "Translation API check failed",
    "已获取 {count} 个模型。": "Fetched {count} models.",
    "翻译接口：{message}": "Translation API: {message}",
    "翻译接口检测失败：{message}": "Translation API check failed: {message}",
    "翻译接口检测异常：{error}": "Translation API check exception: {error}",
    # ---- gui: run control / progress ----
    "状态：开始处理": "Status: started",
    "状态：处理结束": "Status: finished",
    "状态：发生异常": "Status: exception occurred",
    "Metascape 分析进度：全部任务已结束": "Metascape analysis: all tasks finished",
    "Metascape 分析进度：发生异常": "Metascape analysis: exception occurred",
    "翻译进度：已关闭": "Translation: disabled",
    "翻译进度：发生异常": "Translation: exception occurred",
    "翻译进度：全部任务已结束": "Translation: all tasks finished",
    "已请求停止，当前文件将在安全点停止。": "Stop requested; the current file will stop at the next safe point.",
    "任务汇总：成功 {success}，跳过 {skipped}，失败 {failed}，停止 {stopped}。": (
        "Summary: {success} succeeded, {skipped} skipped, {failed} failed, {stopped} stopped."
    ),
    "日志目录：{path}": "Log directory: {path}",
    "发生未处理异常：{message}": "Unhandled exception: {message}",
    "状态：{status}": "Status: {status}",
    "状态：Worker {worker} - {status}": "Status: Worker {worker} - {status}",
    "Metascape 分析进度（Worker {worker}）": "Metascape analysis (Worker {worker})",
    "翻译进度（Worker {worker}）": "Translation (Worker {worker})",
    "{prefix}：{status}": "{prefix}: {status}",
    "当前阶段：{status}": "Current stage: {status}",
    "当前文件：{status}": "Current file: {status}",
    "文件路径：{path}": "File path: {path}",
    "Metascape：{status}": "Metascape: {status}",
    "翻译：{status}": "Translation: {status}",
    "最近状态：{status}": "Last status: {status}",
    # ---- metascape_client ----
    "等待 Analysis Report Page 按钮超时。": "Timed out waiting for the Analysis Report Page button.",
    "浏览器尚未启动。": "Browser has not been started.",
    "Express Analysis 页签": "Express Analysis tab",
    "基因输入框": "gene input box",
    "Submit 按钮": "Submit button",
    "已提交基因列表，等待进入分析流程": "Gene list submitted; waiting for the analysis workflow",
    "Express Analysis 按钮": "Express Analysis button",
    "Analysis Report Page 按钮": "Analysis Report Page button",
    "已启动 Express Analysis": "Express Analysis started",
    "等待 Analysis Report Page 按钮与 Metascape 分析进度。": (
        "Waiting for the Analysis Report Page button and Metascape analysis progress."
    ),
    "已进入 Analysis Report Page，等待下载入口": "Entered the Analysis Report Page; waiting for the download entry",
    "Metascape 下载完成": "Metascape download finished",
    "下载入口未提供可直接获取的链接。": "The download entry does not provide a directly fetchable link.",
    "压缩包中未找到任何 xlsx 文件。": "No xlsx file found in the archive.",
    "Zip 模式缺少解压目录参数。": "Zip mode is missing the extraction directory argument.",
    "无法定位页面元素，候选选择器：{selectors}，最后错误：{error}": (
        "Could not locate the page element; candidate selectors: {selectors}; last error: {error}"
    ),
    "{label} 点击失败，已重试 {max_attempts} 次。最后错误：{error}": (
        "{label} click failed after {max_attempts} attempts. Last error: {error}"
    ),
    "打开 Metascape：{url}": "Opening Metascape: {url}",
    "等待 networkidle 超时，继续执行页面流程。": "Timed out waiting for networkidle; continuing with the page flow.",
    "已定位基因输入框：{selector}": "Located gene input box: {selector}",
    "已定位提交按钮：{selector}": "Located submit button: {selector}",
    "已定位 Express Analysis 按钮：{selector}": "Located Express Analysis button: {selector}",
    "已定位 Analysis Report Page 按钮：{selector}": "Located Analysis Report Page button: {selector}",
    "已定位下载入口：{selector}": "Located download entry: {selector}",
    "下载入口": "download entry",
    "下载完成：{path}": "Download finished: {path}",
    "已从压缩包定位 Excel：{path}": "Located Excel in the archive: {path}",
    "直接获取下载文件失败：HTTP {status}": "Direct download fetch failed: HTTP {status}",
    "等待 Metascape 页面元素超时，请检查网络或页面选择器。原始错误：{error}": (
        "Timed out waiting for a Metascape page element; check the network or page selectors. Original error: {error}"
    ),
    "Metascape 正在分析：{percent}%": "Metascape analyzing: {percent}%",
    "{label} 点击尝试 {attempt}/{max_attempts}。": "{label} click attempt {attempt}/{max_attempts}.",
    "{label} 常规点击失败，第 {attempt} 次：{error}": "{label} regular click failed on attempt {attempt}: {error}",
    "{label} 第 {attempt} 次使用 force click 成功。": "{label} force click succeeded on attempt {attempt}.",
    "{label} force click 失败，第 {attempt} 次：{error}": "{label} force click failed on attempt {attempt}: {error}",
    "{label} 第 {attempt} 次使用 JS click 成功。": "{label} JS click succeeded on attempt {attempt}.",
    "{label} JS click 失败，第 {attempt} 次：{error}": "{label} JS click failed on attempt {attempt}: {error}",
    # ---- settings ----
    "配置文件为空，已恢复默认配置。": "The settings file is empty; defaults restored.",
    "配置加载失败，已使用默认界面状态。": "Failed to load settings; default UI state is used.",
    # ---- translator ----
    "翻译 API Key 不能为空。": "Translation API Key cannot be empty.",
    "模型列表接口": "Model list endpoint",
    "模型列表接口返回格式异常，未找到 data/models 数组。": (
        "Model list endpoint returned an unexpected format; no data/models array found."
    ),
    "模型列表接口未返回可用模型。": "Model list endpoint returned no available models.",
    "连接成功：模型 {model} 已响应。": "Connection successful: model {model} responded.",
    "未知": "unknown",
    "翻译 API Base URL 不能为空。": "Translation API Base URL cannot be empty.",
    "{operation}返回格式异常，预期 JSON 对象。": (
        "{operation} returned an unexpected format; expected a JSON object."
    ),
    "翻译失败：{error}": "Translation failed: {error}",
    "无法解析翻译结果：{payload}": "Could not parse the translation result: {payload}",
    "获取模型失败：{error}": "Failed to fetch models: {error}",
    "{operation}未返回 JSON（HTTP {status}，Content-Type: {content_type}）。": (
        "{operation} did not return JSON (HTTP {status}, Content-Type: {content_type})."
    ),
    "Anthropic 接口返回格式异常：{payload}": "Anthropic endpoint returned an unexpected format: {payload}",
    "Responses 接口返回格式异常：{payload}": "Responses endpoint returned an unexpected format: {payload}",
    "翻译接口未返回 choices：{payload}": "Translation endpoint returned no choices: {payload}",
    "翻译接口返回了空结果。": "Translation endpoint returned an empty result.",
    "翻译接口暂时不可用，HTTP {status}: {body}": "Translation endpoint temporarily unavailable, HTTP {status}: {body}",
    "翻译请求被拒绝，HTTP {status}: {body}": "Translation request rejected, HTTP {status}: {body}",
    # ---- workflow ----
    "输入目录中未找到受支持的基因列表文件。": "No supported gene list files found in the input directory.",
    "准备开始处理": "Preparing to start",
    "等待启动": "Waiting to start",
    "翻译已关闭": "Translation disabled",
    "处理结束": "Processing finished",
    "全部任务已结束": "All tasks finished",
    "当前文件处理完成": "Current file finished",
    "全部翻译流程已结束": "All translation work finished",
    "检测到已有结果文件，已跳过：{path}": "Existing result file detected; skipped: {path}",
    "文件中未读取到任何有效基因。": "No valid genes were read from the file.",
    "Metascape 开始。": "Metascape started.",
    "翻译完成": "Translation finished",
    "处理成功": "Processed successfully",
    "日志文件：{path}": "Log file: {path}",
    "并发数：{count}": "Concurrency: {count}",
    "待处理文件数：{count}": "Files to process: {count}",
    "全部任务完成，总用时 {duration}。": "All tasks finished; total time {duration}.",
    "翻译已关闭，跳过翻译阶段。": "Translation disabled; skipping the translation stage.",
    "已完成 {name}": "Finished {name}",
    "开始处理：{name}": "Start processing: {name}",
    "读取基因完成：{count} 个基因。": "Genes read: {count} genes.",
    "Metascape 完成，用时 {duration}。": "Metascape finished in {duration}.",
    "当前文件处理完成，总用时 {duration}。": "Current file finished; total time {duration}.",
    "失败 {name}": "Failed {name}",
    "秒": "s",
    "翻译开始。": "Translation started.",
    "Metascape 已完成，翻译已跳过": "Metascape finished; translation skipped",
    "等待翻译": "Waiting for translation",
    "翻译阶段失败：{error}。Metascape 已完成，用时 {duration}。": (
        "Translation stage failed: {error}. Metascape finished in {duration}."
    ),
    "处理失败：{error}": "Processing failed: {error}",
    "正在处理 {name}": "Processing {name}",
    "Metascape 分析完成，正在翻译 Excel": "Metascape analysis finished; translating the Excel file",
    "翻译完成：{path}，用时 {duration}。": "Translation finished: {path}, took {duration}.",
    "翻译失败，已跳过 {name}": "Translation failed; skipped {name}",
    "处理失败：{name}，原因：{error}": "Processing failed: {name}, reason: {error}",
    "翻译失败，已跳过：{error}": "Translation failed; skipped: {error}",
    "Excel 后处理跳过：{error}": "Excel post-processing skipped: {error}",
    "翻译 {name}: {current}/{total}": "Translating {name}: {current}/{total}",
    "翻译进行中：{current}/{total}": "Translating: {current}/{total}",
}


def get_ui_language() -> str:
    return _current_language


def set_ui_language(language: str) -> None:
    global _current_language
    _current_language = language if language in UI_LANGUAGES else UI_LANGUAGE_ZH


def tr(text: str) -> str:
    """按当前界面语言翻译文案；中文模式下原样返回。"""
    if _current_language == UI_LANGUAGE_ZH:
        return text
    return _EN.get(text, text)
