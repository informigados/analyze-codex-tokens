# 🧠 Analyze Codex Tokens

Understand exactly how your Codex sessions consume tokens.

This tool scans your local Codex logs and generates a **clear, structured analysis** of usage, costs, prompts, and agent behavior.

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
* ⚖️ Input vs output ratios
* 🧠 Instruction-heavy sessions
* 📉 Optimization insights

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
~/.codex/analysis/tokens/
```

Files generated:

* `token_report.md`
* `/prompts/*.md`

## 🔧 Optional Configuration

### Filter by last N days

```bash
export SINCE_DAYS=7
```

### Filter by date

```bash
export SINCE_DATE="2026-03-30"
```

### Custom Codex directory

```bash
export CODEX_HOME="/path/to/.codex"
```

### Custom output directory

```bash
export OUTPUT_DIR="/path/to/output"
```

## 🧠 Key Features

* 🔍 Recursive `.jsonl` discovery (works with VS Code extension)
* 🤖 Subagent tracking and cost analysis
* 📊 Deep token breakdown
* 📈 Identify inefficiencies fast

## ⚠️ Notes

* Requires local Codex logs
* If no data appears, check your `.codex` folder
* VS Code extension may store additional data in `.sqlite` (not parsed yet)

## 📝 Changelog

### 2026-04-10 (1.0.0)

- Initial release.

## 👥 Authors

- INformigados: https://github.com/informigados/
- Alex Brito: https://github.com/alexbritodev

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
