# Conduit API Server
FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy workspace files
COPY pyproject.toml uv.lock ./
COPY packages/shared ./packages/shared
COPY packages/api ./packages/api

# Install dependencies
RUN uv sync --frozen --no-dev --package conduit-api

# Set working directory to api package
WORKDIR /app/packages/api

# Default: start server (migrations handled by separate container)
CMD ["uv", "run", "conduit-api"]
