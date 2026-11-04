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

import json
import types
from collections import deque
from collections.abc import Callable, Iterator
from itertools import islice
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
from app.workflows import _registry
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition, Port
from app.workflows.contracts.io import (
    Binding,
    FileRef,
    LiteralValue,
    NodeOutputRef,
    TableIORef,
    TemplateValue,
    file_refs,
    output_refs,
    target_path,
)
from app.workflows.contracts.policy import ERROR_PORT
from app.workflows.contracts.results import WorkflowError
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.joins import (
    GraphAnalysis,
    analyse,
    any_pair_runs_together,
    at_level_of,
    can_run_together,
    wire_condition,
    wire_runs_whenever,
)
from app.workflows.graph.model import Edge, NodeInstance, ScopeBoundary, WorkflowGraph
from app.workflows.graph.quick_log import references, refused_reference
from app.workflows.nodes._port_names import clash_message
from app.workflows.nodes.control_foreach._handler import BODY_PORT, DONE_PORT
from app.workflows.triggers import UNATTENDED, entry_graph, entry_nodes

Problems = list[tuple[str, str]]
DefinitionMap = dict[UUID, NodeDefinition | None]
PortMap = dict[UUID, tuple[Port, ...]]

FOREACH = "control.foreach"
LOOP_ITEM = "loop.item"
LOOP_YIELD = "loop.yield"
ERROR_HANDLE = "error.handle"


def graph_size_problems(graph: WorkflowGraph) -> Problems:
    """A hard ceiling on one graph's node/edge/binding counts.

    Checked first, ahead of even `derive_scopes`: the run conditions and ancestor
    sets `analyze_graph` keeps per node grow with the graph, up to O(n^2) total
    memberships for a linear chain of n nodes, and the console routes a graph reaches
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
    problems += _error_port_clash_problems(graph, definitions)
    problems += _binding_target_field_problems(graph, definitions)
    problems += _literal_binding_type_problems(graph, definitions)
    problems += _template_binding_problems(graph, definitions)
    problems += await _table_binding_problems(db, ctx, graph)
    problems += await file_binding_problems(db, ctx, graph)
    problems += await _resource_problems(db, ctx, graph, definitions)

    entries = entry_nodes(graph)
    if len(entries) > 1:
        problems += _rule_1_single_entry(graph)
        problems += _rule_2_reachable_outputs(graph, analyze_graph(graph).node_scope, [])
        for entry in entries:
            branch = derive_scopes(entry_graph(graph, entry.id))
            dangling = _dangling_reference_problems(branch)
            problems += dangling
            if not dangling:
                problems += _structure_problems(
                    branch, {node.id: definitions[node.id] for node in branch.nodes}
                )
    else:
        problems += _structure_problems(graph, definitions)

    if problems:
        raise GraphValidationError(problems)
    return graph


def _structure_problems(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    problems: Problems = []
    analysis = analyze_graph(graph)
    node_scope = analysis.node_scope
    ports = instance_ports(graph, definitions)
    _, cycle_problems, outer_order = _rule_7_no_cycles(graph, node_scope)
    problems += cycle_problems

    problems += _rule_1_single_entry(graph)
    problems += _rule_2_reachable_outputs(graph, node_scope, outer_order)
    problems += _rule_3_type_compatibility(graph, definitions, ports)

    problems += _rule_4_branch_local_availability(graph, analysis.precede, node_scope)
    problems += _merge_mode_problems(analysis)
    problems += _rule_5_exclusive_merge(graph, definitions)
    problems += _rule_6_nested_scope_boundaries(graph, node_scope)
    problems += _rule_8_one_port(graph, definitions)
    problems += _shared_error_handler_problems(analysis)
    problems += _answering_step_problems(analysis)
    problems += _split_problems(graph, definitions)
    problems += _merge_setting_binding_problems(graph, definitions)
    problems += _rule_9_required_inputs_bound(graph, definitions)
    problems += _rule_10_error_routes(graph, definitions)
    problems += _rule_11_loop_bodies(graph, definitions, node_scope)
    problems += _rule_12_policies(graph, definitions)
    problems += _rule_13_named_and_switched_off_steps(graph, definitions, ports)
    problems += _quick_log_problems(graph, ports)

    return problems


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


def analyze_graph(graph: WorkflowGraph) -> GraphAnalysis:
    """Everything the publish rules and the dispatcher read off a graph's shape.

    Scopes, definitions and, per scope, the condition each step runs under, its wires
    and what must precede it - computed once per graph. A graph whose outer part is
    cyclic has no conditions: the cycle is refused on its own.
    """
    graph = derive_scopes(graph)
    definitions = _resolve_definitions(graph)
    node_scope = node_scope_map(graph)
    _, _, order = _rule_7_no_cycles(graph, node_scope)
    return analyse(graph, definitions, node_scope, acyclic=order is not None)


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
        if any(ref.node_id not in node_ids for ref in output_refs(binding.source)):
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
    # Imported here: `agent_registry` reaches the capability registry, which
    # reaches this module through the table and artifact services (an import cycle).
    from app.services.agent_registry import DEFAULT_GRANTED_SCOPES

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
        bound_fields_by_node.setdefault(binding.target_node_id, set()).add(
            target_path(binding.target_field)[0]
        )

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


# Where an author names the output ports of a step: its config's list and the key
# holding each entry's name.
_AUTHOR_NAMED_PORTS = {
    "logic.switch": ("rules", "name"),
    "ai.classify": ("categories", "name"),
    "error.handle": ("branches", "name"),
    "human.approval": ("choices", "id"),
    "logic.split": ("branches", "name"),
}


def _error_port_clash_problems(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    """An author-named port called `error`, on a step that routes its errors.

    The step's own config refuses a name that is one of its static ports
    (`nodes._port_names`), but `error` is a port only when the step's policy
    routes its errors, which only the graph knows.
    """
    problems: Problems = []
    for node in graph.nodes:
        definition = definitions.get(node.id)
        if definition is None or not node.routes_errors:
            continue
        named = _AUTHOR_NAMED_PORTS.get(definition.id)
        if named is None:
            continue
        field, key = named
        entries = node.config.get(field)
        if not isinstance(entries, list):
            continue
        for index, entry in enumerate(entries):
            if isinstance(entry, dict) and entry.get(key) == ERROR_PORT:
                problems.append(
                    (
                        f"nodes.{node.id}.config.{field}.{index}.{key}",
                        clash_message(ERROR_PORT),
                    )
                )
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


def graph_file_refs(graph: WorkflowGraph) -> Iterator[tuple[str, FileRef]]:
    """File imports named by direct bindings and recursively by pinned outputs."""
    seen: set[UUID] = set()
    for index, binding in enumerate(graph.bindings):
        if isinstance(binding.source, FileRef) and binding.source.file_id not in seen:
            seen.add(binding.source.file_id)
            yield f"bindings.{index}", binding.source
    for node in graph.nodes:
        for ref in file_refs(node.pinned_output):
            if ref.file_id not in seen:
                seen.add(ref.file_id)
                yield f"nodes.{node.id}.pinned_output", ref


async def file_binding_problems(
    db: AsyncSession, ctx: AuthContext, graph: WorkflowGraph
) -> Problems:
    """Whether each `FileRef` a binding names is a file its author may hand a run.

    A file is always some run's output - there is no organization-wide one - so
    the author has to be able to see the workflow whose run made it. The same
    organization is not enough: an id learned from another workflow's run would
    otherwise be laundered into this one's imports, which a step then trusts.
    """
    problems: Problems = []
    refs = list(islice(graph_file_refs(graph), settings.WORKFLOW_GRAPH_MAX_BINDINGS + 1))
    if len(refs) > settings.WORKFLOW_GRAPH_MAX_BINDINGS:
        return [
            (
                "files",
                f"A graph imports at most {settings.WORKFLOW_GRAPH_MAX_BINDINGS} unique files",
            )
        ]
    for field, ref in refs:
        row = await workflow_file_repo.get(db, ref.file_id, organization_id=ctx.organization_id)
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
        if (
            workflow is None
            or (ctx.api_key_id is not None and run is not None and not run.public_origin)
            or not await resolve_access(
                db, ctx, workflow, Perm.WORKFLOWS_VIEW, resource_type=WORKFLOW
            )
        ):
            problems.append((field, "This file does not exist or is not accessible"))
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
    """One way in: the entry is a node no edge reaches, and a trigger is the entry.

    A workflow starts from exactly one trigger - the node naming how a run is
    admitted - so a second one is refused, and so is a trigger that is not where
    the graph starts: it would name a way in that never runs the steps after it.
    """
    if graph.entry_node_id not in graph.node_by_id:
        return [("entry_node_id", "The entry node is not one of this graph's nodes")]
    incoming = {edge.target_node_id for edge in graph.edges}
    if graph.entry_node_id in incoming:
        return [("entry_node_id", "The entry node cannot be the target of any edge")]
    triggers = [
        node.id
        for node in graph.nodes
        if (definition := _try_get_definition(node)) is not None
        and definition.category == TRIGGER_CATEGORY
    ]
    problems: Problems = [
        (f"nodes.{node_id}", "A trigger cannot have an incoming connection")
        for node_id in triggers
        if node_id in incoming
    ]
    kinds: set[str] = set()
    for entry in entry_nodes(graph):
        if entry.definition_id in UNATTENDED:
            if entry.definition_id in kinds:
                problems.append((f"nodes.{entry.id}", "Use one trigger of each unattended kind"))
            kinds.add(entry.definition_id)
    return problems


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
    queue: deque[UUID] = deque(node.id for node in entry_nodes(graph))
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
    for index, binding, ref, templated in _output_reads(graph):
        source_definition = definitions.get(ref.node_id)
        target_definition = definitions.get(binding.target_node_id)
        if source_definition is None or target_definition is None:
            continue
        source_type = _resolve_field_path(ports[ref.node_id], ref.port, ref.field_path)
        if source_type is _UNKNOWN:
            problems.append(
                (f"bindings.{index}", "This field path does not exist on the source port's schema")
            )
            continue
        if templated:
            # A placeholder becomes text whatever it holds; the field taking text
            # is `_template_binding_problems`' to check, once per template.
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


def _template_binding_problems(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    """A `TemplateValue` makes text, so the field it is bound to must take text."""
    problems: Problems = []
    for index, binding in enumerate(graph.bindings):
        if not isinstance(binding.source, TemplateValue):
            continue
        target_definition = definitions.get(binding.target_node_id)
        if target_definition is None:
            continue
        target_type = _field_type(target_definition, binding.target_field)
        if target_type is not _UNKNOWN and not _types_compatible(str, target_type):
            problems.append(
                (f"bindings.{index}", "A template makes text, and this field does not take text")
            )
    return problems


def _output_reads(graph: WorkflowGraph) -> list[tuple[int, Binding, NodeOutputRef, bool]]:
    """Every read of another node's output: the binding, the reference, and whether
    the reference is a template's placeholder.

    A template reads one per placeholder, each checked like a binding of its own
    - it exists, it runs before the reader, it is in scope - and flagged, since
    what it holds becomes text rather than filling the field as it is.
    """
    return [
        (index, binding, ref, isinstance(binding.source, TemplateValue))
        for index, binding in enumerate(graph.bindings)
        for ref in output_refs(binding.source)
    ]


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
    """What a binding's `target_field` takes: its field's type, or `Any` for one
    key of a field that takes an open object. `_UNKNOWN` when neither exists."""
    field, key = target_path(field_name)
    for schema in (definition.input_schema, definition.config_schema):
        if schema is not None and field in schema.model_fields:
            annotation = schema.model_fields[field].annotation
            if key is None:
                return annotation
            one_key = bool(key) and field_name.count("/") == 1
            return Any if one_key and _takes_keys(annotation) else _UNKNOWN
    return _UNKNOWN


def _takes_keys(annotation: Any) -> bool:
    """Whether a field is an open object a binding may fill one key at a time:
    `dict[str, Any]`, optionally `| None`."""
    if get_origin(annotation) in (Union, types.UnionType):
        members = [arg for arg in get_args(annotation) if arg is not type(None)]
        return len(members) == 1 and _takes_keys(members[0])
    return get_origin(annotation) is dict and get_args(annotation) == (str, Any)


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

    `Any`, or a `dict` whose values are such (optionally `| None`): a
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
        return len(args) == 2 and _is_dynamic(args[1])
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


# Rule 4 - branch-local data availability


def _rule_4_branch_local_availability(
    graph: WorkflowGraph, precede: dict[UUID, frozenset[UUID]], node_scope: dict[UUID, UUID]
) -> Problems:
    """A node binds only to what has certainly run before it.

    That is the steps before it that run whenever it does (`GraphAnalysis.precede`): the
    steps on its way in, and every leg of a parallel group before the step that waits for
    them, but not one arm of an If. Inside a loop body that includes what ran before the loop: a
    binding to a node of an enclosing scope is checked at that scope's level, against the
    loop the target sits in - the source must precede the loop itself.
    """
    problems: Problems = []
    for index, binding, ref, _templated in _output_reads(graph):
        source_id = ref.node_id
        target_id = at_level_of(binding.target_node_id, node_scope.get(source_id), node_scope)
        if target_id is None:
            # Not an enclosing scope's node - rule 6 says so.
            continue
        if source_id == target_id:
            # A node precedes itself (`precede` always folds `node_id`
            # into its own set), so the membership check below would call
            # this available - it never is, since the node has not run yet
            # at the point it would need its own output.
            problems.append((f"bindings.{index}", "This binding reads the node's own output"))
            continue
        target_precede = precede.get(target_id)
        if target_precede is None:
            continue
        if source_id not in target_precede:
            problems.append(
                (
                    f"bindings.{index}",
                    "This binding reads a node's output on a path where that node has not "
                    "necessarily run",
                )
            )
    return problems


# Rule 5 - exclusive merge


def _rule_5_exclusive_merge(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    """A merge takes one edge from each branch.

    Whether its branches are exclusive is the join classification's to say
    (`_merge_mode_problems`); what is left here is the shape no classification can
    read - two edges leaving one port into the same merge, whichever way it waits.
    """
    problems: Problems = []
    incoming: dict[UUID, list[tuple[UUID, str]]] = {}
    for edge in graph.edges:
        incoming.setdefault(edge.target_node_id, []).append((edge.source_node_id, edge.source_port))

    for node in graph.nodes:
        definition = definitions.get(node.id)
        if definition is None or definition.id != MERGE:
            continue
        edges_in = incoming.get(node.id, [])
        if len(edges_in) > 1 and len(set(edges_in)) != len(edges_in):
            problems.append(
                (f"nodes.{node.id}", "This merge has more than one edge from the same branch")
            )
    return problems


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
    for index, binding, ref, _templated in _output_reads(graph):
        source_id = ref.node_id
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


# Rule 8 - one port

MERGE = "logic.merge"
SPLIT = "logic.split"


def _rule_8_one_port(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    """A step that is not a control node sends its output through one port.

    Any number of steps may follow a port: they run side by side, and the steps that
    wait for them are what `_merge_mode_problems` judges.
    """
    problems: Problems = []
    ports_by_node: dict[UUID, set[str]] = {}
    for edge in graph.edges:
        # A routed failure leaves by `error` instead of `out`, never beside it.
        if edge.source_port != ERROR_PORT:
            ports_by_node.setdefault(edge.source_node_id, set()).add(edge.source_port)

    for node_id, ports in ports_by_node.items():
        definition = definitions.get(node_id)
        if definition is not None and definition.kind == "control":
            continue
        if len(ports) > 1:
            problems.append(
                (f"nodes.{node_id}", "A non-control node may only send output through one port")
            )
    return problems


def _wait_for(node: NodeInstance) -> str:
    """A merge's `wait_for` as stored: absent means the branch that ran."""
    return "all" if node.config.get("wait_for") == "all" else "one"


def _merges(analysis: GraphAnalysis) -> list[NodeInstance]:
    return [
        node
        for node in analysis.graph.nodes
        if (definition := analysis.definitions.get(node.id)) is not None and definition.id == MERGE
    ]


def _merge_mode_problems(analysis: GraphAnalysis) -> Problems:
    """A merge's `wait_for` must match how its branches reach it, and its branch names be usable.

    Branches that can run together need `all`, or the merge would pass on one of them and
    forget the rest; and `all` needs each of them certain to arrive whenever the merge runs.
    Branches of which only one runs need `one`. Under `all` each branch is handed on by
    name, so the names must differ; a name read that no branch has is refused where it is
    read. A merge with a branch nothing reaches is left to the reachability rule.
    """
    # Imported here: the node's handler module reaches back into the graph package.
    from app.workflows.nodes.logic_merge._handler import branch_keys

    graph = analysis.graph
    problems: Problems = []
    keys_by_merge: dict[UUID, set[str]] = {}
    for node in _merges(analysis):
        mode = _wait_for(node)
        keys = branch_keys(graph, node)
        wires = analysis.incoming.get(node.id, ())
        if len(wires) > 1 and all(wire_condition(analysis, node.id, w) is not None for w in wires):
            together = any_pair_runs_together(analysis, node.id)
            uncertain = [w for w in wires if not wire_runs_whenever(analysis, node.id, w)]
            name = (
                keys[(uncertain[0].source_node_id, uncertain[0].source_port)] if uncertain else ""
            )
            if mode == "one" and together:
                problems.append(
                    (
                        f"nodes.{node.id}",
                        "Several branches reach this merge together; set Wait for to All branches"
                        if not uncertain
                        else f"Several branches reach this merge together, and '{name}' is "
                        "not certain to arrive",
                    )
                )
            elif mode == "all" and not together:
                problems.append(
                    (
                        f"nodes.{node.id}",
                        "Only one branch can reach this merge at a time; "
                        "set Wait for to The branch that ran",
                    )
                )
            elif mode == "all":
                problems += [
                    (
                        f"nodes.{node.id}",
                        f"'{keys[(wire.source_node_id, wire.source_port)]}' is not certain to "
                        "reach this merge whenever it runs",
                    )
                    for wire in uncertain
                ]
        names = list(keys.values())
        keys_by_merge[node.id] = set(names)
        if mode == "all" and (not all(names) or len(set(names)) != len(names)):
            problems.append(
                (f"nodes.{node.id}.config.branch_keys", "Each branch needs a name of its own")
            )
    for index, _binding, ref, _templated in _output_reads(graph):
        keys = keys_by_merge.get(ref.node_id)
        if keys is None or len(ref.field_path) < 2 or ref.field_path[0] != "branches":
            continue
        if ref.field_path[1] not in keys:
            problems.append(
                (f"bindings.{index}", f"This merge has no branch called '{ref.field_path[1]}'")
            )
    return problems


def _split_problems(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    """A Split takes every branch at once, so it has no one way out for an error to take instead."""
    return [
        (f"nodes.{node.id}.policy", "A Split cannot route its errors; route each branch's own")
        for node in graph.nodes
        if node.routes_errors
        and (definition := definitions.get(node.id)) is not None
        and definition.id == SPLIT
    ]


_MERGE_SETTINGS = frozenset({"wait_for", "branch_keys"})


def _merge_setting_binding_problems(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    """A Merge's `wait_for` and `branch_keys` are fixed in the editor, never bound.

    The executor decides when a Merge runs from its stored config, so a binding that
    changed either one would reach the handler's call but not the decision.
    """
    return [
        (
            f"nodes.{binding.target_node_id}.{binding.target_field}",
            "A Merge's setting cannot be bound",
        )
        for binding in graph.bindings
        if (definition := definitions.get(binding.target_node_id)) is not None
        and definition.id == MERGE
        and target_path(binding.target_field)[0] in _MERGE_SETTINGS
    ]


def _shared_error_handler_problems(analysis: GraphAnalysis) -> Problems:
    """An error handler may not be fed by two branches that run together.

    It would see two errors at once but can hand on only one.
    """
    return [
        (
            f"nodes.{node.id}",
            "Two branches that run together send their errors here; give each branch its own "
            "error handler",
        )
        for node in analysis.graph.nodes
        if (definition := analysis.definitions.get(node.id)) is not None
        and definition.id == ERROR_HANDLE
        and any_pair_runs_together(analysis, node.id)
    ]


def _answering_step_problems(analysis: GraphAnalysis) -> Problems:
    """A run answers once, and a webhook is answered once: no second step that may answer too."""
    messages = {
        "core.output": "This Output step and another can both run in one run; a run answers once",
        "webhook.respond": "This Respond to webhook step and another can both run in one run; "
        "a webhook is answered once",
    }
    problems: Problems = []
    for definition_id, message in messages.items():
        answering = [
            node
            for node in analysis.graph.nodes
            if (definition := analysis.definitions.get(node.id)) is not None
            and definition.id == definition_id
        ]
        for index, later in enumerate(answering):
            if any(
                analysis.node_scope.get(earlier.id) == analysis.node_scope.get(later.id)
                and can_run_together(analysis, earlier.id, later.id)
                for earlier in answering[:index]
            ):
                problems.append((f"nodes.{later.id}", message))
    return problems


# Rule 9 - every required input is bound exactly once

# Steps that branch on `value`: unbound it reads `None`, so the step would always take its
# false / otherwise branch without anything saying so.
_DECIDES_ON_VALUE = frozenset({"logic.if", "logic.switch"})


def _rule_9_required_inputs_bound(graph: WorkflowGraph, definitions: DefinitionMap) -> Problems:
    problems: Problems = []
    bound_counts: dict[tuple[UUID, str], int] = {}
    # A field bound one key at a time is bound - and must not be bound whole too,
    # or which value a key holds would depend on the order the bindings ran in.
    keyed: set[tuple[UUID, str]] = set()
    for binding in graph.bindings:
        key = (binding.target_node_id, binding.target_field)
        bound_counts[key] = bound_counts.get(key, 0) + 1
        field, by_key = target_path(binding.target_field)
        if by_key is not None:
            keyed.add((binding.target_node_id, field))
    for node_id, field_name in sorted(keyed & set(bound_counts), key=str):
        problems.append(
            (f"nodes.{node_id}.{field_name}", "This input is bound whole and by key at once")
        )

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
        if (
            definition.id in _DECIDES_ON_VALUE
            and (node.id, "value") not in bound_counts
            and (node.id, "value") not in keyed
        ):
            problems.append(
                (
                    f"nodes.{node.id}.value",
                    "This step decides on `value` - bind what it should look at",
                )
            )
        for field_name, field in definition.input_schema.model_fields.items():
            if (
                field.is_required()
                and bound_counts.get((node.id, field_name), 0) == 0
                and (node.id, field_name) not in keyed
            ):
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

    for index, binding, ref, _templated in _output_reads(graph):
        source = graph.node_by_id.get(ref.node_id)
        if source is None or not source.routes_errors:
            continue
        on_error_path = _reached_through(graph, source.id, lambda port: port == ERROR_PORT)
        on_success_path = _reached_through(graph, source.id, lambda port: port != ERROR_PORT)
        target = binding.target_node_id
        if ref.port == ERROR_PORT and target in on_success_path:
            problems.append(
                (
                    f"bindings.{index}",
                    "This binding reads the step's error on a path where it may have succeeded",
                )
            )
        elif ref.port != ERROR_PORT and target in on_error_path:
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


# Rule 13 - a step's own name, and what switching one off may not break


def _hands_on(graph: WorkflowGraph, ports: PortMap, ref: NodeOutputRef) -> bool:
    """Whether a step switched off hands on what `ref` reads from it.

    Switched off, a step hands on what came in along its one incoming edge. That
    is what `ref` gets if the step before is on and its output has the field, of a
    type the switched-off step's own output declares there.
    """
    incoming = [edge for edge in graph.edges if edge.target_node_id == ref.node_id]
    if len(incoming) != 1:
        return False
    edge = incoming[0]
    if graph.node_by_id[edge.source_node_id].disabled:
        return False
    arriving = _resolve_field_path(ports[edge.source_node_id], edge.source_port, ref.field_path)
    declared = _resolve_field_path(ports[ref.node_id], ref.port, ref.field_path)
    if arriving is _UNKNOWN or declared is _UNKNOWN:
        return False
    return _types_compatible(arriving, declared)


def _rule_13_named_and_switched_off_steps(
    graph: WorkflowGraph, definitions: DefinitionMap, ports: PortMap
) -> Problems:
    """Names tell steps apart, and a step switched off leaves nothing waiting on it.

    Two steps may not share a name, ignoring case: the name is how a builder tells
    them apart in every list of bindings and problems. A step switched off does
    nothing, so it may be neither the trigger nor a step that decides which way the
    run goes, and nothing may read its output unless it hands the field on - what
    came into it has that field (`_hands_on`).
    """
    problems: Problems = []
    named: dict[str, UUID] = {}
    for node in graph.nodes:
        label = (node.label or "").strip()
        if label:
            key = label.casefold()
            if key in named:
                problems.append(
                    (f"nodes.{node.id}.label", f"Another step is already called '{label}'")
                )
            else:
                named[key] = node.id
        if not node.disabled:
            continue
        definition = definitions.get(node.id)
        if node.id == graph.entry_node_id:
            problems.append((f"nodes.{node.id}.disabled", "The trigger cannot be switched off"))
        elif definition is not None and definition.kind == "control":
            problems.append(
                (
                    f"nodes.{node.id}.disabled",
                    "A step that decides which way the run goes cannot be switched off",
                )
            )
    for index, _binding, ref, _templated in _output_reads(graph):
        if graph.node_by_id[ref.node_id].disabled and not _hands_on(graph, ports, ref):
            problems.append(
                (
                    f"bindings.{index}",
                    "This reads a step that is switched off, so it would receive nothing",
                )
            )
    return problems


def _quick_log_problems(graph: WorkflowGraph, ports: PortMap) -> Problems:
    """A Quick Log logs only ports its step has, and reads nothing it may not.

    `outputs` names output ports of the step as this graph configures it - `error`
    among them when the step routes its errors. A message may read `{{step}}`,
    `{{outcome}}`, the step's own output and `{{error.code}}` / `{{error.message}}`;
    `error.details` and the rest of the error are refused. A reference with no value
    on some run - an output field of a step that failed, an error of one that
    succeeded - is not a problem: the line renders it empty.
    """
    problems: Problems = []
    for node in graph.nodes:
        quick_log = node.quick_log
        if quick_log is None:
            continue
        if node.definition_id in (LOOP_ITEM, LOOP_YIELD):
            problems.append(
                (
                    f"nodes.{node.id}.quick_log",
                    "A quick log goes on the loop itself, not on its item or yield step",
                )
            )
            continue
        if quick_log.outputs == ():
            problems.append(
                (
                    f"nodes.{node.id}.quick_log.outputs",
                    "Name at least one output, or leave it unset to log every outcome; "
                    "to log nothing, remove the quick log",
                )
            )
        for path in references(quick_log.message):
            if refused_reference(path):
                problems.append(
                    (
                        f"nodes.{node.id}.quick_log.message",
                        f"'{{{{{'.'.join(path)}}}}}' cannot be read: a log line may read "
                        "only error.code and error.message of an error",
                    )
                )
        if quick_log.outputs is None or node.id not in ports:
            continue
        outputs = {port.id for port in ports[node.id] if port.kind == "output"}
        for index, name in enumerate(quick_log.outputs):
            if name not in outputs:
                problems.append(
                    (
                        f"nodes.{node.id}.quick_log.outputs.{index}",
                        f"This step has no output '{name}'",
                    )
                )
    return problems
