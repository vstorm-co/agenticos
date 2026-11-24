# normalize record relationships

Status: claimed implementation draft. Owner: shermzy.
Requested on 15 November 2026 (Asia/Singapore). Base: t3 at 080c1294.

## Contract

Introduce canonical relationship definitions and indexed edges with composite tenant/table constraints, ordered links and read-only backlinks.

## Acceptance checks

- Verify organization, endpoint table and relationship-definition constraints in PostgreSQL.
- Backfill ordered and archived links; preserve evidence of dangling or invalid legacy references.
- Choose an explicit canonical cutover after parity checks; do not maintain competing authoritative stores.
- Enforce cardinality transactionally and include relationship storage in quota accounting.
- Preserve stable field/record IDs and avoid fabricated business revisions/events during representation backfill.

## Dependencies and ownership

Depends on #100.
Preserve the agreed row Read/Write contract: Write includes Read and updates to
ordinary fields, while deletion, sharing and schema administration stay separate.
Coordinate through this PR before overlapping implementation. This initial
commit records the implementation contract; application changes follow after
all draft PRs have been opened and claimed.

## Validation and rollout

Use focused deterministic tests and the exact revision's CI. Database constraint
and migration behavior requires disposable PostgreSQL integration tests. Preserve
existing data, revisions, history, idempotency and tenant checks. No production
configuration, migration, merge or deployment is authorized by this plan alone.
