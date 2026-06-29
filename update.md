# Update Log

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

  
