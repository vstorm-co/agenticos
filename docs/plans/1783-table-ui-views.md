# #1783 — Virtual Tables: UI editing and saved table, kanban and list views

Design for the console half of Virtual Tables: create/configure a table, edit
its records, and browse them through saved table/kanban/list views — Notion-style,
over the real `/api/v1/tables` service #1782 built
(`docs/virtual-tables.md`, `backend/app/schemas/virtual_table.py`,
`backend/app/api/routes/v1/virtual_tables.py`, all on
`feat/1782-virtual-tables-storage`). Depends only on #1782; retarget from that
branch to `main` once PR #1812 merges, per `56-workflows-tables-implementation-plan.md`.
`virtual-tables-demo.html` is illustrative only — no production styling or
structure is taken from it.

## 1. Scope

In: table creation, column (schema) editing, record CRUD, table/kanban/list
saved views, search/filter/sort, pagination, sharing, conflict handling,
onboarding and dashboard integration. Out: agent tools and typed workflow
nodes over tables (#1784), triggers on record creation (#1785) — this issue
is the human-facing surface only.

## 2. Routes and pages

New route tree under `frontend/src/app/[locale]/(dashboard)/tables/`:

- `page.tsx` — the table catalog. A `DataTable`/`ListCard` list of
  `TableSummary` rows (name, visibility badge, schema version, `created_at`),
  search via `ListControls`, `PaginationBar`, and a "New table" button gated
  on `Perm.TABLES_CREATE`. Mirrors `agents/page.tsx`'s catalog shape.
  **`TableSummary` needs `updated_at` added** for a "most recently changed"
  sort or display (round 1 of this review: the real schema on #1782's
  branch has `updated_at` only on `TableRead`, not `TableSummary` — a small
  additive field, not a behavior change, since every list-serving query
  already selects the row).
- `[id]/page.tsx` — one table. Header (name, description, visibility badge,
  a "Share" button opening `SharingPanel`), a "Columns" button opening
  `schema-editor-dialog.tsx`, a view-kind switcher (`Tabs`: Table / Kanban /
  List, `?view=table|kanban|list` via `useUrlState`, the same pattern
  `rag/[id]/page.tsx` uses for its own tabs), and a saved-view `Select`
  scoped to the active kind (a view is saved *for* one kind, since a kanban
  grouping has no table-view equivalent).

No `tables/[id]/[view]` segment: the view id is a query param
(`?view=kanban&viewId=<uuid>`), not a path segment, so switching views never
loses the record-detail sheet or scroll position via a full navigation.

## 3. Data layer

- `frontend/src/lib/tables-api.ts` — typed client on `api-client.ts`:
  `listTables`, `createTable`, `getTable`, `updateSchema`, `listRecords`,
  `queryRecords`, `createRecord`, `updateRecord`, `deleteRecord`, mapping 1:1
  onto the real routes. `frontend/src/lib/table-views-api.ts` does the same
  for the new `table_views` resource (§4).
- `query-keys.ts`: `qk.tables.list(query)`, `qk.tables.detail(id)`,
  `qk.tables.records(id, query)` (the query object as the key, matching
  `mcpServers.listPage`'s convention so two filters are two cache entries),
  `qk.tables.views(id)`.
- Hooks: `use-tables.ts`, `use-table-records.ts` (wraps `queryRecords`),
  `use-table-views.ts`, and `use-record-mutation.ts` — the one shared
  create/update/delete mutation every cell editor and the kanban drag use,
  so conflict handling (§7) lives in one place.
- `frontend/src/stores/table-view-store.ts` — ephemeral only: the
  in-progress filter/sort/column-visibility draft before it is saved, and
  pending conflict banners. Nothing here is server state.

## 4. The saved-view model: a new `table_views` row, not client storage

A view persists: `name`, `kind` (`table`/`kanban`/`list`), `visibility`
(`private`/`shared`), and a `config` JSONB blob of
`{filters: RecordFilter[], sort: RecordSort, visible_columns: UUID[] | null,
group_by: UUID | null}` — reusing `RecordFilter`/`RecordSort` from
`virtual_table.py` directly, so a saved view's config is literally a
`RecordQuery` plus the two console-only fields (`visible_columns`,
`group_by`). `visible_columns: null` means "all live columns", matching how
the table itself treats an absent column list.

**Decision: a backend model, not `localStorage`.** A "shared" view must be
visible to every teammate who can see the table — a filtered kanban board a
lead sets up for the team is the primary use case the issue names — and
`localStorage` cannot cross accounts or devices. A view row carries
`table_id` and `organization_id` (denormalized, the same reasoning
`docs/virtual-tables.md#who-can-do-what` gives for records), so it never
outlives or leaks across a table it no longer belongs to.

New model `backend/app/db/models/table_view.py`:

```python
class TableView(Base, TimestampMixin):
    __tablename__ = "table_views"
    id: Mapped[UUID]
    table_id: Mapped[UUID]          # FK virtual_tables.id, ondelete=CASCADE
    organization_id: Mapped[UUID]   # FK organizations.id
    owner_user_id: Mapped[UUID]     # FK users.id, ondelete=CASCADE
    name: Mapped[str]
    kind: Mapped[str]               # "table" | "kanban" | "list"
    visibility: Mapped[str]         # "private" | "shared"
    config: Mapped[dict[str, Any]]  # JSONB
    UniqueConstraint(table_id, owner_user_id, name)
```

Deliberately **not** a `ResourceType`/grant subject like `TABLE` itself: the
issue is explicit that "private and shared views never grant access beyond
the table", so a view has no sharing of its own — `shared` only means
"visible to anyone who already has `tables:view` on the parent table".
`VirtualTableService` (or a sibling `TableViewService` in the same
`app/services/virtual_tables/` package, a thick domain per `architecture.md`)
resolves that with the existing `resolve_access(ctx, table, Perm.TABLES_VIEW,
resource_type=TABLE)` before touching the view repository — a 404 on the
table is a 404 on every view under it, same as records today. Editing or
deleting a view is restricted to its `owner_user_id`, or a caller whose
`TABLES_EDIT` scope is `ALL` — not to "anyone who can edit the table", so a
shared editor cannot silently repoint a lead's saved filter.

Routes, mounted at `/api/v1/tables/{table_id}/views`, no collection-level
`require(...)` gate (access is resolved per-table, not per-role, matching the
record routes): `GET` (mine + shared), `POST`, `GET/{view_id}`,
`PATCH/{view_id}`, `DELETE/{view_id}`. Schemas (`backend/app/schemas/table_view.py`):
`TableViewCreate`, `TableViewUpdate`, `TableViewRead`, `TableViewList`,
importing `RecordFilter`/`RecordSort` rather than redefining them. Needs an
`alembic-migration` on top of #1782's branch — check `alembic heads` at
implementation time rather than assuming a number, per `56-shared-contracts.md`.

**Registers a `DependencyChecker`** (#1793 found #1782's hook in
`services/virtual_tables/dependencies.py` shipped and never registered
against by anything — this is one of the three registrants its own
docstring names). At `table_views` service import time:
`register_dependency_checker(table_view_dependents)`, where the checker
looks up every `table_views` row whose `config` names a `column_id` in the
archived set (`visible_columns`, the kanban `group_by` column, or a filter's
`column_id`) and returns `Dependent(kind="table_view", id=view.id)` for
each — so archiving a column a saved view depends on is refused, naming the
view, rather than leaving that view silently broken.

## 5. Rendering each view type

All three pull the same `RecordRead[]` through `POST /tables/{id}/records/query`
built from the active view's `config` (or the in-progress draft before a
save) — there is exactly one read path; the views differ only in layout.

- **Table** (`table-grid-view.tsx`): `components/ui/data-table.tsx`, columns
  built from `table.columns` filtered by `visible_columns`, `sortable` wired
  to server-side `RecordSort` (`onSort`, not client sort — a `multi_select`
  column is not sortable per the service, so its `Column` omits `sortable`).
  `PaginationBar` drives `skip`/`limit`; `has_more` decides whether "next" is
  enabled (there is no `total`). A cell click opens `record-detail-sheet.tsx`
  (a `Sheet`) rather than editing in place — inline editing collides with
  sortable headers and keyboard row navigation, and one sheet per record keeps
  the editing surface identical across all three view types.
- **Kanban** (`table-kanban-view.tsx`): requires `group_by` to name a live
  `single_select` column (the view-config UI refuses to save a kanban view
  without one). Lanes are that column's non-archived options plus one "No
  value" lane for `is_null`. Each lane runs its own `records/query` with
  `filters: [...view.filters, {column_id: group_by, op: "eq"/"is_null",
  value: option.id}]` and its own `skip`/`limit`/"load more" — a single
  unfiltered fetch can't populate every lane under the service's 100-row page
  cap. Dragging a card calls the update mutation with `values:
  {[group_by]: targetOptionId}, expected_revision: record.revision`. No drag
  library exists in `frontend/package.json` today; reuse the hand-rolled
  pointer-event drag already written for
  `components/dashboard/dashboard-editor.tsx`, factored into
  `use-kanban-drag.ts`, rather than adding `@dnd-kit`.
- **List** (`table-list-view.tsx`): one row per record — a title line (the
  first visible column) plus up to three secondary values, on
  `components/ui/list-card.tsx`. Same query, same pagination, no headers — the
  simpler surface the issue asks for, useful where the grid renders badly
  (`long_text`-heavy tables).

## 6. Record editing by column type

`components/tables/record-cell-editor.tsx` dispatches on `ColumnDef.type`,
reusing `schema-form.tsx`'s shape (controlled `value`/`onChange`, `disabled`,
per-field `error`, "`undefined` = untouched, `null` = explicitly cleared")
but as a single-field control, invocable either inline (grid cell) or N-times
inside `record-detail-sheet.tsx`'s full-row form — table cells need per-cell
editing, not one form that opens every field at once the way a capability's
config does.

| Column type | Control | Note |
|---|---|---|
| `text` | `Input` | |
| `long_text` | `Textarea` | not the `MarkdownEditor` — cell text is stored verbatim, not rendered as prose |
| `number` | `Input type="number" step="any"` | |
| `integer` | `Input type="number" step="1"` | parsed and rejected above 2^53−1, same bound the service enforces |
| `boolean` | tri-state `Select` (`Not set` / `True` / `False`) when `nullable`, else `Switch` | extends `schema-form`: its `Switch` has no unset state, but a nullable boolean cell does |
| `date` | new `date-cell.tsx`, native `<input type="date">` | no existing single-date primitive (`date-range-picker.tsx` is ranges only) |
| `datetime` | new `datetime-cell.tsx`, `<input type="datetime-local">` | converts the browser's local wall-clock value to/from the column's UTC ISO 8601 on blur — the one control here with a real extension, not just a new type |
| `single_select` | `Select` over `column.options` | keyed on the option's stable `id`, not a JSON Schema `enum` value; a record holding an archived option's id still renders its (struck-through) label read-only |
| `multi_select` | new `multi-select-cell.tsx`, `Popover` + checkbox list + chip summary | no multi-select primitive exists yet; scoped to `components/tables/` rather than promoted to `components/ui/` until a second consumer needs it |

Where `schema-form.tsx` is not reused: its `enum`/`suggested`/`stringList`
kinds are JSON-Schema-specific and have no table-column equivalent, and its
masked/secret handling is irrelevant here — cells are never credentials.

## 7. Conflict handling — a stale `expected_revision`

Every record mutation (cell save, kanban drag, sheet save) goes through
`use-record-mutation.ts`, which always sends the `revision` the client last
read. On `409 REVISION_CONFLICT`, the acceptance criterion is explicit: the
UI must refuse the write **without losing the local edit**. Concretely:

- **Kanban drag**: the card stays rendered in the *target* lane (not
  reverted to its old lane) with a conflict badge and two actions: "Reload
  and reapply" (refetch the record, retry the same status change against the
  fresh `revision`) and "Discard" (drop the pending move, refetch, and let
  the record land wherever its current value places it). The dragged intent
  — "this should be in lane X" — is never silently thrown away; the user
  either confirms it against the new state or explicitly discards it.
- **Cell / sheet edit**: the input keeps the typed value (it does not snap
  back to the stale server value) with an inline error and the same two
  actions, scoped to that field.
- `REVISION_REQUIRED` (428) is not reachable from the console — every record
  the UI mutates was just read, so it always has a revision to send; only a
  raw upsert-by-external-id (agent/API territory, #1784) hits it.

## 8. Permissions

Page and create-button gating uses `usePermissions()` exactly as elsewhere:
the `/tables` nav entry and catalog page render only under `Perm.TABLES_VIEW`,
"New table" under `Perm.TABLES_CREATE`.

Per-table edit affordances (schema editor, record editing, kanban drag, view
save/delete) are **not** derived client-side from role scope alone. Today's
dominant pattern — a page-wide `canEdit = can(Perm.X_EDIT)` fanned out
unchanged to every card (`agents/page.tsx`, `skills/page.tsx`,
`context/page.tsx`) — is blind to a per-row grant: a Viewer holding an
explicit `edit` grant on one specific table would see no edit controls,
because `/me/permissions` only reports role scope. The codebase already has
the right answer to exactly this, precedented on `Agent.can_run` and
`Trigger.can_manage` (`frontend/src/types/agents.ts:328-335`,
`frontend/src/types/triggers.ts:34-42`): a boolean resolved **server-side**
per row, folding in scope and grant, shipped on the read model.
`TableSummary`/`TableRead` should carry the same — `can_edit: bool`, set in
`VirtualTableService.list_tables`/`describe_table` from
`resolve_access(ctx, table, Perm.TABLES_EDIT, resource_type=TABLE)` — rather
than reintroducing the role-only gap `can_run` was added to close elsewhere.
The frontend reads `table.can_edit` directly, the way `agents/[id]/page.tsx`
reads `agent.can_run`, and feeds it to `<SharingPanel resourceType="table"
resourceId={id} canManage={table.can_edit} />`.

Sharing is a small, concrete gap this issue closes on the frontend side: the
backend already mounts `table_sharing_router` at `/tables/{id}/sharing`
(`backend/app/api/routes/v1/sharing.py`), but the frontend never wired it up
— `SharingResourceType` (`frontend/src/types/sharing.ts:17`) and
`SHARING_ROOT` (`frontend/src/hooks/use-sharing.ts`) both need a `table`
entry. Likewise `Perm.TABLES_VIEW`/`TABLES_EDIT`/`TABLES_CREATE` do not exist
yet in `frontend/src/types/permissions.ts` and need adding to mirror
`backend/app/core/permissions.py`.

Keyboard navigation (an explicit AC): the grid already gets native `<table>`
semantics through `DataTable`; the kanban board additionally needs a
non-pointer move path — each card gets a "Move to…" `DropdownMenu` of lanes
as the accessible equivalent of the drag.

## 9. Onboarding and dashboard integration

- `src/lib/onboarding/tour.ts`: a stop on the new `/tables` nav entry
  (`data-tour="nav-tables"`), gated on `Perm.TABLES_VIEW`.
- `src/lib/onboarding/flows.ts`: a `CreationFlow` for "table" (name → columns
  → visibility), registered in `flowForPage` for `/tables`, mirroring the
  agent/skill creation flows.
- No `detail-targets.ts` resolver needed — a table's detail view already has
  its own route (`/tables/[id]`).
- Dashboard widget `tables` in `src/lib/dashboard/registry.ts`
  (`components/dashboard/widgets/tables-widget.tsx`), gated on
  `Perm.TABLES_VIEW`: caller's tables, most-recently-updated first, each
  linking to its default view. Placed in the **Workspace** band per
  `docs/console.md`. Mirror the id in `WIDGET_IDS`
  (`backend/app/schemas/dashboard_layout.py`) and add
  `dashboard.widgets.tables.*` copy in `en`/`pl`/`de`, per
  `.claude/rules/frontend.md`'s widget checklist.

## 10. Test plan → acceptance criteria

| AC | Coverage |
|---|---|
| Consistent across every matching view, including agent/API/workflow writes | E2E: create a record in the table view, assert it appears in kanban and list; seed a second record via a raw API call (standing in for an agent/API writer, since #1784's tools don't exist yet) and assert a refetch surfaces it identically in all three |
| Views survive reload, column renames and permitted config changes | Component: `use-table-views.test.tsx` round-trips create/list/update. E2E: save a filtered kanban view, reload, assert `viewId` restores its filters/sort/grouping; rename the grouping column and assert the view still resolves (same column id) |
| Unauthorized reads/writes and stale drag-and-drop refused without losing the local edit | Integration: `table-kanban-view.integration.test.tsx` mocks a 409 on drag, asserts the card stays in the target lane with the conflict banner and retry. E2E: two contexts, one PATCHes a record raising its revision while the other's drag hits the conflict path. Backend: tenant-isolation and owner-vs-shared-editor tests in `backend/tests/services/test_table_views.py` |
| Keyboard navigation and documented permissions | Integration: `record-detail-sheet.integration.test.tsx` completes an edit tab-to-tab, no pointer events. E2E: keyboard-only journey, catalog → table → "Move to…" kanban reassignment. `tables-page.integration.test.tsx` asserts create/edit controls are absent, not merely disabled, without `TABLES_CREATE`/`can_edit` |
