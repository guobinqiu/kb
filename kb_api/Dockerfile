# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:python3.11-bookworm

ARG USE_CN_MIRROR=false
ARG UV_DEFAULT_INDEX_CN=https://pypi.tuna.tsinghua.edu.cn/simple
ARG UV_HTTP_TIMEOUT=120

ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV UV_HTTP_TIMEOUT=${UV_HTTP_TIMEOUT}

WORKDIR /app
RUN mkdir -p /app/kb_api
RUN --mount=type=bind,source=kb_api/pyproject.toml,target=/app/kb_api/pyproject.toml,readonly \
  --mount=type=bind,source=kb_api/uv.lock,target=/app/kb_api/uv.lock,readonly \
  if [ "$USE_CN_MIRROR" = "true" ]; then \
  cd /app/kb_api && UV_DEFAULT_INDEX="$UV_DEFAULT_INDEX_CN" uv sync --frozen --no-install-project --no-dev; \
  else \
  cd /app/kb_api && uv sync --frozen --no-install-project --no-dev; \
  fi

COPY kb_api/__init__.py /app/kb_api/
COPY kb_api/config /app/kb_api/config
COPY kb_api/api /app/kb_api/api
COPY kb_api/rag_retriever /app/kb_api/rag_retriever

CMD ["/app/.venv/bin/uvicorn", "kb_api.api.main:app", "--host", "0.0.0.0", "--port", "6100", "--workers", "1"]
