# Haqwa: one container for Cloud Run. FastAPI serves the API and the built React SPA.

# --- Stage 1: build the frontend -------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY web/frontend/package.json web/frontend/package-lock.json ./
RUN npm ci
COPY web/frontend/ ./
# The UI uses mock data unless this is exactly "false" at build time.
ENV VITE_USE_MOCK=false
RUN npm run build

# --- Stage 2: Python runtime -----------------------------------------------
FROM python:3.12.14-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    HAQWA_CACHE_DIR=/tmp/haqwa_cache

WORKDIR /app

# Dependencies first so code changes do not reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

COPY web/__init__.py ./web/__init__.py
COPY web/api ./web/api
COPY --from=frontend /frontend/dist ./web/frontend/dist

RUN useradd --create-home --uid 1000 app
USER app

# Cloud Run sets PORT (8080 by default).
CMD ["sh", "-c", "exec uvicorn web.api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
