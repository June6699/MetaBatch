# Update Log

## 2026-09-06

- `Add`: 新增英文界面模式（配置管理区右上角下拉框切换，中文 / English，立即生效），界面、日志、错误消息全部跟随界面语言。
- `Update`: 界面语言切换移到顶部独立的「语言 / Language」标签页，标签名固定双语显示，任何界面语言下都能找到入口。
- `Add`: 新增翻译目标语言选项（默认简体中文，不提供英语），支持繁体中文、日语、韩语、法语、德语、西班牙语、葡萄牙语、俄语、意大利语；结果 Excel 的翻译列名跟随所选语言（简体中文仍为 `中文描述`，向后兼容已有文件）。
- `Add`: 新增英文版 README（`README-en.md`）；完善中文 README，补充项目结构、双语界面、目标语言、打包与测试说明。
- `Update`: `MetaBatch.spec` 改为相对路径并纳入版本管理，可直接按 README 说明打包；清理 `.gitignore` 与本地产物（`build/`、`logs/`、`__pycache__` 等）。
- `Fix`: 鼠标悬停在配置名、API 格式、认证字段、API Model、分析模式、Metascape/翻译连接方式等下拉框上滚动滚轮不再误改选项，必须点开下拉才能选择；主界面与日志区的标签栏同样不再被滚轮切换，滚轮事件改为驱动页面滚动。
- `Fix`: 同一目录下同名不同扩展名的输入文件（如 `a.txt` 与 `a.xlsx`）不再互相覆盖，输出名会追加原扩展名（`a_txt_metascape.xlsx` / `a_xlsx_metascape.xlsx`）。
- `Fix`: 补上文件之间的随机 5~10 秒间隔（可被停止事件打断），多并发下不再连续轰炸 Metascape。
- `Fix`: 关闭窗口时若后台线程仍在运行，现在会请求停止并等待线程退出后再关闭，避免 `QThread: Destroyed while thread is still running` 崩溃。
- `Fix`: 翻译 API 对 4xx（鉴权/参数错误）不再无意义重试，立即失败；429/5xx 仍然指数退避重试并尊重 `Retry-After`。
- `Fix`: 并发 worker 翻译相同词条时共享同一个在途请求，不再重复调用翻译 API。
- `Fix`: 输入 txt/csv/tsv 支持 UTF-8 BOM 与 GBK/GB2312 编码，无法解码时报出可读错误而不是 `UnicodeDecodeError`。
- `Fix`: Metascape 首页 `networkidle` 等待超时不再导致整个文件失败。
- `Fix`: 配置文件改为临时文件+原子替换写入，写入中途崩溃不再损坏全部配置。
- `Fix`: Anthropic `max_tokens` 由 256 提升到 1024，长富集描述不再被截断。
- `Update`: 翻译完成后不再重复打开/保存一次 Excel 做列宽调整。
- `Update`: 并发数、代理端口输入非法时给出中文提示；“保存配置”也会捕获并提示这些错误。
- `Update`: 移除 Qt6 已废弃的 `AA_EnableHighDpiScaling` / `AA_UseHighDpiPixmaps` 设置（Qt6 默认启用高 DPI）。
- `Update`: `requirements.txt` 移除已弃用的 PySimpleGUI。

## 2026-06-29

- `Add`: MetaBatch 迁移到 PySide6 主界面，解决 Windows 下字体发虚问题。
- `Add`: 新增多配置持久化、是否翻译、代理、并发数、summary 输出、logs 目录日志文件。
- `Add`: 新增递归扫描输入目录、输出目录复刻相对结构、结果文件统一追加 `_metascape` 后缀。
- `Add`: 新增 `Enrichment` 工作表翻译与 `Description` / `中文描述` 自动列宽。
- `Update`: 主界面改为顶部标签页，支持配置、运行、进度、日志分区。
- `Update`: 日志改为带时间戳输出，并同时写入屏幕和 `logs/` 文件。
- `Update`: 日志界面升级为“总日志 + 每个 worker 独立标签页”，5 并发下可以按 worker 查看各自输出。
- `Update`: Excel 写回后显式持久化 `Enrichment` 活动页状态、工作簿视图和 `Description` 列宽，并补充本地样例文件验证。
- `Update`: Workflow 日志与进度现在携带 worker 编号，文件日志也会写出 `Worker N` 前缀。
- `Fix`: Metascape 下载改为更稳健的自动化链路，增加直接链接兜底，降低 `Download.save_as: canceled` 的概率。
- `Fix`: Metascape 的 `Submit`、`Express Analysis`、`Analysis Report Page`、下载入口点击增加显式等待、重试、force click / JS click 兜底，缓解 5 并发下偶发点击超时。
- `Fix`: `Enrichment` 缺失时保持失败语义，但提示调整为“可能因为基因过少未产生富集结果”。

## 2026-06-30

- `Add`: 日志视图升级为彩色日志，按成功、失败、警告、进度、操作等类型区分显示颜色。

- `Add`: 进度页新增按并发 worker 纵向排列的独立进度卡片，可滚动查看每个 worker 的当前状态。

- `Add`: Worker 进度卡片支持显示当前阶段、Metascape 进度、翻译进度、最近状态和当前文件路径。

- `Add`: 使用 PyInstaller 打包生成 `dist/MetaBatch.exe`，支持无 Python 环境启动桌面程序。

- `Update`: 打包产物使用内置图标，并兼容 `sys._MEIPASS` 的资源路径解析。

- `Fix`: 修复 worker 进度回调链路，GUI 与 workflow 之间现在会同步传递 worker 编号和当前文件相对路径。

## 2026-07-01

- `Fix`: 修复 `WorkflowWorker` 与 `WorkflowController` 的进度回调参数不一致，避免运行时触发 `takes 8 positional arguments but 9 were given`。
- `Update`: 重新使用 PyInstaller 构建 `dist/MetaBatch.exe`，并替换为最新产物。
