# Workflows: durable execution, approvals, budgets and run history

Design for [#1788](https://github.com/vstorm-co/agenticos/issues/1788).
Depends on [#1786](1786-node-contracts.md) (design only so far); this
document treats the [shared contracts](56-shared-contracts.md) page —
especially `NodeResult` (`Completed`/`Waiting`/`Failed`/`Uncertain`) and
`NodeDefinition` — as fixed, and builds the execution engine that
interprets them. Five other issues (#1789, #1790, #1791, #1792,
transitively #1793) cannot be implemented for real until this exists.

This is the hardest backend issue in the milestone, not a CRUD service
with a background job attached: it is a crash-recoverable state machine
where "the request came back 200" and "the effect actually happened" are
two facts that can disagree, and the design exists to keep that
disagreement from becoming silent data loss or a double-charged external
call. The reconciler section is where the real difficulty lives.

## What is reused, and what is new

Per #56's scope ("reuse the existing Python service layer, AgentRunner,
Prefect, storage, approvals and governance"):

| Reused as-is | New for #1788 |
|---|---|
| `AgentRunnerService`/`ChatAgentRunner` — a node **resumes** a real agent run, never launches a parallel one | The graph-level state machine: `WorkflowRun`, `NodeRun`, `NodeAttempt` |
| `ApprovalGate`, `ApprovalService`, `agent_runs.paused_state` — the decision is recorded exactly where it is today | The dispatch outbox, leases/fencing, and the reconciler for interrupted work |
| `SpendLedger`/`BudgetGuard` — pricing, pre-call enforcement, `booked_to`/`billed_to` attribution | Workflow-scoped cost columns — no separate ledger *table* today, see [Budget](#budget-cost-propagation-deadlines-and-cancellation) |
| The run path's two-commit discipline (`AgentRunnerService._run`) | An event log with cursors — a run is inspected mid-flight by #1787, not only polled after |
| Prefect flows in `app/worker/tasks/`; `run_reaper.py` as the reconciler's precedent | The reconciler logic itself — no interrupted-effect resolution exists today |

No second budget ledger, no second approval queue. A node that calls an
agent gets a real `agent_runs` row, a real approval and a real resume; the
workflow layer only has to find its way back to it.

## Module layout

```
app/db/models/workflow_run.py      # WorkflowRun, NodeRun, NodeAttempt, DispatchOutbox, WorkflowEvent
app/services/workflow_execution/
  __init__.py                      # re-exports WorkflowExecutionService (the facade)
  facade.py                        # start/cancel/list/resume-check
  dispatcher.py                    # claim outbox rows, run one node attempt, advance the graph
  reconciler.py                    # stale leases, orphaned in-flight attempts, expired approvals
  budget.py                        # wires SpendLedger/BudgetGuard to workflow_runs' columns
  events.py                        # append + cursor read/decode for workflow_events
  exceptions.py
app/worker/tasks/workflow_tasks.py # @flow definitions; each opens its own session, calls the service
app/worker/prefect_app.py          # registers the poll + reconcile deployments
app/api/routes/v1/workflow_runs.py # thin: start, cancel, get, list events since cursor
```

Mirrors `services/rag/`/`services/billing/`: a facade routes calls, real
logic and Prefect-facing infra live inside the package.

## The persisted model

Every table carries `organization_id`, matching every other org-scoped
table in the schema.

```
WorkflowRun
  id, organization_id, workflow_id, workflow_version_id (frozen graph, #1786)
  status: RunStatus (below)
  triggered_by: {api, websocket, webhook, chat, schedule, table_created}
  budget_limit, spent_cost, cost_is_partial   # budget_limit copied from WorkflowVersion.budget_limit at start
  deadline_at: datetime | None
  next_event_seq: bigint default 0            # see Events
  paused_reason: {approval, external_event, retry_backoff} | None
  error: WorkflowError | None
  root_run_id: uuid                           # this run's own id if it is the root, else the originating run's
  causation_run_id: uuid | None                # the run whose side effect (a node write, a trigger) admitted this one
  visited_trigger_ids: jsonb                   # trigger ids already fired in this causal chain, for #1785's cycle check
  depth: int default 0                        # causation-chain length; #1785 refuses admission past a configured ceiling
  started_at, ended_at

NodeRun                                        # one row per (run, node instance, loop scope)
  id, organization_id, workflow_run_id, node_instance_id
  scope_path: jsonb                            # [] at top level, [{loop_node_id, index}, ...] inside foreach
  status: {pending, running, waiting, needs_attention, succeeded, failed, skipped, cancelled}
  waiting_reason, resume_token, waiting_agent_run_id (FK agent_runs.id, nullable)
  UNIQUE (workflow_run_id, node_instance_id, scope_path)

NodeAttempt                                     # append-only; one row per try, never mutated after terminal
  id, organization_id, node_run_id, attempt_no
  idempotency_key: text                         # see Reconciler — stable across attempts of the SAME logical op
  status: {in_flight, completed, failed, uncertain}
  result: jsonb, cost: numeric, cost_is_partial: bool
  started_at, ended_at

DispatchOutbox                                  # what is ready to run next, and who currently owns it
  id, organization_id, workflow_run_id, node_run_id
  available_at: timestamptz                     # future for a scheduled retry
  claimed_by: uuid | None                        # a fencing token, not a Prefect flow-run identity
  lease_expires_at: timestamptz | None
  status: {pending, claimed, done, cancelled}    # cancelled: round 1 of this review found cancellation
                                                  # writing a status the model didn't have
  UNIQUE (node_run_id) WHERE status IN ('pending', 'claimed')   # see "Resuming an approval" below

WorkflowEvent                                    # append-only, drives #1787's run-history UI
  id, organization_id, workflow_run_id, seq (bigint, from next_event_seq), kind, node_run_id | None
  payload: jsonb, created_at

ResourceRef                                      # FileRef ids, TableIORef bindings resolved at start
  id, organization_id, workflow_run_id, kind, ref: jsonb
```

`NodeAttempt` is append-only for the same reason `agent_runs` is not: an
overwritten row could not answer "what did the failed try before this one
cost," and the issue requires retaining that. `DispatchOutbox` is a
transactional outbox — a row is created in the **same transaction** that
records the `NodeResult` which made the next node runnable, so "the result
is durable" and "the next step is scheduled" can never disagree.

`WorkflowRun`'s four causation columns (`root_run_id`, `causation_run_id`,
`visited_trigger_ids`, `depth`) exist because #1785's cycle-protection
requirement has nowhere else to live — #1793 found #1785 assuming this
document's table already carried them when it didn't. A root run sets its
own id as `root_run_id` and leaves `causation_run_id` null; a run admitted
by a trigger (or, later, any node that can itself cause a new run) copies
its originator's `root_run_id`, sets `causation_run_id` to the originating
run's id, appends to `visited_trigger_ids`, and increments `depth` by one —
all in the same admission transaction #1785 already needs for its own
dedup insert, so this costs that transaction nothing extra.

## Prefect: a flow per dispatch tick, not a flow per run

**Decision: each node attempt is its own short-lived Prefect flow run,
triggered directly and backed by a periodic poller. No single long-running
`@flow` per `WorkflowRun`.**

A flow-per-run design holds the run's position in one flow's call stack for
the run's whole life — through `waiting_approval`, that can be hours or
days. Either it holds a transaction open across the wait (the `#12` failure
`docs/architecture.md` names: a pooled connection idle for the run's whole
life), or it holds nothing and *is* the durable state, in which case a
worker restart loses the run's position with nothing in Postgres to
reconcile from. A graph whose branches depend on a `NodeResult` produced
seconds or days earlier is also not safely replayable the way Prefect's
checkpoint-retry assumes: a `waiting` node resumes on an external decision,
not on deterministic recomputation.

Postgres stays the only source of truth for run position, and Prefect is
reduced to scheduling, backoff and worker fan-out per unit of work — the
same shape `ingest_document_flow` already has. Three deployments:

- **`workflow-dispatch-node`** — takes `(workflow_run_id, node_run_id)`.
  Three phases, not two (round 1 of this review caught the two-phase
  version contradicting the Reconciler section below, which requires an
  `in_flight` `NodeAttempt` committed *before* the handler runs — without
  it, a crash mid-call leaves no row for the reconciler to find, and the
  run silently stalls):
  1. **Claim.** `UPDATE ... SET claimed_by = :token, lease_expires_at =
     now() + :ttl, status = 'claimed' WHERE status = 'pending' OR
     (status = 'claimed' AND lease_expires_at < now())` — reclaiming a
     lease-expired row needs the `status = 'claimed'` branch explicitly;
     `status = 'pending'` alone can never match a row this same claim
     already transitioned to `claimed`, which is what the first draft's
     predicate did, permanently stranding a run the instant its worker died
     mid-lease. Commits.
  2. **Record `in_flight`.** A second, short transaction inserts the
     `NodeAttempt` row with `status = 'in_flight'` and its
     `idempotency_key`, and commits *before* the handler is called — the
     row the reconciler needs to exist no matter what happens next.
  3. **Run and settle.** The node handler runs *outside any transaction*.
     A third transaction persists the attempt's terminal `status`/`result`,
     transitions the `NodeRun`, appends a `WorkflowEvent`, and — on
     `Completed` unblocking downstream nodes — inserts their outbox rows,
     all in that one commit.
- **`workflow-dispatch-poll`** — an interval deployment that finds
  `pending` or lease-expired outbox rows and triggers
  `workflow-dispatch-node` for each. Starting or resuming a run also
  triggers the node flow directly via `spawn_after_commit` for low
  latency, but that trigger can be lost; the poll guarantees forward
  progress regardless — the literal reading of "leases/fencing and a
  reconciler for queued or interrupted work."
- **`workflow-reconcile`** — a slower interval deployment, structurally
  `run_reaper.py`'s stale-run sweep applied to expired leases, orphaned
  `in_flight` attempts and expired approvals (below).

`claimed_by` is minted fresh per claim, not the flow-run id: a hung flow
and a reclaiming poller's flow must never both believe they own the row, so
every write after a claim re-checks `claimed_by = :my_token` before
committing.

## The run-status state machine

Run status is coarser than node status — several `NodeRun`s can be
`waiting` in different ways at once, notably inside a `foreach` body. Run
status is the most severe of its live nodes', ranked `needs_attention` >
`budget_exceeded` > `failed` > `waiting_approval` > `waiting_retry` >
`running`.

| Run status | Entered when | Driven by |
|---|---|---|
| `queued` | `WorkflowRun` created, no outbox row claimed yet | — |
| `running` | First outbox claim commits | — |
| `waiting_approval` | A `NodeRun` gets `Waiting(reason="approval")` | `NodeResult.Waiting` |
| `waiting_retry` | `Waiting(reason in {external_event, retry_backoff})`, or a `Failed` with a retryable `retry_guarantee` schedules backoff | `NodeResult.Waiting`/`Failed` |
| `needs_attention` | A `NodeRun` gets `Uncertain`, or the reconciler synthesizes one for an orphan it cannot safely resolve | `NodeResult.Uncertain` |
| `budget_exceeded` | `BudgetGuard` refuses a node's call before it is made | pre-call check, not a `NodeResult` |
| `cancelled` | Explicit cancel, revoked access, or an expired approval (mirrors `ApprovalService.expire_stale`: the caller went away, spend to that point stands) | — |
| `failed` | A `Failed` exhausts its retry policy with no handler route (#1790 gap below), or any node fails outside a caught path | `NodeResult.Failed` |
| `succeeded` | No outbox rows remain and every reachable output was reached (guaranteed satisfiable by #1786's reachable-outputs check) | `NodeResult.Completed`, transitively |

Node-level `skipped` is **not** a `NodeResult` outcome — it is assigned
structurally at dispatch time when graph traversal shows a node
unreachable this run (the untaken `logic.if` branch, an empty `foreach`
body), the same reachability reasoning `validate_graph` already applies at
publish time. It produces no outbox row and emits one `node_skipped` event.

**The retry_guarantee/#1790 gap.** `retry_guarantee` (`none`/`idempotent`/
`at_least_once`) decides whether a retry is attempted at all, but the
ceiling, backoff schedule and "route to a declared error-handler node"
policy belong to **#1790**, not yet designed. Until it lands: `idempotent`
and `at_least_once` nodes get a fixed small ceiling of backoff retries via
`waiting_retry`; `none` gets zero; exhausting retries fails the run outright
with no routing hook. This is the minimum that unblocks #1789/#1792;
#1790's design must revisit the ceiling and the `failed` row, not silently
override them.

## Approvals: resuming the same agent run, never launching a new one

The issue: "returns `Waiting`; resume the same agent/run, rather than
launching it again."

A node handler calling `AgentRunnerService.run`/`resume` that parks on
`ApprovalGate` — recorded exactly as today, `agent_runs.status =
awaiting_approval`, real `paused_state` — does not treat this as a node
failure; it returns `Waiting(reason="approval", resume_token=<node_run_id>)`,
and `NodeRun.waiting_agent_run_id` is set to that `agent_runs.id`. The
`resume_token` the contract defines is concretely the `NodeRun`'s own id,
sufficient because the link is already 1:1 on the row.

The human decision still goes through the **existing** surface,
`ApprovalService.decide`, unchanged — a workflow run has no chat socket for
anyone to click "resume" in. What #1788 adds is the wake-up: once a
decision commits, the same unit of work inserts a `DispatchOutbox` row for
the matching `NodeRun` via `spawn_after_commit`. `workflow-dispatch-node`
re-claims it and the handler calls `AgentRunnerService.resume` on the
stored `agent_run_id` — never `run` again, which would silently drop the
approved call by re-sending the original prompt to a fresh agent. If the
direct wake is lost, `workflow-reconcile` is the backstop: it finds
`NodeRun`s waiting on an `agent_runs` row no longer `awaiting_approval` and
dispatches them.

`ApprovalService.decide` refusing a second *decision* on the same approval
is not the same guarantee as refusing a second *dispatch* for the same
`NodeRun` — round 1 of this review found a real race the "cannot resume
twice" line glossed over: the direct wake can insert its outbox row, and
before anything claims it, `workflow-reconcile` can independently see the
same now-decided `agent_runs` row and insert a *second* outbox row for that
`NodeRun`, since nothing before this fix distinguished "already has a
pending dispatch" from "needs one." Two separate outbox rows can each be
claimed and each call `resume` on the same `agent_run_id` concurrently. The
partial unique index above, `UNIQUE (node_run_id) WHERE status IN
('pending', 'claimed')`, closes it structurally: the reconciler's insert
hits the constraint and is read back as "already dispatched" the same way
#1785's admission insert reads back a constraint violation as "already
admitted," rather than needing the reconciler to remember to check first.

"Rechecks decision authority": before issuing `resume`, the dispatcher
re-checks the approving member's *current* authority via the same
`resolve_access` check that gated the decision, rather than trusting a
grant that may have been revoked since — a stale-authority resume is
refused and the `NodeRun` moves to `needs_attention` instead.

A **rejected** approval resumes the agent exactly as today — the model
sees the refusal and answers — so it surfaces as an ordinary `Completed` or
a node-declared `Failed`; rejection is not a special workflow state.

## Budget, cost propagation, deadlines and cancellation

There is no separate ledger *table* in this codebase — `agent_runs` stores
its own cost columns and `SpendLedger` is an in-memory accumulator flushed
onto them. #1788 follows the same shape: `WorkflowRun.spent_cost`/
`cost_is_partial` and a per-`NodeAttempt` `cost` column are the persisted
form; `BudgetGuard`'s pre-call check, the `genai-prices` lookup and
`SpendEntry.booked_to`/`billed_to` attribution are reused verbatim.

- **Parent budget.** `WorkflowRun` carries an inherited cap (org limit,
  optionally tightened by the published workflow's own budget block). A
  node calling an agent constructs its `BudgetGuard` via `for_delegate`,
  attributed the way a subagent delegation already is — `booked_to` the
  node instance and scope path, `billed_to` the `WorkflowRun` — so the cap
  binds on every agent call inside the run.
- **Non-agent cost** (a paid HTTP node, a metered table op) books directly
  against the same discipline: checked before the call, recorded after, at
  zero-with-a-flag for anything the pricing snapshot does not know.
- **Retaining failed-attempt cost without double-counting.** Because
  `NodeAttempt` is append-only, a failed attempt's spend is its own row; a
  retry books a new attempt with a new `cost` entry, and `spent_cost` sums
  every attempt of every node — nothing lost, nothing double-counted. A
  child agent run's own columns stay the source of truth for that run; the
  workflow only sums what it bills to itself, the boundary that already
  keeps a delegate's month from double-billing its parent.
- **Deadlines and cancellation.** `deadline_at` is checked at every outbox
  claim, before the handler runs — a claim past deadline fails outright.
  Cancelling a run marks every non-`done` outbox row `cancelled` and, for
  any `NodeRun` with a live `waiting_agent_run_id`, cancels that agent run
  through its existing path — a cancelled workflow must not leave a live
  agent run nobody is watching.

## The reconciler, and what "never promise exactly-once" means concretely

The named scenario: a node's HTTP handler `POST`s to an external API, gets
a 200, and the process is killed before the response reaches `NodeAttempt`.
On restart, nothing in the process remembers whether the call happened —
only the row on disk, which says `in_flight`.

The rule: **an interrupted attempt is never assumed either outcome.** This
is also why `in_flight` is written **before** the call, in its own
committed transaction — written after, a crash mid-call would leave no row
at all, and the reconciler would have nothing to find; the run would just
stop, silently, with no `needs_attention` anywhere. `workflow-reconcile`
finds `NodeAttempt` rows `in_flight` whose owning outbox lease expired:

- If `retry_guarantee` is `idempotent` — the target system dedupes on the
  `idempotency_key` this attempt sent (`f"{organization_id}:
  {workflow_run_id}:{node_instance_id}:{scope_path}"`, stable across
  attempts of the same logical op, distinct across loop iterations, sent as
  the call's own idempotency header where supported) — the reconciler may
  dispatch a **fresh** attempt automatically: a duplicate is provably
  harmless by the node's own declared contract. The only case that
  auto-retries.
- Anything else (`at_least_once` with no dedup on the far side, or `none`)
  — the orphaned attempt is marked `uncertain`, `Uncertain(detail=...)` is
  synthesized if the node never reported one, and the `NodeRun` follows the
  ordinary `Uncertain` path into `needs_attention`. Never retried
  automatically, no second attempt created — "do not automatically
  duplicate unknown operations," exactly.
- `needs_attention` is resolved by a person through a review action
  structurally like `ApprovalService.decide` (own row, own authority
  check): confirm-succeeded (`NodeRun` proceeds as `Completed`) or
  confirm-failed/compensated (as `Failed`, normal retry routing applies).
  New surface for #1787/#1793 to build; this document fixes only its
  authorization model and its effect on the state machine.

## Event streaming with cursors

`WorkflowEvent.seq` is a per-run monotonic counter
(`WorkflowRun.next_event_seq`, incremented in the same transaction as the
insert — never a shared sequence, so a cursor for one run stays small,
dense and meaningless for another). Reused directly from
`notification_center.py`'s `encode_cursor`/`decode_cursor` shape, this
codebase's existing answer to "give me everything after where I left off";
`workflow_events` only needs the run-scoped `seq` in place of a timestamp
tiebreak.

`GET /workflow-runs/{id}/events?after=<cursor>` serves both backfill and
live tailing via polling or a socket — the same `(kind, payload)` frame
vocabulary `run_stream.py`'s `RunFrames`/`FrameSink` uses for chat, but
backed by a committed table instead of in-process iteration: every event is
inserted in the same transaction as the `NodeRun`/`NodeAttempt` change that
produced it, so a reconnect after any crash sees exactly what happened.
#1787's run-history view and any live "watch this run" panel read this one
table.

## Migration sketch

New tables: `workflow_runs`, `node_runs`, `node_attempts`,
`dispatch_outbox`, `workflow_events`, `resource_refs`. All carry
`organization_id` and FK to `workflow_versions` (#1786) via
`workflow_runs.workflow_version_id`. Indexes: a partial index on
`dispatch_outbox (status, available_at) WHERE status = 'pending'` for the
poller's claim scan; unique `(workflow_run_id, node_instance_id,
scope_path)` on `node_runs`; `(workflow_run_id, seq)` on `workflow_events`;
unique `(node_run_id, attempt_no)` on `node_attempts`.

Numbering is not fixed here. `main` is at `0091_rag_metadata_prereqs` as of
this writing (`alembic heads` in this worktree); per [shared
contracts](56-shared-contracts.md#why-1786-is-based-on-1782s-branch-not-main),
#1786 itself stacks above `0092`/`0093` on #1782's unmerged branch and has
not landed. #1788's migration stacks on top of whatever #1786 lands as —
verify `backend/alembic/versions/` heads at implementation time rather than
trusting any number written today.

## Test plan

Structural precedent: `tests/integration/test_run_commit_boundary.py`
(the run path's two-commit ordering) and
`test_flow_starts_after_commit.py` (`spawn_after_commit` ordering) — every
crash-injection test below follows that shape, against a real Postgres.

| Injection point | What must hold |
|---|---|
| After dispatch (claimed, before the handler starts) | Lease expires; reconciler reclaims and dispatches exactly once more — no duplicate `NodeAttempt` for one `attempt_no` |
| After an external effect, before result persistence | Attempt found `in_flight`; idempotent nodes get one automatic retry on the same `idempotency_key`, everything else lands in `needs_attention`, never silently retried |
| After node-result persistence (result + downstream outbox insert) | One transaction; no observable state where the result exists but the downstream dispatch does not, or the reverse |
| At an approval boundary (decision committed, before the workflow-side wake) | The reconciler's backstop wake fires; direct wake + reconciler together resume the agent run exactly once |
| At a loop boundary (one `foreach` iteration completes, before loop advance-or-finish commits) | `scope_path`-keyed identity means the completed iteration is never re-run; only the advance step retries |

Also directly off the acceptance criteria: a stale-worker test (a lease
expiring mid-call is reclaimed, not duplicated); a duplicate-delivery test
(poller and direct wake both firing resolve to one dispatch via the fencing
compare-and-swap); an access-revocation test (a membership revoked between
decision and resume stops the resume); a hard-budget test (a `BudgetGuard`
refusal stops new dispatch while cost and error stay visible); and a
child-run reconciliation test (a workflow-owned agent run that crashes
mid-run is caught by `run_reaper.py`'s existing sweep, and the workflow's
own reconciler notices the now-terminal `agent_runs` row the same way it
notices a decided approval).

## Open dependencies this design does not resolve

- **#1790** owns the real retry ceiling, backoff schedule and
  error-routing policy; this document's `failed` transition and retry
  ceiling are a deliberately minimal placeholder.
- **#1786** owns `NodeDefinition`/`NodeResult`'s actual shape; if its real
  implementation departs from [shared contracts](56-shared-contracts.md),
  this state machine (keyed directly off that union) needs revisiting in
  the same change.
- The `needs_attention` review action (confirm-succeeded/confirm-failed) is
  new product surface with no existing UI to point to — #1787 and #1793
  need to design what an operator sees; this document fixes only its
  authorization model and its effect on the state machine.
