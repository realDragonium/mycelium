# syntax=docker/dockerfile:1.7
# Mycelium MCP server image. Build context = repo root:
#   docker build -f docker/Dockerfile -t mycelium-server .
ARG PYTHON_VERSION=3.13

# --- builder: resolve deps + install the project + spaCy model --------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/app/.venv \
    UV_PROJECT_ENVIRONMENT=/app/.venv

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer first (cached unless lockfile changes).
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Project source, then install the project itself.
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# spaCy model the app loads at runtime (phrasing.py -> en_core_web_sm).
# Installed as a wheel into the venv so it travels with the copied .venv.
ARG SPACY_MODEL_VERSION=3.8.0
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install \
      "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-${SPACY_MODEL_VERSION}/en_core_web_sm-${SPACY_MODEL_VERSION}-py3-none-any.whl"

# --- runtime ----------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

# curl: ALB/container health check. sqlite3: WAL pragma in entrypoint.
# awscli + zstd: derived-artifact snapshot push/pull. Litestream: WAL -> S3.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl sqlite3 zstd awscli \
    && rm -rf /var/lib/apt/lists/*

ARG LITESTREAM_VERSION=0.3.13
RUN curl -fsSL \
      "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-amd64.deb" \
      -o /tmp/litestream.deb \
    && dpkg -i /tmp/litestream.deb \
    && rm /tmp/litestream.deb

WORKDIR /app
COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:${PATH}" \
    VIRTUAL_ENV=/app/.venv \
    MYCELIUM_DATA_DIR=/data \
    MYCELIUM_HTTP_HOST=0.0.0.0 \
    MYCELIUM_HTTP_PORT=8765 \
    MALLOC_ARENA_MAX=2

COPY docker/litestream.yml /etc/litestream.yml
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && mkdir -p /data

EXPOSE 8765
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
