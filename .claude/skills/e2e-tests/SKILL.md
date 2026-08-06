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
- Where a resource genuinely has no seeded row, assert on the **response** instead.

## The net, which is not a substitute

`test` from `e2e/fixtures.ts` fails any test whose page took a **5xx from `/api/*`**.
Only 5xx: a 401 from a deliberately wrong password and a 403 from a refusal are the
product working, and several specs exist to prove exactly that. `/api/rag/*` is exempt
— a test deployment has no embedding key, so collection stats answer 500 by design.

Always import `test` and `expect` from `./fixtures`, never from `@playwright/test`
directly, or the spec loses the net.

## Never assert a new row straight after a submit

> **Creating something through a dialog goes through `submitDialog` (`e2e/helpers.ts`).**

`click(submit)` followed by `expect(theNewRow).toBeVisible()` sat at six sites, was seen
to flake at four of them, and cost three separate diagnoses in one day (#132) — every
time with the same message, `element(s) not found`, sixteen seconds later.

That message is the trap. **An open Radix dialog takes the rest of the page out of the
accessibility tree**: while one is on screen `getByRole("main")`, `getByRole("row")`
and `skillCard()` resolve to *nothing at all*. So the assertion could only ever report
the absence of the page, and a create refused with a 409 looked identical to a list that
had not refetched. Measured: `main` counts 1, then 0 while the dialog is open, then 1
again — in the same sample that first sees the row.

`submitDialog` waits on two signals rather than hopes: the write's own response, whose
status and body *are* the diagnosis, and then the dialog closing — the app saying it has
finished everything it does around the write. A longer `expect` timeout is not an
alternative to either; it makes a race slower to fail.

It does **not** promise the row is rendered, and that is not a shortcut — the list's
refetch is sometimes answered with the pre-write list even though the row is committed
and both server layers return it (**#230**, about one run in eight). Two consequences:

- **A fixture step asks the API, and asks more than once.** Every step of
  `seed.setup.ts` asserts through `/api/…` now, because its job is that the fixture
  exists. Whether it renders is a product claim, and `vault.spec.ts` /
  `skills.spec.ts` make it against the rows the seed left, on pages they loaded
  themselves. Asking the API is not enough on its own: **a 2xx from this backend
  means the request was answered, not that the write is readable.** The commit sits
  in a `Depends`-with-`yield` exit code, which FastAPI unwinds after the response
  has gone out (**#353**) — measured at 21.7ms on one acceptance. So a fixture check
  is `nowThere`, a poll, never a single read. The membership step was the one site
  #222 missed when it converted the file, and it cost 87 skipped specs three times
  in a day (**#335**).
- **A product spec about the rendering reloads first**, marked `#230`, until that
  issue closes.

The list's `GET` is deliberately not a third wait: `useKnowledgeBases` never makes one,
and where one is made, #230 is about the answer being wrong rather than late.

It also ignores a 401 on the write's path. `apiClient.send` refreshes an expired access
token and re-issues the same request, so the app acts on the retry — stopping at the
first response would fail a write that succeeded.

## A failing `[seed]` step runs no product spec at all

`setup` and `seed` are project dependencies. When a step in one fails, Playwright does
not run what depends on it, and the log reads `1 failed`, `7 passed`, `17 did not run` —
which on a pull request looks like a product regression. `e2e/fixture-reporter.ts` prints
a banner saying otherwise, and a GitHub error annotation under CI. **Read it before
touching product code**, and treat a green re-run as evidence about the fixture rather
than about the branch.

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

`auth`, `agents`, `chat`, `journey`, `models`, `skills`, `vault`, `sharing`,
`navigation`, `sidebar`, `sidebar-active`, `activity`, `refusals`, `mcp-servers`,
`kb-ingestion`, `kb-integrations`. Read the closest one before adding a new file —
`refusals.spec.ts` in particular, since asserting a refusal is where this suite earns
its keep.

## The model that answers is a stub, and that is why the journey runs

`journey.spec.ts` is the only spec that runs an agent end to end, and it needs a model
to answer. It used to need a real provider key and skipped itself without one — which
meant the one spec covering the seams ran in no environment, CI included.

`e2e/stub-model-server.ts` serves the Chat Completions API, including the SSE path the
chat takes, and `playwright.config.ts` starts it beside the app on `127.0.0.1:4010`. A
model profile points at it through the **Endpoint** field, which model profiles allow on
loopback deliberately: a local model is a first-class provider here.

Two things follow, and both are easy to get wrong:

- **The stub echoes the token it is told to say** and generates nothing. That is the
  assertion: only the published agent's instructions can put that token in the request,
  so the reply proves the spec reached the provider. Do not teach it to be clever.
- **It returns usage**, because the journey's last assertion is a cost. A stub with zero
  usage would make the spec pass on a run that metered nothing — the one thing it is
  there to catch.

What it does not cover, and should not pretend to: that a real provider answers, or that
a real key is accepted. Those would make a green suite depend on somebody else's uptime.

## The pgvector trap

The database must be `pgvector/pgvector:pg16`, not stock Postgres. The RAG store issues
`CREATE EXTENSION IF NOT EXISTS vector` on first write, and stock Postgres answers
`extension "vector" is not available` — a 500 before any row is committed. If an upload
spec 500s on a fresh environment, check the image first. Every compose file and both CI
jobs pin it; they used to pin `postgres:16-alpine`, which is why no ingestion path had
ever been exercised and an upload spec sat skipped.
