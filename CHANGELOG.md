# Changelog

Notable changes to AgenticOS. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Two things are versioned separately from this file and worth knowing about:

- **`SPEC_VERSION`** — the agent spec format, currently **7**. A published agent
  and a client's exported YAML both carry it, so it only ever moves forward with a
  migration that keeps old documents loading. See
  [the spec reference](docs/reference/spec.md).
- **The migration chain** — `backend/alembic/versions/`, squashed to a single
  `0001_baseline` for this first version. Revision ids named below (`0038`,
  `0059`, `0066`) are history: they describe when something changed, not a file
  that still exists. Schema changes are listed here by what they do.

## [Unreleased]

Nothing yet.

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

[Unreleased]: https://github.com/vstorm-co/agenticos/compare/v0.0.8...HEAD
[0.0.8]: https://github.com/vstorm-co/agenticos/compare/v0.0.7...v0.0.8
[0.0.7]: https://github.com/vstorm-co/agenticos/compare/v0.0.6...v0.0.7
[0.0.6]: https://github.com/vstorm-co/agenticos/compare/v0.0.5...v0.0.6
[0.0.5]: https://github.com/vstorm-co/agenticos/compare/v0.0.4...v0.0.5
[0.0.4]: https://github.com/vstorm-co/agenticos/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/vstorm-co/agenticos/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/vstorm-co/agenticos/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/vstorm-co/agenticos/releases/tag/v0.0.1
