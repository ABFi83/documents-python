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

1. `POST /documents` (`app/routes/documents.py`) takes one or more PDFs (multipart field `files`, repeated; `file` still accepted), rejects the whole request with 400 if any is not a PDF, and per file saves it to `uploads/`, creates a `Document` + `Process(PENDING, document=doc)` and starts a `threading.Thread` (`analyze_file`, gets the process **id** and re-queries it). Returns the list of processes with 202.
2. The thread gets the text with `pdf_to_text` (`app/services/text_service.py`): docling-serve `POST /v1/convert/file` with `to_formats=text` (plain text, not markdown, so the regexes still match), falling back to PyPDF2 (no OCR) if Docling is down or fails. Docling URL: env `DOCLING_URL`, default `http://localhost:5001`; run it with `docker run -d --name docling -p 5001:5001 quay.io/docling-project/docling-serve`. Text read failure → process `ERROR`.
3. `extract_info_from_text(process, text)` (`app/services/extract_service.py`): `estrai_nome` (first spaCy `PER`) → also written to `user.name/surname`; `estrai_skill` (section `COMPETENZE [TECNICHE]`, fixed whitelist); `estrai_esperienze_generico` (lines `<head> <date> – <date|oggi>`, dates `MM/YYYY`, `set 2025`, `2025`; head `Ruolo — Azienda` or company only; text from `FORMAZIONE`/`ISTRUZIONE` on is ignored). The result is stored as JSON in `Process.result` (`{nome, cognome, linguaggi, frameworks, esperienze:[{azienda, ruolo, start_date, end_date (ISO date|null), description}]}`): **it does not create `Skill`/`Experience` rows** — the user profile is manual only (`/users/skill`, `/users/experience`).
   Every write of the thread goes through `save_process` (`extract_service.py`): a conditional `UPDATE process ... WHERE id=?` done **first** in the transaction (on SQLite it takes the write lock); `rowcount == 0` means the CV was deleted while being analyzed → rollback, nothing written (user name included). Keep that order if you add writes. `analyze_file` also skips Docling when the process is already gone.
4. History: `GET /documents` (newest first) and `GET /documents/<id>` return each document with its `process` (status + `result`). `GET /documents/summary` = `somma_estrazioni` (`app/services/summary_service.py`) over the `COMPLETED` CVs: skills merged case-insensitively, experiences deduplicated on (azienda, ruolo, start_date) keeping the newest CV's data, each item with `document_ids`. `DELETE /documents/<id>` removes process, document and file, also while the CV is still being analyzed. `GET /process/<id>` (returns 202) / `GET /process` still work. `POST /users/reset` deletes the user's processes, documents, skills and experiences.

## Job-search agent

An LLM agent searches the web for positions matching a `SearchProfile`; the user rates/moves them. FE contract: `docs/fe/2026-11-21-agente-ricerca-fe-brief.md`. Spec: `docs/superpowers/specs/2026-11-21-agente-ricerca-posizioni-design.md`.

- Routes: `settings.py` (`/settings`: providers, AI connections, test), `search_profiles.py` (`/search-profiles`: criteria CRUD, `/suggestions` from CVs, start/list runs), `runs.py` (`/runs`: get, answer, cancel, delete), `positions.py` (`/positions`: list, detail+events, vote, status, delete, `/manual`).
- `app/services/agent/`: `runner.py` (loop + `save_run`), `tools.py` (tool specs + checks: `cerca_web`, `leggi_pagina`, `salva_posizione`, `fai_domanda`), `context.py` (profile without personal data + feedback summary), `prompt.py`, `pages.py` (`read_page`, SSRF-safe). `app/services/positions.py`: `TRANSITIONS`, URL/company dedup, `classify_reason`, `extract_position`.
- Run lifecycle: `PENDING → RUNNING → COMPLETED | ERROR | CANCELLED`, with `RUNNING ⇄ WAITING_INPUT` when the agent calls `fai_domanda` (`question` set; `POST /runs/<id>/answer` resumes in a new thread). One active run per user (409): enforced by the partial unique index `uq_search_run_attivo` on `search_run(user_id) WHERE status IN ('PENDING','RUNNING','WAITING_INPUT')` (enum **names** are stored); `start_run` catches `IntegrityError`. Since there are no migrations, `create_app` also creates `SearchRun`'s indexes with `checkfirst` after `create_all`, so existing DBs get it on startup. Step/search/page/save counters live in `SearchRun.counters`.
- Step limit: when the next step is the last one, the runner appends a wrap-up note (`ULTIMO_PASSO`) to that turn's tool results and refuses `fai_domanda` (is_error), so a run never pauses at the limit; a resume after an answer always runs at least one step.
- Personal data never reaches the AI: `estrai_ruolo_obiettivo(text, nome, cognome)` reads the headline only after the line holding the name (None if the name isn't found; skips address/contact lines), and `profile_context` / `/suggestions` drop any role containing a word of the user's or a CV's name/surname (`contiene_nome`, `nomi_personali` in `summary_service.py`). The initial message carries today's date (`initial_message(..., oggi=None)`), the system prompt stays static for caching.
- `save_run(run_id, expected, **values)`: conditional `UPDATE ... WHERE status = expected` first in the transaction; `rowcount == 0` → rollback and the thread stops without writing (run was cancelled/deleted). Every thread write goes through it; positions are `add_all`ed only after it returns True.
- `conversation` / `pending_results` are append-only: only through `adapter.start/step/add_tool_results`, never edited (provider-specific format, e.g. thinking blocks must be passed back untouched).
- Adapters (`app/services/ai/`): `LlmAdapter`/`SearchAdapter` in `base.py`, one class per provider (no LiteLLM), registered in `registry.py` (`LLM_PROVIDERS` with `models`/`default_model`, `SEARCH_PROVIDERS`). To add a provider: implement the adapter (raise `AdapterError` with a safe message, never the key), add it to the registry dict, add a test with mocks. `/settings/providers` picks it up automatically.
- API keys: encrypted with Fernet (`app/utils/crypto.py`), only `key_last4` is returned, `/settings` bodies are never logged. `ENCRYPTION_KEY` env var is required to save/use keys (without it: 400 on save, `AdapterError` on use). Generate: `.venv\Scripts\python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Changing it makes stored keys undecryptable (users re-enter them).
- Limits per run (config in `create_app`, override in tests): `AGENT_MAX_STEPS=30`, `AGENT_MAX_SEARCHES=15`, `AGENT_MAX_PAGES=25`, `AGENT_MAX_SAVED=20`.
- Tests: `tests/fakes.py` — `register_fakes()` adds provider `fake`, `reset_fakes()` clears class state; `FakeLlm.script` (list of turns with `tool_calls`/`error`), `FakeLlm.json_reply` (for `extract_json`), `FakeSearch.results/error`. Run threads are made synchronous with `patch('app.routes.<module>.Thread', SyncThread)` (`tests/test_documents.py`). No network in tests.

## Gotchas

- VS Code debugging on Python 3.14: debugpy's `sys.monitoring` backend crashes (`AssertionError` in `_pydevd_sys_monitoring_cython`) while importing spaCy's Cython modules. `.vscode/launch.json` sets `PYDEVD_USE_SYS_MONITORING=0` to fall back to `settrace`; keep it on any new debug config.

- `Document` column is `meta_data` (`metadata` is reserved by SQLAlchemy); the API form field / query param is still called `metadata`.
- Tests must pass overrides via `create_app({...})` (applied before `db.init_app`/`create_all`). Setting `app.config` after `create_app()` is too late, and `tearDown`'s `drop_all()` would wipe the real `db.sqlite`.
