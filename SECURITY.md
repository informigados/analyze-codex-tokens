# 🔐 Security Policy

> ℹ️ **Codex** is an OpenAI product. This repository is an independent analyzer and is not an official OpenAI repository.

## ✅ Supported Versions

This project currently follows a simple support model:

| Version | Status |
| ------- | ------ |
| Latest release (`main`) | ✅ Supported |
| Older releases | ⚠️ Best effort |

## 🚨 Reporting a Vulnerability

If you find a security issue, please report it responsibly:

1. Prefer **GitHub Security Advisories (private report)** for this repository.
2. If private reporting is unavailable, open an issue titled: `SECURITY: <short summary>`.
3. Do **not** include secrets, tokens, private logs, or exploit code in public issues.

Please include:

- Affected file(s) and function(s)
- Reproduction steps
- Expected vs actual behavior
- Impact assessment
- Suggested fix (optional)

## ⏱️ Response Expectations

- Initial triage response: up to **7 days**
- Status updates for validated issues: every **7-14 days**
- Fix timeline depends on severity and maintainer availability

## 🛡️ Scope Notes

This script is local/offline-oriented and does not run a network service.  
Main risks are usually related to:

- Unsafe handling of local logs
- Accidental exposure of sensitive prompt content
- Misconfiguration of output/report directories
