# Indexer Independent Dependencies Implementation Plan

**Goal:** Keep Indexer dependencies independent while sharing the KB configuration.

**Architecture:** Indexer stays at `kb_api/rag_indexer`, with its own pyproject, lockfile and Dockerfile. Both entrypoints continue reading `kb_api/config/rag.yaml` through `KB_CONFIG_FILE`. Tests stay in their existing directories.

**Tech Stack:** Python 3.11, uv, pytest, Docker Compose.

## Global Constraints

- Do not change parsing, indexing, retrieval, MQ or authentication behavior.
- Keep the remote MinerU and TEI endpoints unchanged.
- Do not add frontend tests or move existing tests.

### Task 1: Dependency Boundaries

- Restore `kb_api/rag_indexer/pyproject.toml` with Indexer dependencies and its three test directories.
- Remove Indexer-only dependencies and testpaths from `kb_api/pyproject.toml`.
- Generate both lockfiles and synchronize both environments.

### Task 2: Build And Documentation

- Update Indexer's Dockerfile to install from its own pyproject and lockfile, preserving the shared config copy and existing entrypoint.
- Update README and architecture documentation to describe independent dependencies and shared configuration.

### Task 3: Verification

- Run KB API, Search and shared configuration tests with the KB environment.
- Run Indexer, Parser and Indexer Inference unit tests with the Indexer environment.
- Rebuild both containers and verify health, shared config, remote TEI and MQ consumption.
