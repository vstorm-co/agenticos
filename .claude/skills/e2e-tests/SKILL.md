---
name: e2e-tests
description: Write or fix a Playwright end-to-end test in frontend/e2e — a new journey spec, a seeded fixture, or debugging "the e2e suite passes but the feature is broken" / "make test-e2e fails". Use for any spec that crosses the whole stack (sign in, build an agent, publish, run, approve). Every page in this product renders its empty state when a query fails, so a spec that asserts on chrome is a spec that asserts on nothing.
---

# E2E — the suite that once tested a dead backend

```bash
make test-e2e          # checks a backend is up and says so if not
cd frontend && bun run test:e2e:ui        # pick and watch specs
bun run test:e2e:headed                   # see it happen
```

Playwright starts the frontend. The **backend, its migrations and
`agenticos cmd bootstrap` are the precondition.**

## The rule

> **A spec must assert on something the seed put there.**

Every dashboard page is a client component that fans out to several queries, and every
one renders its empty state when a query fails. "No skills yet" and "the skills request
answered 502" are **the same pixels**. A spec that asserts a heading and a button
passes against a backend that was never started — which is exactly how this suite spent
months testing the login page.

Two consequences:

- Assert on a **seeded row** — a name, a slug, a count.
- Where a resource genuinely has no seeded row (Activity needs a real provider key to
  have a run), assert on the **response** instead.

## The net, which is not a substitute

`test` from `e2e/fixtures.ts` fails any test whose page took a **5xx from `/api/*`**.
Only 5xx: a 401 from a deliberately wrong password and a 403 from a refusal are the
product working, and several specs exist to prove exactly that. `/api/rag/*` is exempt
— a test deployment has no embedding key, so collection stats answer 500 by design.

Always import `test` and `expect` from `./fixtures`, never from `@playwright/test`
directly, or the spec loses the net.

## Prove a new spec can fail

Point `BACKEND_URL` at a dead port and watch it go red **before you trust it**. A spec
that has never failed has never been tested.

## The two fixture layers

**`agenticos cmd bootstrap`** — an owner, an organization, a model profile, and the
published agent `@getting-started`. It walks a fresh install to *one working agent* and
stops there on purpose; it is the shortest path to seeing the product work, not a demo
database.

**`e2e/seed.setup.ts`** — what bootstrap deliberately does not: a skill, a knowledge
base, a draft agent, a stored key, an org MCP connection, and a second member. It
creates them **through the UI**, so the setup is itself a test of the create paths.

Names live in `e2e/helpers.ts` as constants (`SEEDED_SKILL_NAME`, `DRAFT_AGENT_SLUG`,
…). Assert against those constants, never a literal — a renamed fixture then fails
loudly in one place instead of in six specs.

Need a new fixture? Add it to `seed.setup.ts` and export its name from `helpers.ts`. Do
not create data inside a spec unless creating it *is* the behaviour under test.

## What belongs here, and what does not

E2E is for journeys crossing the whole system: sign in, build an agent, publish it, run
it, approve a tool call, share a conversation.

It is **not** for: a permission hiding a button (that is a frontend integration test
with a mocked API — cheaper and more precise), a service rule (unit), or a constraint
(backend integration). See the `frontend-feature` and `backend-tests` skills.

## Existing specs

`auth`, `agents`, `chat`, `journey`, `skills`, `vault`, `sharing`, `navigation`,
`sidebar`, `sidebar-active`, `activity`, `refusals`, `mcp-servers`, `kb-ingestion`,
`kb-integrations`. Read the closest one before adding a new file — `refusals.spec.ts`
in particular, since asserting a refusal is where this suite earns its keep.

## The pgvector trap

The database must be `pgvector/pgvector:pg16`, not stock Postgres. The RAG store issues
`CREATE EXTENSION IF NOT EXISTS vector` on first write, and stock Postgres answers
`extension "vector" is not available` — a 500 before any row is committed. If an upload
spec 500s on a fresh environment, check the image first. Every compose file and both CI
jobs pin it; they used to pin `postgres:16-alpine`, which is why no ingestion path had
ever been exercised and an upload spec sat skipped.
