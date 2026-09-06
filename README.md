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
- **AI 翻译**：按 OpenAI Chat 兼容协议调用（兼容 Anthropic Messages 原生格式与 OpenAI Responses 格式），支持一键获取模型列表、测试连通性；翻译目标语言可选（默认简体中文，不提供英语——Metascape 的 Description 本身是英文），支持繁体中文、日语、韩语、法语、德语、西班牙语、葡萄牙语、俄语、意大利语；相同词条在并发下共享同一次请求，`429/5xx` 自动指数退避重试。
- **多套配置**：可保存多套配置并随时切换，启动时自动恢复上次使用的配置；界面语言（中文 / English）与翻译目标语言随配置持久化。
- **连接方式**：Metascape 与翻译 API 可分别选择直连或代理，并发数量可调（默认 5，最大 32）。
- **双语界面**：中文 / English 一键切换，立即生效；日志与错误消息跟随界面语言。
- **进度与日志**：批处理总进度、Metascape 分析进度、翻译进度三层进度条，外加每个 Worker 的独立进度卡片和日志标签页；日志按类型着色，并同时写入 `logs/` 目录，记录单文件 Metascape 用时、翻译用时与总用时，批处理进度显示为 `x/y (z%)`。
- **稳健性**：文件之间随机休息 5~10 秒避免被限流；已存在的结果自动跳过（断点续传）；单文件失败不影响整体任务；点击控件的滚轮误触防护（悬停滚动不会误改下拉框选项和标签页）。
- **开箱即用**：内置应用图标，源码运行和 PyInstaller 打包运行均可复用。

## 项目结构

```text
MetaBatch/
├─ main.py
├─ requirements.txt
├─ MetaBatch.spec            # PyInstaller 打包配置
├─ README.md
├─ README-en.md
├─ assets/
│  └─ metabatch_icon.ico
├─ metabatch/
│  ├─ __init__.py
│  ├─ assets.py              # 应用图标生成
│  ├─ excel_processor.py     # Enrichment 表翻译与列宽调整
│  ├─ gene_reader.py         # 基因列表文件发现与读取
│  ├─ gui.py                 # PySide6 主界面
│  ├─ i18n.py                # 界面文案双语词典
│  ├─ logging_utils.py       # 运行日志
│  ├─ metascape_client.py    # Playwright 自动化
│  ├─ models.py              # 数据模型与翻译语言定义
│  ├─ paths.py               # 输出路径规则
│  ├─ runtime.py             # 打包/源码运行路径兼容
│  ├─ settings.py            # 配置持久化
│  ├─ translator.py          # OpenAI 兼容翻译客户端
│  └─ workflow.py            # 并发任务调度
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
7. 在顶部配置区选择已有配置，或用"保存当前 / 另存为 / 删除"管理多套配置；界面语言在配置管理区右上角切换。
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

## 说明与限制

- 当前只实现 `Express Analysis`。
- Metascape 是单页应用，页面结构变动后，`metabatch/metascape_client.py` 中的候选选择器可能需要调整。
- 每个文件处理完成后，Worker 会随机休息 5~10 秒再处理下一个文件，降低被 Metascape 限流的风险。
- 翻译时会在每次请求间隔至少 `0.1` 秒，并对 `429/5xx` 做有限重试；`4xx`（如 Key 错误）会立即失败。
- 如果 `Enrichment` 工作表中已经存在目标语言的翻译列（简体中文为 `中文描述`），会跳过该文件，避免重复写入。
- 如果结果文件中没有 `Enrichment` 工作表，程序会将其视为失败，并提示"可能因为基因过少未产生富集结果"。
- 程序按输出目录中映射后的 `_metascape` 目标文件做跳过判断，不会重复提交同名任务。
- 如果翻译 API 调用失败，程序会跳过该文件的翻译，继续处理下一个文件，并在 summary 中记录失败原因。

## 打包

安装 PyInstaller 后，使用项目自带的 spec（已包含图标与资源）：

```powershell
py -3.11 -m pip install pyinstaller
py -3.11 -m PyInstaller --noconfirm MetaBatch.spec
```

产物为 `dist/MetaBatch.exe`。项目内的路径处理已兼容 `__file__` / `sys._MEIPASS` 场景。

## 开发与测试

```powershell
py -3.11 -m unittest discover -s tests
```

测试覆盖翻译客户端的重试策略与并发去重、输入文件编码兼容、输出路径规则、界面文案词典完整性等。
