# Top-Level Imports Implementation Plan

**Goal:** Move imports to module scope wherever doing so preserves existing behavior.

**Architecture:** Keep API, Retriever, Indexer and Chat independent. Preserve local imports only where optional dependencies, circular imports or test fixture ordering require them.

**Tech Stack:** Python, pytest, FastAPI.

## Tasks

1. Review nested imports in all project Python files, including tests.
2. Move safe imports to existing module import sections without moving resource initialization or changing business behavior.
3. Keep necessary conditional imports and document their concrete reasons in the completion report.
4. Run existing API, Retriever, Indexer and Chat tests; use only rag_test for database tests.
5. Check the final import inventory and diff whitespace. Do not build, restart or publish services.
