---
description: Frontend conventions — App Router, data layer, stores, i18n, permissions
globs: ["frontend/**/*.ts", "frontend/**/*.tsx", "frontend/**/*.css"]
---

# Frontend Conventions

Deeper guidance lives in the `frontend-feature` skill.

## Stack

Next.js 15 (App Router) · React 19 · TypeScript strict · Tailwind · `next-intl` ·
TanStack Query · Zustand · vitest + Testing Library · Playwright. Package manager and
runner: **bun**.

## Structure

| Path | |
|---|---|
| `src/app/[locale]/(dashboard)/…` | The product. Routes are **locale-prefixed** |
| `src/app/[locale]/(auth)/`, `auth/`, `onboarding/`, `legal/`, `shared/` | Everything else |
| `src/app/api/…` | Route handlers proxying to the backend (same-origin auth cookies) |
| `src/lib/` | Typed API clients on `api-client.ts` / `server-api.ts`, plus `query-keys.ts` |
| `src/hooks/` | One per resource — `use-agents`, `use-permissions`, … |
| `src/stores/` | Zustand, one per concern, re-exported from `index.ts` |
| `src/components/<domain>/` | UI by domain; primitives in `ui/`, empty/error in `states/` |
| `src/types/` | Shared types |

There is no `(marketing)` route group.

## Conventions

- **Server Components by default.** `"use client"` only for state, effects or handlers.
- **All API access goes through `src/lib/` clients**, consumed via a hook. No `fetch`
  in a component.
- **Register query keys** in `query-keys.ts` so invalidation stays consistent.
- **Stores hold UI/ephemeral state only.** Server data lives in the query layer.
- **Every user-facing string through `next-intl`**, and `make lint` enforces it:
  `scripts/check_i18n.py` fails on a string a person would read sitting in a
  component - a text node, a readable attribute, a toast, a sentence in a ternary -
  and on the reverse, a key a component reads that `messages/en.json` does not hold.
  A genuine non-string takes `i18n-exempt: <reason>`; the reason is required.
  It reads a file **line by line**, so two shapes still get past it: a text node the
  formatter broke across lines, and a template literal with one word beside its
  interpolation (`` `Remove ${name}` ``). Neither is allowed - they are unread, not
  exempt - and there are 114 of them in the tree waiting for the parser rewrite.
  Do not add a 115th because the guard stays quiet.
- **A count is an ICU `plural`, never a ternary.** `{n} file{n === 1 ? "" : "s"}`
  and `count === 1 ? "1 skill" : \`${count} skills\`` are sentences only English
  builds that way, so they are refused too - the message holds
  `{count, plural, =1 {1 skill} other {# skills}}` and the component passes `count`.
  Same for a text node that mixes words with an interpolation: it is one message with
  a named parameter, not English with a hole in it. **A single word counts** — on
  either side, and whichever way round the guard reads it: `Owned by {email}`,
  `{n} runs`, and `Rotate {name}` / `chunk {n}` / `· expires {date}` are all refused.
  A lambda inside the interpolation does not make it something else, so a count summed
  with `reduce` is refused too.
- **English is the source language, and `pl.json` holds only what is translated.**
  `src/i18n.ts` merges `en.json` underneath every locale, so a missing translation
  renders English instead of the key. A module-level table of labels cannot call a
  translator, so it holds *keys* and the component translates at the point of use;
  a pure helper either answers with a key or takes `t`.
- Keep components under ~100 lines; extract when they grow.
- Do not hand-edit `src/lib/mcp-logos.generated.ts` — run `bun run gen:mcp-logos`.

## Permissions

`use-permissions.ts` gives the effective permission set for the active organization. A
control the caller may not use is **not rendered** — not rendered and then 403.

Prove it with an integration test (`*.integration.test.tsx`, Testing Library against a
mocked API), not with Playwright.

## An empty page is ambiguous

Every dashboard page fans out to several queries and renders its empty state when one
fails. "No skills yet" and "the request answered 502" are the same pixels — check the
network before the component, and never write a test that asserts only on chrome.

## Verify

From `frontend/` — at the repository root vitest finds no config and reports phantom
failures. While writing, run only what covers the change:

```bash
bunx vitest run src/components/chat/usage-strip.test.tsx
```

Once, before the push — from the repository root, because CI's `test-frontend` job
runs all four and `make lint-frontend` is the first three of them:

```bash
make lint-frontend && make test-frontend-cov && make build-frontend
```

**`test:coverage`, not `test:run`.** The job CI runs measures coverage and fails under
100% lines/statements/functions or 97.5% branches on `src/{app/api,lib,stores,hooks}`
and most of `src/components`, so a suite where every test passes can still be red. A
dead branch is easier to delete than to cover: a `?? ""` behind a check that already
proved the value, or an optional prop two callers always pass, is one the gate is
right to notice.
