# MetaBatch

**简体中文 | [English](README-en.md)**

MetaBatch 是一个面向 [Metascape](https://metascape.org) 批量富集分析的 Python 3.11 桌面工具。它会批量读取基因列表，通过 Playwright 自动打开 Metascape 的 Express Analysis 页面，提交分析、下载结果；启用翻译时，会把 `Enrichment` 工作表里的 `Description` 列调用 AI 翻译成所选语言，并追加为新列（默认简体中文，列名 `中文描述`）。

## 功能特性

- **批量处理**：递归扫描输入目录中的所有基因列表文件；支持通配符过滤（"文件匹配"填写 `*.txt`、`*gene*` 等，多个用 `;` 分隔，留空则匹配全部支持类型），界面实时显示"匹配文件 N 个"；输出目录复刻输入的相对目录结构，所有结果统一追加 `_metascape` 后缀。
- **输入格式**：支持 `txt`、`csv`、`tsv`、`xlsx`、`xls`，兼容 UTF-8（含 BOM）与 GBK/GB2312 编码；同名不同扩展名的输入（如 `a.txt` 与 `a.xlsx`）会自动消歧命名，不会互相覆盖。
- **自定义基因列**：
  - 留空：默认使用第一列。
  - 输入数字：按 1-based 列号取值，例如 `1`、`3`。
  - 输入 Excel 列字母：例如 `A`、`C`。
  - 输入表头名：例如 `gene_symbol`，按首行表头定位。
- **下载类型**：
  - `仅 Excel (xlsx)`：下载单个 Excel 结果并直接翻译。
  - `完整 Zip 包`：下载 Zip，自动解压并定位其中的 Excel，再翻译。
- **AI 翻译**：按 OpenAI Chat 兼容协议调用（兼容 Anthropic Messages 原生格式与 OpenAI Responses 格式），支持一键获取模型列表、测试连通性；翻译目标语言可选（默认简体中文，不提供英语——Metascape 的 Description 本身是英文），支持繁体中文、日语、韩语、法语、德语、西班牙语、葡萄牙语、俄语、意大利语；批量请求按内容长度自适应分块——待翻译条目总字符 ≤4000（且 ≤100 条）时一次发送，超限才分成最少的几块，按顺序写回 Excel，并通过缓存避免并发 Worker 重复请求，`429/5xx` 自动指数退避重试。
- **多套配置**：可保存多套配置并随时切换，启动时自动恢复上次使用的配置；界面语言（中文 / English）与翻译目标语言随配置持久化。
- **大列表保护**：「跳过超过 N 基因的列表」默认勾选，右侧可**自行填写上限**（默认 5000）——超过上限的列表不提交给 Metascape（数千基因的列表会让 Metascape 输入框响应极慢、页面卡死），而是在日志与清单中标记为「基因过多」；取消勾选即可关闭该保护。
- **结果清单**：每次运行结束会在输出目录根下写出 `metabatch_gene_report.csv`（UTF-8 BOM），覆盖**所有输入文件**并给出「基因数 / 是否做了 Metascape / 是否翻译了 / 状态 / 跳过原因 / 消息」，一眼就能看出哪些文件没结果、为什么。
- **自动续跑**：每次开始前先扫描输出目录，已经跑完的文件（`*_metascape.xlsx` 存在且含 `Enrichment` 表；启用翻译时还要求已有目标语言列）直接跳过，只处理没跑完或没跑过的文件；中断后再次「开始处理」即可从断点继续，无需手动挑文件。
- **翻译预检**：每次运行开始只做一次最小翻译请求；接口不可用（例如 Key 失效、地址写错、超时）时本次运行自动暂停翻译，Metascape 结果照常下载，并在日志、进度页与汇总中明确提示，避免每个文件都白等一次超时。
- **连接方式**：Metascape 与翻译 API 可分别选择直连或代理，并发数量可调（默认 5，最大 32）。
- **双语界面**：顶部独立的「语言 / Language」标签页中一键切换中文 / English，立即生效；日志与错误消息跟随界面语言。
- **进度与日志**：批处理总进度、Metascape 分析进度、翻译进度三层进度条，外加每个 Worker 的独立进度卡片和日志标签页；日志按类型着色，并同时写入 `logs/` 目录，记录单文件 Metascape 用时、翻译用时与总用时，批处理进度显示为 `x/y (z%)`。
- **稳健性**：文件之间随机休息 5~10 秒避免被限流；已存在的结果自动跳过（断点续跑，且只写了一半的损坏结果会被重跑）；连续失败 20 个文件后停止提交剩余任务（多为网络或接口配置问题，修好后再次开始会自动续上）；单文件失败不影响整体任务；点击控件的滚轮误触防护（悬停滚动不会误改下拉框选项和标签页）。
- **开箱即用**：内置应用图标，源码运行和 PyInstaller 打包运行均可复用。

## 项目结构

```text
MetaBatch/
├─ main.py                          # 入口
├─ build.bat                        # 一键打包脚本（双击运行）
├─ MetaBatch.spec                   # PyInstaller 打包配置
├─ requirements.txt
├─ README.md / README-en.md
├─ update.md                        # 更新日志
├─ translate_boundary_metascape.py  # 离线补翻译命令行工具（见下文）
├─ assets/
│  └─ metabatch_icon.ico
├─ runtime_hooks/
│  ├─ crash_handler.py              # 全局崩溃兜底（运行时钩子）
│  └─ qt_dll_path.py                # Qt DLL 搜索路径（运行时钩子）
├─ metabatch/
│  ├─ __init__.py
│  ├─ assets.py                      # 应用图标生成
│  ├─ excel_processor.py             # Enrichment 表翻译与列宽调整
│  ├─ gene_reader.py                 # 基因列表文件发现与读取
│  ├─ gui.py                          # PySide6 主界面
│  ├─ i18n.py                         # 界面文案双语词典
│  ├─ logging_utils.py                # 运行日志
│  ├─ metascape_client.py             # Playwright 自动化
│  ├─ models.py                        # 数据模型与翻译语言定义
│  ├─ paths.py                         # 输出路径规则
│  ├─ runtime.py                       # 打包/源码运行路径兼容
│  ├─ settings.py                      # 配置持久化
│  ├─ translator.py                    # OpenAI 兼容翻译客户端
│  └─ workflow.py                      # 并发任务调度
├─ demo/                              # 示例输入与结果（不随包分发）
└─ tests/
```

## 安装

推荐直接使用本机 `py -3.11`：

```powershell
py -3.11 -m pip install -r requirements.txt
py -3.11 -m playwright install chromium
```

## 启动

```powershell
py -3.11 main.py
```

## 使用方式

1. 选择基因列表文件夹。
2. 选择输出结果文件夹。
3. 如目录中同时存在基因列表与 Metascape 结果（如 `.txt` 与 `.xlsx` 并存），在"文件匹配"中填写 `*.txt` 即可只处理 txt；留空则处理全部支持类型，界面会显示"匹配文件 N 个"。
4. 选择下载类型。
5. 如果输入文件不是"每行一个基因"的单列文本，可以填写"基因所在列"。
6. 填入翻译接口信息：
   - `API Base URL`：例如 `https://your-api-host/v1`
   - `API Key`
   - `Model`（可用"获取模型"按钮拉取列表，"测试连通性"验证）
   - `API 格式` 与 `认证字段` 按服务提供商选择
7. 需要其他语言时，在"翻译目标语言"中选择（默认简体中文）。
8. 在顶部配置区选择已有配置，或用"保存当前 / 另存为 / 删除"管理多套配置；界面语言在顶部独立的「语言 / Language」标签页中切换。
9. 需要时可以关闭翻译，或设置 Metascape / 翻译 API 的代理与并发数。
10. 点击"开始处理"。

## 输入文件示例

下面这种 `txt` 文件可直接使用，不需要额外设置基因列：

```text
Zfhx3
Adamts9
Hdgfl1
Tafa1
1700123L14Rik
Cdh13
Prl7c1
Prl7d1
Nell2
Prl2b1
```

如果是 `xlsx/xls/tsv/csv` 一类结构化文件，可以指定某一列作为基因列。

## 输出规则

- 输入目录会递归扫描，输出目录会保留输入根目录下的相对结构。
- 所有结果文件统一加 `_metascape` 后缀。
  - 例如输入：
    - `mouse\timepoint_comparisons\D56_Immune_A_M24_Immune_B_FDR0.05.txt`
  - 若输出根目录为：
    - `mouse_metascape`
  - 则输出 Excel 为：
    - `mouse_metascape\timepoint_comparisons\D56_Immune_A_M24_Immune_B_FDR0.05_metascape.xlsx`
  - 输出 Zip 为：
    - `mouse_metascape\timepoint_comparisons\D56_Immune_A_M24_Immune_B_FDR0.05_metascape.zip`
- 同一目录下存在同名不同扩展名的输入时（如 `a.txt` 与 `a.xlsx`），输出名会追加原扩展名以避免覆盖，例如 `a_txt_metascape.xlsx`、`a_xlsx_metascape.xlsx`。
- Zip 模式会额外创建：
  - `{输入文件名}_metascape_extracted/`

## 配置与日志

- 配置文件保存在程序目录下的 `metabatch_config.json`，以 UTF-8 明文保存多套配置，其中**包含 API Key，请勿外传**；写入采用临时文件原子替换，异常中断不会损坏配置。
- 每次运行都会在 `logs/` 目录下生成一份带时间戳的日志文件。
- `metabatch_summary.csv` 会写到输出根目录，汇总每个文件的状态、耗时与失败原因；另含 `gene_count`、`skipped_reason`（`已有结果` / `基因过多`）、`translation_status`（`translated` / `paused` / `failed` / `disabled`）与 `translation_message` 三列，便于排查"文件在哪一步没拿到结果"。
- `metabatch_gene_report.csv` 是给人看的结果清单（UTF-8 BOM，Excel 双击即可）：每个输入文件一行，含基因数、`metascape`（已做/未做/已有结果/部分完成）、`translated`（已翻译/已暂停/翻译失败/未翻译/未知）与失败原因。
- 源码启动和 exe 启动使用各自程序目录下的配置：`py -3.11 main.py` 读取项目根目录的 `metabatch_config.json`，打包后的 `dist/MetaBatch/MetaBatch.exe` 读取同目录 `dist/MetaBatch/metabatch_config.json`；两者的输入目录、代理和 API 设置不会自动同步。

## 离线补翻译工具

`translate_boundary_metascape.py` 用于对**已有的结果目录**批量补翻译，无需重新跑 Metascape：

```powershell
$env:METABATCH_TRANSLATION_API_KEY = "你的Key"
py -3.11 translate_boundary_metascape.py --results-dir "结果目录" --model "deepseek-flash"
```

默认调用 `https://api.deepseek.com/v1` 的 `chat/completions`（可用 `--api-base-url` 换成其他 OpenAI 兼容地址）。它会把「中文描述」列补到已有结果 Excel 里，因此**运行时翻译被暂停或失败的文件，之后可以用它一次性补齐**。

它会递归处理目录下所有 `*_metascape.xlsx`，自动跳过已翻译或无 `Enrichment` 的文件，对唯一 Description 去重后批量翻译，并在结果目录生成 `metabatch_translation_summary.tsv` 汇总每个文件的状态。

## 耗时参考（实测，2026-10-15）

单个文件的 Metascape 时间**由服务端决定**，本机实测（2200~3000 基因）：

| 阶段 | 实测耗时 |
| --- | --- |
| 打开页面 → 提交基因列表 | 30~130 秒（页面加载 + 大列表写入） |
| Submit → Express Analysis 可用（ID 转换） | ≈ 90 秒 |
| Express Analysis → 分析完成（Enrichment & PPI） | ≈ 6 分钟（进度条会长时间停在 75% 附近，属正常） |
| 分析完成 → 报告页 + 下载 xlsx | 2~15 秒（直接按 session_id 跳转） |

因此**单文件约 7~8 分钟**，且 5 个并发任务往往在同一时间段内一起完成——Metascape 似乎对同一 IP 串行排队，所以并发主要是让服务端队列不空转，并不会成倍提速。211 个文件按 5 并发大约需要 **5~8 小时**，建议把长时间任务放在机器空着的时候跑（中断后再次「开始处理」会自动续跑）。

## 说明与限制

- 当前只实现 `Express Analysis`。
- Metascape 会**间歇性进入维护状态**（跳转到 `maintenance.html`）：此时日志会明确提示「Metascape 当前返回的是维护页…正在等待其恢复」，程序会继续轮询等待，不会误判为选择器失效。
- 基因数太少的列表（实测 40 个基因）Metascape 不会生成 `Enrichment` 表，该文件的翻译阶段会被记为失败（清单里显示"翻译失败"），Metascape 结果本身仍然保留。
- Metascape 是单页应用，页面结构变动后，`metabatch/metascape_client.py` 中的候选选择器可能需要调整。
- 按钮点击采用 **DOM 点击优先**策略：本机实测 `locator.click()`（含 `force=True`）在 5 并发下会整段挂死 30 秒，而 DOM 点击 1~8 秒内完成；鼠标点击仅作兜底（单次上限 8 秒）。若点击最终失败，会在 `logs/` 下保存 `click_failure_*.png` 截图与页面元素状态，便于定位。
- Metascape 的 `maintenance.html` 多数是**假警报**：`app.js` 在同步健康检查 `health_check_pull` 返回 `1` 或请求失败时会跳该页，而后端实测一直返回 `0`。程序遇到维护页会先以 2 秒间隔重载几次尝试恢复，并在日志中记录每一步的页面 URL/标题。
- 并发会按 CPU 核数设上限（每个无头浏览器约需 2 个逻辑核），且每个文件开始前若系统 CPU 高于 70% 会先等待回落，避免渲染进程被"饿"住导致点击拿不到响应。
- 每个文件处理完成后，Worker 会随机休息 5~10 秒再处理下一个文件，降低被 Metascape 限流的风险。
- 单文件的分析 + 下载总超时默认为 1800 秒（30 分钟）：Metascape 的富集与 PPI 步骤在基因较多时会长时间停在 75% 附近。
- 「Metascape 连接方式」选代理时，程序会先探测代理端口是否有人监听：不通则本次自动改走直连并给出提示（代理软件没启动时最容易出现"能跑但莫名其妙很慢"的情况）。
- 翻译时会在每次请求间隔至少 `0.1` 秒，并对 `429/5xx` 做有限重试；`4xx`（如 Key 错误）会立即失败。
- 如果 `Enrichment` 工作表中已经存在目标语言的翻译列（简体中文为 `中文描述`），会跳过该文件，避免重复写入。
- 如果结果文件中没有 `Enrichment` 工作表，程序会将其视为失败，并提示"可能因为基因过少未产生富集结果"。
- 程序按输出目录中映射后的 `_metascape` 目标文件做跳过判断，不会重复提交同名任务；已有结果但缺少 `Enrichment` 表、或启用翻译却还没有目标语言列的文件会被视为未完成并重跑。
- 单个列表的基因数超过上限（默认 5000，界面「大列表保护」可开关）时直接跳过：Metascape 输入框对数千基因的列表响应极慢，实测 8000 基因会让 `fill()` 卡满 30 秒超时。
- 如果翻译 API 调用失败，程序会把该文件记为 `partial`（Metascape 结果已下载、翻译失败），继续处理下一个文件，并在 summary 中记录失败原因；若运行前的翻译预检就失败，则本次运行整体暂停翻译。
- Responses 格式对 GPT-5 类模型使用 `instructions`、`input` 和 `max_output_tokens`，不会发送不兼容的 `temperature` 参数。

## 打包

最简单的方式是**双击项目根目录的 `build.bat`**；或手动执行：

```powershell
py -3.11 -m pip install pyinstaller
py -3.11 -m PyInstaller --clean --noconfirm MetaBatch.spec
```

### 产物布局（onedir）

打包结果为目录形态（启动快、便于排查）：

```text
dist/MetaBatch/
├─ MetaBatch.exe          # 主程序（双击运行）
└─ _internal/             # 全部运行依赖（PySide6、playwright、Python 运行时等）
```

### 体积构成与裁剪

`_internal` 约 186 MB，主要构成：

| 部分 | 约占用 | 说明 |
|---|---|---|
| playwright | 102 MB | 其中 `node.exe` 约 87 MB，是 playwright 驱动浏览器的运行时，**必需** |
| PySide6 | 55 MB | Qt 的 Core/Gui/Widgets 等，GUI 必需 |
| PIL 及其他 | ~30 MB | 图标生成、证书、字符集、greenlet 等 |

`MetaBatch.spec` 已裁剪项目未使用的 Qt 模块（WebEngine、Qml/Quick、Multimedia、3D、Pdf 等），以及环境中被第三方库 `try/except` 误收集的可选依赖（numpy/OpenBLAS、lxml、h2、cryptography、`opengl32sw`、AVIF、OpenSSL 3），体积由约 280 MB 降至约 186 MB。若在极端无 GPU 环境界面渲染异常，可在 spec 中移除对应排除项后重新打包。

### 崩溃兜底与日志

- 打包版内置全局崩溃钩子：未捕获异常会写入 exe 同目录 `logs/metabatch_crash_*.log` 并弹窗提示，不再出现 PyInstaller 原始错误框。
- 若双击 exe 后没有窗口，先查看 `dist/MetaBatch/logs/`；窗口版不显示控制台，日志通常能直接定位配置、浏览器或页面问题。

### 分发到其他电脑

Playwright 的 **Chromium 浏览器本体**不在 pip 包 / dist 内（位于打包机用户目录 `ms-playwright` 缓存）。把整个 `dist/MetaBatch/` 拷到未安装过的电脑后，需让对方先安装一次浏览器：

```powershell
py -3.11 -m playwright install chromium
```

（Python 包与 node 驱动已在 `_internal` 中，无需另装 playwright 包。）现代 PySide6 已内置 ICU，无需单独携带；若仍看到 `DLL load failed while importing QtCore`，请确认使用的是本次重新构建的 `dist/MetaBatch/MetaBatch.exe`，不要混用旧 exe。

## 开发与测试

```powershell
py -3.11 -m unittest discover -s tests
```

测试覆盖翻译客户端的重试策略与并发去重、输入文件编码兼容、输出路径规则、界面文案词典完整性等。
