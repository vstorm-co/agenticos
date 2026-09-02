# The console's code

[Architecture](architecture.md) is the backend. This is the other half: the
Next.js application in `frontend/`, for somebody about to change it.

**Stack.** Next.js 15 (App Router) · React 19 · TypeScript strict · Tailwind ·
`next-intl` · TanStack Query · Zustand · vitest and Testing Library ·
Playwright. Package manager and runner: **bun**.

## Where things live

| Path | |
|---|---|
| `src/app/[locale]/(dashboard)/…` | The product. Routes are **locale-prefixed** |
| `src/app/api/…` | Route handlers proxying to the backend |
| `src/lib/` | Typed API clients, `query-keys.ts`, and the registries below |
| `src/hooks/` | One per resource — `use-agents`, `use-permissions`, … |
| `src/stores/` | Zustand, one per concern |
| `src/components/<domain>/` | UI by domain; primitives in `ui/`, empty and error states in `states/` |

Server Components are the default. `"use client"` is for state, effects and
handlers, not for habit.

## The browser never calls the backend

Every request goes to `/api/*` on this app, which forwards to FastAPI with the
access token taken from an **HttpOnly cookie**. That is what keeps the token out
of JavaScript and the backend's URL out of the client bundle.

One forwarder does it — `src/lib/platform-proxy.ts` — rather than a hand-rolled
route file per endpoint repeating the same twelve lines.

!!! warning "A response with no `Cache-Control` is not a response nobody caches"

    The proxy stamps `no-store` on anything the backend left unmarked. Every
    answer here depends on a cookie, a permission set and the organization
    header, and a list refetched after a write must reach the server.

    A hand-rolled route file owes the same header — the proxy is the only place
    that applies it for you.

## Data, and where state lives

**All API access goes through a client in `src/lib/`, consumed via a hook.** No
`fetch` in a component.

Server data lives in the query layer; **stores hold UI and ephemeral state
only**. Register every query key in `query-keys.ts` so invalidation after a
write stays consistent.

## Permissions are a rendering decision

`use-permissions.ts` gives the effective permission set for the active
organization. **A control the caller may not use is not rendered** — not
rendered and then 403.

Two traps, both of which have shipped here:

- **Which roles a picker offers is arithmetic, not a list.** `assignableRoles`
  mirrors the server's rule over the permission catalog: a role is offered only
  when the caller's own strictly outranks it. A hardcoded "every role but owner"
  is what offered an Admin the Admin option and 403'd after the email was typed.
- **A page that names an organization in its URL *is* that organization.** The
  API client stamps `X-Organization-Id` from the *active* org, so a page acting
  on the org in its path while reading permissions for the active one decides
  Acme's members by your role in Globex. The adoption lives in `ActiveOrgGuard`,
  once.

## Every user-facing string goes through `next-intl`

`make lint` enforces it in both directions: a readable string sitting in a
component fails, and so does a key the catalog holds that no component reads.

Three rules that catch people out:

- **A count is an ICU `plural`, never a ternary.** `{n} file{n === 1 ? "" : "s"}`
  is a sentence only English builds that way.
- **A noun the sentence agrees with is not a parameter.** `{matched} of {total}
  {noun}` renders `3 of 40 skills` under Polish. The noun goes inside the
  `plural` or `select`.
- **The catalog holds copy, and only copy.** A false positive takes an
  `i18n-exempt` with a reason; it never takes a key. Answering one by moving a
  Tailwind class list into `en.json` is how translating a string once stripped a
  component of its styling.

English is the source language and is merged under every locale, so a missing
translation renders English rather than the key.

!!! info "The product's own nouns stay English in every locale"

    agent, spec, capability, skill, embed, budget, run, prompt, provider, token,
    vault, workspace, sandbox, MCP. They name things a client also meets in the
    docs, in the API and in exported YAML — translating them in the UI and
    nowhere else makes two vocabularies for one product. Inflect them, do not
    replace them.

## Four registries, and no second source

Each of these is one table that several parts of the UI read. Adding to the
table is the whole change; adding a second source is the bug.

| | Holds | Add by |
|---|---|---|
| `lib/tool-catalog.ts` | Icon, running caption, finished name and renderer for every tool the backend registers | A row keyed on the capability's tool id. A backend test compares the two in both directions |
| `lib/brand-glyphs.generated.ts` | Every service, connector and provider mark, as raw path data | A row in `scripts/gen-brand-icons.ts`, then `bun run gen:brand-icons`. Never an icon package import |
| `lib/dashboard/registry.ts` | The dashboard widgets and the permission each is gated on | Five edits, listed on the page below |
| `lib/dialog-sizes.ts` | One width token and one shape token per dialog | Picking a token, never a bespoke height |

## Two things a new surface owes

Both are registries with the same failure mode: a page added anywhere else is
simply absent, nothing fails, and the feature ships invisible.

**A walkthrough stop.** `lib/onboarding/tour.ts` is the passive walk a page's
"?" replays, and `flows.ts` is the guided creation it offers at the end. A page
with no stop renders **no "?" at all** — so a new page whose header has no help
button has not been registered. Gate the step on the permission its control
carries, mark it `optional` when the control needs data to exist, and anchor it
on something bounded.

**A dashboard widget**, if the feature produces state somebody would want at a
glance. Five edits: the id and definition in `dashboard/registry.ts`, the
component in `components/dashboard/widgets/`, a placement in `layouts.ts`, the
id mirrored in `backend/app/schemas/dashboard_layout.py` — a test fails when
those two drift — and copy in both `en.json` and `pl.json`.

## Verify

From `frontend/`. At the repository root vitest finds no config, reports around
164 phantom failures and leaves a stray cache directory.

```bash
bunx vitest run src/components/chat/usage-strip.test.tsx   # while writing
```

Once, before pushing — from the repository root:

```bash
make lint-frontend && make test-frontend-cov && make build-frontend
```

!!! danger "`test:coverage`, not `test:run`"

    The job CI runs measures coverage and fails under 100% lines, statements and
    functions or 97.5% branches. A suite where every test passes can still be
    red, and has been.

A dead branch is easier to delete than to cover: a `?? ""` behind a check that
already proved the value is one the gate is right to notice.

**A spec that times out is usually the machine.** `testTimeout` is 15s and
`asyncUtilTimeout` 5s, both measured rather than guessed. Neither is a reason to
keep a spec that mounts more than its assertions read.

## Recap

- The browser talks to **`/api/*` on this app**, never to FastAPI — one
  forwarder, and it stamps `no-store`.
- Server data lives in the **query layer**; stores hold UI state only.
- A control the caller may not use is **not rendered**, and role pickers are
  **computed, not listed**.
- Copy goes through **`next-intl`**, counts are ICU plurals, and the catalog
  holds copy and only copy.
- A new surface owes a **walkthrough stop**, and a widget if it has glanceable
  state — both are silent registries.

[The backend →](architecture.md) · [Adding a feature →](adding_features.md) ·
[Testing →](testing.md)
