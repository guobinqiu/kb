# KB Boundary Cleanup Implementation Plan

**Goal:** Remove unused responsibilities and duplicate wrappers without changing public APIs or deployment boundaries.

**Architecture:** Management HTTP code stays in `api/`; retrieval stays in `rag_retriever/`; indexing stays in `rag_indexer/`. Shared helpers remain inside their owning module rather than a new global package.

**Tech Stack:** Python, FastAPI, psycopg, HTTPX, pytest, Docker Compose.

## Constraints

- Preserve URLs, response bodies, YAML format, permissions, queue acknowledgement and result callback behavior.
- Preserve transaction semantics and existing unrelated changes.
- Use `rag_test` only for management database tests; run these tests serially.
- Do not add frontend or source-inspection guard tests.
- Do not rebuild, restart, commit or publish services.

## Management API

- Move `require_admin` from `api/auth.py` to `api/permissions.py`; update org and user route imports.
- Remove unused StorageClient and QueueClient protocols and the management RabbitMQ consumer.
- Keep RabbitMQ publishing persistent tasks and its existing lifecycle interface.
- Make the descendants SQL helper an explicit function in `api/dao/orgs.py`, used by org and user repositories.
- Remove unused `list_apps(include_disabled=...)` arguments.
- Verify org subtree listing through the user repository, existing permission tests, file callbacks and queue publishing tests.

## Retriever

- Remove document indexing, stale-chunk cleanup and unused indexing deadline code from query-side vector clients.
- Preserve collection creation/deletion and chunk pagination used by management APIs.
- Consolidate repeated retry and provider assembly code; preserve provider-specific protocols and response validation.
- Remove pure import forwarding where callers can directly reference the actual owner.
- Return transport-neutral retrieval errors and map them at the HTTP route.
- Verify retrieval modes, fallback, vector filters, pagination, tracing and inference protocols.

## Indexer

- Move presigning out of the HTTP adapter so MQ and HTTP call the same internal MinIO implementation.
- Remove obsolete search/debug schemas and unused parser/inference HTTP error handlers.
- Remove unused index-side reranking while preserving shared configuration parsing for embeddings.
- Consolidate upstream errors and direct request ID imports inside Indexer; preserve actual retry differences.
- Verify task processing, callbacks, ACK behavior, parser normalization and vector indexing with local unit tests.

## Integration

- Review every changed module and stale import; update affected documentation and tests.
- Run management, Retriever and Inference suites serially, then Indexer unit suites.
- Validate Compose configuration and `git diff --check`.
