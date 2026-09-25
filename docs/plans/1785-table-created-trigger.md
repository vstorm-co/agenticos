# #1785 — Trigger workflows when a Virtual Table record is created

Design for [#1785](https://github.com/vstorm-co/agenticos/issues/1785), child
of [#56](https://github.com/vstorm-co/agenticos/issues/56). Depends on
[#1782](https://github.com/vstorm-co/agenticos/issues/1782) (built, PR #1812,
branch `feat/1782-virtual-tables-storage`), [#1788](1788-durable-execution.md)
and [#1792](1792-channel-adapters.md) (both design-only). No new admission
mechanism: this is a **seventh `ExposureAdapter`**, consuming
`VirtualTableOutbox` rows and calling #1792's own `admit()` like every other
adapter; the run itself is entirely #1788's.

## What this issue retires

#1782 wrote `VirtualTableOutbox` with a consumer in mind — its own docstring
says "a row here means the record committed; **a consumer claims undelivered
rows in its own session and marks `dispatched_at` when it has handed them
on**" (`backend/app/db/models/virtual_table.py`). No such consumer exists.
`virtual_table_repo.add_outbox`, called from `records.py`'s create path,
writes the row in the same transaction as the record and its history entry;
nothing ever reads `dispatched_at IS NULL` back out.

That gap already cost a workaround: #1823 found undispatched outbox rows
accumulate forever, and PR #1828 closed it with a 30-day dead-letter
retention sweep for exactly that reason — *"there is no consumer yet,
#1785"*, and in its Limitations, *"Undispatched rows are bounded by a 30-day
dead letter, not delivered."* That sweep is a safety net for a queue nobody
drains, not a delivery mechanism, and says so.

**This issue is that consumer.** Once it ships, rows are dispatched (admitted
into a `WorkflowRun`, or explicitly filtered/blocked, below) well inside 30
days in the ordinary case, and #1828's sweep reverts to a backstop for a
broken or disabled trigger's rows, not the only thing bounding this table's
growth. This design does not change that sweep; it retires the urgency
behind it.

## The consumption mechanism

A Prefect flow, `workflow-dispatch-table-trigger`, structurally identical to
#1788's `workflow-dispatch-poll` and #1792's schedule heartbeat: an interval
deployment claiming pending rows with the `SELECT ... FOR UPDATE SKIP LOCKED`
claim every queue table in this milestone uses — the behavior
`VirtualTableOutbox`'s own docstring already commits to — against
`virtual_table_outbox_pending_idx` (`created_at` `WHERE dispatched_at IS
NULL`), scoped per organization so one tenant's backlog cannot starve
another's claim batch.

Claiming and admitting are two separate commits, mirroring #1788's "outbox
row exists" vs. "handler ran" split: a claim marks a row with a fencing
token and lease (#1788's `claimed_by`/`lease_expires_at` shape) in its own
transaction. A crash between claim and admission leaves the row
`dispatched_at IS NULL` with an expired lease, reclaimed by the poller
exactly as #1788's dispatcher reclaims a stale outbox lease.

**One event, several triggers: `dispatched_at` is set only after every
active trigger on that table has been evaluated, not after the first.**
Round 1 of this review caught this underspecified: a table can have several
active triggers (§ Trigger configuration), each evaluated independently
against the same outbox row and each producing its own
`TableTriggerAdmission` via the `(trigger_id, outbox_event_id)` key, but the
row's own `dispatched_at IS NULL` predicate is what the pending-index
consumer uses to find work at all — setting it after only the first
trigger's admission commits would make the consumer never revisit that row,
silently skipping every other trigger on the table for that event. The
claimed consumer pass therefore loops: read every active
`VirtualTableTrigger` for the claimed row's `table_id`, run one admission
transaction per trigger (so a crash mid-loop leaves the completed triggers'
admissions intact, read back via the unique constraint on retry, and only
the unevaluated remainder re-runs), and set `dispatched_at` in a final,
separate small transaction once the loop has evaluated all of them — never
inside any individual trigger's own admission transaction.

## Trigger configuration

One row per configured trigger (a table can have several):

```python
class VirtualTableTrigger(Base, TimestampMixin):
    id: UUID
    organization_id: UUID              # FK CASCADE, indexed
    table_id: UUID                      # FK virtual_tables.id CASCADE
    workflow_id: UUID                    # FK CASCADE
    workflow_version_id: UUID            # FK workflow_versions.id, NOT NULL, pinned
    revision: int                         # bumped on every config write
    filter: list[RecordFilter]             # #1782's own shape, reused verbatim
    input_mapping: dict[str, str]          # core.input field -> record column id
    execution_principal_user_id: UUID      # FK users.id, NOT NULL — see below
    is_active: bool
    activated_at: datetime                  # the watermark — see subscription boundary
    created_by_user_id: UUID | None
```

**The creation snapshot a filter and `input_mapping` evaluate against is the
record's `create` history row, not the outbox payload.** Round 1 of this
review checked #1782's real `add_outbox` call and found the outbox
`payload` carries only `{table_id, record_id, external_id, schema_version,
revision}` — no cell values, no `author_user_id` — so a filter naming an
actual column, or an `input_mapping` naming `author_user_id`, cannot be
evaluated from the outbox row alone as an earlier draft of this document
assumed. The consumer instead loads
`VirtualTableRecordHistory` by `(record_id, revision)` from the outbox
payload's own fields, `operation = "create"`: its `after` column holds the
exact merged values `add_history` wrote at creation, and its
`actor_user_id` is the creating user — both already durable, already
tied to that one revision, and exactly the "creation snapshot" the issue
asks for, since a record later edited still has that history row unchanged.

**The filter reuses #1782's `RecordFilter`/`FilterOp`/`FilterValue` types
directly** (`app/schemas/virtual_table.py`) — no second filter DSL. It is
validated at save time against the table's live schema, exactly as
`RecordQuery.filters` already is, and stays column-id-keyed so a rename
doesn't orphan it. All filters hold (AND), matching `RecordQuery`.

**Input mapping** is `{payload key: record column id}` — round 3 of this
review corrected this once #1789 settled `core.input.output_schema` as the
fixed `WorkflowInputPayload{payload: dict[str, Any], triggered_by: str}`,
with no per-workflow typed field list to bind into (#1792 needed the same
correction). Admission builds `payload` from the mapping — `{key:
record_values[column_id] for key, column_id in input_mapping.items()}` —
validated at save time only against the table's current schema (every
`column_id` names a live column), never against a target `input_schema`
that does not exist at this boundary. `triggered_by = "table_created"`.
A workflow that needs a typed field out of `payload` reads it with a
`data.map` node just past `core.input`, the same as #1792's channel
adapters.

**The execution principal is the trigger's own configured principal, pinned
at activation — never the record's author, never derived from record data.**
The issue's scope line is explicit that "the record author is the initiator"
but "record content cannot choose the execution principal." Concretely:
`execution_principal_user_id` is set by the trigger's *configuring* user
(defaulting to themselves, like #1792's exposures), checked for table and
workflow-run authority at that moment, and used unchanged for every event
until the trigger is edited. The record's `author_user_id` travels only as
ordinary input data if the mapping names it — data the workflow can read,
never an identity it runs as. This is #1792's "never read `run_as` from the
caller's payload" rule, with "payload" read as "the record's own columns."

## Atomic admission

One outbox row admits **exactly once per trigger**, matching #1792's webhook
durability choice — not #1788's or #1792's looser mechanisms (a Redis `SET
NX` TTL, an in-memory dedupe). The decision and the `WorkflowRun` +
`DispatchOutbox` insert happen in one transaction:

```python
class TableTriggerAdmission(Base):
    id: UUID
    organization_id: UUID
    trigger_id: UUID                # FK virtual_table_triggers.id
    outbox_event_id: UUID           # FK virtual_table_outbox.id
    trigger_revision: int           # pinned at this admission — see below
    workflow_run_id: UUID | None    # NULL when filtered/blocked, not a run
    status: AdmissionStatus         # see below
    created_at: datetime

    __table_args__ = (
        UniqueConstraint("trigger_id", "outbox_event_id", name="uq_table_trigger_admission"),
    )
```

`(trigger_id, outbox_event_id)` is the admission key: several triggers can
evaluate the same outbox row independently, but a given pair is decided once.
The admission insert, the `WorkflowRun` insert and its first `DispatchOutbox`
row are one commit — #1792's webhook-dedup shape extended one step earlier,
not `trigger_dedupe.py`'s cheaper TTL cache. A retry after a crash re-evaluates
the row and hits the unique constraint if a prior attempt already committed;
the violation *is* "already admitted," read back rather than raced against.

**Both the trigger's own revision and the workflow version are pinned at
admission**, read off `VirtualTableTrigger` inside the same transaction:
`WorkflowRun.workflow_version_id` is copied from the trigger's stored value
(never re-resolved against the workflow's current published version), and the
admission carries the trigger's `revision` at that moment, into
`TableTriggerAdmission.trigger_revision` (round 3 of this review: this
prose already claimed the revision was carried; the model had no column
for it — after an edit, the admission history could no longer say which
filter, mapping or principal actually produced a given status). Editing the
trigger afterward bumps `revision` but never touches an admission or run
already committed — the forward-only discipline #1786's `draft_revision` and
#1792's pinned `workflow_version_id` already hold.

## The transactional subscription boundary

The issue's own rule: activation does not backfill old records; reactivation
does not replay disabled-period events; disabling stops new admissions but
does not cancel in-flight runs.

**How "does not backfill" is enforced, checked against #1782's write path
rather than assumed:** `add_outbox` is called unconditionally on every record
insert — a row is written whether or not any trigger exists for that table,
let alone an active one, because #1782 does not know about triggers at all.
So enforcement is entirely on the **read side**, via `activated_at`, a
watermark the consumer compares against `outbox.created_at`: `outbox.created_at
>= trigger.activated_at` admits, older is `FILTERED`.

**A plain timestamp comparison across two transactions is not enough**
(GitHub's automated review caught this: Postgres assigns `now()` when a
statement runs, not when its transaction commits, so a slow record-insert
that *started* before activation but *commits* after it can carry a
`created_at` earlier than `activated_at` even though the row only became
real, to anyone else, after the trigger was already active — exactly the
event a configuring user expects to be caught). Activation closes the
window by taking the **same `FOR UPDATE` row lock on the table #1782's
own schema changes already take**, before reading and setting
`activated_at`, rather than by trusting the timestamps alone: record
inserts hold `FOR SHARE` on the same row for the length of their write
(per #1782's own locking), so activation's `FOR UPDATE` request blocks
until every already-started insert has committed, and no insert can start
until activation releases the lock. Nothing can straddle the boundary once
the lock is held, so the timestamp comparison it takes afterward is
comparing against an activation moment no concurrent write could have
crossed — the same serialization argument #1782's schema-change-versus-write
locking already relies on, reused rather than reinvented. Once admitted, a
(trigger, event) pair produces `FILTERED` for a pre-activation row, never a
`WorkflowRun` — a query-time filter, not a data deletion: the outbox row
itself is untouched, and #1828's sweep still governs its removal.

**Reactivation does not replay** for the same reason: disabling only flips
`is_active`, so the row and its old `activated_at` survive, and reactivation
writes a fresh `activated_at`, strictly later than anything from the
disabled period, whose events are then claimed and marked `FILTERED` as
pre-activation history. **Disabling stops new admissions but does not cancel
in-flight runs**: it removes the trigger from the watermark check
immediately, but writes nothing to `workflow_runs`/`dispatch_outbox`/
`node_runs` — a run already admitted continues under #1788's state machine
untouched, the way revoking a `WorkflowExposure` leaves a started run alone.

## Causation, cycles and quotas

A table-triggered run can itself write a record (a workflow's table-write
node, #1784) that re-enters this consumer. `WorkflowRun` carries
`root_run_id` (the first run in the chain, self if none),
`causation_run_id` (the immediate parent), `visited_trigger_ids: list[UUID]`
(every trigger id already fired in this chain) and `depth: int` (hop count
from the root) — propagated to any outbox row a node inside it produces,
via an optional causation context `records.py`'s write path accepts the same
way it already threads `actor_user_id` through history.

Before evaluating a trigger's filter, the consumer checks: if `trigger.id` is
already in the causing write's `visited_trigger_ids`, admission is `BLOCKED`
— catching self-triggering and any A→B→A cycle structurally, not only by
depth. `depth` past a configured ceiling is also `BLOCKED`, a backstop for a
longer non-repeating chain the visited-set alone doesn't catch.

**Per-root/organization quotas are checked and incremented atomically in the
same admission transaction** — an `UPDATE ... RETURNING` against a counter
row locked `FOR UPDATE`, refusing the insert if it would exceed the ceiling,
not a best-effort count taken beforehand — closing the same race #1788's
budget check closes for spend.

**Admission status is a first-class enum**, not a log line:

```python
class AdmissionStatus(enum.StrEnum):
    QUEUED = "queued"      # WorkflowRun created, dispatch enqueued
    FILTERED = "filtered"  # RecordFilter did not match, or predates activation
    BLOCKED = "blocked"    # cycle (visited-trigger) or depth/quota ceiling
    FAILED = "failed"      # admission itself errored (e.g. permission recheck)
```

Every row carries one of these, exposed on a **trigger's own history view** —
`GET .../triggers/{trigger_id}/admissions`, gated by `Perm.TABLES_VIEW` and
`Perm.WORKFLOWS_VIEW`, paginated newest-first, each row showing `status`,
`created_at`, `workflow_run_id` when present, and a coarse `reason` for
`blocked`/`filtered`/`failed` — never the record's own data. This is the
surface the issue's "blocked, filtered, queued and failed events" and
"visible without leaking record data" criteria both point at.

## Permission recheck, at activation and at execution

**At activation** (creating or re-enabling a trigger): `resolve_access` for
the configuring user against the table (`Perm.TABLES_VIEW`, the authority to
manage the trigger at all), *and*, separately, the two checks execution will
actually require — the **stored execution principal** against the workflow
(`Perm.WORKFLOWS_RUN`) *and* the same stored principal against the table
(`Perm.TABLES_VIEW`) — run before the row is written or `is_active` flips
true. Checking only the configuring user's table access was the earlier
draft's gap (round 3 of this review): a configuring user with table access
can name a different execution principal who can run the workflow but
cannot view the table, and activation would have accepted it, producing a
trigger that deterministically `FAILED` every future event with nothing at
activation time to say why.

**At execution**, before each admission commits, the same `WORKFLOWS_RUN`
(and table-view) check re-runs against the *stored* principal fresh, because
access can be revoked between activation and a later event — the scenario
#1788 already guards for a resuming approval and #1792 for a stored
webhook/schedule principal. A failed recheck writes a `FAILED` admission,
never a silent skip, and does not auto-disable the trigger; an operator
reviews the history and disables or re-authorizes it explicitly, the posture
#1788 takes for a stale-authority resume.

## The CRUD response and the workflow are two separate things

The record-CRUD caller — UI, agent tool (#1784), public API, or another
workflow's table-write node — gets exactly today's response: `records.py`'s
create/upsert methods return their existing `RecordWrite`, serialized to the
route's existing `201`/`200`, unchanged. The outbox row is already written in
that same transaction by #1782; nothing here changes that timing. Trigger
evaluation, admission, the run and its result all happen **after** that
transaction has committed, in a separate consumer pass. The CRUD response
body never carries a `workflow_run_id`, an admission status, or any hint a
trigger fired — a table-triggered run has no connection to reply on, matching
#1792's rule verbatim. Delivery is the admission history above and the run's
own event stream, never a field bolted onto the record write's response.

## Module layout

```
app/db/models/virtual_table_trigger.py    # VirtualTableTrigger, TableTriggerAdmission, AdmissionStatus
app/repositories, app/schemas/virtual_table_trigger.py
app/services/table_trigger/
  facade.py                                # create/update/activate/deactivate trigger, list admissions
  consumer.py                               # claim outbox rows, evaluate filter, call workflow_admission.admit()
  causation.py                              # visited-trigger/depth/quota checks, shared with #1784's write node
app/api/routes/v1/virtual_table_triggers.py
app/worker/tasks/table_trigger_tasks.py     # workflow-dispatch-table-trigger deployment
```

New tables: `virtual_table_triggers`, `table_trigger_admissions`, org-scoped,
FK to `virtual_tables`/`workflows`/`workflow_versions`. Migration stacks
above whatever #1786/#1788/#1792 land as, and above #1828's
`0093_virtual_table_sweep_indexes` on #1782's branch; verify `alembic heads`
at implementation time rather than trusting a number written today.

**Registers a `DependencyChecker`**, the third of the three registrants
#1782's dependency hook already names in its own docstring (#1783 registers
for saved views, #1784 for `TableIORef` bindings, this is the trigger's
own): `register_dependency_checker(trigger_dependents)` at
`table_trigger` import time, scanning active `VirtualTableTrigger` rows
whose filter or `input_mapping` names a `column_id` in the archived set and
returning `Dependent(kind="table_trigger", id=trigger.id)` per match —
archiving a column a live trigger filters or maps on is refused, naming the
trigger, rather than leaving it silently matching nothing or mapping a gap.

## Test plan against the acceptance criteria

| AC | Assertion |
|---|---|
| AC1 — one run per trigger/event under duplicate delivery | Two concurrent consumer passes over one insert (a lease race) yield exactly one `QUEUED` admission and one `WorkflowRun`; the second resolves via the `(trigger_id, outbox_event_id)` constraint. |
| AC2 — updates, upsert-update, failed transactions, duplicate writes do not trigger created | Covered upstream by #1782 (the event is written only on insert; an update or rolled-back write produces no outbox row); this test only confirms the consumer never sees a row for those cases. |
| AC3 — filters use the creation snapshot; revoked access blocks execution | A filter evaluates against the record's own values *at creation*, not a live re-read, so a later edit cannot retroactively change whether a past event matched. A principal revoked between activation and the event produces `FAILED`, no run. |
| AC4 — self-triggering and A→B→A chains stopped and visible without leaking record data | A write node re-entering its own trigger, and a two-trigger A→B→A cycle, both resolve to `BLOCKED` via the visited-trigger-id check; the admission history shows `status=blocked` and a reason string, never the record payload. |

## Open dependencies this design does not resolve

**#1789** owns `core.input`'s real field shape; input mapping here designs
against #1792's own hedge and needs no redesign once #1789 lands. **#1786**
owns graph validation's real implementation; the type-compatibility check
reused for input-mapping validation is borrowed by reference. **#1788** owns
the run state machine and #1792 owns `admit()`; this design treats both as
fixed interfaces and adds no third execution or admission path of its own.
