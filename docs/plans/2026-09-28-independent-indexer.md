# Independent Indexer Implementation Plan

**Goal:** Make rag_indexer and kb_api independent Python projects in one repository.

**Architecture:** Each project owns its dependencies, lock file, configuration, request context and container entry point. Communication remains RabbitMQ tasks and HTTP result callbacks.

**Tech Stack:** Python 3.11, uv, Docker Compose.

## Global Constraints

- Preserve task/result contracts, service names, ports and models directory.
- No compatibility imports, shared Python package, migrations or guard tests.
- Keep current dependency versions.

## Tasks

1. Move Indexer to the repository root and update Python imports and configuration paths.
2. Split pyproject.toml, uv.lock and YAML configuration; keep CPU/GPU extras only in Indexer.
3. Update Dockerfiles, Compose, model download commands and documentation.
4. Remove cross-project test imports and OTel guard fixtures; keep functional coverage.
5. Install and test each independent environment, build both images and recreate the two local services.
