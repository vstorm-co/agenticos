# Authoring assistant — plan first (#52)

A system that helps people **write** agents, not only run them: instructions in
the Builder, skill bodies, tool descriptions. Two modes — *describe → draft
agent* and *improve an existing agent from evidence*. This is the plan the issue
asks for, written for review by @DEENUU1 before any implementation. A companion
demo of the review UI is beside it: `docs/design/authoring-assistant-demo.html`.

The one-sentence design: **the assistant reads the org's own run record and
ratings, proposes changes as evidence-backed diffs — or verifies changes a
person made by hand — and everything lands in a draft a person reviews,
replays against real past prompts, and publishes; it writes nothing on its
own, and an organization can switch it off entirely.**

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
  - `instructions`: **a base snapshot plus a list of anchored hunks**, each
    `{old_text, new_text, rationale, evidence}`, decided independently.
    This deliberately diverges from `skill_proposals`' whole-body shape,
    because the decision differs: a skill proposal is accepted or discarded
    whole, where a prompt review is per-change — the demo's Accept / Edit /
    Dismiss on each suggestion is the product. Staleness is handled openly
    rather than avoided: a hunk applies only while its `old_text` still
    matches the current draft; a hunk whose anchor is gone renders as
    *stale* with a side-by-side view, never applies silently. The UI
    computes the visible diff with the existing `frontend/src/lib/diff.ts`.
  - `tool_override`: `capability_id` + stable `tool_id` + the proposed
    `description` (and rarely `name`) — the same two fields
    `ToolOverride` carries, so acceptance is a two-field write into
    `capabilities[i].tool_overrides[tool_id]` that must survive
    `_tool_override_problems` at publish.
- Each hunk carries `rationale` (one paragraph, the assistant's argument)
  and `evidence` (JSONB: rating ids, run ids, the numbers behind "3 of 5 👎") —
  rendered in the review UI as the hover popover the demo shows, resolved
  through org-scoped reads so a stale or foreign id renders as absent, never
  as a leak.
- **Accepting must not race the Builder's autosave.** The Builder holds the
  draft client-side and autosaves the whole spec, so a server-side accept
  while the page is open would be clobbered by the next autosave. Accept
  therefore happens *in* the Builder: the client applies the hunk to its own
  state and the server write and query invalidation travel together.

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

## Decision 6 — synthetic evaluation is out; replay on real prompts is in

Synthetic datasets, a scoring function and result storage are a schema change
and a ground-truth question this issue should not carry — scoped out exactly as
the issue suggests. What *is* in scope is the evaluation the org's own history
already funds — Decision 9's replay — plus two things worth stating here:

- **The cheap loop already exists.** `rating_counts_by_version` answers "did
  the accepted change help" without any harness: after a proposal is accepted
  and published as v*N+1*, the assistant's next run can cite the v*N* → v*N+1*
  rating shift as evidence — the improvement loop closes on data we already
  keep.
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

## Decision 8 — two directions, one grammar: the assistant also verifies

Improvement flows both ways. Beside *assistant proposes → person decides*
(Decisions 2 and 7), a person who edited the draft by hand can ask the
assistant to **verify** their changes: the same improver agent, handed the
diff between the current draft and the last published version plus the same
evidence, answers with a critique — what the edit improves, what it risks,
and what it silently removed ("you dropped the language-matching line; two
👎 were about answering Polish customers in English").

The verdict is a report, and anything actionable in it is an ordinary
proposal hunk — same table, same review grammar, same accept path. No second
mechanism: verification is the improver run with a different injected
resource (the human's diff instead of a blank slate), so budgets, Activity
and the org switch (Decision 10) cover it for free.

*Rejected: a blocking "AI gate" on publish — a verdict that could refuse a
publish makes the assistant an authority over people, which inverts the
platform's model. The critique informs; `validate_spec` and a person decide.*

## Decision 9 — replay: test a draft against the prompts users already sent

After editing (either direction), a person can run the candidate spec against
**real past prompts of this agent** and compare answers side by side: the
opening user messages of recent conversations (rated-down ones first), the
old answer from history, the new answer from the candidate, a human verdict
per pair with an optional judge suggestion. This is evaluation grounded in
data the org already owns — no synthetic dataset, no ground-truth question.

The three hard edges, decided here:

- **A replay must never re-fire a side effect.** The original run may have
  sent a message or written a file; replaying it must not do it twice. Tool
  calls are answered **from the recording**: `tool_calls` rows and the run
  manifest hold the original arguments and results, so a replay toolset
  serves the recorded result when the candidate calls the same tool, and
  when the candidate diverges — calls a tool the original never called — the
  call is *not executed*: the pair is marked **divergent** and the reviewer
  sees which tool the new prompt reached for. Divergence is a finding, not a
  failure; read-only capability calls (knowledge search) may be allowed live
  behind a config, side-effecting ones never.
- **A replay runs the candidate, which is a draft.** Two ways to get there:
  teach `prepare` to accept an explicit spec (a `spec=` escape hatch beside
  `get_runnable_spec`, used only by replay and gated accordingly), or
  publish the candidate into a shadow environment nothing user-facing points
  at and replay via the existing `environment_id` path. The first keeps
  version history clean; the second reuses more. Left open for review
  (question 6) with a lean toward the explicit spec — versions are the
  product's audit trail and test noise does not belong in it.
- **Replay runs are runs.** Metered against the agent's and the org's caps
  (a replay of twenty prompts is a visible, bounded spend, shown before the
  button fires), recorded through `finish`, and stamped with a new
  `RunSurface.REPLAY` — the member has a writer now, so it earns its place
  under the enum's own rule, and for the same reason `EMBED` exists: a
  replay stamped `WEB` lies to anyone asking how the product is used.

**Skills replay the same way, with a cheaper mechanism.** A skill is read,
not executed, so "test the new skill body" means replaying runs that *loaded*
it — and those are queryable today: `tool_calls` rows with
`tool_name = 'load_skill'` and the skill's name in `args`, joined to their
runs. Each pair replays under **its own recorded agent version** (a skill is
bound to many agents; the honest comparison holds the agent constant per
pair) with the candidate body injected as a **resource override** — skills
reach a run through `resources["skills"]`, so no spec change and no publish
question arises at all. The one wrinkle: the recorded `load_skill` *result*
is the old body, so the replay toolset must serve the candidate body for the
edited skill while serving everything else from the recording.

**The replay set is picked for relevance to the edit, capped small.** Five
pairs by default, because the point is "does the edited fragment now work",
not coverage — and the edited hunks say what to look for. Selection ranks
the candidate pool (this agent's past opening prompts; for a skill, the
prompts of runs that loaded it) by semantic similarity to the hunks'
`old_text`/`new_text`, embedded **on demand** through the org's existing RAG
embedding credential (`services/rag/embeddings.py`) — nearest-neighbour
ranking gives the wanted fallback for free: editing the border-collie
paragraph of a dog-expert agent surfaces border-collie conversations first
and other-breed conversations next, because that is what cosine distance
means. No standing index and no schema change: a few hundred candidates
embed in one batch per replay setup. Where the org has no embedding
credential, selection degrades honestly to lexical match (Postgres
trigram/full-text) and then to rated-down-first, most-recent — and the
picker always *says* how each pair was chosen, so an off-topic set is
visible rather than silently unrepresentative. Deliberately **not** the RAG
pipeline itself: conversations are never ingested into a knowledge
collection — that would leak chat into retrieval; only the embedding client
is shared.

Comparison results live on the replay session (a small table: candidate
hunks/spec/skill reference, prompt-pair verdicts, how each pair was picked,
spend), keyed to the agent and readable under `runs:view`. The demo shows
the comparison view.

## Decision 10 — an organization switch, off means off

Whether AI assists authoring at all is the organization's decision, not the
platform's default-on. A single org-level setting (in organization settings,
gated on `org:settings` like the rest of them) turns the assistant off: the
backend refuses Improve, Verify and Replay runs when it is off — the
frontend hiding the strip is a courtesy, the service refusal is the
boundary, in exactly the "not rendered is not enough" sense the permission
rules already state. The seeded improver agent stays (it is data), it just
cannot be started through the authoring surface.

One switch in v1. Granularity (proposals yes / replay no, or per-surface)
is question 7 — cheap to add later, expensive to guess now.

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
6. **Verify direction** — the diff-in resource and the critique output
   (Decision 8); actionable findings land as ordinary proposal hunks. Test:
   a verify run with the switch off is refused; a critique proposes, never
   writes.
7. **Replay** — the replay toolset answering from `tool_calls`/manifest
   recordings, divergence marking, the candidate-spec path chosen in review,
   the skill-body resource override, relevance selection (on-demand
   embeddings with the lexical and rated-down fallbacks, the picked-because
   label), `RunSurface.REPLAY`, the session + pair-verdict rows, spend
   preview. Tests: a side-effecting tool is never executed on replay; a
   divergent call is recorded and not fired; the edited skill's recorded
   `load_skill` result is replaced by the candidate body while every other
   recording is served verbatim; selection falls back in the declared order
   and labels each pair; replay spend meters against both caps; cross-tenant
   prompt sourcing refused.
8. **The organization switch** — org settings field + service refusal on all
   three entry points + frontend gating. Test: off means the endpoint
   refuses, not just the UI hiding.
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

- The synthetic-dataset harness (Decision 6 — phase 2, own milestone and
  schema); replay covers the "did it get better" question with real prompts.
- Auto-accept, auto-publish, or any write outside the draft/proposal path.
- A verdict that can block a publish (Decision 8's rejected alternative).
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

## Resolved in review — @DEENUU1

*(to be filled in during review; this section records the outcomes so the doc
stands as the final design rather than a set of proposals)*
