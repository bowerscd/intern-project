# Copilot Workspace Instructions

## AI Knowledge Base

Before making any changes, read and internalize all rules in `.ai/lessons.jsonl`.
Each line is a JSON object with a `rule` field — treat every rule as a hard constraint.
Append new lessons to that file when you discover project-specific gotchas or are corrected by the user.

## Quick Reference

- **Setup**: `make setup` (root Makefile creates all venvs + installs deps + configures git hooks)
- **Test**: `make test` (backend + frontend) · `make test-integration` (Docker/Podman stack)
- **Lint**: `make lint` · **Format**: `make format`
- **Pre-commit hook** runs lint + tests automatically — do not bypass without reason
- **Shell**: fish — no bash heredocs, no `[[` conditionals
- **No sudo** in automation — Podman is rootless
- **No PII** in `.ai/` — it's committed to a public repo
