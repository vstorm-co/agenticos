# Changelog

Notable changes to AgenticOS. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Two things are versioned separately from this file and worth knowing about:

- **`SPEC_VERSION`** — the agent spec format, currently **8**. A published agent
  and a client's exported YAML both carry it, so it only ever moves forward with a
  migration that keeps old documents loading. See
  [the spec reference](docs/reference/spec.md).
- **The migration chain** — `backend/alembic/versions/`, squashed to a single
  `0001_baseline` for this first version. Revision ids named below (`0038`,
  `0059`, `0066`) are history: they describe when something changed, not a file
  that still exists. Schema changes are listed here by what they do.

## [Unreleased]

### Changed

- **The i18n guard parses instead of grepping, and the copy it found is in the
  catalog.** `scripts/check_i18n.py` had been patched for a new shape four times
  (#199, #246, #249, #314) and each fix was correct: the pattern was the problem.
  Reading a `.tsx` file as text means deciding per candidate whether you are looking
  at TypeScript or JSX, so every rule carried a threshold standing in for a parse
  and the next shape fell between two of them. The last one was one word wide —
  `` aria-label={`Remove ${source.name}`} `` sat below a two-word threshold that
  existed to keep `` `audience${key}Hint` `` out. It is now
  `frontend/scripts/check-i18n.ts`, walking `JsxText`, `JsxExpression`,
  `StringLiteral` and `TemplateExpression` through `ts.createSourceFile`: a node the
  formatter broke over three lines is one node, a type argument list is not JsxText
  at all, and a comment is invisible rather than blanked. `MIXED`, `COUNT`, `LEAD`,
  `JSX_TEXT`, `mask_generics`, `readable`, `NOT_PROSE` and both word-count
  thresholds are deleted rather than ported; every policy rule carries over.
  Runs from `make lint-frontend` (`bun run check:i18n`) and a new pre-commit hook,
  with `frontend/scripts/check-i18n.test.ts` in place of the five
  `backend/tests/test_check_i18n_*.py` files. Closes #395 and #141. (#610)
- **131 hardcoded strings answered, and 34 dead keys deleted.** What the parser
  reports on the tree before the sweep, in 66 files: 64 template literals, 62 text
  nodes, 4 strings and a toast. That is the one-word template literals #395
  measured (`aria-label`s and toasts — `Open ${org.name}`, `${name} updated.`), the
  multi-line text nodes #141 measured (the 404 page, `global-error.tsx`, the
  magic-link step, four legal paragraphs), and eight confirm-dialog titles a bare
  `?` on the machine-read list had been exempting. 128 became messages; three took a
  reasoned `i18n-exempt` — two on the error boundary that renders above
  `NextIntlClientProvider`, one on a capability's wire format. A sentence split across an
  element is now one `t.rich` message rather than a head, a `<span>` and a tail,
  which is what made the 34 fragment keys dead — the guard's own `unreadKeys` named
  every one. Three decisions worth recording. A number and its unit is a formatter
  rather than a message — `` `${bytes} KiB` `` is the shape, and `ctx` joined the
  unit list for the model picker's badge — so the fourteen of those take a rule
  rather than fourteen exemptions. `PROVIDER_DEFAULT` holds a key now instead of the
  words, per the module-table rule. And `result: ` in `run-python.tsx` keeps an
  exemption, because `parseResult` beside it matches the string literally. (#610)

### Fixed

- **An `i18n-exempt` now covers the element it opens.** It applied to its own line
  and the next, so the three exemptions in `app/not-found.tsx` — written above an
  `<h1>` whose words are on the third line, because the opening tag carries four
  Tailwind classes — covered the tag and missed the copy. Nothing noticed while a
  text node alone on its line matched no rule at all. A reason worth two lines
  covers the code under the whole comment block, too. (#610)
- **The parser reads a `.ts` file, which is what kept #446 closed.** The port
  landed with the offence sweep narrowed back to `*.tsx`, because the branch was
  cut before #446 was fixed. Merging it that way would have taken the `.ts` sweep
  out again — every `toast.success("…")` in `src/hooks/**` invisible, and nothing
  stopping the 381 strings #446 migrated from coming back. The sweep reads both
  suffixes now, by the same rules: a parser has no bracket to anchor on, so
  nothing needs gating on the suffix. `src/app/api/**` keeps its skip, still at
  the sweep rather than in a rule, because a route payload is a string a rule
  reads perfectly well and what excuses it is where it lives (#603). Six strings
  the widened sweep found are in the catalog: `timeAgo`'s three relative-time
  labels as ICU plurals, the stream-error prefix, `chunk {number}`, and
  `summarizeEmbedding` — deleted rather than translated, having had no caller but
  its own test. (#610)
- **A key was checked against the wrong namespace when a file held two
  translators.** `missingKeys` unioned every namespace in a file, so a key read
  through one translator counted as present if any *other* namespace held it. That
  hid eight keys on the admin conversations page: `archived`, `active`, `all`,
  `allOwners` and `allAgents` were read through a `useTranslations("admin")` while
  only `pages.admin` held them, so all eight rendered as their own key strings on
  screen in every locale. A call now resolves to the nearest enclosing binding of
  that name — by scope, because one page binds `getTranslations("pages.meta")` in
  `generateMetadata` and `getTranslations("pages.auth")` below it, both called
  `t`, and keying on the name alone reports 157 live keys as missing. Where the
  walk finds no binding it falls back to every namespace that name takes. (#610)
- **`` `Bearer ${token}` `` was reported as copy.** An auth header value is the one
  header shape `MACHINE_READ`'s character class cannot see, holding no punctuation
  at all, so the whitespace rule read it as a word beside an interpolation. Only
  latent while the sweep skipped `.ts`; both call sites are in `src/lib`. (#610)
- **A ternary between two one-word labels in a readable prop was read by nothing.**
  `aria-label={busy ? "Saving" : "Save"}` passed the attribute rule, which read a
  bare literal, and `readString`, which wants a capital and a space before it calls
  something a sentence — #395's own defect wearing a ternary. A label is
  capitalised or holds a space, which keeps `dir === "asc" ? "desc" : "asc"` out.
  (#610)
- **A toast holding a sentence was reported twice**, once by each rule that owns
  it, inflating the count a person works through. The toast rule keeps its
  argument. (#610)
## [0.0.103] - 2026-08-11

The Builder says when the agent people are talking to is not the one on screen,
and Publish says what it will move before it moves it.

### Added

- **Publish says what it will move before it moves it.** The confirmation dialog
  names the version it creates, the default environment that follows the publish
  the moment it lands (or, on a first publish, that `production` is created and
  the agent goes live), and each pinned environment that stays on the version it
  is pinned to. (#519)

### Fixed

- **The Builder tracked "unsaved" and never "unpublished".** Once the autosave
  settled the page read as finished, while every channel, widget and API call was
  still answering with the published version — toggle a tool off in the Toolbox
  and nothing on screen said a publish was needed. A header badge now compares the
  *stored* draft against the frozen version spec: "Draft differs from v7", with a
  title spelling out that published surfaces keep answering with v7 until a
  publish, or "Up to date with v7". Compared as sorted-keys YAML, the same
  serialization the version diff reads, so key order cannot read as a change
  nobody made. (#519)
- **A publish left the environments panel naming the pin it had just moved.**
  Publish and rollback invalidated `qk.agents` and not `qk.environments`, so the
  History tab contradicted the dialog's own sentence seconds after it was read.
  Pre-existing; included because the new dialog makes it visible. (#519)

## [0.0.102] - 2026-08-11

The copy guard reads a `.ts` file, and the 381 English strings it had never been
pointed at are in the catalog.

### Fixed

- **`check_i18n.py` never read a `.ts` file, so every hook toast was invisible to
  it.** The offence sweep walked `frontend/src/**/*.tsx` and nothing else, which
  left 381 offences across 90 files unread since the guard was written: nineteen
  `toast.success("…")` in `src/hooks/**` alone, plus the module tables of labels in
  `lib/tool-catalog.ts`, `lib/ingestion-config.ts` and `lib/mcp-servers.ts`.
  Widening the glob was not the fix — in a `.ts` file `; return` is a text node and
  `a > b` is a count — so `JSX_TEXT`, `MIXED`, `COUNT` and `LEAD` are gated on the
  suffix and the rest now read a string literal wherever it sits. All 381 are
  migrated: 233 messages added to `messages/en.json`, and the module tables hold
  keys with the copy resolved where it renders, pure helpers taking the caller's
  translator (`toolStep`, `toolCaption`, `ingestionProblems`,
  `mergeWithUserCommands`). (#446)
- **The `import`/`export` line-skip keyed on the keyword rather than the module
  specifier**, which in a `.ts` file hid every `export const LABEL = "…"` and every
  default parameter on an `export function` — `getErrorMessage`'s
  `"An unexpected error occurred"`, the sentence behind most failed requests here,
  and `PROVIDER_DEFAULT` beside a `useTranslations` import somebody had already
  added and never used. (#446)
- **The MCP add-server dialog rendered a catalog key as its hint.** `AUTH_CHOICES`
  held `hint: "authTokenHint"` and the paragraph below the radio group printed it
  verbatim, in every locale — neither a hardcoded string nor a missing key, so no
  guard could see it. Found by the duplication rule once the catalog held the
  sentence. (#446)
- **The test translator was rebuilt on every call**, where the real
  `useTranslations` is a `useMemo` over stable inputs. A hook putting `t` in a
  `useCallback`'s dependencies then handed a new function to every render, and an
  effect keyed on that callback re-fired forever: the admin conversations screen
  loaded in a loop and never left its spinner. `vitest.setup.ts` caches one
  translator per namespace. (#446)

### Removed

- **A superseded MCP catalog and two dead helpers.** `lib/mcp-catalog.ts` held a
  curated table of fourteen servers with their own descriptions, examples and
  category headings; nothing rendered it — the catalog the product shows is served
  by the backend from `app/core/catalog/mcp_servers.json`, is fifty-nine entries
  deep, and has its own categories. Its copy was dead English, so it was deleted
  rather than translated, along with `MCP_CATEGORIES`' four unrendered headings and
  `summarizeIngestion`, which only its own test called. `gen-mcp-logos.ts` now
  takes its domains from the backend catalog. (#446)

## [0.0.101] - 2026-08-11

Three static guards against the code getting worse, and the slop they target
swept out of the tree.

### Added

- **Guards that enforce standards `CLAUDE.md` only stated.** `scripts/check_routes.py`
  keeps an endpoint module to routers — a helper moves to a service or a
  `_`-prefixed module, or carries a reasoned `# routes-helper` marker;
  `scripts/check_comments.py` rejects ASCII banner comments; and `vulture` gates
  unused variables and parameters in `make lint`. The noisier function-level scan
  and the frontend `knip` live in `make dead-code` as an advisory report, because
  a blocking function gate on a registry-driven codebase is false positives all
  the way down. (#595)

### Changed

- **Route helpers moved out of the endpoint modules.** The runs status parser
  became `RunStatus.parse_csv`, on the enum that owns the values and shared by the
  list and export routes; the sharing loaders moved to `_sharing_loaders.py`.
- **Comment slop removed, ~140 lines across the backend and frontend** — section
  labels, restatements, and mechanism-narration. The load-bearing
  `#issue`/footgun/invariant comments and the docstrings stay, and `CLAUDE.md` and
  `code-style.md` now state the bar: the default is no comment.
- **Two dead items the previous sweep missed**, caught by the new `vulture` gate:
  `sanitize_filename`, orphaned when its only caller was removed in #579, and a
  dead `project_id` argument on `channel_session.create`. Closes #521. (#595)

## [0.0.100] - 2026-08-10

Dead weight removed across the backend and frontend, and one dead method turned
into a real contract.

### Changed

- **Stripped unreferenced code across the tree.** Repository helpers, service
  methods, sanitizers and frontend exports with no surviving caller are deleted
  (each traced first), and four frontend `export`s narrowed to module-internal.
  Net −892/+53. Not only deletion: the vector store's dead `aclose()` becomes an
  abstract contract the application lifespan shuts down through, so teardown no
  longer reaches past the interface into `.engine` behind a `# type: ignore`.
  (#579)

## [0.0.99] - 2026-08-10

Run history can be filtered by rating, and a down-rated run says so — with the
comment readable on the run itself.

### Added

- **Filter run history by rating, and flag a down-rated run.** A `rated=down`
  filter on run history, and a `down_rated_run_ids` marker on list rows —
  tenant-bound, `distinct`, and the same `rating < 0` definition the filter uses,
  so a marked row is exactly a row the filter returns. In the run detail, the
  most recent down rating's comment is read off the transcript
  (`RunTranscriptMessage.rating_comment`, from
  `get_down_rating_comments_for_messages`, batched newest-first), so "what people
  said was wrong" is readable where the run is read rather than only in the
  app-admin export. Permission-gated on `runs:view`. Completes the run side of
  #209. (#538)

## [0.0.98] - 2026-08-10

Runs, approvals and spend export as CSV — exactly the rows the list would show.

### Added

- **CSV export for runs, approvals and spend.** `GET /runs/export`,
  `/approvals/export` and `/spend/export` each serialise exactly the rows their
  list route would return, gated as their list sibling is (runs and spend on
  `runs:view`, approvals on `approvals:decide`) with the `Scope.OWN` floor
  enforced in-query. An unbounded export gets the two rules it needs by design: a
  mandatory date range and a row cap that refuses rather than truncates above it.
  Columns survive a spreadsheet sum — `cost_is_partial` on runs,
  `partial_run_count` on spend, so a wholly unpriced run exports a real `0` beside
  `cost_is_partial=true`, never a bare `0` — and CSV formula injection is
  neutralised. Each export writes an `audit_log` entry (window, applied filter
  names, row count — never the request body or a resolved row). An export menu on
  the Activity page carries the applied filters, gated on `runs:view`. Closes
  #211. (#531)

## [0.0.97] - 2026-08-10

Regression coverage that every entry point records a run's transcript.

### Changed

- **Transcript recording is covered for embed, channel and default-agent runs.**
  `backend/tests/test_surface_transcripts.py` asserts at the repository boundary
  that a widget run, a channel mention and the default agent each record their
  turns — role, content, run id, the model and version that actually ran, and
  tool-call args and results — and that a broken widget run still records what
  the visitor asked. Closes #205's requirement that the fix ship with a
  regression test. (#530)

## [0.0.96] - 2026-08-10

The sync-source wizard is decomposed into one component per step — a structural
refactor, no behaviour change.

### Changed

- **Sync-source wizard split into per-step components.** The 761-line
  `sync-source-wizard.tsx` becomes a ~320-line shell (cross-step flow, the shared
  form, the header and step indicator, and the `connectorsFailed` /
  `orgIntegrationsFailed` flags it hands down) plus one component per step —
  `sync-source-{connector,configure,schedule,clone}-step.tsx` — following the
  pattern #221 set in `components/rag/`. A folded-in fix routes the empty-config
  note through `next-intl`. Closes #461, #540. (#529)

## [0.0.95] - 2026-08-10

The Activity tab's spend view breaks down who spent what.

### Added

- **Per-person spend on the Activity tab.** A `SpendByPerson` card beneath "By
  agent" on the Spend tab reads `/stats/usage?group_by=user` over the tab's date
  window, gated on `runs:view` (renders nothing and issues no query without it),
  with delegated runs excluded. A "+N others" line appears when `active_users`
  exceeds the rows shown, so a top-N list never reads as the whole organization.
  Closes #214. (#578, superseding the stacked #527)

## [0.0.94] - 2026-08-10

The Activity tab gains a per-version summary that cannot disagree with the
dashboard's completed-share figure.

### Added

- **A version strip on the Activity tab.** When narrowed to one agent, a card per
  version sits above the run table — runs, completed share, cost per run, p95 and
  the current-version marker. Its "completed share" and the dashboard's Outcomes
  donut both compute through one shared helper (`src/lib/run-outcomes.ts`), with
  `cancelled` and `budget_exceeded` in the denominator on both sides, so the two
  figures cannot drift. Closes #489. (#526)

## [0.0.93] - 2026-08-10

A run's transcript is readable by authorization, not only by whoever owns the
run.

### Added

- **`GET /api/v1/runs/{run_id}/transcript`** — returns a run's messages
  (paginated) to any colleague in the same organization holding `runs:view`; a
  run is read by authorization, not by ownership. A caller from another tenant is
  refused exactly as a run that does not exist is, so existence never leaks. The
  response's `conversation_id` is `null` when the run has no transcript, distinct
  from an empty `items`. `AgentRunnerService.get_run_transcript` resolves the run
  org-scoped (404 before the permission is read), then checks `runs:view` (403).
  Closes #490. (#525)

## [0.0.92] - 2026-08-10

The whole-suite test targets run across worker processes, roughly halving them.

### Changed

- **`make test` and the other whole-suite targets run across workers.** `pytest
  -n auto --maxprocesses 4` on `test`, `test-fast`, `test-integration` and
  `test-cov`; `pytest-cov` combines the per-worker data so the 100% platform gate
  is unchanged, and scoped `pytest <file>` runs stay serial (spawning workers for
  one file costs more than the file). The cap is four because the unit slice is
  import-bound — every worker imports the app once — and an uncapped `-n auto` on
  a many-core machine runs *slower* than serial, all of it worker startup. Adds
  `pytest-xdist` to the dev group. Refs #520. (#570)

## [0.0.91] - 2026-08-10

The integration test suite builds its schema once per process instead of before
every test, halving it.

### Changed

- **Integration tests build the schema once, not before every test.** The
  per-test `drop_all` + `create_all` (~0.4s of DDL each, very nearly the whole
  runtime of a suite whose assertions are microseconds of Postgres work) is
  replaced by a session-scoped build plus a `TRUNCATE ... RESTART IDENTITY
  CASCADE` reset between tests. The integration slice drops from ~125s to ~53s,
  and the per-process `_p<pid>` database isolation is untouched, so two runs on
  one machine stay safe. `TRUNCATE`, not a rollback: the API-flow tests commit
  through the real session, so their rows would outlive a rollback. Closes #215.
  Refs #520. (#535)

## [0.0.90] - 2026-08-10

Importing the application stops dragging in two SDKs it never uses on the
request path, so every process start and scoped test run is a couple of seconds
shorter.

### Changed

- **`import app.main` no longer pulls in `aiogram` and `prefect`.** The Telegram,
  Slack and Mattermost adapters are imported inside `lifespan` (which the test
  client never runs) and the sync flows inside their dispatcher, so a cold app
  import drops from ~5.5s to ~2.3s — a cost every scoped `pytest` run and every
  process start paid for libraries neither the API nor the tests touch. A
  subprocess guard test keeps them out of `sys.modules`, and a dead
  `_slack_register` alias went with it. Runtime behaviour is unchanged; startup
  imports them as before. Refs #520. (#544)

## [0.0.89] - 2026-08-10

Run history gains the duration controls the dashboard's p95 needs rows behind,
and the contributor guidance has its test-loop numbers corrected.

### Added

- **Sort and filter run history by duration** — a sortable `Took` column, a
  "slow runs" canned view, and a dashboard p95 deep-link that seeds the sort and
  the time window. The sort is server-side over the whole narrowed set, not one
  page; the backend query landed with #202 and is reused unchanged. Closes #210.
  (#528)

### Changed

- **Contributor guidance** — `CLAUDE.md` now states the scoped-vs-full test rule
  outright and its runtime figures are corrected against measurement: CI answers
  in about twelve minutes rather than seven, and a scoped backend file takes a
  few seconds rather than "under one" (the wait is importing the app, not the
  run). The same stale CI figure in `docs/testing.md` and three moved
  `app/core/catalog/` paths in the docs trigger map went with it. Closes #522.
  (#534)

## [0.0.88] - 2026-08-10

Two grouped dependency updates, nothing else. The lockfile resolves cleanly with
both applied (`uv lock --check`), and CI is green on the combination.

### Changed

- **Agent-framework dependencies** — `pydantic-ai-slim` to 2.26.0 (including its
  `mcp` extra), `logfire` to 4.40.0, and `genai-prices` to 0.1.1. (#523)
- **The rest of the backend** — `uvicorn[standard]` to 0.52.1, `alembic` to
  1.19.0, `pymupdf` to 1.28.2, `liteparse` to 2.11.1, `google-auth` to 2.56.3,
  `boto3` to 1.43.66, and the `ty` type checker to 0.0.69. (#524)

## [0.0.87] - 2026-08-10

Mattermost is a channel you can register and talk to, and the gaps that stopped
any channel from being a complete surface are closed with it. One agent can now
answer on Mattermost, Slack and Telegram, be watched writing its reply, read the
channel it is answering in, and be told how to write for that surface — without
editing the spec every surface shares. Closes eleven issues (#41, #24, #22, #10,
#205, #157, #152, #208, #26, #153, #514). The delivery-dedup guard a retried
webhook needs is deliberately not here and stays tracked as #167.

Nine migrations, `0013`–`0021`, add the link-request, exposure-prompt and
per-binding tool columns and settle the "one agent per bot" rule. `SPEC_VERSION`
stays at **8**: the channel-tools capability is assembled per run from the
binding that admitted the message, never stored in a published spec.

### Added

- **A working Mattermost integration.** A bot is registered with its own server
  URL and an operator-supplied webhook secret, and answers over either an
  outgoing webhook or an authenticated event stream — the latter the right
  choice behind a VPN, exposing nothing. Registerable from the exposure panel
  and from the CLI (`agenticos cmd channel-add-bot`), for a deployment with no
  browser pointed at it. `api_base_url` is validated on scheme and shape so an internal
  address passes. (#41, #24)
- **A reply a chat can watch being written.** A placeholder post appears the
  moment the question arrives, grows in place — throttled to about one edit a
  second — and shows what the agent is doing while a tool runs, on Mattermost,
  Slack and Telegram through one seam. An adapter that cannot edit a message
  still posts one finished answer. (#514)
- **A per-channel prompt on the binding.** House style for a surface — how to
  lay a message out, how long to answer, which language — appended to the spec's
  instructions at run time and never substituted for them, seeded per platform
  and editable beside the environment and session-scope controls. It lives on
  the exposure row, so it never enters a client's exported YAML. (#153)
- **An agent can read the channel it is answering in** — its info and members —
  through tools granted by the binding, so "may it read what was said here" has
  a different answer on an internal server and a customer one.
- **Account linking and complete channel runs.** `/link` mints a code and
  `@slug` runs as the person who typed it; a channel run records its messages
  and the surface it arrived on, renders a chart as an image, and answers a tool
  approval in the thread that asked for it. (#10, #205, #208, #157, #152)

### Changed

- **`webhook_secret` is sealed at rest** through the vault, beside the three
  secrets that already were; the Mattermost webhook accepts the token Mattermost
  generates rather than one minted locally, while Telegram keeps minting the one
  we hand out. (#22)
- **A channel webhook hands its work over with `spawn_after_commit`**, so the
  background run sees the row the request just wrote. (#26)
- One bot serves one agent; a second binding to the same bot is refused.

### Fixed

- A failed final live-reply edit re-posts the answer whole instead of blanking
  it; "needs approval" is said only when a run actually parked; a resumed channel
  run keeps its exposure prompt and channel tools; and the chart renderer sizes a
  stacked bar to the stack rather than the tallest bar, treats a non-finite value
  as a gap, and draws in any colour Pillow accepts.

## [0.0.86] - 2026-08-09

A file dragged into the chat lands wherever it is dropped.

### Changed

- **The whole page is the drop target.** Attaching a file by dragging it meant
  hitting the composer - a strip a few centimetres tall at the bottom of the
  window - and missing it was not a no-op: the browser's default for a dropped
  file is to *open* it, so a drop anywhere else navigated the tab away from the
  conversation and whatever was half-typed in it. The same `preventDefault` that
  lets the page take the file is what stops the browser taking it, so listening
  on the window fixes both halves at once. While a file is over the page an
  overlay covers it: the ground blurred, a dashed card in the middle, and the
  per-file size limit written on it, because a 60MB video refused *after* the
  drag is a round trip nobody needed to make.

  A drag carrying anything other than files - selected text, a link, one of the
  app's own draggable rows - is left entirely alone, not even prevented. Nothing
  is accepted while the composer is disabled (an archived conversation, a run
  waiting on an approval), and the overlay not appearing is what says so.

### Fixed

- **The DataTransfer type name was in the message catalog.** The check for "this
  drag carries files" compared against a translated key, so the DOM's own
  constant `Files` sat in `en.json` as copy - and translating it would have
  stopped drag-and-drop working with nothing on screen to say why.

## [0.0.85] - 2026-08-09

Approving a tool call, and everything that was missing on the other side of it.
A run that stopped for a person, was let through, and carried on had almost none
of that written down — so the second half of a turn was a blank, and the record
of it was worse than the screen.

### Fixed

- **A continuation now says what it did.** `POST /runs/{id}/resume` executes the
  agent inside the request rather than on the socket a conversation streams, so
  its tool calls reached nobody: the response carried the answer, the status and
  the cost, and never the work. Approving a command showed nothing running, then
  asked for a second approval for a step that had never been drawn, and finished
  with a reply that accounted for neither. The response now carries the calls, in
  order, each with what came back ([#505](https://github.com/vstorm-co/agenticos/issues/505)).
- **A continuation with no answer recorded nothing at all.** The transcript wrote
  the assistant turn only when there was an answer, and a segment that runs a
  command and then parks on a second one has none — so the command it ran, its
  arguments and its result were never written. Three commands ran in a sandbox
  and history accounted for one.
- **What an approved call returned is recorded.** Its row is written open when
  the run parks; the resume that finally runs it produces the return *without*
  the call it belongs to, so nothing ever closed the row. The one call somebody
  deliberately reviewed was the one call that opened onto nothing
  ([#506](https://github.com/vstorm-co/agenticos/issues/506)).
- **One run is drawn as one turn.** A run that parks leaves several assistant
  messages — each segment written as it happens, rather than folded back into a
  turn somebody has already read — and each drew its own avatar and agent name.
  One question read as three agents answering it. Consecutive messages of the
  same run are now one turn: the avatar and the name once, at the top, and the
  time and the cost once, under the end.
- **The approval panel belongs to its conversation.** It followed the reader into
  another thread and its buttons still worked, so a call could be decided from
  under a different agent's transcript — settling a step in messages that were no
  longer loaded, with nothing on screen changing to say it had happened
  ([#507](https://github.com/vstorm-co/agenticos/issues/507)).
- **A replayed step no longer animates.** A tool call is stored as running until
  something records its outcome, and an expiry runs nothing — so the step it
  parked on stayed open and pulsed in the present tense under a conversation that
  had ended days earlier. The expiry sweep closes those steps now, and a replayed
  call still marked in flight renders as unfinished: not an error, not a success,
  the outcome nobody wrote down.

## [0.0.84] - 2026-08-09

The chat surface, seven issues deep — plus the two things a conversation could
not previously say about itself: what order a turn happened in, and what it is
waiting for.

### Added

- **A turn's order is recorded rather than reconstructed.** `messages.parts`
  (migration `0012`) stores the sequence as it was streamed — reasoning, the text
  the model wrote, and the tools it called, interleaved as they occurred. A row
  used to say *what* a turn contained and never *when*, so a client replaying one
  had to invent an order, and the only one it could invent was reasoning, then
  every tool, then the answer. A turn that introduced three charts, drew them and
  summarised them lost its introduction on save and showed the summary above the
  work it described. Null on a turn of one part and on anything written before
  this, which is a client's signal to fall back rather than render nothing.
- **Search, sort and an agent filter on the conversation sidebar**, served by the
  route rather than applied to the thirty threads already fetched. The tab counts
  are gone rather than moved: they counted what had been fetched, so a deployment
  holding hundreds read "Active 8 · Archived 2". The collapsed rail carries the
  recent threads, a search that opens with the cursor in the box, and Archived.
- **Spreadsheets can be attached and read.** `.xlsx` and `.xlsm` join the allowed
  types, parsed with `openpyxl` — every sheet named, rows tab-separated — and the
  extraction is written beside the original in a workspace exactly as a PDF's is.
  An agent cannot open a workbook: `run_python` has no filesystem and the sandbox
  has no spreadsheet library, so accepting one without parsing it would have been
  worse than the refusal it replaces.

### Fixed

- **`create_chart` drew an empty frame.** `data: list[dict[str, Any]]` reaches a
  model as an array of objects with no declared properties, so the only row the
  schema promised was valid was `{}` — which is what arrived, beside a full set of
  series, colours and axis titles. The numbers are columns now: `x_values` and one
  `values` list per series, with nothing in the signature left unsaid.
- **Tool calls rendered as raw JSON.** `web_search` and `create_chart` were renamed
  in the backend and three of four frontend files went on matching the old names.
  One table now, `lib/tool-catalog.ts`, checked against the capability registry in
  both directions by a backend test.
- **One file viewer and one file card**, everywhere. Opening a file meant four
  different things depending on where it was clicked, and showing one meant three.
- **The file viewer was served the model's read of a file, not the file.**
  `StateBackend.read` numbers every line for an agent citing one; the viewer showed
  those numbers, so Source could not be copied and an HTML preview rendered them as
  page content.
- **A parked run can be decided from the conversation it stopped in.** A resume
  that reaches a second gated call parks again, and nothing said so — the panel
  closed on a run still waiting, leaving the approvals queue as the only way to
  finish it. The resume response carries what is still parked, the panel reopens on
  the same turn, and an approved step stops saying it is waiting for approval.
- **Every message after the first was dropped on a resumed thread.**
  `persist_user_turn` called two functions without a required keyword, and the
  `TypeError` was logged as "failed to persist conversation".
- Charts open wherever they sit in a turn rather than only as the last step; a
  chart's x-axis title no longer lands on its legend; a long paste attaches as a
  file instead of filling the composer; `run_python` folds its code once output
  arrives; the reasoning block renders Markdown; and the Builder's inline
  specialists can be discarded without scrolling past six sections to find the
  control.


## [0.0.83] - 2026-08-08

### Fixed

- **The Activity page's run list and the RUNS figure only moved on a full page
  reload.** `useRuns` — read by both the RUNS figure and the Run history tab —
  carried the app-wide query defaults (`staleTime` five minutes,
  `refetchOnWindowFocus` off), so after an agent ran, the Runs tab sat at "No
  runs yet" and the RUNS count at zero beside a Spend tab that already counted
  the run, until the page was reloaded. It now spreads `DASHBOARD_FRESHNESS`
  like `useSpend`, `useUsageStats` and `useApprovals`, so returning to the tab
  refetches. The runs were written and `GET /runs` returned them throughout —
  this was only a stale client cache. (#499)

## [0.0.82] - 2026-08-07

### Added

- **Activity is rebuilt on our own rows.** `/runs` reads `agent_runs`,
  `messages` and `tool_calls`, so no panel goes blank on a deployment that never
  set `LOGFIRE_TOKEN`. Three tabs — Runs, Approvals, Spend — each owning its own
  request, loading state, empty state and retry, which is the only arrangement in
  which "nothing is waiting" and "we could not ask" stay different sentences. The
  Approvals tab is withheld whole from a caller without `approvals:decide` rather
  than shown with its buttons removed: reading the queue takes the same permission
  as deciding one, so a refused caller was reading a 403 drawn as "Nothing waiting
  — agents are running without needing you".
- **`messages.run_id`** — which run produced a turn, and what a run detail view
  is built on. Nullable, `ON DELETE SET NULL`, no backfill: deleting a run must
  not delete the transcript, and a turn written outside a run has no run to name.
  Chosen over windowing `messages` between a run's `started_at` and `ended_at`,
  which is quietly wrong — two runs in one thread interleave, so the first run's
  window contains the second's turns, and a run that never ended yields an empty
  window that reads as "nothing was recorded".
- **Nine filters on run history**, each narrowing the page and the count
  together: a *set* of statuses (`failed,budget_exceeded` is the query somebody
  actually types), surface, who it ran as, a time window, environment, exposure,
  version, "slower than", and whether anybody rated it down. Sorting by duration
  is computed in SQL over the whole narrowed set, because sorting a page of
  twenty-five sorts the wrong set — that is the gap between "p95 is 14.8s" on the
  dashboard and *those runs*.
- **Spend by provider and by key**, which a per-agent breakdown cannot answer: an
  invoice arrives from a vendor, and a leaked key is found by what was spent
  through it.
- **The role-aware dashboard** (#149): one route, one widget registry,
  twenty-seven cards. Which cards a caller gets is decided by the permissions they
  hold, never by their role name.
- **Where agents run code** (#455): sandbox capacity, sessions and runtime cards
  in that registry — how much room is left, what is running, and what the host
  allows, which are the three questions an operator has when an agent dies inside
  a container.
- **One knowledge surface** (#221): `/rag` lists the bases, `/rag/[id]` is the
  base itself, and `/kb` only redirects. Search now defaults to every base the
  caller can read instead of one collection at a time, and each result carries its
  document, page, score and which base it came from.
- **`connections:view`, so an operator can watch where sandboxes run without
  being handed the keys to them.** `connections:manage` did two jobs: reading a
  host's session list, its activity log and the memory and CPU ceilings its
  service enforces, and pointing a connection at an address and attaching the
  vault secret that starts containers there. Only owner, admin and builder held
  it, so the operator dashboard had no sandbox section at all — despite those
  reads being exactly the operator's questions ("why did that agent just get a
  429"). The reads (`GET /sandbox-connections`, `/runtimes`, `/{id}/policy`,
  `/{id}/sessions`, and the session events) now carry `connections:view`, which
  operator holds; create, edit, delete, probe, the local-service peek and the
  credential store stay on `connections:manage`. Nothing in the catalog implies
  one permission from another, so the roles that manage connections were given
  the read alongside it and lose no access.
- **Two host-wide session numerators** (#495), so all three ceilings on
  `GET /sandbox-connections/{id}/sessions` divide against something honest.
  `len(sessions)` is scoped to the caller's organization and was being divided by
  `SANDBOXD_MAX_SESSIONS` and `SANDBOXD_MAX_OPEN_SESSIONS`, both host-wide — so an
  operator under their own ceiling and still refused a session had no way to see
  the host was full of another tenant's work.

### Fixed

- **Four surfaces were recording nothing at all.** Writing the transcript was
  each surface's job and they were not equal: web chat recorded everything, a
  channel bot recorded two lines of text, and the embedded widget, a channel
  mention, the HTTP API and every resumed run recorded nothing — so an
  organization was billed for an answer given to a visitor on a client's site with
  no row saying what was asked or what was said back. It is written from
  `AgentRunnerService._run` now, the one place a non-streaming run executes,
  because a thing every surface has to remember is a thing the next surface will
  not. The write runs inside a SAVEPOINT: a failed transcript rolls back only
  itself, and the run row's status, cost and tokens still commit.
- **A streaming chat turn that did not finish threw its answer away.** A run that
  failed, hit its budget, was stopped or lost its socket never returns a
  `ChatTurn`, so the write on the success path was skipped and everything the
  model had already streamed was discarded — leaving the run in history pointing
  at a transcript holding the question and nothing else. That is the run somebody
  opens.
- **A delegate's spend was billed to its parent's vendor.** Every run in a tree
  shares one ledger, so a parent's `cost_usd` already contains its children's:
  counting every row billed the money twice, and counting only top-level rows
  totalled correctly while attributing the delegate's spend to the wrong provider
  and the wrong key. Each row now carries what it spent *itself*, which nests and
  still sums to the bill.
- **`logfire_trace_id` was null on every row ever written.** `finish()` accepted
  one from the day the column existed and no caller ever passed it, so the write
  was guarded by a condition that was always false and the field the public API
  documents as a deep link into the trace was empty. It is read at the point of
  writing now, on every path out of a run — including the failed ones, which are
  the runs somebody wants a trace for.
- **An embedded run was recorded as `web`, and a Mattermost mention as `api`.**
  Nothing errored; the numbers simply landed in the wrong bucket, and every reader
  of the column inherited it. A widget on somebody else's public site and an
  employee in the dashboard are not the same thing to anyone asking how this
  product is used.
- **The approvals queue had no stable order to page through.** `created_at` comes
  from `server_default=func.now()`, which Postgres answers with the *transaction*
  timestamp, and a run parks on all of its outstanding calls at once — so every
  call a fan-out parked shared an instant exactly, and a page boundary drawn
  through them let a row come back on two pages or on neither.
- **The count of what is waiting stopped at fifty.** `GET /approvals` answers
  fifty rows at a time and the figure drew `items.length`, so a queue of a hundred
  and twenty read 50 and went on reading 50 however long it grew. A count that
  saturates is worse than a missing one: nothing on screen looks unusual.
- **`kind` never reached a client** (#494). `SandboxConnectionService.sessions()`
  sets it on both return paths, but `SandboxSessionList` never declared the field,
  so `response_model` stripped it — and a Daytona host holding no sessions by
  design was byte-for-byte identical to an idle docker host.
- **The ratings table drew nothing at all on a failed request.** Its error state
  was folded into `empty`, and a failure leaves no rows array for the empty branch
  to fire on — so neither rendered, and an app admin reading a broken endpoint saw
  a header row over blank space with no reason to think anything was wrong.
- **The test suite resolved its Postgres password twice** (#491), with two
  different defaults, so any checkout without a `backend/.env` failed two tests
  for a reason that had nothing to do with the code.

### Changed

- **`SPEC_VERSION` is 8.** `observability.organization` and
  `observability.project` say where an agent's traces can be *read*, which a write
  token does not carry. Both optional with a default, so every stored document and
  every client's exported YAML keeps loading unchanged and there is no migration
  to write. Both are validated as slugs rather than only length-bounded: they are
  interpolated into a URL path, and a value with a slash or a query character
  would escape it.

## [0.0.81] - 2026-08-07

### Fixed

- **145 more keys came out of `messages/en.json`, and 82 of them had a
  hand-written Polish translation** — done for nobody, because nothing read the
  English either. Another 43 messages had their words written out in the source
  beside the key that held them, so the catalogue looked migrated while the
  literal stayed on screen. That is worse than an unmigrated string: the guard
  counted it as handled (#425).
- A sentence split across two keys, its tail beginning at a full stop, so neither
  half reads as copy to anything looking at one key at a time.

### Added

- Three rules, all anchored on the **catalogue** rather than the source, so none
  has to decide what a text node is — which is how two of them reach `.ts` files
  the offence sweep has never opened: a key nothing reads, a message whose words
  also sit in the source, and a value opening on `.` `,` `:` `;`.

## [0.0.80] - 2026-08-07

### Fixed

- **166 values came out of `messages/en.json`**: 18 Tailwind class lists, still
  being read back through `cn(t("…"))` so a translator opening `pl.json` was
  asked to translate CSS, and 148 fragments of JavaScript source that nothing
  read at all. The catalogue goes 2849 → 2696 (#348).
- `check_i18n.py` could not see copy passed through a prop it did not know:
  `READABLE_ATTRS` had no `noun`, so `<Pager>` took one from six call sites as a
  plain English word and rendered `3 of 40 skills` under `pl`, where no plural
  can agree with the count. The word is inside the message now (#362).
- The knowledge-base document table told a Viewer to drag in files they may not
  upload (#349).
- `SharingPanel` interpolated an English noun into five sentences and pluralised
  it with an `s` (#420).

## [0.0.79] - 2026-08-07

### Fixed

- A failed sync source was drawn exactly like a successful one. `SyncStatusBadge`
  tested `status === "failed"`, which the worker never writes — it writes `done`
  and `error` — so every finished and every failed sync fell through to the same
  grey token (#356).
- The document badge twenty lines above it was wrong the same way, and worse:
  three of its four keys (`completed`, `pending`, `failed`) are names nothing
  writes, against the service's `processing`/`done`/`error`. It had been "fixed"
  onto that wrong vocabulary once already.
- `/rag`'s status icon drew anything it did not recognise as a spinner, so a
  cancelled sync spun for the life of the page.
- The sync wizard's target-collection picker could not be reached from any of its
  three call sites, so "Add source" on `/rag` — where the tab lists the whole
  organization's sources — filed against whichever collection the sidebar
  happened to have selected, invisibly (#434).
- Creating a collection on `/rag` reported every refusal as "Failed to create
  collection", discarding the server's own message — which is what made 0.0.66's
  better 400 invisible on the only screen that creates one by name (#436).

### Added

- `frontend/src/lib/rag-status.ts` — one source for the vocabulary, naming the
  three columns that share it and what writes each.

## [0.0.78] - 2026-08-07

### Fixed

- Seven select triggers repeated a badge that only means something in the list —
  "deployment default", "not on this host" — where a comparison against the other
  options has nothing to compare against. They move into `SelectItem`'s `trailing`
  slot, which renders outside `ItemText` and so is not inherited by the closed
  trigger (#341).
- Create knowledge base could not say the embedding-model list had *failed*:
  loading and refused were the same pixels. Refused now has its own branch and
  names the default the collection will get anyway (#365).
- The runtime field lost its only warning when the badge moved, and
  `connection-dialog` saves `default_runtime` without validating it — so you could
  probe a host, pick an alias it had just refused, and save with nothing
  dissenting. An explicit line under the field restores it, and restores it for
  screen readers too, since Radix names an option by `ItemText` alone.

## [0.0.77] - 2026-08-07

### Security

- The chat's model picker created an organization-wide model profile without
  checking `connections:manage`, so anybody who could open a conversation was
  offered the form and refused by the API (#419).
- The chat's approval panel offered editable arguments and Submit to anybody a
  parked run streamed to, though deciding an approval needs `approvals:decide`,
  which neither `member` nor `builder` holds. The banner and the arguments stay,
  read-only; the controls become a sentence (#438).

## [0.0.76] - 2026-08-07

### Security

- `InlineSecret` offered a vault write at seven call sites and only one checked
  `secrets:edit`, so six of them showed the form and let the API answer 403. The
  permission is now checked inside the component, because every call site posts
  the same endpoint — a per-caller gate is one condition written seven times and
  forgotten six of them (#361).

### Fixed

- Two test fixtures answered `/me/permissions` with a list, which is a `TypeError`
  inside `usePermissions` rather than "no permissions" — so those specs had been
  passing for the wrong reason.

## [0.0.75] - 2026-08-07

### Fixed

- The admin conversations screen's Owner filter was permanently empty. Its BFF
  proxy forwarded to a route that has never existed — the path matched
  `/admin/conversations/{conversation_id}` instead, which 422'd trying to parse a
  UUID — and both admin proxies dropped `sort_by` and `sort_dir` on the way
  through (#413).
- The admin users table drew a `Role` column for a field the API stopped
  returning in migration `0066`, so it had been blank since. It now renders
  `conversation_count`, which the backend had been joining for on every page load
  and nothing read (#414).
- The skills library marked a skill uninstalled that cannot be installed, so
  Install answered 409 (#415).

### Added

- `test_bff_forwarded_paths.py` reads every `/api/v1/…` literal out of the route
  handlers and checks it against the application's own route table, in
  declaration order, validating each hard-coded segment through the field FastAPI
  would use. Over 46 forwarded paths it finds exactly one defect — the one above.

## [0.0.74] - 2026-08-07

### Fixed

- A tool call nobody decided parked its run for ever. Approvals still pending
  after their window are now swept to `expired` — recorded as a decision nobody
  made (`decided_by_user_id IS NULL`) rather than as a denial somebody issued,
  so the audit trail says what actually happened (#178).

## [0.0.73] - 2026-08-07

### Fixed

- The web chat billed nothing for the embedding calls behind a knowledge search.
  Metering lived at the call site, so a surface that forgot it under-reported
  silently: `record_ambient_usage` found no active ledger and dropped the cost,
  the run's own total was short, the organization's month never saw it, and
  nothing raised. The meter moved inside `execute` and `iterate`, so every
  surface that runs an agent is metered by construction rather than by
  remembering (#16).

## [0.0.72] - 2026-08-07

### Fixed

- The dev and production stacks notice a worker whose event loop has stopped
  turning (#358). Both were where #336 found them: `docker-compose-dev.yml` runs
  a single unsupervised uvicorn, and `docker-compose-prod.yml` runs uvicorn's
  `Multiprocess`, which pings each worker over a pipe answered by a thread — and
  a thread keeps answering while the loop is blocked, so the one stack with
  cover had cover against the least likely failure. The worker now judges its
  own loop from a thread (`app/core/watchdog.py`) and kills its own process,
  which turns a wedge into the one failure all three stacks already handle.
  Neither supervisor was replaced and PID 1 is untouched in all three.
- Ctrl+C returns from a worker that wedged *before* its first beat (#366). The
  reload supervisor escalated to `SIGKILL` on a verdict it could not reach for a
  worker that had never beaten — one hung on a Postgres that is down, say — so
  the shutdown waited out Docker's ten-second grace period instead. It now
  terminates and joins with a bound, and says which of the two it killed.

### Changed

- **`RELOAD_WEDGED_AFTER` is now `EVENT_LOOP_WEDGED_AFTER`.** It is no longer
  only the reload supervisor's: the worker's own watchdog reads the same
  variable, so one number turns the check off for a debugging session rather
  than leaving one of the two judges running to kill it.

## [0.0.71] - 2026-08-07

### Fixed

- Ingestion and sync flows were spawned before the transaction that wrote the row
  they read had committed, so a flow could start, look for its own document row
  and not find it — an upload answered `processing` that stayed that way.
  `spawn_after_commit` queues the work on the session and `_managed_session`
  starts it two statements after `commit()` (#417).
- `rag-source-sync` cancelled the sync it had just reported starting: `asyncio.run`
  kills pending tasks on the way out (#439).
- `POST /rag/documents/{id}/retry` queued nothing and cleared the error message,
  so a retry was a one-way trip into permanent `processing`. A bare `ValueError`
  on a decided refusal is now a 400 rather than a 500 (#441).


## [0.0.70] - 2026-08-07

### Fixed

- A write was answered before its transaction committed, so the next read could
  miss it. `get_db_session` commits in the exit code of a `Depends`-with-`yield`,
  and FastAPI unwinds that stack **after** the response has been written — so a
  2xx said the request had been handled, not that the write was readable. One
  keyword argument, `scope="function"`, moves the commit in front of the response
  (#353).
- A failed request now rolls back before the error response is built rather than
  after it, because the exception unwinds the same stack. A caller could be told
  404 while the partial write causing it was still open.
- A failed health probe left the session's transaction aborted, which on the new
  ordering turned an intended 503 into a 500 — on the endpoint an operator reads
  when something is already wrong (#416).


## [0.0.69] - 2026-08-07

### Fixed

- Admin user and conversation search did not escape `LIKE` wildcards, so a caller
  typing `%` or `_` changed what the query meant rather than searching for it: `_`
  matched any single character and `%` matched everything, which is a wrong-rows
  bug and a cheap way to make an admin listing scan far more than it should. All
  three sites now go through one helper on SQLAlchemy's `icontains(autoescape=True)`
  (#372).
- Admin listings sorted on nullable columns without ordering nulls, so the emptiest
  rows led page one (#411).

### Removed

- `escape_sql_like` in `core/sanitize.py` — dead, and half-right in a way that
  would have been worse than nothing had anything called it.


## [0.0.68] - 2026-08-07

### Security

- An app admin's password reset was written to the audit trail in plaintext. The
  request body was dumped into `app_admin_audit_logs.details`, so resetting a
  password recorded it (#412).
- A refusal's `details` described the server rather than the refusal: an upstream
  client's exception text on a 503, container filesystem paths on a 500, and a
  provider base URL echoed back on four validation errors — one of which exists
  *because* the URL carries a password. The diagnosis moves to the log; the
  response names the field that explains the refusal (#342).
- A sandbox address could carry userinfo, which `probe_policy` echoed into both
  the response and the log. `ServiceAddress` was the only one of the three URL
  validators not refusing credentials.

### Fixed

- The capability registry echoed a rejected configuration back to the caller in a
  400, unlike the identical call one module over.


## [0.0.67] - 2026-08-07

### Security

- A failed ingest stored a vendor SDK's exception text in `rag_documents.error_message`
  and the dashboard rendered it. An embedding or vector-store client's message can
  carry an endpoint, a key fragment, a bucket name or an internal host — and stored,
  that is a durable leak read later by whoever looks at a failed upload, rather than
  the transient one 0.0.38 closed on the HTTP path. Nine sites now record the stage,
  the exception **type** as a symbol, and what to do about it; the text goes to the
  worker log (#423).

### Fixed

- The outermost ingestion handler overwrote the innermost one's message, so a parse
  failure — the commonest path — reported "could not be ingested" rather than "could
  not be read". Harmless while all three wrote the same `str(exc)`; not harmless once
  the innermost knew which stage had failed.


## [0.0.66] - 2026-08-07

### Security

- `POST /kb` accepted any `collection_name` and never claimed it, so a member with
  `collections:edit` could point a knowledge base at another organization's vector
  table and read and write it through every gate that followed. `claim` had
  exactly one call site, the `/rag` route (#367).
- A collection name over 45 characters truncated onto another collection's table.
  The bound is derived from the longest identifier built from a name —
  `rag_<name>_embedding_idx`, not `rag_<name>` — so a name of 46 to 59 characters
  truncated only the *index* name, `CREATE INDEX IF NOT EXISTS` then found the
  first collection's index and built nothing, and the second collection searched
  unindexed at the first one's width (#368).
- Upper case is refused. Postgres folds an unquoted identifier, so `Handbook` and
  `handbook` were two rows, two collections the platform believed distinct, and
  **one physical table** holding both tenants' vectors — #368's defect reached by
  another route. Refused rather than normalised: this branch's argument is that an
  unusable name is turned away, not silently rewritten into something the caller
  never typed.

### Fixed

- A malformed or reserved collection name answers 400 rather than 500 (#371).
- Dropping a collection whose name the new rules refuse no longer swallows the
  refusal and orphan the vector table.


## [0.0.65] - 2026-08-07

### Security

- A Drive file whose name is a path escaped the sync directory. A remote filename
  is attacker-controlled from this system's point of view — anyone who can share
  a file into a synced folder chooses it — so the write target is now **resolved
  and confirmed** to be inside the directory rather than sanitised by
  substitution, which makes `..`, its encodings, homoglyphs and a pre-existing
  symlink one question instead of a blacklist that is always one entry short
  (#370).
- A sync source's `folder_id` was interpolated into the Drive query unescaped.
  It is now allowlisted where the query is built — the single funnel both the
  configured folder and every recursed sub-folder pass through, so rows written
  before the check are covered too — and asked again by every route that stores a
  config, not only by create (#369).
- Two deployment-wide credential fallbacks removed. A tenant's `folder_id` or
  `bucket` could widen a query running under the **operator's** identity, which
  turns one field of a source's own configuration into a reach across
  organizations. The S3 case was the worse of the two: both settings default to
  empty, so the fallback resolved to `None` and boto3 fell through to the
  container's own credential chain.

### Changed

- The write target is now `BaseSyncConnector.download_file`'s decision, with
  connectors implementing `_fetch`. A connector added later cannot choose a path,
  and a test asserts none overrides it.


## [0.0.64] - 2026-08-07

### Fixed

- Every JSON response the platform proxy returns now declares a cache policy. It
  carried none — no `Cache-Control`, no `ETag`, no `Last-Modified` — on every
  mutable collection on the surface, and silence is not "do not cache": a 200
  with no policy is one the browser may reuse on its own judgement. Every answer
  here depends on a cookie, a permission set and an organization header, so there
  is nothing on this surface a shared or heuristic cache may keep. A backend that
  does name a policy still wins, which is how the catalog icons and the embed
  bundle keep theirs.


## [0.0.63] - 2026-08-07

### Fixed

- A stacked pull request ran no CI at all, and its checks list was empty rather
  than red. `ci.yml` triggered on `pull_request: branches: [main, master]`, which
  matches on the **base**, so a branch opened against another branch matched no
  trigger — and an empty check list reads as "still running" rather than "nobody
  looked". Four pull requests merged that way in one day, each verified only
  locally. The trigger no longer filters on the base (#359).
- `docs/file-processing.md` described a platform-admin RAG model this project
  replaced: "any authenticated user can search any collection", "only admins can
  manage them". All three claims were false, and the same paragraph sat under its
  own heading in `docs/architecture.md`, which a search for "only admins" misses
  because that copy reads `Only **admins**` (#354).

### Changed

- Every CI job now carries a `timeout-minutes`, each several times its measured
  runtime. Only `changes` had one, so a hung job ran to the platform default
  rather than to a number somebody chose (#364).


## [0.0.62] - 2026-08-07

### Fixed

- None of the ten cases around `mask_generics` in the i18n guard's test file
  tested it: stub the function to `return text` and all ten still passed, while
  the guard then reported three false positives over the real tree. It was
  load-bearing and untested, so a refactor could have broken it with only a
  tree-wide `make lint` to notice. One case now fails without it.


## [0.0.61] - 2026-08-07

### Security

- `h2` bumped past CVE-2026-71554.


## [0.0.60] - 2026-08-07

### Fixed

- `main` did not pass `make lint-backend`. Two ruff findings — `RET501` and a
  `RUF100` for a `noqa` naming a rule this project does not select — arrived with
  PRs merged during the GitHub Actions outage, when every check sat `pending` and
  nobody could see them. Because the pre-commit hook runs `ruff check . --fix`
  over the whole tree regardless of what is staged, it kept rewriting those two
  files into unrelated commits and rolling them back, so every branch cut from
  `main` started red on a gate it had not broken (#407).


## [0.0.59] - 2026-08-06

### Fixed

- `tests/test_migrations.py` ran for the first time. It needed a database called
  `agenticos_migrations_test`, a missing one became a module-level skip, and
  nothing in the repository ever created it — so the only assertions that
  `downgrade()` works at all reported "4 skipped" into a green build on every CI
  run this project has ever had (#234). The module creates that database before
  its first test and drops it after its last, with the process id in the name so
  two runs on one machine cannot drop each other's mid-upgrade (#346).
- A remaining skip now means one thing only: no Postgres answered. Under `CI` it
  is not a skip at all but a failure, because a declared service container that
  did not come up is not a laptop without Docker.
- The probe says *why* the server did not answer. A Postgres that is up and
  refusing — a wrong password, a database in recovery — used to be reported as a
  container that never started.


## [0.0.58] - 2026-08-06

### Fixed

- `make install` did not create `backend/.env`, the third thing a fresh checkout
  is missing. Everything running on the host reads it — `db-check`, `db-upgrade`,
  `run`, and pytest through `app.core.config` — so without one
  `POSTGRES_PASSWORD` is empty and `alembic check` is refused with
  `fe_sendauth: no password supplied`, four minutes into `make check`. It is
  copied from the example, once, and an existing file is never overwritten (#299).
- `REDIS_PASSWORD` carried a live placeholder in the example. Copied into a dev
  `.env` it made every request fail against a local redis that has no
  `requirepass`, and in a deployed stack it let `change-me-in-production` be
  inherited from an example file. It is commented out in both directions now,
  and the deployed compose files already refuse to start without a real one.
- The empty `SANDBOXD_TOKEN=` in the example did not match the `^SANDBOXD_TOKEN=.`
  that `make dev` greps for, so a fresh checkout ended up with the key twice and
  worked only by last-wins. The assignment is gone; the comment stays.


## [0.0.57] - 2026-08-06

### Fixed

- `make install` did not install the frontend toolchain, so a fresh checkout
  could not run `make check` at all: eslint, prettier, tsc, vitest and next live
  only in `frontend/node_modules`, and the first four minutes of `check` are the
  backend half, so it said `eslint: command not found` well after you had walked
  away (#227).

### Changed

- `test_ci_parity.py` now holds the setup commands to the mirror-image rule: a
  gating job may prepare its runner however it likes, as long as `make install`
  prepares a laptop the same way. The next toolchain CI adds has to land in
  `install` or be exempted with a written reason.
- `make quickstart` no longer claims to install dependencies in `docs/commands.md`.
  It is `quickstart: dev`, and nothing in that chain reaches `install` — which
  sent people down exactly the road this release closes.


## [0.0.56] - 2026-08-06

### Changed

- The last four route handlers that read a repository directly now go through a
  service, which is what `.claude/rules/architecture.md` has always asked for:
  the audit listing, a knowledge base's sync logs, an org integration's sync
  logs, and the vault key a provider catalog is fetched with (#232).
- `AuditService` is new. The `/audit` route held "an entry belongs to exactly one
  organization" as a keyword argument it filled in itself, which is a scope no
  service test can see and one the next reader of that entity would have had to
  know to repeat.
- Both surfaces showing a sync source's history read it through
  `SyncSourceService.list_logs` rather than each carrying its own query and its
  own copy of the same twelve-field mapping.
- The provider-listing key moves out of a private helper in the route and into
  `OrganizationSecretService`, so nothing in the HTTP layer unseals a secret.


## [0.0.55] - 2026-08-06

### Fixed

- The reserved-names integration test set the vector store's resolver to `None`,
  which stopped being valid in 0.0.43 when the resolver became required and its
  `None` short-circuit was deleted. `_for_collection` calls it unconditionally,
  so the test raised `TypeError: 'NoneType' object is not callable` on every run
  with a real database. Shipped in 0.0.45 and fixed here.


## [0.0.54] - 2026-08-06

### Fixed

- A knowledge base's sync history came back short. The route read every log
  carrying that source id, applied `limit` in SQL, and only then dropped the rows
  belonging to another collection — so the page was cut before the thinning. A
  source repointed at another base (`SyncSourceUpdate` carries
  `collection_name`, and earlier runs keep the name they ran against) made a
  request for twenty runs answer with fewer, `total` described the survivors
  rather than the source, and there was no way to page past the gap. The source
  is resolved against the base first now (#233).
- A source that is not this base's answers `404` rather than `200 []`. Both
  rendered "no syncs yet", and one of them was a request that should have failed.


## [0.0.53] - 2026-08-06

### Fixed

- The double-backtick guard skipped every directory called `worktrees`, which was
  the wrong rule twice over: it silently stopped reading a `docs/worktrees/` that
  is only a directory with a name, and it still walked a git worktree placed
  anywhere else. It now detects a nested checkout — a `.git` file or directory —
  and declines to descend into it, which is what the rule always meant (#225).
- The self-exemption matched one absolute path, so every copy of the script under
  a worktree was reported as three findings on a line nobody had edited. It
  matches the file's name now, and `--fix` is safe on a copy for the same reason.


## [0.0.52] - 2026-08-06

### Fixed

- `scripts/check_i18n.py` skipped any line containing `=>`, because a type like
  `(() => Promise<void>) | null` reads as a text node to a regex — and an inline
  handler is the most common thing on a JSX line, so the exemption was far wider
  than the problem. It also matched nothing when a text node spanned two lines,
  which the formatter does freely. The guard now masks generics rather than
  skipping the line, and reads interpolation rules over the whole file (#314).
- 55 strings across 30 files that those two blind spots had been hiding,
  including two menu items sitting between translated siblings, and English
  compiled into the two model-picker components (#332).


## [0.0.51] - 2026-08-06

### Fixed

- `scripts/check_i18n.py` walked past two shapes of hardcoded copy: a sentence
  that begins with a word before its interpolation, and a count built with a
  lambda rather than an ICU plural. Both render in English under any locale, and
  `make lint` reported clean over them (#249).


## [0.0.50] - 2026-08-06

### Fixed

- The embedding Model select in Create knowledge base never showed its value —
  it said "Loading models…" for as long as the dialog was open, while the list
  below it was populated. Radix writes the new value onto a hidden native select
  and dispatches `change` before the items have registered their options, so the
  value read back was empty and clobbered the state. This is the one choice in
  the dialog that cannot be revisited, since a collection's embedding width is
  frozen at creation (#328).
- The agent builder offered the add-model form to anyone who could open it,
  though submitting needs `connections:manage`, and the store-a-key form inside
  it never checked `secrets:edit`. A control the caller may not use is not
  rendered (#329).
- Two buttons in the same dialog were both called "Add a key" while writing
  different secrets. By accessible name they were indistinguishable, so a screen
  reader heard the same button twice (#331).


## [0.0.49] - 2026-08-06

### Changed

- Every place a provider or a provider key is chosen now draws the same row —
  brand mark, name, an optional masked hint. Choosing an embedding key in Create
  knowledge base offered bare strings while the agent builder three clicks away
  drew the mark, and the two did not look like the same product. Ten pickers
  converge on one primitive, including two that had hand-copied the row and one
  where two different keys rendered as the same line (#304).

### Fixed

- A provider mark's `<title>` was being used as its option's type-to-search key,
  so every model in Create knowledge base answered to `openrouter…` rather than
  to its own name.
- The tick marking a stored key was inherited by the closed select's trigger,
  where it reads as "selected" rather than "has a key".


## [0.0.48] - 2026-08-06

### Fixed

- The **Describe images** model control in Create knowledge base was the agent
  builder's picker rendered in its lesser branch: a bare radio list, with no
  provider/model/key form, no way to say whether the chosen profile can
  authenticate at all, and — on a deployment with no saved profiles — a dead end
  offering no way out of itself (#305).

### Changed

- `ModelProfilePicker`'s `allowAdd` meant two things at once: show the form, and
  offer the bin on every saved row. They are now `allowAdd` and `allowRemove`.
  The knowledge-base dialog gets the first only, so it can create a model and a
  key but cannot destroy an organization-wide profile that agents point at. The
  current-model line, which is what says a profile has no key, renders in both
  shapes.
- The add-model form in that dialog is gated on `connections:manage`; it posts a
  model profile, and a control the caller may not use is not rendered.


## [0.0.47] - 2026-08-06

### Fixed

- The knowledge-base detail page stated the size of the page the table had
  loaded, not the size of the collection. A collection holding fifty-seven
  documents said "20 documents" under its own title, and pressing Load more made
  the number climb, which reads as ingestion happening rather than the page
  correcting itself. The document count now reads the collection's total; the
  vector count says plainly that it counts what is loaded, until everything is
  (#324).
- Nine strings in the knowledge-base pages rendered in English under any locale —
  single words below the guard's threshold, text nodes alone on a line, copy
  behind an `&&`, and a schedule read as "every 30m". Two of them are counts and
  are now ICU plurals (#325).
- Drag-and-drop upload compared a translated string against the browser's
  `DataTransfer` type. Under Polish that comparison could never match, so
  dropping a file would have done nothing.

### Changed

- A Tailwind class list was being stored in `messages/en.json` and read through
  the translator, so a translator opening `pl.json` was asked to translate CSS.


## [0.0.46] - 2026-08-06

### Changed

- A knowledge base is deleted from its own page, not from the card in the list.
  The only control used to be a hover-revealed trash icon sitting on top of a
  whole-card link — the most destructive action on the resource, one mis-aimed
  click away from opening it, on the surface that shows least about what is
  about to be destroyed. It is now in the detail page's actions menu, behind
  `collections:edit`, behind a confirmation naming the collection and its real
  document count, and it is not offered for the default collection, which the
  server refuses (#303).
- The three `window.confirm` calls in the knowledge-base pages are proper
  confirmation dialogs with translated copy. A raw `confirm()` argument is
  hardcoded English the i18n guard cannot see.

### Fixed

- Both delete dialogs now disable while the request is in flight. A double-click
  sent a second DELETE and toasted a 404 over a removal that had worked.


## [0.0.45] - 2026-08-06

### Fixed

- A collection could be named after a model table. `_table("documents")` derives
  `rag_documents`, which is the table tracking every organization's ingested
  documents, so `GET /rag/collections/documents/info` returned every
  organization's document count and the delete path issued a `DROP TABLE`
  against it. Nothing refused the name, and `documents` was the *default*
  collection name, so the collision sat on the documented first-run path. Both
  the store and `KnowledgeBaseService.create` now refuse a name that collides
  with a declared model table (#345).

### Changed

- The default collection name is now `default`, one constant shared by the four
  `rag-*` commands and two schemas, pinned by a test that fails if it is ever
  set to a model table's name. `RAGSettings.collection_name` was read nowhere
  and is deleted.


## [0.0.44] - 2026-08-06

### Fixed

- `PgVectorStore.list_collections()` reported a collection called `documents`
  that does not exist. It matched every table by name prefix, and `rag_documents`
  — the model table tracking ingested documents — matched. The listing has held
  that phantom on every deployment since the table existed, and `rag-stats`
  reported the row count of that tracking table as a vector count. Collection
  membership is now decided by `is_runtime_vector_table`, the same predicate
  alembic uses, so the two answer from one source (#339).
- The prefix match also treated `_` as a SQL wildcard, so a table named
  `ragXfoo` listed as a collection called `Xfoo`.


## [0.0.43] - 2026-08-06

### Fixed

- Document ingestion ignored the collection's own embedding key and model. The
  worker built its vector store with no resolver, so the collection's
  `embedding_secret_id` — validated and stored when the collection was created —
  was never read. On a deployment with no `OPENROUTER_API_KEY` this crashed with
  advice to set one; where both were set it was worse than a crash, billing the
  deployment's account while the UI said the organization's key paid. The
  collection's recorded model was ignored the same way, so a collection could be
  indexed by one model and searched by another (#306).
- The three ways key resolution can silently fall back to the deployment key —
  a missing secret row, an unseal failure, the wrong kind — now reach the flow
  log the operator reads, and the error names the collection and which key it
  tried.

### Changed

- `resolver` is now required on `PgVectorStore` rather than defaulting to `None`.
  Five call sites passed it and one forgot; the default is what made forgetting
  silent.


## [0.0.42] - 2026-08-06

### Fixed

- `make db-check` failed on any database that had ingested a document. Alembic
  compared the models against the live schema and saw the per-collection vector
  tables the RAG store creates at runtime, which no migration declares, so it
  reported drift that no migration could ever resolve (#288).

### Added

- `app/db/vector_tables.py` — `is_runtime_vector_table`, one predicate for
  "is this table a runtime vector table rather than a declared model", read from
  `Base.metadata` rather than from a name pattern.


## [0.0.41] - 2026-08-06

### Fixed

- The local supervisor replaced a worker that had died but ignored one that was
  alive and not answering — deadlocked on a lock, spinning, or blocked on a
  socket that never replies. Such a worker has no exit code, so the supervisor
  saw a healthy child and did nothing while the container served no requests.
  The worker now stamps a monotonic beat from uvicorn's `callback_notify`, and a
  worker silent across two consecutive polls is replaced (#336).

### Added

- `RELOAD_WEDGED_AFTER` — how long a worker may go without running its event
  loop before it is treated as wedged. Set it to `0` under a debugger.


## [0.0.40] - 2026-08-06

### Fixed

- When the kernel killed the reloader's worker in the local stack — an OOM kill
  being the realistic way — nothing reaped it and nothing replaced it. PID 1
  stayed alive, so the container reported `Up`, Docker's restart policy never
  fired, and every request timed out with no log line because the process that
  would have written it was gone. A supervisor now replaces a worker that dies,
  the way uvicorn already does on the `--workers` path (#308).

### Added

- `backend/cli/reload_supervisor.py`, a dedicated entrypoint. It deliberately
  does not import the application: routing PID 1 through `cli.commands` cost
  464 MB against 28 MB, which is the whole application inside the one process
  whose job is to survive an OOM kill.


## [0.0.39] - 2026-08-06

### Fixed

- `prefect-runner` had never once passed a health check and never could. It runs
  the backend image, which carried a `HEALTHCHECK` written for the API, and the
  runner serves no HTTP. A status that is red unconditionally is not a status: a
  dead runner looked exactly like a live one, and nothing could depend on it
  becoming healthy. The runner now serves Prefect's own `/health` on 8080 and is
  probed against it (#310).
- The API's own probe passed on a 500 — it fetched the health endpoint and
  ignored the status. It now raises for status, with a 30s start period.

### Changed

- The `HEALTHCHECK` moved out of `backend/Dockerfile` and into the `app` and
  `prefect-runner` service definitions in all three compose files. An image with
  two consumers should not assert what only one of them can satisfy.


## [0.0.38] - 2026-08-06

### Fixed

- A domain exception carrying a `UUID` in its `details` was delivered as a bodiless
  500 instead of the refusal it described. `JSONResponse` serializes with plain
  `json.dumps`, which cannot encode a `UUID`, so the exception handler raised on
  the way out — after it had already logged the refusal, which is why the log and
  the response disagreed. A browser session kept across a database reset hit this
  on every `GET /api/v1/auth/me`. All three response-building handlers now encode
  `details` through `jsonable_encoder` (#307).
- The capability registry echoed a rejected configuration back to the caller in a
  400, unlike the identical call one module over.

### Changed

- `.claude/rules/exceptions-security.md` showed `details={"user_id": str(user_id)}`,
  which contradicted both the code and `architecture.md`. Domain exceptions pass
  the value; the encoder handles it. The one exception, money, says why.


## [0.0.37] - 2026-08-06

### Fixed

- The `ai-review` workflow concluded `success` when it had produced no review at
  all, and posted "the reviewer did not produce a result" — a sentence that reads
  like a verdict on the diff. Eleven pull requests merged unreviewed before anyone
  noticed. A run is now classified `reviewed`, `declined` or `broken`; `broken`
  fails the job and the comment says the reviewer failed, carrying what Codex
  printed. A cancelled run no longer reports the reviewer as dead, and a broken
  re-run no longer deletes the previous run's inline findings (#311).

The cause of the Codex failure itself is an enforced spend limit on the OpenAI
project, recorded on #311. The `pull_request` trigger stays off until that is
lifted.


## [0.0.36] - 2026-08-06

### Fixed

- The end-to-end suite's `[seed]` project asserted the colleague's membership
  with a single read. When it lost, Playwright skipped everything that depends
  on the fixture and reported the whole suite red having exercised no product
  code at all — three times in one day, on unrelated branches. The step now
  polls the API and, when it does give up, prints what it actually saw
  (#335).

The underlying cause is filed rather than fixed: this backend answers a write
before the transaction commits, so a 2xx says the request was handled and not
that the write is readable (#353).


## [0.0.35] - 2026-08-06

Nothing in this release changes what the product does. It changes what CI costs,
which had reached about 8,900 billed Actions minutes in the first six days of
August across 369 runs at 24.1 minutes each
([#317](https://github.com/vstorm-co/agenticos/issues/317)).

### Changed

- **A push to a branch now cancels that branch's run in flight.** `ci.yml` carried no
  `concurrency` block at all, while `ai-review.yml` and `docs.yml` both did — so every
  push started a fresh matrix and left the previous one running to completion. 75 of
  369 runs were superseded while still in flight, about 1,800 billed minutes, and only
  2 runs in that window were ever `cancelled`. A push to `main` is exempt, and via
  `github.run_id` rather than `cancel-in-progress: false`: `false` means *queue*, and
  GitHub cancels any previously **pending** run in a group when a newer one is queued,
  so a third merge arriving would have cancelled the second and left that commit with
  no CI at all.
- **`test`, `test-frontend` and `e2e` are skipped when the changed paths cannot affect
  them.** A `changes` job decides, and the decision lives in
  `scripts/ci_changed_scope.py` rather than in a glob, so it is testable. It skips a
  suite only when *every* changed path is provably irrelevant to it — an unrecognised
  path runs everything — because the permissive spelling of the same idea would let a
  new directory silently stop a suite, which is a green build with a gate missing from
  it rather than a red one. A required status check is satisfied by `success`,
  `skipped` **or** `neutral`, which is why this is a job-level condition and not a
  `paths:` filter: a filtered-out workflow never posts its checks, and the ruleset
  would wait forever. See [branches](docs/branching.md#a-required-check-may-legitimately-report-skipped).
- **Dependencies are cached, at all seven install sites.** `setup-uv` was called five
  times with no cache, re-resolving and re-downloading all 278 locked packages each
  time; `setup-bun` caches the binary and not the packages; and `e2e` downloaded about
  170 MB of Chromium on every run. All three are keyed on the lockfile that pins them.

### Fixed

- **Four ways the new path gate could have passed on nothing**, all found in review of
  the change that introduced it and all the failure it was built to prevent. A
  `changes` job that *failed* skipped every gated suite without its condition being
  read, and since a skipped required check is a pass and `changes` is not itself a
  required context, one API error would have turned the merge button green over a
  branch where nothing ran — each gated job now carries `!cancelled()`. A rename was
  half-invisible, because `pulls/{n}/files` reports only the path a file arrived at, so
  a module moved out of `backend/` skipped the backend suite; `previous_filename` is
  fed through as well. And the `changes` job declared `pull-requests: read` without
  `contents: read`, which a job-level block *replaces* rather than adds to — working
  only for as long as this repository stays public.

## [0.0.34] - 2026-08-06

### Changed

- **The automated reviewer no longer runs on a pull request**
  ([#311](https://github.com/vstorm-co/agenticos/issues/311)). Every `ai-review` run since
  2026-08-05 evening died about twelve seconds into its Codex step with `codex exited with code 1` —
  the shape of an authentication, quota or entitlement refusal at the first API call rather than a
  model working and failing — and then concluded `success` and posted "No review: the reviewer did
  not produce a result", a sentence that reads like a verdict on the diff. Eleven pull requests
  merged with no automated review before anybody noticed, three of them releases. A reviewer that
  runs and says nothing is worse than one that plainly is not running, so the `pull_request` trigger
  is removed until the Codex failure is understood; `workflow_dispatch` stays, because the fix has
  to be testable against a real pull request. Adding the `ai-review` label now does nothing at all.
  `CLAUDE.md` and [code review](docs/code-review.md) say so, and the latter records that its own
  "a failed run says so" claim is what #311 disproved — making a failed run *report* as a failure is
  the second half of that issue and is not done.

## [0.0.33] - 2026-08-06

### Fixed

- **The Prefect runner no longer starts every queued flow run at once.** `aserve` declares
  `limit: Optional[int] = None` and hands that straight to `Runner(limit=...)`, where `None` means
  *no cap* — while constructing a `Runner` without the argument falls back to Prefect's own default
  of five. Calling `aserve(*deployments)` and saying nothing was therefore the one spelling that
  removed the ceiling entirely. Starting the stack after three days of downtime, the runner found
  the backlog of once-a-minute `rag-sync-check` runs and started 71 `prefect.engine` processes at
  once — each a fresh interpreter importing the whole application, about 120 MB apiece. 6.02 GiB of
  a 7.75 GiB host, and the kernel resolved it by OOM-killing the API container's worker.

### Added

- **`PREFECT_RUNNER_LIMIT`** (default `5`) — how many flow runs execute at once; the rest queue. A
  memory ceiling rather than a throughput dial, and the moment it matters is the restart after
  downtime rather than the steady state. Documented in
  [configuration](docs/configuration.md#background-work-prefect).

## [0.0.32] - 2026-08-06

### Fixed

- **A dynamic specialist's definition is now owned per delegation, not keyed by name**
  ([#292](https://github.com/vstorm-co/agenticos/issues/292)). What each specialist a model
  invented was built from rode a single per-run store keyed by the specialist's name, and the build
  factory overwrote it on a repeat. Two `delegate` calls in one turn with the same name but
  different instructions — which Pydantic AI may run concurrently — both wrote that one entry, so
  whichever delegation opened its panel later stamped the *other* specialist's definition onto its
  `SubagentStarted` frame, and the chat's "Promote to a draft agent" control ([#177](https://github.com/vstorm-co/agenticos/issues/177))
  then carried someone else's instructions and model. Each `delegate` now owns its own copy; the
  name-keyed store is kept only for the `create_agent` specialists a `task` reaches by name, which
  are one-per-name and cannot collide. Narrow and self-inflicted — no cross-tenant or permission
  impact.

## [0.0.31] - 2026-08-06

### Changed

- **The chat "Promote to a draft agent" control now pre-validates the model-chosen name**
  ([#293](https://github.com/vstorm-co/agenticos/issues/293)). A dynamic specialist's name is
  whatever the model chose, and the delegation library allows names the backend `SpecialistSpec`
  rejects — its pattern (`^[a-zA-Z0-9_-]+$`) and its 64-character limit. The chat control passed
  that name straight to the promote request, so an over-long or oddly-punctuated one failed with a
  raw 422 surfaced as an error toast — for a name nobody can edit in chat. The control now disables
  and shows the reason when the name would be refused, the same guard the Builder's specialist
  editor already puts on its own promote button.

## [0.0.30] - 2026-08-06

### Added

- **Promote a specialist to a draft agent — the honest way to keep one**
  ([#177](https://github.com/vstorm-co/agenticos/issues/177)). A dynamic specialist is
  never persisted (keeping one means publishing an agent, a person's action), and an inline
  specialist lives only in its parent's spec — so the only way to keep either was to copy
  its instructions out of a chat log, producing an agent whose provenance nobody can see.
  A **Promote to a draft agent** action now sits on an inline specialist in the Builder's
  delegation section and on a dynamic specialist in the chat delegation panel while the run
  that created it is still on screen. It creates an ordinary **draft** from the specialist's
  instructions, model profile, capabilities, collections and skills, through the same
  `SpecialistSpec.to_agent_spec()` conversion — and stops there: it does not publish, does
  not pin the new agent as a delegate of its parent, and does not remove the inline
  specialist, each of which stays a decision the author makes next with the usual validation
  in front of it. The draft is owned by **the person who promoted it** and subject to the
  usual `AGENTS_EDIT` check — a specialist created inside someone else's run does not become
  their agent. A promoted dynamic specialist publishes without further editing and answers,
  when run, what it answered inside the run it came from.

## [0.0.29] - 2026-08-06

### Fixed

- **An inline specialist's spend under a published delegate now reaches an agent's month**
  ([#228](https://github.com/vstorm-co/agenticos/issues/228)). Spend attribution (0.0.7,
  #192) stamps every `SpendEntry` with the delegation that booked it and reads a
  delegation's cost as its share of the ledger — but an inline specialist gets no
  `agent_runs` row, only published delegates do. So an inline `fact-checker` under a
  published `researcher` booked its spend to its own key, which is in no run row, and the
  innermost stamp meant it was not in the researcher's share either: on a $0.75 run the
  researcher's row read $0.50, and $0.25 reached no agent's month. The organisation total
  was always right (the top-level row is the whole ledger), which is why nothing failed.
  An entry now carries a second attribution — *who spent it* (for the delegation panel's
  own-share `cost_usd`) and *which agent row it bills to* (for the month): an inline
  specialist bills to its nearest published ancestor, so that row is whole again while the
  panel still shows the specialist's own share, with nothing double-counted. Holds through
  an inline specialist nested under another inline specialist, too.

## [0.0.28] - 2026-08-06

### Fixed

- **A `create_agent` specialist created by a nested delegate survives an approval park**
  ([#254](https://github.com/vstorm-co/agenticos/issues/254)). 0.0.20 (#175) carried a
  top-level dynamic specialist across a park — its definition serialised into `paused_state`
  and re-seeded on resume through the same factory — but only at the root. A specialist a
  delegate *one level down* created was still lost when a nested delegation parked and
  resumed: the nested level's registry was rebuilt empty, so `task` answered "unknown
  subagent" for it. The specialist carry now descends the parked tree, so a kept specialist
  at any depth is re-seeded on resume and reachable by name, metered on the run's shared
  ledger exactly as it was the first time. `max_agents` still bounds each level, so a resume
  cannot exceed it by rebuilding.

## [0.0.27] - 2026-08-05

### Fixed

- **A delegation panel closes when an approved resume's continuation raises**
  ([#262](https://github.com/vstorm-co/agenticos/issues/262)). The panel reconciliation
  from 0.0.16 (#173/#250) closed an awaiting panel from the resumed run's status — but only
  when the resume *returned* one. If the continuation raised, `AgentRunnerService._run`
  recorded the run `failed`/`cancelled` and re-raised, so `POST /runs/{id}/resume` returned
  no result, the frontend skipped reconciliation, restored the already-decided approval, and
  left the panel on `awaiting_approval` forever — with a retry then refused because the run
  was already terminal. The resume route now conveys the recorded terminal status even on
  the raising path, without swallowing the failure the caller still sees, so the panel
  reaches `failed`/`cancelled` and the spent approval is not restored.

## [0.0.26] - 2026-08-05

### Added

- **The agent map is interactive, and shows delegates as their own nodes**
  ([#126](https://github.com/vstorm-co/agenticos/issues/126)). The map — the read-only
  picture of "what is this agent, in total?" — now draws delegation. A published delegate
  (pinned, navigable), an inline specialist (no page of its own), and a pin the
  organization no longer has or the caller cannot see (named as unreachable rather than
  dropped) each render as a distinct kind of node — an agent, not a tool — grouped under a
  Delegation heading and edged to the hub by the same measured layout the capabilities use.

  And it is a control now, not a picture: every node is a focusable button, click or
  Enter/Space lights its edge and dims the rest and opens a detail panel, Escape or a click
  away clears it, and a published delegate's panel links through to *that* agent's page — so
  the delegation tree is walkable one hop at a time. It stays read-only (the forms own the
  fields) and keeps pan/zoom. Rendering the tree recursively inline is a deliberate
  follow-up, [#276](https://github.com/vstorm-co/agenticos/issues/276).

## [0.0.25] - 2026-08-05

### Changed

- **`ruff` now lints `alembic/` and the guard scripts, and the dead ignore is live again**
  ([#229](https://github.com/vstorm-co/agenticos/issues/229)). `ruff` was only ever invoked
  on `backend/app` and `backend/tests`, so `backend/alembic/` and the repository-root
  `scripts/` (the three guards — `check_backticks.py`, `check_i18n.py`, `docs_drift.py` —
  that gate every PR) were never linted, and the `per-file-ignores` entry for `alembic/**`
  silenced rules on files ruff never read. `make lint-backend` and both pre-commit ruff
  hooks now run `ruff check . ../scripts` from `backend/`, so all three trees are linted and
  the config stays one definition across make, pre-commit and CI (`test_ci_parity.py` still
  holds). No genuine code defects surfaced: `alembic/` was already clean, and the 21
  findings in `scripts/` are legitimate patterns relaxed with a documented reason (`T201`,
  since printing is the guards' purpose; `S603`/`S607`, the same literal-argv `git`
  invocation already accepted for the migration test). The `alembic/**` ignore is kept and
  now genuinely live, covering autogenerated migrations' downgrade stubs and raw
  `op.execute` SQL. A model edited without a migration — `x == 2` under `alembic/versions/`
  — is now refused where the old command passed it silently.

## [0.0.24] - 2026-08-05

### Fixed

- **A parked run whose spec no longer builds stays resumable**
  ([#176](https://github.com/vstorm-co/agenticos/issues/176)). `resume` flipped the run to
  `RUNNING` before fetching and building its spec, and `claim_parked_run` only claims a run
  in `AWAITING_APPROVAL` — so if the build then failed (a secret a binding named was
  deleted, a model profile removed, a capability dropped in a deploy, an MCP connection
  unshared), the row was stranded in `RUNNING` and could never be resumed again, with a
  person's approval recorded against work that would not continue and nothing reporting it.
  The spec is built first now, and the run is marked `RUNNING` only once the build has
  succeeded; a build that raises leaves the run `AWAITING_APPROVAL`, so the same approval
  can be resumed once whatever the spec named is restored.

## [0.0.23] - 2026-08-05

### Fixed

- **The E2E suite runs beside another checkout's dev server**
  ([#223](https://github.com/vstorm-co/agenticos/issues/223)). `playwright.config.ts`
  hardcoded ports 3000 and 4010, so the suite could not start when a `make dev` or a second
  checkout already held them. The frontend port now derives from `E2E_PORT` (default 3000)
  and the stub model server's from `E2E_STUB_MODEL_PORT` (default 4010), driving `baseURL`,
  both `webServer` URLs, each server's `PORT`, and — the part that has to agree — the stub
  URL the specs write into the model profile the backend dials, so server, specs and backend
  all read one value. Same shape as #189: the value is *derived* from the environment, not
  `setdefault`, so CI is exercised on the new path rather than silently left on the old one.
  The loopback binding is kept, so the host-uvicorn path works and the containerised-backend
  constraint is not falsely implied.

## [0.0.22] - 2026-08-05

### Added

- **A sync delegate can ask the person already waiting on its parent**
  ([#184](https://github.com/vstorm-co/agenticos/issues/184)). An author can turn on
  questions for a delegation, so a **sync** specialist can ask "which currency?" of the
  person waiting on the parent run instead of burying an assumption in its answer —
  answered through the run's own `ask_user` channel, the same one the parent uses. It is
  off by default and gated tightly, because the reasons this was once declined are real:
  a **background** delegation has handed back a task id with nobody waiting, so it is never
  granted the ability (nor is an `auto` delegation, which may become one); a specialist a
  model invented at run time is never granted it either; and a surface with no `ask_user`
  (the API, a channel, a schedule) refuses rather than hangs. The library injects
  `ask_parent` for a caller-supplied delegate only since `subagents-pydantic-ai` 0.2.17,
  which is why this rides on the 0.2.18 floor adopted in 0.0.21.

  Concurrency came with it: two delegate questions in one turn would race the single
  `ask_user` channel, so the channel is serialised — the same class of fix as the approval
  writes in 0.0.17, and for the same reason.

## [0.0.21] - 2026-08-05

### Changed

- **Adopt `subagents-pydantic-ai` 0.2.18, which fixes the general-purpose delegate at the
  source** ([#174](https://github.com/vstorm-co/agenticos/issues/174)). The delegation
  library used to default its `default_model` to a hardcoded string, so a consumer with no
  usable default — which AgenticOS is, on purpose: there is no deployment-wide model — got a
  general-purpose delegate that either failed or, worse, ran one tenant's work on whatever
  provider key happened to sit in the process environment. AgenticOS had already removed the
  switch from its own surface (0.0.7) and refuses a modelless dynamic specialist in
  `DelegatingToolset._refuse_dynamic`; 0.2.18 removes the fallback upstream too, so the
  library now refuses a modelless dynamic call of its own accord rather than compiling an
  unmetered one. The pin moves to `>=0.2.18` and the local comments and the capability
  reference are corrected to describe the removed fallback in the past tense. `#174` closes
  now that AgenticOS is on the fixed version.

## [0.0.20] - 2026-08-05

### Fixed

- **A `create_agent` specialist survives the approval park that interrupts it**
  ([#175](https://github.com/vstorm-co/agenticos/issues/175)). A specialist the model
  writes at run time is documented as lasting for the reply, but it did not survive a
  *second* approval park: the library's dynamic-agent registry belongs to the built agent,
  and a resume rebuilds the agent fresh, so `task` answered "unknown subagent" for a
  specialist the model was told it could keep. The specialist's definition — a name,
  instructions, a model — is now carried in the run's `paused_state` alongside the spend,
  timings and approval rows already kept there, and a resumed turn re-seeds the registry
  through the same factory, so the specialist arrives with the run's shared budget guard
  and approval channel exactly as it did the first time. `max_agents` still bounds how many
  one run may keep, so a resume cannot exceed it by rebuilding. This survives within one
  run; a dynamic specialist is still never persisted across runs — keeping one past its run
  means promoting it to a published agent, which is a person's action.

## [0.0.19] - 2026-08-05

### Added

- **An offline audit of the skill bindings a published version can no longer reach**
  ([#186](https://github.com/vstorm-co/agenticos/issues/186)). Publish-time validation
  (0.0.8, #179) stops a *new* version binding a skill its publisher cannot see, but a
  version published before that check keeps loading whatever its spec named — so a
  published agent may be reading another member's private skill right now, and nothing
  reported it. `agenticos cmd audit-skill-bindings` sweeps every **runnable** published
  version — not just each agent's current pointer, but versions a non-terminal run will
  resume on, reached through the delegation pin-closure — and names the agent, the version,
  the skill and the publisher for each binding that publisher could not reach today.

  Two edges it gets right, because an audit that cries wolf is one an operator learns to
  ignore: the pin-closure honours `max_depth`, so a binding only an unreachable grandchild
  holds is not flagged; and a disabled skill, or a delegate whose agent has been archived,
  is dropped rather than reported, since neither can actually load. A version whose
  publisher has since been **deleted** is a third answer, not "reachable" or not — the
  report says so, because `published_by_user_id` is `SET NULL` and an operator needs to
  know the difference. It **reports**, never unbinds: taking a skill off a published
  version would change what a published agent does without anyone deciding, which is the
  opposite of what publishing means here.

## [0.0.18] - 2026-08-05

### Fixed

- **A run count is an ICU plural, and the guard that missed it now catches the shape**
  ([#199](https://github.com/vstorm-co/agenticos/issues/199)). A run count was built as
  `"{n} runs"` — a plural only English forms that way — and `scripts/check_i18n.py`, the
  gate whose whole job is to refuse exactly that, passed over it. Both halves are fixed:
  the count is now `{count, plural, =1 {1 run} other {# runs}}` with the component passing
  `count`, and the guard is closed so the next English-only plural is refused rather than
  merged. A guard verified only by a green suite is a guard nobody has tested, so the
  change writes the offending shape into a fixture and confirms the script rejects it.

## [0.0.17] - 2026-08-05

### Fixed

- **Two gated tool calls in one model step no longer race the request's session**
  ([#169](https://github.com/vstorm-co/agenticos/issues/169)). A gated tool call writes an
  approval row, and pydantic-ai runs the tool calls from one model response
  *concurrently* — so an agent with two gated tools, answering one step with both, hit
  `db.add` + `flush` on the request's shared `AsyncSession` from two coroutines at once,
  and `AsyncSession` is not concurrency-safe: the damage reaches the parent run row and the
  conversation, not just the approval. Delegation widened the window, since a sync delegate
  keeps the parent's channel. The approval rows are now queued during the run and written
  once when it parks — the shape delegation already took for its child run rows — so nothing
  writes to the session mid-run. A run whose model emits two gated calls in one step parks
  once naming both, with two rows of distinct ids and a session still usable for the
  terminal write.

  Two follow-ups the write path surfaced, both fixed here. A delegate **deleted** between
  the park and the deferred write no longer breaks the park: the write first locks the
  delegates still present, and a parked call whose delegate is gone is written with a null
  `subagent_agent_id` (the `SET NULL` foreign key) rather than a reference that would fail
  the insert and roll the parked run back — the approval survives and a person can still
  decide it; only the delegate attribution, which no longer exists, is dropped. And the
  lock that holds the surviving delegates takes `FOR KEY SHARE` rather than
  `FOR NO KEY UPDATE` (`with_for_update(read=True, key_share=True)`), so it blocks a
  concurrent delete without also blocking an ordinary agent update.

## [0.0.16] - 2026-08-05

### Fixed

- **A delegation panel reaches a terminal state when its delegate parked on an approval**
  ([#173](https://github.com/vstorm-co/agenticos/issues/173)). When a sync delegation
  parked for a human approval in web chat, its panel showed the delegate as still working
  and stayed there — because `POST /runs/{id}/resume` runs over HTTP with no
  `subagent_events` sink, so no `subagent_complete` frame ever reached the WebSocket
  reducer, and the panel sat on `awaiting_approval` forever after the approval was granted.
  Web-chat resume doesn't stream, so the panel is now reconciled from the HTTP answer: the
  resumed run's own status is applied to every panel still awaiting — `completed`,
  `failed`/`budget_exceeded`→failed, `cancelled` — while a resume that parks *again* is
  left waiting, preserving the continuation case. Streamed text is kept; cost and tokens
  stay null rather than invented, since the frame that carries them never arrived. This
  covers a resume that **returns** a status; a resume whose continuation itself raises
  returns no result and still leaves the panel waiting, tracked as
  [#262](https://github.com/vstorm-co/agenticos/issues/262).

## [0.0.15] - 2026-08-05

### Fixed

- **A sync-only delegating agent is no longer offered the background-task tools**
  ([#185](https://github.com/vstorm-co/agenticos/issues/185)). An agent configured
  `mode: "sync"` can never have a background delegation, yet its model was still offered
  the six tools that only make sense for one — `check_task`, `wait_tasks`,
  `list_active_tasks`, `send_message_to_subagent`, and both cancels. Six tool descriptions
  in every turn's context for actions that cannot happen, and tool descriptions are the
  strongest prompt surface in this product. This is the same defect class as
  [#182](https://github.com/vstorm-co/agenticos/issues/182) (0.0.8) and extends its
  mechanism: the offered set is now computed per run. The six tools are withheld only from
  an agent that can never reach a background delegation — mode `sync`, no delegate whose
  `preferred_mode` is `async` or `auto`, and dynamic specialists off; anything that could
  still produce a background delegation (an `auto` agent, or an `auto`-override on a
  delegate, or an enabled dynamic-specialist path) keeps all of them, since the model
  decides per delegation there. A dedicated test pins the exact tool set each of those
  configurations is offered; the capability drift table is unchanged and does not itself
  catch this, since its widest fixture is background-capable by construction.

## [0.0.14] - 2026-08-05

### Changed

- **`alembic check` is a usable gate again**
  ([#183](https://github.com/vstorm-co/agenticos/issues/183)). It had failed on `main`
  for reasons unrelated to any change under test — index-naming drift from early
  migrations that the models and the migrations disagreed about — so the one command that
  would catch "somebody edited a model and forgot the migration" could not be run, and it
  hid real drift behind noise a reader had to filter by hand. The drift is resolved (the
  models and migrations now agree on the index names), and `alembic check` is wired into
  both `make check` and CI, on both sides of `tests/test_ci_parity.py`, so it stays green
  rather than rotting again. This is the fourth check to have existed and not run — after
  `make check` equalling CI (#143), spelling over the tree (#188) and the CodeQL config
  (#220) — and, like those, the value is in the check running at all.

## [0.0.13] - 2026-08-05

### Fixed

- **`bootstrap` ensures the model profile it names, rather than adopting any it finds**
  ([#172](https://github.com/vstorm-co/agenticos/issues/172)). On a database that had
  been used before, `make platform-bootstrap` adopted whatever model profile already
  existed instead of ensuring the one it was told to create — so the agent it published
  ran on a profile nobody asked for, and several E2E specs that assume the named profile
  failed on any database not freshly created. It now ensures the profile it names,
  creating it when absent and matching by name when present, so a second bootstrap is
  idempotent rather than dependent on what the database happened to hold.

## [0.0.12] - 2026-08-05

### Fixed

- **A delegated run's recorded time span survives an approval park**
  ([#191](https://github.com/vstorm-co/agenticos/issues/191)). A delegated `agent_runs`
  row reads its span from the library's `TaskHandle`, which is correct for a single-turn
  delegation — but one that parks on an approval and resumes runs in two processes, and
  the resume rebuilds a fresh handle stamped at the *resume*, so the row began when the
  person answered and dropped the entire pre-park segment. The earliest start is now
  carried across the park the way spend is (0.0.8, #180): `ParkedDelegation` holds it,
  `paused_state` serialises it, and the resumed turn folds it back in — the span is the
  first segment's start and the last segment's end, and unlike cost the segments are not
  summed. A pre-task refusal, which finds no handle, still writes no row at all.

### Changed

- **Run-history routes read through the service, not the repository**
  ([#197](https://github.com/vstorm-co/agenticos/issues/197)). A route reaching
  `agent_run_repo` directly is one of this codebase's named hard boundaries, and it was
  crossed here — which is not merely stylistic: a route that reaches the repository
  bypasses wherever the service puts the tenant scope, so the next filter added to the
  service is one a hand-written route keeps its own answer to. `list_runs` now scopes to
  the caller's organization inside `AgentRunnerService`, the one tenant boundary the rest
  of run history already reads through, and the delegated-run parameters added in 0.0.11
  (`parent_run_id`, `include_delegations`) thread through it rather than sitting in the
  route.

## [0.0.11] - 2026-08-05

### Fixed

- **Run history can tell a delegated run from one a person started**
  ([#181](https://github.com/vstorm-co/agenticos/issues/181)). The columns
  (`parent_run_id`, `subagent_task_id`) had existed since delegation landed and nothing
  read them, so a fan-out turn listed as several independent runs and a page that summed a
  column double-counted every delegation — a parent's cost already contains its children's.
  `AgentRunRead` now carries both, and withholds the delegation handle whenever the parent
  is gone (a foreign key can only null its own column, so `subagent_task_id` outlives the
  delete that nulls `parent_run_id`); `list_runs` filters `parent_run_id IS NULL` for the
  history list, and answers the run-detail query — "what did this run delegate" — by
  `parent_run_id`, which is the lookup the migration's index was speculative weight for
  until it had one.

  A delegated run is **badged** in the table and reachable from its chat panel, so the
  fan-out reads as one tree rather than a list of strangers. The monthly sums keep the
  existing `(organization_id, started_at)` index, with the null test applied to rows it
  already found.

## [0.0.10] - 2026-08-05

### Fixed

- **The E2E seed no longer depends on a product bug to pass**
  ([#132](https://github.com/vstorm-co/agenticos/issues/132)). Five sites created a row
  through a dialog and then asserted it was on screen, with no wait on the write that put
  it there; four flaked, and three branches paid a diagnosis for it in one day. Two causes,
  both now removed from the test's path. An open Radix dialog takes the rest of the page
  out of the accessibility tree, so `getByRole` resolved to nothing while the dialog was up
  and the assertion reported `element(s) not found` for a refusal it never looked at — a
  shared `submitDialog` waits on the write's own network response instead, and through the
  client's transparent 401 retry so it matches the request that settled rather than the one
  that was retried. And a **fixture** step now asserts through the API, never on the row
  appearing, because the refetch after a write is sometimes answered the pre-write list —
  which is a real product bug ([#230](https://github.com/vstorm-co/agenticos/issues/230)),
  left open, not a broken fixture.

  A failing `[setup]` or `[seed]` step is a Playwright *project dependency*, so its failure
  skips every product spec — the log reads "1 failed, 7 passed, 17 did not run" and looks
  like a product regression. `e2e/fixture-reporter.ts` now prints a banner saying exactly
  that, so the next reader does not spend the diagnosis a fourth time.

## [0.0.9] - 2026-08-05

### Fixed

- **Five WebSocket frames the frontend declared but no backend surface sends**
  ([#195](https://github.com/vstorm-co/agenticos/issues/195)). `use-chat.ts` and
  `WSEventType` named `llm_started`, `llm_completed`, `todo_event`, `context_usage` and
  `context_compacted` — two with live `case` arms and a test asserting a dead branch
  behaves. That is [#144](https://github.com/vstorm-co/agenticos/issues/144) in the
  opposite direction: #144 was the frontend matching tool names the backend had stopped
  sending; this is frames it never started. With `app/services/agent_session.py` now fully
  covered and in the gate (0.0.8, #165), the set of frames a surface actually emits is
  knowable exactly — none of the five is among them, on the dashboard socket, the channel
  surface or the embed. The union members, the `case` arms, the payload interfaces and the
  test for the dead branch are gone, along with two per-event interfaces whose field names
  disagreed with the wire (`TextDeltaEvent.data.delta` for the wire's `content`,
  `ToolResultEvent.tool_name`/`result` for `tool_call_id`/`content`).

## [0.0.8] - 2026-08-05

Everything that landed after delegation and before the next feature: the branches that
were stacked behind it, plus two more the same work surfaced. Nearly all of it is a defect
delegation created or uncovered, and several are about a check that reported green while
the thing it checked went unchecked.

No schema change, `SPEC_VERSION` unchanged at **7**.

### Fixed

- **A delegation's recorded cost is its own, not the run around it**
  ([#180](https://github.com/vstorm-co/agenticos/issues/180)). Cost was measured as the
  growth of the run's shared ledger between the delegation starting and being settled — and
  a **background** delegation is settled when it is next *polled*, which is arbitrarily
  later than it finished. So a delegate that spent $0.01 while the parent went on to spend
  $0.50 was recorded at **$0.51**, on its own run row, in its monthly total and in the
  delegation panel.

  Every `SpendEntry` now carries the delegation that booked it, and a delegation's cost is
  its share of the ledger rather than a window over it. That also fixes the second half:
  a mid-tree delegate no longer counts what its own delegates spent.

  `has_unpriced_models` travels with the share and survives an approval park, so a row
  cannot claim a precise cost for a delegation that had an unpriced request before the
  approval.

- **A cancelled run is recorded cancelled, and the row survives**
  ([#171](https://github.com/vstorm-co/agenticos/issues/171)). `_run` caught
  `BudgetExceeded` and `Exception` but not `CancelledError`, which derives from
  `BaseException` — so a cancel passed straight through with the status left at its initial
  `FAILED`, and because a propagating `BaseException` skips the session's auto-commit, even
  that write rolled back and the row stayed `RUNNING` forever. It now records
  `CANCELLED`, commits explicitly, and keeps the tokens already spent — the streaming
  surface had this right and said so in a comment the non-streaming path did not follow.
  Delegation reaches this path too, so a cancelled delegation now keeps its cost rather
  than losing it.

- **`skill_ids` is validated at publish, at both levels**
  ([#179](https://github.com/vstorm-co/agenticos/issues/179)). It was the one reference a
  spec could make that publish never checked — and skills carry grants that nothing
  enforced, so a publisher whose role gives `SKILLS_VIEW: Scope.SHARED` could bind another
  member's **private** skill by UUID and every runner of that agent then read its body.
  Refused now, with the same deliberately indistinguishable "not found" wording the
  collection check uses, so ids stay unprobeable. Versions published *before* the check are
  a separate problem, tracked as [#186](https://github.com/vstorm-co/agenticos/issues/186).

- **A delegation tool nothing could reach is no longer offered**
  ([#182](https://github.com/vstorm-co/agenticos/issues/182)). `answer_subagent` exists so a
  parent can answer a question its delegate asked, and no delegate here can ask one — the
  library injects `ask_parent` for neither a configured delegate nor an autonomous
  specialist. So it was a tool description in every delegating agent's context, on every
  turn, for an action that cannot happen; tool descriptions are the strongest prompt surface
  in this product.

  It stays **declared** — a tool absent from a capability's `tools=` can be neither gated nor
  renamed, and that half of the failure is silent — and the drift test now subtracts an
  explicit table rather than skipping the capability. Seven tools are offered, nine under
  `allow_dynamic`, ten declared.

### Changed

- **The chat wire format is behind the coverage gate at 100%**
  ([#165](https://github.com/vstorm-co/agenticos/issues/165)). `app/services/agent_session.py`
  decides every frame the dashboard WebSocket sends and every frame it accepts, and it was
  in **neither** the coverage nor the `ty` include list — 63% covered, with `process_message`
  and both terminal `complete` frames untested. Every surface reads this format, so a frame
  renamed here is a frontend branch that silently stops matching, which is
  [#144](https://github.com/vstorm-co/agenticos/issues/144) exactly.

  Now 100% of 194 statements and 72 branches, in both lists, with 56 tests that assert the
  frame that reached the socket rather than that a method was called. The author
  mutation-tested it — 19 mutations, every frame name renamed, both terminal flags flipped,
  the disconnect re-raise swallowed — and all 19 were caught, because 100% coverage is a
  claim about lines executed and not about tests that would notice.

  Two dead branches came out with it, one of which would have silently dropped the frame
  carrying a run's answer had it ever been reachable.

- **CodeQL's false positives no longer block a merge by hand**
  ([#220](https://github.com/vstorm-co/agenticos/issues/220)). `github-code-quality` posts
  each alert as a review thread, and the ruleset requires every thread resolved — so one
  idiomatic pattern (`py/ineffectual-statement` on a bare `await <task>`, which suspends and
  re-raises and is the whole point of the statement) cost eight hand-written replies on a
  single pull request, with no `.github/codeql/` config in the repository to tune it. There
  is one now, suppressing only what is demonstrably wrong for this codebase's idioms and
  leaving everything else reporting — the inverse of #188 and #203, which were checks looking
  at too little. `docs/code-review.md` now documents the CodeQL half: how alerts arrive, that
  they gate through the ruleset, and where the config lives.

## [0.0.7] - 2026-08-05

**Delegation.** An agent can hand work to named specialists instead of carrying every
intermediate result in one context — and three checks that existed and did not run were
made to run, which is how two of the defects below were found.

`SPEC_VERSION` is unchanged at **7**: every field delegation adds is optional with a
default, so a spec stored before it reads unchanged. Two migrations,
`0007_delegated_runs` and `0008_approval_delegate`, both additive and both reversible.

### Added

- **Delegation** ([#40](https://github.com/vstorm-co/agenticos/issues/40)). Two kinds, and
  the difference is deliberately visible rather than smoothed over:

  - a **delegate** is a published agent **pinned to a version** — permission-checked at
    publish, with its own capabilities, model and collections. A pin whose version is gone
    fails the run and names the delegate; never a quiet fall back to the current version,
    because the point of pinning is that nothing changes without somebody deciding.
  - an **inline specialist** carries its own bindings but is **not versioned**: nothing can
    reference it, and editing the parent changes it.

  What makes something an agent here is versioning, a permission check at publish, its own
  capabilities, and being metered and capped. A specialist has three of the four, and the
  one it lacks is the version — which is the whole design, and why there is one spec type,
  one validator and one builder used recursively rather than a second agent format.

  A delegation streams into its own collapsible panel per task, so a fan-out is legible
  rather than a quiet gap in the transcript; a gated tool inside a delegate parks the run
  and **resumes in place** rather than re-running the delegation; `sync`, `async` and `auto`
  modes with the task-lifecycle tools; and a model may invent a specialist at run time
  behind `allow_dynamic`, built through the same `build_agent` everything else goes through
  so its requests are priced and counted.

  Cost is the part worth reading twice. One run has **one spend ledger**, and every delegate
  records into it — which is what makes the parent's cap see a delegation's spend before its
  next model request, at precisely the moment delegation multiplies what a turn can cost. So
  the caps that bind inside a delegation are the parent's. A delegation to a published agent
  also gets an `agent_runs` row of its own carrying `parent_run_id`, and the two monthly
  questions want opposite arithmetic: what the organization owes excludes child rows, what
  *one agent* cost includes them.

### Fixed

- **A delegate's own knowledge collections never reached the running delegate**
  ([#166](https://github.com/vstorm-co/agenticos/issues/166)). The delegation library runs a
  child on `clone_for_subagent` of the *parent's* deps, so the deps our factory built for it
  — collections and all — were discarded before its first request. A delegate configured
  with a collection resolved it, never saw it, and answered "No active knowledge bases
  selected" to every search while looking correctly configured.

- **Three spend aggregates double-counted a delegated run**
  ([#170](https://github.com/vstorm-co/agenticos/issues/170)), and one of them was emailed
  as the organization's bill. On a $1.00 run of which $0.40 was a delegate, the bill read
  $1.00 and three breakdowns read $1.40 — with the delegate's $0.40 appearing under two
  vendors at once.

- **The liveness probe reported version `1.0.0` from every deployment**, however many
  releases it was behind. `GET /api/v1/health/live` read
  `getattr(settings, "VERSION", "1.0.0")` against a setting that has never existed, so the
  fallback was the only answer it ever gave — and the `getattr` is what made it silent
  rather than an `AttributeError` on the first request. It now reports `app.__version__`,
  the same source OpenAPI and the CLI already read.

  Found by the automated reviewer on this release's own pull request, which is the right
  place for it: the one claim a release makes is that the version is the same everywhere.
  The test that should have caught it is named `test_liveness_probe_reports_the_build` and
  asserted the status and the environment — everything except the build.

- **Every integration run gets a database of its own**
  ([#189](https://github.com/vstorm-co/agenticos/issues/189)). `tests/integration/conftest.py`
  called `drop_all` against a fixed database name, so two suites at once dropped each
  other's tables — two runs of the same commit produced *different* failure sets, which is
  the signature of a race rather than a bug. Four people lost time to it in one day. The
  name now carries the pytest process id, created and dropped by the fixture; both safety
  rails are kept and one added.

### Changed

- **`make check` now runs every job CI runs**
  ([#143](https://github.com/vstorm-co/agenticos/issues/143)). It was documented as "what CI
  runs" and ran about half: `bun run build`, `pip-audit` and `mkdocs --strict` had no local
  equivalent at all, and eslint, prettier and `tsc` sat outside `make lint`, so it passed on
  a branch with a type error in a `.tsx`. One divergence ran the other way and is the
  sharper one — the i18n check was local-only, so a pull request could merge an
  untranslated string in a product whose frontend rules lean on that script.

  Fixed structurally rather than by copying commands: the workflow calls the Makefile's
  targets, and `backend/tests/test_ci_parity.py` asserts both directions, so a job added to
  one and not the other fails the suite.

- **Spelling is checked over the tree, not over the files a commit happens to touch**
  ([#188](https://github.com/vstorm-co/agenticos/issues/188)). One misspelling was sitting
  on `main`, waiting for whoever next opened that file for an unrelated reason. Exactly one
  existed once the scope was right, verified two ways — the per-file scope had not
  accumulated a backlog, it was hiding one word and would have gone on hiding the next.
  `.codespellrc` now records that omitting the `en-GB_to_en-US` dictionary is deliberate:
  this repository writes "behaviour" on purpose.

## [0.0.6] - 2026-08-04

Dependencies only. No behaviour change, no schema change, `SPEC_VERSION` unchanged
at 7 — this is here so the version literals and the lockfiles move together rather
than drifting until somebody notices.

### Changed

- **TypeScript 5.9.3 → 6.0.3** (dev). A major, so it was checked rather than
  assumed: `tsc --noEmit`, `eslint --max-warnings 0`, the coverage gate and
  `next build` all pass with no source change.

  Dependabot bumped `frontend/package.json` and left `bun.lock` alone, which two CI
  jobs would have refused — they run `bun install --frozen-lockfile`, and that fails
  outright when the manifest and the lock disagree. The lock is updated here, so the
  next such bump should be checked for the same omission.

- **ruff 0.15.0 → 0.16.1** (dev). Ruff is the formatter as well as the linter, so a
  new rule or a changed format would have turned `make lint` red *after* the merge
  rather than before it. `ruff format --check` reports 476 files already formatted
  and `ruff check` passes, so nothing in the tree needed touching.

- **boto3 1.43.59 → 1.43.62.**

## [0.0.5] - 2026-08-04

**Every sign-in lands on the dashboard**, and a deep link interrupted by the login
form is resumed rather than dropped.

### Changed

- **One post-sign-in destination, decided in one place.** Password sign-in forked
  on `is_app_admin`, the OAuth callback always went to `/dashboard`, and the magic
  link always to `/chat` — three call sites that each decided on their own and
  disagreed, so which door somebody came through decided where they landed.
  `postSignInDestination()` in `src/lib/auth-landing.ts` is now the only answer.

  The default is the same for every role on purpose. What a role may not see is
  handled by not rendering the widget, never by a different landing page — a role
  fork there quietly splits one product into two.

- The mobile tab bar's Home tab targets `/dashboard` for every role, and its unused
  `useAuth` dependency is gone.

### Added

- **`?returnTo=` survives the login round trip.** `AuthGuard` appends the path it
  refused when it sends a visitor to `/login`, and the visitor resumes there after
  signing in instead of being dumped on the dashboard having lost where they were
  going.

  Deliberately not for OAuth: that needs the `state` parameter round trip, and the
  flow is being rewritten separately.

### Security

- **The `returnTo` guard refuses anything off-origin**, so the login form cannot be
  turned into an open redirect. Two checks, both load-bearing: a pattern that
  demands a single leading slash, and an origin comparison after parsing. The
  pattern alone misses control characters, because the URL parser strips tab, LF
  and CR before parsing — so `/<tab>/evil.example` resolves off-origin. The origin
  check alone would accept a bare relative path like `agents`, which resolves
  against wherever the visitor happens to stand.

  Refused values are not sanitised into something safe. A fixed-up open redirect is
  still an open redirect, so anything suspect falls back to the dashboard.

## [0.0.4] - 2026-08-04

**An agent can have a workspace: files, and on a container-backed host a shell.**
`SPEC_VERSION` is unchanged at 7 — `capabilities` is an open list, so adding an id
is additive and every published agent keeps loading.

### Added

- **The `sandbox` capability.** Seven tools — `ls`, `read_file`, `glob`, `grep`,
  `write_file`, `edit_file`, `execute` — over one of two backends. `state` stores a
  JSON document in this database and needs no infrastructure, which is what makes
  the feature real on a default install; `service` runs a container or a cloud
  sandbox on a connection an operator registered.

  `code_execution` stays. The two are not a subset of each other: it computes with
  no infrastructure anywhere, and `state` has no shell at all, so an agent granted
  both computes with one and remembers with the other.

- **`backend` is infrastructure; `session_scope` is a data-sharing policy.**
  Getting the first wrong costs a feature. Getting the second wrong shows one
  person another person's files — so `agent` scope warns at the field, the file
  panel names whose workspace it is, and setting it is recorded in the audit log.

  The spec never names an image, a mount, a network mode or a ceiling. A spec is
  authored in a browser by anyone holding `edit` on an agent, and one that could
  name a container image could name one whose entrypoint mounts the host.

- **Attachments stop being context and become data.** A file used to be parsed and
  pasted into the message, at its full token weight on every turn forever, and a
  50 MB CSV could not be attached at all. With a workspace it is written to
  `/uploads/` and the model gets a reference plus twenty lines. Images go both
  ways under a ceiling: a path is no substitute for looking at a picture, and
  looking at one is no substitute for being able to resize it.

- **Sandbox connections**, with their credentials in the vault — a per-organization
  row rather than a deployment setting, which is what makes two hosts possible and
  what bills a Daytona sandbox to the organization that opened it.

- **Read-only workspace routes and a browser.** Folders, whole-tree search,
  previews and downloads. A container-backed workspace is read off the host volume,
  so a week-old conversation lists its files after its session was reaped.

- **A file panel in chat**, beside the transcript, and a Workspaces page scoped per
  reader — an operator sees the organization's, everybody else sees their own files
  and the shared workspace of an agent they have talked to.

- **`sandboxd` runs beside the app** and is the only service holding the Docker
  socket, which is the whole reason an agent can have a container while this
  application has no Docker access. Never published, its own dashboard off,
  reaching the daemon by supplementary group rather than as root.

### Changed

- **Approval is per tool.** `sandbox` is the first capability that genuinely reads
  *and* writes, and one flag cannot describe it: marking the capability
  side-effecting makes an agent ask permission to list a directory, and not
  marking it lets a write run unattended. `CapabilityToolInfo.side_effecting`
  overrides the capability's answer per tool — additive, `None` defers, every
  existing capability behaves exactly as before.

  Only `execute` is gated. Writing into scratch space deleted with its
  conversation is not the act sending an email is, and an agent that must ask
  before every write cannot do multi-step work at all.

- **The ruleset denies, the platform asks.** The library ships `allow`/`deny`/`ask`,
  and its `ask` is an in-run `await` that dies with the socket, while this
  platform's persists a row, mails somebody and parks the run. So `"ask"` never
  comes from the ruleset, with `ask_fallback="deny"` as the backstop.

- **Requires `pydantic-ai-backend>=0.2.25`**, which fixes three things this
  repository had worked around: a ruleset's per-path rules are enforced by the
  library (and it also filters `grep` and checks a command's path arguments),
  `WorkspaceArchive.read_bytes` serves a file a decode would have ruined, and
  `stop(purge=...)` means the same thing on every backend.

- **Attachment routing moved out of the WebSocket into the chat runner**, because
  where a file goes depends on whether the agent has a workspace and only
  `prepare` knows that. Every surface behaves the same instead of the WebSocket
  owning the only implementation.

### Fixed

- Paths an agent may not touch are refused: credentials (`**/.env`, `**/*.pem`,
  `**/.ssh/**`) and the system tree. A `grep` cannot return a line from one, and a
  command naming one is refused.
- A Daytona sandbox is deleted when its run or its conversation ends. It used to
  be deleted on neither, once per run, on the organization's own cloud account.
- A workspace is keyed on the host it runs on, so moving an agent between
  connections opens a new one instead of reattaching to a row naming the host it
  has left.
- Writes are capped at the call site rather than at the flush. Refusing later
  accepted the write, reported success to the model, and dropped the run's work in
  a `finally` block while the agent kept reasoning about a file that was never
  kept.
- A file too large to store is named and sampled rather than pasted whole — the
  fallback used to run backwards, since a write is only refused for a file too big
  to paste.
- The chat file panel is always reachable, and lists what people attached as well
  as what the agent wrote. It used to appear only once a workspace row had been
  flushed, so it was absent for the whole of a turn parked awaiting approval.
- Approving a parked call shows the resumed answer. `POST /runs/{id}/resume`
  executes the agent and returns its output; the chat discarded it, so an approval
  looked like it had done nothing until the page was reloaded.

### Security

- Every secret at rest goes through the vault, including the sandbox service token
  and a Daytona key. There is no second mechanism.
- A workspace file served inline gets an opaque origin, `nosniff`, a CSP sandbox
  and `filename*` only — `.svg` and `.html` are never inline, because "the agent
  wrote it" is not a trust boundary.
- The address a client asks the platform to probe is validated, so a holder of
  `connections:manage` cannot turn the API container into a fetch proxy for
  anything on its network.
- A user id is hashed rather than sanitised when it keys a workspace. Dropping the
  characters a session id forbids mapped `a.b` and `ab` onto one workspace, which
  is one person reading another's files.

## [0.0.3] — 2026-08-02

A frontend release, and almost all of it is about one thing: what a browser is
still holding when the account or the organization changes underneath it.

### Security

**One tenant's data could reach another tenant's screen, and one account's could
reach another account's.** Nothing here crossed a server-side boundary - every
refusal the backend makes it still made - but the browser kept and re-showed
answers it had already been given, which for a multi-tenant product is the same
outcome by a different route.

- **Uploads went to the wrong organization.** `ingestFile` sent no
  `X-Organization-Id`, and the backend reads a request without it as the
  caller's personal organization - so uploading into a collection whose name
  exists in both wrote the file to the wrong tenant and reported success under
  the right one. The one *write* across the boundary in this list.
- **Switching organization changed a label and nothing else.** Most query keys
  name no organization, so with `staleTime` at five minutes one tenant's agent
  names, knowledge bases, secrets and conversations stayed on screen under
  another's. Everything cached is dropped on a switch now - dropped rather than
  marked stale, and before the paint rather than after it.
- **Signing out left the previous account's data in memory.** The query cache
  and the Zustand stores both survived a sign-out, so the next account signing
  in on the same browser could be served the previous one's conversations,
  agents, and the device names and IP addresses on their profile. Emptied when
  the signed-in account changes, keyed on the account rather than on the act of
  signing in - a password login, an OAuth callback, a magic link and the
  dashboard's own auth check are four different doors, and only one of them was
  covered.
- **A request already in flight could refill what had just been emptied.** A
  conversation's messages, a page of the list, a knowledge base's documents, a
  chat message queued while the socket was down: each now checks the account and
  the organization it started in before writing anything.

### Added

- `apiClient.raw()` — the `Response` without the JSON parse, for downloads and
  previews, so reaching for bytes no longer means giving up the organization
  header, the 401 refresh and `ApiError`.
- `useChanged` — one tested hook for "adjusting state when a prop changes",
  replacing the effects that wrote state after rendering the stale value once.

### Changed

- **`eslint-config-next` 15 → 16**, which turns on the React Compiler's hook
  rules; the frontend broke them in 31 places and no longer does. Server reads
  moved to the query layer where they belonged, and the flat config is imported
  directly - through `FlatCompat` the plugin graph is self-referential and
  ESLint dies serializing it.
- `admin/ratings` fetched its fixed thirty-day summary again for every page of
  results, and rendered a failed half as zeroes beside a full table. Two
  queries, two error states.
- `admin/system` polled health on an interval that kept running in a hidden tab.
- The RAG document list, the ratings page and the admin user drawer rendered a
  502 as "nothing here". They say what happened, and offer a retry.

### Fixed

- `/rag` polled a document's ingestion status exactly once. It armed the next
  poll from the identity of an array React Query deliberately keeps stable, so
  a document stuck at `processing` never updated without a reload.
- The `/rag` sync tab emptied itself on an organization switch and stayed empty
  until the user clicked away and back.
- The sync wizard discarded a half-filled form when a background refetch
  reordered the collection list.
- The admin user drawer vanished instead of closing when its row was deleted.
- "Revoke all others" from the second page of sessions listed the devices it
  had just revoked.
- The agent builder could sit on its skeleton after a rollback to a version
  structurally equal to the current draft.

### Removed

- `MANUAL_STEPS.md`, a generator leftover in which nearly every variable name
  was wrong. `docs/configuration.md` has it correctly, and now has the two
  external click-paths that file was the only place to carry.

### Notes for operators

Nothing to do. No migration, no configuration change, no API change. A signed-in
user is signed out of nothing; the first page load after deploying refetches
more than usual, because a browser holding a cache from before this version
identifies its tenant and starts again.

## [0.0.2] — 2026-08-02

A dependency patch, and the first release cut through the path 0.0.1 built.

### Changed

- `tavily-python` 0.7.26 → 0.7.27, which is what the `web_research` capability
  searches with.

## [0.0.1] — 2026-08-02

First tagged version. The platform is usable end to end — build an agent in the
UI, publish it, run it from chat, an HTTP API, Slack or an embedded widget, with
budgets and approvals applying identically to all of them — and the interfaces
below should be treated as unstable until 0.1.0.

### Added

**The agent model.** An agent is data, not code: instructions, a model profile, a
set of capabilities and a budget, versioned on publish and exportable as YAML into
a client's own git repository. Spec, version, exposure and run are the four nouns
everything else is built from.

**Capabilities** — seven, registered in code and composed by configuration:
knowledge search, skills, web search (DuckDuckGo, native, Tavily, Brave, Exa),
sandboxed Python, charts, reasoning effort, and a clock. Per-tool approval and
per-agent tool renaming key on a stable tool id, so a rename cannot detach an
approval gate.

**MCP** — any Model Context Protocol server by URL, over streamable HTTP or SSE,
with 58 common servers in the picker and full OAuth 2.1 (discovery, dynamic client
registration, PKCE, refresh). Connections are personal or organization-wide; only
the latter can be bound by a published agent.

**Models** — 27 providers, per-organization credentials, fallback on outage, and
self-hosted Ollama or a LiteLLM proxy. Model ids stay free text, with live and
curated pickers, because a provider ships something the morning after any list is
warmed.

**Knowledge and skills** — collections with pgvector retrieval over uploaded
documents, Google Drive and S3; and skills, which are written know-how the agent
loads only when it decides one is relevant.

**Governance** — monthly budgets checked *before* each model request and recorded
even when a run fails, human approval for side-effecting tools, per-agent alerts
with an audience, and an audit trail.

**Permissions** — three layers: the deployment superadmin, an organization role
composed from a permission catalog, and per-row visibility plus grants. Effective
access is `max(role scope, grant)`, so sharing one resource never means promoting
somebody.

**The vault** — envelope encryption for every credential at rest, sealed to the
organization or member that owns it, so a ciphertext moved between tenants cannot
be decrypted. There is deliberately no second mechanism.

**Surfaces** — web chat, HTTP API, Slack, Telegram, Mattermost and embeddable
widgets, all behind one runner.

**Multi-tenancy** — organization isolation enforced by database constraints rather
than by service code alone.

**Dependency freshness as a policy.** FastAPI, Pydantic AI, Logfire and
genai-prices are uncapped and meant to track their newest release — genai-prices
especially, since it *is* the price snapshot budgets are computed from.
`make deps-upgrade` bumps them, a scheduled `framework-freshness` workflow tries
the newest on a Monday and opens an issue when it breaks, and Dependabot opens the
PR. Majors are not held back: delaying one does not avoid the upgrade, it only
makes the eventual jump wider.

**Pre-commit**, covering both halves of the repo: the standard hygiene hooks,
`codespell`, `yamlfmt`, `zizmor` over the workflows, and ruff / ty / prettier /
eslint / tsc. `pre-commit` had been a dependency and `make install` had been
running `pre-commit install` for a while, but there was no config file, so the
installed hook did nothing.

### Fixed

- **Every path that created a user was broken.** The user repository still passed
  `role=` to the model after the column was dropped in `0066`, and SQLAlchemy
  raises on an unmapped keyword — so registration, Google OAuth,
  `agenticos user create` and `agenticos cmd bootstrap` all failed. Bootstrap is
  the command the install instructions open with.
- **`agenticos cmd seed --clear` deleted nothing**, for the same reason: it
  filtered on the dropped `role` column. It now keys on `is_app_admin`.
- **The chat WebSocket 500'd on handshake in local development.**
  `docker-compose.dev.yml` claimed in its header to be identical to
  `docker-compose.yml`, had drifted, and had lost `--ws websockets-sansio` —
  and it was the file `make dev` used.
- **Production ran without a route to the internet.** The only network was marked
  `internal: true`, which blocks egress, so no agent could reach a model provider.
  Split into an internal `data` network for Postgres and Redis and an `edge`
  network for the app.
- **Production ran no background work at all** — no Prefect server or runner, so
  document ingestion and collection syncs never happened and an upload stayed
  unsearchable forever.
- **The test guarding the coverage gate could not run on the interpreter that
  ships.** It used `Path.full_match`, added in Python 3.13, while CI installs
  3.12. `backend/.python-version` now pins 3.12 so local matches.
- **The security CI job never audited anything** — it errored installing
  `pip-audit` outside a virtualenv, with two more argument errors queued behind
  that.
- **Icons and diagrams in the documentation rendered as their own source**, for
  want of `pymdownx.emoji` and a mermaid custom fence.
- **FastAPI 0.141 stopped flattening included routers into `app.routes`**, so
  every route sweep in `tests/api/test_platform_routes.py` silently ran over zero
  routes. Rewritten on the public `iter_route_contexts`. Found by upgrading rather
  than by a Dependabot PR, which is the argument for the freshness workflow.
- **`Agent.updated_at` was typed `string | undefined`** while the API sends
  `null`, which made the honest test for "never edited" a type error.
- **The workflows ran with a broader token than they need** and left the checkout
  credential on disk. Every action is now pinned to a commit SHA,
  `persist-credentials: false` everywhere, `contents: read` by default, and Pages
  write scoped to the one job that deploys.
- **`backend/.pre-commit-config.yaml`** shadowed the repository root and carried a
  `ty` hook that failed on an argument the pinned `ty` does not accept.

### Security

- **A conversation was readable and writable across tenants.** `GET
  /conversations/{id}/messages` returned a full transcript — tool calls and
  their arguments included — for a conversation in another organization, and
  `POST` to the same path appended a turn to it, `role: "assistant"` included,
  which rendered to its owner as the agent's own words. `organization_id` is now
  a required argument on every conversation read and write; a caller that
  genuinely reads across tenants passes an explicit sentinel.
- **The avatar proxy forwarded a path traversal to the backend.** It is the one
  route handler served without a session, so an anonymous caller could drive
  arbitrary `GET`s against the internal API and read the response.
- **A channel bot missing one configuration value stalled the whole API.** The
  Slack and Mattermost supervisors retried a start that returns without
  awaiting, which never yields — so the event loop starved and every request,
  health check included, stopped being answered.
- **Icons are resolved from the directory listing**, not by joining a request
  parameter onto a path, and a symlink out of that directory is refused.

### Added — the toolchain that keeps it honest

- **An automated pull request reviewer** that reads this repository's own rules
  from the base branch rather than a generic checklist. See
  [Code review](docs/code-review.md).
- **`main` is protected by a ruleset** with no bypass actors: pull request
  required, CI green, squash only, no force push. See
  [Branches](docs/branching.md).
- **A weekly freshness job** that upgrades the entire lockfile, transitive
  packages included, runs the suite against it and opens an issue when the
  newest release breaks us.

### Changed

- **One compose file per environment**, with a matching frontend file beside it:
  `docker-compose.yml` (local), `docker-compose-dev.yml` (dev server),
  `docker-compose-prod.yml` (production), each with a `.frontend.yml` sibling.
  `make stage` is kept as an alias for the new `make dev-server`.
- **One long-lived branch.** Work reaches `main` by pull request from a
  short-lived branch, squashed on merge. A `dev` branch existed briefly and was
  removed; see [Branches](docs/branching.md). CI's lint job matches `make lint`,
  and the integration suite refuses to skip when `CI` is set: an unreachable
  database there means the service container failed, and skipping two hundred
  tests to report green is worse than failing.
- **Pydantic AI 2.x** is the agent runtime, and the frontend is on **Next 16**.
- **The documentation is the single copy of how the system works**, with a
  trigger map from code path to page in `CLAUDE.md` and a `Stop` hook
  (`scripts/docs_drift.py`) that names the pages a change owes.

### Removed

- `users.role`, `UserRole`, `User.has_role()`, `RoleChecker`, `CurrentAdmin` and
  `CurrentSuperuser` (`0066`). Authority inside an organization is a membership
  row plus the permission catalog.
- `CHANNEL_ENCRYPTION_KEY` and the deployment-wide Fernet keys (`0038`).
  Everything seals through the vault, bound to an owner.
- `app/agents/assistant.py` and `app/agents/prompts.py`. There is no single agent
  object and no system prompt in code; an agent is assembled per run from the
  capabilities its spec names.
- Conversation-level knowledge-base ids (`0059`). An agent's spec is the only
  thing that decides what it may search.
- `ENV_VARS.md`, superseded by [Configuration](docs/configuration.md).
- `.fastapi-fullstack.json` and the `make upgrade*` template-merge targets. This
  codebase has diverged from the generator past the point where a 3-way merge
  helps.

[Unreleased]: https://github.com/vstorm-co/agenticos/compare/v0.0.32...HEAD
[0.0.32]: https://github.com/vstorm-co/agenticos/compare/v0.0.31...v0.0.32
[0.0.31]: https://github.com/vstorm-co/agenticos/compare/v0.0.30...v0.0.31
[0.0.30]: https://github.com/vstorm-co/agenticos/compare/v0.0.29...v0.0.30
[0.0.29]: https://github.com/vstorm-co/agenticos/compare/v0.0.28...v0.0.29
[0.0.28]: https://github.com/vstorm-co/agenticos/compare/v0.0.27...v0.0.28
[0.0.27]: https://github.com/vstorm-co/agenticos/compare/v0.0.26...v0.0.27
[0.0.26]: https://github.com/vstorm-co/agenticos/compare/v0.0.25...v0.0.26
[0.0.25]: https://github.com/vstorm-co/agenticos/compare/v0.0.24...v0.0.25
[0.0.24]: https://github.com/vstorm-co/agenticos/compare/v0.0.23...v0.0.24
[0.0.23]: https://github.com/vstorm-co/agenticos/compare/v0.0.22...v0.0.23
[0.0.22]: https://github.com/vstorm-co/agenticos/compare/v0.0.21...v0.0.22
[0.0.21]: https://github.com/vstorm-co/agenticos/compare/v0.0.20...v0.0.21
[0.0.20]: https://github.com/vstorm-co/agenticos/compare/v0.0.19...v0.0.20
[0.0.19]: https://github.com/vstorm-co/agenticos/compare/v0.0.18...v0.0.19
[0.0.18]: https://github.com/vstorm-co/agenticos/compare/v0.0.17...v0.0.18
[0.0.17]: https://github.com/vstorm-co/agenticos/compare/v0.0.16...v0.0.17
[0.0.16]: https://github.com/vstorm-co/agenticos/compare/v0.0.15...v0.0.16
[0.0.15]: https://github.com/vstorm-co/agenticos/compare/v0.0.14...v0.0.15
[0.0.14]: https://github.com/vstorm-co/agenticos/compare/v0.0.13...v0.0.14
[0.0.13]: https://github.com/vstorm-co/agenticos/compare/v0.0.12...v0.0.13
[0.0.12]: https://github.com/vstorm-co/agenticos/compare/v0.0.11...v0.0.12
[0.0.11]: https://github.com/vstorm-co/agenticos/compare/v0.0.10...v0.0.11
[0.0.10]: https://github.com/vstorm-co/agenticos/compare/v0.0.9...v0.0.10
[0.0.9]: https://github.com/vstorm-co/agenticos/compare/v0.0.8...v0.0.9
[0.0.8]: https://github.com/vstorm-co/agenticos/compare/v0.0.7...v0.0.8
[0.0.7]: https://github.com/vstorm-co/agenticos/compare/v0.0.6...v0.0.7
[0.0.6]: https://github.com/vstorm-co/agenticos/compare/v0.0.5...v0.0.6
[0.0.5]: https://github.com/vstorm-co/agenticos/compare/v0.0.4...v0.0.5
[0.0.4]: https://github.com/vstorm-co/agenticos/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/vstorm-co/agenticos/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/vstorm-co/agenticos/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/vstorm-co/agenticos/releases/tag/v0.0.1
