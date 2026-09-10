FROM oven/bun:1 AS base

# Install dependencies only when needed
FROM base AS deps
WORKDIR /app

# Copy package files (bun.lock is the current text lockfile; bun.lockb is the
# legacy binary one — match both so --frozen-lockfile has a lockfile to use).
COPY package.json bun.lock* ./

# Install dependencies
RUN bun install --frozen-lockfile

# Rebuild the source code only when needed
FROM base AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# No build arguments: the public URLs and limits the browser needs are runtime
# environment, read on every request, so one image serves every deployment
# (see src/lib/public-config.ts).

# Build the application
ENV NEXT_TELEMETRY_DISABLED=1
RUN bun run build

# Production image
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN useradd --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:bun /app/public ./public
COPY --from=builder --chown=nextjs:bun /app/.next/standalone ./
COPY --from=builder --chown=nextjs:bun /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["bun", "server.js"]
