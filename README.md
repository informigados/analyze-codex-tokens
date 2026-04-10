# 🧠 Analyze Codex Tokens

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](#-tests)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Understand exactly how your Codex sessions consume tokens.

> ℹ️ **Codex** is an OpenAI product. This project is an independent local analyzer for Codex session logs.

This tool scans your local Codex logs and generates a **clear, structured analysis** of usage, costs, prompts, and agent behavior.
It also supports localized console/report output with English as the default base language.

## 🚀 What It Does

Analyzes `.jsonl` session logs from:

* `~/.codex/sessions`
* `~/.codex/archived_sessions`

Then generates:

### 📊 Token Report

A complete breakdown of:

* 🔢 Total tokens (input, output, cached, reasoning)
* 📁 Usage by project
* 💸 Most expensive sessions
* 🤖 Subagent usage & overhead
* 🔗 Subagents without parent in selected range
* ⚖️ Input vs output ratios
* 🧠 Instruction-heavy sessions
* 📉 Optimization insights
* 🧾 Structured JSON output for automation

### 🧾 Prompt Extraction

Creates a `/prompts` folder with:

* All user prompts
* Organized by project
* Sorted by time

## ⚙️ Requirements

* Python 3.10+
* No external dependencies

## ▶️ How to Run

### Run the script

```bash
python analyze-codex-tokens.py
```

or on Windows:

```powershell
py analyze-codex-tokens.py
```

## 📂 Output

Default location:

```
./reports/<lang>-YYYY-MM-DD_HHMMSS/
```

Files generated:

* `token_report.md`
* `token_report.json`
* `/prompts/*.md`

## 🧩 CLI Options

You can run with direct CLI flags (recommended for CI/scripts):

```bash
python analyze-codex-tokens.py \
  --since-days 7 \
  --lang pt-br \
  --output-dir ./reports \
  --redact-prompts \
  --json
```

Windows PowerShell:

```powershell
py analyze-codex-tokens.py --since-days 7 --lang pt-br --output-dir .\reports --redact-prompts --json
```

Available flags:

* `--since-days N`
* `--since-date YYYY-MM-DD`
* `--codex-home PATH`
* `--output-dir PATH`
* `--lang en|pt-br|pt-pt|es`
* `--redact-prompts` / `--no-redact-prompts`
* `--json` / `--no-json`

## 🔧 Optional Configuration (ENV Fallback)

### Filter by last N days

```bash
export SINCE_DAYS=7
```

```powershell
$env:SINCE_DAYS="7"
```

### Filter by date

```bash
export SINCE_DATE="2026-03-30"
```

```powershell
$env:SINCE_DATE="2026-03-30"
```

### Custom Codex directory

```bash
export CODEX_HOME="/path/to/.codex"
```

```powershell
$env:CODEX_HOME="C:\path\to\.codex"
```

### Custom output directory

```bash
export OUTPUT_DIR="/path/to/output"
```

```powershell
$env:OUTPUT_DIR="C:\path\to\output"
```

If `OUTPUT_DIR` is not set and `--output-dir` is not provided, the script creates a language-prefixed timestamped folder under:

```
./reports/<lang>-<timestamp>/
```

### Redact prompts in outputs

```bash
export REDACT_PROMPTS=true
```

```powershell
$env:REDACT_PROMPTS="true"
```

### Toggle JSON output

```bash
export WRITE_JSON=true
```

```powershell
$env:WRITE_JSON="true"
```

### Language for console/report output

```bash
export REPORT_LANG="pt-br"
```

```powershell
$env:REPORT_LANG="pt-br"
```

Supported values:

* `en` (default)
* `pt-br`
* `pt-pt`
* `es`

Examples:

Generate report in Brazilian Portuguese with automatic folder naming (PowerShell):

```powershell
py analyze-codex-tokens.py --lang pt-br
```

Generate report in European Portuguese with automatic folder naming (Bash):

```bash
python analyze-codex-tokens.py --lang pt-pt
```

Use environment variable in PowerShell, then run normally:

```powershell
$env:REPORT_LANG="es"
py analyze-codex-tokens.py
```

Use environment variable in Windows CMD:

```cmd
set REPORT_LANG=en
py analyze-codex-tokens.py
```

`--lang` takes precedence over `REPORT_LANG` when both are set.

If you use `--output-dir .\reports` (or `./reports/<lang>`), the tool also auto-creates `<lang>-<timestamp>` inside `reports`.

## 🧠 Key Features

* 🔍 Recursive `.jsonl` discovery (works with VS Code extension)
* 🤖 Subagent tracking and cost analysis
* 🧱 Markdown-safe report formatting (better organization/readability)
* 🧾 JSON report export (`token_report.json`)
* 🔒 Optional prompt redaction mode
* 📊 Deep token breakdown
* 📈 Identify inefficiencies fast

## ⚠️ Notes

* Requires local Codex logs
* Only sessions with `total_tokens > 0` are included in the analysis
* If no data appears, check your `.codex` folder
* VS Code extension may store additional data in `.sqlite` (not parsed yet)

## ✅ Tests

Run unit tests:

```bash
python -m unittest discover -s tests -v
```

PowerShell:

```powershell
py -m unittest discover -s tests -v
```

## 📝 Changelog

### 2026-04-10 (1.0.0)

- Initial release.

## 👥 Authors

- INformigados: https://github.com/informigados/
- Alex Brito: https://github.com/alexbritodev

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
