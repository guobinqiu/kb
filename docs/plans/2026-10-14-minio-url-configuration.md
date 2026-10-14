# MinIO URL Configuration Implementation Plan

**Goal:** Replace split MinIO endpoint/TLS settings with HTTP(S) URLs for KB API and Indexer, then deploy the verified change to 233.

**Architecture:** The API accepts one internal `KB_MINIO_URL` and one browser-facing `KB_MINIO_PUBLIC_URL`; URL parsing supplies the MinIO host and TLS flag. The Indexer reads `storage.url` from the shared YAML. The MinIO container is named `kb_minio` so the internal hostname resolves without a separate network alias; its data mount is unchanged.

**Tech Stack:** Python 3.11, FastAPI, MinIO Python SDK, pytest, Docker Compose.

## Global Constraints

- Local internal URL: `http://kb_minio:9000`.
- Local public URL: `http://localhost:9000`.
- 233 internal URL: `http://kb_minio:9000`.
- 233 public URL: `http://19.16.1.233:9000`, reachable by the user's browser.
- Remove `KB_MINIO_ENDPOINT`, `KB_MINIO_SECURE`, and YAML `storage.endpoint_url`.
- HTTP/HTTPS is derived from URL schemes, with no separate secure flag.
- Preserve unrelated formatting and logic.

---

### Task 1: API URL settings and storage client

**Files:**
- Modify: `kb_api/tests/test_storage.py`
- Modify: `kb_api/tests/test_auth.py`
- Modify: `kb_api/api/config.py`
- Modify: `kb_api/api/services/minio.py`
- Modify: `kb_api/api/main.py`

**Interfaces:**
- `Settings.minio_url: str` reads `KB_MINIO_URL`.
- `MinioStorage(url, access_key, secret_key, bucket, public_url=...)` accepts HTTP(S) origins and derives `secure` from the scheme.

- [ ] Add tests asserting HTTP internal storage is non-TLS, HTTPS internal storage is TLS, HTTPS public presigning uses TLS, and malformed URLs fail validation.
- [ ] Run `kb_api/.venv/bin/python -m pytest kb_api/tests/test_storage.py kb_api/tests/test_auth.py -q` and confirm the new tests fail for missing URL behavior.
- [ ] Replace the old fields and constructor arguments; validate URL origin, scheme, host, and path before creating the SDK client.
- [ ] Run the same tests and confirm they pass.

### Task 2: Indexer YAML URL and MinIO client

**Files:**
- Modify: `kb_api/rag_indexer/tests/unit/test_config_loader.py`
- Modify: `kb_api/rag_indexer/tests/unit/test_minio.py`
- Modify: `kb_api/rag_indexer/common/config.py`
- Modify: `kb_api/rag_indexer/clients/minio.py`
- Modify: `kb_api/config/rag.yaml`

**Interfaces:**
- `StorageConfig.url: str | None` reads `storage.url`.
- `minio_client(config)` parses the URL scheme and host to construct `Minio(..., secure=...)`.

- [ ] Add tests for `storage.url` parsing and both HTTP/HTTPS client settings.
- [ ] Run `kb_api/.venv/bin/python -m pytest kb_api/rag_indexer/tests/unit/test_config_loader.py kb_api/rag_indexer/tests/unit/test_minio.py -q` and confirm the new tests fail.
- [ ] Rename the config field and update its consumer and YAML key.
- [ ] Run the same tests and confirm they pass.

### Task 3: Deployment config, documentation, and local validation

**Files:**
- Modify: `deploy/infra.yaml`
- Modify: `deploy/env.example`
- Modify: `deploy/.env` (ignored local configuration)
- Modify: `docs/install-233.md`
- Modify: `README.md`

**Interfaces:**
- Compose service `minio` uses container name `kb_minio` on `kb-net` with no explicit alias.

- [ ] Replace old env variables and YAML references without changing credentials.
- [ ] Validate `docker compose --env-file deploy/.env -p kb-infra -f deploy/infra.yaml config -q` and the other KB Compose files.
- [ ] Run API, Indexer, and WebUI test suites plus the WebUI production build.
- [ ] Check `git diff --check`, commit, and push the source changes.

### Task 4: 233 rollout and runtime checks

**Files:**
- Modify: remote `/home/imsdom/workspace/kb/deploy/.env` (ignored runtime configuration)

**Interfaces:**
- Remote API and Indexer load the new internal URL; browser upload URLs remain reachable at `19.16.1.233:9000`.

- [ ] Transfer the commit to 233 and fast-forward the clean checkout while preserving ignored data directories.
- [ ] Replace remote `KB_MINIO_ENDPOINT`/`KB_MINIO_SECURE` with `KB_MINIO_URL` while keeping the public URL at the remote IP.
- [ ] Recreate MinIO with the new container name, rebuild/recreate API and Indexer, and leave PostgreSQL and its data volume intact.
- [ ] Confirm container DNS resolves `kb_minio`, HTTPS detection tests pass, API/Indexer health is green, and a presigned upload URL uses the remote public endpoint.
