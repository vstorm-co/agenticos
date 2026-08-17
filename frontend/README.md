# AgenticOS — frontend

Next.js 15 (App Router) · React 19 · TypeScript strict · Tailwind v4 · `next-intl` ·
TanStack Query · Zustand. The console: agent builder, chat, knowledge bases,
skills, vault, MCP connections, runs and organization settings.

Conventions live in [`.claude/rules/frontend.md`](../.claude/rules/frontend.md);
the working guide is the `frontend-feature` skill. This file is how to run it.

## Run it

```bash
bun install
bun dev            # http://localhost:3000
```

The backend has to be up at `http://localhost:8000` — `make dev` from the
repository root. Without it every page renders its **empty state rather than an
error**, so "no skills yet" and "the request 502'd" look identical; check the
network tab before the component.

In Docker instead: `make dev-frontend` (see the compose files at the root).

## Environment

`cp .env.example .env.local`. Two kinds of variable, and the difference matters
more here than the values do.

**Server-side.** Read at runtime by route handlers and server components. Change
one and restart.

| Variable | |
|---|---|
| `BACKEND_URL` | Where the route handlers proxy to. Same-origin proxying is what keeps auth cookies working |
| `OTEL_EXPORTER_OTLP_ENDPOINT` / `_HEADERS` | Optional. Server-side traces to Logfire. **Unset, the spans are built and dropped** — `instrumentation.ts` registers the SDK on every boot, and off Vercel `@vercel/otel` has no exporter without these. Point them at the project the backend writes to and the two halves land together; `docker-compose-prod.frontend.yml` passes both through |

**`NEXT_PUBLIC_*` — build arguments, not runtime configuration.** Next inlines
these into the browser bundle at build time. Changing one means **rebuilding the
image**, not restarting the container.

| Variable | |
|---|---|
| `NEXT_PUBLIC_API_URL` | What the *browser* calls. Must be publicly reachable, not a container name |
| `NEXT_PUBLIC_WS_URL` | The chat WebSocket, which the browser opens against the backend directly |
| `NEXT_PUBLIC_SITE_URL` | This app's own public URL, for OAuth redirects and metadata |
| `NEXT_PUBLIC_MAX_UPLOAD_SIZE_MB` | Client-side upload limit. Keep it at or below the backend's |
| `NEXT_PUBLIC_OAUTH_PROVIDERS` | Comma-separated. `google` is the one wired up |
| `NEXT_PUBLIC_RAG_ENABLED` | Show the knowledge-base UI |

> Getting the public URLs wrong produces the most confusing failure in this
> stack: server-side rendering keeps working over the internal network while
> every call from the browser goes to whatever hostname was baked in. The page
> loads, and nothing in it does.

The deployed compose files (`docker-compose-dev.frontend.yml`,
`docker-compose-prod.frontend.yml`) therefore **require** `PUBLIC_API_URL`,
`PUBLIC_WS_URL` and `PUBLIC_SITE_URL` at build time and refuse to start without
them.

## Scripts

```bash
bun dev                  # dev server, hot reload
bun run build            # production build — also type-checks the route tree
bun run start            # serve the production build
bun run analyze          # bundle analysis

bun run lint             # eslint . --max-warnings 0
bun run lint:fix
bun run format           # prettier --write
bun run format:check     # what CI runs
bun run type-check       # tsc --noEmit

bun run test             # vitest, watch
bun run test:run         # vitest once
bun run test:coverage    # with the coverage gate — what CI runs
bun run test:ui

bun run test:e2e         # playwright
bun run test:e2e:ui      # pick and watch specs
bun run test:e2e:headed  # see the browser
bun run test:e2e:debug
bun run test:e2e:report

bun run gen:mcp-logos    # regenerate src/lib/mcp-logos.generated.ts
```

Before pushing: `bun run type-check && bun run lint && bun run test:run`. From
the root, `make check` runs the whole thing including the backend.

## Tests

| Kind | Where | Asserts |
|---|---|---|
| Unit | `src/**/*.test.ts(x)` | Stores, hooks, pure functions |
| Integration | `src/**/*.integration.test.tsx` | Testing Library against a mocked API — that a permission actually hides a control, that a form submits what it claims |
| E2E | `e2e/*.spec.ts` | Playwright against a running stack |

`bun run test:coverage` runs the first two; vitest's `include` covers both
patterns. E2E is separate and needs a migrated, seeded backend — see the
`e2e-tests` skill, and note that an E2E spec **must assert on seeded data**, for
the empty-state reason above.

## Layout

```
src/
├── app/
│   ├── [locale]/(dashboard)/…   the console — agents, chat, kb, skills, vault,
│   │                            mcp-servers, runs, orgs, settings, admin
│   ├── [locale]/(auth)/, auth/, onboarding/, legal/, shared/
│   └── api/…                    route handlers proxying to the backend
├── components/<domain>/         UI by domain; primitives in ui/, empty and
│                                error states in states/
├── hooks/                       one per resource — use-agents, use-permissions…
├── lib/                         typed API clients on api-client.ts /
│                                server-api.ts, plus query-keys.ts
├── stores/                      Zustand, one per concern
├── types/
├── i18n.ts
└── middleware.ts                locale routing + auth guards
```

Routes are locale-prefixed. There is no `(marketing)` route group and no
`components/marketing`.

## Internationalization

Every user-facing string goes through `next-intl` — never hardcode copy. Add a
locale by extending `i18n.ts` and providing its message catalog.

## Deploying

Normally as part of the stack, with one compose file per environment — see
[Install](../docs/install.md#environments) and [Deploying](../docs/deploy.md).

Vercel works too, since the app is an ordinary Next build. Set `BACKEND_URL` plus
every `NEXT_PUBLIC_*` above as **build-time** environment variables; setting them
only at runtime leaves the browser bundle pointing at whatever was there when the
build ran.
