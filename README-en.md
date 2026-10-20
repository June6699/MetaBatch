# MetaBatch

**English | [简体中文](README.md)**

MetaBatch is a Python 3.11 desktop tool for batch enrichment analysis on [Metascape](https://metascape.org). It reads gene lists in bulk, automatically opens Metascape's Express Analysis page via Playwright, submits the analysis, and downloads the results. When translation is enabled, it sends the `Description` column of the `Enrichment` worksheet to an AI translation API in the selected target language (Simplified Chinese by default, appended as a `中文描述` column).

## Features

- **Batch processing**: recursively scans the input directory for gene list files, with glob filtering ("File pattern" accepts `*.txt`, `*gene*`, etc.; separate multiple patterns with `;`; leave empty to match all supported types). The UI shows "Matched files: N" live. It mirrors the input's relative directory structure in the output directory and appends the `_metascape` suffix to all results.
- **Input formats**: supports `txt`, `csv`, `tsv`, `xlsx`, and `xls`, with UTF-8 (including BOM) and GBK/GB2312 encodings. Inputs that share a stem but differ in extension (e.g. `a.txt` and `a.xlsx`) are disambiguated automatically and never overwrite each other.
- **Custom gene column**:
  - Leave empty: defaults to the first column.
  - A number: interpreted as a 1-based column index, e.g. `1`, `3`.
  - An Excel column letter: e.g. `A`, `C`.
  - A header name: e.g. `gene_symbol`, located via the first-row header.
- **Download types**:
  - `Excel only (xlsx)`: downloads the single Excel result and translates it directly.
  - `Full Zip package`: downloads the Zip, extracts it, locates the Excel inside, then translates.
- **AI translation**: calls an OpenAI-compatible chat API (also compatible with the native Anthropic Messages format and the OpenAI Responses format), with one-click model fetching and connection testing. The translation target language is selectable (Simplified Chinese by default; English is not offered because Metascape descriptions are already in English): Traditional Chinese, Japanese, Korean, French, German, Spanish, Portuguese, Russian, and Italian are available. Batch requests are size-adaptive: pending items with ≤4000 total characters (and ≤100 items) are sent in a single request; otherwise they are split into the minimum number of chunks, written back in order, and cached across workers to avoid duplicate requests; `429/5xx` responses are retried with exponential backoff.
- **Multiple profiles**: save and switch between multiple configuration profiles; the last-used profile is restored on startup. The UI language (中文 / English) and the translation target language are persisted per profile.
- **Large list guard**: "Skip lists with more than N genes" is enabled by default with an **editable limit** (default 5000) — oversized lists are not submitted to Metascape (lists with thousands of genes make the Metascape input box extremely slow and can hang the page); they are reported as "too many genes" in the log and the report. Uncheck the box to disable the guard.
- **Result report**: every run writes `metabatch_gene_report.csv` (UTF-8 BOM) to the output root, covering **all input files** with gene count, whether Metascape ran, whether translation happened, status, skip reason, and message — so it is immediately clear which files produced no result and why.
- **Automatic resume**: before each run the output folder is scanned; files that already finished (`*_metascape.xlsx` present with an `Enrichment` sheet, plus the target-language column when translation is enabled) are skipped, and only unfinished or new files are processed. After an interruption, just press Start again to continue where it stopped.
- **Translation pre-check**: one minimal translation request is sent at the start of each run. If the endpoint is unavailable (bad key, wrong URL, timeout), translation is paused for that run, Metascape results keep downloading, and the log, progress page, and summary say so explicitly — instead of every file waiting for its own timeout.
- **Connections**: Metascape and the translation API can each use a direct connection or a proxy; concurrency is adjustable (default 5, max 32).
- **Bilingual UI**: switch between 中文 and English with one click in the dedicated "语言 / Language" tab at the top, effective immediately; log and error messages follow the UI language.
- **Progress and logs**: three progress bars (batch, Metascape analysis, translation) plus per-worker progress cards and log tabs; logs are color-coded by type and written to the `logs/` directory, recording per-file Metascape time, translation time, and total time. Batch progress is shown as `x/y (z%)`.
- **Robustness**: workers rest for a random 5–10 seconds between files to avoid rate limiting; existing results are skipped automatically (resume support, and half-written result files are re-run); after 20 consecutive failures the remaining files are no longer submitted (usually a network or API configuration problem — starting again afterwards resumes automatically); a single failed file does not affect the rest; scroll-wheel protection prevents accidentally changing dropdowns or tabs while scrolling.
- **Ready to go**: built-in app icon, reusable for both source runs and PyInstaller-packaged runs.

## Project Structure

```text
MetaBatch/
├─ main.py                          # Entry point
├─ build.bat                        # One-click build script (double-click)
├─ MetaBatch.spec                   # PyInstaller build configuration
├─ requirements.txt
├─ README.md / README-en.md
├─ update.md                        # Update log
├─ translate_boundary_metascape.py  # Offline backfill translation CLI
├─ assets/
│  └─ metabatch_icon.ico
├─ runtime_hooks/
│  ├─ crash_handler.py              # Global crash handler (runtime hook)
│  └─ qt_dll_path.py                # Qt DLL search path (runtime hook)
├─ metabatch/
│  ├─ __init__.py
│  ├─ assets.py                      # app icon generation
│  ├─ excel_processor.py             # Enrichment sheet translation and column widths
│  ├─ gene_reader.py                 # gene list discovery and reading
│  ├─ gui.py                          # PySide6 main window
│  ├─ i18n.py                         # bilingual UI text dictionary
│  ├─ logging_utils.py                # run logs
│  ├─ metascape_client.py             # Playwright automation
│  ├─ models.py                        # data models and translation language definitions
│  ├─ paths.py                         # output path rules
│  ├─ runtime.py                       # frozen/source path compatibility
│  ├─ settings.py                      # settings persistence
│  ├─ translator.py                    # OpenAI-compatible translation client
│  └─ workflow.py                      # concurrent task scheduling
├─ demo/                              # sample inputs and results (not distributed)
└─ tests/
```

## Installation

Using the local `py -3.11` launcher is recommended:

```powershell
py -3.11 -m pip install -r requirements.txt
py -3.11 -m playwright install chromium
```

## Running

```powershell
py -3.11 main.py
```

## Usage

1. Select the gene list folder.
2. Select the output folder.
3. If the folder contains both gene lists and Metascape results (e.g. `.txt` and `.xlsx` together), enter `*.txt` in "File pattern" to process only the txt files; leave empty to process all supported types. The UI shows "Matched files: N".
4. Choose the download type.
5. If the input is not a single-column text file with one gene per line, fill in the gene column.
6. Fill in the translation API details:
   - `API Base URL`: e.g. `https://your-api-host/v1`
   - `API Key`
   - `Model` (use "Fetch Models" to pull the list, "Test Connection" to verify)
   - Choose `API format` and `Auth field` according to your provider
7. For other languages, pick a target language (Simplified Chinese by default).
8. Select an existing profile in the top bar, or manage profiles with "Save / Save As / Delete"; the UI language switch lives in the dedicated "语言 / Language" tab at the top.
9. Optionally disable translation, or configure proxies and concurrency for Metascape / the translation API.
10. Click "Start".

## Input File Example

A `txt` file like the one below can be used directly, with no gene column setup:

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

For structured files such as `xlsx/xls/tsv/csv`, specify which column holds the genes.

## Output Rules

- The input directory is scanned recursively; the output directory mirrors the relative structure under the input root.
- All result files get the `_metascape` suffix.
  - Given the input:
    - `mouse\timepoint_comparisons\D56_Immune_A_M24_Immune_B_FDR0.05.txt`
  - and the output root:
    - `mouse_metascape`
  - the output Excel is:
    - `mouse_metascape\timepoint_comparisons\D56_Immune_A_M24_Immune_B_FDR0.05_metascape.xlsx`
  - and the output Zip is:
    - `mouse_metascape\timepoint_comparisons\D56_Immune_A_M24_Immune_B_FDR0.05_metascape.zip`
- When inputs in the same folder share a stem but differ in extension (e.g. `a.txt` and `a.xlsx`), the original extension is appended to the output name to avoid overwriting, e.g. `a_txt_metascape.xlsx` and `a_xlsx_metascape.xlsx`.
- Zip mode additionally creates:
  - `{input file name}_metascape_extracted/`

## Configuration and Logs

- Settings are stored in `metabatch_config.json` next to the program, saving multiple profiles as UTF-8 plain text. **It contains API Keys — do not share it.** Writes use atomic temp-file replacement, so an unexpected crash cannot corrupt the file.
- Every run creates a timestamped log file in the `logs/` directory.
- `metabatch_summary.csv` is written to the output root, summarizing each file's status, timing, and failure reasons. It also carries `gene_count`, `skipped_reason` (`已有结果` / `基因过多`), `translation_status` (`translated` / `paused` / `failed` / `disabled`), and `translation_message`, so it is obvious at which stage a file failed to produce a result.
- `metabatch_gene_report.csv` is the human-readable report (UTF-8 BOM, opens directly in Excel): one row per input file with gene count, `metascape` (done / not done / existing result / partly done), `translated` (translated / paused / translation failed / not translated / unknown), and the failure reason.
- Source and exe launches use separate configuration files: `py -3.11 main.py` reads the project-root file, while the packaged `dist/MetaBatch/MetaBatch.exe` reads `dist/MetaBatch/metabatch_config.json` next to it. Input folders, proxies, and API settings are not synchronized automatically.

## Offline Backfill Translation

`translate_boundary_metascape.py` batch-translates an **existing result folder** without re-running Metascape:

```powershell
$env:METABATCH_TRANSLATION_API_KEY = "your-key"
py -3.11 translate_boundary_metascape.py --results-dir "results-dir" --model "deepseek-flash"
```

By default it calls `https://api.deepseek.com/v1/chat/completions` (use `--api-base-url` for another OpenAI-compatible endpoint). It appends the translation column to existing result workbooks, so **files whose translation was paused or failed during a run can be backfilled in one pass**.

It recursively processes every `*_metascape.xlsx`, skips already-translated files or those without an `Enrichment` sheet, deduplicates and batch-translates the unique descriptions, and writes `metabatch_translation_summary.tsv` to the result folder.

## Notes and Limitations

- Only `Express Analysis` is currently implemented.
- Metascape **intermittently enters maintenance** (redirecting to `maintenance.html`): the log then says explicitly that the maintenance page was returned and that the tool is waiting for recovery; the run keeps polling instead of misreporting a broken selector.
- Very small gene lists (measured with 40 genes) do not produce an `Enrichment` sheet, so that file's translation stage is recorded as failed (shown as "translation failed" in the report) while the Metascape result itself is kept.
- Metascape is a single-page application; if its page structure changes, the candidate selectors in `metabatch/metascape_client.py` may need updating.
- Button clicks prefer **DOM clicks**: measured locally, `locator.click()` (including `force=True`) hangs for a full 30 seconds under 5-way concurrency, while a DOM click finishes in 1–8 seconds; mouse clicks are only a fallback (8-second cap per attempt). When a click finally fails, a `click_failure_*.png` screenshot plus the element states are saved under `logs/`.
- Metascape's `maintenance.html` is usually a **false alarm**: `app.js` redirects there when the synchronous `health_check_pull` call returns `1` *or fails*, while the backend consistently answered `0` in testing. On hitting that page the tool first reloads a few times (2-second gaps) to recover, logging the page URL/title at each step.
- Concurrency is capped by the CPU (each headless browser needs about two logical cores), and each file waits for the system CPU to drop below 70% before starting, so a starved renderer cannot stall clicks.
- After finishing a file, a worker rests for a random 5–10 seconds before the next one to reduce the risk of Metascape rate limiting.
- Translation requests are spaced at least `0.1` seconds apart, with limited retries for `429/5xx`; `4xx` errors (e.g. a bad key) fail immediately.
- If the `Enrichment` worksheet already contains a translation column for the target language (`中文描述` for Simplified Chinese), the file is skipped to avoid duplicate writing.
- If the result file has no `Enrichment` worksheet, it is treated as a failure with the hint that the gene list may be too small to produce enrichment results.
- Skip detection is based on the mapped `_metascape` target file in the output directory, so identical tasks are never submitted twice. An existing result that lacks the `Enrichment` sheet, or that is missing the target-language column while translation is enabled, counts as unfinished and is re-run.
- A list with more genes than the limit (5000 by default, toggled by the "Large list guard" checkbox) is skipped: the Metascape input box responds extremely slowly to lists with thousands of genes — measured with 8000 genes, `fill()` times out after 30 seconds.
- If a translation API call fails, that file is recorded as `partial` (Metascape result downloaded, translation failed), the next file is processed, and the reason is recorded in the summary. If the pre-run translation pre-check already fails, translation is paused for the whole run.
- The Responses format uses `instructions`, `input`, and `max_output_tokens` for GPT-5-style models and omits the incompatible `temperature` parameter.

## Packaging

The easiest way is to **double-click `build.bat`** in the project root; or run manually:

```powershell
py -3.11 -m pip install pyinstaller
py -3.11 -m PyInstaller --clean --noconfirm MetaBatch.spec
```

### Output layout (onedir)

The result is a directory (fast startup, easy to troubleshoot):

```text
dist/MetaBatch/
├─ MetaBatch.exe          # Main program (double-click)
└─ _internal/             # All runtime dependencies (PySide6, playwright, Python runtime, ...)
```

### Size breakdown and trimming

`_internal` is about 186 MB:

| Part | ~Size | Notes |
|---|---|---|
| playwright | 102 MB | Includes `node.exe` (~87 MB), the runtime playwright uses to drive the browser — **required** |
| PySide6 | 55 MB | Qt Core/Gui/Widgets, required for the GUI |
| PIL & others | ~30 MB | Icon generation, certificates, charset, greenlet, ... |

`MetaBatch.spec` already excludes unused Qt modules (WebEngine, Qml/Quick, Multimedia, 3D, Pdf, ...) and optional dependencies pulled in via third-party `try/except` imports (numpy/OpenBLAS, lxml, h2, cryptography, `opengl32sw`, AVIF, OpenSSL 3), reducing the size from ~280 MB to ~186 MB. If rendering misbehaves in an extreme GPU-less environment, remove the corresponding exclusion from the spec and rebuild.

### Crash handling and logs

- The packaged build installs a global crash hook: uncaught exceptions are written to `logs/metabatch_crash_*.log` next to the exe with a friendly dialog, instead of the raw PyInstaller error box.
- If double-clicking the exe shows no window, inspect `dist/MetaBatch/logs/`; the windowed build hides the console, and the logs usually pinpoint configuration, browser, or page issues.

### Distributing to other computers

The Playwright **Chromium browser binaries** are not inside the pip package / dist (they live in the packager's `ms-playwright` cache). After copying the whole `dist/MetaBatch/` folder to a clean machine, install the browser once:

```powershell
py -3.11 -m playwright install chromium
```

(The Python packages and the node driver are already in `_internal`; there is no need to install the playwright package separately.) Modern PySide6 has ICU built in, so no separate ICU files are needed. If `DLL load failed while importing QtCore` still appears, make sure you are running the newly rebuilt `dist/MetaBatch/MetaBatch.exe`, not an older copy.

## Development and Testing

```powershell
py -3.11 -m unittest discover -s tests
```

Tests cover the translation client's retry strategy and in-flight deduplication, input file encoding compatibility, output path rules, and UI dictionary completeness.
