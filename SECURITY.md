# Security Policy

## Supported Versions

Only the latest release on `main` receives security fixes.

| Version | Supported |
|---------|-----------|
| 0.x (latest, `commoner-analyse`) | ✅ |
| any `sansad-semantic-crawler` release | ❌ |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report privately via GitHub's [Security Advisories](https://github.com/CommonerLLP/commoner-analyse/security/advisories/new) feature.

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix if known

You will receive a response within 7 days. If the vulnerability is confirmed, a patch will be released as soon as possible with a coordinated disclosure.

## Scope

This package is a read-only analysis library over records acquired by `commoner-probe`. It optionally makes outbound HTTP requests to a local Ollama endpoint for the LLM discourse tier. It writes JSONL and SQLite files locally.

Known constraints:
- All three LLM call sites — the discourse-tier classifier
  (`analyse-discourse --llm-tier`), the ministry-query refinement path, and
  the topic classifier's `llm` mode (`--classifier llm` / a topic profile's
  `classifier.mode: "llm"`) — validate the endpoint scheme (HTTP/HTTPS only)
  via `llm_client.py`, and can optionally reject loopback/private/link-local
  hosts (`allow_private=False`; `"allow_private": false` in a topic profile's
  `classifier` block) to defeat SSRF against internal services.
- No authentication credentials are stored or transmitted beyond what the caller supplies
- `data/`, `notes/`, and `memory/` directories are gitignored and must never be committed
