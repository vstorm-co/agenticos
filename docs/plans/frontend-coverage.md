# Getting to 100% coverage

Goal: 100% on both stacks, with as few exclusions as we can defend. This file is
the running ledger - what is done, what is left, and how much of it there is.

Two gates, and only one of them is in `make check`:

| | Runs | Currently |
|---|---|---|
| Backend platform layer | `make test` / `make check` | **100%**, enforced |
| Backend whole app | `make coverage-all` (informational) | **66%** - 4,538 of 14,814 statements uncovered |
| Frontend, measured set | `bun run test:coverage` - **CI only** | **100%** statements, lines and functions; 98.7% branches, enforced |
| Frontend, whole of `src` | informational | see the table below |

`make check` runs `test:run`, not `test:coverage`. That is why the frontend gate
sat red without anyone noticing; the thresholds are now **100/98/100/100** and the
`include` list is what has *finished*, widened one layer at a time.

Branches are gated at 98 rather than 100 for one reason: TypeScript-required
guards whose other half no caller can reach - `event.target.files ?? []`,
`pop() ?? "text"`, a `?? ""` on a value an early return already proved, a
`typeof window === "undefined"` in a client module. Each is a narrowing, not a
behaviour. Faking one would mean testing the type checker.

## Frontend

### At 100%, and gated

| Layer | Files | What it holds |
|---|---|---|
| `src/lib/**` | 26 | The API client and its 401 recovery, the error envelope readers, the query-key factory, the RAG and MCP wrappers, SEO metadata, the ingestion config, the file tree, the diff |
| `src/stores/**` | 11 | The streaming message timeline, the session, the active organization and its refusals, the UI panels |
| `src/components/agents/**` | 26 | The Builder: the spec forms, the capability workbench, version history, exposures, embeds, alerts, the agent map |
| `src/components/skills/**` | 6 | The skill workbench and its files, the create dialog, the gallery |
| `src/components/sharing/**` | 1 | Grants and visibility |
| `src/hooks/**` | 30 | All of them. The chat's socket and its stream reader, the session, the conversation list, knowledge bases and their uploads, the admin screens, every data hook |
| `src/app/api/**` | 69 | Every proxy route. The session cookies, the admin gate, the byte-moving routes, the OAuth callback, and all 18 mounts of the shared forwarder |
| `src/components/chat/tool-results/**` | 8 | Every renderer a tool call can get, and the generic fallback that catches the rest |
| `src/components/chat/` (20 of 24) | 20 | The Markdown renderer and its citations, the tool-call card, the transcript item, the per-conversation controls, the share dialog, the slash-command registry and palette, the citations panel, the approval dialog, ratings, the file preview and its viewers, the transcript list, the queue, the empty state, copy |

### Left, in the order worth doing it

Measured against the whole of `src` (33,270 statements, 12,196 covered at the last
informational run - the numbers below are what each group has *uncovered*):

| Group | Uncovered | Notes |
|---|---|---|
| `src/app/[locale]/**` | 8,060 | The pages. Last on purpose - composition, and the E2E suite is where a broken page actually fails |
| `src/components/chat/` (4 files) | ~1,150 | `conversation-sidebar` (480), `chart-message.impl` (420), `chat-input` (405), `chat-container` (402) |
| `src/components/legal`, `auth` | 1,285 | Static copy and the four auth forms |
| `src/components/kb`, `rag` | 1,204 | Ingestion settings, the upload flow, sync sources |
| `src/components/ui/**` | 536 | Primitives. Cheap, and several already have tests |
| `src/components/{settings,admin,dashboard,vault,layout,mcp,teams,theme,states}` | ~1,100 | Panels and tables |
| `src/i18n.ts`, `src/middleware.ts` | 33 | The locale negotiation and the auth redirect |

Order: **the rest of the chat → the smaller component directories → pages.**
What is left in the chat is the big composed pieces - the composer, the
transcript item, the sidebar, the file preview - and the two heavy renderers
behind `next/dynamic`.

The route tests declare `@vitest-environment node`, because that is where a route
handler runs - and because `request.formData()` never resolves under jsdom, so
every upload route would have hung. `vitest.setup.ts` guards its `window` work on
that.

### Found while covering the chat renderer

Two defects in `markdown-content.impl.tsx`, both fixed, both with a test that fails
against the old code:

- **The copy button was missing from every highlighted code block.** The block's
  text was read as `children` assuming a string, but `rehype-highlight` replaces
  that single text node with a tree of `<span>` tokens - so the button rendered
  only for a block whose language nothing recognised. It now reads the text out of
  the token tree. The most-used control on a code block had quietly gone.

- **A reference-style link was corrupted whenever citations were on.** The citation
  pass rewrote the `[1]` in `See [the docs][1].` into a link of its own, leaving a
  stray bracket and a dangling anchor in the answer. The pass now matches the whole
  `[text][N]` form and hands it back untouched - while still marking `[1][2]`,
  which is what an agent writes when two sources agree.

### Found while covering the proxy routes

**The admin conversations screen could not filter by agent.** The proxy forwards an
allowlist of query parameters, and `agent_id` was not on it - so the filter the
screen offers sent a value that never left the proxy, and the table answered with
every thread. The backend accepts the parameter and the hook sends it; only the hop
between them dropped it. Fixed, and `admin-routes.test.ts` now pins each parameter
the screen can send.


Thirty-eight of the generated routes under `src/app/api` answer a refusal with
`detail: error.message`. That is `BackendApiError`'s own string - `"Backend API
error: 400 Bad Request"` - not the backend's `detail`, which is sitting right
there in `error.data`. The routes written by hand for this platform
(`login`, `register`, `oauth-callback`) read the envelope properly; the
template's do not.

The symptom is a user-visible one: an expired magic link, a stale password-reset
token and a duplicate invitation all report a status code instead of the sentence
that says what to do. The fix is one helper and thirty-eight call sites, so it
wants its own change rather than riding along with the tests -
`session-routes.test.ts` asserts the current behaviour with a comment naming it,
because a test claiming the better sentence would be a test of nothing.

## Backend

The platform layer is at 100% and gated. The whole app is at 66%, and the 4,538
uncovered statements are concentrated in template-inherited I/O:

| Module | Missing |
|---|---|
| `worker/tasks/rag_tasks.py` | 185 |
| `services/rag/documents.py` | 159 |
| `services/channels/router.py` | 138 |
| `services/rag/vectorstore.py` | 126 |
| `services/rag/retrieval.py` | 100 |
| `services/channels/slack.py` | 96 |
| `services/channels/telegram.py` | 87 |
| `services/channels/mattermost.py` | 82 |
| `services/rag/ingestion.py` | 81 |
| `services/rag_document.py` | 72 |
| `services/rag/connectors/google_drive.py` | 59 |
| `services/rag/sources/google_drive.py` | 40 |
| `services/rag/connectors/s3.py` | 39 |
| ...and roughly 3,300 more spread thin | |

`CLAUDE.md` currently argues against holding these to the platform bar, on the
grounds that testing an adapter's internals through mocks "buys a coverage number
rather than confidence". That argument is worth revisiting rather than deleting:
several of these are not really adapters -

- `channels/router.py` decides which agent answers a mention, **as which user**.
  That is an authorization path and it belongs in the gated set.
- `rag/retrieval.py` and `vectorstore.py` decide what an agent is allowed to read
  back. Also authorization, dressed as search.
- `rag_tasks.py` is where an upload dies silently, which this repository has
  already been bitten by.

The genuinely mock-only ones are the transport edges: `slack.py`, `telegram.py`,
`mattermost.py`, `connectors/*`, `providers/smtp.py`. Those are where an
integration test against a fake server earns more than a mocked unit test.

### Suggested order

1. Move `channels/router.py`, `rag/retrieval.py`, `rag/vectorstore.py` and
   `worker/tasks/rag_tasks.py` into the gated list, one at a time, covering each
   to 100% as it goes in. These four are ~550 statements and carry real rules.
2. `rag/documents.py`, `rag/ingestion.py`, `rag_document.py` - the pipeline. ~310.
3. The transport edges, with a fake server rather than mocks where practical.
4. Everything remaining, thin and mechanical: schemas, models, `__init__` files.

Adding a module to `[tool.coverage.run] include` also adds it to
`[[tool.ty.overrides]] include` - `tests/test_coverage_gate.py` asserts the two
lists are equal, so they move together.

## A flaky integration test, found while verifying this

`TestChattingWithAPublishedAgent::test_a_chat_turn_lands_in_run_history_as_a_web_run`
fails roughly one run in five, in isolation, with no ordering involved (there is
no `pytest-randomly` or `xdist` here). It asserts that a chat turn which ended
badly still left a row in `agent_runs`; on a bad run there is no row at all, so
`(await self._runs(db))[0]` raises `IndexError`.

The `RuntimeError` the test expects is raised and logged normally, and there is no
`run_notification_failed` in the output, so `finish()` is reached and the notifier
is not the cause. Something between `finish()` writing the row and the test's
`SELECT` seeing it is nondeterministic.

Worth knowing: every green full-suite run earlier in this session was on **Python
3.14.3**, and this reproduces on **3.12.9**, which is what `backend/.python-version`,
`requires-python`, the Dockerfile and CI all use. So it is the shipping
interpreter that flakes, and the one that was masking it was the local-only newer
one. Not attributable to this session's changes with any confidence - it needs its
own investigation, and a flaky test in CI is worse than a failing one because it
teaches people to re-run.
