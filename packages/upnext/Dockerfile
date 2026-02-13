# UpNext SDK + CLI
FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy workspace files
COPY pyproject.toml uv.lock ./
COPY packages/shared ./packages/shared
COPY packages/upnext ./packages/upnext
COPY packages/server/pyproject.toml packages/server/README.md ./packages/server/
COPY packages/server/src ./packages/server/src
COPY packages/server/alembic.ini ./packages/server/alembic.ini
COPY packages/server/alembic ./packages/server/alembic
COPY packages/server/static ./packages/server/static

# Install dependencies
RUN uv sync --frozen --no-dev --package upnext

# Set working directory
WORKDIR /app/packages/upnext

# Ensure Python output is not buffered
ENV PYTHONUNBUFFERED=1

# Default: show CLI help (no examples are bundled into the image)
CMD ["uv", "run", "--no-sync", "upnext", "--help"]
