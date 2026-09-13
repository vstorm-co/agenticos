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

# Every package's own licence file, kept under the package's path. The standalone
# output traces JavaScript and `package.json` only, so without this the runner
# would ship MIT and LGPL code with none of the notices those licences require
# (docs/licenses.md). The index of what is here is THIRD_PARTY_NOTICES.md in the
# repository, which this build context does not see.
RUN find node_modules -type f \( -iname 'LICENSE*' -o -iname 'LICENCE*' -o -iname 'COPYING*' \) \
    -exec sh -c 'mkdir -p "/app/licenses/$(dirname "$1")" && cp "$1" "/app/licenses/$1"' _ {} \;

# Production image
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN useradd --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:bun /app/public ./public
COPY --from=builder --chown=nextjs:bun /app/.next/standalone ./
COPY --from=builder --chown=nextjs:bun /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:bun /app/licenses ./licenses

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["bun", "server.js"]
