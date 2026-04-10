# 🤝 Contributing Guide

Thanks for your interest in contributing to **Analyze Codex Tokens**.

> ℹ️ **Codex** is an OpenAI product. This repository is an independent analyzer and is not an official OpenAI repository.

## 🎯 Contribution Scope

Good contributions include:

- Bug fixes
- Test coverage improvements
- Documentation improvements
- Performance and maintainability improvements
- New report insights that stay aligned with the current project goals

## 🧰 Local Setup

Requirements:

- Python 3.10+
- Git

Run locally:

```bash
python analyze-codex-tokens.py
```

Windows PowerShell:

```powershell
py analyze-codex-tokens.py
```

## ✅ Testing

Before opening a PR, run tests:

```bash
python -m unittest discover -s tests -v
```

PowerShell:

```powershell
py -m unittest discover -s tests -v
```

## 🧭 Code Style

- Keep changes focused and small.
- Preserve current naming and structure when possible.
- Add or update tests for behavior changes.
- Keep docs in sync with code changes.
- Prefer clear, explicit logic over clever shortcuts.

## 📝 Commit Guidelines

- Use concise, descriptive commit messages.
- Group related changes in the same commit.
- Avoid mixing refactors and feature changes without reason.

Example:

```text
feat: add language-prefixed timestamp output folders
```

## 🚀 Pull Request Checklist

Before submitting:

- Tests pass locally.
- Documentation was updated (if needed).
- No sensitive/local files were included.
- Generated artifacts were not committed (for example: `reports/`, `prompts/`, caches).
- PR description explains what changed and why.

## 🐞 Reporting Issues

When opening an issue, include:

- Clear summary
- Steps to reproduce
- Expected behavior
- Actual behavior
- Environment details (OS, Python version, command used)

## 🔐 Security

Please do not post secrets, private logs, tokens, or exploit details in public issues.

For responsible disclosure, follow the instructions in [SECURITY.md](SECURITY.md).

## 💬 Questions

If you are unsure about an idea, open an issue first to discuss scope and approach before implementing a large change.
