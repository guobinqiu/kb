# MQ-Only Indexer Implementation Plan

**Goal:** Run Indexer as a foreground RabbitMQ consumer without an HTTP server or a consumer thread.

**Architecture:** The entrypoint owns Parser, Inference and Vector clients. SIGTERM/SIGINT requests a graceful stop. Results go to the KB API callback before ACK.

**Tech Stack:** Python, Pika, HTTPX, Docker Compose, pytest.

## Tasks

1. Replace HTTP tests with process lifecycle and foreground-consumer tests; verify failure first.
2. Replace FastAPI startup with a Python entrypoint; close connections and clients on exit.
3. Remove HTTP routes, authentication, middleware and HTTP-only tests. Keep internal MinIO signing.
4. Update Docker entrypoint, process liveness check, Nginx, dependencies and documentation.
5. Run Indexer unit tests and KB API regression against rag_test; validate Compose and whitespace.

Preserve task payloads, callbacks, ACK/NACK and indexing behavior. Do not deploy or add source-inspection tests.
