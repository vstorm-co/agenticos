# Virtual Tables

A **virtual table** is a typed table of records that an organization keeps for its
agents, workflows and integrations: orders to reconcile, files to process, leads
to follow up.

Tables are metadata plus JSONB. Nothing creates a physical SQL table, so making a
table costs one row, renaming a column changes no record, and no tenant can grow
the database catalog. Every read and write goes through one service,
`VirtualTableService`, so the console, agent tools, workflow nodes and the public
API share the same rules. This page describes the service and its HTTP routes
under `/api/v1/tables`; the OpenAPI document is the contract for them.

## How a table is built { #how-a-table-is-built }

| Part | What it is | Identity |
|---|---|---|
| **Table** | A name, an owner, a visibility and grants, like a [context file](context.md) | `id`, stable |
| **Schema version** | An immutable snapshot of the columns. A change appends version N+1 | `version` |
| **Column** | A label, a type, whether it may be empty, an optional default | `id`, stable |
| **Option** | One choice of a select column | `id`, stable |
| **Record** | Cell values keyed by column id, a revision and an optional `external_id` | `id`, stable |

Values are keyed by the column's **id**, never its label. A rename therefore
rewrites one schema version and no record. A record remembers the schema version it
was last written under.

A record stores only the cells that hold a value. A cell sent as `null` is cleared,
and a read shows nothing for it. On a create, a column's default fills only the cells
you leave out; a cell you send as `null` stays empty.

## Column types { #column-types }

| Type | Stored as | Filters |
|---|---|---|
| `text` | Text up to 1,000 characters | `eq` `ne` `contains` `starts_with` `in` `is_null` |
| `long_text` | Text up to 100,000 characters | the same as `text` |
| `number` | A finite number | `eq` `ne` `lt` `lte` `gt` `gte` `in` `is_null` |
| `integer` | A whole number, at most 2^53 - 1 | the same as `number` |
| `boolean` | `true` or `false` | `eq` `ne` `is_null` |
| `date` | `YYYY-MM-DD` | the same as `number` |
| `datetime` | ISO 8601 with a time zone, stored as UTC | the same as `number` |
| `single_select` | The id of an option | `eq` `ne` `in` `is_null` |
| `multi_select` | A list of option ids | `contains` `is_null` |

Text is stored exactly as sent. Leading and trailing spaces, line breaks and
whitespace-only values are the user's data, so they are not trimmed. Only a length
limit applies, and the NUL character is refused, in cells and equally in names, labels,
descriptions and external ids, because PostgreSQL cannot store it.

Comparisons match only cells that hold a value. Use `is_null` to find the empty ones.

## Changing a schema { #changing-a-schema }

`PUT /tables/{id}/schema` takes the full list of columns the table should have, and
the `expected_version` the caller last read. The service reconciles it with the
current columns:

- A column with an `id` is that column. A column without one is new.
- A column's **type never changes**, because the values stored under it would no
  longer mean what they did. Add a new column instead.
- Nothing is deleted. A column or option left out is **archived**: its values stay
  readable and filterable, and writing to it is refused with `ARCHIVED_COLUMN`.
- Archived ones count toward the limits. A table holds at most 100 columns and a select
  column at most 100 options, archived included. A change that would exceed either is
  refused with `INVALID_SCHEMA` and appends no version, so replacing a full list of options
  is not possible; add a new column instead.
- A new required column needs a default, since existing records hold nothing for it.
  An existing column cannot become required while any record has no value for it, and a
  required column cannot come back from the archive without a default, because records
  written while it was archived could not hold one.
- A stale `expected_version` is a `SCHEMA_VERSION_CONFLICT`.
- A submission identical to the current columns, with the same ids, order, labels and
  options, changes nothing: no version is appended and the current table is returned. A
  reorder or a changed label is a change.

Records are not rewritten. A record written under version 1 stays readable and
editable under version 4; a required column it never held takes its default the
next time the record is edited.

A record write and a schema change or archive of the same table take turns: the write
waits for one in flight and is then judged against what it committed, so a record never
lands in a table archived a moment earlier.

Archiving a column, or the whole table, first asks every registered dependency
checker whether something still uses it. Workflows, views and triggers do not exist
yet, so none is registered and nothing blocks; `app/services/virtual_tables/dependencies.py`
is where a feature registers one, and a refusal names the dependents in
`SCHEMA_DEPENDENCY`.

## Records and revisions { #records-and-revisions }

Every record has a `revision`, starting at 1 and rising with each change.

| Operation | Route | Needs `expected_revision` |
|---|---|---|
| Create | `POST /tables/{id}/records` | No |
| Update named cells | `PATCH /tables/{id}/records/{record_id}` | Yes |
| Delete | `DELETE /tables/{id}/records/{record_id}?expected_revision=` | Yes |
| Upsert | `PUT /tables/{id}/records/by-external-id/{external_id}` | Only when the record exists |
| Read, exists | `GET .../records/{record_id}`, `.../by-external-id/{external_id}`, `.../exists` | No |

An update or delete that names an old revision is refused with `REVISION_CONFLICT`
(409) and `details.current_revision`; nothing is overwritten. Read the record again
and retry. An upsert that finds an existing record and no `expected_revision` gets
`REVISION_REQUIRED` (428), again with the revision to send.

An external id is 1 to 255 characters and may contain `/`, as in `2026/ORD-1`. It cannot
contain NUL or a line break. The service checks this as well as the routes. Over HTTP the route refuses it first,
with `VALIDATION_ERROR`; a caller that uses the service directly gets `INVALID_RECORD`.

Concurrent upserts of one external id create one record. The loser finds it and is
answered as an update: it needs the revision, or it is told which one to send.

An update that would leave every cell as it is changes nothing. The revision stays, no
history row or receipt is written, and the current record is returned. A stale
`expected_revision` is still a conflict, because it is checked first. An upsert that finds
the record follows the same rule.

A delete is a hard delete. The record's history stays until its retention removes it.

## Safe retries { #safe-retries }

Every record write accepts an `Idempotency-Key` header (at most 128 characters). A
retry with the same key and the same body returns the first answer, with
`Idempotent-Replayed: true`, and writes nothing, even if the record has changed
since. The same key with a different body is refused with `IDEMPOTENCY_KEY_REUSED`.

The header marks a replayed create, update or upsert. A replayed delete answers 204 as the
first one did and is not marked.

A key belongs to the caller and to the kind of write, so two callers can use the
same string and one caller can use it for a create and an upsert. Only successes are
stored: a refused write leaves no receipt, so you correct it and retry with the
same key.

A replay is answered only to a caller who can still edit the table. Once access is
revoked, the same retry is a 404.

A receipt lasts 24 hours. After that the key is forgotten, and the same key with the same
body is a new write: it executes again instead of returning the first answer. Retry within
the window, and treat a longer gap as a fresh request. The lifetime is enforced when the key
is used, so it holds to the hour; the daily sweep only reclaims the space of receipts nobody
retried.

## Listing and filtering { #listing-and-filtering }

`GET /tables/{id}/records` pages through a table; `POST /tables/{id}/records/query`
adds typed filters, all of which must hold. Both are bounded: `limit` is 1 to 100,
`skip` is at most 10,000, and a query has at most 20 filters.

The order is total. The requested sort (`created_at`, `updated_at` or a sortable
column) is followed by the record id, so a page never repeats or skips a record in
an unchanged table. Records with no value in the sorted column come last in either
direction. A `multi_select` column cannot be sorted. `updated_at` is set when a record is
created and moves on each edit, so records nobody has edited sort by their creation time.

There is no `total`, because counting a filtered table is not cheap. `has_more` says
whether another page follows.

## What commits together { #what-commits-together }

A record write, its history row, its idempotency receipt and, for a create, a
`table.record.created` outbox row are written in one transaction and commit or roll
back together. A failure at any step leaves none of them. Table and schema changes
are recorded in the [audit log](governance.md); record changes are recorded in the
per-record history, which keeps the cells each change touched.

Two of these stores hold copies of what was written. A receipt holds the whole record as
the write returned it, and history holds what changed, so a record delete removes the
current row and leaves both behind until their retention removes them. Outbox rows hold
ids. Treat all three as personal data if the cells are; see
[data protection](data-protection.md#the-database) and
[limits and retention](#limits-and-retention).

The outbox row is the hand-off to whatever reacts to a new record. Nothing consumes
it yet, so nothing ever marks one delivered - a future consumer claims undelivered rows in
its own session and marks them dispatched. Until then, an undispatched row is removed only
by its own much longer retention window (below), a dead-letter cutoff rather than a claim
that the event was ever collected.

## Limits and retention { #limits-and-retention }

A tenant can only grow the shared database as far as the deployment lets it. Every limit is
a deployment setting, applies **per organization** so one tenant's usage never counts
against another's, and is refused with `QUOTA_EXCEEDED` (402) when a write would pass it.

| Setting | Default | Limits |
|---|---|---|
| `TABLES_MAX_PER_ORGANIZATION` | 200 | Tables an organization has. Archived ones count, because a table is never deleted |
| `TABLES_MAX_RECORDS_PER_TABLE` | 100,000 | Records in one table. Updating a record in a full table is allowed |
| `TABLES_MAX_RECORD_BYTES` | 1,000,000 | The serialized values of one record, in bytes |

The refusal names the quota and its ceiling in `details` (`{"quota": "records", "limit":
100000}`), never the content, and writes a `table.quota_refused` entry to the
[audit log](governance.md) with the same two fields. Nothing is written by the refused
request. Writes are also limited to `RATE_LIMIT_TABLE_WRITES_PER_MINUTE` (300) per member
and organization, in the console as much as over the API; a member over it gets a 429 with
`Retry-After`. See [configuration](configuration.md#rate-limiting).

**What history keeps.** A create keeps the whole record in `after`, and a delete keeps the
whole record in `before`; the record limit bounds both. A record that predates the limit,
or was written before `TABLES_MAX_RECORD_BYTES` was lowered, can still be over it - its
delete then keeps `before` as `{"omitted": {"bytes": <its size>, "limit": <the limit>}}`
instead of the values, and still succeeds. An update keeps only the cells that changed:
`before` holds their earlier values and `after` their new ones, and a column missing from
one side was empty there. Editing one cell of a large record therefore costs one cell,
however often it is repeated.

**Retention.** The daily [retention sweep](governance.md#retention) also removes table
data, hard-deleting in batches, for every organization:

| What | Removed when | Setting |
|---|---|---|
| Receipts | Older than 24 hours | `TABLES_RECEIPT_TTL_HOURS` |
| Outbox rows | Dispatched more than 3 days ago | `TABLES_OUTBOX_RETENTION_DAYS` |
| Undispatched outbox rows | Never dispatched and 30 days old. Nothing consumes this outbox yet, so every row reaches this window eventually - see below | `TABLES_OUTBOX_UNDISPATCHED_RETENTION_DAYS` |
| History | Older than 365 days, for a deleted record as much as a live one | `TABLES_HISTORY_RETENTION_DAYS` |

The sweep writes one audit entry per organization, naming the class (`table_receipts`,
`table_outbox`, `table_history`) and the count. These are deployment settings, not
per-organization ones. The records themselves and the tables are never removed by it.

`RATE_LIMIT_TABLE_WRITES_PER_MINUTE` is a *per-member* allowance, so one pass's budget for
each of the three classes scales with both it and the organization's own active member
count, with headroom so a pre-existing backlog is worked down rather than merely held level
- every member writing flat out at once never outpaces the sweep, up to a generous cap on
how many members one organization's own pass sizes itself for. See
[configuration](configuration.md#virtual-tables-limits-and-retention) for the numbers. A
backlog beyond that is worked off over several passes, the same as any other class.

## Who can do what { #who-can-do-what }

| Permission | Holds it |
|---|---|
| `tables:view` | Owner, admin, builder and operator see all tables; a member or viewer sees their own, org-visible and shared ones |
| `tables:edit` | Owner and admin edit all; a builder edits their own and shared; a member edits their own |
| `tables:create` | Owner, admin, builder, member |

`tables:view` and `tables:edit` are resource permissions, so a [grant](permissions.md)
on one table widens a role for that table only: a viewer given `edit` on one table
edits that table and nothing else. Sharing uses the same `/tables/{id}/sharing`
routes as the other shared resources. Records inherit their table's access, and the schema enforces it: a record, history or
outbox row references its table through the organization as well, so a row cannot name a
table from another tenant.

Another organization's table, and one the caller may not reach, are both a 404. A
context with no signed-in subject reaches nothing.

## Errors { #errors }

Every refusal answers `{"error": {"code", "message", "details"}}`, and the `code` is
what a client branches on.

| Code | Status | Meaning |
|---|---|---|
| `REVISION_CONFLICT` | 409 | The record changed since it was read |
| `REVISION_REQUIRED` | 428 | An upsert of an existing record needs `expected_revision` |
| `SCHEMA_VERSION_CONFLICT` | 409 | The schema changed since it was read |
| `SCHEMA_DEPENDENCY` | 409 | Something depends on what the change removes |
| `TABLE_ARCHIVED` | 409 | The table refuses writes |
| `ALREADY_EXISTS` | 409 | The table name or the external id is taken |
| `INVALID_RECORD` | 422 | A value does not fit its column; `details.fields` names each one |
| `ARCHIVED_COLUMN` | 422 | A value names an archived column |
| `INVALID_QUERY` | 422 | A filter or sort the table cannot answer |
| `INVALID_SCHEMA` | 422 | An inconsistent schema change |
| `IDEMPOTENCY_KEY_REUSED` | 422 | The key was used for a different request |
| `QUOTA_EXCEEDED` | 402 | The write would pass a storage limit; `details` names the quota (`tables`, `records`, `record_bytes`) and its ceiling |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many table writes in the last minute; see `Retry-After` |
| `VALIDATION_ERROR` | 422 | The request itself is malformed: a wrong type, an unknown field, a limit, or NUL, a line break or a lone surrogate in an id, key or name. Refused by the route before the service runs |
| `AUTHORIZATION_ERROR` | 403 | The caller lacks the permission a collection route requires (`tables:view`, `tables:create`) |
| `CONCURRENT_CHANGE` | 409 | An upsert lost a race with the deletion of the same record. Retry it |
| `NOT_FOUND` | 404 | No such table or record, or not one the caller may reach |

## Calling the service from Python { #calling-the-service-from-python }

```python
service = VirtualTableService(db)
table = await service.create_table(ctx, TableCreate(name="Orders", columns=[
    ColumnInput(label="Customer", type="text"),
]))
customer = str(table.columns[0].id)

written = await service.upsert_record(
    ctx, table.id, "ORD-1042", RecordUpsert(values={customer: "Acme"}),
    operation_key="import-2026-09-21-row-17",
)

# Send the revision back to change it; a stale one raises RevisionConflictError.
await service.upsert_record(
    ctx, table.id, "ORD-1042",
    RecordUpsert(values={customer: "Acme Ltd"}, expected_revision=written.record.revision),
)
```

The organization always comes from `ctx`, never from an argument. The service never
commits: the request's session does, and a worker owns its own session scope.

## Not built yet { #not-built-yet }

- **A principal for API keys.** Access, receipts and history all name a signed-in
  user. How an API key acts on a table for the external API is still to be agreed.
- Agent tools, workflow nodes and the console screens, which will call this service.
- A consumer of the outbox. Until one exists, every created-record event reaches
  `TABLES_OUTBOX_UNDISPATCHED_RETENTION_DAYS` and is discarded rather than delivered - a
  disclosed dead letter, not a queue anything can drain today.
- Dependency checkers for workflows, views and triggers.
