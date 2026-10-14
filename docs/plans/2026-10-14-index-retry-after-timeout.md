# Index Retry After Timeout Implementation Plan

**Goal:** Let a user retry a timed-out file's indexing without uploading the object again, with the same interaction as KB3.

**Architecture:** Keep the existing `POST /workspaces/{workspace_id}/files/{file_id}/index` endpoint and RabbitMQ queue. Add the KB3 retry action to the KB file list, and verify that a timed-out task cannot complete a subsequent retry via its stale callback credentials.

**Tech Stack:** Vue 3, Element Plus, Axios, FastAPI, PostgreSQL, pytest, Node test runner.

## Global Constraints

- Match KB3's retry button placement, icon, enablement, copy, and toast behavior.
- Retry reuses `s3_url`; the existing replace action remains the path for a new upload.
- Keep RabbitMQ; do not introduce Redis or Asynq.
- Preserve the unrelated local worktree changes and the remote 233 Qdrant config.

---

### Task 1: Retry UI

**Files:** `webui/tests/file-retry.test.mjs`, `webui/src/views/FilesView.vue`, `webui/src/utils/kbApi.js`, `webui/src/i18n/locales/zh.json`, `webui/src/i18n/locales/en.json`.

**Interfaces:** `retryFile(workspaceId, file)` calls the existing index endpoint with `file.s3_url`, `file.filename`, and `file.mime_type`; `retryIndex(file)` invokes it for manageable failed rows.

- [x] Write a test that asserts the retry action, helper payload, and translation keys exist.
- [x] Run `node --test webui/tests/file-retry.test.mjs`; confirm the missing retry action fails the test.
- [x] Add the same retry control and behavior as KB3, preserving existing file-list layout and replace flow.
- [x] Run `node --test webui/tests/file-retry.test.mjs` and `npm run build` in `webui`.

### Task 2: Timeout-to-retry lifecycle

**Files:** `kb_api/tests/test_file_index_timeout.py`.

**Interfaces:** `expire_indexing_files(cutoff)` marks the old task failed; the existing index route enqueues a fresh task; `POST /api/v1/index-results` rejects old credentials and accepts new ones.

- [x] Add a PostgreSQL-backed test that expires a task and retries the same stored object.
- [x] Assert the retry retains the file ID, switches to `indexing`, publishes a new task ID, and clears the timeout error.
- [x] Assert the old callback receives 401 while the new callback completes with 204.
- [x] Run the focused pytest test and the full API test suite.

### Task 3: Release verification

**Files:** No additional source files.

- [x] Run `git diff --check`, Node UI tests, API tests, and RabbitMQ worker tests.
- [x] Review the resulting diff for unrelated formatting changes.
- [ ] Deploy to 233 only after tests pass and verify Qdrant configuration remains unchanged.

## Self-review

- Retry and replace are distinct paths; both are visible and protected by existing permissions.
- RabbitMQ delivery and existing timeout-sweep logic remain unchanged.
- The integration test covers timeout, retry, stale callback, and successful current callback.
