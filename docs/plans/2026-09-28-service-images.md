# Service Images Implementation Plan

**Goal:** Build independent KB API and RAG Indexer images from one repository and lock file.

**Architecture:** Each image contains its own application code and dependency extras. Compose mounts only the shared configuration and Indexer models; application code comes from the image.

**Tech Stack:** Docker Compose, Python 3.11, uv.

## Global Constraints

- Preserve service names, ports, configuration paths and CPU/GPU selection.
- Keep one pyproject.toml and uv.lock.
- No source-inspection guard tests or frontend tests.
- Do not commit unrelated workspace changes.

## Tasks

1. Separate common, API and Indexer dependencies into dependency extras without changing version constraints; update the lock file.
2. Make kb_api/Dockerfile copy only API, Search and configuration. Add rag_indexer/Dockerfile for Indexer and request_context.py.
3. Update Compose build paths and replace full source mounts with a read-only configuration mount; retain the Indexer models mount.
4. Update deployment documentation with image boundaries and rebuild requirements.
5. Validate Compose, build both images, smoke-test them without source mounts, run backend tests, and recreate both local services.
