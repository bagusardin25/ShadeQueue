# Single-origin image: Vite SPA + FastAPI + fixture seed.

# --- stage 1: frontend -------------------------------------------------------
FROM node:22-bookworm-slim AS web

WORKDIR /src
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
RUN npm ci --include=optional
COPY apps/web ./apps/web
RUN npm run build


# --- stage 2: python dependencies --------------------------------------------
FROM python:3.12-slim AS deps

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /src
COPY apps/api/pyproject.toml apps/api/uv.lock* ./
RUN uv sync --no-install-project --no-dev


# --- stage 3: runtime --------------------------------------------------------
FROM python:3.12-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 shadequeue

COPY --from=deps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production

WORKDIR /app

COPY apps/api/app ./apps/api/app
COPY apps/api/serve.py ./apps/api/serve.py
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY fixtures ./fixtures
COPY scripts ./scripts
COPY --from=web /src/apps/web/dist ./apps/web/dist

ENV PYTHONPATH=/app/apps/api

USER shadequeue
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/api/health" || exit 1

CMD ["sh", "-c", "alembic upgrade head && python scripts/load_fixtures.py && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --loop app.runtime:new_event_loop"]
