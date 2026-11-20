# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Flask REST API for uploading CVs (PDF), extracting profile data (name, skills, work experiences) via spaCy + regex, and managing the user's skills/experiences. Code comments and logs are mostly in Italian.

## Commands

Python 3.14 in `.venv` (3.15 not usable yet: no PyYAML wheel, no C compiler on this machine). Use `.venv\Scripts\python` for everything.

```bash
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # also installs the it_core_news_sm spaCy model (pinned wheel URL)

.venv\Scripts\python run.py                  # dev server on 127.0.0.1:5000, Swagger UI at /apidocs

.venv\Scripts\python -m unittest discover tests            # all tests
.venv\Scripts\python -m unittest tests.test_auth.AuthTestCase.test_login_success   # single test
```

Don't install with `--only-binary=:all:`: Flasgger 0.9.7.1 (required for Flask 3, which removed `flask.Markup`) is published only as an sdist, so pip falls back to 0.9.5, which is broken on Flask 3.

No linter/formatter configured.

## Architecture

- `app/__init__.py` — `create_app()` factory: config is hardcoded (SQLite `db.sqlite`, `uploads/` folder, JWT secret), registers blueprints `/auth`, `/documents`, `/users`, `/process`, logs every request's headers/body, and calls `db.create_all()`. **No migrations**: schema changes to `app/models.py` require deleting the SQLite file (it lives in Flask's `instance/` dir).
- `app/models.py` — `User` owns `Document`, `Process`, `Skill`, `Experience`. `Process.status` is the `ProcessStatus` enum.
- `app/schemas.py` — Marshmallow schemas used for serialization.
- Auth: Flask-JWT-Extended; `app/utils/jwt.py` issues tokens with `identity=str(user.id)`, so `get_jwt_identity()` returns a **string** — cast with `int()` when comparing to integer ids.

### Upload → extraction flow (spans several files)

1. `POST /documents` (`app/routes/documents.py`) saves the file to `uploads/`, creates a `Document` and a `Process(PENDING)`, then starts a `threading.Thread` and returns the process with 202.
2. The thread (inside `app.app_context()`) reads the PDF with PyPDF2 and calls `extract_info_from_text(process, text)` in `app/services/extract_service.py`.
3. The service: first spaCy `PER` entity → `user.name/surname`; regex on the `COMPETENZE TECNICHE` section → `Skill` rows (fixed whitelist of languages/frameworks); `estrai_esperienze_generico` regex on `<company> MM/YYYY - MM/YYYY|present|oggi` lines → `Experience` rows. Sets process to `COMPLETED` or `ERROR` (+ `error_message`).
4. Client polls `GET /process/<id>` (returns 202) or `GET /process` for status.

Extracted rows are appended, never deduplicated; `POST /users/reset` deletes the user's documents/skills/experiences. `/users/skill` and `/users/experience` provide manual upsert/delete/list.

## Gotchas

- VS Code debugging on Python 3.14: debugpy's `sys.monitoring` backend crashes (`AssertionError` in `_pydevd_sys_monitoring_cython`) while importing spaCy's Cython modules. `.vscode/launch.json` sets `PYDEVD_USE_SYS_MONITORING=0` to fall back to `settrace`; keep it on any new debug config.

- `Document` column is `meta_data` (`metadata` is reserved by SQLAlchemy); the API form field / query param is still called `metadata`.
- Tests must pass overrides via `create_app({...})` (applied before `db.init_app`/`create_all`). Setting `app.config` after `create_app()` is too late, and `tearDown`'s `drop_all()` would wipe the real `db.sqlite`.
