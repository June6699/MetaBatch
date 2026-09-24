# MetaBatch

**简体中文 | [English](README-en.md)**

MetaBatch 是一个面向 [Metascape](https://metascape.org) 批量富集分析的 Python 3.11 桌面工具。它会批量读取基因列表，通过 Playwright 自动打开 Metascape 的 Express Analysis 页面，提交分析、下载结果；启用翻译时，会把 `Enrichment` 工作表里的 `Description` 列调用 AI 翻译成所选语言，并追加为新列（默认简体中文，列名 `中文描述`）。

## 功能特性

- **批量处理**：递归扫描输入目录中的所有基因列表文件，输出目录复刻输入的相对目录结构，所有结果统一追加 `_metascape` 后缀。
- **输入格式**：支持 `txt`、`csv`、`tsv`、`xlsx`、`xls`，兼容 UTF-8（含 BOM）与 GBK/GB2312 编码；同名不同扩展名的输入（如 `a.txt` 与 `a.xlsx`）会自动消歧命名，不会互相覆盖。
- **自定义基因列**：
  - 留空：默认使用第一列。
  - 输入数字：按 1-based 列号取值，例如 `1`、`3`。
  - 输入 Excel 列字母：例如 `A`、`C`。
  - 输入表头名：例如 `gene_symbol`，按首行表头定位。
- **下载类型**：
  - `仅 Excel (xlsx)`：下载单个 Excel 结果并直接翻译。
  - `完整 Zip 包`：下载 Zip，自动解压并定位其中的 Excel，再翻译。
- **AI 翻译**：按 OpenAI Chat 兼容协议调用（兼容 Anthropic Messages 原生格式与 OpenAI Responses 格式），支持一键获取模型列表、测试连通性；翻译目标语言可选（默认简体中文，不提供英语——Metascape 的 Description 本身是英文），支持繁体中文、日语、韩语、法语、德语、西班牙语、葡萄牙语、俄语、意大利语；每 20 条 Description 合并为一次批量请求，按顺序写回 Excel，并通过缓存避免并发 Worker 重复请求，`429/5xx` 自动指数退避重试。
- **多套配置**：可保存多套配置并随时切换，启动时自动恢复上次使用的配置；界面语言（中文 / English）与翻译目标语言随配置持久化。
- **连接方式**：Metascape 与翻译 API 可分别选择直连或代理，并发数量可调（默认 5，最大 32）。
- **双语界面**：顶部独立的「语言 / Language」标签页中一键切换中文 / English，立即生效；日志与错误消息跟随界面语言。
- **进度与日志**：批处理总进度、Metascape 分析进度、翻译进度三层进度条，外加每个 Worker 的独立进度卡片和日志标签页；日志按类型着色，并同时写入 `logs/` 目录，记录单文件 Metascape 用时、翻译用时与总用时，批处理进度显示为 `x/y (z%)`。
- **稳健性**：文件之间随机休息 5~10 秒避免被限流；已存在的结果自动跳过（断点续传）；单文件失败不影响整体任务；点击控件的滚轮误触防护（悬停滚动不会误改下拉框选项和标签页）。
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
3. 选择下载类型。
4. 如果输入文件不是"每行一个基因"的单列文本，可以填写"基因所在列"。
5. 填入翻译接口信息：
   - `API Base URL`：例如 `https://your-api-host/v1`
   - `API Key`
   - `Model`（可用"获取模型"按钮拉取列表，"测试连通性"验证）
   - `API 格式` 与 `认证字段` 按服务提供商选择
6. 需要其他语言时，在"翻译目标语言"中选择（默认简体中文）。
7. 在顶部配置区选择已有配置，或用"保存当前 / 另存为 / 删除"管理多套配置；界面语言在顶部独立的「语言 / Language」标签页中切换。
8. 需要时可以关闭翻译，或设置 Metascape / 翻译 API 的代理与并发数。
9. 点击"开始处理"。

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
- `metabatch_summary.csv` 会写到输出根目录，汇总每个文件的状态、耗时与失败原因。
- 源码启动和 exe 启动使用各自程序目录下的配置：`py -3.11 main.py` 读取项目根目录的 `metabatch_config.json`，打包后的 `dist/MetaBatch/MetaBatch.exe` 读取同目录 `dist/MetaBatch/metabatch_config.json`；两者的输入目录、代理和 API 设置不会自动同步。

## 离线补翻译工具

`translate_boundary_metascape.py` 用于对**已有的结果目录**批量补翻译，无需重新跑 Metascape：

```powershell
$env:METABATCH_TRANSLATION_API_KEY = "你的Key"
py -3.11 translate_boundary_metascape.py --results-dir "结果目录" --model "模型名"
```

它会递归处理目录下所有 `*_metascape.xlsx`，自动跳过已翻译或无 `Enrichment` 的文件，对唯一 Description 去重后批量翻译，并在结果目录生成 `metabatch_translation_summary.tsv` 汇总每个文件的状态。

## 说明与限制

- 当前只实现 `Express Analysis`。
- Metascape 是单页应用，页面结构变动后，`metabatch/metascape_client.py` 中的候选选择器可能需要调整。
- 每个文件处理完成后，Worker 会随机休息 5~10 秒再处理下一个文件，降低被 Metascape 限流的风险。
- 翻译时会在每次请求间隔至少 `0.1` 秒，并对 `429/5xx` 做有限重试；`4xx`（如 Key 错误）会立即失败。
- 如果 `Enrichment` 工作表中已经存在目标语言的翻译列（简体中文为 `中文描述`），会跳过该文件，避免重复写入。
- 如果结果文件中没有 `Enrichment` 工作表，程序会将其视为失败，并提示"可能因为基因过少未产生富集结果"。
- 程序按输出目录中映射后的 `_metascape` 目标文件做跳过判断，不会重复提交同名任务。
- 如果翻译 API 调用失败，程序会跳过该文件的翻译，继续处理下一个文件，并在 summary 中记录失败原因。
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
