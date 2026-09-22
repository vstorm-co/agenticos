# Workflows: shared contracts

The cross-cutting decisions every per-issue design in this directory is
written against. #1786 is the issue that ships these; every other document
here treats this page as the authoritative interface rather than re-deriving
its own shape for the same thing. See the [implementation
plan](56-workflows-tables-implementation-plan.md) for status and build
order.

Written 2026-09-22. These are **design decisions, not yet implemented code**
— confirm they still hold before building against them, and update this page
in the same change if #1786's real implementation departs from it.

## Why #1786 is based on #1782's branch, not `main`

#1782 (`feat/1782-virtual-tables-storage`, PR #1812) is unmerged but built,
reviewed and tested. It already solves two problems #1786 would otherwise
have to solve from a standing start:

- **`expected_revision` optimistic concurrency** exists nowhere on `main`.
  It exists, proven, on #1782's branch. #1786 reuses that exact pattern
  rather than inventing a second one — see below.
- **Per-table dynamic IO** needs a real table/column model. #1782's branch
  has one (`VirtualTable`, `ColumnDef`, the column-type registry). A design
  based on `main` would have to stub this and rewrite it once #1782 merges;
  a design based on #1782's branch references the real thing once.

Practical consequence: #1786's branch stacks on
`feat/1782-virtual-tables-storage`, the same way #1823/PR #1828 already
does, and needs retargeting to `main` once #1782 merges. Its migration
number must be chosen against that branch's `alembic heads`, not `main`'s
(#1782's branch is currently at `0092`, and #1823 already claimed `0093` on
top of it — verify the actual head before numbering #1786's migration).

## Resolved decisions

Five questions were open after #1786's initial planning pass. Resolved as
follows, so implementation isn't blocked on further discussion:

1. **`FileRef` is originated by #1786**, not #1791. It is a thin, unopinionated
   reference (an opaque id, a declared content type, a declared byte size,
   nothing else) with no storage backing — #1786's contract tests exercise
   its *serialization*, not real file access. #1791 later adds real
   validation against authorized storage (local/S3) without changing this
   shape, only adding what enforces it. #1786's acceptance criteria
   explicitly require contract tests to cover `FileRef`, so the type has to
   exist at this tier regardless.
2. **`TableIORef` is a real reference into #1782's model** — a table id plus
   a list of column ids (or `None` for "all live columns"), validated at
   bind time against the table's *current* schema version the way a graph's
   other typed bindings are, not a generic placeholder.
3. **`expected_revision` is reused, not reinvented.** Same field name, same
   conflict/required error shape as #1782's `RevisionConflictError` /
   `RevisionRequiredError`, applied to `Workflow` draft writes. Same
   ordering too, precisely: authorization and lifecycle checks run first
   (round 1 of this review caught "revision before any other refusal"
   overstating this — read literally it would check revision before
   authorization, which #1782's real `update_record` never does), *then*
   the revision compare-and-set runs before payload/value validation or
   any mutation.
4. **`Perm.WORKFLOWS_VIEW` / `WORKFLOWS_EDIT` / `WORKFLOWS_CREATE` /
   `WORKFLOWS_RUN` and a `ResourceType WORKFLOW` are added in #1786**,
   mirroring #1782's `TABLES_VIEW`/`TABLES_EDIT`/`TABLES_CREATE` and
   `TABLE = ResourceType(...)`. Every later workflow route (#1787 onward)
   needs a gate to exist from day one; retrofitting it after routes are
   already shipped is more expensive than adding it alongside the model now.
   The fourth permission, `WORKFLOWS_RUN`, was added during the consistency
   pass across all eleven design documents (2026-09-22): #1785 and #1792 both
   needed to gate "may cause this workflow to execute" separately from "may
   edit its graph," and nothing in the original four decisions provided it.
5. **The one required sample node is `debug.echo`**, an action node with no
   real effect, not `core.input`/`core.output`. Those two names are left
   for #1789 to claim as the real graph-boundary node kinds it defines,
   rather than #1786 preempting them with a throwaway.

## Module layout

```
app/workflows/
  contracts/
    results.py      # Completed / Waiting / Failed / Uncertain — the discriminated union
    io.py            # IOPort, IOSchema, FileRef, TableIORef
    definition.py    # NodeDefinition, NodeKind, EffectKind, RetryGuarantee
  _registry.py        # register()/load_builtins(), mirrors app/agents/capabilities/_registry.py
  nodes/
    debug_echo/       # the one required sample node
  graph/
    model.py          # NodeInstance, Edge/Binding, ScopeBoundary
    validate.py        # one pure function per validation rule
    errors.py           # GraphValidationError, field-scoped problems
app/db/models/workflow.py     # Workflow (draft/published/archived) + WorkflowVersion (frozen)
app/schemas/workflow.py
app/services/workflow_registry.py
app/api/routes/v1/workflows.py   # thin: GET node-catalog + draft CRUD/publish
```

Deliberately mirrors `app/agents/capabilities/**`'s shape, so the existing
`tests/test_capability_layout.py` gets a workflow-side sibling rather than a
bespoke check, and so a developer who already knows how to add a capability
already knows the shape of adding a node.

## The result contract

```python
class Completed(BaseModel, Generic[T]):
    status: Literal["completed"] = "completed"
    output: T

class Waiting(BaseModel):
    status: Literal["waiting"] = "waiting"
    reason: Literal["approval", "external_event", "retry_backoff"]
    resume_token: str

class Failed(BaseModel):
    status: Literal["failed"] = "failed"
    error: WorkflowError   # typed, never a bare Exception

class Uncertain(BaseModel):
    status: Literal["uncertain"] = "uncertain"
    detail: str   # an external effect of unknown outcome — #1788 must reconcile, never retry blindly

NodeResult = Annotated[Completed | Waiting | Failed | Uncertain, Field(discriminator="status")]
```

#1786 defines and serialization-tests this. #1788 (durable execution)
interprets `Waiting`/`Uncertain` for its state machine. #1789/#1790/#1791
implement node handlers that return it. No issue other than #1786 changes
its shape without updating this page.

## `NodeDefinition`

```python
@dataclass(frozen=True)
class NodeDefinition:
    id: str                        # "debug.echo" — permanent, like a capability id
    version: int                   # bumped on a breaking config/IO change; a graph pins (id, version)
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
    scopes: frozenset[str] = frozenset()      # the same scope catalog capabilities use
    handler: NodeHandler | None = None         # None until an execution issue supplies one
```

`register()` / `REGISTRY` / `load_builtins()` copy
`app/agents/capabilities/_registry.py`'s shape exactly, including its
duplicate-id guard.

## Graph validation

One pure function per rule in the issue, composed by `validate_graph()`,
each returning field-scoped problems that are collected and reported
together (the `agent_registry.py` convention), refusing publication rather
than failing at run:

exactly-one-input · reachable-outputs (forward reachability from input) ·
type-compatibility (a static schema-shape check per edge) · branch-local
data availability (a binding may only reference a node reachable on *every*
path to it — a dominator check) · exclusive-merge (a `logic.merge`'s inputs
must come from one `logic.if`'s mutually exclusive branches, checked
structurally) · nested-scope boundaries (a `control.foreach` body cannot
bind outward except through its declared ports) · no cycles (Kahn's
algorithm, scope bodies treated as opaque) · no parallel fan-out in v1
(refused unless the node is `control`-kind).

## `Workflow` / `WorkflowVersion`

`Workflow` (draft/published/archived, like `Agent`) + `WorkflowVersion`
(frozen JSONB `graph`, like `AgentVersion`): `id, workflow_id,
organization_id, version, graph, note, published_by_user_id`,
`UniqueConstraint(workflow_id, version)`. `Workflow.draft_revision: int`
bumps on every draft write; draft-update routes take `expected_revision`
exactly as #1782's record writes do, comparing under a row lock and raising
the same conflict shape on mismatch. #1787's autosave and conflict banner
build directly on this.

## The editor catalog

A `NodeCatalog` (`items: list[NodeCatalogEntry]`, `total: int`) serialized
once from `all_node_definitions()`, mirroring `CapabilityCatalog` in
`app/api/routes/v1/agents.py`. `GET /api/v1/workflows/node-catalog`, gated
by `Perm.WORKFLOWS_VIEW`, permission-checked and free of secrets or raw
config values beyond schema. #1787 builds its palette against this; #1786
only has to expose it safely.

## Non-goals #1786 holds the line on

No execution (#1788 owns the state machine that interprets `NodeResult`),
no concrete node library beyond the one sample (#1789/#1790/#1791/#1792 own
the real nodes), no visual editor (#1787), no `eval`/`exec` of client-supplied
code or JS expressions anywhere, ever.
