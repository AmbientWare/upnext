# Example service Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy workspace files
COPY pyproject.toml uv.lock ./
COPY packages/shared/pyproject.toml packages/shared/README.md packages/shared/
COPY packages/shared/src packages/shared/src
COPY packages/upnext/pyproject.toml packages/upnext/README.md packages/upnext/
COPY packages/upnext/src packages/upnext/src
COPY packages/server/pyproject.toml packages/server/README.md packages/server/
COPY packages/server/src packages/server/src
COPY packages/server/alembic.ini packages/server/alembic.ini
COPY packages/server/alembic packages/server/alembic
COPY packages/server/static packages/server/static
COPY examples examples/

# Install upnext package (includes aiohttp for client)
RUN uv sync --frozen --no-dev --package upnext

# Default command - can be overridden
CMD ["uv", "run", "upnext", "run", "examples/service.py"]
