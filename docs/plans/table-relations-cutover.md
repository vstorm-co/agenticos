# Relationship storage and cutover

Engineering rollout note for PR #101. This is a coordinated cutover, not a rolling
upgrade that can keep old table writers running.

## Storage contract

A relationship is identified by its existing source table and immutable column
ID. `virtual_table_relations` declares its destination table, archive state and
maximum number of destinations per source record. An omitted `link_limit` keeps
the existing limit, or defaults to 100 for a new field. A limit of 1 represents a
single destination; this release does not claim destination uniqueness or
one-to-one relationships.

`virtual_table_record_links` holds each connection once. Composite foreign keys
bind both endpoints to the same organization and to the tables declared by the
relationship. A source/field/target primary key prevents duplicate destinations.
A unique source/field/position plus a position bound enforces the declared
cardinality inside PostgreSQL, including concurrent attempts to exceed a limit
of 1. The source owns ordering; backlinks read the same edges. Active positions
are dense while retaining relative order; evidence keeps original rejected
positions. Narrowing counts active edges, including hidden valid destinations,
so quarantine entries do not prevent a valid cardinality change.

Normal writes synchronize edges at the existing record repository boundary,
inside the same transaction as the record, revision, history, outbox and receipt.
The source row lock and expected revision still serialize changes. The atomic
link-delta API in PR #100 supplies a merged internal value; preserved hidden
links remain in that internal value. Synchronization does not apply the caller's
read projection to storage.

Current reads project ordered edges before validating the public record shape.
Destination table and row authorization still runs after this internal
projection, including for labels, lookups and rollups. A receipt at an older
source revision keeps its original source snapshot and resolves destination
visibility at read time. It must not combine today's edges with an older
revision number.

Authorized `contains` and `is_null` filters join these same edges to readable
destination rows before pagination or counting. One-hop project membership
uses canonical edges in SQL and the same validated field/cardinality rules for
single-record checks. A quarantined legacy value therefore grants no inherited
Read access and cannot make a link filter match. Explicit row Read/Write grants
remain subject to the destination table's access boundary.

The original JSON link representation remains available for immutable history,
legacy evidence and rollback. Direct writes outside the repository boundary are
unsupported after cutover. No per-user-table DDL runs on an API request.

## Archive, delete and quota behavior

Archiving a link field retains its definition and edges; restoring the same field
ID restores the same connections. Reverse traversal refuses an archived field.
Deleting a destination record removes incoming edges through a foreign-key
cascade and leaves the source record and its revision intact. Deleting a source
record removes its edges. Deleting a table removes its corresponding definitions
and edges; a reference does not give another table a second copy of a record.

Relationship definitions, edges and retained evidence count against organization
storage usage. Table creation, schema changes and record writes share the same
storage admission lock, acquired before table or record locks. A schema change
and any type conversion share one savepoint, including definitions and history;
table creation includes its completed receipt. Storage is checked before the
ordinary table audit because a refusal audits in a separate transaction. A
refused operation leaves only that content-free refusal audit, even if its
caller catches the error and commits the surrounding transaction. Receipt
replays and unchanged schemas remain available above a lowered ceiling.

## Read-only reverse traversal

`GET /tables/{table_id}/records/{record_id}/backlinks` requires
`source_table_id` and `column_id`, with bounded `skip` and `limit`.

The service authorizes the destination table and record, the named source table,
and each source row before pagination. It returns source records using the
ordinary read pipeline. There is no hidden total, relation enumeration or reverse
write route. A backlink supplies neither a row grant nor source write permission.
Recursive permission inheritance, editable reciprocal fields, polymorphic
destinations and one-to-one destination constraints are outside this version.

## Backfill and evidence

Migration `0327_virtual_table_relations` follows `0326_room_threads` from #90.
The application dependency stack is #103, #99 and #100 before #101; the room
thread migration must also be integrated before this revision is released.
The earlier, unreleased `0326_virtual_table_relations` checkpoint was renumbered
to avoid sharing a revision number with the room migration. Its original commit
and rehearsal receipts remain historical evidence below, not validation of the
new parent chain. Never edit a migration that has reached a deployed database.

The migration requires a complete Tables read and write outage. Adding the
composite record uniqueness constraint takes an `ACCESS EXCLUSIVE` lock on
`virtual_table_records`, held through the entire transactional backfill; reads
also wait behind that lock. The explicit write barrier alone does not describe
the outage. The migration copies current schema definitions including archived
fields and walks source records in 500-row keyset batches. It keeps
source IDs, column IDs, source revisions, schema versions, record JSON and
immutable history unchanged. Existing valid destinations become ordered edges.

`virtual_table_link_evidence` retains the original value, source revision and
position for malformed cells, invalid IDs, missing destinations and duplicate
destinations. IDs outside the declared destination table or organization are
recorded as unavailable destinations without copying foreign record content.
An over-limit cell is retained whole and produces no partial set of live edges.
This can make fewer links visible after cutover; an operator must inspect and
repair the retained evidence, not assume the migration resolved it.

An invalid relationship definition, including a missing or cross-organization
destination table or an invalid stored limit, aborts the transaction. Only an
omitted or null limit uses the legacy default of 100; zero, false and blank values
require repair before cutover. The migration does not guess a new destination
or silently drop an invalid field. Evidence has no record foreign
key, so deleting a record does not erase its migration evidence; deleting the
source table still removes that table's data.

## Pre-cutover storage projection

On the disposable copy, record each organization's current charged storage,
then migrate and measure the additional definitions, edges and evidence with
the same `virtual_table_repo.storage_bytes` accounting used by admission. Include
archived definitions and their retained edges, rejected whole cells and duplicate
or invalid destinations. The old JSON and immutable history remain stored, so
their bytes cannot be subtracted from the projection.

Produce one row per organization with the pre-migration bytes, additional bytes
for each of the three relationship tables, total projected charged bytes, the
deployment's `TABLES_MAX_STORAGE_BYTES_PER_ORGANIZATION`, and remaining headroom.
Flag every organization above the ceiling, and those with insufficient headroom
for their expected next writes, including history, receipts and outbox copies.
The migration neither changes this setting nor discards evidence to fit it.
An organization above the ceiling retains reads, receipt replays, no-ops and
deletes, but storage-growing operations will be refused. Resolve the reported
headroom requirements before scheduling cutover; this PR does not authorize a
production quota change.

Measure physical database and index growth separately from the admission charge,
along with the complete read/write outage duration, on a representative restored dataset. Counts
or a small fabricated-data rehearsal do not establish production disk capacity
or migration timing.

## Deployment gate and rehearsal

1. Review the dependency stack: #103 link-visibility hardening, #99 explicit row
   Read/Write access and #100 atomic link deltas. This checkpoint combines their
   implementation with canonical read/write baselines and authorized edge
   predicates; keep the combined permission regressions in the required CI
   run. Keep the schema-definition quota, refusal rollback, concurrent lock-order
   and cached batch authority regressions in that run. The required CI coverage
   gate and deployment-specific rehearsal remain prerequisites for activation.
2. On a disposable copy, rehearse the migration and inspect invalid definitions,
   evidence counts and the per-organization storage projection above. Check valid
   edge counts and ordered destinations against source values; resolve invalid
   definitions and quota headroom before scheduling cutover. Large installations
   need measured lock duration and migration disk headroom.
3. Schedule a complete Tables read and write outage. Stop table-serving API
   processes, imports, agents, workflow workers and background jobs; block new
   table reads as well as writes and drain in-flight transactions. Apply the
   migration while that outage remains in force, then start only application
   versions that synchronize edges.
4. Verify one Alembic head, target/source organization constraints, representative
   direct reads, bounded views, CSV, receipts, deltas and backlinks under a
   restricted member identity. Resume Tables traffic after these checks.
5. Keep the previous release and database backup available until verification
   finishes. A downgrade removes relationship storage and leaves source JSON
   intact, but old code does not enforce the new link limits or Read/Write
   policy contract. Rollback therefore needs the same write barrier and a
   deliberate application-version decision.

The earlier unreleased checkpoint passed a full-chain PostgreSQL rehearsal on
2026-11-14 UTC, using a new disposable database and fabricated tenants. These
receipts name its original `0326` revision and predecessor; repeat the chain
rehearsal after integration of `0326_room_threads` and the renamed `0327`:

- A fresh upgrade reached `0325_merge_t3_rooms_v173`. An intentionally invalid
  cross-organization relationship then refused `0326` without leaving its tables
  or changing the seeded data or recorded migration version.
- After repairing that fixture's definition, `0326` produced two definitions,
  four ordered edges and seven evidence rows for malformed cells, invalid IDs,
  missing destinations, a duplicate and an over-limit cell. Archived definitions
  were retained. Original values, source revisions, schema versions, history,
  receipts and outbox snapshots were unchanged.
- `alembic check` reported no new upgrade operations. Downgrading to `base`,
  upgrading the complete chain again and repeating that check passed with the
  single head `0326_virtual_table_relations`.
- The rehearsal dropped only the unique test database it created.

The focused migration tests additionally cover the second 500-row backfill page.
These checks do not establish production disk headroom or cutover duration, and
the required CI coverage gate and representative restored-data rehearsal still
apply. No migration should run against a live deployment as part of this PR's
development or validation.
