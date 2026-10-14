# KB Domain Entry Implementation Plan

**Goal:** Serve KB WebUI, KB API, and Chat through configurable domain-based HTTP hosts like KB3.

**Architecture:** Add a dedicated Nginx Compose project on the existing `kb-net` network. Render an Nginx config template with three hostnames and forward requests to the existing `webui`, `kb_api`, and `chat` containers. Preserve the WebUI's same-origin `/api` proxy, RabbitMQ, Qdrant, and the current port-5175 access path during transition.

**Tech Stack:** Docker Compose v2, nginx:1.27-alpine, Nginx envsubst templates, Just, Node test runner.

## Global Constraints

- Hostnames must be configurable through `deploy/.env`; the local examples are `web.kb.test`, `api.kb.test`, `chat.kb.test` from the existing local `/etc/hosts`.
- Bind HTTP port 80 only; port 443 on 233 belongs to another service.
- Do not change database, vector backend, Chat API paths, or WebUI authentication behavior.
- Preserve the remote `kb_api/config/rag.yaml` Qdrant customization.

---

### Task 1: Domain-aware entry service

**Files:** `webui/tests/domain-routing.test.mjs`, `deploy/nginx.yaml`, `deploy/nginx/default.conf.template`, `deploy/env.example`, `justfile`.

**Interfaces:** `KB_WEB_DOMAIN`, `KB_API_DOMAIN`, `KB_CHAT_DOMAIN`, and `KB_HTTP_PORT` feed the Nginx service; `just nginx up/down` manages it independently.

- [x] Write a Node test that requires an Nginx Compose service, three distinct host mappings, and the Just entry points.
- [x] Run `node --test webui/tests/domain-routing.test.mjs`; confirm it fails because the entry service is missing.
- [x] Add the Nginx template and Compose service with `kb-net` upstreams and `KB_HTTP_PORT` defaulting to 80.
- [x] Add the four variables to `deploy/env.example` and the Nginx up/down commands to `justfile`.
- [x] Run the Node test and `docker compose --env-file deploy/env.example -p kb-nginx -f deploy/nginx.yaml config -q`.

### Task 2: Deployment documentation and runtime verification

**Files:** `README.md`, `docs/install-233.md`.

**Interfaces:** The documented HTTP entry is `http://<KB_WEB_DOMAIN>`; clients may call `http://<KB_API_DOMAIN>/api/v1/...` and `http://<KB_CHAT_DOMAIN>/api/v1/llm/...`.

- [x] Document `just nginx up`, DNS/hosts setup, the three route roles, and the unchanged fallback port 5175.
- [x] Run the frontend Node tests and build, Compose config validation, and `git diff --check`.
- [ ] On a later user-requested deployment, verify 233 still has port 80 free and preserve its Qdrant config.
- [ ] On that deployment, configure 233's `/etc/hosts` without changing the local machine's hosts, then verify all three routes with explicit Host headers and check API/Indexer/WebUI health.

## Self-review

- One Nginx process selects backends by Host and keeps the existing internal APIs unchanged.
- HTTP 80 does not compete with the unrelated 443 service.
- A missing public DNS record can be worked around with each client's hosts file; 233's hosts file does not control the local browser's DNS resolution.
