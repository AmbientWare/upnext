# Conduit Web Dashboard
FROM oven/bun:1 AS builder

WORKDIR /app

# Copy package files
COPY packages/web/package.json packages/web/bun.lock ./

# Install dependencies
RUN bun install --frozen-lockfile

# Copy source
COPY packages/web/ ./

# Build the app
RUN bun run build

# Production stage - use Bun since build output is Bun-specific
FROM oven/bun:1-alpine

WORKDIR /app

# Copy built output
COPY --from=builder /app/.output ./.output

# Expose port
EXPOSE 3000

# Start the server with Bun
CMD ["bun", "run", ".output/server/index.mjs"]
