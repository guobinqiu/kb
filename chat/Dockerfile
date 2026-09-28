# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:python3.11-bookworm

ARG USE_CN_MIRROR=false
ARG UV_DEFAULT_INDEX_CN=https://pypi.tuna.tsinghua.edu.cn/simple
ARG UV_HTTP_TIMEOUT=120

ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV UV_HTTP_TIMEOUT=${UV_HTTP_TIMEOUT}

WORKDIR /app
RUN mkdir -p /app/chat
RUN --mount=type=bind,source=chat/pyproject.toml,target=/app/chat/pyproject.toml,readonly \
  --mount=type=bind,source=chat/uv.lock,target=/app/chat/uv.lock,readonly \
  if [ "$USE_CN_MIRROR" = "true" ]; then \
  cd /app/chat && UV_DEFAULT_INDEX="$UV_DEFAULT_INDEX_CN" uv sync --frozen --no-install-project; \
  else \
  cd /app/chat && uv sync --frozen --no-install-project; \
  fi

COPY chat/__init__.py /app/chat/__init__.py
COPY chat/pytest.ini /app/chat/pytest.ini

CMD ["/app/.venv/bin/uvicorn", "chat.src.main:app", "--host", "0.0.0.0", "--port", "6001", "--workers", "1"]
