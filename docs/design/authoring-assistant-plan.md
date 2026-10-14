# Authoring assistant — plan first (#52)

A system that helps people **write** agents, not only run them: instructions in
the Builder, skill bodies, tool descriptions. Two modes — *describe → draft
agent* and *improve an existing agent from evidence*. This was the plan-first
deliverable of #52. Since 2026-10-12, #52 is the "Self improving" milestone
(#2110–#2119): it puts evals first and builds this assistant on top of them.
This document is the design record for that work — the decisions, the
alternatives they rejected and the contract the implementation keeps.
[Where this plan stands](#where-this-plan-stands) says what #52 changed, which
issue owns each decision, and what the code showed when the plan was checked
against `main`. A companion demo of the review UI is beside it:
`docs/design/authoring-assistant-demo.html`.

The one-sentence design: **the assistant reads the org's own run record and
ratings, proposes changes as evidence-backed diffs — or verifies changes a
person made by hand — and nothing changes an agent without a person's
decision: spec changes wait in the draft a person publishes, a skill change
waits in a proposal a person applies (and applying it is live — skills have
no draft stage); the assistant writes nothing on its own, and an organization
can switch it off entirely.**

## Where this plan stands

### What #52 changed

- **Evals come first.** Datasets (#2110), scoring (#2111), eval runs (#2113),
  generated cases (#2114) and suites with triggers (#2115) are the core of the
  milestone, so [Decision 6](#decision-6--synthetic-evaluation-is-out-replay-on-real-prompts-is-in)
  is reversed. A proposal is checked before anyone accepts it by running the
  agent's suites on the **proposed projection**: a frozen snapshot of the
  draft with every pending hunk applied — the demo's "Proposed" view
  (contract item 2). The draft itself does not change; running the suites
  on the draft alone would measure the baseline, because pending hunks are
  not in it. A skill proposal is checked the same way, with the candidate
  body and resources served in place of the current ones.
- **Replay becomes an eval run.** [Decision 9](#decision-9--replay-test-a-draft-against-the-prompts-users-already-sent)'s
  pairs come from a dataset made from real conversations; tool calls are
  answered from the recordings by #2112; a draft runs through the
  explicit-spec path and is compared with a baseline by #2113. Those runs are
  stamped `eval`, so no `RunSurface.REPLAY` is added. Decision 9's rules —
  matching, divergence, the frozen candidate, attribution, holding the model
  and resources constant — stand, and are now owed by #2112 and #2113.
- **More proposal targets.** Context files, the agent's and its delegates'
  descriptions, the model and its settings, capabilities, knowledge bindings
  and MCP allowed tools (#2118); missing knowledge-base content (#2119).
- **The organization switch** ([Decision 10](#decision-10--an-organization-switch-off-means-off))
  covers the judge, the case generator and the knowledge-gap drafts as
  well as the assistant. Deterministic evals stay available while it is off.

### Which issue owns each decision

| Decision | Owned by |
|---|---|
| 1 — ratings and the run record lead | #2117; the same read path feeds #2110, #2114 and #2119 |
| 2 — propose, never write | #2117 (spec, skills; "Check with evals" runs the suites on the frozen proposed projection, never on the draft alone), #2118 (the targets in [Proposal targets added by #52](#proposal-targets-added-by-52)), #2114 (generated cases arrive as a proposal) |
| 3 — the improver is an agent | #2117; the seeded-agent mechanism is built first, for the judge, in #2111 |
| 4 — tenant scope and gates | every child |
| 5 — mode 1 produces a draft | #2117 |
| 6 — synthetic evaluation is out | reversed: #2110, #2111, #2114, #2115 |
| 7 — one review grammar | #2117, #2118, #2114 |
| 8 — the assistant also verifies | #2117 |
| 9 — replay | #2112 (recordings), #2113 (draft runs, comparison) |
| 10 — the organization switch | #2111, extended by #2114, #2117 and #2119 |
| SoL-Pi 1 — paired baseline | #2113; used by #2116, #2117 and #2118 |
| SoL-Pi 2 — pinned judge | #2111, #2113 |
| SoL-Pi 3 — the improver never sees evals | #2117, #2118; the same exclusion in #2114 and #2119 |
| SoL-Pi 4 — evidence overlap on the gate | #2116, from #2117's evidence and #2110's `case.source` |
| SoL-Pi 5 — verified quotes | #2117, #2111, #2119 |
| SoL-Pi 6 — two axes, quality first | #2113, #2115; the efficiency goal in #2118 |
| SoL-Pi 7 — expected effect | #2117 |
| SoL-Pi 8 — map-reduce over runs | #2117 |

### Proposal targets added by #52

Decisions 2–4 define instructions, tool descriptions and skills in detail.
The targets #2118 and #2119 add are held to the minimum contract below; their
detailed design belongs to the #2118 and #2119 pull requests, which must not
weaken it.

| Target | Proposal shape | How it is accepted | Gate |
|---|---|---|---|
| Context file | A whole-content replacement with rationale, evidence and the base version, modelled on the skill proposal (Decision 2) | Apply, live for every bound agent; refused when the file changed after the base version | `context:edit` on the file via `resolve_access` |
| Agent description, delegate descriptions | Hunks in the agent's `spec_proposals` batch | Into the draft | `agents:edit` on the agent |
| Model profile and model settings | Hunks in the batch, with an eval comparison of quality and cost | Into the draft | `agents:edit`, and use of the proposed profile |
| Capabilities: add, remove, config, approval mode | Hunks in the batch | Into the draft | `agents:edit`; never widens access |
| Knowledge bindings, MCP allowed tools | Hunks in the batch | Into the draft | `agents:edit`; never widens access |
| Missing knowledge | A report with drafted content | No apply action — a person adds documents | `collections:view` on the searched collections to read the report |

**A proposal never widens access.** A capability, collection, MCP connection,
model profile or delegate the caller cannot grant is refused when the
proposal is staged and again when it is accepted; `validate_spec` checks the
result at publish like any manual edit. #2118 defines the staging tools for
these targets — `propose_context`, `propose_description`, `propose_model`,
`propose_capability`, `propose_knowledge_binding` and `propose_mcp_tools` —
beside Decision 3's, and #2119 defines `report_knowledge_gap`.

### Considered after review, and rejected

- **Apply modes: Manual, Canary, Auto.** The engine write-up on #52
  (2026-08-28) proposed a toggle under which an accepted change ships to a
  canary slice of traffic, or goes live on its own behind eval gates.
  Rejected: nothing changes an agent without a person's decision — no
  auto-accept, auto-publish or auto-apply — and a canary slice needs traffic
  splitting, which environments do not do. The toggle is gone from the demo.
- **An optimizer engine (GEPA/DSPy, "Mode B").** Generating candidate edits
  and keeping the one that wins on held-out cases is future work, outside
  this milestone. It would build on eval runs (#2113) and scoring (#2111), and
  its output would still be a proposal a person accepts.
- **SoL-Pi's automatic implementation.** The study lets its loop implement
  and adopt changes without a person, and names autonomous recursive
  self-improvement an open risk itself. That is the case for propose, never
  write.
- **"Must get cheaper" for every proposal.** Only a proposal that declares an
  efficiency goal is held to it; see
  [Adopted from SoL-Pi](#adopted-from-sol-pi-nvidia-arxiv-260920519), point 6.
- **SoL-Pi's figures.** Its evidence is an A/B over 11 tasks with no
  confidence intervals, and its "Performance" variant was chosen on the set
  it is reported on. The rules are adopted; the percentages are not quoted.
- **SoL-Pi's harness mechanisms** — ObservationPack, Online Context Compact,
  Action Fusion, the Evidence-Preserving Reducer — are outside this
  milestone. Measuring how much of our runs' input is re-sent tool output
  comes first; a `pack` mode for `tool_output_limits` may follow as a
  platform issue, tracked separately.

### Adopted from the engine write-up

- **Secret-scan on cases.** "Add to dataset", CSV/JSONL import (#2110) and
  cases generated from conversations (#2114) copy transcript text into a new
  table and its exports. A credential found in it is refused or redacted
  before the case is stored.
- **Never measure on the evidence.** When a proposal is checked with evals
  (#2117), cases taken from the conversations the proposal was derived from
  are left out of the comparison; otherwise the gain is measured on the data
  it was fitted to.
- **No separate growth cap.** A suite that wants one carries a length or cost
  ceiling check (#2111).

### Adopted from SoL-Pi (NVIDIA, arXiv 2609.20519)

SoL-Pi is an agent harness whose improvements were found by an auto-research
loop: rollouts, trajectory analysis, a proposal, review and two validation
gates, through which 4 of 152 ideas survived. This milestone takes its rules
for measurement and isolation, not its mechanisms.

1. **A paired baseline** (#2113; used by #2116, #2117's "Check with evals"
   and #2118's model comparison). A gate runs a baseline arm in the same eval
   run as the candidate, because providers drift between runs. A cached
   baseline may stand in only when its baseline version, dataset version and
   judge (point 2) all match and it is younger than a configured number of
   hours. Cases whose outcome flipped are rerun, twice by default and
   configurably, so the report separates confirmed regressions from
   unconfirmed ones. A small sample is reported as uncertainty ("sample too
   small"), not a verdict; there is no hard minimum. The baseline arm's cost
   is in the estimate shown before consent. The default comparison on the
   Evals tab stays cheap — the last run of the previous version — and shows
   the date and the model on both sides.
2. **A pinned judge** (#2111, #2113). A score snapshot records the judge's
   model profile, its spec version and a hash of the rubric. A comparison
   whose other side was scored by a different judge is marked invalid.
3. **The improver never sees evals** (#2117, #2118; also #2114, #2119). The
   improver's read tools (`read_runs`, `read_transcript`, `read_feedback`,
   `read_manifest`) never return runs stamped `eval` or `case_scores`. There
   is no proposal target for suites, thresholds, datasets, scorers or
   environments, and a test asserts the target registry holds none of them.
   A failed "Check with evals" reaches the improver only as the person's
   decision, never as the content of the cases. The same exclusion of eval
   runs applies to #2114's conversations source and to #2119's search log.
   This deliberately departs from SoL-Pi, which shows its optimizer the dev
   results and isolates only the held-out set; an opt-in dev dataset the
   improver may read is future work.
4. **Evidence overlap on the gate** (#2116, from #2117's evidence and
   #2110's `case.source`). The promotion gate's report shows how many suite
   cases come from conversations that were evidence for proposals accepted
   into the version. It informs; it does not block.
5. **Verified quotes** (#2117, #2111, #2119). A proposal's evidence — run
   ids, quotes from transcripts and manifests — is checked deterministically
   against the database; an item that does not verify is dropped and
   flagged. At most 12 items of at most 600 characters each. The judge's
   output may carry `quotes`; each must occur verbatim in the answer, and one
   that does not is flagged in `reason` without changing the verdict. A
   knowledge-gap draft cites its sources (document ids, questions), which
   are verified the same way.
6. **Two axes, quality first** (#2113, #2115). A suite's threshold is a
   quality tolerance — a minimum pass rate and a maximum of confirmed
   regressions — plus an optional efficiency ceiling: the largest allowed
   rise in cost per passed case and in p95 latency. The report shows both
   axes side by side. SoL-Pi's rule that at least one efficiency metric must
   improve applies only to a proposal that declares an efficiency goal, such
   as a model or capability change made to cut cost (#2118).
7. **An expected effect** (#2117). A proposal states what it should change —
   the cases it should flip, or the behaviour — and the "Check with evals"
   report says whether that happened ("flipped 3 of 4 predicted").
8. **Map-reduce over runs** (#2117), as an implementation note: one subagent
   per run or conversation, and a reducer that assembles the evidence.

### What the code showed (`main` at 0.0.535, 2026-10-12)

- **There is no workflow engine**, so #2111 cannot reuse `WorkflowStepEval`
  (#1925). #2111 defines the check vocabulary; workflow step evals reuse it
  later.
- **`agent_runs.agent_id` is not nullable**, so a judge call recorded as a run
  needs an agent. The judge (#2111), the case generator (#2114) and the
  improver (#2117) are seeded system agents. Only skills are seeded today
  (`OrganizationService._seed_bundled_skills`), so #2111 builds that mechanism
  once.
- **Conversations carry no `agent_id`; messages do.** The ratings-for-agent
  read joins `message_ratings` to `messages.agent_id`, with the tenant
  through `conversations.organization_id`.
- **The tenancy audit sees only what it lists.** `TENANT_REQUIRED` in
  `tests/test_org_scope_regression.py` is maintained by hand: a new org-scoped
  repo function is audited once it is added there.
- **`tool_calls` keeps one, effective `tool_name`** and orders calls by
  `started_at`, with no occurrence index. The tool definitions the model was
  handed are in `run_manifests.payload`; Decision 9's stable-id matching maps
  through them.
- **Knowledge search records no score**, and `min_score` defaults to 0.0, so a
  search almost always returns something. The only miss visible in existing
  data is the empty-result text. #2119 needs searches to record their top
  score before there is anything to group.
- **Environments, promotion and `tracks_latest` work as Decision 9 assumed.**
  Per-environment connections (#2112) are new. `get_runnable_spec` refuses
  drafts; the explicit-spec path is threaded through `prepare`.
- **A Datasets resource fits the owned-resource machinery** — Skill's model,
  `resolve_access`, the shared `resource_grants` table and the sharing
  router. Immutable dataset versions follow `AgentVersion`, not the skill's
  informational version counter.

## 0. What already exists — corrected

The issue was filed on 2026-08-01 and three of its premises have moved since.
The design builds on what shipped rather than re-proposing it.

**"`message_ratings` is currently surfaced nowhere" — no longer true.** Since
#538 and the Activity rebuild, ratings are read in five places: the
`?rated=up|down` filter on run history (`repositories/agent_run.py`,
`_was_rated`), the 👎 marker on run rows (`AgentRunnerService.down_rated_run_ids`),
per-turn ratings **including the down-rating comment** on the run transcript
(`transcript_ratings`), the org-scoped `GET /stats/ratings/summary`
(`StatsService.ratings_summary`), and per-version counts
(`message_rating.rating_counts_by_version` → `VersionUsageRow`). What is still
missing is exactly the two things this issue needs: an org-scoped read of **raw
rating rows for one agent** (the admin list is deployment-wide, app-admin only),
and any consumer that turns the signal into a change.

**`run_manifests` is a better mode-2 source than traces, and the issue does not
mention it.** One row per run, recorded from the wire by `RecordingModel`
(`app/agents/manifest.py`): the exact `instructions`, system prompts, tool
names + descriptions + schemas the model was actually handed, and per-request
stats. For authoring purposes this beats a Logfire trace — it answers "what did
the model see" rather than "what did the model do", and it exists on every
deployment unconditionally. With the recorder's own limits, which the read
path must honour: no manifest is written when a run never reached a model
request, a persistence failure is deliberately swallowed rather than failing
the run, and `fit` may truncate instructions and tool schemas — so a manifest
is *best-available* evidence, and an absent or truncated one is skipped or
surfaced as incomplete while the ratings and transcript evidence continues.

**"Propose, don't write" is already implemented — for skills.** `skill_proposals`
(`db/models/skill_proposal.py`): an agent's write to a skill file lands as a
whole-body proposal; a person holding `skills:edit` applies or discards; a
decision is terminal; three turns refining the same skill leave one proposal.
The model docstring argues both halves — why propose-not-apply, why
whole-body-not-diff. This plan extends that grammar to the spec; it does not
invent a second review queue.

**Mode 1 has a shipped precedent.** Promoting a dynamic specialist
(`docs/concepts.md`) already turns an agent-authored definition into an
**ordinary draft** — owned by the promoter, gated on `agents:edit`, never
published, pinned nowhere. Its stated reasoning ("publishing is a person's
action") is the argument this plan reuses.

**No AI-assisted authoring exists anywhere yet.** A sweep of `backend/app` and
`frontend/src` for generate/improve/suggest/rewrite finds only static category
suggestions, model-id picker suggestions and the schema-driven form. Greenfield.

## Decision 1 — ratings and the run record lead; traces enrich

Mode 2 works from data every deployment has:

| Signal | Where | What it answers |
|---|---|---|
| 👍/👎 + comment | `message_ratings` (value, `comment`, per message) | what readers rejected, in their words |
| Run outcomes | `agent_runs` (status, `error`, tokens, cost, latency, surface) | failure modes, cost/latency outliers |
| What the model saw | `run_manifests.payload` | the exact instructions & tool descriptions in force |
| What happened | `messages` + `tool_calls` | retries, tool misuse, the shape of bad answers |
| Did a change help | `rating_counts_by_version` | v*N* vs v*N+1*, already queryable |

Logfire traces are **optional enrichment**, never a prerequisite — and in v1
they are not even that, because **no read path exists**: `LOGFIRE_TOKEN` and
`ObservabilitySpec.token_secret_id` are both *write* credentials (they let a
run send traces), and the org/project slugs only build a link for a person
already signed into Logfire. So v1 ships trace enrichment as exactly what the
product already has — the link on the run — and the assistant states plainly
that it worked from ratings and run outcomes. Reading traces would need a
separate read credential and integration; that is future work behind this
degradation seam, not a configuration away. The assistant never refuses for
want of a trace.

*Rejected: trace-first (the issue's own text kills it — the traces are often
not ours to read). Also rejected: building a trace-ingestion pipeline to make
them always available; that is an observability project, not an authoring one.*

## Decision 2 — propose, never write; Accept lands in the draft

Every suggestion the assistant makes is a **proposal row**, reviewed by a
person. Accepting one writes into the agent's *draft* spec — the one draft the
Builder edits — through the registry service. Publishing stays a separate,
human action through the existing validate-then-publish path, so a proposal can
never touch a published version even indirectly without a person clicking
Publish and `validate_spec` passing.

Why not write the draft directly and skip the proposal: `save_draft`
deliberately does not validate and **silently overwrites** — an assistant
writing there mid-session would clobber a human's in-progress edit, which is
the exact failure `skill_proposals` was built to avoid. And the proposal is
where the *why* lives: each row carries a rationale and evidence references
(rating ids, run ids) that a draft field cannot.

Mechanism, per surface:

- **Skills** — reuse the `skill_proposals` mechanism and recording seam
  (`_propose_skill_changes` in `AgentRunnerService.finish`), **extended
  additively**: nullable `rationale`, `evidence` JSONB and a base `skill
  version` column, so a skill proposal can carry the same evidence popover
  and Edit action the other two surfaces get — the existing table stores
  only the replacement body, which cannot feed the unified grammar Decision
  7 promises. The base version is **enforced at Apply**, not merely stored:
  a proposal reviewed against v3 refuses to overwrite a skill somebody has
  meanwhile advanced to v4 — it renders stale with a side-by-side, exactly
  the hunk rule — where today's Apply updates unconditionally. And one truth stated rather than papered over: **applying a
  skill proposal is a live change.** Skills have no draft/publish stage —
  Apply bumps `skills.version` and every bound agent reads the new body on
  its next run. The draft-first guarantee above is a *spec* guarantee; for
  skills the proposal itself is the review stage, the Apply control says it
  goes live everywhere, and the eval suites of the agents that bind the
  skill run on the candidate body before Apply — the test stage a draft
  would otherwise provide. A skill draft path was considered
  and rejected: "no deploy, no pull request" is the product's own model for
  skills, and a second lifecycle would contradict it.
  Two recording consequences the reuse does not get for free:
  - **Evidence needs its own inlet.** `_propose_skill_changes` receives
    filesystem `SkillChange` objects — there is no rating or run reference
    in a workspace write. The improver therefore stages skill changes
    through an explicit `propose_skill` tool (rationale + evidence
    attached, like its spec siblings), recorded through the extended
    columns; the workspace-write route stays for ordinary agents and
    records, honestly, evidence-less proposals.
  - **Supersession is scoped to the proposer.** The existing recorder
    dedups pending rows by organization + skill alone, so an improver
    proposal would replace another agent's pending edit in place and
    corrupt its attribution. Pending skill proposals key on
    (organization, skill, proposing agent); one agent's newer proposal
    supersedes only its own.
- **Instructions and tool descriptions** — a sibling table, `spec_proposals`,
  modelled on `skill_proposals` (org id, target `agent_id`, authoring
  `run_id`/`conversation_id`). Cardinality: **one open batch per agent** —
  the batch holds the instruction hunks *and* a collection of tool-override
  entries keyed by `(capability_id, tool_id)`, so one improver run
  suggesting two tool descriptions records both and the reviewer sees the
  whole batch; a later run supersedes the batch, not one entry at a time —
  where "later" is decided by the **source run's start time**, not by which
  `finish` committed first: proposals are recorded from `finish`, so two
  overlapping improver runs can complete out of order, and an older run
  must never replace a newer batch merely because it finished last.
  **Decision state lives on the hunk, not the row**: each
  hunk carries its own `status` (pending/accepted/dismissed) and decision
  metadata (`decided_by`, `decided_at`), because one review can accept one
  hunk and dismiss its neighbour, which a row-level status cannot represent.
  The row keeps lifecycle only: **open until the draft publishes or a newer
  run supersedes it** — deciding the last pending hunk does not close the
  batch, or Undo would die with the final decision. A hunk decision is
  revisable (Undo) while the batch is open and becomes terminal when it
  closes; `skill_proposals`' decided-once rule applies to the closed batch,
  not to a hunk mid-review. Two mechanics that keep decisions honest:
  - **Undo is anchored like Accept.** It reverses the draft write only
    while the accepted text still stands in the draft; if the reviewer has
    meanwhile edited that text by hand, Undo goes *stale* and refuses —
    optimistic concurrency alone cannot catch this, because the manual
    edit legitimately advanced the revision.
  - **A hunk decision and its draft mutation are one conditional
    transaction.** Two reviewers concurrently accepting and dismissing the
    same pending hunk must resolve to exactly one outcome — a
    compare-and-set commits together with any draft write, so a dismissed
    hunk can never linger applied in the draft. The draft-revision check
    does not cover this on its own: Dismiss writes no draft. The
    compare-and-set conditions on **both the hunk's status and its batch
    still being open**: supersession closes the batch without touching any
    hunk's status, so a check on the hunk alone would let an Accept or Undo
    already in flight change the draft after a newer run had closed the
    batch it belongs to.
  Two target kinds:
  - `instructions`: **a base snapshot plus a list of anchored hunks**, each
    `{old_text, new_text, rationale, evidence}`, decided independently.
    This deliberately diverges from `skill_proposals`' whole-body shape,
    because the decision differs: a skill proposal is accepted or discarded
    whole, where a prompt review is per-change — the demo's Accept / Edit /
    Dismiss on each suggestion is the product. **The anchor is a position,
    not the text alone**: each hunk stores its base-snapshot range and the
    surrounding context lines, because bare `old_text` is ambiguous when
    the same line appears twice and a pure insertion (empty `old_text`)
    would match everywhere. Staleness is handled openly rather than
    avoided: a hunk applies only while that specific anchor still resolves
    in the current draft — text moved but unambiguous still applies; an
    anchor that is gone, changed or ambiguous renders the hunk *stale*
    with a side-by-side view, never applies silently and never applies in
    the wrong place. The UI computes the visible diff with the existing
    `frontend/src/lib/diff.ts`.
  - `tool_override`: `capability_id` + stable `tool_id` + the proposed
    `description` (and rarely `name`) — the same two fields
    `ToolOverride` carries, so acceptance is a two-field write into
    `capabilities[i].tool_overrides[tool_id]` that must survive
    `_tool_override_problems` at publish. **Staleness applies here too**,
    not only to instruction hunks: the proposal stores the base values it
    was computed against (the binding's then-current name/description, or
    their absence), and acceptance applies only while the base still
    matches — a removed capability, a removed override or a newer manual
    edit renders the proposal *stale*; it never re-adds a removed binding
    and never overwrites the newer edit.
- Each hunk carries `rationale` (one paragraph, the assistant's argument)
  and `evidence` (JSONB: rating ids, run ids, the numbers behind "3 of 5 👎") —
  rendered in the review UI as the hover popover the demo shows, resolved
  through org-scoped reads so a stale or foreign id renders as absent, never
  as a leak. **And bound to the target, not merely the tenant**: the
  recorder accepts a run or rating reference only when it belongs to the
  target agent (for a skill proposal, only a run that loaded that skill) —
  tenant membership alone would let a fabricated or prompt-injected id
  dress an unrelated record up as support for the hunk. A reference that
  fails the target relationship is dropped at staging, not rendered
  hopefully.
- **Accepting must not race the Builder's autosave.** The Builder holds the
  draft client-side and autosaves the whole spec, so a server-side accept
  while the page is open would be clobbered by the next autosave — and
  "accept happens in the Builder" alone does not close the race, because a
  whole-spec PUT can already be in flight when Accept fires, and the stale
  request landing second would silently drop the accepted hunk while the
  proposal records *accepted*. Draft writes therefore take **optimistic
  concurrency**: `agents.draft_spec` gains a revision the client echoes
  back; a write carrying a stale revision is refused and re-merged, and
  Accept and autosave serialize through the same check.

Propose-only is also the security boundary, not just the review ergonomics.
The assistant reads rating comments and transcripts — text written by
whoever chats with the agent, which makes it a prompt-injection surface: a
comment can try to steer the improver into proposing a hostile instruction
("ignore the refund policy"). A proposal rendered as a diff with its evidence
quoted is exactly the artifact a person can catch that in; an assistant that
wrote directly would carry the injection straight into the spec.

*Rejected: auto-accept below some confidence bar; a version-controlled "agent
edited this" publish path. Both make the assistant a writer, and the platform's
value is that specs change only through drafts a person publishes.*

## Decision 3 — the improver is an agent, with one runner-assembled capability

The improver is an ordinary platform agent — which the issue demands, and which
buys everything for free: a model profile, budgets checked before each request,
approvals, and its runs recorded through `AgentRunnerService.finish`, hence
metered and visible in Activity with no extra work.

**Shipped as a seeded, org-owned agent** — created at organization creation and
topped up like the skill library, visible in the Agents list, its instructions
editable. That is the product being the product: the improver's own prompt is
itself improvable, by itself.

**One new capability, `authoring`**, following the registry conventions
(`snake_case` id, verb-first tool ids, `tools=(...)` explicit):

| Tool | Reads/It stages |
|---|---|
| `read_agent_spec` | the target's draft + published spec, **with the resolved capability catalog** — per binding, every tool's stable id, effective name and effective description via `effective_tools`, because neither the spec (overrides only) nor a manifest (provider-facing names only) carries the `(capability_id, tool_id)` identity `propose_tool_description` must name for a not-yet-overridden tool |
| `read_feedback` | ratings with comments for the target, org-scoped |
| `read_runs` | run metadata: status, error, tokens, cost, latency |
| `read_manifest` | what the model was handed on a given run |
| `read_transcript` | one run's messages + tool calls |
| `read_skill` | a skill run's target: its current body and resources, with the version a `propose_skill` replacement is based on — a whole-body proposal needs the current content, and a skill nobody has loaded has no manifest or transcript to recover it from |
| `read_catalog` | mode 1 only: what the caller can see — skills, collections and context files (id, name, description) and the capability registry |
| `propose_instructions` | stages instruction hunks with rationale + evidence |
| `propose_tool_description` | stages a tool-override entry |
| `propose_skill` | stages a skill-body proposal with rationale + evidence |
| `propose_agent` | mode 1: stages a new draft agent definition |

None of the read tools returns a run stamped `eval` or a case score, so the
improver is never fitted to the suites that check it — see
[Adopted from SoL-Pi](#adopted-from-sol-pi-nvidia-arxiv-260920519), point 3.

Two invariants carried over from the existing registry:

- **The capability never queries the database.** The runner resolves the
  target's data org-scoped and injects it via `CapabilityBuildContext.resources`
  — the same shape as `knowledge`, `context` and `skills`. The `organization_id`
  filter lives in the resolver, one place. For a skill run, the runner checks
  `skills:edit` on the target skill through `resolve_access` at run start and
  only then injects the snapshot `read_skill` returns.
- **`selectable=False`, runner-assembled** — the `channel_tools` precedent.
  The target agent varies per run, so the binding is assembled when a run is
  started through the authoring surface (the Builder's "Improve" action → a
  dedicated endpoint that starts a run of the improver agent with the target
  injected). Publish refuses the capability in any spec, so no ordinary agent
  can be handed org-wide run-and-rating reads by a Toolbox click; the read
  authority derives from the human caller's own permissions at run start.

The `propose_*` tools **stage** into run state; the runner records the staged
proposals in `finish`, beside `_propose_skill_changes` — same seam, same
dedup-across-turns behaviour, and the capability stays DB-free.

The capability builds in **two modes**, because mode 1 has no target by
definition: with an injected target it exposes the full toolset above; on a
mode-1 authoring session it builds narrowed to `read_catalog` and
`propose_agent`; with neither injected it builds `None`. One capability,
one registration — the runner decides the mode from what it injects, the
`channel_tools` way.

Mode 1 has no target to read, but the draft it proposes names org resources
by id: "use our refund-policy skill" has to resolve to a real skill. So the
runner injects, read-only, the catalogs the caller can see — skills,
collections and context files, each as id, name and description, resolved
through `visible_resource_ids` — and the capability registry. Every read of
a specific agent's data stays off. `propose_agent` refuses at staging any
reference that is not in the injected catalog, so a hallucinated id never
reaches the draft to fail later at publish.

**No new `RunSurface` member.** The enum's own rule is that every member needs
a writer and answers "how is the product used"; an improver run started from
the dashboard is `WEB`, and "was it the improver" is already answerable by
`agent_id` — the same argument that keeps delegation out of the enum.

*Rejected: a bare service endpoint that calls a model directly (skips budgets,
approvals, Activity — everything the issue lists); a selectable capability
gated on a new scope (grants org-wide evidence reads to whatever agent binds
it, decided by whoever edits that spec rather than by the caller's own
permissions).*

## Decision 4 — tenant scope, and which permissions gate what

Everything the improver reads arrives through resolvers that take
`organization_id` explicitly — the executable audit in
`tests/test_org_scope_regression.py` (`test_tenant_argument_has_no_default`)
holds every function listed in its `TENANT_REQUIRED` to that, so each new
repo function is added to the list. Evidence ids in a proposal resolve
through the same org-scoped reads when rendered; a foreign id is absent, not an
error, and cross-tenant reads answer 404 as everywhere else.

No new permission. The composition of existing gates already names each action:

| Action | Gate |
|---|---|
| Start an improve/verify run on agent X | `runs:view` (the evidence), `agents:edit` on X via `resolve_access` (the proposals aim at its draft), **and `agents:run` on the seeded improver** via `resolve_access` — grants are independent, so edit access to X does not imply use of the improver, and starting it spends the org's money |
| Start an improve run on skill S | `runs:view`, **`skills:edit` on S via `resolve_access`** — skills have their own ownership, visibility and grants, so access to some agent that binds S proves nothing about S — and `agents:run` on the improver, same as above |
| Verify for a skill | The same gates, and **only against a pending skill proposal** (candidate vs current body): skills have no draft and keep no previous content, so a live manual edit has no base to verify against — Verify(skill) is review of a proposal, never an after-the-fact audit of an edit already live |
| Start a replay | The gates above for its target, **plus `agents:run` on every agent the replay executes**: the target agent for a spec replay, and each selected source agent for a skill replay — replay runs the candidate under those agents and charges their budgets. A case whose source agent the caller may not run is excluded from the run and the exclusion reported |
| Record or change a replay pair's verdict | The run's creator, or `agents:edit` / `skills:edit` on the session's target — `runs:view` reads sessions, it never rewrites another reviewer's evaluation |
| Accept/dismiss an instructions or tool-description proposal | `agents:edit` on the target |
| Apply/discard a skill proposal | `skills:edit` on the skill (existing) |
| Publish the resulting draft | `agents:publish` (existing) |
| Mode 1: create the draft agent | `agents:edit` (the promote precedent), plus `agents:run` on the improver as above |

A new `authoring:*` permission would be a second name for authority these
already express. Owed tests: the cross-tenant refusal (an improver run in org A
cannot read org B's ratings/runs/manifests, in the
`test_org_scope_regression.py` style), ownership-alone-is-not-access on
proposal decisions, an editor of agent X without use of the improver refused
at start, a caller without `skills:edit` on S refused skill authoring however
many agents bind S, a replay refused without `agents:run` on its target and a
skill-replay source silently excluded without it, and a `runs:view`-only
member refused a verdict write.

## Decision 5 — mode 1 produces a draft, never a version

*Describe → draft agent* reuses the promote-a-specialist shape verbatim: the
assistant's `propose_agent` output becomes an ordinary draft — name,
instructions, capability bindings, collection/skill references — owned by the
person who asked, subject to `agents:edit`, validated only when that person
publishes. It stops there, for the reasons `docs/concepts.md` already gives.

One identity rule the promote precedent does not need but mode 1 does:
`propose_agent` on a *later turn* of the same authoring conversation
**updates the draft the first turn created**, never mints a sibling — the
conversation persists the created draft's id, so "make it friendlier" refines
one agent instead of leaving three near-duplicates behind. The cross-turn
test covers this path explicitly.

Trigger templates were considered as the non-AI alternative (a curated,
code-defined catalog pre-filling the create form) and kept as complementary:
templates answer "give me the usual shape", the assistant answers "design this
from my description". Neither replaces the other.

## Decision 6 — synthetic evaluation is out; replay on real prompts is in

> **Reversed by #52.** Evals are the core of the milestone; see
> [Where this plan stands](#where-this-plan-stands). The reasoning below is
> kept as the record of the original scope. The rate-not-count rule still
> holds wherever per-version ratings are cited.

Synthetic datasets, a scoring function and result storage are a schema change
and a ground-truth question this issue should not carry — scoped out exactly as
the issue suggests. What *is* in scope is the evaluation the org's own history
already funds — Decision 9's replay — plus two things worth stating here:

- **The cheap loop already exists — read as rates, not counts.**
  `rating_counts_by_version` reports likes and ratings submitted, with no
  exposure: ten 👎 across a thousand v7 answers against two across ten v8
  answers is a *worsening rate* wearing an improving count. So the v*N* →
  v*N+1* shift the assistant cites is computed against answers served per
  version, carries a minimum-sample caveat, and below that sample is offered
  as qualitative evidence ("two of the ten v8 answers were rated down"),
  never as the verdict.
- **Phase 2 sketch, deliberately undesigned:** dataset rows (input, expected
  qualities), scoring as a capability or a judge agent, results keyed on
  `agent_version_id`. Each of those is a decision for its own plan; replay
  (Decision 9) will have built the run-and-compare mechanics they reuse.

## Decision 7 — three surfaces, one review grammar

Instructions, skill bodies and tool descriptions get **one** review grammar,
shown in the demo: a diff in the product's existing diff idiom (the
`SpecDiff` visual language from the History tab), each change carrying an
inline marker whose hover shows the assistant's rationale and the evidence
behind it (rating comments, run references), and three actions — **Accept**
(into the draft; for a skill, the proposal's Apply, labelled as the live
change it is), **Edit** (open pre-filled in the ordinary editor), **Dismiss**
(recorded). A chip summarises the batch: "4 suggestions · from 6 👎 across
22 runs". For skills this grammar is what Decision 2's additive columns and
an Edit action on the Skills review card exist for — the current
Review/Apply/Discard surface carries no evidence and no pre-filled edit.

Where it lives in the Builder: an assistant strip on the **Build** tab above
the instructions card (diff renders in place of the editor while reviewing),
and the same treatment on **Toolbox** tool rows for description proposals —
which already have the "overridden" visual (brand left-rail) to inherit.
Skills proposals stay on the Skills page where they already render.

Per the walkthrough rule, the new strip and the Improve action owe `tour.ts`
stops (gated on `agents:edit`, `optional: true` — the strip renders only when
proposals exist) in the same change.

## Decision 8 — two directions, one grammar: the assistant also verifies

Improvement flows both ways. Beside *assistant proposes → person decides*
(Decisions 2 and 7), a person who edited the draft by hand can ask the
assistant to **verify** their changes: the same improver agent, handed the
diff between the current draft and the last published version plus the same
evidence, answers with a critique — what the edit improves, what it risks,
and what it silently removed ("you dropped the language-matching line; two
👎 were about answering Polish customers in English").

The verdict is a report, and anything actionable in it is an ordinary
proposal hunk — same table, same review grammar, same accept path, with one
supersession carve-out: verification findings **merge into the open batch**
rather than superseding it, because Verify is offered while Improve
suggestions may still be pending, and "a later run supersedes" would let a
critique silently discard suggestions the person has not reviewed. Only a
full improver run replaces the batch. No second mechanism otherwise:
verification is the improver run with a different injected resource (the
human's diff instead of a blank slate), so budgets, Activity and the org
switch (Decision 10) cover it for free.

*Rejected: a blocking "AI gate" on publish — a verdict that could refuse a
publish makes the assistant an authority over people, which inverts the
platform's model. The critique informs; `validate_spec` and a person decide.*

## Decision 9 — replay: test a draft against the prompts users already sent

> **Reframed by #52.** Replay is an eval run over a dataset made from real
> conversations: tool calls answered from the recordings by #2112, the draft
> run and the comparison by #2113, stamped `eval` rather than `REPLAY`. The
> rules below are the contract those issues keep. Pairs come from a dataset a
> person curates, so the relevance picker is not built in this milestone.

After editing (either direction), a person can run the candidate spec against
**real past prompts of this agent** and compare answers side by side: the
cases of a dataset made from real conversations, the old answer from
history, the new answer from the candidate, a human verdict per pair with an
optional judge suggestion. This is evaluation grounded in
data the org already owns — no synthetic dataset, no ground-truth question.

The three hard edges, decided here:

- **A replay must never re-fire a side effect.** The original run may have
  sent a message or written a file; replaying it must not do it twice. Tool
  calls are answered **from the recording**: `tool_calls` rows and the run
  manifest hold the original arguments and results, and a replayed call is
  matched by **stable tool id, normalized arguments and occurrence order** —
  where the stable id is *resolved*, not read: `tool_calls` and the manifest
  record only the effective, possibly overridden name, so matching maps each
  side through its version's stable-id → effective-name table (the recorded
  side through the frozen version, the candidate side through the candidate
  spec), and a candidate that merely renames a tool still matches its own
  recorded calls. A same-tool call with different arguments is a mismatch,
  because serving it an unrelated recording (`get_order(999)` answered with
  `get_order(4512)`'s result) would fabricate the very improvement or
  regression the comparison exists to measure. Any mismatch — different
  arguments, a repeated call past the recorded occurrences, or a tool the
  original never called — leaves the call *not executed* and marks the pair
  **divergent**; the reviewer sees what the new prompt reached for.
  Divergence is a finding, not a failure; read-only capability calls
  (knowledge search) may be allowed live behind a config, side-effecting
  ones never.
- **A replay runs the candidate, which is a draft.** Two ways to get there:
  teach `prepare` to accept an explicit spec (a `spec=` escape hatch beside
  `get_runnable_spec`, used only by replay and gated accordingly), or
  publish the candidate into a shadow environment and replay via the
  existing `environment_id` path. The lean is firmly the explicit spec —
  versions are the product's audit trail and test noise does not belong in
  it, and the shadow path is unsafe as currently built: `publish` calls
  `_move_environments_that_follow`, so every tracks-latest environment
  (a dev bot, any following surface) would move onto the unreviewed
  candidate; that alternative is viable only with a promotion-free
  version-mint that does not exist today. Question 6 stands with that
  weight on it. The explicit-spec path carries three obligations of its
  own:
  - **validation first**: a draft skipped `validate_spec` on save, and the
    resolvers downstream of `prepare` deliberately trust that a published
    binding was already authorized — so replay runs the candidate through
    the full caller-scoped reference-and-permission validation before
    assembly, or an editor could exercise a collection, skill or secret
    through replay that they could never publish;
  - **honest attribution**: `_assemble` falls back to
    `agent.current_version_id`, which would book every candidate run to a
    published version it did not execute — replay runs carry **no**
    `agent_version_id` and link the session's candidate snapshot instead,
    so Activity and `usage_by_version` never absorb candidate answers;
  - **a frozen candidate**: confirming the preview captures an immutable
    snapshot of the candidate (the spec, or the skill body + resources,
    with its revision), and every pair runs that snapshot — a Builder
    autosave or a replaced skill proposal mid-session must not make pair
    four answer for different content than pair one under a single
    aggregate verdict.
- **A pair holds everything constant except the edited variable.** The
  historical answer may have run on a per-turn model override, and skills
  or context files may have changed since the source run — so the candidate
  side of a pair runs the **recorded model** (a pair whose recorded model
  no longer resolves is excluded and reported, or explicitly marked) and
  rebuilds its non-edited resources from the source run's manifest and
  recordings, replacing only the field under evaluation. Otherwise the
  comparison attributes a model swap or a context edit to the instruction
  change it is supposed to measure.
- **Replay runs are runs.** Metered against the agent's and the org's caps
  (a replay of twenty prompts is a visible, bounded spend, shown before the
  button fires), recorded through `finish`, and stamped `eval` like every
  other eval run — a replay stamped `WEB` would lie to anyone asking how the
  product is used, and a separate replay member would split one kind of
  run across two surfaces in eval analytics.

**Skills replay the same way, with a cheaper mechanism.** A skill is read,
not executed, so "test the new skill body" means replaying runs that *loaded*
it — queryable from `tool_calls`, with one care: `tool_name` records the
**effective, per-binding name**, which an override may have renamed, so the
lookup resolves each run's frozen agent version for its stable-id →
effective-name mapping and matches `load_skill` through that, then inspects
the skill argument — never a literal `tool_name = 'load_skill'` sweep, which
silently misses every renamed binding. Each pair replays under **its own
recorded agent version** (a skill is
bound to many agents; the honest comparison holds the agent constant per
pair) with the candidate injected as a **resource override** — skills reach
a run through `resources["skills"]`, so no spec change and no publish
question arises at all. Two wrinkles, both about serving the candidate
whole: the replay toolset answers `list_skills`, `load_skill` **and**
`read_skill_resource` for the edited skill from the **complete candidate
snapshot** — body *and* resources, since a proposal can replace both, and a
newly added resource is candidate content, not a divergence — while serving
everything else from the recording. And a skill is often loaded
mid-conversation, where the source answer depended on earlier turns: such a
pair replays with the **recorded conversation prefix** up to the source
turn — an immutable copy fed as history; the original conversation is never
touched — so the candidate answers the same situation, not the same
sentence out of context.

Comparison results live on the eval run (#2113) — keyed to its **target
(kind + id: agent or skill)**, not to one agent, because a skill run's
pairs deliberately span the agents that loaded it; each pair persists its
source agent, source run and the dataset case it came from, and the run
holds the frozen candidate snapshot, the verdicts and the spend. Readable
under `runs:view`; verdict writes take the run's creator or the target's
edit permission (Decision 4). Human verdicts **start unset** — the judge's
suggestion is displayed beside them, never written into them, and the
aggregate counts only what a person actually decided. The demo shows the
comparison view.

### Deferred: the relevance picker

**Deferred, not built in this milestone.** Replay pairs come from a dataset a
person curated (#2110, #2114); #2112 and #2113 select nothing. The design
below is kept as the record for a later picker that proposes cases into a
dataset, and is no obligation on any child of #52.

**The replay set is picked for relevance to the edit, capped small — and the
pool is capped before anything embeds.** Five pairs by default, because the
point is "does the edited fragment now work", not coverage. The candidate
pool is this agent's past opening prompts (for a skill, the prompts of runs
that loaded it), bounded **deterministically before embedding** — a recency
window and a hard count (rated-down candidates admitted first), because a
long-lived agent can hold hundreds of thousands of conversations and "a few
hundred candidates" must be a rule, not a hope; the picker reports how many
older candidates the cap excluded. Three further exclusions, each reported
the same way: **prompts that carried attachments** (the recorded answer was
produced from routed file contents the replay cannot faithfully re-supply),
**prompts with no persisted assistant answer** (a failed, budget-blocked or
cancelled source run keeps the question and nothing to compare against),
and prompts without a usable recording. Reconstructing recorded attachments
is future work, not a silent approximation. Selection ranks the pool by
semantic similarity to **the edit as its surface expresses it** — the
instruction hunks' `old_text`/`new_text`; for a tool-description proposal,
the base and candidate descriptions, preferring prompts of runs that
actually called that stable tool; for a skill proposal, the body diff —
embedded **on demand** through the shared embedding client
(`services/rag/embeddings.py`). Nearest-neighbour ranking gives the wanted
fallback for free: editing the border-collie paragraph of a dog-expert
agent surfaces border-collie conversations first and other-breed
conversations next, because that is what cosine distance means. **Which
credential embeds is an explicit org setting**, not a borrowed one: there
is no single org-wide RAG credential to reuse — embedding resolution is per
*collection*, and a replay candidate belongs to none — so an
authoring-embedding choice sits in organization settings beside Decision
10's switch, and while it is unset selection degrades honestly to lexical
match (Postgres trigram/full-text) and then to rated-down-first,
most-recent. The picker always *says* how each pair was chosen, so an
off-topic set is visible rather than silently unrepresentative. No standing
index and no schema change: a few hundred candidates embed in one batch per
replay setup — and because that batch already costs money, **consent comes
before selection, not after it**: the button opens the preview first
(estimated selection cost and estimated run cost together), and confirming
creates the replay session, into which the selection embedding is metered.
Deliberately **not** the RAG pipeline itself: conversations are never
ingested into a knowledge collection — that would leak chat into retrieval;
only the embedding client is shared.

## Decision 10 — an organization switch, off means off

Whether AI assists authoring at all is the organization's decision, not the
platform's default-on. A single org-level setting (in organization settings,
gated on `org:settings` like the rest of them) turns AI assistance off, and
the backend then refuses **every model-backed entry point** in the service
that starts it:

- the assistant: Improve, Verify, Replay, and mode 1's describe→draft run,
  which is AI-assisted authoring as much as the other three (#2117);
- the LLM judge, whether a person starts the eval run or a suite trigger
  does (#2111, #2115);
- the case generator (#2114);
- the knowledge-gap report's drafted content (#2119).

The frontend hiding the controls is a courtesy; the service refusal is the
boundary, in exactly the "not rendered is not enough" sense the permission
rules already state. A refused judge leaves an eval run with deterministic
checks only — evals with no model-backed scorer, and a person's verdicts,
stay available while the switch is off. The seeded improver, judge and
generator agents stay (they are data); they just cannot be started.

One switch in v1. Granularity (proposals yes / replay no, or per-surface)
is question 7 — cheap to add later, expensive to guess now.

## Work breakdown (phase 1, in review order)

> The schedule is now #52's children (see
> [Which issue owns each decision](#which-issue-owns-each-decision)). The
> slices are kept for the tests each one owes; slice 7 is owned by #2112 and
> #2113.

1. **Read path** — org-scoped resolvers: ratings-for-agent
   (`message_ratings` → `messages.agent_id`, the tenant through
   `conversations.organization_id`, the `get_rating_summary_scoped` shape),
   runs, manifests, transcripts. Repo functions take `organization_id` and
   are added to the executable audit's `TENANT_REQUIRED`.
2. **`spec_proposals`** — model (one open batch per agent; per-hunk status +
   decision metadata; positional anchors with context; `rationale`,
   `evidence` JSONB; base snapshots for hunks *and* tool-override entries
   keyed by `(capability_id, tool_id)`), the draft-revision column and its
   optimistic concurrency check, the additive `skill_proposals` columns and
   the per-proposer supersession key, migration, service
   (list/accept/dismiss/undo; accept writes the draft via the registry
   service), routes. Tests: mixed per-hunk decisions on one batch; two
   tool-override entries survive in one batch; concurrent Accept and
   Dismiss of one hunk resolve to exactly one outcome; an Accept or Undo
   racing the supersession of its batch either commits before the batch
   closes or is refused, never changes the draft after it; undo while open,
   terminal at close, and undo goes stale when the accepted text was
   manually edited; a duplicate-text anchor and an empty-`old_text`
   insertion resolve by position or go stale, never apply at the wrong
   place; a stale tool-override base refuses to apply; a stale-revision
   draft write is refused; an older run's batch never supersedes a newer
   one; a stale skill proposal (base version advanced) refuses to apply;
   an evidence reference outside the target is dropped at staging; an
   improver skill proposal does not replace another agent's pending one;
   cross-tenant 404; accept lands in draft and never publishes.
3. **Capability `authoring`** — registry entry (`selectable=False`), read tools
   over injected resources, `propose_*` staging; runner assembly for the
   authoring surface + recording in `finish`; `read_skill` over the
   injected skill snapshot; the mode-1 catalogs. Tests: capability builds
   `None` with neither a target nor a mode-1 session injected; a mode-1
   build narrows to `read_catalog` and `propose_agent`, and its catalog
   holds only what the caller can see; a mode-1 reference outside the
   catalog is refused at staging; a skill run injects the current body and
   resources only after `skills:edit` on that skill passes, and is refused
   without it; staged proposals recorded once across turns; publish
   refuses a spec carrying the capability.
4. **Seeded improver agent** — created at org creation, topped up like the
   skill library; the Builder "Improve" endpoint starting its run with the
   target injected (gates per Decision 4). Tests: budget metered, run lands in
   Activity, degrades honestly when the org has no model profile.
5. **Mode 1** — `propose_agent` → draft creation on the promote path, with
   the conversation-scoped draft identity. Tests: draft only, owned by the
   caller, publish untouched; a later turn updates the same draft instead
   of creating a sibling.
6. **Verify direction** — the diff-in resource and the critique output
   (Decision 8); actionable findings land as ordinary proposal hunks. Test:
   a verify run with the switch off is refused; a critique proposes, never
   writes.
7. **Replay** — the replay toolset answering from `tool_calls`/manifest
   recordings, divergence marking, the candidate-spec path chosen in review
   (validated caller-scoped before assembly, no `agent_version_id`
   attribution, frozen candidate snapshot per session), the recorded-model
   and recorded-resources constancy per pair, the skill candidate served
   whole (body + resources across `list_skills`/`load_skill`/
   `read_skill_resource`), the conversation-prefix replay for later-turn
   skill pairs, pairs taken from the cases of a curated dataset (no
   relevance selection — see
   [Deferred: the relevance picker](#deferred-the-relevance-picker)), runs
   stamped `eval`, the run + pair-verdict rows keyed to the target kind,
   spend preview. Tests: a side-effecting tool is never executed on
   replay; a recorded result is served only on a stable-id +
   normalized-args + occurrence-order match, an args mismatch and an
   extra occurrence mark the pair divergent, and a candidate-renamed tool
   still matches through the id mapping; a divergent call is recorded and
   not fired; the edited skill's candidate body *and resources* are served
   while every other recording is served verbatim; a later-turn pair
   replays with its recorded prefix and mutates nothing; a renamed
   `load_skill` binding is still found; an unvalidated draft reference is
   refused before assembly; a replay run carries no version attribution;
   a mid-session autosave does not change later pairs; a replay run is
   stamped `eval`; no model call before the run-creating consent; replay
   spend meters against both caps; a pair's verdict write is refused for `runs:view`
   alone; cross-tenant prompt sourcing refused.
8. **The organization switch** — the org settings field + service refusal
   on every model-backed entry point (Improve, Verify, Replay,
   describe→draft, the judge, the case generator, the knowledge-gap draft)
   + frontend gating. Tests: off means each of those services refuses, not
   just the UI hiding, one test per entry point — including a judge started
   by a suite trigger; an eval run with only deterministic checks still
   runs while the switch is off.
9. **Frontend** — assistant strip + diff review (reuse `diff.ts` and the
   `SpecDiff` idiom), Toolbox proposed-description rows, accept/edit/dismiss
   wiring, verify report, replay comparison view, i18n keys, tour stops.
10. **Docs owed by the implementation, per the trigger map** —
    `docs/skills.md` and `docs/concepts.md` (named by the issue),
    `docs/reference/capabilities.md` (new capability),
    `docs/governance.md` (what improver and replay runs meter, the org
    switch). This plan lives in `docs/design/` and is excluded from the
    published site.

Each slice is a committable piece with its own tests; 1–2 are useful alone
(they finish the ratings story), 3–6 are the assistant, 7 is replay, 8–9 are
the governance switch and the surface.

## Out of scope, deliberately

The synthetic-dataset harness was listed here; #52 moved it into scope
(#2110, #2111, #2114, #2115).

- Auto-accept, auto-publish, or any write outside the draft/proposal path —
  including apply modes that let a change go live without a person.
- An optimizer engine (GEPA/DSPy) — future work, outside milestone #21.
- A verdict that can block a publish (Decision 8's rejected alternative).
- Trace ingestion or a Logfire dependency of any kind.
- MCP tool descriptions — they come from the connected server, not the spec;
  improving them means writing to somebody else's catalog.
- Scheduled/triggered improver runs (the heartbeat could fire one later; v1 is
  manual so the cost is a person's decision).
- A dev dataset whose results the improver may read — future work; in this
  milestone the improver sees no eval results at all.
- SoL-Pi's harness mechanisms (ObservationPack, context compaction, Action
  Fusion, the reducer) — see
  [Considered after review, and rejected](#considered-after-review-and-rejected).

## Open product questions — answered

All nine are answered in [Resolved](#resolved).

1. **Is the seeded improver visible in the Agents list** (this plan: yes,
   editable, its prompt improvable by itself) or a hidden system row?
2. **Should Accept carry an approval gate** on top of `agents:edit`? This plan
   says no — the draft *is* the review stage, and publish is the second gate —
   but an org that wants four-eyes on drafts might disagree.
3. **Where mode 1 lives**: a "Describe it" panel in the create dialog, or a
   chat-first flow that ends in a draft? The demo shows only mode 2; mode 1's
   surface is cheap to decide late.
4. **A default budget cap on the seeded improver** — it meters like any agent;
   should the seed ship with `budget.monthly_usd` set so a new org cannot burn
   its org cap on self-improvement?
5. **Proposal retention** — decided proposals kept forever (the audit-trail
   argument) or swept after N days (the clutter argument)?
6. **How replay runs a draft** — the explicit-spec escape hatch in `prepare`
   (this plan's lean: version history stays clean) or a shadow environment
   publish (reuses more, pollutes versions). Decision 9 has both halves.
7. **Switch granularity** — one org-level toggle (this plan) or per-surface
   (proposals / verify / replay separately)?
8. **Who judges a replay pair** — human-only verdicts in v1 with the judge
   suggestion off by default, or the judge on from the start? Judge calls
   cost money and add a second model opinion to govern.
9. **A standing embedding index over opening prompts** — on-demand embedding
   (this plan) re-embeds the candidate pool on every replay setup; a stored
   pgvector column would make selection instant but adds a schema change, an
   ingestion cost on every conversation and a backfill. Defer until replay
   usage shows the on-demand batch actually hurts?

## The demo, audited — the contract the implementation must keep

A full functional pass over `authoring-assistant-demo.html` (2026-08-25),
checking every number, state and flow against itself, against this plan and
against the real product's mechanics. Four inconsistencies were found and
fixed in the demo in the same change; everything else below is recorded so
the implementation does not quietly lose it.

### Fixed in the demo during the audit

- **"3 of 5" vs "3 of 6"** — one popover counted comments where its chip
  counted ratings. Unified on ratings ("3 of 6 👎"); the rule for the real
  UI: an evidence chip counts *ratings*, and prose that means comments says
  "comments".
- **Dismiss all missed the Toolbox suggestion** — the chip counts pending
  suggestions across both tabs, so the button now clears both. Rule: the
  strip's numbers and its bulk actions share one scope.
- **The divergent replay pair showed a finished answer** — impossible, since
  the divergent call is never executed; a run stops there. The pair now
  shows the attempted call and "not executed — side effects never replay",
  and stays judgeable (choosing to escalate *is* the improvement).
- Static tab-count fallback disagreed with the computed one; "6 rated
  answers" now says "rated-down".

### Contract — behaviour the demo shows and the implementation owes

1. **Entry conditions.** Verify and replay exist only while the draft
   differs from the published version; the strip renders only under
   `agents:edit`, evidence reads require `runs:view`, and the org switch
   (Decision 10) removes every AI-assisted entry point server-side.
2. **View semantics.** "Current v*N*" is the published version, always.
   "Review" diffs the current draft plus pending hunks; an accepted hunk
   joins the base and stops being highlighted. "Proposed" is a preview of
   the draft with every pending hunk applied — a projection, never a stored
   state.
3. **Verify lifecycle is run status.** The button's three states map to the
   improver run's status (`running` → spinner, terminal → "See results" +
   a fresh "Verify my edits"); the frontend subscribes the way Activity
   does and needs no state machine of its own. Old results stay reachable
   during a re-run; a finished re-run replaces the report under the new
   run's id.
4. **A re-run analyzes the current draft.** The demo restores a static
   findings template on re-run; the real report is regenerated, so a
   finding the person already fixed (e.g. via "Restore the line") must not
   reappear.
5. **"Restore the line" edits the draft** — so the Review diff changes with
   it. The demo does not redraw the diff; the implementation must.
6. **Undo of an accepted hunk returns the assistant's original proposal**
   to pending — while the accepted text still stands in the draft; a manual
   edit of that text makes Undo stale (Decision 2). The demo keeps the
   user's edited text after undo; the real rule is that Edit-then-accept is
   one decision and undo reverses the whole of it.
7. **Replay runs the accepted draft** (draft vs published, manual edits
   included), never pending hunks — those are checked on the proposed
   projection. Each pair names the dataset case it came from; the demo's
   "picked:" labels belong to the deferred relevance picker.
8. **A divergent pair is a stopped run**, shown as the attempted call, its
   arguments, and the not-executed notice — never a fabricated result, and
   never a silent stub. It remains judgeable.
9. **Spend preview before anything spends.** The demo opens the dialog with
   results; the real flow inserts "5 cases · estimated $X — run?" between
   the button and *any* cost, which is why confirming is what creates the
   eval run (Decision 9).
10. **Run references link.** Every `run #xxxx` chip in evidence, every
    replay pair and both improver-run badges resolve to the run detail in
    Activity, org-scoped; a foreign or deleted id renders as absent.
11. **Rating arithmetic must reconcile.** Per-suggestion evidence counts
    (3+2+1+2 "of 6") may overlap — one 👎 can evidence two hunks — but each
    must be a subset of the summary's total, and the strip, the verify
    card and the replay picker read the same numbers from the same rows.
12. **The strip's honesty line is real.** "No Logfire traces — worked
    without them" is Decision 1's degradation made visible; it renders
    whenever the trace read failed or was not attempted, and never blocks
    anything.
13. **"Run again" supersedes — by run start time.** A fresh improver run
    replaces the pending batch for its target; an older run finishing late
    never replaces a newer batch; decided hunks keep their state and are
    not re-proposed; verification findings merge, never supersede
    (Decision 8).
14. **Every string is a catalog key**, counts are ICU plurals (the chip is
    one message with two plurals), and the diff/marker glyphs (`+`, `−`
    U+2212) follow `SpecDiff`'s conventions.
15. **Costs shown are the runs' recorded costs** (`cost_usd`, with the `≥`
    partial-pricing mark where it applies) — the demo's flat `$0.03`/`$0.11`
    are placeholders, not a format.
16. **Human replay verdicts start unset.** The judge's suggestion is shown
    beside the control, never written into it; the aggregate counts only
    pairs a person decided, and undecided pairs are counted as undecided.

### Deliberate demo fakes — do not copy into the implementation

The 2-second verify timer · results appearing without a spend-preview step ·
the static findings template on re-run (contract items 4–5) · edited text
surviving undo (item 6) · the judge always on (the scorers configured per
dataset decide, #2111) · no stale-hunk example (Decision 2 defines the rendering) · no
"needs a model first" refusal state on the improver buttons (the seeded
improver may be an unpublished draft — feasibility note) · placeholder tabs.

## Resolved

Questions 6–9 were settled by #52 on 2026-10-12; 1–5 were decided on
2026-10-13. The milestone is built end to end and verified as a whole when
it is finished, so these answers are final for the implementation.

1. **The seeded improver is visible** in the Agents list, editable, and
   marked as a system agent; its prompt is improvable by itself. The judge
   (#2111) and the case generator (#2114) follow the same rule.
2. **No approval gate on Accept.** The draft is the review stage and publish
   is the second gate; an organization that wants four eyes on a change
   already has `agents:publish` and approvals.
3. **Mode 1 lives in the create dialog**, as a "Describe it" panel that ends
   in an ordinary draft.
4. **The seeded improver ships with a modest `budget.monthly_usd`**, editable
   like any agent's, so a new organization cannot spend its cap on
   self-improvement by accident. The judge and the generator ship the same
   way.
5. **Decided proposals are kept.** They are the record of why an agent
   changed. No sweeper in v1.
6. **A draft runs through the explicit-spec path** in `prepare`, with
   Decision 9's three obligations — #2113.
7. **One organization switch**, covering the assistant, case generation,
   the judge and the knowledge-gap drafts; deterministic evals stay
   available while it is off — #52.
8. **The judge is a scorer configured per dataset** (and per suite); a
   person's verdict is stored beside the judge's and never overwritten by
   it — #2111.
9. **No standing embedding index.** Pairs come from curated datasets (#2110,
   #2114), so the relevance picker that would have needed it is not built in
   this milestone.

The apply-mode toggle (Manual / Canary / Auto) is rejected; see
[Considered after review, and rejected](#considered-after-review-and-rejected).
