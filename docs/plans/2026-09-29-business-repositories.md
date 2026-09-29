# Business Repository Split Implementation Plan

**Goal:** Group existing database operations by business without changing SQL or public repository calls.

**Architecture:** Replace `kb_api/dao.py` with `kb_api/api/dao/`, containing apps, orgs, users, workspaces, files and shared connection helpers. Export one `PostgresDAO` that combines the business methods.

**Tech Stack:** Python, psycopg, PostgreSQL, pytest.

## Constraints

- Preserve method signatures, SQL, transaction boundaries and return values.
- Keep workspace membership and organization grants in `workspaces.py`.
- Do not add schema migration, frontend tests, locks or source-string assertions.
- Run database tests serially against `rag_test` only.

## Tasks

1. Extract connection and result helpers into `api/dao/base.py`; move methods unchanged into the five business modules using Python AST method boundaries.
2. Export the composed `PostgresDAO` from `api/dao/__init__.py` and update imports to `kb_api.api.dao`. The Dockerfile copies this package together with `kb_api/api`.
3. Point the app rollback test's ID monkeypatch at `api.dao.apps`, where `create_app` now resolves the helper.
4. Verify preserved method signatures and SQL literals against the original AST during extraction, then run `kb_api/.venv/bin/pytest kb_api/tests -q` and `git diff --check`.
