# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Slipstream — multi-stage, multi-arch image (linux/amd64 + linux/arm64)
#
#   stage 1  frontend  → build the SPA with Node
#   stage 2  deps      → build Python wheels into a virtualenv
#   stage 3  runtime   → slim image with ffmpeg, the venv, and the built SPA
#
# The build context is the repository root (see .dockerignore).
# ---------------------------------------------------------------------------

ARG PYTHON_VERSION=3.12
ARG NODE_VERSION=20

# ---------------------------------------------------------------------------
# Stage 1 — frontend
# ---------------------------------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS frontend

WORKDIR /build

# Lockfile-only install first so dependency layers survive source edits.
# `npm ci` needs package-lock.json; the wildcard keeps the build working in a
# checkout that has not committed one yet, where npm falls back to install.
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY frontend/ ./

# `npm run build` runs `tsc -b` first, so a type error fails the image build
# rather than shipping a stale bundle.
RUN npm run build && test -f dist/index.html


# ---------------------------------------------------------------------------
# Stage 2 — Python dependencies
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS deps

# argon2-cffi and the SQLAlchemy C extensions need a compiler on arm64, where
# fewer manylinux wheels exist. Build tools stay in this stage only.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      libffi-dev \
 && rm -rf /var/lib/apt/lists/*

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt ./
RUN pip install --upgrade pip setuptools wheel \
 && pip install -r requirements.txt


# ---------------------------------------------------------------------------
# Stage 3 — runtime
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="Slipstream" \
      org.opencontainers.image.description="Self-hosted universal media downloader" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/OWNER/slipstream"

# ffmpeg is not optional in a container: without it no rung that needs muxing
# and no MP3 conversion can be served, and the app would honestly report those
# formats as unavailable. ca-certificates is needed for HTTPS extraction.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg \
      chromium \
      ca-certificates \
      curl \
      tini \
 && rm -rf /var/lib/apt/lists/*

# Unprivileged runtime user. The UID is fixed so a bind-mounted ./data keeps
# consistent ownership across rebuilds and hosts.
RUN groupadd --gid 10001 slipstream \
 && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin slipstream

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production \
    DATA_DIR=/app/data \
    FRONTEND_DIST=/app/frontend/dist \
    PORT=8000

ENV DOUYIN_BROWSER_EXECUTABLE=/usr/bin/chromium

COPY --from=deps /opt/venv /opt/venv

WORKDIR /app

COPY --chown=slipstream:slipstream backend/ /app/backend/
COPY --from=frontend --chown=slipstream:slipstream /build/dist /app/frontend/dist
COPY --chown=slipstream:slipstream docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod +x /usr/local/bin/entrypoint.sh \
 && mkdir -p /app/data/db /app/data/logs /app/data/temp \
 && chown -R slipstream:slipstream /app/data

# Named volume by default so the database survives `docker compose down`.
VOLUME ["/app/data"]

USER slipstream
WORKDIR /app/backend

EXPOSE 8000

# /api/health/ready reports whether the database is reachable, which is what
# an orchestrator should gate traffic on. /api/health alone can be "degraded"
# (e.g. ffmpeg missing) while still serving correctly.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/api/health/ready" >/dev/null || exit 1

# tini reaps the ffmpeg and yt-dlp subprocesses the worker spawns; without a
# real init, cancelled jobs would accumulate as zombies.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["serve"]
