# syntax=docker/dockerfile:1
# Stage 1: build the React SPA (Debian-based Node: Alpine's musl stack is too small for Rollup's parser)
FROM node:20-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: FastAPI serves the API and the built SPA from one URL
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONUTF8=1 \
    APP_TZ=Asia/Kolkata LOG_JSON=1 PORT=8000
RUN apt-get update && apt-get install -y --no-install-recommends curl tzdata \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 1000 corvo
WORKDIR /srv
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/procure_engine backend/procure_engine
COPY backend/app backend/app
COPY backend/alembic backend/alembic
COPY backend/alembic.ini backend/alembic.ini
RUN pip install -e ./backend
COPY policies policies
COPY --from=ui /ui/dist frontend/dist
RUN mkdir -p backend/var && chown -R corvo:corvo /srv
USER corvo
WORKDIR /srv/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD curl -fsS "http://localhost:${PORT}/healthz" || exit 1
# Migrations and the idempotent seed run on startup (app lifespan). One worker keeps in-process caches coherent.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
