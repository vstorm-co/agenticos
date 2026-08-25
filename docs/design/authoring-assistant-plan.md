# Authoring assistant — plan first (#52)

A system that helps people **write** agents, not only run them: instructions in
the Builder, skill bodies, tool descriptions. Two modes — *describe → draft
agent* and *improve an existing agent from evidence*. This is the plan the issue
asks for, written for review by @DEENUU1 before any implementation. A companion
demo of the review UI is beside it: `docs/design/authoring-assistant-demo.html`.

The one-sentence design: **the assistant reads the org's own run record and
ratings, proposes changes as evidence-backed diffs, and everything it proposes
lands in a draft a person reviews and publishes — it writes nothing on its own.**

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
deployment unconditionally.

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

Logfire traces are **optional enrichment**, never a prerequisite.
`AgentSpec.observability` can point traces at a client's own Logfire project,
and `LOGFIRE_TOKEN` is `str | None` — so the assistant states plainly when
traces are unreachable ("no traces for this agent — working from ratings and
run outcomes") and proceeds. It never refuses for want of a trace, and a trace
read failing degrades to the table above, silently to the model and visibly in
the assistant's own output.

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

- **Skills** — reuse `skill_proposals` unchanged. Nothing new to build; the
  assistant writes skill files in its workspace and the existing
  `_propose_skill_changes` seam in `AgentRunnerService.finish` records them.
- **Instructions and tool descriptions** — a sibling table, `spec_proposals`,
  modelled on `skill_proposals` (org id, target `agent_id`, authoring
  `run_id`/`conversation_id`, status pending/accepted/dismissed, terminal
  decisions, one pending proposal per target — a later run supersedes it).
  Two target kinds:
  - `instructions`: the **whole proposed body**, same argument as skills — a
    stored diff rots as the draft moves; the reviewer compares two complete
    texts, and the UI computes the diff at render time with the existing
    `frontend/src/lib/diff.ts`.
  - `tool_override`: `capability_id` + stable `tool_id` + the proposed
    `description` (and rarely `name`) — the same two fields
    `ToolOverride` carries, so acceptance is a two-field write into
    `capabilities[i].tool_overrides[tool_id]` that must survive
    `_tool_override_problems` at publish.
- Each row also carries `rationale` (one paragraph, the assistant's argument)
  and `evidence` (JSONB: rating ids, run ids, the numbers behind "3 of 5 👎") —
  rendered in the review UI as the hover popover the demo shows, resolved
  through org-scoped reads so a stale or foreign id renders as absent, never
  as a leak.

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
| `read_agent_spec` | the target's draft + current published spec |
| `read_feedback` | ratings with comments for the target, org-scoped |
| `read_runs` | run metadata: status, error, tokens, cost, latency |
| `read_manifest` | what the model was handed on a given run |
| `read_transcript` | one run's messages + tool calls |
| `propose_instructions` | stages a whole-body instructions proposal |
| `propose_tool_description` | stages a tool-override proposal |
| `propose_agent` | mode 1: stages a new draft agent definition |

Two invariants carried over from the existing registry:

- **The capability never queries the database.** The runner resolves the
  target's data org-scoped and injects it via `CapabilityBuildContext.resources`
  — the same shape as `knowledge`, `context` and `skills`. The `organization_id`
  filter lives in the resolver, one place.
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
catches any new repo function that forgets. Evidence ids in a proposal resolve
through the same org-scoped reads when rendered; a foreign id is absent, not an
error, and cross-tenant reads answer 404 as everywhere else.

No new permission. The composition of existing gates already names each action:

| Action | Gate |
|---|---|
| Start an improve run on agent X | `runs:view` (the evidence) **and** `agents:edit` on X via `resolve_access` (the proposals aim at its draft) |
| Accept/dismiss an instructions or tool-description proposal | `agents:edit` on the target |
| Apply/discard a skill proposal | `skills:edit` (existing) |
| Publish the resulting draft | `agents:publish` (existing) |
| Mode 1: create the draft agent | `agents:edit` (the promote precedent) |

A new `authoring:*` permission would be a second name for authority these
already express. Owed tests: the cross-tenant refusal (an improver run in org A
cannot read org B's ratings/runs/manifests, in the
`test_org_scope_regression.py` style), and ownership-alone-is-not-access on
proposal decisions.

## Decision 5 — mode 1 produces a draft, never a version

*Describe → draft agent* reuses the promote-a-specialist shape verbatim: the
assistant's `propose_agent` output becomes an ordinary draft — name,
instructions, capability bindings, collection/skill references — owned by the
person who asked, subject to `agents:edit`, validated only when that person
publishes. It stops there, for the reasons `docs/concepts.md` already gives.

Trigger templates were considered as the non-AI alternative (a curated,
code-defined catalog pre-filling the create form) and kept as complementary:
templates answer "give me the usual shape", the assistant answers "design this
from my description". Neither replaces the other.

## Decision 6 — evaluation is out: phase 2, its own milestone

Synthetic datasets, a scoring function and result storage are a schema change
and a ground-truth question this issue should not carry — scoped out exactly as
the issue suggests. Two things belong in this plan anyway:

- **The cheap loop already exists.** `rating_counts_by_version` answers "did
  the accepted change help" without any harness: after a proposal is accepted
  and published as v*N+1*, the assistant's next run can cite the v*N* → v*N+1*
  rating shift as evidence — the improvement loop closes on data we already
  keep.
- **Phase 2 sketch, deliberately undesigned:** dataset rows (input, expected
  qualities), eval runs as ordinary runs so metering and Activity come free,
  scoring as a capability or a judge agent, results keyed on
  `agent_version_id`. Each of those is a decision for its own plan.

## Decision 7 — three surfaces, one review grammar

Instructions, skill bodies and tool descriptions get **one** review grammar,
shown in the demo: a diff in the product's existing diff idiom (the
`SpecDiff` visual language from the History tab), each change carrying an
inline marker whose hover shows the assistant's rationale and the evidence
behind it (rating comments, run references), and three actions — **Accept**
(into the draft / the skill-proposal apply), **Edit** (open pre-filled in the
ordinary editor), **Dismiss** (terminal, recorded). A chip summarises the
batch: "4 suggestions · from 6 👎 across 22 runs".

Where it lives in the Builder: an assistant strip on the **Build** tab above
the instructions card (diff renders in place of the editor while reviewing),
and the same treatment on **Toolbox** tool rows for description proposals —
which already have the "overridden" visual (brand left-rail) to inherit.
Skills proposals stay on the Skills page where they already render.

Per the walkthrough rule, the new strip and the Improve action owe `tour.ts`
stops (gated on `agents:edit`, `optional: true` — the strip renders only when
proposals exist) in the same change.

## Work breakdown (phase 1, in review order)

1. **Read path** — org-scoped resolvers: ratings-for-agent (two-hop join via
   `messages`→`conversations`, the `get_rating_summary_scoped` shape), runs,
   manifests, transcripts. Repo functions take `organization_id`; the
   executable audit holds them to it.
2. **`spec_proposals`** — model (modelled on `skill_proposals`, plus
   `rationale`, `evidence` JSONB, target kind), migration, service
   (list/accept/dismiss; accept writes the draft via the registry service),
   routes. Tests: terminal decisions, one-pending-per-target, cross-tenant 404,
   accept lands in draft and never publishes.
3. **Capability `authoring`** — registry entry (`selectable=False`), read tools
   over injected resources, `propose_*` staging; runner assembly for the
   authoring surface + recording in `finish`. Tests: capability builds `None`
   without injected target; staged proposals recorded once across turns;
   publish refuses a spec carrying the capability.
4. **Seeded improver agent** — created at org creation, topped up like the
   skill library; the Builder "Improve" endpoint starting its run with the
   target injected (gates per Decision 4). Tests: budget metered, run lands in
   Activity, degrades honestly when the org has no model profile.
5. **Mode 1** — `propose_agent` → draft creation on the promote path. Test:
   draft only, owned by the caller, publish untouched.
6. **Frontend** — assistant strip + diff review (reuse `diff.ts` and the
   `SpecDiff` idiom), Toolbox proposed-description rows, accept/edit/dismiss
   wiring, i18n keys, tour stops.
7. **Docs owed by the implementation, per the trigger map** —
   `docs/skills.md` and `docs/concepts.md` (named by the issue),
   `docs/reference/capabilities.md` (new capability),
   `docs/governance.md` (what an improver run meters). This plan lives in
   `docs/design/` and is excluded from the published site.

Each slice is a committable piece with its own tests; 1–2 are useful alone
(they finish the ratings story), 3–5 are the assistant, 6 is the surface.

## Out of scope, deliberately

- The evaluation harness (Decision 6 — phase 2, own milestone and schema).
- Auto-accept, auto-publish, or any write outside the draft/proposal path.
- Trace ingestion or a Logfire dependency of any kind.
- MCP tool descriptions — they come from the connected server, not the spec;
  improving them means writing to somebody else's catalog.
- Scheduled/triggered improver runs (the heartbeat could fire one later; v1 is
  manual so the cost is a person's decision).

## Open product questions — for review, none blocking

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

## Resolved in review — @DEENUU1

*(to be filled in during review; this section records the outcomes so the doc
stands as the final design rather than a set of proposals)*
