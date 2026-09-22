# #1790 — Workflows: error routing and durable foreach scopes

Design for [issue #1790](https://github.com/vstorm-co/agenticos/issues/1790),
child of [#56](https://github.com/vstorm-co/agenticos/issues/56). Depends on
[#1786](1786-node-contracts.md) (`WorkflowGraph`, `validate_graph`, node
contracts) and [#1788](1788-durable-execution.md) (`WorkflowRun`/`NodeRun`/
`NodeAttempt`/`DispatchOutbox`, the reconciler, and the `retry_guarantee` gap
it left for this issue). Both are treated as fixed. This design adds two
fields to types #1786 already ships (`NodeInstance.policy`,
`WorkflowError.bypassable`, flagged below) and is otherwise built inside
#1786's graph JSON and #1788's run tables — **no new tables or columns.**

## Module layout

```
backend/app/workflows/
  contracts/policy.py           # NodePolicy, RetryPolicy
  nodes/error_handle/, error_raise/, control_foreach/, loop_item/, loop_yield/
  graph/validate.py             # extended: rules 9 and 10, below
backend/app/services/workflow_execution/
  foreach.py                    # scope-entry freeze, iteration advance, item-error policy
  errors.py                     # AppException -> WorkflowError, bypassable classification
```

`foreach.py`/`errors.py` join `dispatcher.py`/`reconciler.py` in #1788's
existing package.

## Policy is per-instance, not per-definition

`NodeDefinition.retry_guarantee` is static per node *kind*: what retrying
`http.request` can safely assume. It says nothing about how many times one
*instance* should retry, with what backoff, or what happens on exhaustion —
per-instance config, a sibling of `config`:

```python
class RetryPolicy(BaseModel):
    max_attempts: int = Field(ge=1, le=10)
    backoff: Literal["fixed", "exponential"] = "exponential"
    base_delay_seconds: float = Field(gt=0, default=2.0)
    max_delay_seconds: float = Field(gt=0, default=60.0)

class NodePolicy(BaseModel):
    timeout_seconds: float | None = None
    retry: RetryPolicy | None = None
    on_error: Literal["fail_run", "route"] = "fail_run"

# addition to #1786's graph/model.py NodeInstance:
class NodeInstance(BaseModel):
    ...
    policy: NodePolicy | None = None
```

`policy=None` keeps #1788's placeholder (fixed small ceiling for
`idempotent`/`at_least_once`, zero for `none`) as the default. `retry.
max_attempts` is *capped*, not overridden, by `retry_guarantee`: a
`none`-guarantee instance configuring `max_attempts > 1` is refused at
publish. `on_error = "route"` makes a node's `error` output port live;
`"fail_run"` (default) fails the run as today's placeholder does.

## `error.handle` and `error.raise`

Both `kind="control"`, `effect_kind="pure"` — they route or synthesize,
never touch an external system.

**`error.handle`**: input port `in` (`WorkflowError`), zero or more named
branches matched against `WorkflowError.code`/`retryable`, plus one
mandatory `default` port. A node with `policy.on_error = "route"` gets an
implicit `error` output port carrying `WorkflowError` (never its declared
`output_schema`); wiring it to an `error.handle`'s `in` is how failures get
routed. Nothing matching flows out `default`.

**Mandatory default branch, enforced at publish.** #1786's `validate_graph`
already special-cases node kinds inside its generic passes (rule 5:
`logic.merge`'s predecessors trace to one `logic.if`; rule 8: `control` kind
exempt from the fan-out ban). #1790 adds two rules the same way, refused the
same way — one `field_problems` entry per violation, all ten collected
together:

| # | Rule | Algorithm |
|---|---|---|
| 9 | `error.handle` default required | Every instance's `default` port needs an outgoing edge, else refused, `field="nodes.<id>"`. |
| 10 | Scope-only kinds stay in scope | `loop.item`/`loop.yield` must sit in a `ScopeBoundary.body_node_ids` rooted at `control.foreach`; one at top level is refused. |

An unrouted `error.handle` cannot publish — a missing default is a rejected
draft, not a runtime surprise.

**`error.raise`** takes `code`, `message`, `details: dict[str, Any]`,
`retryable: bool = False` and always returns `Failed(error=WorkflowError(...,
bypassable=True))`, never `Completed`; no output port (rule 2 treats it as a
sink). It lets an author deliberately fail a branch with a typed, safe
payload rather than a Python message/traceback leaking through — the same
reason every handler-caught `AppException` maps field-for-field into
`WorkflowError` rather than `str(exc)`: a bare exception or stack trace is
never a legal `Failed.error`, whether the runtime or the author produces it.

**Normal output is unavailable on the error branch.** A routed node exposes
two ports with disjoint payload types: `out` (`output_schema`, reachable
only from `Completed`) and `error` (`WorkflowError`, reachable only from an
exhausted or non-retryable `Failed`). Rule 3 already refuses a mismatched
edge, so keeping the ports structurally distinct — not one `out` port
carrying a union — means a binding downstream of `error` can only resolve
`WorkflowError` fields; the `NodeAttempt.result` row holds one payload or
the other, never both.

## What cannot be routed around an `error.handle`

Validation/revision conflicts, cancellation, permission revocation, budget
exhaustion, uncertain effects — excluded by two mechanisms, matching the two
paths they reach the state machine by.

**Never become a `Failed` at all.** `Uncertain` is its own `NodeResult`
variant, routed straight to `needs_attention`, no `on_error` consultation.
Budget exhaustion is "a pre-call check, not a `NodeResult`" — refused before
the handler runs. Revision conflicts happen at publish/draft-write, before a
`WorkflowRun` exists. Cancellation is a run-level status transition
terminating every non-`done` outbox row directly, never through one node's
result.

**Reach the handler-wraps-`AppException` path, but are marked
non-bypassable.** Permission revocation checked *inside* a handler (a
mid-run `resolve_access` against a since-revoked grant) does surface as a
caught exception mapped to `WorkflowError`. One field excludes it anyway:

```python
# addition to #1786's contracts/results.py WorkflowError:
class WorkflowError(BaseModel):
    ...
    bypassable: bool = True
```

`errors.py`'s `AppException -> WorkflowError` mapping sets
`bypassable=False` for a fixed set — authorization exceptions,
`RevisionConflictError`/`RevisionRequiredError`, in-handler cancellation —
everything else defaults `True`. The dispatcher checks `bypassable` *before*
`policy.on_error`: a non-bypassable `Failed` fails the run even with a live
`error.handle` wired to the port. Not a node-kind or `effect_kind` flag —
both are static per-definition; this is per-exception, decided once where
caught.

## `control.foreach`: the nested body

**Representation, checked against #1786.** #1786's `graph/model.py` already
ships `ScopeBoundary{scope_node_id, body_node_ids: frozenset[UUID],
entry_port, exit_port}` — inline `NodeInstance`s in `graph.nodes`, tagged
into a scope by `body_node_ids` membership, not a nested `WorkflowGraph`
under `config`. #1790 uses this as-is: no second graph representation. It
matches rule 6 (crossing edges refused unless declared) and rule 7 (bodies
collapsed for the outer cycle pass) exactly as written; a nested-graph value
would need its own copy of both. #1789 has no design document yet, so there
is no second assumption to reconcile against — #1786's shape is consistent
and sufficient.

`control.foreach`'s config binds `items` and `item_error_policy` (below);
its `entry_port`/`exit_port` connect to `loop.item`'s output and
`loop.yield`'s input, the two boundary edges rule 6 sanctions.

**`loop.item`**: `kind="control"`, `handler=None` *permanently* — not
"until an execution issue supplies one" like every other node, structurally
never invoked. Its `output_schema` (`item`, `index`, `count`) exists only to
be referenced: at scope entry the dispatcher synthesizes that iteration's
`loop.item` row directly as `Completed`, in-process — the same treatment
#1788 gives `skipped` — so every other body node resolves bindings through
the ordinary `NodeRun` lookup, no special case in the binding resolver.

**`loop.yield`**: `kind="control"`, one input bound to the iteration's
result, one output edge (the scope's `exit_port`); handler is identity.
Exists as an explicit node so the body has one referenceable "iteration
done" point and one sink for rule 2.

## Freezing the input list, persistence, checkpoints

`control.foreach`'s dispatch resolves `items` once, before any iteration
outbox row exists, and snapshots it via #1788's existing `ResourceRef` table
(`kind="foreach_manifest"`, no new table). Every iteration reads the frozen
snapshot, never the live source — a row changed mid-run does not change what
this run iterates.

**Inline JSONB only, in #1790's own scope — a `FileRef`-backed manifest is
#1791's to add, not #1790's.** An earlier draft proposed a blob-backed
manifest via `FileRef` for large lists, but #1791 is where `FileRef` gets
real storage; #1786's `FileRef` at #1790's own tier is deliberately
unbacked (shared-contracts decision 1), and #1791 itself depends on #1790
— a blob manifest here would need #1791's storage before #1791 can start,
a real cycle (round 3 of this review). #1790 instead ships `max_items`
(the existing Limits row) sized so inline JSONB always fits comfortably —
a few thousand short items, not a bound chosen for storage capacity — and
the manifest is read once, fully, at freeze time, never paged. Once #1791
lands, a blob-backed manifest for genuinely large lists is a
`ResourceRef.kind` addition, not a redesign of anything here.

Iteration scopes reuse #1788's `NodeRun` exactly: `UNIQUE(workflow_run_id,
node_instance_id, scope_path)` with `scope_path = [{loop_node_id, index},
...]` was already built "to support foreach"; #1790 is the first issue to
populate it with more than `[]`. Iterations run **sequentially** — the same
"no parallel fan-out in v1" discipline (rule 8) applied to the runtime:
iteration `i+1`'s first outbox row is inserted only once iteration `i` has a
**terminal** result — `loop.yield` succeeds, *or*, under `collect`, `i`'s
own `WorkflowError` is persisted to its slot. Under `stop`, `i` failing
does **not** advance to `i+1` at all; it fails `control.foreach` itself
(round 3 of this review: an earlier draft had this backwards, tying
advancement to `stop` rather than `collect`, the opposite of the policy
section below). Checkpointing on restart finds the highest index with a
terminal result of *either* kind — a `collect`-mode failure is as terminal
as a success, so a crash immediately after one does not re-dispatch that
same index, potentially duplicating whatever side effect it already caused
before failing (round 3 of this review: "highest succeeded `loop.yield`"
alone missed exactly this case) — and resumes at the next one; lower
indices are never re-dispatched, the same constraint that stops a duplicate
`NodeAttempt`. A crash mid-iteration is handled entirely by #1788's existing
lease/`in_flight` recovery — the scope boundary only decides which index
runs next.

Approval inside an iteration needs no new mechanism: the waiting `NodeRun`
carries its own `scope_path`, so `waiting_agent_run_id` and #1788's resume
wake resolve to the exact `(node_instance_id, scope_path)` row.

Cost and operation-key scoping are already correct in #1788: the idempotency
key is `f"{organization_id}:{workflow_run_id}:{node_instance_id}:
{scope_path}"`, already "distinct across loop iterations" by #1788's own
text. #1790 confirms `control.foreach`'s dispatch populates a non-empty
`scope_path` for every body `NodeRun`, the precondition that claim depended
on — without it, two iterations on the same `node_instance_id` would
collide on both the unique constraint and the key. Cost follows the same
rows: each iteration's `NodeAttempt.cost` sums into `WorkflowRun.spent_cost`
like any node, so `BudgetGuard` sees real cumulative spend mid-loop.

## Ordering, empty input, result collection

Sequential iteration means completion order equals input order by
construction; `control.foreach`'s `Completed` is assembled by reading
`loop.yield`'s stored result for indices `0..N-1` in order, not by
append-on-completion. An empty frozen manifest is exactly the case #1788's
own skip-reasoning names ("an empty `foreach` body"): no outbox rows,
`control.foreach` synthesizes `Completed(items=[])` immediately, no
`loop.item`/`loop.yield` rows at all — the same structural skip as an
untaken `logic.if` branch.

## Item-error policy: stop vs. collect

`control.foreach.config.item_error_policy: Literal["stop", "collect"] =
"stop"`.

- **`stop`** — the first iteration whose `loop.yield` is never reached fails
  `control.foreach` with that `WorkflowError`; no further iteration
  dispatches. Default, matching every node's own `fail_run`.
- **`collect`** — a failed iteration's `WorkflowError` fills that index's
  slot (`ForeachItemResult = Completed[Any] | Failed`, per index) and the
  next iteration still dispatches. `control.foreach` completes once every
  index has a terminal result; whether "any item failed" matters downstream
  is the author's call, expressed by binding the collected list into a
  `logic.if`/`error.handle` after the scope exits.

## Limits

| Limit | Checked | Effect when exceeded |
|---|---|---|
| `max_items` | At freeze, against manifest length | Freeze refused, error naming cap and count — never truncated |
| `max_depth` | At publish, walking `graph.scopes` | New rule alongside 9/10; refused at publish |
| `max_total_nodes` | At dispatch, running `NodeRun` count under the run | Further outbox creation refused; run fails |

## Why not unrestricted `while` or a general parallel map

A `while` loop has no statically known iteration count, so it cannot be a
bounded, frozen manifest walked by index — the only way to express "loop
until condition" is a back edge from body to entry, exactly what rule 7 (no
cycles) refuses at publish. A general parallel map is exactly what rule 8
refuses for fan-out, and would multiply #1788's reconciler surface:
idempotency and budget accounting assume attempts for one
`(node_instance_id, scope_path)` never race. Both are explicit non-goals.

## Test plan

- Rule 9/10 refusals: `error.handle` missing `default`; `loop.item` outside
  any scope.
- A routed node's handler fails: `error` carries only `WorkflowError`, no
  binding reaches `output_schema` for that attempt.
- One test per non-bypassable category (in-handler `RevisionConflictError`,
  budget pre-call refusal, cancelled run, `Uncertain`), each wired to a live
  `error.handle`; the run still fails/cancels/needs-attention and the
  handler never dispatches.
- **Nested two-level foreach, mid-iteration error, resume** — an outer
  `control.foreach` over 3 items each running an inner `control.foreach`
  over 2; the inner scope's second item on the outer's second iteration
  fails its first attempt. `stop` yields `Failed` naming the exact
  `scope_path`; `collect` yields a full 3x2 grid with one `Failed` slot.
  Kill the process after the failing `NodeAttempt` persists but before the
  outer scope's advance-or-finish commits (the loop-boundary injection
  point #1788's own test plan names); on restart, the outer scope resumes
  at the correct index, no already-`succeeded` inner iteration
  re-dispatches, no duplicate `NodeAttempt`. Matches #1793's later criteria
  ("inject crashes around... loop boundaries", "no claimed exactly-once
  behavior beyond explicit guarantees") — a concrete fixture for #1793 to
  reuse.
- Empty `items`: `Completed(items=[])`, zero body `NodeRun` rows, one
  `skipped` event.
- One test per limit, naming the configured limit and observed value.
- `error.raise`'s `Failed.error` holds only the configured fields,
  independent of the underlying Python exception.

## Suggested commit order

1. `contracts/policy.py` + `NodeInstance.policy`/`WorkflowError.bypassable`
   additions to #1786's models, with serialization tests.
2. `graph/validate.py` rules 9, 10, `max_depth` — one refusal test each.
3. `nodes/error_handle/`, `nodes/error_raise/` + unit tests, then
   `services/workflow_execution/errors.py` (mapping and non-bypassable
   table, one test per category).
4. `nodes/loop_item/`, `nodes/loop_yield/` + the dispatcher's structural
   synthesis of `loop.item`'s `Completed` at scope entry.
5. `services/workflow_execution/foreach.py` — freeze/manifest, sequential
   advance, item-error policy, limits — with the crash-injection and
   nested-scope tests above against a real Postgres.
6. `nodes/control_foreach/` wiring the above into a registered
   `NodeDefinition`, plus catalog and API tests (422 paths for every new
   refusal, restart/resume integration test).
7. `docs/reference/capabilities.md` and the `pyproject.toml`/`ty` include-list
   entries for the two new service files, same commit as the code they
   cover, per #1786's precedent.
