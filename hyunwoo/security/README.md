# Bills security checks

These checks only apply to Bills files. They do not scan or change another
member's personal directory.

- Ruff checks the whole Bills backend whenever a Bills file is committed,
  including an evidence-only commit.
- detect-secrets checks Bills text files for possible credentials.
- pip-audit checks backend, test and security-tool dependencies against
  published vulnerability reports, including their resolved dependencies.

The hooks stop a commit when a check fails. They do not automatically fix,
stage, commit or push files. Dependency auditing needs internet access;
an unavailable audit service is a failed check, not a successful scan.

## Install after cloning

Run from the repository root:

```bash
python3 -m venv hyunwoo/.security-venv
hyunwoo/.security-venv/bin/python -m pip install -r hyunwoo/security/requirements.txt
hyunwoo/.security-venv/bin/pre-commit install --config hyunwoo/.pre-commit-config.yaml
```

Keep this environment in place: the installed Git hook uses its Python.
The environment and dependency-audit cache are ignored by Git.

If the clone already has a different pre-commit setup, coordinate with its
owner before installing this one. This clone had no existing pre-commit hook.

## Run checks without committing

```bash
hyunwoo/.security-venv/bin/pre-commit run --config hyunwoo/.pre-commit-config.yaml --all-files
```

This checks tracked Bills files. New files are checked when staged for a
commit. After staging, use the same command without `--all-files` to check
exactly the staged changes. Do not bypass a failing hook with `--no-verify`.

The same checks are included in the Bills GitHub Actions workflow. Its
endpoint evidence step tests the seeded bill list and the create/read/
update/delete lifecycle, then uploads the test results.

## Run the security tests

Three pytest tests in `hyunwoo/tests/pre_commit/` run Ruff, secret detection
and dependency auditing. The test requirements include the security tools,
so the existing CI backend test job installs them too. Ruff checks the
backend, matching the commit hook. Secret detection checks the backend,
frontend and tests. The audit covers the backend, test and security-tool
requirements, not unrelated packages in the local environment.

```bash
hyunwoo/.security-venv/bin/python -m pip install -r hyunwoo/backend/requirements.txt -r hyunwoo/tests/requirements.txt
hyunwoo/.security-venv/bin/python -m pytest hyunwoo/tests -v
```

Dependency auditing needs internet access. The tests fail if a tool fails,
times out, finds a possible secret or reports a vulnerable dependency.
The Testing Review reads the saved summary in
`hyunwoo/tests/pre_commit/security-tests.log`; the matching JUnit results
are saved alongside it. These manual test results do not replace actual
commit-time hook evidence.

For the required commit-time evidence, capture the hook output when you
make your own next Bills commit. A manual run is useful validation, but
is not evidence that a commit actually ran the hooks.

## Changes found during setup

The initial audit flagged older Flask, Requests and pytest versions. The
Bills requirements now use Flask 3.1.3, Requests 2.34.2 and pytest 9.0.3.
Direct local Flask execution also keeps the debugger off and only listens
on the local machine. Docker still uses Gunicorn as before.

Release notes: [Flask](https://flask.palletsprojects.com/en/stable/changes/),
[Requests](https://requests.readthedocs.io/en/latest/community/updates/).

Passing these checks does not prove the application is secure or add
authentication. The shared Multi-Agent Server must not be publicly exposed.
