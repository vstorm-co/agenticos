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
checker whether something the caller can see still uses it. Saved views are the one
registered today (see [saved views](#saved-views)); workflows and triggers will
register theirs in `app/services/virtual_tables/dependencies.py`. A refusal names the
dependents in `SCHEMA_DEPENDENCY`. A dependent the caller cannot see is never named
and never blocks them: its feature copes with the change instead.

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

A delete is a hard delete. The record's history stays.

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

## Saved views { #saved-views }

A **view** is a kept filter, sort and grouping over one table's records - what the
console's table/kanban/list screens save so a person does not rebuild the same
board every visit. It is a sub-resource of the table, not a shareable resource of
its own: a view has no owner-and-grants of its own kind, and `shared` means only
"visible to anyone who already holds `tables:view` on the parent table" - it never
widens access beyond what the table itself allows.

`GET/POST /tables/{id}/views` and `GET/PATCH/DELETE /tables/{id}/views/{view_id}`
list, create, read, update and delete them. The list is paged with `skip` and
`limit` (at most 100), the caller's own views first, then the shared ones, each by
name; `total` counts them all. `config` is `{filters, sort,
visible_columns, group_by}` - a `RecordQuery` plus the two fields only the
console's own rendering needs: `visible_columns` (`null` means every live column)
and `group_by` (a live `single_select` column, for a kanban board's lanes).

| Field | Meaning |
|---|---|
| `kind` | `table`, `kanban` or `list` - a view is saved *for* one kind |
| `visibility` | `private` (only its owner) or `shared` (anyone who can see the table) |
| `can_manage` | Whether this caller may rename, reconfigure or delete it |

Listing, reading and deleting resolve against the table (`tables:view`); creating
or changing one needs `tables:edit` on the table, so an owner whose edit access was
taken away can still delete their views but no longer reshape or share them.

Changing or deleting a view is narrower still: only its owner, or a caller whose
`tables:edit` [scope](permissions.md) is `ALL` - not "anyone who can edit the
table" - so a shared editor cannot silently repoint another member's saved filter. Refused
the same way every other per-resource write here is: `NOT_FOUND` (404), never a 403
that would disclose a view's existence to a caller it refuses.

Archiving a column that a view the caller can see - their own, or a shared one -
filters, sorts or groups by is refused with `SCHEMA_DEPENDENCY`, naming the view.
Another member's private view does not block the archive and is not named: the
caller could neither see nor change it. Showing a column in `visible_columns` does
not block either. Whatever a view still names of a column that is no longer live is
dropped when the view is read: a filter on it goes, a sort by it falls back to
`created_at`, a grouping by it is cleared, and it leaves `visible_columns`. The
stored config is not rewritten.

## What commits together { #what-commits-together }

A record write, its history row, its idempotency receipt and, for a create, a
`table.record.created` outbox row are written in one transaction and commit or roll
back together. A failure at any step leaves none of them. Table and schema changes
are recorded in the [audit log](governance.md); record changes are recorded in the
per-record history, which keeps the values before and after each change.

Three of these stores keep data with no retention yet. The per-record history and the
receipts hold the values, so a record delete removes the current row and leaves both
behind. A receipt holds the whole record as the write returned it, and is removed only
with its account or organization. Outbox rows hold ids, and are never purged after
delivery. Treat them as personal data if the cells are; see
[data protection](data-protection.md#the-database).

These stores hold full snapshots, and a genuine edit of a large record still writes one to
the history, and one to a receipt when a key is sent. Per-tenant quotas or rate limits on
that growth, and storing only what changed, are not implemented yet.

The outbox row is the hand-off to whatever reacts to a new record. Nothing consumes
it yet. A consumer claims undelivered rows in its own session and marks them
delivered.

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

Whether a specific caller may edit a specific table is also on the wire directly:
`TableSummary.can_edit` and `TableRead.can_edit` are resolved server-side (role
scope or an explicit grant) and shipped on every read, the same way `Agent.can_run`
is - so a catalog row or a detail page never has to guess whether its edit controls
would be refused. A saved view's own `can_manage` is the same idea, one level down
(see [Saved views](#saved-views)).

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
| `ALREADY_EXISTS` | 409 | The table name, a view name or the external id is taken |
| `INVALID_RECORD` | 422 | A value does not fit its column; `details.fields` names each one |
| `ARCHIVED_COLUMN` | 422 | A value names an archived column |
| `INVALID_QUERY` | 422 | A filter or sort the table cannot answer |
| `INVALID_SCHEMA` | 422 | An inconsistent schema change |
| `IDEMPOTENCY_KEY_REUSED` | 422 | The key was used for a different request |
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
- Agent tools and typed workflow nodes over tables, and triggers on record
  creation. The console screens (table creation, schema editing, record CRUD and
  the saved table/kanban/list views this page's [Saved views](#saved-views)
  section describes) exist; agent- and workflow-side access to the same service
  does not yet.
- Consumers of the outbox, and dependency checkers for workflows and triggers -
  saved views already register one (see [Saved views](#saved-views)).
- Per-tenant quotas or rate limits on history and receipt growth, and delta storage for them.
