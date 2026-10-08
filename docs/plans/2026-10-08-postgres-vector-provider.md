# PostgreSQL Vector Provider Implementation Plan

**Goal:** Add `postgres` as a third vector backend using `pgvector` for dense search and `pg_search` for optional BM25 search.

**Architecture:** Map each App collection to a PostgreSQL table in the default schema so every App can keep its own embedding dimension and indexes. The Indexer writes vectors and metadata through psycopg; RAG Search performs dense and BM25 queries through a separate read client while preserving the existing `VectorClient` contract and RRF pipeline.

**Tech Stack:** PostgreSQL 16, ParadeDB 0.25.10, pgvector, pg_search, psycopg 3, pytest.

## Global Constraints

- The provider name and configuration key are `postgres`, not `paradedb`.
- Exactly one of `qdrant`, `milvus`, cloud variants, or `postgres` is enabled.
- Qdrant and Milvus behavior remains unchanged.
- `bm25: false` disables PostgreSQL sparse search without disabling dense search.
- Extension prerequisites are declared in `scripts/db.sql` and `scripts/test_db.sql`; App vector tables are created and removed through the same collection lifecycle used by Qdrant and Milvus.

---

### Task 1: Configuration Contract

**Files:**
- Modify: `kb_api/config/rag.yaml`
- Modify: `kb_api/rag_indexer/common/config.py`
- Modify: `kb_api/rag_search/common/config.py`
- Test: `kb_api/rag_indexer/tests/unit/test_config.py`
- Test: `kb_api/rag_search/tests/test_config.py`

**Interfaces:**
- Consumes: one enabled `vector_db` entry.
- Produces: `provider="postgres"` with `database_url`, BM25 switch, operation timeouts, and retry settings.

- [ ] Write configuration tests that select `postgres` and reject multiple enabled backends.
- [ ] Run the tests and confirm failure because `postgres` is unsupported.
- [ ] Add the `postgres` provider configuration and parsers.
- [ ] Run the focused configuration tests.

### Task 2: PostgreSQL Schema and Indexer Client

**Files:**
- Modify: `scripts/db.sql`
- Modify: `scripts/test_db.sql`
- Create: `kb_api/rag_indexer/clients/vector/postgres.py`
- Modify: `kb_api/rag_indexer/app/main.py`
- Modify: `kb_api/rag_indexer/pyproject.toml`
- Modify: `kb_api/rag_indexer/uv.lock`
- Test: `kb_api/rag_indexer/tests/unit/test_postgres_vector.py`

**Interfaces:**
- Consumes: parsed chunks, App scope, dense embedding client, and PostgreSQL connection URL.
- Produces: chunk upsert/delete/count/list operations in `{app_id}_chunks` and App-scoped lifecycle methods.

- [ ] Write failing tests for chunk upsert parameters, stale-tail deletion, App deletion, and dimension validation.
- [ ] Run the tests and confirm the client is missing.
- [ ] Add `vector` and `pg_search`, the chunk table and indexes to both SQL scripts.
- [ ] Implement the Indexer PostgreSQL client using explicit transactions.
- [ ] Wire `provider="postgres"` into Indexer startup and lock dependencies.
- [ ] Run the focused Indexer tests.

### Task 3: PostgreSQL Search Client

**Files:**
- Create: `kb_api/rag_search/clients/vector/postgres.py`
- Modify: `kb_api/rag_search/service.py`
- Test: `kb_api/rag_search/tests/test_postgres_vector.py`

**Interfaces:**
- Consumes: query vectors, BM25 query text, App scope, and metadata filters.
- Produces: existing public search items with `_score`, content, chunk ID, and metadata.

- [ ] Write failing tests for dense SQL, BM25 SQL, metadata filtering, chunk pagination, and BM25 disablement.
- [ ] Run the tests and confirm the client is missing.
- [ ] Implement dense, sparse, chunk-list and lifecycle methods using psycopg.
- [ ] Wire `provider="postgres"` into `load_search_service()`.
- [ ] Run the focused Search tests.

### Task 4: Integration and Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`

**Interfaces:**
- Consumes: the complete PostgreSQL provider.
- Produces: documented local configuration and verified Compose deployment.

- [ ] Apply `scripts/test_db.sql` to `rag_test` and run PostgreSQL provider integration tests.
- [ ] Run existing Qdrant/Milvus and API regression tests.
- [ ] Rebuild KB API and Indexer images.
- [ ] Verify `git diff --check`, service health, dense search and BM25 search.
