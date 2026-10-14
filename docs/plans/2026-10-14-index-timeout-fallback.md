# Index Timeout Fallback Implementation Plan

**Goal:** Settle Python KB indexing tasks that remain `indexing` beyond their configured time budget.

**Architecture:** Preserve RabbitMQ delivery. Record task start in `files.indexing_started_at`, let the KB API periodically mark stale indexing rows `failed`, and fence callback writes by task credentials and expected status. Match KB3's 900-second timeout and one-minute sweep without porting Redis/Asynq.

**Tech Stack:** FastAPI lifespan, asyncio, psycopg/PostgreSQL, RabbitMQ, pytest, YAML.

## Global Constraints

- Index timeout is measured from task creation, including queue wait.
- Expired files become `failed` with error `处理异常`.
- A late callback must not restore an expired file to `indexed`.
- Existing `kb` code changes in the worktree belong to the previous user request and must be preserved.
- No 233 deployment or production data mutation is part of this plan.

---

### Task 1: Schema and task lifecycle

**Files:** `scripts/db.sql`, `scripts/test_db.sql`, `kb_api/tests/test_schema.py`, `kb_api/tests/test_file_index_timeout.py`, `kb_api/api/dao/files.py`.

**Interfaces:** `set_file_index_task(file_id, task_id, token_hash)` sets `indexing_started_at` when status is `indexing`; `apply_file_result` requires expected status and clears task credentials and timestamp; `expire_indexing_files(cutoff)` returns affected row count.

- [x] Write database tests asserting task start is stored, a stale row changes to `failed`, an on-time row stays `indexing`, and a late result returns false.
- [x] Run the focused lifecycle and schema tests and confirm they fail before implementation.
- [x] Add `indexing_started_at TIMESTAMPTZ`, idempotent `ALTER TABLE`, backfill of existing indexing rows from `updated_at`, and the partial indexing-time index to both SQL scripts. Add the column to the exact schema assertion.
- [x] Add guarded SQL operations to `FilesDAO`; keep `indexing_started_at` out of public file responses.
- [x] Run the focused pytest tests and confirm they pass.

### Task 2: Configured API sweep

**Files:** `kb_api/config/rag.yaml`, `kb_api/api/config.py`, `kb_api/api/main.py`, `kb_api/tests/test_index_timeout_sweep.py`.

**Interfaces:** `load_index_task_timeout()` returns a positive timeout in seconds from `indexer.task_timeout`; `run_index_timeout_sweep(dao, timeout_seconds, interval_seconds=60)` checks once immediately, then periodically until cancellation.

- [x] Write tests that a configured timeout creates the correct cutoff and that cancellation stops the sweep.
- [x] Run `kb_api/.venv/bin/pytest -q kb_api/tests/test_index_timeout_sweep.py` and confirm expected failures.
- [x] Add `task_timeout: 900` to YAML, validate it in config loading, and start/cancel the sweep in the production FastAPI lifespan.
- [x] Run the focused sweep tests and then the full `kb_api/tests` suite.

### Task 3: RabbitMQ stale-callback acknowledgement

**Files:** `kb_api/rag_indexer/rabbitmq.py`, `kb_api/rag_indexer/tests/unit/test_rabbitmq.py`.

- [x] Prove a 401 callback currently requeues its task.
- [x] Acknowledge 401 as terminal while retaining retry for other callback failures.
- [x] Run the RabbitMQ worker and telemetry unit tests.

### Task 4: Final verification

**Files:** `docs/api.md`.

- [x] Document timeout behavior without changing RabbitMQ transport instructions.
- [x] Run `kb_api/.venv/bin/pytest -q kb_api/tests` against `rag_test`.
- [x] Run `git diff --check` and inspect the final diff.

## Self-review

- Coverage includes start timestamp, stale transition, callback fence, schema migration, config, scheduler, and tests.
- Queue transport remains RabbitMQ; the KB3 Asynq split is intentionally excluded.
