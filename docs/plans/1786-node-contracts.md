# #1786 — Workflow node contracts, registry and graph validation

Design for [issue #1786](https://github.com/vstorm-co/agenticos/issues/1786),
child of [#56](https://github.com/vstorm-co/agenticos/issues/56). This issue
*ships* the decisions recorded in
[56-shared-contracts.md](56-shared-contracts.md); read that page first, it is
not re-derived here. Below: concrete models, the eight validation algorithms,
the persistence and route shapes, the migration, the coverage-gate edits, a
commit order and a test plan against the four acceptance criteria. Branch
stacks on `feat/1782-virtual-tables-storage` (PR #1812) — `expected_revision`
and the real table/column model both live there, not on `main`.

## Module layout

```
backend/app/workflows/
  contracts/results.py, io.py, definition.py   # results, FileRef/TableIORef, NodeDefinition
  _registry.py                                  # register()/get()/all_node_definitions()/load_builtins()
  nodes/debug_echo/{__init__,_handler,README}.md # @register(...), handler, docs — the one sample node
  graph/model.py, validate.py, errors.py        # WorkflowGraph, one fn per rule, GraphValidationError
backend/app/db/models/workflow.py        # Workflow, WorkflowVersion, WorkflowStatus
backend/app/repositories/workflow.py      # mirrors virtual_table.py
backend/app/schemas/workflow.py            # WorkflowRead/DraftUpdate, NodeCatalog(Entry)
backend/app/services/workflow_registry.py   # draft CRUD, publish
backend/app/api/routes/v1/workflows.py       # node-catalog + draft CRUD + publish, thin
```

`app/agents/capabilities/**` and `app/services/virtual_tables/**` overlaid: a
registry package for the typed extension point, a thin service + repository
pair for the stored resource, one route module. `tests/test_workflow_node_layout.py`
(sibling of `test_capability_layout.py`) enforces the node-package shape so a
node cannot land outside `nodes/` with every other test still green.

## `NodeDefinition`, `register()`, `load_builtins()`

```python
@dataclass(frozen=True)
class Port:
    id: str
    label: str
    kind: Literal["input", "output"]   # #1793 caught this missing; direction is not inferable from id alone
    schema: type[BaseModel] | None   # None for a control port with no payload

@dataclass(frozen=True)
class NodeDefinition:
    id: str                          # "debug.echo" — permanent, like a capability id
    version: int                     # bumped on a breaking config/IO change
    name: str
    category: str
    description: str
    kind: Literal["action", "control", "waiting"]
    config_schema: type[BaseModel] | None
    input_schema: type[BaseModel] | None
    output_schema: type[BaseModel] | None
    ports: tuple[Port, ...]
    effect_kind: Literal["pure", "read", "write"]
    retry_guarantee: Literal["none", "idempotent", "at_least_once"]
    scopes: frozenset[str] = frozenset()
    handler: NodeHandler | None = None   # None until #1788 supplies one
```

`_registry.py` copies `app/agents/capabilities/_registry.py`'s shape:
`REGISTRY: dict[str, dict[int, NodeDefinition]]` keyed by id then version (a
graph pins `(id, version)`, so an old published graph may still reference a
superseded one); `register()` raises on a duplicate `(id, version)`;
`get(id, version)` raises `BadRequestError` naming what is available;
`all_node_definitions()` is sorted for a stable catalog; `load_builtins()`
imports `app.workflows.nodes` submodules explicitly (`debug_echo` only here),
same `_builtins_loaded` guard, same failure mode: a node package nobody
imports does not exist as far as the catalog is concerned.

`debug.echo` (the required sample, shared-contracts decision 5):
`kind="action"`, `effect_kind="pure"`, `retry_guarantee="idempotent"`, input
port `in` (`DebugEchoConfig{message: str}`), output port `out`
(`DebugEchoOutput{echoed: str, received_at: datetime}`), a real handler
returning `Completed(output=DebugEchoOutput(...))` — tested and callable
with no executor to call it yet, exactly what AC1 checks.

## The result contract

Every model below is `ConfigDict(frozen=True, extra="forbid")` unless noted;
omitted from the snippets for brevity.

```python
class Completed(BaseModel, Generic[T]):
    status: Literal["completed"] = "completed"
    output: T

class Waiting(BaseModel):
    status: Literal["waiting"] = "waiting"
    reason: Literal["approval", "external_event", "retry_backoff"]
    resume_token: str

class WorkflowError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False

class Failed(BaseModel):
    status: Literal["failed"] = "failed"
    error: WorkflowError

class Uncertain(BaseModel):
    status: Literal["uncertain"] = "uncertain"
    detail: str

NodeResult = Annotated[Completed[Any] | Waiting | Failed | Uncertain, Field(discriminator="status")]
```

`WorkflowError` mirrors `AppException`'s `message`/`details` shape
(`.claude/rules/exceptions-security.md`) rather than inventing a second one —
a handler wrapping a caught `AppException` maps it field for field.

## `io.py`: `FileRef`, `TableIORef`, bindings

The exact shapes the shared-contracts page resolved, not reopened here, each
carrying a `kind` discriminator for `BindingSource`:

```python
class FileRef(BaseModel):
    kind: Literal["file"] = "file"
    file_id: UUID
    content_type: str = Field(max_length=255)
    byte_size: int = Field(ge=0)

class TableIORef(BaseModel):
    kind: Literal["table"] = "table"
    table_id: UUID
    column_ids: tuple[UUID, ...] | None = None   # None = all live columns
    schema_version: int = Field(ge=1)             # the version this binding was checked against
```

Two more `kind`-discriminated variants complete `BindingSource`:
`NodeOutputRef{node_id: UUID, port: str, field_path: tuple[str, ...] = ()}`
and `LiteralValue{value: Any}` (a constant typed by the target field).
`field_path` was missing in the first draft (round 1 of this review: without
it, `NodeOutputRef` can only bind a *whole* port's payload, so `agent.run`'s
`AgentRunOutput` output could never satisfy a `str`-typed field like another
node's `prompt` — exactly #1793's two-agents-in-sequence journey, the
milestone's second acceptance criterion). Empty means "the whole port
value", matching the old behavior; a non-empty path walks `output_schema`'s
nested `model_fields` (`("text",)` off `AgentRunOutput` for its `text: str`)
and rule 3 (type compatibility) resolves the *path's* terminal type, not the
port's, refusing a path that does not exist on the schema or names a
non-leaf model where a scalar was bound. `Binding{target_node_id: UUID,
target_field: str, source: BindingSource}` is what a `NodeInstance.config`
field actually resolves to — see the graph model below.

A `TableIORef` is validated at bind time, inside `validate_graph`'s
resource-resolution pass, not merely at parse time: the service loads the
`VirtualTable` through `resolve_access(ctx, table, Perm.TABLES_VIEW,
resource_type=TABLE)`, confirms `schema_version` matches the table's current
one, and confirms every id in `column_ids` names a live column — reusing
`app/services/virtual_tables/types.py`'s lookups rather than a second copy.

## Graph model

`app/workflows/graph/model.py` — five frozen, `extra="forbid"` models:
`NodePosition{x: float, y: float}`; `NodeInstance{id: UUID, definition_id:
str, definition_version: int, config: dict[str, Any], layout: NodePosition}`;
`Edge{id, source_node_id, source_port: str, target_node_id, target_port: str}`;
`ScopeBoundary{scope_node_id: UUID, body_node_ids: frozenset[UUID],
entry_port: str, exit_port: str}` (a `control.foreach` instance plus the body
it owns); and `WorkflowGraph{entry_node_id: UUID, nodes: tuple[NodeInstance, ...],
edges: tuple[Edge, ...], bindings: tuple[Binding, ...], scopes: tuple[ScopeBoundary, ...] = ()}`.

`body_node_ids` is **server-derived, never client-authored** (#1793 found this
unresolved and #1790 built on top of it without answering it either): the
editor sends node positions and edges only; `validate_graph`'s reachability
pass computes, for each `control.foreach` node, the set of nodes reachable
from its `entry_port` and not reachable from the outer graph's own
`entry_node_id` except through that same entry port, and that computed set
*is* `body_node_ids` on the `WorkflowGraph` the server persists. A client
that claimed a different membership would have its claim silently
overwritten by the recomputed one, not validated against it — this is safer
than trusting a client-supplied set (which could misrepresent the
nested-scope-boundary rule) and asks nothing of #1787 beyond drawing edges.

`layout` carries only `NodePosition`; nothing execution-relevant reads it.
This is what makes AC3's "layout moves do not alter execution semantics"
testable rather than asserted: `validate_graph()` and every future consumer
never dereference `.layout`, so two graphs differing only in `NodePosition`
produce identical validation output, dominator sets and topological order.

## Graph validation

`validate_graph(graph, ctx) -> None` composes two passes, both collecting
every problem before refusing (the `agent_registry.py` convention).

**Pass 0 — resource resolution**, no topology: every `(definition_id,
definition_version)` must resolve via `_registry.get()` ("missing versions");
`NodeDefinition.scopes` must be a subset of `ctx`'s granted scopes
("inaccessible resources", mirroring `CapabilityDef.scopes` in `build()`);
every `TableIORef` binding must resolve and stay live, as above; every
`config` blob must validate against its `config_schema`.

**Pass 1 — the eight structural rules**, pure functions over the graph alone:

| # | Rule | Algorithm |
|---|---|---|
| 1 | Exactly one input | `entry_node_id` must name a node with in-degree 0. Refused if missing or if any edge targets it. |
| 2 | Reachable outputs | BFS/DFS forward from `entry_node_id`, treating each scope body as one opaque node reached only via its `entry_port`/`exit_port`. **Every top-level node must be visited, not only sinks** (fixed in round 1 of this review: checking only sinks lets a second, unreachable zero-in-degree source — or an unreachable island connected only to itself — pass both rule 1 and the old rule 2 undetected, since rule 1 only proves the *named* entry has in-degree 0, not that it is the *only* one). Any node the forward walk does not reach is named in the refusal, sinks and non-sinks alike. |
| 3 | Type compatibility | Per edge, compare the source port's `output_schema` field descriptor against the target port's `input_schema` descriptor — a shallow structural comparison (base type, and for `FileRef`/`TableIORef`/nested models, the model name) from `model_fields`, not full unification. |
| 4 | Branch-local data availability | Dominator check. Process nodes in topological order (rule 7 runs first); `Dom(entry)={entry}`; `Dom(n)={n} ∪ ⋂ Dom(p)` over predecessors `p`. A binding to `NodeOutputRef(node_id=M)` on node `N` is refused unless `M ∈ Dom(N)`. |
| 5 | Exclusive merge | For `logic.merge` with predecessors `A1..Ak`, compute their nearest common dominator `F` from rule 4's tree. Refused unless `F.definition_id == "logic.if"` and each `Ai` is dominated by a distinct immediate child of `F` — one branch port each, never both. |
| 6 | Nested scope boundaries | Node→scope map from `graph.scopes`. Any edge/binding crossing scopes is refused unless it is one of the two boundary edges a `ScopeBoundary` declares. |
| 7 | No cycles | Kahn's algorithm, run twice: once outer with each scope body collapsed to its `scope_node`, once inside each body independently. Nodes left with nonzero in-degree are the cycle. |
| 8 | No parallel fan-out (v1) | For every non-`control` node, group outgoing edges by `source_port`; refused if any port has >1 edge, or more than one port has any edge. Control nodes' declared branch ports are the sanctioned exception. |

A refusal is one `GraphValidationError(BadRequestError)` (422),
`details={"fields": [...]}` built with `field_problems`/`field_details`
exactly as `InvalidRecordError` is — one entry per violated rule, `field`
pointing at `nodes.<id>` / `edges.<id>` / `bindings.<index>`, `message`
naming the rule in prose. `validate_graph` raises once with every problem
collected, the same reason `_merge` in `records.py` collects every cell
problem before raising.

## `Workflow` / `WorkflowVersion` and the `expected_revision` flow

`agents`/`agent_versions`-shaped, not `virtual_tables`-shaped: `Workflow`
gets `draft_revision: int` (`Agent.draft_spec` has no such field today)
because `#1787`'s autosave writes drafts far more often than the Builder's
occasional agent edit. Starts at `0`, bumps by one per accepted draft write
only, never on publish.

`Workflow` (`workflows`, `TimestampMixin`): `id`, `organization_id` (FK
CASCADE, indexed), `owner_user_id`/`visibility` (shareable-resource pair, as
`Agent` has), `slug`, `name`, `status` (`WorkflowStatus`, default `draft`),
`draft_graph: JSONB`, `draft_revision: int` (`NOT NULL`, default `0`),
`current_version_id: UUID | None` (no FK, same reason as `Agent`'s).
`WorkflowVersion` (`workflow_versions`, `TimestampMixin`): `id`,
`workflow_id` (FK CASCADE), `organization_id`, `version: int`,
`graph: JSONB` (frozen `WorkflowGraph.model_dump(mode="json")`),
`note: str | None`, `published_by_user_id`, `budget_limit: Decimal | None`
(the pinned cap #1788's `WorkflowRun.budget_limit` copies at run start,
which #1793 found referenced without either issue having modeled where it
comes from — named to match `WorkflowRun.budget_limit` exactly rather than
`BudgetGuard`'s own internal `limit_usd`, since this field's only job is to
seed that column; `None` means "no workflow-level cap, only whatever each
`agent.run` node's own pinned agent enforces"), `UniqueConstraint(workflow_id, version)`.
Pinned per version like everything else here — republishing to change the cap
is the only way to change it, consistent with "published definitions remain
unchanged after draft edits."

**Draft write** (`PATCH .../{id}/draft`, body `{graph, expected_revision}`)
mirrors `RecordOperations.update_record`: load the row `for_update=True`,
compare `draft_revision` to `expected_revision` *before* any other check,
raise `RevisionConflictError` on mismatch (#1782's fields, retargeted to
`workflow_id`) — 409, `{"message": "...changed by someone else...", "details":
{"workflow_id", "expected_revision", "current_revision"}}` — otherwise store
`draft_graph` and increment `draft_revision`. `#1787`'s autosave reads
`current_revision` off the 409 and retries with it.

**Publish** (`POST .../{id}/publish`) is also `expected_revision`-gated, so a
publish racing a draft edit cannot promote a stale draft: same revision
check, then `validate_graph(WorkflowGraph.model_validate(draft_graph), ctx)`
(raises `GraphValidationError`, 422, on any Pass 0/1 rule), then
`workflow_repo.create_version(...)` at `current_version + 1`, flipping
`status` to `PUBLISHED`. `repositories/workflow.py` exposes `create_version`
and reads only — no `update_version` — which is what makes "published
definitions remain unchanged after draft edits" structural, not a convention
to remember.

## The node-catalog route

`GET /api/v1/workflows/node-catalog`, `response_model=NodeCatalog`, gated by
`dependencies=[Depends(require(Perm.WORKFLOWS_VIEW))]`, returns
`NodeCatalog(items=[...for d in all_node_definitions()], total=...)`.
`NodeCatalog`/`NodeCatalogEntry` mirror `CapabilityCatalog`/
`CapabilityCatalogEntry`: id, version, name, category, description, kind,
the three schemas as JSON Schema, ports, effect kind, retry guarantee,
scopes. `require(...)` is correct here — deployment-wide, no resource to
grant against — exactly as `CapabilityCatalog`'s own route.

`Perm.WORKFLOWS_VIEW`/`WORKFLOWS_EDIT`/`WORKFLOWS_CREATE` join `Perm` beside
`TABLES_*` (`RESOURCE_PERMS` for view/edit, every role's dict — `CREATE`
global-scoped like `TABLES_CREATE`). `WORKFLOW = ResourceType(key="workflow",
view=Perm.WORKFLOWS_VIEW, edit=Perm.WORKFLOWS_EDIT)` joins `access.py` beside
`TABLE`. Draft and publish routes use `resolve_access(db, ctx, workflow,
Perm.WORKFLOWS_EDIT, resource_type=WORKFLOW)` in the service, never a
route-level `require(...)` — per-resource routes delegate.

A **fourth permission, `Perm.WORKFLOWS_RUN`**, is added alongside these three
(#1793 found #1785 and #1792 both gating on it as though it already existed
in this document — it didn't; this is the fix, not a report of their error).
"May edit this workflow's graph" and "may cause a published version of it to
execute" are genuinely different authorities — a trigger or an exposure
invokes through `Perm.WORKFLOWS_RUN` on the `WORKFLOW` resource, checked at
admission and again at resume (#1785, #1792), while the editor and publish
routes stay on `WORKFLOWS_EDIT`. Resource-scoped like `VIEW`/`EDIT`, not
global like `CREATE`: a grant can hand someone the right to trigger one
specific workflow without handing them edit access to its graph.

`_PERM_MIN_GRANT[Perm.WORKFLOWS_RUN] = GrantLevel.USE` in `access.py` (round
1 of this review: the permission was added to the enum, the role tables and
`resolve_access`'s resource check, but not to this map — without it, a
caller relying on a resource *grant* rather than role scope would always be
refused, since `_PERM_MIN_GRANT.get(perm)` decides what grant level
satisfies a resource-scoped permission and an absent entry means none does).
`Perm.AGENTS_RUN: GrantLevel.USE` is the exact precedent — same shape,
already shipped, for the same "may invoke, may not edit" distinction on
agents.

## Migration

Verified against the `1782` worktree: `ls backend/alembic/versions | tail -5`
shows the chain ending at `0092_virtual_tables.py`; no `0093` exists there.
The shared-contracts page notes `#1823` already claimed `0093` on top of the
same branch elsewhere, but that branch is absent here and cannot be
confirmed. **Verify `alembic heads` against whatever #1786 actually stacks
on at implementation time**; take `0093` only if free, `0094_workflows.py`
otherwise. Two new tables, `workflows` and `workflow_versions`, both
org-scoped with `NOT NULL organization_id`, the `(workflow_id, version)`
unique constraint, no backfill needed — both are new.

## Coverage gate / `ty` include-list

Six new entries in both `[tool.coverage.run] include` and
`[[tool.ty.overrides]] include`, same order in both (checked by
`test_coverage_gate.py`), following `virtual_table`'s grouping:

```
"app/db/models/workflow.py",
"app/repositories/workflow.py",
"app/schemas/workflow.py",
"app/services/workflow_registry.py",
"app/workflows/**",
"app/api/routes/v1/workflows.py",
```

## Suggested commit order

1. `contracts/` + serialization tests.
2. `_registry.py` + drift test, empty `nodes/` package.
3. `nodes/debug_echo/` + tests — provable in isolation (AC1).
4. `graph/model.py` + `errors.py` + serialization tests (half of AC4).
5. `graph/validate.py`, one rule at a time with its own refusal test (AC2),
   composed into `validate_graph()` last.
6. `db/models/workflow.py` + `repositories/workflow.py` + the migration.
7. `schemas/workflow.py` + `services/workflow_registry.py` (draft CRUD,
   `expected_revision`, publish) + service tests (AC3).
8. `Perm.WORKFLOWS_*` + `ResourceType WORKFLOW` + role catalog entries + tests.
9. `api/routes/v1/workflows.py`, wired into the router, + API tests
   (403/404/409/422 paths).
10. `pyproject.toml` include-list edit; `docs/permissions.md` gets the three
    new permission rows — the only doc surface this issue owns, per the
    shared-contracts page's non-goals.

## Test plan against the four acceptance criteria

**AC1 — sample node without touching executor dispatch.**
`test_workflow_node_layout.py` asserts `debug_echo/`'s file shape.
`test_debug_echo_registered` asserts it is reachable through
`all_node_definitions()`/`get("debug.echo", 1)` after `load_builtins()` and
nowhere else. A unit test calls the handler directly and asserts
`Completed(output=DebugEchoOutput(...))`. No executor exists yet (`#1788`
owns it), so the criterion is trivially true for this diff; the layout test
keeps it true afterward.

**AC2 — invalid graphs refused with actionable errors.**
`test_workflow_graph_validation.py`: one test per rule (8 structural +
missing-version + inaccessible-scope + stale-`TableIORef`), each building the
smallest graph that violates exactly one rule and asserting
`GraphValidationError.details["fields"]` names the right id and a
human-readable message. An API test posts an invalid graph to `/publish` and
asserts 422 in the `field_problems` shape `InvalidRecordError` already uses.

**AC3 — published definitions immutable, layout inert.**
Publish, capture `WorkflowVersion.graph`; edit and republish the draft;
assert the original version row is unchanged (no update path exists on it).
A second test builds two graphs identical except every `NodePosition` and
asserts `validate_graph()` accepts/refuses both identically with equal
dominator sets and topological order. A third drives two concurrent
`PATCH .../draft` calls with one `expected_revision`; the loser gets
`RevisionConflictError` naming the winner's new revision.

**AC4 — contract serialization.**
`test_workflow_contracts.py`: round-trip each of
`Completed`/`Waiting`/`Failed`/`Uncertain` (discriminator resolves to the
right subtype), `WorkflowError` with populated `details`, `FileRef` (rejects
an extra field, rejects negative `byte_size`), `TableIORef` with
`column_ids=None` and with an explicit tuple, a `Binding` wrapping each
`BindingSource` variant, and a full `WorkflowGraph` carrying a
`ScopeBoundary` — asserting the round trip keeps the same `body_node_ids`.
