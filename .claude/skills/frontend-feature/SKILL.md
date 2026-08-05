---
name: frontend-feature
description: Build or change a page, view or data-driven feature in the Next.js frontend — a route under the dashboard, wiring UI to a backend endpoint, a Zustand store, a permission that must hide a control, or localized copy. Use for any work in frontend/src, including "the page renders but shows an empty state" and "this button should not be visible to a Viewer".
---

# Frontend — Next.js 15, React 19

`.claude/rules/frontend.md` has the conventions. `docs/architecture.md` has the
request path. This is the working layout and the traps.

## Layout

| Path | |
|---|---|
| `src/app/[locale]/(dashboard)/…` | The product: `agents`, `chat`, `rag` (knowledge bases + search; `kb` only redirects there), `skills`, `vault`, `mcp-servers`, `runs`, `orgs`, `settings`, `admin`, `invitations`, `profile` |
| `src/app/[locale]/(auth)/…`, `auth/`, `onboarding/`, `legal/`, `shared/` | Everything else |
| `src/app/api/…` | Route handlers that proxy to the backend (same-origin auth cookies) |
| `src/lib/` | Typed API clients on `api-client.ts`, `server-api.ts`, `query-keys.ts` |
| `src/hooks/` | One per resource: `use-agents`, `use-skills`, `use-permissions`, … |
| `src/stores/` | Zustand, one per concern, re-exported from `index.ts` |
| `src/components/<domain>/` | UI by domain; primitives in `components/ui/`, empty/error in `components/states/` |

Routes are **locale-prefixed**. There is no `(marketing)` group.

## Steps

1. **Page** — `src/app/[locale]/(dashboard)/<feature>/page.tsx`. Server Component by
   default; `"use client"` only for state, effects or handlers.
2. **Client** — a typed module in `src/lib/<feature>-api.ts` built on `api-client.ts`.
   Never scatter `fetch` in components. Server-side reads go through `server-api.ts`.
3. **Query keys** — register in `src/lib/query-keys.ts` so invalidation stays
   consistent.
4. **Hook** — `src/hooks/use-<feature>.ts` wrapping the client, exported from
   `hooks/index.ts`. Components consume hooks, not clients.
5. **Store** — only for UI/ephemeral state. Server data belongs in the query layer.
6. **Components** — under `src/components/<domain>/`, composed from `components/ui/`.
   Under ~100 lines; extract when they grow.
7. **i18n** — every user-facing string through `next-intl`. Never hardcode copy.
8. **Verify:**
   ```bash
   cd frontend && bun run type-check && bun run lint && bun run test
   ```

## Permissions hide controls, and that needs a test

`use-permissions.ts` reads the effective permission set for the active organization.
A control the caller may not use should not be rendered — not rendered-and-then-403.

**Write the integration test.** `*.integration.test.tsx` runs Testing Library against a
mocked API and is the cheap, precise place to assert that a permission actually hides a
button and that a form submits what it claims to. See
`components/agents/capability-settings.integration.test.tsx`,
`components/teams/members-table.integration.test.tsx`,
`components/mcp/mcp-server-list.integration.test.tsx`.

This is *not* E2E work. Reserve Playwright for journeys crossing the whole stack — see
the `e2e-tests` skill.

## The empty-state trap

Every dashboard page fans out to several queries and **renders its empty state when a
query fails**. "No skills yet" and "the skills request answered 502" are the same
pixels. So:

- When a page looks empty, check the network tab before the component.
- A test that asserts a heading and a button passes against a backend that was never
  started. Assert on data.

## Tests

```bash
bun run test          # vitest watch
bun run test:run      # once
bun run test:coverage
bun run test:e2e      # playwright — see the e2e-tests skill
```

Unit tests sit beside the source (`agent-spec.test.ts`, `auth-store.test.ts`);
integration tests are `*.integration.test.tsx`.

## Generated files

`src/lib/mcp-logos.generated.ts` is written by `bun run gen:mcp-logos`, which fetches
each catalog server's favicon and bakes it in as a base64 data URI so the demo MCP badge
renders in a self-contained HTML export with no network. Do not hand-edit it —
regenerate after changing `mcp_servers.json`.

That is separate from the backend icon contract (`app/core/catalog/icons/<name>.svg`,
served as a `currentColor` silhouette) — see the `project-docs` and `mcp-connections`
skills.
