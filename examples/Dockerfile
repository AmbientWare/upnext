# Example service Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy workspace files
COPY pyproject.toml uv.lock ./
COPY packages/shared/pyproject.toml packages/shared/README.md packages/shared/
COPY packages/shared/src packages/shared/src
COPY packages/conduit/pyproject.toml packages/conduit/README.md packages/conduit/
COPY packages/conduit/src packages/conduit/src
COPY packages/server/pyproject.toml packages/server/README.md packages/server/
COPY packages/server/src packages/server/src
COPY packages/server/alembic.ini packages/server/alembic.ini
COPY packages/server/alembic packages/server/alembic
COPY packages/server/static packages/server/static
COPY examples examples/

# Install conduit package (includes aiohttp for client)
RUN uv sync --frozen --no-dev --package conduit-py

# Default command - can be overridden
CMD ["uv", "run", "conduit", "run", "examples/service.py"]
