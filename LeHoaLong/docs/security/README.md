# Security reports — Goals and Budgeting

One file per check per run, named `YYYY-MM-DD-<check>.md`, so the history
shows what each check found on a given day and what was done about it.
Older reports are never edited; a new run gets a new file.

| Check | Tool | What it covers | Runs in |
| ----- | ---- | -------------- | ------- |
| Static analysis | ruff `S` rules (flake8-bandit) | `LeHoaLong/**/*.py` | pre-commit, CI `backend` job |
| Dependencies | pip-audit 2.10.1 | `backend/requirements.txt`, `tests/requirements.txt` | pre-commit (when either file changes), CI `backend` job, CI weekly schedule |
| Secrets | detect-secrets 1.5.0 | every tracked file in the repository | pre-commit |

## Reports

| Date | Static analysis | Dependencies | Secrets |
| ---- | --------------- | ------------ | ------- |
| 2026-10-22 | [825 → 0](2026-10-22-ruff-security.md) | [4 advisories → 0](2026-10-22-pip-audit.md) | [0 findings](2026-10-22-detect-secrets.md) |
| 2026-10-25 (rerun, raw logs) | [0](logs/2026-10-25-ruff-security.txt) | [0](logs/2026-10-25-pip-audit.txt) | [0, canary caught](logs/2026-10-25-detect-secrets.txt) |

## Re-running

From the repository root:

```bash
pip install ruff==0.16.6 pip-audit==2.10.1 detect-secrets==1.5.0

ruff check LeHoaLong --statistics
pip-audit -r LeHoaLong/backend/requirements.txt
pip-audit -r LeHoaLong/tests/requirements.txt
detect-secrets scan --baseline .secrets.baseline   # then: detect-secrets audit .secrets.baseline
```

Or all of them at once, with the hooks installed: `pre-commit run --all-files`.

On Windows Git Bash, set `MSYS_NO_PATHCONV=1` before passing a regex to
`detect-secrets scan --exclude-files`: Git Bash otherwise rewrites
`(^|/)package-lock\.json$` into a Windows path, and the baseline records a
pattern that never matches.
