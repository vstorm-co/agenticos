"""`validate_graph`: everything a graph must satisfy before it can be published.

Two passes, both collecting every problem before refusing (the
`agent_registry.py` convention - fixing a graph one error per round trip in
the editor is the difference between a Builder people use and one they
avoid):

- **Pass 0 - resource resolution**, no topology: every `(definition_id,
  definition_version)` must resolve, every scope a node needs must be
  granted, every `TableIORef` must still resolve and stay live, every
  `FileRef` must name a file from a run the author can see, and every
  node's `config` must validate against its `config_schema`.
- **Pass 1 - the nine structural rules**, pure functions over the graph.

`validate_graph` also derives `WorkflowGraph.scopes` before checking anything
- see `derive_scopes` - and returns the graph *with* that derived value, which
is what the caller persists. A client's own claim about scope membership is
never trusted, only overwritten.

## The control-node convention this module establishes

No control node ships in #1786 (`debug.echo` is `kind="action"`), so the
scope-deriving and scope-checking rules below are exercised only by
synthetic, test-registered `kind="control"` definitions. Two conventions,
settled against `1786-node-contracts.md` and `1790-error-foreach.md` (#1790
is the first issue to register a real `control.foreach` plus a body-interior
`loop.item`/`loop.yield`, and its design was written independently of this
module - `loop.yield` owning the scope's real exit corroborates the second
convention below rather than being reconciled with it after the fact):

- **Only a node whose id is in the `control.*` namespace owns a scope at
  all** - `logic.if` branches without owning a body, and only a looping
  construct like `control.foreach` does. Counting output ports alone cannot
  tell the two apart, since a branching node can equally have two or more.
  #1790's own `loop.item`/`loop.yield` corroborate this rather than
  complicating it: both are `kind="control"` (rule 10 needs them inside a
  scope, not owning one), and neither is `control.*`-namespaced - they sit
  in the `loop.*` namespace precisely because they are body-interior helpers
  of a scope, never scope owners themselves.
- **A scope-owning node's `entry_port` is always its own port** - the
  control node is the single node a client wires into and out of in the
  editor, and the body's reachability walk starts from the control node's
  own declared output ports. `exit_port`, however, is **not** always the
  control node's own port: it belongs to `ScopeBoundary.exit_node_id`, which
  may be the control node itself (every scope `derive_scopes` below computes
  today, since #1786 registers no control node whose exit lives elsewhere)
  or a body-interior node designated as the scope's real exit -
  `control.foreach`'s `loop.yield`, per #1790, whose own outgoing edge (not
  `control.foreach`'s) is what continues the outer graph. `ScopeBoundary`
  carries `exit_node_id` precisely so #1790 needs no second schema change to
  express this; `_scope_exit_edges` below is what lets rules 2 and 7 treat
  that edge as if it left the control node, exactly as rule 6 already does
  per-edge.

An earlier draft of this module kept both ports on `scope_node_id`, the only
node `ScopeBoundary` named at the time - the most direct reading available
before `exit_node_id` existed, but one `1786-node-contracts.md` itself
contradicted in its own derive-scopes walkthrough (see that document's
"ScopeBoundary: the settled shape" section) and one #1790's `loop.yield`
could not be expressed against at all.
"""

from __future__ import annotations

import json
import types
from collections import deque
from collections.abc import Callable
from typing import Any, Union, get_args, get_origin
from uuid import UUID

from pydantic import BaseModel, TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.field_errors import field_problems
from app.core.permissions import AuthContext, Perm
from app.repositories import virtual_table_repo
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_file as workflow_file_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.virtual_table import ColumnDef
from app.services.access import TABLE, WORKFLOW, resolve_access
from app.services.agent_registry import DEFAULT_GRANTED_SCOPES
from app.workflows import _registry
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.contracts.io import FileRef, LiteralValue, NodeOutputRef, TableIORef
from app.workflows.contracts.policy import ERROR_PORT
from app.workflows.contracts.results import WorkflowError
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, ScopeBoundary, WorkflowGraph
from app.workflows.nodes.control_foreach._handler import BODY_PORT, DONE_PORT

Problems = list[tuple[str, str]]
DefinitionMap = dict[UUID, NodeDefinition | None]
PortMap = dict[UUID, tuple[Port, ...]]

FOREACH = "control.foreach"
LOOP_ITEM = "loop.item"
LOOP_YIELD = "loop.yield"
ERROR_HANDLE = "error.handle"


def graph_size_problems(graph: WorkflowGraph) -> Problems:
    """A hard ceiling on one graph's node/edge/binding counts.

    Checked first, ahead of even `derive_scopes`: `_dominators` below
    retains a full dominator set per node, up to O(n^2) total memberships
    for a linear chain of n nodes, and the console routes a graph reaches
    through are explicitly unmetered (SECURITY.md's hardening checklist) -
    an unbounded graph is a resource-exhaustion vector, not only a slow
    request. `WorkflowRegistryService` calls this before a draft is even
    persisted, not only here at publish.
    """
    problems: Problems = []
    if len(graph.nodes) > settings.WORKFLOW_GRAPH_MAX_NODES:
        problems.append(
            ("nodes", f"A graph holds at most {settings.WORKFLOW_GRAPH_MAX_NODES} nodes")
        )
    if len(graph.edges) > settings.WORKFLOW_GRAPH_MAX_EDGES:
        problems.append(
            ("edges", f"A graph holds at most {settings.WORKFLOW_GRAPH_MAX_EDGES} edges")
        )
    if len(graph.bindings) > settings.WORKFLOW_GRAPH_MAX_BINDINGS:
        problems.append(
            ("bindings", f"A graph holds at most {settings.WORKFLOW_GRAPH_MAX_BINDINGS} bindings")
        )
    return problems


async def validate_graph(db: AsyncSession, ctx: AuthContext, graph: WorkflowGraph) -> WorkflowGraph:
    """Check every publish-time rule and return the graph with derived scopes.

    Raises:
        GraphValidationError: One or more rules failed. `details["fields"]`
            names every violation, not only the first.
    """
    size_problems = graph_size_problems(graph)
    if size_problems:
        raise GraphValidationError(size_problems)
    graph = derive_scopes(graph)
    definitions = _resolve_definitions(graph)

    problems: Problems = _dangling_reference_problems(graph)
    if problems:
        # Every other rule assumes an edge or a binding names a real node;
        # checking that first, and refusing before them, is what keeps their
        # own messages from being about a node that was never there.
        raise GraphValidationError(problems)

    problems += _missing_version_problems(graph, definitions)
    problems += _scope_access_problems(graph, definitions)
    problems += _config_schema_problems(graph, definitions)
    problems += _binding_target_field_problems(graph, definitions)
    problems += _literal_binding_type_problems(graph, definitions)
    problems += await _table_binding_problems(db, ctx, graph)
    problems += await _file_binding_problems(db, ctx, graph)
    problems += await _resource_problems(db, ctx, graph, definitions)

    node_scope = node_scope_map(graph)
    ports = instance_ports(graph, definitions)
    outer_predecessors, cycle_problems, outer_order = _rule_7_no_cycles(graph, node_scope)
    problems += cycle_problems

    problems += _rule_1_single_entry(graph)
    problems += _rule_2_reachable_outputs(graph, node_scope, outer_order)
    problems += _rule_3_type_compatibility(graph, definitions, ports)

    dominators = _all_dominators(graph, node_scope, outer_predecessors, outer_order)
    problems += _rule_4_branch_local_availability(graph, dominators, node_scope)
    problems += _rule_5_exclusive_merge(graph, definitions, dominators)
    problems += _rule_6_nested_scope_boundaries(graph, node_scope)
    problems += _rule_8_no_parallel_fanout(graph, definitions)
    problems += _rule_9_required_inputs_bound(graph, definitions)
    problems += _rule_10_error_routes(graph, definitions)
    problems += _rule_11_loop_bodies(graph, definitions, node_scope)
    problems += _rule_12_policies(graph, definitions)

    if problems:
        raise GraphValidationError(problems)
    return graph


# Scope derivation


def derive_scopes(graph: WorkflowGraph) -> WorkflowGraph:
    """Recompute `scopes` from the graph's own topology.

    Server-derived, never client-authored: the editor sends nodes, edges and
    bindings, and whatever it claims about `scopes` is discarded and replaced
    with this. See the module docstring for the control-node convention and
    the `ScopeBoundary` docstring for what `entry_port`/`exit_port` mean.
    """
    forward = _forward_edges(graph)
    scopes: list[ScopeBoundary] = []
    for node in graph.nodes:
        definition = _try_get_definition(node)
        if definition is None or not _owns_a_scope(definition):
            continue
        output_ports = [port.id for port in definition.ports if port.kind == "output"]
        if len(output_ports) < 2:
            continue
        entry_port, exit_port = output_ports[0], output_ports[1]
        body = _body_reachable_from(graph, forward, scope_node_id=node.id, entry_port=entry_port)
        scopes.append(
            ScopeBoundary(
                scope_node_id=node.id,
                body_node_ids=frozenset(body),
                entry_port=entry_port,
                # No registered control node designates a body-interior exit
                # (#1790's `loop.yield` does not exist here), so the only
                # sound derivation is the control node's own port. See the
                # module docstring: `exit_node_id` need not always equal
                # `scope_node_id`, but discovering a value other than the
                # control node's own id from topology alone is exactly the
                # circular problem `1786-node-contracts.md` warns about, and
                # would require metadata #1790's real `control.foreach` does
                # not exist yet to define.
                exit_node_id=node.id,
                exit_port=exit_port,
            )
        )
    return graph.model_copy(update={"scopes": tuple(scopes)})


def _owns_a_scope(definition: NodeDefinition) -> bool:
    """Whether this control node owns a body, as opposed to a plain branch.

    Not every `kind="control"` node has a scope: `logic.if` branches without
    owning a body, and only a looping construct like `control.foreach` does.
    Scoped by id namespace (`control.*`) rather than by output-port count
    alone, since a branching node can equally have two or more output ports
    without owning anything.
    """
    return definition.kind == "control" and definition.id.startswith("control.")


def _body_reachable_from(
    graph: WorkflowGraph, forward: dict[UUID, list[Edge]], *, scope_node_id: UUID, entry_port: str
) -> set[UUID]:
    """Forward BFS from `entry_port`'s targets, never re-entering `scope_node_id`.

    Excluding `scope_node_id` from the walk (rather than special-casing
    `exit_port` during it) is what stops the body from absorbing everything
    downstream of the scope: the only edges that lead back into the outer
    graph are the ones leaving `scope_node_id` itself, and those are never
    traversed because the walk never revisits it.
    """
    seen: set[UUID] = set()
    queue: deque[UUID] = deque(
        edge.target_node_id
        for edge in graph.edges
        if edge.source_node_id == scope_node_id and edge.source_port == entry_port
    )
    while queue:
        current = queue.popleft()
        if current in seen or current == scope_node_id:
            continue
        seen.add(current)
        for edge in forward.get(current, ()):
            if edge.target_node_id not in seen:
                queue.append(edge.target_node_id)
    return seen


def _forward_edges(graph: WorkflowGraph) -> dict[UUID, list[Edge]]:
    adjacency: dict[UUID, list[Edge]] = {}
    for edge in graph.edges:
        adjacency.setdefault(edge.source_node_id, []).append(edge)
    return adjacency


def node_scope_map(graph: WorkflowGraph) -> dict[UUID, UUID]:
    """Which scope owns each node, for nodes inside one at all.

    Nested scopes overlap: an outer scope's body BFS (`_body_reachable_from`)
    only refuses to re-enter its own `scope_node_id`, so it walks straight
    through a nested control node into that scope's body too - both
    boundaries list the same interior nodes. Ownership must resolve to the
    innermost one regardless of `graph.scopes`' own order (which follows
    `graph.nodes`, an editor's or a client's to reorder) - the smallest body
    containing a node is always the more deeply nested one, since a nested
    body is by construction a subset of everything that reaches it from
    outside.
    """
    owner: dict[UUID, UUID] = {}
    owner_body_size: dict[UUID, int] = {}
    for scope in graph.scopes:
        body_size = len(scope.body_node_ids)
        for node_id in scope.body_node_ids:
            current_size = owner_body_size.get(node_id)
            if current_size is None or body_size < current_size:
                owner[node_id] = scope.scope_node_id
                owner_body_size[node_id] = body_size
    return owner


def owner_chain(node_id: UUID, node_scope: dict[UUID, UUID]) -> list[UUID]:
    """The loops enclosing `node_id`, innermost first - empty at the top level."""
    chain: list[UUID] = []
    owner = node_scope.get(node_id)
    while owner is not None:
        chain.append(owner)
        owner = node_scope.get(owner)
    return chain


def instance_ports(graph: WorkflowGraph, definitions: DefinitionMap) -> PortMap:
    """Every node's ports as this graph configures it.

    The definition's own, or those its config declares (`ports_for` -
    `error.handle`'s branches), plus an `error` output port carrying the
    `WorkflowError` on a node whose policy routes its failures.
    """
    result: PortMap = {}
    for node in graph.nodes:
        definition = definitions.get(node.id)
        if definition is None:
            continue
        ports = definition.ports
        if definition.ports_for is not None:
            ports = definition.ports_for(_validated_config(node, definition))
        if node.routes_errors:
            ports = (
                *ports,
                Port(id=ERROR_PORT, label="Error", kind="output", schema=WorkflowError),
            )
        result[node.id] = ports
    return result


def _validated_config(node: NodeInstance, definition: NodeDefinition) -> BaseModel | None:
    if definition.config_schema is None:
        return None
    try:
        return definition.config_schema.model_validate(node.config)
    except PydanticValidationError:
        return None


def _scope_exit_edges(graph: WorkflowGraph) -> dict[UUID, list[Edge]]:
    """A scope's exit edges, keyed by `scope_node_id`, as the outer graph must see them.

    Only populated when `exit_node_id` differs from `scope_node_id` - #1790's
    `loop.yield`, body-interior: the real edge is sourced at the interior
    node, but rules 2 and 7 treat a whole scope as one opaque node wired
    through `scope_node_id` alone, so they consult this instead of
    `graph.edges` directly for that one edge. When the two coincide (every
    scope `derive_scopes` produces today), the real edge is already
    `scope_node_id`'s own and these rules find it there without help.
    """
    result: dict[UUID, list[Edge]] = {}
    for scope in graph.scopes:
        if scope.exit_node_id == scope.scope_node_id:
            continue
        matches = [
            edge
            for edge in graph.edges
            if edge.source_node_id == scope.exit_node_id and edge.source_port == scope.exit_port
        ]
        if matches:
            result[scope.scope_node_id] = matches
    return result


# Pass 0 - resource resolution


def _dangling_reference_problems(graph: WorkflowGraph) -> Problems:
    """Every edge and binding must name nodes that are actually in the graph.

    Checked once, structurally, ahead of every other rule: an edge or a
    binding naming a node that does not exist is not "the wrong shape" or
    "the wrong scope" - it is not a reference to anything, and every later
    rule assumes it is.
    """
    node_ids = set(graph.node_by_id)
    problems: Problems = []
    for edge in graph.edges:
        if edge.source_node_id not in node_ids:
            problems.append((f"edges.{edge.id}", "This edge's source node is not in this graph"))
        if edge.target_node_id not in node_ids:
            problems.append((f"edges.{edge.id}", "This edge's target node is not in this graph"))
    for index, binding in enumerate(graph.bindings):
        if binding.target_node_id not in node_ids:
            problems.append(
                (f"bindings.{index}", "This binding's target node is not in this graph")
            )
        if isinstance(binding.source, NodeOutputRef) and binding.source.node_id not in node_ids:
            problems.append(
                (f"bindings.{index}", "This binding's source node is not in this graph")
            )
    return problems


def _try_get_definition(node: NodeInstance) -> NodeDefinition | None:
    try:
        return _registry.get(node.definition_id, node.definition_version)
    except BadRequestError:
        return None


def _resolve_definitions(graph: WorkflowGraph) -> DefinitionMap:
    return {node.id: _try_get_definition(node) for node in graph.nodes}


def _missing_version_problems(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    return [
        (
            f"nodes.{node.id}",
            f"Unknown node definition: {node.definition_id!r} version {node.definition_version}",
        )
        for node in graph.nodes
        if definitions[node.id] is None
    ]


def _scope_access_problems(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    """A node's `scopes` must be a subset of what this deployment grants.

    Node scopes draw from the same catalog `NodeDefinition.scopes` documents
    capabilities using (`DEFAULT_GRANTED_SCOPES`) - one deployment-wide set,
    the same way `AgentRegistryService._binding_problems` checks a capability
    binding's scopes, rather than per-organization: nothing in this codebase
    grants a scope per tenant today.
    """
    problems: Problems = []
    for node in graph.nodes:
        definition = definitions[node.id]
        if definition is None:
            continue
        missing = definition.scopes - DEFAULT_GRANTED_SCOPES
        if missing:
            problems.append(
                (
                    f"nodes.{node.id}",
                    f"This deployment has not granted: {', '.join(sorted(missing))}",
                )
            )
    return problems


def _config_schema_problems(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    """`node.config` against its `config_schema`, aware of config bindings.

    `Binding.target_field` may name a `config_schema` field (a value that is
    configuration rather than runtime input, per its own docstring) - a debug
    node's own `message` is documented as "configured on the node, or bound",
    inclusively, a default a binding may override rather than a slot only one
    of the two may fill. So a required config field the client leaves out of
    `node.config` because a binding supplies it instead is not "missing" - it
    is bound; that is the only error class set aside for a bound field, and a
    wrong-shaped value the client *did* supply is still refused exactly as
    before.
    """
    problems: Problems = []
    bound_fields_by_node: dict[UUID, set[str]] = {}
    for binding in graph.bindings:
        bound_fields_by_node.setdefault(binding.target_node_id, set()).add(binding.target_field)

    for node in graph.nodes:
        definition = definitions[node.id]
        if definition is None:
            continue
        if definition.config_schema is None:
            if node.config:
                problems.append((f"nodes.{node.id}.config", "This node declares no configuration"))
            continue
        bound_fields = bound_fields_by_node.get(node.id, set()) & set(
            definition.config_schema.model_fields
        )
        try:
            definition.config_schema.model_validate(node.config)
        except PydanticValidationError as exc:
            root = f"nodes.{node.id}.config"
            errors = [
                error
                for error in exc.errors(include_url=False, include_input=False)
                if not (
                    error["type"] == "missing" and error["loc"] and error["loc"][0] in bound_fields
                )
            ]
            for problem in field_problems(errors, root=root):
                problems.append((problem["field"], problem["message"]))
    return problems


async def _resource_problems(
    db: AsyncSession, ctx: AuthContext, graph: WorkflowGraph, definitions: DefinitionMap
) -> Problems:
    """What each node's config names, checked against the graph's author.

    Only for a config that validates on its own: a config with a field still to
    be bound at run time, or one already refused above, has nothing settled to
    check yet, and a second refusal about the same field would only repeat it.
    """
    problems: Problems = []
    for node in graph.nodes:
        definition = definitions[node.id]
        if (
            definition is None
            or definition.resource_check is None
            or definition.config_schema is None
        ):
            continue
        try:
            config = definition.config_schema.model_validate(node.config)
        except PydanticValidationError:
            continue
        for field, message in await definition.resource_check(db, ctx, config):
            problems.append((f"nodes.{node.id}.config.{field}", message))
    return problems


async def _table_binding_problems(
    db: AsyncSession, ctx: AuthContext, graph: WorkflowGraph
) -> Problems:
    problems: Problems = []
    for index, binding in enumerate(graph.bindings):
        if not isinstance(binding.source, TableIORef):
            continue
        problems += await table_ref_problems(db, ctx, binding.source, field=f"bindings.{index}")
    return problems


async def _file_binding_problems(
    db: AsyncSession, ctx: AuthContext, graph: WorkflowGraph
) -> Problems:
    """Whether each `FileRef` a binding names is a file its author may hand a run.

    A file is always some run's output - there is no organization-wide one - so
    the author has to be able to see the workflow whose run made it. The same
    organization is not enough: an id learned from another workflow's run would
    otherwise be laundered into this one's imports, which a step then trusts.
    """
    problems: Problems = []
    for index, binding in enumerate(graph.bindings):
        if not isinstance(binding.source, FileRef):
            continue
        row = await workflow_file_repo.get(
            db, binding.source.file_id, organization_id=ctx.organization_id
        )
        run = (
            await workflow_run_repo.get_run(
                db, row.workflow_run_id, organization_id=ctx.organization_id
            )
            if row is not None
            else None
        )
        workflow = (
            await workflow_repo.get(db, run.workflow_id, organization_id=ctx.organization_id)
            if run is not None
            else None
        )
        if workflow is None or not await resolve_access(
            db, ctx, workflow, Perm.WORKFLOWS_VIEW, resource_type=WORKFLOW
        ):
            problems.append((f"bindings.{index}", "This file does not exist or is not accessible"))
    return problems


async def table_ref_problems(
    db: AsyncSession, ctx: AuthContext, ref: TableIORef, *, field: str
) -> Problems:
    """Whether `ref` still names a table `ctx` can read, at a schema that fits it.

    For a binding's source and a table node's own config alike: the table must
    exist and be readable, its schema must not have moved since the reference was
    made, and every column it pins must still be live.
    """
    table = await virtual_table_repo.get_table(
        db, ref.table_id, organization_id=ctx.organization_id
    )
    if table is None or not await resolve_access(db, ctx, table, TABLE.view, resource_type=TABLE):
        return [(field, "This table does not exist or is not accessible")]
    if table.schema_version != ref.schema_version:
        return [(field, "This table's schema has changed since this binding was made")]
    if ref.column_ids is None:
        return []
    version = await virtual_table_repo.get_schema_version(
        db, table_id=table.id, version=table.schema_version
    )
    live_ids = {
        column.id
        for column in (ColumnDef.model_validate(c) for c in version.columns)
        if not column.archived
    }
    missing = [column_id for column_id in ref.column_ids if column_id not in live_ids]
    if missing:
        return [(field, f"Not a live column of this table: {', '.join(str(m) for m in missing)}")]
    return []


# Rule 1 - exactly one input


def _rule_1_single_entry(graph: WorkflowGraph) -> Problems:
    if graph.entry_node_id not in graph.node_by_id:
        return [("entry_node_id", "The entry node is not one of this graph's nodes")]
    incoming = {edge.target_node_id for edge in graph.edges}
    if graph.entry_node_id in incoming:
        return [("entry_node_id", "The entry node cannot be the target of any edge")]
    return []


# Rule 2 - reachable outputs


def _rule_2_reachable_outputs(
    graph: WorkflowGraph, node_scope: dict[UUID, UUID], outer_order: list[UUID] | None
) -> Problems:
    """Every top-level node must be visited by a forward walk from the entry.

    Checking only sinks would let a second, unreachable zero-in-degree source
    pass undetected - rule 1 only proves the *named* entry has in-degree 0,
    not that it is the only one.
    """
    if graph.entry_node_id not in graph.node_by_id:
        return []
    top_level = [node.id for node in graph.nodes if node.id not in node_scope]
    adjacency = _forward_edges(graph)
    exit_edges = _scope_exit_edges(graph)
    seen: set[UUID] = set()
    queue: deque[UUID] = deque([graph.entry_node_id])
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        for edge in adjacency.get(current, ()):
            target_scope = node_scope.get(edge.target_node_id)
            target = (
                edge.target_node_id if target_scope is None else _scope_owner(graph, target_scope)
            )
            if target not in seen:
                queue.append(target)
        # A scope whose exit lives on a body-interior node (#1790's
        # `loop.yield`) has no edge of its own in `adjacency[current]` above;
        # its real exit edge is sourced elsewhere, so it is found here instead.
        # Unconditional, like the loop above would be without its own
        # dedup-on-append - `if current in seen: continue` at the top of the
        # `while` already makes a repeat enqueue harmless.
        for exit_edge in exit_edges.get(current, ()):
            queue.append(exit_edge.target_node_id)
    unreached = [node_id for node_id in top_level if node_id not in seen]
    return [
        (f"nodes.{node_id}", "This node is not reachable from the entry node")
        for node_id in unreached
    ]


def _scope_owner(graph: WorkflowGraph, scope_node_id: UUID) -> UUID:
    return scope_node_id


# Rule 3 - type compatibility


def _rule_3_type_compatibility(
    graph: WorkflowGraph, definitions: DefinitionMap, ports: PortMap
) -> Problems:
    problems: Problems = []
    for edge in graph.edges:
        source_definition = definitions.get(edge.source_node_id)
        target_definition = definitions.get(edge.target_node_id)
        if source_definition is None or target_definition is None:
            # Unresolvable definition is already reported by
            # `_missing_version_problems`; nothing more to say here.
            continue
        source_schema = _port_schema(ports[edge.source_node_id], edge.source_port, "output")
        if source_schema is _UNKNOWN:
            problems.append(
                (f"edges.{edge.id}", "This edge's source port does not exist on that node")
            )
            continue
        target_schema = _port_schema(ports[edge.target_node_id], edge.target_port, "input")
        if target_schema is _UNKNOWN:
            problems.append(
                (f"edges.{edge.id}", "This edge's target port does not exist on that node")
            )
            continue
        if not _shapes_compatible(source_schema, target_schema):
            problems.append(
                (f"edges.{edge.id}", "The source and target ports carry incompatible shapes")
            )
    for index, binding in enumerate(graph.bindings):
        if not isinstance(binding.source, NodeOutputRef):
            continue
        source_definition = definitions.get(binding.source.node_id)
        target_definition = definitions.get(binding.target_node_id)
        if source_definition is None or target_definition is None:
            continue
        source_type = _resolve_field_path(
            ports[binding.source.node_id], binding.source.port, binding.source.field_path
        )
        if source_type is _UNKNOWN:
            problems.append(
                (f"bindings.{index}", "This field path does not exist on the source port's schema")
            )
            continue
        target_type = _field_type(target_definition, binding.target_field)
        if target_type is not _UNKNOWN and not _types_compatible(source_type, target_type):
            problems.append(
                (f"bindings.{index}", "The source value is not compatible with this field")
            )
    return problems


def _literal_binding_type_problems(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    """A `LiteralValue` binding must actually satisfy the target field's type.

    The type check above only reaches a `NodeOutputRef` source, comparing
    one port schema's field to another's; a literal is a concrete value, not
    a schema, so it is validated against the target field's annotation
    directly rather than compared type-name to type-name.
    """
    problems: Problems = []
    for index, binding in enumerate(graph.bindings):
        if not isinstance(binding.source, LiteralValue):
            continue
        target_definition = definitions.get(binding.target_node_id)
        if target_definition is None:
            continue
        target_type = _field_type(target_definition, binding.target_field)
        if target_type is _UNKNOWN:
            continue
        try:
            # As JSON, because that is what a literal is: the graph is stored as
            # JSON, so a tuple arrives as a list and a UUID as a string, and strict
            # JSON validation accepts exactly those spellings and nothing looser.
            TypeAdapter(target_type).validate_json(json.dumps(binding.source.value), strict=True)
        except PydanticValidationError:
            problems.append(
                (f"bindings.{index}", "This literal value does not match the target field's type")
            )
    return problems


def _binding_target_field_problems(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    """Every binding's `target_field` must be a real field of the target node.

    `Binding`'s own docstring (`app.workflows.contracts.io`) promises this
    module confirms the field, the node and the source all agree; the type
    check above only reaches this for a `NodeOutputRef` source, so a literal,
    file or table binding naming a field that does not exist on the target's
    `input_schema`/`config_schema` passed unnoticed.
    """
    problems: Problems = []
    for index, binding in enumerate(graph.bindings):
        target_definition = definitions.get(binding.target_node_id)
        if target_definition is None:
            continue
        if _field_type(target_definition, binding.target_field) is _UNKNOWN:
            problems.append((f"bindings.{index}", "This field does not exist on the target node"))
    return problems


_UNKNOWN = object()


def _port_schema(ports: tuple[Port, ...], port_id: str, kind: str) -> Any:
    for port in ports:
        if port.id == port_id and port.kind == kind:
            return port.schema
    return _UNKNOWN


def _shapes_compatible(source: type[BaseModel] | None, target: type[BaseModel] | None) -> bool:
    """Whether an edge may carry `source`'s payload into `target`.

    A control port (`schema=None` on either end) carries nothing to compare,
    so it is compatible with anything - a pure control-flow edge into a data
    port simply triggers the node with whatever its own config already holds.
    Two data ports must share the same shape.
    """
    if source is None or target is None:
        return True
    if source is target:
        return True
    return _model_shape(source) == _model_shape(target)


def _model_shape(model: type[BaseModel]) -> frozenset[tuple[str, str]]:
    return frozenset(
        (name, _type_name(field.annotation)) for name, field in model.model_fields.items()
    )


def _type_name(annotation: Any) -> str:
    return getattr(annotation, "__name__", str(annotation))


def _field_type(definition: NodeDefinition, field_name: str) -> Any:
    for schema in (definition.input_schema, definition.config_schema):
        if schema is not None and field_name in schema.model_fields:
            return schema.model_fields[field_name].annotation
    return _UNKNOWN


def _resolve_field_path(ports: tuple[Port, ...], port_id: str, field_path: tuple[str, ...]) -> Any:
    schema = _port_schema(ports, port_id, "output")
    if schema is _UNKNOWN or schema is None:
        return _UNKNOWN if schema is _UNKNOWN else schema
    current: Any = schema
    for part in field_path:
        if _is_dynamic(current):
            return Any
        # A path may pass through an optional model (`record: Record | None`); at
        # run time a `None` there resolves the rest of the path to `None`, which
        # the target field then accepts or refuses on its own terms.
        members = _members(current)
        if len(members) == 1:
            current = members[0]
        if not (isinstance(current, type) and issubclass(current, BaseModel)):
            return _UNKNOWN
        if part not in current.model_fields:
            return _UNKNOWN
        current = current.model_fields[part].annotation
    return current


def _is_dynamic(annotation: Any) -> bool:
    """Whether a path may reach into `annotation` with no schema to follow.

    `Any`, or a `dict` whose values are `Any` (optionally `| None`): a
    trigger's payload, a mapped record, an agent's structured answer. What
    such a path finds is only known once the run has it, so it resolves to
    `Any` here and is validated against the target field when the node is
    dispatched - `_resolve_io` refuses a value that does not fit, which fails
    the run rather than handing a handler the wrong type.
    """
    if annotation is Any:
        return True
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        members = [arg for arg in get_args(annotation) if arg is not type(None)]
        return len(members) == 1 and _is_dynamic(members[0])
    if origin is dict:
        args = get_args(annotation)
        return len(args) == 2 and args[1] is Any
    return False


def _members(annotation: Any) -> list[Any]:
    """A union's members without `None`, or the annotation alone."""
    if get_origin(annotation) in (Union, types.UnionType):
        return [arg for arg in get_args(annotation) if arg is not type(None)]
    return [annotation]


def _types_compatible(source: Any, target: Any) -> bool:
    # `Any` on either side is checked at dispatch rather than here; see `_is_dynamic`.
    if source is target or source is Any or target is Any:
        return True
    # A free-form object field takes any structured value: a model's output
    # reaches it as the dict it is stored as.
    if _is_dynamic(target) and (
        _is_dynamic(source) or (isinstance(source, type) and issubclass(source, BaseModel))
    ):
        return True
    if get_origin(source) in _SEQUENCES and get_origin(target) in _SEQUENCES:
        return _sequences_compatible(source, target)
    source_members, target_members = _members(source), _members(target)
    if source_members == [source] and target_members == [target]:
        return _type_name(source) == _type_name(target)
    # A union on either side, `None` set aside: an optional target takes what it
    # holds (a `str` binds to `str | None`), and a source fits if every one of its
    # members fits some member of the target. A source that is `None` at run
    # time fills an optional field with `None`, which is what optional means.
    return all(
        any(_types_compatible(member, candidate) for candidate in target_members)
        for member in source_members
    )


_SEQUENCES = (list, tuple)


def _sequences_compatible(source: Any, target: Any) -> bool:
    """A list and a tuple are one JSON array: they bind to each other by element type.

    A `table.record.query`'s `records` is a tuple and a loop's `items` a list;
    both arrive as the same array, so only what they hold decides - and a
    `list[Any]` takes anything.
    """
    target_item = next((arg for arg in get_args(target) if arg is not Ellipsis), Any)
    return all(
        _types_compatible(item, target_item) for item in get_args(source) if item is not Ellipsis
    )


# Rule 7 - no cycles (run first; rules 4/5 need a topological order)


def _rule_7_no_cycles(
    graph: WorkflowGraph, node_scope: dict[UUID, UUID]
) -> tuple[dict[UUID, set[UUID]], Problems, list[UUID] | None]:
    """Kahn's algorithm, run over the outer graph and independently per body.

    Scope bodies are collapsed to their `scope_node` for the outer pass, so a
    loop's own internal edges never register as a cycle at the outer level.
    """
    top_level_edges = [
        edge
        for edge in graph.edges
        if edge.source_node_id not in node_scope and edge.target_node_id not in node_scope
    ]
    # A scope's exit edge sourced at a body-interior node (#1790's
    # `loop.yield`) has one endpoint inside `node_scope` and is dropped by
    # the filter above; the outer pass still needs to see it, as if it left
    # `scope_node_id` - the one node the outer graph is actually wired to.
    # A target that turns out to be inside another scope is `_kahn`'s to
    # ignore, the same way it already ignores any edge naming a node outside
    # the node list it was given.
    for scope_node_id, exit_edges in _scope_exit_edges(graph).items():
        for exit_edge in exit_edges:
            top_level_edges.append(exit_edge.model_copy(update={"source_node_id": scope_node_id}))
    top_level_nodes = [node.id for node in graph.nodes if node.id not in node_scope]
    predecessors, order, cyclic = _kahn(top_level_nodes, top_level_edges)
    problems: Problems = [
        (f"nodes.{node_id}", "This node is part of a cycle") for node_id in sorted(cyclic, key=str)
    ]

    for scope in graph.scopes:
        body_edges = [
            edge
            for edge in graph.edges
            if edge.source_node_id in scope.body_node_ids
            and edge.target_node_id in scope.body_node_ids
        ]
        _, _, body_cyclic = _kahn(list(scope.body_node_ids), body_edges)
        problems += [
            (f"nodes.{node_id}", "This node is part of a cycle within its scope")
            for node_id in sorted(body_cyclic, key=str)
        ]

    return predecessors, problems, (None if cyclic else order)


def _kahn(
    nodes: list[UUID], edges: list[Edge]
) -> tuple[dict[UUID, set[UUID]], list[UUID], set[UUID]]:
    predecessors: dict[UUID, set[UUID]] = {node_id: set() for node_id in nodes}
    successors: dict[UUID, list[UUID]] = {node_id: [] for node_id in nodes}
    in_degree: dict[UUID, int] = dict.fromkeys(nodes, 0)
    for edge in edges:
        if edge.source_node_id not in in_degree or edge.target_node_id not in in_degree:
            continue
        successors[edge.source_node_id].append(edge.target_node_id)
        predecessors[edge.target_node_id].add(edge.source_node_id)
        in_degree[edge.target_node_id] += 1

    queue: deque[UUID] = deque(node_id for node_id, degree in in_degree.items() if degree == 0)
    order: list[UUID] = []
    remaining = dict(in_degree)
    while queue:
        current = queue.popleft()
        order.append(current)
        for successor in successors[current]:
            remaining[successor] -= 1
            if remaining[successor] == 0:
                queue.append(successor)
    cyclic = {node_id for node_id in nodes if node_id not in order}
    return predecessors, order, cyclic


# Rule 4 - branch-local data availability (dominators)


def _all_dominators(
    graph: WorkflowGraph,
    node_scope: dict[UUID, UUID],
    outer_predecessors: dict[UUID, set[UUID]],
    outer_order: list[UUID] | None,
) -> dict[UUID, frozenset[UUID]]:
    if outer_order is None or graph.entry_node_id not in graph.node_by_id:
        return {}
    dominators = _dominators(outer_order, outer_predecessors, root=graph.entry_node_id)

    for scope in graph.scopes:
        body_edges = [
            edge
            for edge in graph.edges
            if edge.source_node_id in scope.body_node_ids
            and edge.target_node_id in scope.body_node_ids
        ]
        body_predecessors, body_order, cyclic = _kahn(list(scope.body_node_ids), body_edges)
        if cyclic:
            continue
        entry_targets = {
            edge.target_node_id
            for edge in graph.edges
            if edge.source_node_id == scope.scope_node_id and edge.source_port == scope.entry_port
        }
        for node_id in entry_targets:
            body_predecessors.setdefault(node_id, set()).add(scope.scope_node_id)
        body_order_with_root = [scope.scope_node_id, *body_order]
        body_dominators = _dominators(
            body_order_with_root, body_predecessors, root=scope.scope_node_id
        )
        # Only the nodes this scope owns directly: an outer body's walk also
        # passes through a nested loop's body, and which of the two answers
        # stood would otherwise depend on the order the scopes are listed in.
        dominators.update(
            {
                node_id: doms
                for node_id, doms in body_dominators.items()
                if node_scope.get(node_id) == scope.scope_node_id
            }
        )
    return dominators


def _dominators(
    order: list[UUID], predecessors: dict[UUID, set[UUID]], *, root: UUID
) -> dict[UUID, frozenset[UUID]]:
    dom: dict[UUID, frozenset[UUID]] = {root: frozenset({root})}
    changed = True
    while changed:
        changed = False
        for node_id in order:
            if node_id == root:
                continue
            preds = [p for p in predecessors.get(node_id, ()) if p in dom]
            if not preds:
                continue
            new_dom = frozenset.intersection(*(dom[p] for p in preds)) | {node_id}
            if dom.get(node_id) != new_dom:
                dom[node_id] = new_dom
                changed = True
    return dom


def _rule_4_branch_local_availability(
    graph: WorkflowGraph, dominators: dict[UUID, frozenset[UUID]], node_scope: dict[UUID, UUID]
) -> Problems:
    """A node binds only to what has certainly run before it.

    Inside a loop body that includes what ran before the loop: a binding to a node
    of an enclosing scope is checked at that scope's level, against the loop the
    target sits in - the source must dominate the loop itself.
    """
    problems: Problems = []
    for index, binding in enumerate(graph.bindings):
        if not isinstance(binding.source, NodeOutputRef):
            continue
        source_id = binding.source.node_id
        target_id = _at_level_of(binding.target_node_id, node_scope.get(source_id), node_scope)
        if target_id is None:
            # Not an enclosing scope's node - rule 6 says so.
            continue
        if source_id == target_id:
            # A node dominates itself (`_dominators` always folds `node_id`
            # into its own set), so the membership check below would call
            # this available - it never is, since the node has not run yet
            # at the point it would need its own output.
            problems.append((f"bindings.{index}", "This binding reads the node's own output"))
            continue
        target_dom = dominators.get(target_id)
        if target_dom is None:
            continue
        if source_id not in target_dom:
            problems.append(
                (
                    f"bindings.{index}",
                    "This binding reads a node's output on a path where that node has not "
                    "necessarily run",
                )
            )
    return problems


def _at_level_of(node_id: UUID, level: UUID | None, node_scope: dict[UUID, UUID]) -> UUID | None:
    """`node_id`, or the loop enclosing it that sits directly in scope `level`."""
    current: UUID | None = node_id
    while current is not None and node_scope.get(current) != level:
        current = node_scope.get(current)
    return current


# Rule 5 - exclusive merge


def _rule_5_exclusive_merge(
    graph: WorkflowGraph, definitions: DefinitionMap, dominators: dict[UUID, frozenset[UUID]]
) -> Problems:
    problems: Problems = []
    predecessors: dict[UUID, list[UUID]] = {}
    for edge in graph.edges:
        predecessors.setdefault(edge.target_node_id, []).append(edge.source_node_id)

    for node in graph.nodes:
        definition = definitions.get(node.id)
        if definition is None or definition.id != "logic.merge":
            continue
        branches = predecessors.get(node.id, [])
        if len(branches) < 2:
            continue
        distinct_branches = set(branches)
        if len(distinct_branches) != len(branches):
            problems.append(
                (f"nodes.{node.id}", "This merge has more than one edge from the same branch")
            )
            continue
        common = _nearest_common_dominator(branches, dominators)
        if common is None:
            problems.append((f"nodes.{node.id}", "This merge's branches share no common dominator"))
            continue
        if not _branches_exclusively(graph.node_by_id[common], definitions.get(common)):
            problems.append(
                (
                    f"nodes.{node.id}",
                    "A merge's branches must come from one logic.if, error handler or "
                    "error-routing step",
                )
            )
            continue
        if not _branches_diverge_at(common, node.id, distinct_branches, graph, dominators):
            problems.append(
                (
                    f"nodes.{node.id}",
                    "This merge's branches are not mutually exclusive - they leave their "
                    "branching step through the same port",
                )
            )
    return problems


def _branches_exclusively(node: NodeInstance, definition: NodeDefinition | None) -> bool:
    """Whether exactly one of this node's output ports is ever taken per run.

    `logic.if` takes `true` or `false`, `error.handle` one branch, and a node that
    routes its errors leaves by `out` or by `error` - never both.
    """
    return node.routes_errors or (
        definition is not None and definition.id in ("logic.if", ERROR_HANDLE)
    )


def _branches_diverge_at(
    common: UUID,
    merge: UUID,
    branches: set[UUID],
    graph: WorkflowGraph,
    dominators: dict[UUID, frozenset[UUID]],
) -> bool:
    """Whether each branch is reachable from `common` through a distinct port.

    A shared dominator is not enough: rule 8 lets a control node fan one port
    out to more than one target, so two branches leaving `common` through the
    *same* port can both run together (or neither run) - not the mutually
    exclusive pair `logic.merge` is built to wait on. Nor is a non-empty,
    non-overlapping `feeding_ports` enough on its own: a branch reconverged
    from more than one of `common`'s ports *before* it is reached (a node
    downstream of both `then` and `else`, alongside one downstream of only
    `then`) is dominated by neither port alone, so it can run on either
    outcome - `feeding_ports` comes back empty for it, not merely shared with
    another branch, and an empty set is refused here for the same reason a
    shared one is.
    """
    seen_ports: set[str] = set()
    for branch in branches:
        branch_dom = dominators.get(branch, frozenset())
        # A branch that is the branching step itself - its port wired straight
        # to the merge - is fed by that edge's port.
        feeding_ports = {
            edge.source_port
            for edge in graph.edges
            if edge.source_node_id == common
            and (
                edge.target_node_id == merge
                if branch == common
                else edge.target_node_id in branch_dom
            )
        }
        if not feeding_ports or feeding_ports & seen_ports:
            return False
        seen_ports |= feeding_ports
    return True


def _nearest_common_dominator(
    nodes: list[UUID], dominators: dict[UUID, frozenset[UUID]]
) -> UUID | None:
    resolved_dom_sets = [dominators.get(node_id) for node_id in nodes]
    if any(dom_set is None for dom_set in resolved_dom_sets):
        return None
    dom_sets: list[frozenset[UUID]] = [
        dom_set for dom_set in resolved_dom_sets if dom_set is not None
    ]
    common = frozenset[UUID].intersection(*dom_sets)
    if not common:
        return None
    # The nearest is the one every other member of `common` also dominates -
    # i.e. it is dominated by everything else in the set.
    for candidate in common:
        candidate_dom = dominators.get(candidate, frozenset())
        if common <= candidate_dom:
            return candidate
    return None


# Rule 6 - nested scope boundaries


def _rule_6_nested_scope_boundaries(graph: WorkflowGraph, node_scope: dict[UUID, UUID]) -> Problems:
    entry_boundary_by_node = {scope.scope_node_id: scope for scope in graph.scopes}
    exit_boundary_by_node = {scope.exit_node_id: scope for scope in graph.scopes}
    problems: Problems = []
    for edge in graph.edges:
        source_scope = node_scope.get(edge.source_node_id)
        target_scope = node_scope.get(edge.target_node_id)
        if source_scope == target_scope:
            continue
        if _is_sanctioned_boundary_edge(edge, entry_boundary_by_node, exit_boundary_by_node):
            continue
        problems.append((f"edges.{edge.id}", "This edge crosses a scope boundary"))
    for index, binding in enumerate(graph.bindings):
        if not isinstance(binding.source, NodeOutputRef):
            continue
        source_id = binding.source.node_id
        chain = owner_chain(binding.target_node_id, node_scope)
        source_scope = node_scope.get(source_id)
        if source_id in chain:
            problems.append(
                (
                    f"bindings.{index}",
                    "This binding reads the loop it runs inside; the loop's results exist "
                    "only once it ends",
                )
            )
        elif source_scope != node_scope.get(binding.target_node_id) and (
            source_scope is not None and source_scope not in chain
        ):
            # Reading into a body from outside it: which iteration's value would
            # it be? What leaves a loop is its `results`.
            problems.append((f"bindings.{index}", "This binding crosses a scope boundary"))
    return problems


def _is_sanctioned_boundary_edge(
    edge: Edge,
    entry_boundary_by_node: dict[UUID, ScopeBoundary],
    exit_boundary_by_node: dict[UUID, ScopeBoundary],
) -> bool:
    """Whether `edge` is one of the two edges a `ScopeBoundary` declares.

    The entry edge (`source_port == entry_port`) always sources at
    `scope_node_id`. The exit edge (`source_port == exit_port`) sources at
    `exit_node_id`, which is `scope_node_id` for every scope #1786 derives
    today but may be a body-interior node - #1790's `loop.yield` - once a
    real `control.foreach` registers one.
    """
    entry_scope = entry_boundary_by_node.get(edge.source_node_id)
    if entry_scope is not None and edge.source_port == entry_scope.entry_port:
        return True
    exit_scope = exit_boundary_by_node.get(edge.source_node_id)
    return exit_scope is not None and edge.source_port == exit_scope.exit_port


# Rule 8 - no parallel fan-out (v1)


def _rule_8_no_parallel_fanout(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    problems: Problems = []
    by_node: dict[UUID, dict[str, list[Edge]]] = {}
    for edge in graph.edges:
        by_node.setdefault(edge.source_node_id, {}).setdefault(edge.source_port, []).append(edge)

    for node_id, by_port in by_node.items():
        definition = definitions.get(node_id)
        if definition is not None and definition.kind == "control":
            continue
        # A routed failure leaves by `error` instead of `out`, never beside it.
        ports_with_edges = [port for port, edges in by_port.items() if edges and port != ERROR_PORT]
        if len(ports_with_edges) > 1:
            problems.append(
                (f"nodes.{node_id}", "A non-control node may only send output through one port")
            )
        for port, edges in by_port.items():
            if len(edges) > 1:
                problems.append(
                    (
                        f"nodes.{node_id}",
                        f"A non-control node's {port!r} port has more than one edge",
                    )
                )
    return problems


# Rule 9 - every required input is bound exactly once


def _rule_9_required_inputs_bound(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    problems: Problems = []
    bound_counts: dict[tuple[UUID, str], int] = {}
    for binding in graph.bindings:
        key = (binding.target_node_id, binding.target_field)
        bound_counts[key] = bound_counts.get(key, 0) + 1

    # Every bound field, not only a required one: two competing sources for
    # an optional field are just as ambiguous - which one an executor would
    # see is undefined - and `field.is_required()` below only ever reaches a
    # field with no binding at all.
    for (node_id, field_name), count in bound_counts.items():
        if count > 1:
            problems.append((f"nodes.{node_id}.{field_name}", "This input is bound more than once"))

    for node in graph.nodes:
        definition = definitions.get(node.id)
        if definition is None or definition.input_schema is None:
            continue
        for field_name, field in definition.input_schema.model_fields.items():
            if field.is_required() and bound_counts.get((node.id, field_name), 0) == 0:
                problems.append(
                    (f"nodes.{node.id}.{field_name}", "This required input is not bound")
                )
    return problems


# Rule 10 - routed errors go somewhere, and stay on their own path


def _rule_10_error_routes(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    """A failure a graph claims to handle must reach a handler, and only a handler.

    A node routing its errors needs its `error` port connected - otherwise a
    failure would end the node, skip everything after it and let the run succeed.
    An `error.handle` needs its `default` connected, so an error no branch matches
    has somewhere to go. And a binding keeps to its side: nothing reachable only
    through `error` may read the node's output (there is none on that path), and
    nothing reachable through `out` may read its error.
    """
    problems: Problems = []
    for node in graph.nodes:
        definition = definitions.get(node.id)
        if node.routes_errors and not _port_edges(graph, node.id, ERROR_PORT):
            problems.append(
                (
                    f"nodes.{node.id}",
                    "This step routes its errors, but its error port leads nowhere",
                )
            )
        if (
            definition is not None
            and definition.id == ERROR_HANDLE
            and not _port_edges(graph, node.id, "default")
        ):
            problems.append(
                (f"nodes.{node.id}", "An error handler's default branch must lead somewhere")
            )

    for index, binding in enumerate(graph.bindings):
        if not isinstance(binding.source, NodeOutputRef):
            continue
        source = graph.node_by_id.get(binding.source.node_id)
        if source is None or not source.routes_errors:
            continue
        on_error_path = _reached_through(graph, source.id, lambda port: port == ERROR_PORT)
        on_success_path = _reached_through(graph, source.id, lambda port: port != ERROR_PORT)
        target = binding.target_node_id
        if binding.source.port == ERROR_PORT and target in on_success_path:
            problems.append(
                (
                    f"bindings.{index}",
                    "This binding reads the step's error on a path where it may have succeeded",
                )
            )
        elif binding.source.port != ERROR_PORT and target in on_error_path:
            problems.append(
                (
                    f"bindings.{index}",
                    "This binding reads the step's output on its error path, where there is none",
                )
            )
    return problems


def _port_edges(graph: WorkflowGraph, node_id: UUID, port: str) -> list[Edge]:
    return [
        edge for edge in graph.edges if edge.source_node_id == node_id and edge.source_port == port
    ]


def _reached_through(
    graph: WorkflowGraph, node_id: UUID, port_matches: Callable[[str], bool]
) -> set[UUID]:
    """Every node reachable from `node_id` through an edge leaving a matching port."""
    adjacency = _forward_edges(graph)
    queue: deque[UUID] = deque(
        edge.target_node_id for edge in adjacency.get(node_id, ()) if port_matches(edge.source_port)
    )
    seen: set[UUID] = set()
    while queue:
        current = queue.popleft()
        if current in seen or current == node_id:
            continue
        seen.add(current)
        queue.extend(edge.target_node_id for edge in adjacency.get(current, ()))
    return seen


# Rule 11 - loop bodies have one way in and one way out


def _rule_11_loop_bodies(
    graph: WorkflowGraph, definitions: DefinitionMap, node_scope: dict[UUID, UUID]
) -> Problems:
    """A `control.foreach` body starts at one `loop.item` and ends at one `loop.yield`.

    `loop.item` is what the dispatcher writes as each iteration starts, and
    `loop.yield` is what it reads back as the iteration's result, so a body with
    neither, or two, has no defined start or result. Both mean nothing outside a
    body. The loop continues through `done`, never through a step inside its own
    body, and loops nest only so deep.
    """
    problems: Problems = []
    by_id = {node.id: definitions.get(node.id) for node in graph.nodes}
    for node in graph.nodes:
        definition = by_id[node.id]
        if definition is None:
            continue
        if definition.loop_body_only:
            owner = node_scope.get(node.id)
            owner_definition = by_id.get(owner) if owner is not None else None
            if owner_definition is None or owner_definition.id != FOREACH:
                problems.append(
                    (f"nodes.{node.id}", "This step only works inside a for-each loop's body")
                )
        if definition.id != FOREACH:
            continue
        problems += _foreach_body_problems(graph, node.id, by_id, node_scope)
        depth = len(owner_chain(node.id, node_scope)) + 1
        if depth > settings.WORKFLOW_FOREACH_MAX_DEPTH:
            problems.append(
                (
                    f"nodes.{node.id}",
                    f"Loops nest at most {settings.WORKFLOW_FOREACH_MAX_DEPTH} deep; "
                    f"this one is {depth} deep",
                )
            )
    return problems


def _foreach_body_problems(
    graph: WorkflowGraph,
    loop_id: UUID,
    by_id: dict[UUID, NodeDefinition | None],
    node_scope: dict[UUID, UUID],
) -> Problems:
    problems: Problems = []
    field = f"nodes.{loop_id}"
    entries = _port_edges(graph, loop_id, BODY_PORT)
    direct = [node_id for node_id, owner in node_scope.items() if owner == loop_id]

    def _count(definition_id: str) -> int:
        return sum(
            1
            for node_id in direct
            if (definition := by_id.get(node_id)) is not None and definition.id == definition_id
        )

    entry_definition = by_id.get(entries[0].target_node_id) if len(entries) == 1 else None
    if entry_definition is None or entry_definition.id != LOOP_ITEM or _count(LOOP_ITEM) != 1:
        problems.append((field, "A loop's body must start at exactly one loop item step"))
    if _count(LOOP_YIELD) != 1:
        problems.append((field, "A loop's body must end at exactly one loop result step"))
    body = {node_id for node_id in node_scope if loop_id in owner_chain(node_id, node_scope)}
    for edge in _port_edges(graph, loop_id, DONE_PORT):
        if edge.target_node_id in body:
            problems.append(
                (f"edges.{edge.id}", "A loop continues through done to a step outside its body")
            )
    return problems


# Rule 12 - a policy only promises what the step can keep


def _rule_12_policies(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    """Retries only where a repeat is safe, and no policy where nothing runs.

    The retry guarantee is the call's own when the definition decides it per
    configuration - an `http.request` `GET` may retry, a `POST` without an
    idempotency header may not.
    """
    problems: Problems = []
    for node in graph.nodes:
        definition = definitions.get(node.id)
        if definition is None or node.policy is None:
            continue
        if definition.handler is None:
            problems.append(
                (f"nodes.{node.id}.policy", "This step never runs, so it takes no policy")
            )
            continue
        retry = node.policy.retry
        if retry is None or retry.max_attempts == 1:
            continue
        guarantee = definition.retry_guarantee
        if definition.retry_guarantee_for is not None:
            guarantee = definition.retry_guarantee_for(_validated_config(node, definition))
        if guarantee == "none":
            problems.append(
                (
                    f"nodes.{node.id}.policy.retry",
                    "Repeating this step's call is not safe, so it cannot retry",
                )
            )
    return problems
