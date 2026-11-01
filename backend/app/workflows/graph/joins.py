"""When a step runs, as a condition on the choices earlier steps make.

The executor runs a step once every step before it has settled, if **any** incoming wire
is live. So a step's *run condition* is the OR, over its incoming edges, of the source's
condition AND the edge's literal: `(source, port)` when the source takes one way out of
several (`branches_exclusively` - an If, a Switch, a decision, a step that routes its
errors), nothing otherwise. Choices at one such step exclude each other; choices at
different steps are independent. Each scope (the top level, each loop body) is analysed on
its own, with a body rooted at its loop.

A condition is a set of *terms*, each a set of `(step, port)` choices, read as their
disjunction. It is kept small by two rules applied to a fixed point: if terms
`t + {D: p}` exist for every output port of D, they are the single term `t` (an unwired
port blocks this, rightly: that way out can be taken and reaches nothing); and a term that
contains another is dropped. Past `MAX_TERMS` - or when an analysis has spent its work budget - the condition is
`unknown`, which answers
"can run together" with yes and "runs whenever" with no, so the rules built on them refuse
rather than accept.

Every question the publish rules, the binding rule and the dispatcher ask comes from the
conditions: `can_run_together` (some term of each is compatible - exact), `runs_whenever`
(every term of the later has a term of the earlier inside it - sound, and conservative), and
the same two for the wires into one step. `precede` is the steps that run whenever a step
does. The mirror is `validation/joins.ts`.

The module is pure: no database, no registry writes. It never raises on a graph
`WorkflowGraph` accepts: a step whose definition does not resolve counts as one that
branches non-exclusively, and a step nothing reaches has no condition at all.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from app.workflows.contracts.definition import NodeDefinition
from app.workflows.graph.model import NodeInstance, WorkflowGraph

WireState = Literal["live", "dead", "failed"]
"""`failed`: the source failed and does not route its errors - only reachable in a
loop under `collect`."""
JoinVerdict = Literal["run", "skip", "incomplete"]

MAX_TERMS = 64
"""The most terms a condition keeps before it is `unknown`."""
BUILD_BUDGET = 4_000_000
"""Element operations one analysis may spend building conditions and precede sets."""
QUESTION_BUDGET = 1_000_000
"""Element operations one analysis may spend answering questions afterwards."""

Term = frozenset[tuple[UUID, str]]


@dataclass(frozen=True, slots=True)
class JoinWire:
    """One edge into a step, by the edge's own id."""

    edge_id: UUID
    source_node_id: UUID
    source_port: str


@dataclass(frozen=True, slots=True)
class RunCondition:
    """When a step runs: the disjunction of `terms`, each a set of `(step, port)` choices.

    `unknown` is set when the condition outgrew `MAX_TERMS`; `terms` is then empty.
    """

    terms: frozenset[Term]
    unknown: bool = False


ALWAYS = RunCondition(frozenset({frozenset()}))
UNKNOWN = RunCondition(frozenset(), unknown=True)


class _Spent(Exception):
    """An analysis ran out of its work budget; what it was computing is `unknown`."""


class _Budget:
    """A count of element operations left, so no graph costs unbounded work."""

    def __init__(self, left: int) -> None:
        self.left = left

    def take(self, cost: int) -> None:
        self.left -= cost
        if self.left < 0:
            raise _Spent


@dataclass(frozen=True, slots=True)
class GraphAnalysis:
    """What the publish rules and the dispatcher both need to know about one graph.

    `conditions` holds a step only when something reaches it, in its own scope; `incoming`
    its distinct wires; `precede` the steps that run whenever it does and come before it,
    itself included.
    """

    graph: WorkflowGraph
    definitions: dict[UUID, NodeDefinition | None]
    node_scope: dict[UUID, UUID]
    exclusive: frozenset[UUID]
    incoming: dict[UUID, tuple[JoinWire, ...]]
    conditions: dict[UUID, RunCondition]
    precede: dict[UUID, frozenset[UUID]]
    _ancestors: dict[UUID, frozenset[UUID]] = field(default_factory=dict, repr=False, compare=False)
    _questions: _Budget = field(
        default_factory=lambda: _Budget(QUESTION_BUDGET), repr=False, compare=False
    )
    _answers: dict[tuple[RunCondition, RunCondition], bool] = field(
        default_factory=dict, repr=False, compare=False
    )


def branches_exclusively(node: NodeInstance, definition: NodeDefinition | None) -> bool:
    """Whether exactly one of this node's output ports is ever taken per run.

    A definition says so itself with `exclusive_branches` - `logic.if` takes
    `true` or `false`, a decision step one of its answers or `unsure` - and a
    node that routes its errors leaves by `out` or by `error`, never both.
    """
    return node.routes_errors or (definition is not None and definition.exclusive_branches)


def at_level_of(node_id: UUID, level: UUID | None, node_scope: Mapping[UUID, UUID]) -> UUID | None:
    """`node_id`, or the loop enclosing it that sits directly in scope `level`."""
    current: UUID | None = node_id
    while current is not None and node_scope.get(current) != level:
        current = node_scope.get(current)
    return current


def _output_ports(
    graph: WorkflowGraph, definitions: Mapping[UUID, NodeDefinition | None]
) -> dict[UUID, tuple[str, ...]]:
    """Each resolvable node's output port ids, in declared order, `error` last when routed."""
    # Imported here: `validate` imports this module.
    from app.workflows.graph.validate import instance_ports

    ports = instance_ports(graph, dict(definitions))
    return {
        node_id: tuple(port.id for port in node_ports if port.kind == "output")
        for node_id, node_ports in ports.items()
    }


# Conditions


def _absorb(terms: set[Term], budget: _Budget) -> set[Term]:
    """`terms` without any that contains another."""
    kept: list[Term] = []
    for term in sorted(terms, key=len):
        for smaller in kept:
            budget.take(len(smaller) + 1)
            if smaller <= term:
                break
        else:
            kept.append(term)
    return set(kept)


def _merge_ports(
    terms: set[Term], ports: Mapping[UUID, tuple[str, ...]], budget: _Budget
) -> set[Term] | None:
    """`terms` with every set of terms that covers all of a step's ports folded into one.

    Only a step whose every port appears somewhere can fold, so the rest are not looked at.
    None when there is nothing to fold.
    """
    seen: dict[UUID, set[str]] = {}
    for term in terms:
        budget.take(len(term) + 1)
        for step, port in term:
            seen.setdefault(step, set()).add(port)
    candidates = {step for step, ways in seen.items() if ways == set(ports.get(step, ()))}
    if not candidates:
        return None
    taken: dict[tuple[UUID, Term], set[str]] = {}
    for term in terms:
        for step, port in term:
            if step in candidates:
                budget.take(len(term) + 1)
                taken.setdefault((step, term - {(step, port)}), set()).add(port)
    folded = {
        (step, rest) for (step, rest), ways in taken.items() if ways == set(ports.get(step, ()))
    }
    if not folded:
        return None
    result: set[Term] = set()
    for term in terms:
        budget.take(len(term) * len(term) + 1)
        if not any(
            (step, term - {(step, port)}) in folded for step, port in term if step in candidates
        ):
            result.add(term)
    return result | {rest for _step, rest in folded}


def _normalise(
    terms: set[Term], ports: Mapping[UUID, tuple[str, ...]], budget: _Budget
) -> RunCondition:
    """The condition of `terms` (at most `MAX_TERMS`), folded and absorbed to a fixed point; `UNKNOWN` once the budget is spent."""
    try:
        current = _absorb(terms, budget)
        while True:
            merged = _merge_ports(current, ports, budget)
            if merged is None:
                return RunCondition(frozenset(current))
            current = _absorb(merged, budget)
    except _Spent:
        pass
    return UNKNOWN


def _either(
    conditions: Sequence[RunCondition], ports: Mapping[UUID, tuple[str, ...]], budget: _Budget
) -> RunCondition:
    """The condition under which any of `conditions` holds; `UNKNOWN` once the terms pass the cap."""
    terms: set[Term] = set()
    for condition in conditions:
        if condition.unknown:
            return UNKNOWN
        terms |= condition.terms
        if len(terms) > MAX_TERMS:
            # Past the cap whatever they fold to: do not even try.
            return UNKNOWN
    return _normalise(terms, ports, budget)


def _both(condition: RunCondition, choice: tuple[UUID, str] | None) -> RunCondition:
    """`condition` and one more choice."""
    if choice is None or condition.unknown:
        return condition
    return RunCondition(frozenset(term | {choice} for term in condition.terms))


def _topological(members: Sequence[UUID], edges: Sequence[tuple[UUID, UUID]]) -> list[UUID]:
    """`members` in an order every edge respects; a node on a cycle is left out."""
    in_degree = dict.fromkeys(members, 0)
    successors: dict[UUID, list[UUID]] = {}
    for source, target in edges:
        successors.setdefault(source, []).append(target)
        in_degree[target] += 1
    queue = [node for node in members if in_degree[node] == 0]
    order: list[UUID] = []
    while queue:
        current = queue.pop()
        order.append(current)
        for successor in successors.get(current, ()):
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                queue.append(successor)
    return order


def covers(inner: RunCondition, outer: RunCondition, budget: _Budget | None = None) -> bool:
    """Whether `inner` holds whenever `outer` does: each term of `outer` has a term of `inner` in it.

    Cheap when `inner` is always true or equals `outer`; with a `budget`, False once it is spent.
    """
    if inner.unknown or outer.unknown:
        return False
    if frozenset() in inner.terms or inner == outer:
        return True
    try:
        for term in outer.terms:
            for small in inner.terms:
                if budget is not None:
                    budget.take(len(small) + 1)
                if small <= term:
                    break
            else:
                return False
    except _Spent:
        return False
    return True


def _compatible(first: Term, second: Term) -> bool:
    chosen = dict(second)
    return all(chosen.get(step, port) == port for step, port in first)


def _may_hold_together(
    first: RunCondition, second: RunCondition, budget: _Budget | None = None
) -> bool:
    """Whether the two can hold in one run; yes when either is unknown or the budget is spent."""
    if first.unknown or second.unknown:
        return True
    try:
        for a in first.terms:
            for b in second.terms:
                if budget is not None:
                    budget.take(len(a) + 1)
                if _compatible(a, b):
                    return True
    except _Spent:
        return True
    return False


def _distinct_wires(graph: WorkflowGraph) -> dict[UUID, tuple[JoinWire, ...]]:
    """The wires into each step: one per (source, port), edges naming a missing step left out."""
    known = {node.id for node in graph.nodes}
    seen: dict[UUID, dict[tuple[UUID, str], JoinWire]] = {}
    for edge in graph.edges:
        if edge.source_node_id in known and edge.target_node_id in known:
            seen.setdefault(edge.target_node_id, {}).setdefault(
                (edge.source_node_id, edge.source_port),
                JoinWire(edge.id, edge.source_node_id, edge.source_port),
            )
    return {target: tuple(wires.values()) for target, wires in seen.items()}


def analyse(
    graph: WorkflowGraph,
    definitions: Mapping[UUID, NodeDefinition | None],
    node_scope: Mapping[UUID, UUID],
    *,
    acyclic: bool,
) -> GraphAnalysis:
    """The run conditions, wires and precede sets of `graph`.

    A graph whose outer part is cyclic has no order to compute conditions in: they stay
    empty (the cycle is refused on its own).
    """
    ports = _output_ports(graph, definitions)
    exclusive = frozenset(
        node.id for node in graph.nodes if branches_exclusively(node, definitions.get(node.id))
    )
    analysis = GraphAnalysis(
        graph,
        dict(definitions),
        dict(node_scope),
        exclusive,
        _distinct_wires(graph),
        {},
        {},
    )
    if not acyclic:
        return analysis
    budget = _Budget(BUILD_BUDGET)
    for level in (None, *dict.fromkeys(node_scope.values())):
        _analyse_scope(analysis, ports, budget, level)
    return analysis


def _analyse_scope(
    analysis: GraphAnalysis,
    ports: Mapping[UUID, tuple[str, ...]],
    budget: _Budget,
    level: UUID | None,
) -> None:
    """Conditions, ancestors and precede sets of the steps directly in scope `level`."""
    graph = analysis.graph
    members = [node.id for node in graph.nodes if analysis.node_scope.get(node.id) == level]
    inside = set(members)
    sources: dict[UUID, list[tuple[UUID, str]]] = {}
    for target, wires in analysis.incoming.items():
        if target in inside:
            for wire in wires:
                lifted = at_level_of(wire.source_node_id, level, analysis.node_scope)
                source = wire.source_node_id if lifted is None else lifted
                if source == level or source in inside:
                    sources.setdefault(target, []).append((source, wire.source_port))
    order = _topological(
        members,
        [
            (source, target)
            for target, wired in sources.items()
            for source, _p in wired
            if source in inside
        ],
    )
    conditions = analysis.conditions
    for node_id in order:
        if node_id == graph.entry_node_id and level is None:
            conditions[node_id] = ALWAYS
            continue
        wires_in: list[tuple[RunCondition, bool]] = []
        for source, port in sources.get(node_id, ()):
            base = ALWAYS if source == level else conditions.get(source)
            if base is not None:
                added = source != level and source in analysis.exclusive
                wires_in.append((_both(base, (source, port) if added else None), added))
        if len(wires_in) == 1 and not wires_in[0][1]:
            # One way in that adds no choice: what runs the step before runs this one.
            conditions[node_id] = wires_in[0][0]
        elif wires_in:
            conditions[node_id] = _either([found for found, _added in wires_in], ports, budget)
    for node_id in order:
        if node_id not in conditions:
            continue
        before: set[UUID] = set()
        for source, _port in sources.get(node_id, ()):
            if source == level:
                before.add(source)
            elif source in conditions:
                before.add(source)
                before |= analysis._ancestors[source]
        analysis._ancestors[node_id] = frozenset(before)
        analysis.precede[node_id] = frozenset(
            {node_id}
            | {
                step
                for step in before
                if step == level or covers(conditions[step], conditions[node_id], budget)
            }
        )


# Questions


def _enclosing(node_id: UUID, node_scope: Mapping[UUID, UUID]) -> list[UUID]:
    """`node_id` and the loops around it, innermost first."""
    chain = [node_id]
    while chain[-1] in node_scope:
        chain.append(node_scope[chain[-1]])
    return chain


def _same_level(analysis: GraphAnalysis, first: UUID, second: UUID) -> tuple[UUID, UUID]:
    """Each step, or the loop around it, lifted to the scope both sit in."""
    levels_of_second = {
        analysis.node_scope.get(step): step for step in _enclosing(second, analysis.node_scope)
    }
    lifted = first
    while analysis.node_scope.get(lifted) not in levels_of_second:
        lifted = analysis.node_scope[lifted]
    return lifted, levels_of_second[analysis.node_scope.get(lifted)]


def can_run_together(analysis: GraphAnalysis, first: UUID, second: UUID) -> bool:
    """Whether one run can reach both steps. A step nothing reaches runs with nothing."""
    a, b = _same_level(analysis, first, second)
    if a == b:
        return True
    condition_a, condition_b = analysis.conditions.get(a), analysis.conditions.get(b)
    if condition_a is None or condition_b is None:
        return False
    return _may_hold_together(condition_a, condition_b, analysis._questions)


def _asked_covers(analysis: GraphAnalysis, inner: RunCondition, outer: RunCondition) -> bool:
    """`covers`, remembered per pair and paid for from the analysis's question budget."""
    answered = analysis._answers.get((inner, outer))
    if answered is None:
        answered = covers(inner, outer, analysis._questions)
        analysis._answers[(inner, outer)] = answered
    return answered


def runs_whenever(analysis: GraphAnalysis, step: UUID, later: UUID) -> bool:
    """Whether `step` has certainly run whenever `later` does: it comes before it and covers it.

    Only `later` is lifted, to the scope `step` sits in: a step inside a loop does not run
    whenever a step after the loop does, but the loop itself does.
    """
    scope = analysis.node_scope.get(step)
    lifted = next(
        (n for n in _enclosing(later, analysis.node_scope) if analysis.node_scope.get(n) == scope),
        None,
    )
    if lifted is None:
        return False
    if step == lifted:
        return True
    condition_a, condition_b = analysis.conditions.get(step), analysis.conditions.get(lifted)
    if condition_a is None or condition_b is None:
        return False
    return step in analysis._ancestors[lifted] and _asked_covers(analysis, condition_a, condition_b)


def wire_condition(analysis: GraphAnalysis, target: UUID, wire: JoinWire) -> RunCondition | None:
    """When `wire` is live: its source runs and leaves by its port. None if nothing reaches the source."""
    level = analysis.node_scope.get(target)
    lifted = at_level_of(wire.source_node_id, level, analysis.node_scope)
    source = wire.source_node_id if lifted is None else lifted
    base = ALWAYS if source == level else analysis.conditions.get(source)
    if base is None:
        return None
    choice = (
        (source, wire.source_port) if source != level and source in analysis.exclusive else None
    )
    return _both(base, choice)


def _wire_conditions(analysis: GraphAnalysis, target: UUID) -> dict[JoinWire, RunCondition]:
    found = {
        wire: wire_condition(analysis, target, wire) for wire in analysis.incoming.get(target, ())
    }
    return {wire: condition for wire, condition in found.items() if condition is not None}


def any_pair_runs_together(analysis: GraphAnalysis, target: UUID) -> bool:
    """Whether two of the wires into `target` can be live in one run."""
    conditions = list(_wire_conditions(analysis, target).values())
    return any(
        _may_hold_together(first, second, analysis._questions)
        for index, first in enumerate(conditions)
        for second in conditions[index + 1 :]
    )


def wire_runs_whenever(analysis: GraphAnalysis, target: UUID, wire: JoinWire) -> bool:
    """Whether `wire` is live whenever `target` runs."""
    condition, later = wire_condition(analysis, target, wire), analysis.conditions.get(target)
    return condition is not None and later is not None and _asked_covers(analysis, condition, later)


def evaluate_join(wires: Sequence[WireState], *, wait_for_all: bool) -> JoinVerdict:
    """Whether a step runs, is skipped, or - waiting for all - was reached by too few legs.

    A wire whose source failed without routing its error skips the step, in either mode:
    the failure is already the run's to report, and the step would otherwise read an output
    that is not there. Otherwise none live: skip; any live: run, unless the step waits for
    every wire and some are not live: `incomplete` (publishing makes that unreachable; it
    stays as a safety net).
    """
    if "failed" in wires or "live" not in wires:
        return "skip"
    if not wait_for_all or all(state == "live" for state in wires):
        return "run"
    return "incomplete"
