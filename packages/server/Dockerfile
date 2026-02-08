# Conduit Server - Multi-stage build

# Stage 1: Build frontend
FROM oven/bun:1 AS frontend-builder

WORKDIR /app/web

# Copy frontend package files
COPY packages/server/web/package.json packages/server/web/bun.lock* ./

# Install dependencies
RUN bun install --frozen-lockfile

# Copy frontend source
COPY packages/server/web ./

# Build frontend (outputs to ../static)
RUN bun run build && mv ../static /static

# Stage 2: Python server
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy workspace config and lock file
COPY pyproject.toml uv.lock ./

# Copy packages
COPY packages/shared ./packages/shared
COPY packages/server ./packages/server

# Copy built frontend
COPY --from=frontend-builder /static ./packages/server/static

# Install dependencies using workspace
RUN uv sync --frozen --no-dev --package conduit-server

# Set working directory to server package
WORKDIR /app/packages/server

# Expose port
EXPOSE 8080

# Start server
CMD ["uv", "run", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8080"]
