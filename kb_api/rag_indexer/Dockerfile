# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:python3.11-bookworm

ARG USE_CN_MIRROR=false
ARG UV_DEFAULT_INDEX_CN=https://pypi.tuna.tsinghua.edu.cn/simple
ARG UV_HTTP_TIMEOUT=120

ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV UV_HTTP_TIMEOUT=${UV_HTTP_TIMEOUT}

WORKDIR /app
RUN mkdir -p /app/kb_api/rag_indexer
RUN --mount=type=bind,source=kb_api/rag_indexer/pyproject.toml,target=/app/kb_api/rag_indexer/pyproject.toml,readonly \
  --mount=type=bind,source=kb_api/rag_indexer/uv.lock,target=/app/kb_api/rag_indexer/uv.lock,readonly \
  if [ "$USE_CN_MIRROR" = "true" ]; then \
  cd /app/kb_api/rag_indexer && UV_DEFAULT_INDEX="$UV_DEFAULT_INDEX_CN" uv sync --frozen --no-install-project --no-dev; \
  else \
  cd /app/kb_api/rag_indexer && uv sync --frozen --no-install-project --no-dev; \
  fi

COPY kb_api/__init__.py /app/kb_api/
COPY kb_api/config /app/kb_api/config
COPY kb_api/rag_indexer /app/kb_api/rag_indexer

CMD ["/app/.venv/bin/python", "-m", "kb_api.rag_indexer.app.main"]
