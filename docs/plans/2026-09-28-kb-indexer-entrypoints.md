# KB API And Indexer Implementation Plan

**Goal:** Put Indexer inside the KB API Python project with two independent entrypoints and one configuration.

**Architecture:** Move Indexer to `kb_api/rag_indexer`. Both processes read `kb_api/config/rag.yaml` using `KB_CONFIG_FILE`. Keep Indexer's request ID handling and existing indexing behavior unchanged.

**Tech Stack:** Python 3.11, FastAPI, uv, Docker Compose, pytest.

## Global Constraints

- No frontend changes or tests.
- No database migrations or data deletion.
- Keep separate `just kb up` and `just indexer up` commands.
- Preserve remote MinerU and TEI endpoints.

### Task 1: Configuration Contract

- Add `kb_api/tests/test_shared_rag_config.py` exercising both vector loaders, both inference loaders and the parser loader against the same `KB_CONFIG_FILE`.
- Run the test before moving Indexer; expect the new module import to fail.

### Task 2: Project And Entrypoints

- Move `rag_indexer` into `kb_api/rag_indexer`, update Python imports and filesystem roots.
- Merge parser, chunking and storage sections into `kb_api/config/rag.yaml`; remove the second configuration.
- Merge dependency declarations into `kb_api/pyproject.toml`, remove Indexer's separate project and lockfile, regenerate the KB lockfile.
- Keep separate Dockerfiles using the shared project dependencies and update Compose entrypoint/config mounts.
- Update active documentation and deployment scripts.

### Task 3: Verification

- Run the shared configuration test, Indexer unit tests, parser tests, both inference suites and KB API tests with the test database.
- Validate both Compose files; rebuild/recreate both local services.
- Check both health endpoints and call remote TEI from each process.
