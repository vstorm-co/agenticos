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
