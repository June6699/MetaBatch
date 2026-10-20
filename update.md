# Update Log

## 2026-10-15（第六步：报告页不再依赖弹窗 + 代理预检 + 默认全屏）

- `Fix`: **报告页那 5 分钟卡死修掉**。Metascape 的「Analysis Report Page」按钮处理器是 `openReportFinalUrl()`（内部 `window.open`），在无头/自动化下会被浏览器弹窗策略拦住，点了也打不开——23:21 那次运行 5 个 worker 全部卡在这一步直到被手动停止，**0 个文件落盘**。现在改为：先点一次（兼容旧行为），15 秒内拿不到报告页就**按 session_id 直接跳转 `#/reportfinal/<session_id>`**。实测直接跳转 **2.1 秒**进报告页并成功下载 xlsx（`get_file?session_id=...&file_name=metascape_result.xlsx`）。
- `Fix`: DOM 点击不再重复派发事件（原先是 `el.click()` + `mousedown/mouseup/click`，等于点了两次，会让 `window.open` 被弹窗策略判定为"非用户手势"而拦截）。现在只做一次 `el.click()`。
- `Add`: **代理可用性预检**。配置里选了代理但代理软件没启动时（本次就是：`proxy_port=51888`，而 `xray` 进程 23:41 才启动），浏览器行为会变得莫名其妙。现在开跑前先用 TCP 探测代理端口，不通则打日志说明并**本次自动改走直连**，不让整次运行白等。
- `Add`: 界面**默认最大化**（`showMaximized`，不再沿用上次窗口尺寸）；边框内仍保留最小尺寸限制。
- `Update`: 单元测试 77 项全部通过；报告页等待逻辑拆成 `_wait_for_report_page` / `_read_session_id`，便于复用与排错。

## 2026-10-15（第五步：修掉自己引入的 `selector` 未定义 bug + 加静态守卫）

- `Fix`: 第四步给基因输入框加 JS 聚焦时写错了变量名（用了不存在的 `selector`，正确是 `textbox_selector`），异常被兜底 `except` 吞掉后**静默回退到慢速鼠标点击**，于是 23:16 那次运行又出现点击挂死。现已修正；5 并发真机复测：`JS 聚焦成功 5/5`、`Submit 按钮 DOM 点击成功`、单文件 17~25 秒全部通过。
- `Add`: 新增静态守卫测试 `tests/test_workflow_gates.UndefinedNameGuardTests`：按函数作用域扫描 `metabatch/*.py`，报告"使用了未定义名字"（含 `page.evaluate(...)` 的参数），并带自检用例——必须能抓到当初那个 `selector is not defined`。这类"低级但会静默降级"的错误以后在测试阶段就会失败。
- `Update`: 单元测试总数 75 → 77。

## 2026-10-15（第四步：点击改为 DOM 优先 + 维护页误报处理 + 清单口径修正）

- `Fix`: **点击策略改为 DOM 点击优先**（实测有效）。22:43 那次运行里 `locator.click()` 与 `force=True` 会整段挂死 30 秒（同一时刻连 `Locator.element_handle()` 都超时），而 DOM 点击（`el.click()` + 派发 mousedown/mouseup）在同一页面 1~8 秒内完成。现在 `_click_with_retry` 先做 DOM 点击，失败才退回鼠标点击，且鼠标单次上限 30s→8s、尝试次数 3→2：单次点击最坏等待从 270 秒降到约 30 秒。5 并发真实链路复测：**5/5 全部成功，单文件 19~34 秒**。
- `Fix`: 修正 DOM 点击的实现缺陷——`page.evaluate()` 不接受 `timeout` 参数，之前传了会导致每次 DOM 点击都静默异常并回退鼠标点击（即"看起来没生效"）。改为不传超时，并在日志区分"DOM 点击成功 / 未生效（原因）"。
- `Update`: 基因输入框不再做鼠标点击，改为 JS 聚焦（写入本来就是 JS 赋值），省掉一次可能挂死的鼠标交互。
- `Fix`: **维护页误报处理**。Metascape 的 `app.js` 会在 `health_check_pull`（一个同步 XHR）返回 `1` **或请求失败**时跳转 `maintenance.html`；实测该接口一直返回 `0`（连续 10 次 / 5 并发），因此维护页多为健康检查偶发失败造成的假警报，而旧逻辑遇到它只会慢轮询等 15 分钟。现在：先以 2 秒间隔重载最多 8 次尝试恢复，未恢复再退回慢轮询，且每步都记录「当前页面 URL/标题」，日志能直接看出到底是被跳到维护页还是元素真的不存在。
- `Fix`: 结果清单口径修正——被停止的任务（`stopped`）不再算作「已做 Metascape」（当时没有结果文件），改标「部分完成」；运行末尾统计改为「已完成 X 个…中途停止 Z 个…失败 F 个」。
- `Add`: 系统饱和保护：按逻辑核数给出并发上限（每个 Chromium 约需 2 个逻辑核），并在每个文件开始前检查系统 CPU，超过 70% 先等待回落（最多 2 分钟），避免浏览器渲染进程被"饿"住导致点击拿不到 ack。
- `Add`: 点击最终失败时记录现场（URL、标题、输入框长度、按钮中心命中测试、最多 12 个可点元素状态）并保存截图到 `logs/click_failure_*.png`。
- `Update`: 浏览器启动参数增加 `--disable-background-timer-throttling`、`--disable-backgrounding-occluded-windows`、`--disable-renderer-backgrounding`。

## 2026-10-15（第三步：阈值可自定义、结果清单、维护页识别）

- `Update`: 「大列表保护」的基因数上限改为**可自定义**：界面勾选框右侧新增数值输入（默认 5000，留空沿用上次数值，非正整数会报错提示），随配置持久化（`max_genes_per_file`）。
- `Add`: 新增**结果清单** `metabatch_gene_report.csv`（写到用户指定的输出目录根下，UTF-8 BOM，Excel 直接打开不乱码）：覆盖本次扫描到的**全部输入文件**，列出文件名/相对路径/**基因数**/**是否做了 Metascape**（已做·未做·已有结果·部分完成）/**是否翻译了**（已翻译·已暂停·翻译失败·未翻译·未知）/状态/跳过原因/消息。同时 `metabatch_summary.csv` 新增 `gene_count` 列，运行日志末尾给出清单统计（共 N 个、已做 X、其中已翻译 Y、已有结果 Z、基因过多跳过 K、失败 F）。
- `Fix`: 识别 Metascape **维护页**（`maintenance.html`）：不再让选择器傻等，而是明确提示「Metascape 当前返回的是维护页…」后等待恢复。（第四步已进一步确认：该页多为 `health_check_pull` 偶发失败造成的假警报，并改为快速重载恢复。）
- `Fix`: 翻译接口预检的"预检通过"日志会带上 Base URL 与模型名，便于确认到底用的是哪套配置。
- `Update`: 翻译失败的文件（例如基因太少、Metascape 未生成 Enrichment 表）现在明确记为 `partial` 并在清单里显示"翻译失败"，不再混进"成功"。

## 2026-10-15（第二步：结果拿不到的三处根因修复）

- `Fix`: 修复大基因列表导致 `textarea.fill()` 卡满 30 秒的问题（10/14 三次运行的 6755–8407 基因列表全部因此失败）。实测 8000 基因时 Playwright 的 `fill()` 超时，但 textarea 其实**已经写入 75174 字符**——卡住的是动作性检查。现改为直接 `el.value = text` + 派发 `input/change`（实测 0.5 秒完成；已确认对 Angular `ng-show="inputData.textbox"` 生效、Submit 按钮正常出现），仅在赋值失败时回退 `fill()`，并在日志中记录基因数与字符数。相关方法：`metascape_client._set_textbox_value`。
- `Add`: 新增「跳过超过 5000 基因的列表」开关（默认打开）：超过上限的列表不再提交 Metascape，而是记入日志与汇总（`status=skipped`、`skipped_reason=基因过多`、界面汇总单列「因基因过多 N 个」）。当前数据集最大文件为 15147 基因（Metascape 官方上限以内也不适合本工具直接提交）。
- `Add`: 新增**自动续跑**：每次开始前预扫描输出目录，`*_metascape.xlsx` 存在且已完成（含 `Enrichment` 表；启用翻译时还要求已有目标语言列）的文件直接跳过，只处理未完成与未处理文件；只写了一半的损坏结果会被重跑。中断后再次「开始处理」即从断点继续。界面与日志会打印「预扫描完成：待处理 N 个，已有结果跳过 M 个，因基因过多跳过 K 个」。
- `Add`: 新增**翻译预检**（每次运行只做一次最小翻译请求）：失败则本次运行暂停翻译并明确提示，Metascape 结果照常下载——避免 10/15 那次 9 个文件各白等 60 秒超时（当时日志为 `api.bblabu.ai ... Read timed out`）。翻译中途失败的文件不再混进"成功"，而是记为 `partial`（Metascape 已完成、翻译失败）。
- `Update`: `metabatch_summary.csv` 新增 `skipped_reason`、`translation_status`、`translation_message` 三列；界面汇总新增「其中 N 个 Metascape 结果已下载但翻译失败」「跳过明细：已有结果 X，因基因过多 Y」「失败原因：…」。
- `Update`: 连续失败 20 个文件后停止提交剩余任务（多为一整批网络/接口问题），已完成的文件保留在磁盘上，修好后再次开始自动续跑。
- `Update`: 离线补翻译工具 `translate_boundary_metascape.py` 默认改为 DeepSeek（`https://api.deepseek.com/v1` + `deepseek-flash`）；运行中翻译被暂停/失败的文件可用它一次性补齐「中文描述」列。
- `Add`: 新增 `tests/test_workflow_gates.py`（阈值边界、已有结果完成度判定、预扫描分类、翻译预检），并扩展 i18n 词典校验。
- `Update`: 单文件超时（Metascape 分析 + 下载）默认由 600 秒放宽到 1800 秒：5000 基因以内容易被 75% 的 PPI 步拖过 10 分钟，超时会被误判为失败。
- `Fix`: 跳过的原因键（`已有结果` / `基因过多`）固定使用中文原始值写入 summary，不再跟随界面语言翻译，修复英文界面下"跳过明细"统计恒为 0 的问题。

## 2026-10-15

- `Fix`: 修复 Submit 按钮无法点击的问题：粘贴后等待 `Submit` 按钮可见且可点击（轮询 500ms，必要时补派 `input` 事件恢复 Angular 状态），不再误落到始终可见但禁用的 Step 3 `Express Analysis` 按钮；移除加载阶段对所谓 "Express Analysis 页签" 的 force click（当前版本并无此页签，且会扰乱页面状态）。
- `Fix`: Submit 之后等待 `Express Analysis` 按钮真正变为 enabled 再点击；`Analysis Report Page` 点击后兼容当前版本的同标签页 `#/reportfinal/...` 跳转与旧版本的新标签页，只点击一次，不再重复点击。
- `Update`: 首页 `networkidle` 由固定 30s 改为 5s 尽力等待，就绪信号改为元素轮询，单文件耗时减少约 25s；Zip 下载入口选择器更新为 `All in One Zip` 文案优先。
- `Add`: 新增「文件匹配」输入框，支持通配符（如 `*.txt`、`*gene*`），多个模式用 `;` 分隔，留空则匹配所有支持类型；输入目录下 txt 与 Metascape 结果 xlsx 并存时，设置 `*.txt` 即可只处理 txt。界面实时显示「匹配文件 N 个」；配置与输出路径同目录，不新增开关。
- `Update`: 翻译批量请求改为按内容长度自适应分块：待翻译条目总字符 ≤4000（且 ≤100 条）时一次发送，超限才按字符预算贪心打包成最少的几块，不拆分单条；Excel 处理改为一次性调用批量翻译，去掉此前 Excel 外层 20 条与翻译器内层 20 条的嵌套重复分块。
- `Add`: 新增文件匹配测试（`tests/test_gene_files.py`）与自适应分块测试（`_plan_chunks`、超字符拆分、去重/顺序/进度回调）。

## 2026-09-24

- `Fix`: 修复 Metascape 初始页面把禁用的 `Express Analysis` 按钮误当成可点击页签的问题，等待基因输入框真正可编辑后再填充，降低 exe 运行时的页面竞态与 `fill` 超时。
- `Update`: Excel 翻译改为每 20 条 Description 一次批量请求，保持原顺序写回，并在并发 Worker 间共享缓存，减少请求数量与等待时间。
- `Fix`: 完善 OpenAI Responses 请求体，针对 GPT-5 类模型使用 `max_output_tokens` 并移除不兼容的 `temperature`；兼容模型返回的 JSON 数组、对象和 Markdown 代码块。
- `Add`: 新增全局崩溃兜底运行时钩子 `runtime_hooks/crash_handler.py`：任何未捕获异常（含启动期 Qt DLL 加载失败）都会写入 `logs/metabatch_crash_*.log` 并弹出友好提示（Qt 不可用时退化为 Win32 原生弹窗），替代 PyInstaller 原始的 "Unhandled exception in script" 对话框。
- `Update`: 完善并规范化打包配置为 `MetaBatch.spec`：输出名 `MetaBatch`、嵌入图标、打包 `assets`、启用「崩溃兜底 + Qt DLL 搜索路径」两个运行时钩子、`optimize=2`、关闭 UPX（UPX 会压坏 Qt DLL，导致 `QtCore` 加载失败）。
- `Update`: 打包产物改为 onedir 布局 `dist/MetaBatch/MetaBatch.exe`（依赖位于同级 `_internal/`）；源码运行与 exe 运行分别读取各自程序目录下的 `metabatch_config.json`，互不自动同步。
- `Update`: 裁剪未使用的 Qt 模块，以及环境中被第三方库 `try/except` 误收集、项目实际不依赖的可选包（numpy/OpenBLAS、lxml、h2/hpack/hyperframe、cryptography、bcrypt、PyYAML、`opengl32sw.dll`、PIL 的 AVIF 插件、多余的 OpenSSL 3）。已实测 requests 的 https 走标准库 ssl（OpenSSL 1.1）、openpyxl 走标准库 xml、urllib3 默认 HTTP/1.1，dist 体积由约 280 MB 降至约 186 MB。
- `Fix`: `requirements.txt` 补 `Pillow`（`assets.py` 使用 PIL 但此前漏列），全新环境 `pip install -r requirements.txt` 不再因缺 PIL 报错。
- `Add`: 新增 `build.bat`，双击即按 `MetaBatch.spec` 一键清理并重新打包。

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
