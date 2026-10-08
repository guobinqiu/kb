# KB API Layout Implementation Plan

**Goal:** Separate application startup, HTTP/business code and external clients instead of keeping them in the package root.

**Architecture:** `api/` is the KB API application directory, containing startup, settings, error handling, telemetry, authorization and rate limits. Its `routes/`, `services/` and `dao/` directories contain HTTP routes, business services (including MinIO and RabbitMQ access) and database operations. Search and Indexer modules retain their current boundaries.

**Tech Stack:** Python, FastAPI, psycopg, pytest, Docker Compose.

## Constraints

- Keep URLs, authentication, response shapes, SQL and transaction behavior unchanged.
- Keep Indexer independent of application telemetry and clients.
- Preserve `kb_api/config/rag.yaml` and environment variable names.
- Do not add frontend tests, migration or compatibility wrapper modules.

## Tasks

1. Move startup, settings, telemetry, security and rate limits into `api/`; move MinIO and RabbitMQ adapters into `api/services/`. Keep request IDs and context in `api/middleware.py`.
2. Extract auth and health routes from the application factory; keep index-result processing and its route in `api/routes/files.py`. Route functions resolve the repository from `request.app.state`, keeping per-application injected dependencies.
3. Keep existing error handlers in `api/main.py`, retaining their behavior and logging.
4. Update imports, test monkeypatch locations, config-relative paths, Docker COPY rules, Compose entrypoint and current documentation.
5. Run backend, Search and Inference tests serially, validate Compose configuration and run `git diff --check`. Do not restart or publish services.
