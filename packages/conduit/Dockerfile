# Conduit SDK + CLI
FROM python:3.13-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy workspace files
COPY pyproject.toml uv.lock ./
COPY packages/shared ./packages/shared
COPY packages/conduit ./packages/conduit

# Install dependencies
RUN uv sync --frozen --no-dev --package conduit

# Set working directory
WORKDIR /app/packages/conduit

# Ensure Python output is not buffered
ENV PYTHONUNBUFFERED=1

# Default: run the example e-commerce service
CMD ["uv", "run", "conduit", "run", "examples/service.py"]
