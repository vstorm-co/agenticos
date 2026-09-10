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

`cp .env.example .env.local`. Every variable is read on the server at runtime -
change one and restart the container. Nothing is inlined into the browser bundle
at build time, so one published image serves every deployment; the values the
_browser_ needs are read from the server's environment on each request and handed
down through `PublicConfigProvider` (`src/lib/public-config.ts`).

| Variable                                   | Default                 |                                                                                                                                                                                                                                                                                                                                                   |
| ------------------------------------------ | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BACKEND_URL`                              | `http://localhost:8000` | Where the route handlers proxy to. Same-origin proxying is what keeps auth cookies working. Server-side only; never reaches the browser                                                                                                                                                                                                           |
| `PUBLIC_API_URL`                           | `http://localhost:8000` | What the _browser_ calls directly - OAuth login, hosted-page uploads, the API docs link. Must be publicly reachable, not a container name                                                                                                                                                                                                         |
| `PUBLIC_WS_URL`                            | `ws://localhost:8000`   | The chat WebSocket, which the browser opens against the backend directly                                                                                                                                                                                                                                                                          |
| `PUBLIC_SITE_URL`                          | `http://localhost:3000` | This app's own public URL, for page metadata, `robots.txt` and the sitemap                                                                                                                                                                                                                                                                        |
| `CHAT_MAX_UPLOAD_SIZE_MB`                  | `10`                    | What the composer refuses before uploading. The same variable name the backend reads, so a compose file passes one value to both containers - the knowledge base's larger `MAX_UPLOAD_SIZE_MB` is a different surface and does not apply here                                                                                                     |
| `OAUTH_PROVIDERS`                          | `google`                | Comma-separated: `google`, `github`, `microsoft`. Empty turns the buttons off                                                                                                                                                                                                                                                                     |
| `OTEL_EXPORTER_OTLP_ENDPOINT` / `_HEADERS` | unset                   | Optional. Server-side traces to Logfire. **Unset, the spans are built and dropped** - `instrumentation.ts` registers the SDK on every boot, and off Vercel `@vercel/otel` has no exporter without these. Point them at the project the backend writes to and the two halves land together; `docker-compose-prod.frontend.yml` passes both through |

> Getting the public URLs wrong produces the most confusing failure in this
> stack: server-side rendering keeps working over the internal network while
> every call from the browser goes to whatever hostname the server was told.
> The page loads, and nothing in it does.

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

| Kind        | Where                           | Asserts                                                                                                               |
| ----------- | ------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Unit        | `src/**/*.test.ts(x)`           | Stores, hooks, pure functions                                                                                         |
| Integration | `src/**/*.integration.test.tsx` | Testing Library against a mocked API — that a permission actually hides a control, that a form submits what it claims |
| E2E         | `e2e/*.spec.ts`                 | Playwright against a running stack                                                                                    |

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

Vercel works too, since the app is an ordinary Next build. Set `BACKEND_URL` and
the `PUBLIC_*` variables above as runtime environment variables.
