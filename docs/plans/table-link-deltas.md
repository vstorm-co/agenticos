# add atomic linked-record edits

Status: implemented; draft awaiting stacked integration and CI. Owner: shermzy.
Requested on 15 November 2026 (Asia/Singapore). Base: t3 at 080c1294.

## Contract

Add typed add/remove link changes to record updates and use them in the table UI, preserving relationships hidden from the editor.

`RecordUpdate.link_changes` is keyed by immutable link-column UUID. Each entry
contains bounded `add` and `remove` UUID lists. The update keeps the existing
revision check, storage quota, transaction, history, trigger and idempotency path.
Only explicit targets are checked for current read access; retained hidden links
are not treated as newly submitted IDs. Scalar edits can share the same request.
Explicit target authorization runs before applying the delta or checking the
resulting cardinality. Even at the link limit, an already-linked hidden ID and
an unknown ID receive the same missing-record refusal. A limit error must not
reveal whether an unreadable destination is already linked.

The grid and record panel emit deltas. The shared write queue advances revisions,
and the conflict store retains and composes explicit choices. A successful delta
settles only the targets it actually sent, preserving earlier unapplied choices
that conflicted while another write was already in flight.

## Acceptance checks

- Validate explicit added/removed targets, source Write and protected security-parent changes.
- Preserve hidden existing links and enforce final link-count limits.
- Reject duplicate, conflicting, unknown and archived-field deltas.
- Retain revision conflicts, idempotency, transactional history and outbox behavior.
- UI sends deltas and keeps edits available after a conflict.

## Dependencies and ownership

Depends on `fix/tables-access-hardening-20261115`, #99.
Preserve the agreed row Read/Write contract: Write includes Read and updates to
ordinary fields, while deletion, sharing and schema administration stay separate.
Coordinate through this PR before overlapping implementation. During integration,
access-field checks must see the fully merged values. Legacy replacement
preservation receives only original `values` keys. Both replacements and deltas
validate every explicitly named destination, including existing links and no-ops;
only omitted hidden destinations are preserved without a caller Read check.

The normalized-relationship follow-up supplies the canonical write baseline,
including hidden valid targets. Use it for delta resolution, merging, access
checks and no-op detection; keep the original stored values for history evidence.
This prevents quarantined malformed legacy values from being reintroduced.

## Validation and rollout

Use focused deterministic tests and the exact revision's CI. Database constraint
and migration behavior requires disposable PostgreSQL integration tests. Preserve
existing data, revisions, history, idempotency and tenant checks. No production
configuration, migration, merge or deployment is authorized by this plan alone.

Regression coverage includes schema refusals, hidden and missing target symmetry,
wrong-table and foreign-organization IDs, no-op and stale revisions, final count
limits, combined scalar/link writes, receipt replay and reuse, and transaction
rollback after history, event or receipt failure. Frontend checks cover the picker,
grid, record panel, shared queue and conflict reapplication.
