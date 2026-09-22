# #1793 — Workflows and Virtual Tables: end-to-end acceptance and documentation

Design for [issue #1793](https://github.com/vstorm-co/agenticos/issues/1793),
closing child of [#56](https://github.com/vstorm-co/agenticos/issues/56).
Depends on #1783, #1784, #1785, #1787, #1789, #1790, #1791, #1792 — every
other delivery design in this milestone except #1781/#1782 (already built)
and #1786/#1788 (consumed transitively through the eight above). This issue
adds no `NodeDefinition`, no model and no route of its own; its module is a
cross-cutting integration test suite plus the milestone's user/developer
documentation, built once every dependency has landed. Written 2026-09-22
against all ten dependency designs in `docs/plans/`, in full.

## Inconsistencies found while writing this

Cross-cutting integration is this issue's job, so the seams between the other
nine documents are its first finding, not a side effect. Five concrete
mismatches, plus three narrower ones the source documents already flag as
open toward #1786 without resolving:

1. **Operation-key / idempotency-key format disagrees between #1784 and
   #1788/#1790.** #1784's node surface derives a table write's operation key
   as `f"workflow:{run_id}:{node_instance_id}"` (or `...:{iteration_key}`
   inside a `foreach`). #1788's reconciler section and #1790 both define
   `NodeAttempt.idempotency_key` as
   `f"{organization_id}:{workflow_run_id}:{node_instance_id}:{scope_path}"`.
   Same purpose — a stable, per-attempt key derived from the run and node
   instance — different template: no `organization_id` in #1784's version,
   a literal `"workflow:"` string where #1788/#1790 put the real
   organization id, and `iteration_key` where #1790 says `scope_path`. A
   table-write node built against #1784's text and a reconciler built
   against #1788's would not agree on what "the same key" looks like.
   **Resolved** in the 2026-09-22 consistency pass: `1784-table-agent-tools.md`
   now says the node surface receives and reuses #1788's exact
   `NodeAttempt.idempotency_key` string rather than constructing its own.

2. **`Perm.WORKFLOWS_RUN` has no document that originates it.**
   `56-shared-contracts.md`'s resolved decision 4 (owned by #1786) commits to
   exactly three workflow permissions — `WORKFLOWS_VIEW`/`_EDIT`/`_CREATE` —
   and `1786-node-contracts.md`'s own permission section defines only those
   three. #1785 and #1792 both gate execution on `Perm.WORKFLOWS_RUN` as if
   it already exists; #1792 says it "joins the three shared-contracts already
   named" (implying #1792 itself adds a fourth), but `56-shared-contracts.md`
   was never updated to record that addition, and #1785 cites no origin for
   it at all. Whoever implements first has to invent where this permission's
   migration actually lives.
   **Resolved:** `56-shared-contracts.md` decision 4 and
   `1786-node-contracts.md` now both define `Perm.WORKFLOWS_RUN` as a fourth,
   resource-scoped permission, gating "may cause this workflow to run"
   separately from "may edit its graph."

3. **`WorkflowRun`'s causation columns are assumed by #1785 but absent from
   #1788's own model.** #1785 states "`WorkflowRun` carries `root_run_id`
   ..., `causation_run_id` ..., `visited_trigger_ids` ... and `depth`" as
   settled fact. #1788's own persisted-model section — the document that
   defines every `WorkflowRun` column — lists `id, organization_id,
   workflow_id, workflow_version_id, status, triggered_by, budget_limit,
   spent_cost, cost_is_partial, deadline_at, next_event_seq, paused_reason,
   error, started_at, ended_at` and nothing else. Four columns #1785's cycle
   detection depends on do not exist in the document that owns the table.
   **Resolved:** `1788-durable-execution.md`'s `WorkflowRun` model now carries
   `root_run_id`, `causation_run_id`, `visited_trigger_ids` and `depth`,
   populated in the same admission transaction #1785 already needs.

4. **The dependency-checker hook #1782 shipped is registered by none of its
   anticipated consumers.** `dependencies.py`'s own docstring (on #1782's
   branch) says "workflows, views and triggers will name tables and columns
   ... a feature that depends on tables registers a checker at import time."
   Of the three, #1783 (saved views reference column ids in `group_by`,
   `visible_columns`, `filters`), #1784 (`TableIORef` bindings inside a
   published `WorkflowVersion.graph`) and #1785 (`VirtualTableTrigger.filter`
   / `input_mapping` name column ids) are exactly the anticipated
   registrants — and none of the three design documents mentions
   `register_dependency_checker` at all. As designed today, archiving a
   column a saved view groups by, a workflow node binds, or a trigger
   filters on succeeds silently.
   **Resolved:** each of `1783-table-ui-views.md`, `1784-table-agent-tools.md`
   and `1785-table-created-trigger.md` now has its own "registers a
   `DependencyChecker`" section naming what it checks and what it returns.

5. **A "published workflow's own budget block" is used by #1788 but never
   modeled by #1786.** #1788's budget section says the parent cap is "the
   org limit, optionally tightened by the published workflow's own budget
   block." `1786-node-contracts.md`'s `Workflow`/`WorkflowVersion` field
   list — the document that owns that schema — has no budget-related field
   at all, on either model.
   **Resolved:** `WorkflowVersion.budget_limit` now carries this, named to
   match `WorkflowRun.budget_limit` exactly since its only job is to seed
   that column at run start.

Narrower, and already self-flagged by #1787 as "open questions for #1786"
rather than newly found here — still real, unresolved seams worth carrying
into this issue's own risk list since nothing downstream resolves them
either:

6. **`Port` has no direction.** #1786's `Port{id, label, schema}` carries no
   `kind`/direction field; #1787 infers input vs. output from an `in`/`out`
   naming convention as a stand-in and says so explicitly. No later document
   (#1789–#1792, which register the real ports) revisits this.
   **Resolved:** `Port` now carries `kind: Literal["input", "output"]`.
7. **`ScopeBoundary.body_node_ids` authorship is unresolved.** #1787 asks
   whether it is client-written (when a node is dropped inside a `foreach`
   view) or server-derived from edge topology at save time. #1790, which
   builds `control.foreach` directly on `ScopeBoundary`, uses the field as
   given and does not answer the question either.
   **Resolved:** server-derived, computed by `validate_graph`'s reachability
   pass and persisted as what the server computed, never trusted from the
   client — see `1786-node-contracts.md`'s graph-model section.
8. **The admission entry point's name is inconsistent even within #1792.**
   #1792's module layout names it `facade.admit_from_*()` (one function per
   adapter); its own prose and commit-order section call it `admit()`
   (singular, shared). #1785 inherits the singular spelling
   ("calling #1792's own `admit()`"). Minor, but the two names imply
   different call shapes for #1793's fixture to drive.
   **Resolved:** standardized on `admit()`; the module-layout line in
   `1792-channel-adapters.md` no longer says `admit_from_*()`.

None of these block writing this design — each is noted at the point below
where it matters — but each is a real disagreement or a real gap, not a
stylistic difference, and belongs on record before implementation starts on
any of the nine dependency issues.

## Scope

Four executable end-to-end journeys with recorded demonstrations;
cross-surface table parity; schema-change protection; publication/version
pinning under concurrent edits; budget parity between agent-direct and
workflow-driven spend; cancellation and access-revocation at every boundary
named below; a consolidated crash-injection matrix; user and developer
documentation. No new `NodeDefinition`, model or route — new code is
`backend/tests/integration/test_workflow_e2e_*.py` (one file per journey, on
the Postgres-integration harness `test_run_commit_boundary.py` already
establishes), `frontend/e2e/workflows-*.spec.ts` (Playwright, recording the
"concrete evidence, not only happy-path screenshots" acceptance criterion),
and the `docs/` pages under Documentation below.

## The four end-to-end journeys

Each runs against a real Postgres, a real Prefect worker pool and #1788's
actual dispatcher/reconciler — never a mocked executor — since restart,
permission and budget behavior is what these criteria check.

### Journey 1 — `/chat` → `knowledge.search` → `agent.run` → answer

Exercises #1786 (`WorkflowInputPayload`/`WorkflowOutputPayload`), #1788 (the
dispatcher advancing three nodes, event streaming with cursors), #1789
(`knowledge.search` against a seeded pgvector collection, `agent.run` pinned
to a published version), #1792's `/chat` adapter (session-bound admission,
reply on the same connection). Graph: `core.input → knowledge.search →
agent.run → core.output`; a dashboard user asks a question a seeded
collection answers.

Assertions beyond "a response appeared": `WorkflowRun.workflow_version_id` is
the version pinned at publish, not whatever is currently draft;
`knowledge.search`'s stored output holds the seeded document's `SourceRef`
with the right `document_id`; `agent.run`'s prompt includes the retrieved
sources, not just the raw question; exactly one `agent_runs` row exists, at
the pinned `agent_version_id`, never "current"; the `/chat` client gets the
terminal event over the connection it opened, with no `workflow_run_id`
exposed before admission commits; a disconnect/reconnect with
`after=<cursor>` replays only the missed `WorkflowEvent.seq` range.

### Journey 2 — two agents in sequence

Exercises #1789's `agent.run` twice and #1786's rule 3 (type-compatibility)
binding one agent's output into the next agent's input. Graph: `core.input →
agent.run(A, v1) → agent.run(B, v1) → core.output`, B's prompt bound to
`NodeOutputRef{node_id: A, port: "out"}` — A's `text` (`str`) into B's
`prompt` (`str`), the case rules 3 and 4 must both accept.

Assertions: two distinct `agent_runs` rows in causal order, each pinned to
its own `agent_version_id`; B's `NodeAttempt` input snapshot holds A's
literal output, not a re-derived value; a variant binding B's input to A's
`sources` (`tuple[SourceRef, ...]`) instead is refused at publish with a
rule-3 `GraphValidationError` naming the edge — the negative case that
proves the check runs; `WorkflowRun.spent_cost` equals the sum of both
`agent_runs.spent_cost` under `for_delegate` attribution, neither doubled
nor missing either run.

### Journey 3 — API-created lead → table trigger → analysis → update → notification

Exercises #1782/#1783's real `/api/v1/tables/{id}/records` route, #1785 (the
outbox consumer, atomic admission, causation tracking), #1789's `agent.run`
plus `http.request` or `notification.send`, #1784's `table.record.update`
node. A "leads" table with a `record.created` trigger; a record is created
through the table's own already-real API route — deliberately **not**
through #1792's workflow-invocation API adapter, which cannot ship for real
yet (#1792 names the public-API auth gap as its own open dependency, the
same gap #1782's consistency review names for external table access,
tracked as #1795 outside this milestone). **This journey's "API" leg is the
table-record API, which is real today; a "create a lead by invoking a
workflow directly" variant stays blocked until the public-API effort
lands.** The trigger runs `agent.run` (score), `http.request`/
`notification.send` (act on it), then `table.record.update` writes the
score back.

Assertions: exactly one `WorkflowRun`/`TableTriggerAdmission` (`QUEUED`) per
record under a concurrent-poller race, the loser resolving via the
`(trigger_id, outbox_event_id)` constraint; the workflow's own
`table.record.update` write does **not** re-fire the trigger
(`visited_trigger_ids` blocks the re-entry, asserted against the admission
history, not inferred from record state); the create API's `201` response
never carries a `workflow_run_id` or any hint a trigger fired, per #1792's
frozen-destination rule #1785 must not special-case; the admission-history
endpoint shows the `QUEUED` row without leaking the record's own field
values.

### Journey 4 — multi-file foreach → conversion → agent → Python → upsert → report

Exercises #1791's file/Python nodes inside #1790's `control.foreach`,
#1784's `table.record.upsert`, #1789's `agent.run` — the fixture graph
#1791's own test plan already names as reused here, built once. Graph:
`core.input(files) → control.foreach → {text.extract → convert.text_to_file
→ agent.run(summarize) → code.python.sandbox(normalize) →
table.record.upsert} → core.output(report)`, four files: two clean PDFs, one
scanned PDF (no text layer), one corrupt DOCX.

Assertions: `item_error_policy="collect"` yields a four-slot result — the
scanned PDF's slot `Failed(code="text_extraction_needs_ocr")`, the corrupt
DOCX's `Failed(code="document_corrupt")`, both clean files complete, the
report enumerating all four; each upsert's `external_id` is per-file, so
four distinct rows exist with zero `REVISION_CONFLICT`s under sequential
(rule 8) iteration; a kill between iteration 3's `code.python.sandbox`
result persisting and the loop's advance-or-finish commit resumes at
iteration 4 on restart, re-dispatching neither iteration 3 nor a duplicate
sandbox session (checked by session count on the deterministic key, not
final state alone); the sandbox's full log lands as a `WorkflowFile`-backed
`FileRef`, never inline — the typed `stdout_tail` must be strictly shorter
than the persisted log's byte size.

## Cross-surface table access and saved views

The same record, read and written identically through #1783's grid/kanban/
list UI, #1784's agent tool (`table.records.*`), #1784's workflow node
(`table.record.*`) and the public API: create via the UI, read the identical
row via a tool call and `table.record.query`, update via the node, confirm
the UI refetch matches — all against one `VirtualTableService`, so there is
exactly one place conflict/validation/audit logic could diverge. **The
public API leg is blocked**, per Journey 3's note — the parity test covers
UI/tool/node today and documents the API leg as an explicit gap, not a
silently dropped fourth column, until #1795 lands.

Saved views surviving a schema change: a kanban view grouped on a
`single_select` column must still resolve after a nullable column is added
or an *unrelated* column is archived (§1783's "rename the grouping column"
test extended). A schema change archiving the view's own `group_by` column
is where the dependency-checker gap (finding 4) bites: since none of
#1783/#1784/#1785 registers against it today, this archive currently
**succeeds**, silently breaking the view. The fixture asserts the intended
behavior (refusal, naming the view) and, until registration lands, is
marked `xfail` with a comment pointing at this section — not dropped, so it
flips green the day the gap closes.

## Revision conflicts surfaced consistently

`expected_revision` conflicts happen at independent layers — table records
(#1782/#1783), workflow drafts (#1786/#1787) — and #1793 confirms they
present the *same shape* everywhere: `409`, `{"message": "...changed by
someone else...", "details": {"<resource>_id", "expected_revision",
"current_revision"}}`. One shared fixture PATCHes twice with the same
first-read revision against both a table record and a workflow draft and
asserts identical `details` key names across both routes — proving the two
independently-designed resources converged on one conflict contract.

## Schema changes checked against dependent workflows/triggers

This is the dependency-checker hook's first real exercise (finding 4, above)
— #1782 shipped `register_dependency_checker`/`find_dependents` with nobody
registered, "so that the day one does, archiving a column it reads is
refused instead of silently breaking it." #1793 is that day. What needs
registering, by whichever issue's implementation lands it (most naturally
#1784 for workflow bindings and table-node graphs, #1785 for trigger
filters/input-mappings, #1783 for saved views — three checkers, not one,
matching the hook's own multi-registrant design):

- A checker walking every **published** `WorkflowVersion.graph` (draft graphs
  are not yet live, so they do not block an archive) for `TableIORef`
  bindings naming the table/column, returning `Dependent(kind="workflow",
  id=workflow_id)`.
- A checker over `VirtualTableTrigger.filter` and `input_mapping` naming the
  table/column, returning `Dependent(kind="trigger", id=trigger_id)`.
- A checker over `TableView.config` (`group_by`, `visible_columns`,
  `filters`) naming the column, returning `Dependent(kind="view",
  id=view_id)`.

#1793's test: archive a column bound by each of the three, assert
`SchemaDependencyError` naming the right `kind`/`id` for each, then archive
an *unbound* column on the same table and assert it succeeds — proving the
check is column-scoped, not table-wide.

## Publication and version pinning

Editing a workflow after a trigger (#1785) or exposure (#1792) pinned an old
version must not retroactively change what already ran. Fixture: publish
v1, activate a table trigger and a `/chat` exposure against v1, publish v2
with an incompatible entry-node schema, then fire both again. Assertions:
the table-triggered run's `workflow_version_id` is v1's, not v2's "current";
the `/chat` exposure — pinned at creation like #1785's trigger, unlike
`AgentExposure`'s floating resolution — likewise still runs v1 until its
owner explicitly repoints it; re-publishing never touches the frozen
`WorkflowVersion` row (`repositories/workflow.py` exposes no
`update_version`, so this is structural — asserted by byte-identical
content before/after the v2 publish).

## Budget limits enforced consistently

Whether spend comes from a workflow's `agent.run` node or a bare agent chat
run, the same `BudgetGuard`/`SpendLedger` applies — no second ledger.
Fixture: an org budget low enough that Journey 2's two-`agent.run` graph
exceeds it on the second call; assert `budget_exceeded` (a pre-call refusal,
never a `NodeResult`), the first agent's spend retained on
`WorkflowRun.spent_cost`, and the identical cap hit by a direct chat call to
the same agent producing the same `BudgetExceeded` through
`AgentRunnerService` unmodified. Because #1786 defines no workflow-level
budget field while #1788 refers to "the published workflow's own budget
block" (finding 5), the fixture exercises only the org-level cap it can
actually configure and documents workflow-scoped tightening as untestable
until that field exists.

## Cancellation

- **Mid-run**: cancel marks every non-`done` outbox row `cancelled` and
  cancels any live `waiting_agent_run_id` through its existing path —
  asserted by confirming no `agent_runs` row is left `awaiting_approval`.
- **Mid-`foreach`-iteration** (#1790): cancel during iteration 2 of 4;
  iteration 3 never dispatches, iteration 2's in-flight attempt follows
  #1788's ordinary lease/`in_flight` recovery — asserted by outbox row count
  and `control.foreach`'s own `NodeRun` landing `cancelled`, not `failed`.
- **Mid-sandbox-job** (#1791): cancel while `code.python.sandbox` is parked
  on `Waiting(reason="retry_backoff")`. **Neither #1788 nor #1791 describes
  closing the live `sandboxd` session on cancellation** — #1788's
  cancellation section only handles `waiting_agent_run_id`, which a sandbox
  job never sets. Real gap, not routed around: the fixture asserts the
  intended behavior (session closed, matching #1788's "no live agent run
  nobody is watching" principle applied to a sandbox session) and, if
  #1791's implementation doesn't close it, files a concrete defect rather
  than accepting an orphaned session as correct.

## Access revocation

- **Mid-run** (#1788): revoke the approving member between decision and
  resume; the dispatcher's authority recheck refuses the resume, moving the
  `NodeRun` to `needs_attention`, never a silent resume.
- **At trigger execution** (#1785): revoke the trigger's
  `execution_principal_user_id`'s authority between activation and a later
  event; the admission recheck writes `FAILED`, not a skipped row, and does
  not auto-disable the trigger — `is_active` stays unchanged.
- **At exposure resume** (#1792): revoke a webhook/schedule exposure's
  stored principal between admission and an approval's resume; #1792's
  second-identity recheck moves the `NodeRun` to `needs_attention` the same
  way. All three assert identically shaped outcomes (`needs_attention` or
  `FAILED`, never a proceeding resume/admission) — the parity this section
  exists to prove.

## Crash-injection matrix

Consolidated from #1788's own five points rather than repeated per
dependency issue — #1790 and #1791 each contribute one concrete fixture
(nested-`foreach` resume; sandbox reconnect) exercised against this same
matrix instead of a separate one, run against Journeys 1–4 rather than
synthetic graphs:

| Injection point | Required outcome | Fixture |
|---|---|---|
| After dispatch, before the handler starts | Lease expires; reconciler reclaims, dispatches exactly once more; no duplicate `NodeAttempt` for one `attempt_no` | Any journey's first write node |
| After an external effect, before result persistence | Attempt found `in_flight`; `idempotent` nodes get one automatic retry on the same key; everything else lands in `needs_attention`, never silently retried | Journey 3's `http.request`/`notification.send` |
| After node-result persistence (result + downstream outbox insert) | One transaction; no state where the result exists but the downstream dispatch does not, or the reverse | Journey 2's second `agent.run` |
| At an approval boundary (decision committed, before the workflow-side wake) | The reconciler's backstop wake fires; direct wake and reconciler together resume the agent run exactly once | Journey 1/2, with an approval-gated tool on the pinned agent |
| At a loop boundary (one `foreach` iteration completes, before advance-or-finish commits) | `scope_path`-keyed identity means the completed iteration never re-runs; only the advance step retries | Journey 4 |

## No exactly-once claim beyond what's explicit

Direct assertion, not inferred from the matrix: for every injection point
where the affected node's `retry_guarantee` is `none` or `at_least_once`
with no far-side dedup, the orphaned attempt's terminal state is
`Uncertain` and the `NodeRun`'s is `needs_attention` — **never** `succeeded`
or silently re-attempted. The test queries for a second `NodeAttempt` after
each such injection and asserts it does not exist until a human resolves
the `needs_attention` review action, and that run status stays
`needs_attention`, not `running`/`succeeded`. This is the concrete,
per-injection-point, per-journey form of #56/#1788's "no claimed
exactly-once beyond what is explicit," not one abstract assertion.

## Documentation deliverables

New pages, wired into `mkdocs.yml` and the topic map in `CLAUDE.md`
(`docs/workflows.md`, `docs/reference/workflow-nodes.md` are new rows;
`docs/concepts.md`, `docs/channels.md`, `docs/reference/capabilities.md` get
updated sections, not new pages):

- **Setup**: creating a table, publishing a first workflow, wiring a
  trigger/exposure — a walkthrough of Journey 1 or 3, screenshotted from the
  real console per `CLAUDE.md`'s "production UI must follow AgenticOS
  styling" (the HTML demos referenced across #1783/#1787/#1789 stay
  illustrative-only).
- **The node and conversion matrix**: generated from `NodeCatalog`, not
  hand-maintained — extending the composed-description discipline #1791
  already sets for its own nodes to the full catalog across #1789–#1792,
  including #1791's conversion pairs (`csv↔json`, `text→file`, `pdf→png`)
  and which formats `text.extract` accepts versus refuses.
- **Triggers and replies**: the frozen-destination rule (#1792) stated
  plainly — "a workflow replies on the connection that started it, or
  through an explicit node you add, never anywhere else" — with the
  table-trigger case (#1785) as the concrete example the rule holds against.
- **Public API examples**: explicitly deferred; the page states the
  adapter's blocked status (Journey 3) rather than documenting a contract
  that does not exist, cross-linked to #1795 to update once it lands.
- **Troubleshooting**: one entry per typed error this milestone introduces —
  `needs_attention`, `REVISION_CONFLICT`, `SCHEMA_DEPENDENCY`, the OCR
  refusal, an SSRF-refused HTTP target — matching how `docs/governance.md`
  already documents budget/approval errors.
- **Extending the registry, for developers**: "how to add a typed node"
  (mirror `debug_echo/`'s three-file shape, `load_builtins()`, the
  coverage-gate include-list edit) and "how to add a column type" (#1782's
  column-type registry) — two how-tos in `docs/adding_features.md`'s style.

## Effort estimates and deferred extensions

Only #1787 carries a granular (best/likely/worst) re-estimate — 49/78/129.5
engineer-days, against the five-week window (2026-09-21 to 2026-10-23) #56
and this issue's own delivery scope still cite. The other nine child
designs carry no day-level number at all; #1788 calls itself "the hardest
backend issue in the milestone" without quantifying it, and #56's own
consistency review only re-affirms the original 1+3-week estimate is
invalid, with no replacement total. **#1793 should not manufacture
per-issue estimates it has no basis for.** What it can state plainly:
#1787 alone already exceeds the milestone window by 2–5x at "likely," under
one owner who also holds #1786/#1789/#1790 — the five-week window is
already falsified by evidence internal to this milestone, independent of
anything #1793 adds. Before implementation starts, each remaining issue
should produce at least a three-point estimate the way #1787 did, rolled
into one milestone total this issue's closing report cites.

Deferred extensions, carried forward from #56's "Implementation consistency
review" and traceable into where each design already draws the line:

- **Hosted pages and Slack** (#1792): both slot into `WorkflowExposure` as a
  sixth/seventh `ExposureAdapter` with no redesign, per #1792's own text —
  deferred for a missing anonymous-visitor session model (pages) and
  because Slack more naturally reuses `AgentExposure`'s bot-binding
  precedent.
- **General OCR** (#1791): `text.extract` refuses a scanned PDF by design —
  the RAG pipeline's own named failure mode (#550, silently indexing a scan
  as empty text) is the reason to refuse, not defer casually.
- **Sub-workflows and parallelism** (#1786/#1790): rule 7 (no cycles) and
  rule 8 (no parallel fan-out in v1) are structural refusals at publish;
  #1790's "why not unrestricted `while` or a general parallel map" section
  states the concrete reason each would break the reconciler's
  per-`(node_instance_id, scope_path)` idempotency assumption.
- **Table attachment columns**: absent from #1783's column-type table
  entirely — no design document proposes one, confirming this stays
  deferred rather than a gap #1793 needs to chase.
