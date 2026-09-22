# Design: #1784 — Virtual Tables: agent tools and typed workflow nodes

Depends on #1782 (`feat/1782-virtual-tables-storage`, PR #1812, built,
unmerged) and #1786 (design only — see [shared contracts](56-shared-contracts.md)).
Written against #1782's branch and against the `NodeDefinition` shape
`56-shared-contracts.md` resolves, since #1786 has no branch yet. Retarget once
either merges.

## Problem

`VirtualTableService` (`app/services/virtual_tables/facade.py`) is already the
one place table logic lives: "the console, agent tools, workflow nodes and the
public API all call this class with an `AuthContext`; none of them reaches the
repository." This issue adds the tool and node layers on top of it — no new
validation, conflict or audit logic, only typed wrapping and access control.

Two separate authorities matter: `Perm.TABLES_CREATE` (org-wide, unrelated to
any one table) decides who may create a table at all; a narrower,
per-capability config decides *which* tables an agent or workflow may touch
and with which operations. The issue requires the second to be resolved from
data the model cannot rewrite, and the two never to be conflated.

## Capability: `app/agents/capabilities/virtual_tables/`

```
virtual_tables/
  __init__.py     @register(...) only
  _capability.py  VirtualTables(AbstractCapability), VirtualTablesConfig
  _toolset.py     the eleven tools
  _access.py      allow-list check + service call, shared by every tool
  README.md
```

Thick shape (own resolution logic), following `knowledge/` for the
config-schema/resource pattern and `sandbox/` for per-tool `side_effecting`.

### Tools

Eleven tools, one-to-one with service methods, using `app.schemas.virtual_table`
types directly (`CellValue`, `RecordQuery`'s filter/sort shape) rather than a
re-derived copy:

| Tool | Service call | `side_effecting` |
|---|---|---|
| `table.list` | `list_tables` | `False` |
| `table.exists` | `describe_table` (catch `NotFoundError`) | `False` |
| `table.describe` | `describe_table` | `False` |
| `table.create` | `create_table` | `True`, gated separately |
| `table.records.exists` | `record_exists` | `False` |
| `table.records.list` | `list_records` | `False` |
| `table.records.get` | `get_record`/`get_record_by_external_id` | `False` |
| `table.records.create` | `create_record` | `True` |
| `table.records.upsert` | `upsert_record` | `True` |
| `table.records.update` | `update_record` | `True` |
| `table.records.delete` | `delete_record` | `True` |

A domain exception's `code`/`message`/`details` (`REVISION_CONFLICT`,
`TABLE_ARCHIVED`, `INVALID_RECORD`, ...) is translated into tool output text
once, in one helper — a refusal the model can act on ("read it again and
retry"), never raised past it. Docstrings carry `Returns:`; a malformed call
uses `steer()`, per `agent-capability`.

### `table.create` is its own tool, its own gate

Per the issue ("do not hide administrative creation in record CRUD"): a
separate typed input (name, description, visibility, `ColumnInput` list),
offered only when the binding's config sets `allow_create: true` (absent from
the toolset otherwise, so an agent without the switch cannot even see it),
still checked against `Perm.TABLES_CREATE` by the service itself at call time
(`tables.py`: `if not ctx.has(Perm.TABLES_CREATE): raise
AuthorizationError`) — `allow_create` narrows what the binding permits, the
live membership permission still decides whether the call runs. On success it
returns the new table's id, schema version and a column-label-to-id mapping,
so a later `table.records.create` in the same run can address the new columns
without guessing a UUID (the "template-field-key to column-ID mapping" the
consistency review names).

**That promise needs the allow-list to grow mid-run, not just the pinned
map to exist** (round 3 of this review: `ctx.deps.virtual_tables` is built
once at run-build time from the frozen `TableGrant` config, before the run
starts — a table `table.create` makes *during* the run can never be a key
of a map frozen before it existed, so the immediately-following
`table.records.create` this tool's own success case promises would always
fail the allow-list check first, never reaching the service). On a
successful `table.create`, the handler inserts `{new_table_id:
frozenset(TableOperation)}` — every operation, since the creating
principal already holds `TABLES_CREATE` and is the new table's owner —
into the *same* `ctx.deps.virtual_tables` dict object the allow-list check
reads, a server-derived addition keyed on the id `create_table` itself
returned, never on anything the model supplies. The dict is mutated once,
in place, for the rest of this run only; it is not written back to the
binding's stored config, so the next run starts from the config's frozen
grants again, `table.create` or not.

It is idempotent via a run/tool-call-derived
`operation_key` (see below), which requires extending `create_table` to
accept one and reuse `run_once` from `receipts.py` — new service-layer
surface this issue adds, not #1782's.

### `config_schema`: which tables, which operations, enforced twice

```python
class TableOperation(StrEnum):
    READ = "read"
    CREATE_RECORD = "create_record"
    UPDATE_RECORD = "update_record"   # covers update and upsert-as-update
    DELETE_RECORD = "delete_record"

class TableGrant(BaseModel):
    table_id: UUID
    operations: frozenset[TableOperation] = frozenset({TableOperation.READ})

class VirtualTablesConfig(BaseModel):
    tables: list[TableGrant] = Field(default_factory=list, max_length=50)
    allow_create: bool = False
```

The Builder's table picker writes `TableGrant` rows into the binding's
`config`, the same way `knowledge`'s collection picker writes into the spec.

**Resolved once, at run-build time, never inside a tool.**
`AgentRunnerService._run` already resolves `resources["kb_collection_names"]`
this way before `build_agent` runs; this capability adds
`resources["virtual_tables"]`, built by walking each `TableGrant` through
`resolve_access(db, ctx, table, perm, resource_type=TABLE)` — the *publishing*
principal's access, not the model's — using `TABLES_VIEW` for `read` and
`TABLES_EDIT` for the write operations. A grant naming a table the principal
can no longer reach is dropped silently, matching how `knowledge` drops an
unbound collection rather than erroring. The result,
`dict[UUID, frozenset[TableOperation]]`, is the pinned allow-list for this run.
`_capability.py` returns `None` (contributes nothing) when it is empty and
`allow_create` is false.

**Enforcement at call time is two checks, both required:**

1. **Allow-list check**, against `ctx.deps.virtual_tables` — reached through
   `AgentDeps`, never through tool-call arguments. A `table_id` the model
   supplies that is not a key of the pinned map, or whose requested operation
   is not in its set, is refused before the service runs. This is
   `AgentDeps`'s own boundary made concrete for tables: "a tool's parameters
   are model-controlled and therefore untrusted, while its deps are resolved
   server-side."
2. **The service's own `resolve_access` check**, unconditionally, on every
   call, because access can be revoked mid-run and the pinned map is only a
   run-start snapshot that narrows, never grants. This is the issue's
   "revalidate access at execution time" requirement.

**`run_auth` cannot stay the immutable copy the field description above
implies** (GitHub's automated review caught this: `resolve_access`'s role
check reads `AuthContext.role` off the object it's given — "no query in
the common case," per its own docstring — so calling it again with the
*same* frozen `run_auth` re-runs the check but not the lookup; only the
explicit-grant fallback queries fresh. A role narrowed or a membership
removed mid-run, during a `waiting_approval` pause that can last hours,
would still pass). Each tool call rebuilds the role half of `run_auth`
fresh from current `OrganizationMember` state — the same query
`get_auth_context` runs per request — inside the same `get_db_context()`
session already open for the call, before invoking `resolve_access`; only
`organization_id`/`user_id` stay fixed for the run's life. This is one
extra indexed lookup per table call, not a new mechanism.

### Reaching the service: two new `AgentDeps` fields

No existing capability writes through a transactional, `AsyncSession`-backed
service mid-run, so `AgentDeps` gains a `run_auth: AuthContext | None`
field — but **not** the run's own `db` session (round 1 of this review
rejected an earlier draft that shared it). `AgentRunnerService._run`
explicitly commits *before* the model call precisely so no connection is
held open across it (`CLAUDE.md`'s hard boundary), and
`AgentDeps.clone_for_subagent`'s own docstring already warns the shared
session is not concurrency-safe. Handing that same session to a tool would
both reopen the transaction the boundary exists to keep closed during a
model call and hand an unsafe-for-concurrent-use object to code that can run
concurrently with other tool calls in the same turn.

Each tool call instead opens its own short-lived session via
`get_db_context()` (the pattern `app/services/virtual_tables/quotas.py`
already uses for an out-of-request write), used only for the duration of
that one tool body and closed before returning — a table write is its own
small transaction, not a participant in the run's. `run_auth` is an
immutable copy of the run's own `AuthContext` for the principal the run
executes as (the publisher), following the same rule
`organization_id`/`user_id` already do on `AgentDeps`; `clone_for_subagent`
passes it through unchanged, since a delegate acts as the same principal.
`_access.py` wraps the two checks above into one helper every tool body
calls.

### Approval

Reuses `ApprovalGate` unchanged. `_capability.py` marks the five write tools
`side_effecting=True` via the per-tool `CapabilityToolInfo` override (the
capability both reads and writes, so the whole-capability flag would gate
`table.list` too). The gate needs no table-specific code: it already keys on
stable tool id, refuses to run unattended with no approval channel, and
replays the *approved* arguments rather than a retried call — which is what
stops a `table_id` or a cell value from being widened between the approval
ask and its replay.

## Workflow-node half

Three `NodeDefinition`s, registered through `app/workflows/_registry.py`'s
`register()` per `56-shared-contracts.md`:

| `id` | Wraps | `kind` | `effect_kind` |
|---|---|---|---|
| `table.record.create` | `create_record` | `action` | `write` |
| `table.record.upsert` | `upsert_record` | `action` | `write` |
| `table.record.query` | `list_records` | `action` | `read` |

Not all eleven tools get node twins: `table.describe`/`.exists` have no
graph-composition role a `logic.if` node doesn't already cover, and
`.update`/`.delete` nodes are deferred to a follow-up once #1787's editor and
#1789's core nodes exist to shape a delete-confirmation step — recorded here,
not silently dropped.

Each `config_schema` names one table via `TableIORef`; `input_schema`/
`output_schema` are generated per-table at bind time from its *current* live
columns, per `56-shared-contracts.md`'s `TableIORef` rule. A create/upsert
node's input port is cell values typed to the bound columns; its output is
the written `RecordRead`. The query node's output is a `RecordList` page, for
a `control.foreach` to walk.

**Permission/scope**, mirroring `56-shared-contracts.md` item 4's
`Perm.WORKFLOWS_*`: each node declares `scopes={"tables:read"}` or
`{"tables:read", "tables:write"}` — a new scope pair this issue adds to the
capability scope catalog (today: `knowledge:read`, `web:read`,
`code:execute`), checked at graph-validation/publish time the same way a
capability's scopes gate agent assembly. An org without `tables:write`
granted cannot publish a graph containing the two write nodes.

**Enforcement mirrors the tool, restated for a graph:**

1. **Table identity is pinned at publish**, in the stored `WorkflowVersion`'s
   `TableIORef` — never a value the running graph computes. There is no
   runtime input a node reads to pick its table, so nothing in the graph can
   redirect a write the way a model argument could try to.
2. **The node handler still calls `resolve_access` through the service on
   every run** (#1788 supplies `NodeDefinition.handler`; this issue's nodes
   must honor the contract), passing the workflow's own owning principal's
   `AuthContext`, resolved once per run start. A table archived or unshared
   after publish is refused at the node with the same `TABLE_ARCHIVED`/
   `NOT_FOUND` codes, surfaced as the run's `Failed` result.

Both surfaces resolve to the same three service methods with no
tool-specific or node-specific validation duplicated above the service
boundary — this is what makes "UI, tools, API adapters and nodes share
conflict, validation, audit and deduplication behavior" true by construction
rather than by convention.

**Registers a `DependencyChecker`** against #1782's unclaimed hook (#1793
flagged this hook as shipped and never registered against): at
`workflow_registry` import time, `register_dependency_checker
(table_binding_dependents)`, where the checker scans published
`WorkflowVersion.graph` for `TableIORef` bindings naming the table (and, for
a column-level archive, checks `column_ids`), returning
`Dependent(kind="workflow_version", id=version.id)` per match — one
published version is enough to refuse the archive, since a draft can still
be edited around it but a published graph cannot.

## `expected_revision`, upsert-by-`external_id`, idempotency

`VirtualTableService` already defines the shape: `expected_revision` on
update/delete/upsert-as-update, `operation_key` scoped to
`(organization, principal, operation)`, refusing a reused key against a
different body.

**Tool surface.** `expected_revision` is a plain model argument — the model
reads the record first, then passes back what it saw, same as the HTTP
client. `operation_key` is **never** a model argument: `_toolset.py` derives
it from `f"agent:{run_id}:{tool_call_id}"`, so a retried identical tool call
within a run replays the same key while two calls with identical arguments
(two genuinely distinct records) never collide.

**Node surface**, per the issue's own stated requirement ("a node run needs a
stable operation key derived from the run/node-instance id, not a random
one"): this must be the *same string* #1788 already mints as
`NodeAttempt.idempotency_key` — `f"{organization_id}:{workflow_run_id}:
{node_instance_id}:{scope_path}"` — not a second, differently-shaped key of
this issue's own invention (#1793 caught an earlier draft of this section
using `f"workflow:{run_id}:{node_instance_id}[:{iteration_key}]"`, which
diverged from #1788's format on the organization scoping and the loop-token
name; fixed here). A `table.record.upsert` node handler receives that string
from #1788's dispatcher and passes it straight through as `operation_key` —
it does not construct its own. `scope_path` (`[]` at top level, `[{loop_node_id,
index}, ...]` inside a `control.foreach`, per #1788's `NodeRun` model) is
what gives each loop iteration its own key, the same field #1788 and #1790
both already use for the same purpose.

`external_id` is caller-chosen on both surfaces, required explicitly, never
inferred from the run or node-instance id — that would collapse every run's
writes onto one record.

## Test plan, mapped to #1784's acceptance criteria

**1. Reads permitted tables, writes only enabled operations.** A
`{READ}`-only grant exposes reads and refuses a create at the allow-list
check (assert zero service calls); `{READ, CREATE_RECORD}` allows a create on
its table and refuses one on an unbound table id; `allow_create=False` means
`table.create` is absent from the built toolset; a grant naming a
now-unreachable table is dropped from the pinned map at build time.

**2. Every node registered and discoverable.** All three ids present in
`all_node_definitions()` with fixed `id`/`version`/`effect_kind`/
`retry_guarantee`/`scopes`; a `NodeCatalog`-serialization test confirms no
secret or raw config leaks; `config_schema` rejects a `TableIORef` naming a
nonexistent or archived table at bind time.

**3. Table creation and record creation have separate permissions.**
`table.create` without `Perm.TABLES_CREATE` is refused even with
`allow_create=true`; `table.records.create` succeeds with `TABLES_EDIT`
access and no `TABLES_CREATE` at all; no argument combination on
`table.records.create` reaches table-creation behavior.

**4. Shared conflict/validation/audit/deduplication behavior.** One fixture
builds a table via the HTTP route, then drives create → conflicting
concurrent update → upsert retry with a reused `operation_key` through the
HTTP route, an agent tool call and a node handler, asserting identical error
codes, identical `record_audit` entries and the same final row across all
three. A create→write→read→retry→denied-access→substituted-id sequence, run
once per surface, per the issue's consistency review.

Coverage: `app/agents/capabilities/virtual_tables/**` joins the platform
100% gate (`[tool.coverage.run] include` and the matching `[[tool.ty.overrides]]
include`, same order); the node package joins the same gate once #1786
establishes it for `app/workflows/**`.
