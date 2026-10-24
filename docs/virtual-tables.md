# Virtual Tables

A **virtual table** is a typed table of records that an organization keeps for its
agents, [workflows](workflows.md) and integrations: orders to reconcile, files to
process, leads to follow up.

Tables are metadata plus JSONB. Nothing creates a physical SQL table, so making a
table costs one row, renaming a column changes no record, and no tenant can grow
the database catalog. Every read and write goes through one service,
`VirtualTableService`, so the console, agent tools, workflow nodes and the public
API share the same rules. This page describes the service and its HTTP routes
under `/api/v1/tables`; the OpenAPI document is the contract for them.

## External clients { #external-clients }

Organization API keys are accepted on `/api/v1/tables`. Send
`Authorization: Bearer aos_…`; the organization comes from the key. Reads need
`tables:view`, record and schema writes need `tables:edit`, and creating a table
needs `tables:create`. The issuer's current access and the key's scopes both apply.
Receipts and history name the issuer; a key cannot widen their access. An inaccessible
table answers `404`, a missing collection permission `403`, a stale revision `409`,
and an invalid query or record `422`. Retrying a record write with the same
`Idempotency-Key` and body returns its original outcome without another created event.

`POST /api/v1/tables/{id}/records/query` accepts `columns` (up to 100 live column
IDs) alongside filters, sort, skip and limit. Only those cells and link labels reach
the response. `null` keeps the full record; `[]` returns metadata only. Computed
columns are evaluated before projection, so their dependencies need not be selected.
The same records immediately appear in the console; table-trigger dispatch is
asynchronous and never delays the CRUD response.

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
| `email` | An address with one `@` and a dot in its domain, up to 254 characters | the same as `text` |
| `url` | An `http` or `https` address with a host, up to 2,048 characters | the same as `text` |
| `phone` | Digits, spaces and `+ ( ) - . /`, at least five digits | the same as `text` |
| `number` | A finite number | `eq` `ne` `lt` `lte` `gt` `gte` `in` `is_null` |
| `integer` | A whole number, at most 2^53 - 1 | the same as `number` |
| `rating` | A whole number from 1 to 5 | the same as `number` |
| `boolean` | `true` or `false` | `eq` `ne` `is_null` |
| `date` | `YYYY-MM-DD` | the same as `number` |
| `datetime` | ISO 8601 with a time zone, stored as UTC | the same as `number` |
| `single_select` | The id of an option | `eq` `ne` `in` `is_null` |
| `multi_select` | A list of option ids | `contains` `is_null` |
| `link` | A list of up to 100 record ids of the table it links to | `contains` (a record id) `is_null` |
| `lookup`, `rollup` | Nothing: worked out when a record is read | none |
| `formula` | Nothing: worked out from the record's other columns when it is read | none |

Text is stored exactly as sent. Leading and trailing spaces, line breaks and
whitespace-only values are the user's data, so they are not trimmed. Only a length
limit applies, and the NUL character is refused, in cells and equally in names, labels,
descriptions and external ids, because PostgreSQL cannot store it.

Comparisons match only cells that hold a value. Use `is_null` to find the empty ones.
`contains` and `starts_with` take a piece of a value, so `@example.com` finds the
addresses at a domain in an `email` column.

An agent's table tools and a workflow's table steps name a choice by its option's
label instead, matched case-insensitively: they write and filter by label, and read a
record's choices back as labels, an archived option's too. A value naming no live
option is refused with the options the column has.

## Links, lookups and rollups { #links-lookups-and-rollups }

A `link` column holds records of another table, or of the same one, named by
`link_table_id`. Writing one checks that each record exists in that table and
that the writer can see it, so a link cannot be used to learn which ids a
private table holds. A record reads its links back named, in `links`, by each
linked record's first text value, then its external id. A linked record deleted
since simply drops out.

A `lookup` reads one column of the linked records through a link column of the
same table (`link_column_id`, `target_column_id`): the values, a choice by its
label. A `rollup` works one out: `count` the links, or the `sum`, `avg`, `min`
or `max` of a column of numbers - `min` and `max` also of dates. Both are worked
out when a record is read and never stored, written, filtered or sorted by.

What a lookup shows goes no further than its reader may: a linked table the
reader cannot see leaves the links unnamed and every lookup and rollup through
them empty. A link keeps its table for life. A lookup reads a column holding
values, not another link or lookup, and archiving a link column is refused
while a lookup or rollup still reads through it. An export writes a link by the
names of its records, and a lookup by what it read.

## Formulas { #formulas }

A `formula` column works a value out from the record's other columns:
`{Price} * {Quantity}`, `IF({Total} > 100, "large", "small")`,
`ROUND({Total} / {Count}, 2)`, `DAYS({Due}, TODAY())`. A column is named by its
label in braces, and renaming it rewrites every formula that names it. A formula
calculates with `+ - * / %`, compares with `= <> < <= > >=`, joins conditions with
`and`, `or` and `not`, and calls `IF`, `ROUND`, `ABS`, `MIN`, `MAX`, `CONCAT`,
`LEN`, `UPPER`, `LOWER`, `DAYS` and `TODAY`. A choice reads as its label.

It may read any live column holding values, a lookup's or rollup's result
included, but not a link or another formula, and a column a formula reads cannot
be archived. Saving the schema checks the formula and says what is wrong with
it. A value it cannot work out - a division by zero, text in a sum, an empty
cell - leaves that record's cell empty. A formula is worked out when the record
is read, like a lookup, and is never stored, written, filtered or sorted by.

## Changing a schema { #changing-a-schema }

`PUT /tables/{id}/schema` takes the full list of columns the table should have, and
the `expected_version` the caller last read. The service reconciles it with the
current columns:

- A column with an `id` is that column. A column without one is new.
- A column's **type changes only to one its values read as**, and the change
  rewrites every record's value. Any value becomes text; text becomes a number, a
  yes/no, a date or a single select when it says one - a select gains an option per
  distinct value; a whole number becomes a number and back when it is whole; a date
  becomes a date and time; one choice becomes several and back when there is one.
  Any other change is refused, and so is one some value does not survive, naming
  how many and one example - nothing is written. Something that uses the column
  refuses it as an archive does. A record's revision moves on, so an edit against
  its old value is a conflict.
- Text becomes an `email`, `url`, `phone` or `rating` column when every value reads
  as one, and a number becomes a rating when it is a whole number from 1 to 5. Each
  of them becomes text again, and a rating a number.
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

Each column carries a read-only **`revision`**, which is `0` for a new column and for
every column that existed before it was added. It counts the changes to what the
column's values *mean*, so a published [page](artifacts.md#live-data) can tell that
the column it was published against is no longer that one. It goes up by one on:

- a type conversion;
- a change to a formula, compared after a rename has been written through it, so renaming
  a column that a formula reads does not count, but another column taking over the label does;
- a different link, lookup or rollup target, or a different aggregate;
- archiving or restoring the column, or archiving or restoring one of its select options.

A new label, default or requiredness, a relabelled select option and a new option leave it
as it was. A filter holds option ids, so none of those changes what a filter matches. A
`TableRead` column can be sent back in a schema change as it came: the field is accepted and
ignored, and only the change itself sets it.

A record write and a schema change or archive of the same table take turns: the write
waits for one in flight and is then judged against what it committed, so a record never
lands in a table archived a moment earlier.

Archiving a column, or the whole table, first asks every registered dependency
checker whether something the caller can both see and change still uses it. Saved
views (see [saved views](#saved-views)) and the workflows that read or write the table
register theirs in `app/services/virtual_tables/dependencies.py`, and so do table
triggers, which block whoever archives: a trigger filtering on a column that is gone
would come back broken.

A refusal lists each dependent in `SCHEMA_DEPENDENCY` with its
`kind`, `id` and `name`, and `name` is null for a trigger in a workflow the caller
cannot open. The console lists them in the dialog that asked, a workflow as a link to
it. Any other dependent is never named and never blocks the caller: its feature copes
with the change instead.

## Archiving and restoring a table { #archiving-a-table }

A table is never deleted; it is archived. An archived table keeps its records,
columns, views and history, and every read still answers. Every write is refused with
`TABLE_ARCHIVED`, whoever asks: no record is created, changed or deleted, and neither
its name nor its columns change. Its name is free for a new table, and it still counts
toward the organization's [table limit](#limits-and-retention).

In the console, a member who can edit the table finds **Archive table** in the
**More actions** menu on its page. The dialog says what archiving does before anything
changes. A published workflow that still reads or writes the table, and that the
caller may edit, refuses the archive with `SCHEMA_DEPENDENCY`, and the dialog lists it
as a link. Saved views and triggers block only a column archive.

An archived table's page says when it was archived. For a member who may edit the
table, the notice carries **Restore**, which brings it back under its name; anyone
else reads its records and is told who can restore it. The catalog lists live tables
until **Archived included** is chosen above it, and an archived table's card says it
is archived.

| Action | Route | Refused with |
|---|---|---|
| Archive | `POST /tables/{id}/archive` | `SCHEMA_DEPENDENCY` (409) while something uses the table. Archiving twice is not an error |
| Restore | `POST /tables/{id}/unarchive` | `BAD_REQUEST` (400) when the table is not archived; `ALREADY_EXISTS` (409) when a live table took its name meanwhile |

Both need the right to edit that table, by role or by a grant on it, and anyone else
gets a 404. `can_edit` is false on an archived table, so `TableRead.can_restore` says
whether this caller may restore it. Each is audited, as `table.archived` and
`table.unarchived`, and counts toward the table write rate limit. A name taken
meanwhile is changed on the live table first, because an archived one cannot be
renamed.

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

## Editing records in the console { #editing-in-the-console }

The catalog's cards say how many records and live columns each table has, who may
reach it and when it last changed. On a table's page, each header shows its column's
type by an icon, numbers sit right-aligned, and dates read as your locale writes
them. The record panel is titled by the record's first column and says when it was
added and last changed.

A member who can edit the table adds, changes and deletes records from its page.
**Add record** asks for a value per live column, typed as the column is. A column that
is required and has no default is marked `*` and must be filled before the record is
written; any other column left empty takes its default. Clicking a cell edits it in
place: Enter or clicking away saves it, Escape leaves it unchanged, and a yes/no that
cannot be empty flips with one click. The arrow keys move between cells, and the
expand button at the end of a row opens the whole record.

The line under the grid adds records as you type: what you type goes into the first
text column, and Enter creates the record and leaves the line ready for the next. A
table with another required column opens **Add record** with the typed value filled
in instead, so nothing is written until every required value is there.

Each edit is one `PATCH` against the revision on screen, so an edit that loses to a
newer change is refused rather than written over it. The record then opens with the
refused value kept beside **Reload and reapply**. Ticking rows offers **Delete** for
all of them, each against its own revision: a record someone changed meanwhile is
kept, and the console says how many were. The record panel deletes one record the same
way.

A delete waits a few seconds with **Undo** in its notice before it is sent; the
records leave every view at once, and Undo brings them back untouched. A member who can only view the table sees the same grid read-only, and clicking a
row opens the record.

For a member who can edit the table, a column's header opens a menu. **Sort ascending**
and **Sort descending** order the grid by it, and **Hide in this view** takes it off the
screen until the hidden-columns button shows it again; **Save view** keeps both.
**Rename** and **Archive column** change the table for everyone, each as the same new
schema version the Columns dialog would write, and an archive something still uses is
refused, with the workflows, views and triggers listed in the dialog. The **+** after the last column adds one, optional to begin
with. A column's type changes in **Columns**, to the types its values convert to.

In **Columns**, **Required** makes a column need a
value, and an archived column moves under **Archived columns**, where **Restore** brings
it back with its values.

### Import and export { #import-and-export }

**Export**, under **…** beside **Share**, saves what the page shows as a CSV file: the records the filters and search
match, in the grid's order, under its visible columns. `POST
/tables/{id}/records/export` does the same for a caller, with the same filters,
search, sort and a list of `columns`. An option is written as its label, several as
`a; b`, and a text cell a spreadsheet would read as a formula starts with `'`. More
than 100,000 matching records are refused with `EXPORT_TOO_LARGE` (413).

**Import**, in the same menu, reads a CSV file, comma or semicolon separated, whose first row names its
columns. Each file column is matched to the table column of the same name, or to
**External id**, and can be pointed elsewhere or skipped. A value that does not read
as its column's type fails its row before anything is sent. The rest go 200 at a time
to `POST /tables/{id}/records/batch`, which writes each record on its own and lists
the ones it refused with their codes, and the console lists every failed row with its
line. Each record added starts the table's triggers, as any other would.

With **External id** mapped, **Update records already here** imports a file again to
bring the table up to date: a row whose external id the table holds changes that
record's cells it names, rather than being refused as taken (`update_existing` on the
batch), and the import counts what it added and what it updated.

**New table** starts with a **Name** column. It can start from a file instead: **Start
from a CSV file** turns
the header into columns and gives each the narrowest type all its values read as -
integer, number, yes/no, date, an ISO date and time, an email address or a link - and otherwise text, or long
text once a value has a line break or runs past 1,000 characters. The name comes from
the file, and both can be changed before creating, which costs less than a type change later.
Once the table exists the import opens with every column already mapped, and the
table opens after it.

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

`search` is text a record must contain, ignoring case, in any live text or long text
column or in the label of a select option it holds. It combines with the filters, and
a blank one searches nothing. A saved view keeps it beside its filters. In the console
the search box sends it, and **Filter** writes the conditions: a column, an operator its
type supports and a value. Each complete condition narrows the records at once, and
**Save view** keeps the conditions, the search and the sort in the view on screen.

The order is total. The requested sort (`created_at`, `updated_at` or a sortable
column) is followed by the record id, so a page never repeats or skips a record in
an unchanged table. Records with no value in the sorted column come last in either
direction. A `multi_select` column cannot be sorted. `updated_at` is set when a record is
created and moves on each edit, so records nobody has edited sort by their creation time.

A listing has no `total`, because counting a filtered table is not cheap: `has_more`
says whether another page follows. `POST /tables/{id}/records/count` answers that
question separately, for a query's filters and search, and counts no further than
100,000; `capped` says more match. The console shows that count beside the view tabs,
and its grid loads a hundred records at a time as it scrolls, drawing only the rows in
view. Past the 10,000 records a query may skip, it asks for a filter or a search.

## Saved views { #saved-views }

A **view** is a kept filter, sort and grouping over one table's records - what the
console's table/kanban/list screens save so a person does not rebuild the same
board every visit. It is a sub-resource of the table, not a shareable resource of
its own: a view has no owner-and-grants of its own kind, and `shared` means only
"visible to anyone who already holds `tables:view` on the parent table" - it never
widens access beyond what the table itself allows.

In the console, the screen with no view picked reads **All records**, and **+** beside
it saves what the screen shows as a new view. A kanban board with no view asks which
single-select column makes its lanes and draws at once; saved as a view, it keeps
that grouping. A card lists up to four of the screen's columns under its title,
leaving out empty ones. A table with no single-select column offers **Add a column** instead.

The view's owner switches it between **Private** and **Shared** with the button beside
**Rename**. Someone who manages another member's view, such as an admin, does not
get the switch: sharing a person's own filters is theirs to choose.

`GET/POST /tables/{id}/views` and `GET/PATCH/DELETE /tables/{id}/views/{view_id}`
list, create, read, update and delete them. The list is paged with `skip` and
`limit` (at most 100), the caller's own views first, then the shared ones, each by
name; `total` counts them all. `config` is `{filters, search, sort,
visible_columns, group_by}` - a `RecordQuery` plus the two fields only the
console's own rendering needs: `visible_columns` (`null` means every live column)
and `group_by` (a live `single_select` column, for a kanban board's lanes).

| Field | Meaning |
|---|---|
| `kind` | `table`, `kanban` or `list` - a view is saved *for* one kind |
| `visibility` | `private` (only its owner) or `shared` (anyone who can see the table) |
| `can_manage` | Whether this caller may rename, reconfigure or reshare it |
| `can_delete` | Whether this caller may delete it |

Listing, reading and deleting resolve against the table (`tables:view`); creating
or changing one needs `tables:edit` on the table, so an owner whose edit access was
taken away can still delete their views but no longer reshape or share them.

Changing or deleting a view is narrower still: only its owner, or a caller whose
`tables:edit` [scope](permissions.md) is `ALL` - not "anyone who can edit the
table" - so a shared editor cannot silently repoint another member's saved filter. Refused
the same way every other per-resource write here is: `NOT_FOUND` (404), never a 403
that would disclose a view's existence to a caller it refuses. `can_manage` and
`can_delete` say which of the two this caller may do.

Archiving a column is refused with `SCHEMA_DEPENDENCY`, naming the view, when a
view the caller can both see and change filters, sorts or groups by it: one of their
own, or - for a caller whose `tables:edit` scope is `ALL` - a shared one. Any other
view does not block the archive and is not named, because the caller could not clear
it; that includes every other member's private view, which is not disclosed even to
an `ALL`-scope caller. Showing a column in `visible_columns` does not block either.

Whatever a view still names of a column that is no longer live is dropped when the
view is read: a filter on it goes, a sort by it falls back to `created_at`, a
grouping by it is cleared, and it leaves `visible_columns` - a view left showing none
of its chosen columns shows every live one. The stored config is not rewritten.

### Pages and views { #views-for-pages }

A published [artifact](artifacts.md#live-data) does not read through a view. Its
bindings are **page queries**: a table, filters, a sort, a limit and the fields the
page reads, which the platform stores on the version of the page when it is published.
A binding may start from a saved view - an agent finds one with `list_views`, which
returns each view's id, its columns and whether it is shared, for tables it may read -
but the view's filters and sort are **copied** into the page then. Editing, sharing,
renaming or deleting the view afterwards changes nothing on the page, and a view's
`visible_columns` and `group_by` are ignored: the binding's `fields` decide the columns.

A view with a free-text search cannot be bound, because a search matches every
live text column and so would widen as columns are added; the publish is refused and names
the view. So is a view whose filter names a column that is gone.

Who may read the page's records is not decided by the view. They are read with the access
of the page's owner, once the owner has consented, and a table's access is all or nothing:
`read` gives every row and every live column. A page query is how a table's rows reach people
who could not open it, and the owner is asked first. See
[Artifacts](artifacts.md#consent-the-owner-decides-who-reads-the-data).

A page query records the `revision` of every column it reaches: its fields, its filter
and sort columns, a formula's inputs, a lookup's or rollup's link and target, and the column
each linked table labels its records by. A binding goes `unavailable` (`source_changed`) when
one of those moved on or was archived, or when a table it reaches was archived, and the
other bindings keep working. Nothing stops a table change for it: a page is not a
dependency that blocks an archive. `share_view` no longer exists; there is no private view
to share for a page.

## Triggers { #triggers }

A [workflow](workflows.md#when-a-table-record-is-added) whose trigger node is **Table
record** runs once it is published for what happens to its table's records - added,
changed or deleted, whichever its `events` name; added only by default - however it
happens: in the console, over the API, by an agent's table tool or by another
workflow's table step. An upsert that creates a record is an addition, and one that
updates it a change. Publishing it needs read access to the table and permission to run
the workflow, because it runs as the member who published it, never as the record's
author. That member's access is checked again on every event.

The trigger runs the version that switched it on, and the next publish moves it to the
new version. Its filters use the operators of [Listing and
filtering](#listing-and-filtering) and are judged on the record as it was added or
changed to, or as it was before it was deleted. A change starts it only when one of
the columns chosen for the table changed, when columns are chosen.

It hands the run the record: `record_id`, `event`, `values` by column id, the same
values as `fields` by label and `author_id`, and for a change or a deletion `before`
and the `changed` columns by label. **Triggers** on the table's page lists the
workflows that start from it, pauses and resumes each, and opens its history.

A trigger starts only for records added while it is on. Switching it on - a publish,
or resuming it - takes the table's schema lock, the one every record write waits on, so no record
committed before that moment ever starts it, and nothing added while it was off is
replayed. The `workflow-table-triggers` job, which runs every ten seconds, reads each new
record's outbox event, so a trigger starts within about ten seconds. It decides once per trigger and records the decision; a second pass, or a
second worker, finds that decision and starts nothing.

**History** lists each decision, newest first, without the record's values:

| Shown as | Why |
|---|---|
| Started a run | Every filter held; the run is linked |
| Skipped | The record did not match, or was added before the trigger was on |
| Blocked | It would have started itself again, the chain went more than five triggers deep or past 50 runs, or the run was refused by the admission quota |
| Could not start | The member it runs as can no longer read the table or run the workflow, or the record's creation could not be read |

A workflow that writes into a table can start that table's triggers, and so on
through other tables. Each run carries the chain it belongs to, and a trigger the
chain has already passed through is blocked rather than started again, which is what
stops two workflows adding records to each other's tables from looping. A column a
trigger filters on cannot be archived until its workflow's trigger stops filtering on it
and is published, even while the trigger is paused, and a table a published workflow
starts from cannot be archived until that workflow starts another way.

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

The outbox row is the hand-off to whatever reacts to a new record: today, the
[triggers](#triggers). Their heartbeat claims undelivered rows in its own session, judges
each against the table's triggers and marks it dispatched in the same transaction. An
undispatched row is removed only by its own much longer retention window (below), a
dead-letter cutoff for a worker that has been down that long rather than a claim the
event was ever collected.

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
| Undispatched outbox rows | Never dispatched and 30 days old: the trigger heartbeat has not run for that long, and no trigger will start for those records | `TABLES_OUTBOX_UNDISPATCHED_RETENTION_DAYS` |
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

Whether a specific caller may edit a specific table is also on the wire directly:
`TableSummary.can_edit` and `TableRead.can_edit` are resolved server-side (role
scope or an explicit grant) and shipped on every read, the same way `Agent.can_run`
is - so a catalog row or a detail page never has to guess whether its edit controls
would be refused. A saved view's own `can_manage` and `can_delete` are the same
idea, one level down (see [Saved views](#saved-views)).

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
| `BAD_REQUEST` | 400 | A restore named a table that is not archived |
| `ALREADY_EXISTS` | 409 | The table name, a view name or the external id is taken |
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

## Adding a column type { #adding-a-column-type }

A column type is one entry in `COLUMN_TYPES` in
`backend/app/services/virtual_tables/types.py`, with its name in `ColumnTypeName` in
`backend/app/schemas/virtual_table.py`. The entry names how the cell is read out of
the record for comparing and sorting (a `SqlKind`), which filter operators it takes,
whether it sorts, and the validator every write and every filter operand goes
through. The validator returns the value as it is stored or raises `CellProblem`
with a message for whoever wrote it. Every surface calls the same service, so the
console, the API, agents and workflows all accept the new type at once, and a
[trigger](#triggers) filters on it with the same rules.

The console needs the type in `ColumnTypeName` in `frontend/src/types/tables.ts`,
an editor in `record-cell-editor.tsx`, a choice in the schema and create-table
dialogs, and its label in the three message catalogs. Tests belong in
`backend/tests/test_virtual_table_types.py` for the validator, and in an integration
test that writes, filters and sorts a record of the new type.

## Not built yet { #not-built-yet }

- Resuming a run that stopped as **Needs attention** from the console. It can be
  cancelled, and a new run started.
