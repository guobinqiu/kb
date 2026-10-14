# Local KB Cutover Implementation Plan

**Goal:** Replace the running local KB3 containers with KB containers named consistently with a `kb_` prefix and use PostgreSQL for KB vector storage.

**Architecture:** Keep Compose service keys and internal DNS aliases stable, changing only `container_name` values and commands that address those names. Verify KB's `vector_db.postgres.enable: true` and `vector_db.qdrant.enable: false` before startup. Stop and remove only KB3 Compose containers to free colliding project/container names; its bind-mounted PostgreSQL, Redis, and MinIO data remain in `kb3/`.

**Tech Stack:** Docker Compose v2, ParadeDB/PostgreSQL, RabbitMQ, Nginx, Node test runner, pytest.

## Global Constraints

- The cutover targets the local Docker context `desktop-linux`, not 233.
- Do not delete KB3's bind-mounted data directories or change KB3 source files.
- Do not migrate KB3 database or object data unless the user explicitly requests it.
- Keep KB's RabbitMQ transport; do not start Qdrant or Milvus profiles.
- Preserve all unrelated local worktree changes.

---

### Task 1: Uniform container names

**Files:** `webui/tests/container-names.test.mjs`, `deploy/infra.yaml`, `deploy/kb.yaml`, `deploy/indexer.yaml`, `deploy/chat.yaml`, `deploy/webui.yaml`, `deploy/tei.yaml`, `deploy/mineru.yaml`, `deploy/nginx.yaml`.

**Interfaces:** Every `container_name` in the eight Compose files begins `kb_`; Compose service keys such as `postgres`, `minio`, `rabbitmq`, `webui`, and `chat` remain unchanged for internal DNS.

- [ ] Add a test reading all eight Compose files and asserting every service has a `kb_` container name.
- [ ] Run `node --test webui/tests/container-names.test.mjs` and confirm it fails on the existing unprefixed names.
- [ ] Rename the containers while leaving service keys, network aliases, ports, volumes, and environment unchanged.
- [ ] Run the test and validate all eight Compose files with `docker compose --env-file deploy/env.example -p kb-infra -f deploy/infra.yaml config -q` and the equivalent command for the other seven files.

### Task 2: Name references and PostgreSQL startup

**Files:** `README.md`, `docs/install-233.md`, `scripts/deploy_tei_services.txt`, `scripts/deploy_mineru_services.txt`.

**Interfaces:** Commands use `kb_postgres`, `kb_api`, `kb_indexer`, `kb_rabbitmq`, and other new container names. KB's `kb_api/config/rag.yaml` retains PostgreSQL enabled and Qdrant disabled.

- [ ] Update direct `docker exec`, `docker logs`, and container-name documentation without changing internal service URLs.
- [ ] Confirm `vector_db.postgres.enable: true` and `vector_db.qdrant.enable: false` in the current config.
- [ ] Run the Node tests, Compose validation, `git diff --check`, and relevant backend tests.

### Task 3: Local service cutover

**Files:** No source changes.

- [ ] Read-only verify the local Docker context, KB3 Compose labels, data mounts, and KB/KB3 port conflicts.
- [ ] Build KB images before interrupting KB3 where possible.
- [ ] Use KB3's separate Compose projects to stop/remove its nine containers without `-v`; retain `kb3/pg_data`, `kb3/redis_data`, and `kb3/minio_data`.
- [ ] Start KB infra, run `scripts/db.sql` against `kb_postgres`, then start KB API, Indexer, Chat, WebUI, and domain Nginx.
- [ ] Verify PostgreSQL vector backend, health endpoints, RabbitMQ consumer, host-based routes, and stopped KB3 state.

## Self-review

- The naming test covers all eight KB Compose files, including optional TEI and MinerU services.
- The cutover preserves KB3 data because each stateful service uses a bind mount.
- No Qdrant profile is started; KB uses its own PostgreSQL data directory.
