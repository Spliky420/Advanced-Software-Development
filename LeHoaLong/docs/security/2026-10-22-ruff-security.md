# Static analysis — ruff security rules — 2026-10-22

**Tool:** ruff 0.16.6, rule set `S` (flake8-bandit), config `LeHoaLong/ruff.toml`
**Scope:** every Python file under `LeHoaLong/`
**Result:** 825 findings before, **0 after**. 4 fixed in code, 12 reviewed and
marked as not a vulnerability, 813 excluded by rule for tests.

## Before

```
$ ruff check LeHoaLong --extend-select S --statistics
813  S101  assert
 11  S608  hardcoded-sql-expression
  1  S104  hardcoded-bind-all-interfaces
Found 825 errors.
```

(One more S608 came to light in `tests/` once the 813 test asserts were out
of the way, so 12 S608 in total.)

## Fixed in code (4)

| Finding | Where | Risk | Fix |
| ------- | ----- | ---- | --- |
| S104 bind to all interfaces | `backend/wsgi.py:23` | `app.run(host="0.0.0.0", debug=True)`. Debug mode serves Werkzeug's interactive debugger, which runs any Python typed into an error page. On `0.0.0.0` anyone on the same network can reach it: remote code execution on the laptop. | Bound to `127.0.0.1`. The Vite dev proxy and a local browser both connect through localhost anyway. The container is unaffected, because it runs gunicorn and never reaches this line. |
| S101 assert | `backend/app/models/budget.py:47` | `assert row is not None` after the upsert. Python strips asserts under `-O`, so the check silently disappears and a `None` leaks into the route as a 500 with a confusing message. | `if row is None: raise RuntimeError(...)` naming the user. |
| S101 assert | `backend/app/services/validation.py:315` | `assert user_id is not None`, used to narrow the type. Under `-O` the function could return `None` as a user id. | Replaced the `if errors:` + assert pair with one `if user_id is None: raise ValidationFailed(errors)`. That is equivalent, because `raw` is not `None` there, so `clean_user_id` returns `None` exactly when it records an error. |
| S101 assert | `tools/build_corpus.py:327` | The corpus-alignment check vanishes under `-O`. | `sys.exit(...)` with the same message. |

## Reviewed, not vulnerable (12 × S608)

S608 flags any SQL built with an f-string. Each site was read; in every one
the interpolated text is fixed by the code, and every user-supplied value is
a `?` bound parameter. Each line carries a `# noqa: S608` with the reason, so
the rule stays on and a *new* string-built query still fails.

| Where | What is interpolated | Why it is safe |
| ----- | -------------------- | -------------- |
| `models/ai_log.py`, `budget.py`, `contributions.py`, `goals.py`, `steps.py` (`_SELECT`, ×5) | table name and the module's `COLUMNS` tuple | module constants |
| `models/contributions.py` (`totals_by_goal`) | `?, ?, ?` placeholders, one per id | only `?` characters; the ids are bound |
| `models/goals.py` (`update_goal`) | `col = ?` assignments | column names are filtered through the `UPDATABLE` whitelist; values bound |
| `models/steps.py` (`update_step`) | `col = ?` assignments | filtered through `UPDATABLE + ("source",)`; values bound |
| `database/init_db.py` (×2) | table name in `SELECT COUNT(*)` | iterates the `TABLES` constant |
| `tests/test_init_db_checks.py` | two SQL string constants concatenated | constants, test-only |

The property that makes the two `UPDATE` builders safe, and that must be
kept if they change: a column name reaches the SQL only after the
`UPDATABLE` whitelist has accepted it. A request body with a key like
`"name = 'x' --"` is dropped by the filter before any string is built.

## Excluded by rule (813 × S101 in tests)

`"tests/*" = ["E402", "S101"]` in `ruff.toml`. pytest is built on bare
`assert`, so in tests the rule is pure noise, and the risk it guards against
(asserts stripped under `-O`) does not apply to a test suite. Outside
`tests/` S101 stays on, which is what found the three asserts above.

## After

```
$ ruff check LeHoaLong
All checks passed!
```

421 tests pass. They also pass in a fresh virtualenv on the upgraded pins
from the dependency report.
