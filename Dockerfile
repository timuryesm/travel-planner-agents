# ─────────────────────────────────────────────────────────────────────────────
# Travel Planner Agents — single-image build
# ─────────────────────────────────────────────────────────────────────────────
# One container serves both the API and the built frontend. The alternative —
# separate backend and nginx images — buys faster partial rebuilds and costs a
# second Dockerfile, an nginx config, live CORS in production, and two things
# to keep in sync. For a project whose README promises clone-and-run, one
# artifact on one port is the stronger story.
#
# Serving both from one origin also removes cross-origin entirely in
# production: the frontend calls /trips/... relative to itself, so
# ALLOWED_ORIGINS only matters for local development against the Vite dev
# server.
#
# Layer order is deliberate. Dependency manifests are copied and installed
# BEFORE application source, so editing a component re-runs only `npm run
# build` and editing Python re-runs nothing in the node stage.

# ── Stage 1: build the frontend ──────────────────────────────────────────────
FROM node:20-alpine AS frontend

WORKDIR /build

# package.json declares no `engines`, so Node is pinned here instead. Vite 5
# requires Node 18+; 20 is the current LTS.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# Empty means same-origin: client.js treats "" as "use relative paths" and
# only falls back to localhost:8000 when the variable is absent entirely.
ENV VITE_API_BASE_URL=""
RUN npm run build


# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.13-slim

# PYTHONUNBUFFERED so agent logs reach the platform's log viewer immediately
# rather than sitting in a buffer; PYTHONDONTWRITEBYTECODE to keep the image
# free of .pyc files that only matter across restarts a container never has.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# No system packages needed: fpdf2 and markdown are pure Python (which is why
# they were chosen over WeasyPrint), asyncpg ships wheels, and the DejaVu
# fonts are vendored in the repo rather than apt-installed.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# alembic.ini and alembic/ are required at runtime, not just at build: the
# FastAPI lifespan runs `command.upgrade(Config("alembic.ini"), "head")` on
# every startup, and that path is relative to WORKDIR.
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY src/ ./src/

# The built frontend. main.py mounts this directory if it exists, so a local
# checkout without a build still runs — the mount is skipped rather than
# crashing at startup.
COPY --from=frontend /build/dist ./static

# Run as a non-root user. The app writes nothing under /app; its only writes
# are the advisory and geocode caches, which live under the system temp dir.
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

EXPOSE 8000

# Railway, Render and Fly all inject $PORT and expect the process to bind it.
# The shell form is required for expansion; ${PORT:-8000} keeps `docker run`
# working locally with no PORT set.
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]