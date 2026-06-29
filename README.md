# MetaBatch

MetaBatch 是一个面向 Metascape 批量富集分析的 Python 3.11 桌面工具。它会批量读取基因列表，自动打开 Metascape 的 Express Analysis 页面，提交分析、下载结果，并在启用翻译时把 `Enrichment` 工作表里 `Description` 列翻译为中文后追加到 `中文描述` 列。

## 功能概览

- 支持批量处理多个基因列表文件，输出文件默认使用输入文件名命名。
- 支持输入格式：`txt`、`csv`、`tsv`、`xlsx`、`xls`。
- 支持自定义基因所在列：
  - 留空：默认使用第一列。
  - 输入数字：按 1-based 列号取值，例如 `1`、`3`。
  - 输入 Excel 列字母：例如 `A`、`C`。
  - 输入表头名：例如 `gene_symbol`，会按首行表头定位。
- 下载类型支持：
  - `仅 Excel (xlsx)`：下载单个 Excel 结果并直接翻译。
- `完整 Zip 包`：下载 Zip，自动解压并定位其中 Excel，再翻译。
- 翻译可以单独关闭。关闭后只做 Metascape 下载，不再修改 Excel。
- 翻译接口按 OpenAI Chat 兼容协议实现，需要提供 `API Base URL`、`API Key`、`Model`。
- 支持保存多套配置，启动时默认恢复上次使用的配置。
- 支持 Metascape 和翻译 API 分别选择直连或代理。
- 支持设置并发数量，默认 5 个并发。
- 界面内置三层进度：批处理总进度、Metascape 分析进度、翻译进度。
- 内置应用图标，源码运行和打包运行都可复用。
- 日志会记录单文件 Metascape 用时、翻译用时、总用时，并同时保存到 `logs/` 目录。
- 批处理进度会显示为 `x/y (z%)`。
- GUI 已迁移到 `PySide6`，用于彻底解决 Windows 高 DPI 下字体发虚问题。
- 主界面采用顶部标签页布局，信息更多时可以滚动。
- 支持递归扫描输入目录，并在输出目录中保留相对目录结构。
- 所有结果文件统一追加 `_metascape` 后缀。

## 项目结构

```text
MetaBatch/
├─ main.py
├─ requirements.txt
├─ README.md
├─ assets/
└─ metabatch/
   ├─ __init__.py
   ├─ assets.py
   ├─ excel_processor.py
   ├─ gene_reader.py
   ├─ gui.py
   ├─ metascape_client.py
   ├─ models.py
   ├─ paths.py
   ├─ runtime.py
   ├─ settings.py
   ├─ translator.py
   └─ workflow.py
```

## 安装

推荐直接使用本机 `py -3.11`：

```powershell
py -3.11 -m pip install -r requirements.txt
py -3.11 -m playwright install chromium
```

其中 GUI 使用 `PySide6`，首次安装体积会比 Tk 大一些，但字体清晰度和高 DPI 表现会更稳定。

## 启动

```powershell
py -3.11 main.py
```

## 使用方式

1. 选择基因列表文件夹。
2. 选择输出结果文件夹。
3. 选择下载类型。
4. 如果输入文件不是“每行一个基因”的单列文本，可以填写“基因所在列”。
5. 填入翻译接口信息：
   - `API Base URL`：例如 `https://your-api-host/v1`
   - `API Key`
   - `Model`
6. 在顶部配置区选择已有配置，或用“保存当前 / 另存为 / 删除”管理多套配置。
7. 需要时可以关闭翻译，或设置 Metascape / 翻译 API 的代理与并发数。
8. 点击“开始处理”。

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
- Zip 模式会额外创建：
  - `{输入文件名}_metascape_extracted/`

## 说明与限制

- 当前只实现 `Express Analysis`。
- Metascape 是单页应用，页面结构变动后，`metabatch/metascape_client.py` 中的候选选择器可能需要调整。
- 翻译时会在每次请求间隔至少 `0.1` 秒，并对 `429/5xx` 做有限重试。
- 如果 `Enrichment` 工作表中已经存在 `中文描述` 列，会跳过该文件，避免重复写入。
- 如果结果文件中没有 `Enrichment` 工作表，程序会将其视为失败，并提示“可能因为基因过少未产生富集结果”。
- 程序默认按输出目录中映射后的 `_metascape` 目标文件来做跳过，不会重复提交同名任务。
- 配置文件会保存在项目目录下的 `metabatch_config.json`，以 UTF-8 明文保存多套配置，其中包含 `API Key`。
- 每次运行都会在 `logs/` 目录下生成一份带时间戳的日志文件。
- `metabatch_summary.csv` 会写到输出根目录。
- 如果翻译 API 调用失败，程序会跳过该文件的翻译，继续处理下一个文件，并在 summary 中记录失败原因。

## 打包

安装 PyInstaller 后可以执行：

```powershell
py -3.11 -m pip install pyinstaller
py -3.11 -m PyInstaller --noconfirm --onefile --name MetaBatch main.py
```

项目里的路径处理已兼容 `__file__` / `sys._MEIPASS` 场景，方便后续单文件打包。
