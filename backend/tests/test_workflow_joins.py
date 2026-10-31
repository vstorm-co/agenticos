"""Run conditions: when a step runs, as a condition on earlier steps' choices.

The same graphs and the same answers as `validation/joins.test.ts`, so a change to one
analysis fails the other's tests. Each case asserts which steps can run together, what
precedes the join, and whether the wires into it run whenever it does.
"""

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.workflows.contracts.policy import NodePolicy
from app.workflows.graph import joins
from app.workflows.graph.joins import (
    ALWAYS,
    MAX_TERMS,
    RunCondition,
    WireState,
    any_pair_runs_together,
    can_run_together,
    covers,
    evaluate_join,
    runs_whenever,
    wire_condition,
    wire_runs_whenever,
)
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import analyze_graph


def _node(
    label: str,
    definition_id: str = "debug.echo",
    config: dict[str, Any] | None = None,
    *,
    routed: bool = False,
) -> NodeInstance:
    return NodeInstance(
        id=uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config={"message": "hi"} if config is None else config,
        layout=NodePosition(x=0, y=0),
        label=label,
        policy=NodePolicy(on_error="route") if routed else None,
    )


def _if(label: str) -> NodeInstance:
    return _node(label, "logic.if", {"condition": "value"})


def _switch(label: str, *names: str) -> NodeInstance:
    rules = [{"name": name, "condition": "value"} for name in names]
    return _node(label, "logic.switch", {"rules": rules})


def _split(label: str, *names: str) -> NodeInstance:
    return _node(label, "logic.split", {"branches": [{"name": name} for name in names]})


@dataclass
class Built:
    graph: WorkflowGraph
    by_label: dict[str, NodeInstance]

    def __post_init__(self) -> None:
        self.analysis = analyze_graph(self.graph)

    def id(self, label: str) -> UUID:
        return self.by_label[label].id

    def together(self, first: str, second: str) -> bool:
        return can_run_together(self.analysis, self.id(first), self.id(second))

    def precedes(self, join: str) -> set[str]:
        labels = {node.id: label for label, node in self.by_label.items()}
        return {labels[step] for step in self.analysis.precede[self.id(join)]}

    def wires_together(self, join: str) -> bool:
        return any_pair_runs_together(self.analysis, self.id(join))

    def wires_whenever(self, join: str) -> dict[str, bool]:
        labels = {node.id: label for label, node in self.by_label.items()}
        return {
            f"{labels[wire.source_node_id]}.{wire.source_port}": wire_runs_whenever(
                self.analysis, self.id(join), wire
            )
            for wire in self.analysis.incoming[self.id(join)]
        }

    def condition(self, label: str) -> RunCondition:
        return self.analysis.conditions[self.id(label)]


def _build(*nodes: NodeInstance, edges: list[tuple[str, str, str]]) -> Built:
    by_label = {node.label or "": node for node in nodes}
    graph = WorkflowGraph(
        entry_node_id=nodes[0].id,
        nodes=nodes,
        edges=tuple(
            Edge(
                id=uuid4(),
                source_node_id=by_label[source].id,
                source_port=port,
                target_node_id=by_label[target].id,
                target_port="in",
            )
            for source, port, target in edges
        ),
    )
    return Built(graph, by_label)


def _entry(label: str = "start") -> NodeInstance:
    return _node(label)


def split2() -> Built:
    return _build(
        _entry(),
        _split("S", "a", "b"),
        _node("A"),
        _node("B"),
        _node("J"),
        edges=[
            ("start", "out", "S"),
            ("S", "a", "A"),
            ("S", "b", "B"),
            ("A", "out", "J"),
            ("B", "out", "J"),
        ],
    )


def if_else() -> Built:
    return _build(
        _entry(),
        _if("I"),
        _node("A"),
        _node("B"),
        _node("J"),
        edges=[
            ("start", "out", "I"),
            ("I", "true", "A"),
            ("I", "false", "B"),
            ("A", "out", "J"),
            ("B", "out", "J"),
        ],
    )


def mixed() -> Built:
    return _build(
        _entry(),
        _if("I"),
        _node("A"),
        _node("B"),
        _node("C"),
        _node("J"),
        edges=[
            ("start", "out", "I"),
            ("I", "true", "A"),
            ("I", "true", "B"),
            ("I", "false", "C"),
            ("A", "out", "J"),
            ("B", "out", "J"),
            ("C", "out", "J"),
        ],
    )


def nested() -> Built:
    return _build(
        _entry(),
        _split("S", "a", "b"),
        _if("I"),
        _node("A"),
        _node("B"),
        _node("C"),
        _node("J"),
        edges=[
            ("start", "out", "S"),
            ("S", "a", "I"),
            ("I", "true", "A"),
            ("I", "false", "B"),
            ("S", "b", "C"),
            ("A", "out", "J"),
            ("B", "out", "J"),
            ("C", "out", "J"),
        ],
    )


def common() -> Built:
    return _build(
        _entry(),
        _if("I"),
        _node("K"),
        _node("A"),
        _node("J"),
        edges=[
            ("start", "out", "I"),
            ("I", "true", "K"),
            ("I", "false", "K"),
            ("K", "out", "J"),
            ("I", "true", "A"),
            ("A", "out", "J"),
        ],
    )


def routed_leg() -> Built:
    return _build(
        _entry(),
        _split("S", "a", "b"),
        _node("A", routed=True),
        _node("H", "error.handle", {}),
        _node("B"),
        _node("J"),
        edges=[
            ("start", "out", "S"),
            ("S", "a", "A"),
            ("A", "out", "J"),
            ("A", "error", "H"),
            ("H", "default", "J"),
            ("S", "b", "B"),
            ("B", "out", "J"),
        ],
    )


def fanout_partial() -> Built:
    return _build(
        _entry(),
        _switch("W", "r"),
        _node("A"),
        _if("B"),
        _node("J"),
        edges=[
            ("start", "out", "W"),
            ("W", "r", "A"),
            ("A", "out", "J"),
            ("W", "r", "B"),
            ("B", "true", "J"),
        ],
    )


def straight() -> Built:
    return _build(
        _entry(),
        _switch("S", "p", "q"),
        _node("J"),
        edges=[("start", "out", "S"), ("S", "p", "J"), ("S", "q", "J")],
    )


def reached_from_both_ports() -> Built:
    """Round 1, graph b: `X.true -> P -> T`, `X.false -> T`, `T -> J`, `P -> J`."""
    return _build(
        _entry(),
        _if("X"),
        _node("P"),
        _node("T"),
        _node("J"),
        edges=[
            ("start", "out", "X"),
            ("X", "true", "P"),
            ("P", "out", "T"),
            ("X", "false", "T"),
            ("T", "out", "J"),
            ("P", "out", "J"),
        ],
    )


def skipped_by_one_port() -> Built:
    """Round 1, graph c: `X.true -> t`, `X.false -> Y -> t`, `t -> T`, `X.true -> A`; `A, T -> J`."""
    return _build(
        _entry(),
        _if("X"),
        _node("t"),
        _node("Y"),
        _node("T"),
        _node("A"),
        _node("J"),
        edges=[
            ("start", "out", "X"),
            ("X", "true", "t"),
            ("X", "false", "Y"),
            ("Y", "out", "t"),
            ("t", "out", "T"),
            ("X", "true", "A"),
            ("A", "out", "J"),
            ("T", "out", "J"),
        ],
    )


def outputs_after_both_ports() -> Built:
    """Round 1, graph a: `X.true -> P -> {O1, T}`, `X.false -> T -> O2`."""
    return _build(
        _entry(),
        _if("X"),
        _node("P"),
        _node("T"),
        _node("O1"),
        _node("O2"),
        edges=[
            ("start", "out", "X"),
            ("X", "true", "P"),
            ("P", "out", "O1"),
            ("P", "out", "T"),
            ("X", "false", "T"),
            ("T", "out", "O2"),
        ],
    )


def nested_with_shared_else() -> Built:
    """`X.true -> Y`, `Y.true -> A`, `Y.false -> T`, `X.false -> T`; `A, T -> J`."""
    return _build(
        _entry(),
        _if("X"),
        _if("Y"),
        _node("A"),
        _node("T"),
        _node("J"),
        edges=[
            ("start", "out", "X"),
            ("X", "true", "Y"),
            ("Y", "true", "A"),
            ("Y", "false", "T"),
            ("X", "false", "T"),
            ("A", "out", "J"),
            ("T", "out", "J"),
        ],
    )


def switch_sharing_a_step() -> Built:
    """`S.a -> s`, `S.b -> s`, `S.otherwise -> C`; `s, C -> J`."""
    return _build(
        _entry(),
        _switch("S", "a", "b"),
        _node("s"),
        _node("C"),
        _node("J"),
        edges=[
            ("start", "out", "S"),
            ("S", "a", "s"),
            ("S", "b", "s"),
            ("S", "otherwise", "C"),
            ("s", "out", "J"),
            ("C", "out", "J"),
        ],
    )


def unwired_otherwise() -> Built:
    return _build(
        _entry(),
        _switch("S", "r1", "r2"),
        _node("A"),
        _node("B"),
        _node("J"),
        edges=[
            ("start", "out", "S"),
            ("S", "r1", "A"),
            ("S", "r2", "B"),
            ("A", "out", "J"),
            ("B", "out", "J"),
        ],
    )


def switch_fully_merged() -> Built:
    return _build(
        _entry(),
        _switch("S", "r1", "r2"),
        _node("A1"),
        _node("A2"),
        _node("A3"),
        _node("J"),
        edges=[
            ("start", "out", "S"),
            ("S", "r1", "A1"),
            ("S", "r2", "A2"),
            ("S", "otherwise", "A3"),
            ("A1", "out", "J"),
            ("A2", "out", "J"),
            ("A3", "out", "J"),
        ],
    )


def routed_error_port() -> Built:
    """`R` routes its errors: `R.out -> A`, `R.error -> H -> B`; `A, B -> J`."""
    return _build(
        _entry(),
        _node("R", routed=True),
        _node("A"),
        _node("H", "error.handle", {}),
        _node("B"),
        _node("J"),
        edges=[
            ("start", "out", "R"),
            ("R", "out", "A"),
            ("R", "error", "H"),
            ("H", "default", "B"),
            ("A", "out", "J"),
            ("B", "out", "J"),
        ],
    )


def loop_graph(parallel: bool = True) -> Built:
    nodes = [
        _entry(),
        _node("F", "control.foreach", {}),
        _node("item", "loop.item", {}),
        _node("X"),
        _node("Y"),
        _node("J"),
        _node("done", "loop.yield", {}),
        _node("after"),
    ]
    edges = [
        ("start", "out", "F"),
        ("F", "body", "item"),
        ("F", "done", "after"),
        ("J", "out", "done"),
    ]
    if parallel:
        nodes.insert(3, _split("S", "a", "b"))
        edges += [
            ("item", "out", "S"),
            ("S", "a", "X"),
            ("S", "b", "Y"),
            ("X", "out", "J"),
            ("Y", "out", "J"),
        ]
    else:
        edges += [("item", "out", "X"), ("X", "out", "Y"), ("Y", "out", "J")]
    return _build(*nodes, edges=edges)


def _chain_parts(layers: int) -> tuple[list[NodeInstance], list[tuple[str, str, str]]]:
    nodes = [_entry()]
    edges: list[tuple[str, str, str]] = []
    previous = "start"
    for layer in range(layers):
        nodes += [_switch(f"S{layer}", "a", "b"), _node(f"M{layer}")]
        edges += [
            (previous, "out", f"S{layer}"),
            (f"S{layer}", "a", f"M{layer}"),
            (f"S{layer}", "b", f"M{layer}"),
        ]
        previous = f"M{layer}"
    return nodes, edges


def switch_chain(layers: int) -> Built:
    """`layers` Switches in a row, each with two wired ways and an unwired `otherwise`."""
    nodes, edges = _chain_parts(layers)
    return _build(*nodes, edges=edges)


def test_two_legs_of_a_split_run_together_and_both_precede_the_join() -> None:
    built = split2()
    assert built.together("A", "B")
    assert built.wires_together("J")
    assert {"A", "B", "S"} <= built.precedes("J")
    assert built.wires_whenever("J") == {"A.out": True, "B.out": True}


def test_the_two_arms_of_an_if_never_run_together_and_neither_precedes_their_rejoin() -> None:
    built = if_else()
    assert not built.together("A", "B")
    assert built.together("A", "A")
    assert not built.wires_together("J")
    assert built.precedes("J") == {"J", "I", "start"}
    assert built.condition("J").terms == {frozenset()}
    assert built.wires_whenever("J") == {"A.out": False, "B.out": False}


def test_a_mixed_group_runs_its_fan_out_together_and_apart_from_the_other_port() -> None:
    built = mixed()
    assert built.together("A", "B")
    assert not built.together("A", "C")
    assert built.wires_together("J")
    assert built.precedes("J").isdisjoint({"A", "B", "C"})


def test_a_split_beside_an_if_runs_the_arms_of_the_if_apart_and_the_other_leg_with_each() -> None:
    built = nested()
    assert not built.together("A", "B")
    assert built.together("A", "C") and built.together("B", "C")
    assert built.precedes("J") >= {"C", "S", "I"}
    assert built.precedes("J").isdisjoint({"A", "B"})


def test_a_step_reached_from_both_ports_precedes_the_join_and_its_sibling_arm_does_not() -> None:
    built = common()
    assert built.together("K", "A")
    assert "K" in built.precedes("J") and "A" not in built.precedes("J")
    assert built.wires_whenever("J") == {"K.out": True, "A.out": False}


def test_a_routed_leg_runs_with_its_handler_but_its_two_wires_never_together() -> None:
    built = routed_leg()
    assert built.together("A", "H")
    assert built.precedes("J") >= {"A", "B", "S"}
    assert "H" not in built.precedes("J")
    assert built.wires_together("J")
    assert built.wires_whenever("J") == {"A.out": False, "H.default": False, "B.out": True}


def test_a_fan_out_from_one_port_runs_together_and_both_steps_precede_the_join() -> None:
    built = fanout_partial()
    assert built.together("A", "B")
    assert {"A", "B"} <= built.precedes("J")
    assert built.wires_whenever("J") == {"A.out": True, "B.true": False}


def test_two_ports_wired_straight_into_a_join_never_run_together() -> None:
    built = straight()
    assert not built.wires_together("J")
    assert built.precedes("J") == {"J", "S", "start"}


def test_graph_b_a_step_reached_from_both_ports_runs_with_the_arm_before_it() -> None:
    built = reached_from_both_ports()
    assert built.together("P", "T")
    assert built.wires_together("J")
    assert "T" in built.precedes("J") and "P" not in built.precedes("J")


def test_graph_c_a_leg_skipped_by_one_port_does_not_precede_the_join() -> None:
    built = skipped_by_one_port()
    assert built.together("A", "T")
    assert "T" in built.precedes("J") and "A" not in built.precedes("J")


def test_graph_a_two_outputs_after_a_step_reached_from_both_ports_run_together() -> None:
    built = outputs_after_both_ports()
    assert built.together("O1", "O2")


def test_a_nested_if_with_a_shared_else_never_runs_its_two_branches_together() -> None:
    built = nested_with_shared_else()
    assert not built.together("A", "T")
    assert not built.wires_together("J")
    assert built.condition("J").terms == {frozenset()}
    assert built.precedes("J") == {"J", "X", "start"}


def test_a_switch_whose_cases_share_a_step_never_runs_it_with_the_other_way_out() -> None:
    built = switch_sharing_a_step()
    assert not built.together("s", "C")
    assert not built.wires_together("J")
    assert built.condition("J").terms == {frozenset()}


def test_an_unwired_way_out_stops_a_branch_from_running_whenever_the_join_does() -> None:
    built = unwired_otherwise()
    assert not built.wires_together("J")
    assert built.wires_whenever("J") == {"A.out": False, "B.out": False}
    assert built.condition("J").terms != {frozenset()}


def test_every_way_out_of_a_three_port_switch_folds_into_always() -> None:
    built = switch_fully_merged()
    assert built.condition("J").terms == {frozenset()}
    assert built.condition("A1").terms != {frozenset()}


def test_a_routed_error_port_splits_the_run_in_two() -> None:
    built = routed_error_port()
    assert not built.together("A", "H")
    assert not built.together("A", "B")
    assert not built.wires_together("J")
    assert built.condition("J").terms == {frozenset()}
    assert built.precedes("J") == {"J", "R", "start"}


def test_a_loop_body_is_analysed_against_the_loop() -> None:
    built = loop_graph()
    assert built.together("X", "Y")
    assert built.precedes("item") == {"item", "F"}
    assert built.precedes("J") >= {"X", "Y", "S", "F", "item"}
    assert "start" not in built.precedes("J")
    assert built.id("after") in built.analysis.precede
    assert built.wires_whenever("J") == {"X.out": True, "Y.out": True}
    # Steps in the body and after the loop are compared where they meet.
    assert built.together("X", "after") and built.together("after", "X")
    inside = loop_graph(parallel=False)
    assert inside.together("X", "after")


def test_a_wire_from_the_loop_itself_is_always_live_inside_its_body() -> None:
    built = loop_graph()
    wire = built.analysis.incoming[built.id("item")][0]
    condition = wire_condition(built.analysis, built.id("item"), wire)
    assert condition is not None and condition.terms == {frozenset()}
    assert wire_runs_whenever(built.analysis, built.id("item"), wire)


def test_a_step_runs_whenever_a_later_one_does_only_if_it_comes_before_it() -> None:
    built = if_else()
    analysis = built.analysis
    assert runs_whenever(analysis, built.id("I"), built.id("J"))
    assert not runs_whenever(analysis, built.id("J"), built.id("I"))
    assert not runs_whenever(analysis, built.id("A"), built.id("J"))
    assert runs_whenever(analysis, built.id("A"), built.id("A"))


def test_a_step_runs_whenever_a_step_in_a_loop_it_encloses_does() -> None:
    built = loop_graph()
    assert runs_whenever(built.analysis, built.id("F"), built.id("X"))
    assert runs_whenever(built.analysis, built.id("start"), built.id("X"))
    assert not runs_whenever(built.analysis, built.id("X"), built.id("start"))


def test_a_condition_past_the_cap_is_unknown_and_never_accepted() -> None:
    built = switch_chain(7)
    assert built.condition("M4").unknown is False
    assert len(built.condition("M5").terms) == 2**6 == MAX_TERMS
    assert built.condition("M5").unknown is False
    assert built.condition("M6").unknown
    assert built.condition("M6").terms == frozenset()
    last = built.id("M6")
    assert can_run_together(built.analysis, last, built.id("start"))
    assert can_run_together(built.analysis, built.id("start"), last)
    assert not runs_whenever(built.analysis, built.id("start"), last)
    assert not runs_whenever(built.analysis, last, built.id("start"))
    assert not covers(built.condition("M6"), ALWAYS)
    assert not covers(ALWAYS, built.condition("M6"))


def test_a_step_after_an_unknown_condition_is_unknown_too() -> None:
    built = switch_chain(8)
    assert built.condition("S7").unknown
    assert built.condition("M7").unknown


def _fan_in_graph(ifs: int) -> Built:
    """A 64-term step feeding `ifs` Ifs whose `true` ways all lead to one step."""
    nodes, edges = _chain_parts(6)
    nodes.append(_node("T"))
    for index in range(ifs):
        nodes.append(_if(f"I{index}"))
        edges += [("M5", "out", f"I{index}"), (f"I{index}", "true", "T")]
    return _build(*nodes, edges=edges)


def _long_chain_graph(steps: int, *, branching: bool) -> Built:
    """A 64-term step followed by `steps` steps in a row (Ifs wired by `true` when `branching`)."""
    nodes, edges = _chain_parts(6)
    previous = "M5"
    for index in range(steps):
        nodes.append(_if(f"C{index}") if branching else _node(f"C{index}"))
        port = "true" if branching and index > 0 else "out"
        edges.append((previous, port, f"C{index}"))
        previous = f"C{index}"
    return _build(*nodes, edges=edges)


def test_a_fan_in_of_many_wide_conditions_is_analysed_in_bounded_time_and_refused_safely() -> None:
    started = time.perf_counter()
    built = _fan_in_graph(450)
    assert len(built.graph.nodes) <= 500 and len(built.graph.edges) <= 2000
    assert time.perf_counter() - started < 5
    assert built.condition("T").unknown
    assert can_run_together(built.analysis, built.id("T"), built.id("I0"))
    assert not runs_whenever(built.analysis, built.id("M5"), built.id("T"))
    assert not wire_runs_whenever(
        built.analysis, built.id("T"), built.analysis.incoming[built.id("T")][0]
    )


def test_a_long_chain_after_a_wide_condition_is_analysed_in_bounded_time() -> None:
    started = time.perf_counter()
    built = _long_chain_graph(450, branching=False)
    assert time.perf_counter() - started < 5
    assert len(built.graph.nodes) <= 500
    last = built.id("C449")
    assert built.id("M5") in built.analysis.precede[last]
    assert runs_whenever(built.analysis, built.id("C0"), last)


def test_a_long_chain_of_choices_after_a_wide_condition_is_analysed_in_bounded_time() -> None:
    started = time.perf_counter()
    built = _long_chain_graph(450, branching=True)
    assert time.perf_counter() - started < 5
    assert built.id("C449") in built.analysis.conditions


def test_a_failed_leg_skips_the_step_in_either_mode() -> None:
    for wait_for_all in (False, True):
        assert evaluate_join(["live", "failed"], wait_for_all=wait_for_all) == "skip"
        assert evaluate_join(["live", "live", "failed"], wait_for_all=wait_for_all) == "skip"
        assert evaluate_join(["dead", "failed"], wait_for_all=wait_for_all) == "skip"


def test_a_step_in_a_loop_does_not_run_whenever_a_step_after_the_loop() -> None:
    built = loop_graph()
    analysis = built.analysis
    assert not runs_whenever(analysis, built.id("X"), built.id("after"))
    assert not runs_whenever(analysis, built.id("J"), built.id("after"))
    assert runs_whenever(analysis, built.id("F"), built.id("after"))
    assert runs_whenever(analysis, built.id("start"), built.id("after"))
    assert runs_whenever(analysis, built.id("F"), built.id("X"))
    assert runs_whenever(analysis, built.id("item"), built.id("X"))


def test_a_graph_with_an_unknown_step_is_analysed_without_raising() -> None:
    built = _build(
        _entry(),
        _split("S", "a", "b"),
        _node("U", "no.such.step", {}, routed=True),
        _node("B"),
        _node("J"),
        edges=[
            ("start", "out", "S"),
            ("S", "a", "U"),
            ("S", "b", "B"),
            ("U", "out", "J"),
            ("B", "out", "J"),
        ],
    )
    assert built.together("U", "B")
    assert built.wires_together("J")
    assert not built.wires_whenever("J")["U.out"]


def test_a_cyclic_graph_has_no_conditions() -> None:
    built = _build(
        _entry(),
        _node("A"),
        _node("B"),
        edges=[("start", "out", "A"), ("A", "out", "B"), ("B", "out", "A")],
    )
    assert built.analysis.conditions == {}
    assert built.analysis.precede == {}
    assert not built.together("A", "B")


def test_a_step_nothing_leads_to_has_no_condition_and_runs_with_nothing() -> None:
    built = _build(
        _entry(),
        _if("I"),
        _node("A"),
        _node("Z"),
        _node("J"),
        edges=[("start", "out", "I"), ("I", "true", "A"), ("A", "out", "J"), ("Z", "out", "J")],
    )
    analysis = built.analysis
    assert built.id("Z") not in analysis.conditions
    assert built.id("Z") not in analysis.precede
    assert not built.together("A", "Z") and not built.together("Z", "A")
    assert not runs_whenever(analysis, built.id("Z"), built.id("J"))
    assert not runs_whenever(analysis, built.id("A"), built.id("Z"))
    wire = next(w for w in analysis.incoming[built.id("J")] if w.source_node_id == built.id("Z"))
    assert wire_condition(analysis, built.id("J"), wire) is None
    assert not wire_runs_whenever(analysis, built.id("J"), wire)
    assert not built.wires_together("J")


def test_two_edges_from_one_port_are_one_wire() -> None:
    built = _build(
        _entry(),
        _node("A"),
        _node("J"),
        edges=[("start", "out", "A"), ("A", "out", "J"), ("A", "out", "J")],
    )
    assert len(built.analysis.incoming[built.id("J")]) == 1


def test_an_edge_from_a_step_that_is_not_in_the_graph_is_ignored() -> None:
    built = split2()
    ghost = Edge(
        id=uuid4(),
        source_node_id=uuid4(),
        source_port="out",
        target_node_id=built.id("J"),
        target_port="in",
    )
    graph = built.graph.model_copy(update={"edges": (*built.graph.edges, ghost)})
    assert len(analyze_graph(graph).incoming[built.id("J")]) == 2


def test_an_edge_crossing_into_a_loop_body_is_not_a_way_in() -> None:
    built = loop_graph(parallel=False)
    crossing = Edge(
        id=uuid4(),
        source_node_id=built.id("start"),
        source_port="out",
        target_node_id=built.id("Y"),
        target_port="in",
    )
    graph = built.graph.model_copy(update={"edges": (*built.graph.edges, crossing)})
    analysis = analyze_graph(graph)
    assert built.id("Y") in analysis.conditions


def test_a_merge_rule_needs_every_port_of_a_step_with_ports_unknown_to_it() -> None:
    built = _build(
        _entry(),
        _node("U", "no.such.step", {}, routed=True),
        _node("A"),
        _node("B"),
        _node("J"),
        edges=[
            ("start", "out", "U"),
            ("U", "out", "A"),
            ("U", "error", "B"),
            ("A", "out", "J"),
            ("B", "out", "J"),
        ],
    )
    assert built.condition("J").terms != {frozenset()}


def test_a_join_runs_when_any_wire_is_live_and_is_skipped_when_none_is() -> None:
    assert evaluate_join(["live", "dead"], wait_for_all=False) == "run"
    assert evaluate_join(["live", "live"], wait_for_all=False) == "run"
    assert evaluate_join(["dead", "dead"], wait_for_all=False) == "skip"
    assert evaluate_join(["dead", "failed"], wait_for_all=False) == "skip"


def test_a_merge_waiting_for_all_needs_every_wire_live() -> None:
    assert evaluate_join(["live", "live"], wait_for_all=True) == "run"
    assert evaluate_join(["dead", "dead"], wait_for_all=True) == "skip"
    partial: list[WireState] = ["live", "dead"]
    assert evaluate_join(partial, wait_for_all=True) == "incomplete"


def test_conditions_are_unknown_once_the_build_budget_is_spent(monkeypatch) -> None:
    monkeypatch.setattr(joins, "BUILD_BUDGET", 10)
    built = switch_chain(4)
    assert built.condition("M3").unknown
    assert can_run_together(built.analysis, built.id("M3"), built.id("start"))
    assert not runs_whenever(built.analysis, built.id("start"), built.id("M3"))


def test_questions_fall_back_once_the_question_budget_is_spent(monkeypatch) -> None:
    monkeypatch.setattr(joins, "QUESTION_BUDGET", 0)
    built = if_else()
    assert can_run_together(built.analysis, built.id("A"), built.id("B"))
    assert built.wires_together("J")
    assert built.wires_whenever("J") == {"A.out": False, "B.out": False}


def test_a_condition_comparison_without_a_budget_is_exact() -> None:
    built = if_else()
    a, b = built.condition("A"), built.condition("B")
    assert not covers(a, b) and not covers(b, a)
    assert covers(a, a) and covers(ALWAYS, a) and not covers(a, ALWAYS)
    assert not joins._may_hold_together(a, b)
    assert joins._may_hold_together(a, ALWAYS)


def test_the_same_comparison_is_answered_from_memory_the_second_time(monkeypatch) -> None:
    built = if_else()
    wire = built.analysis.incoming[built.id("J")][0]
    assert not wire_runs_whenever(built.analysis, built.id("J"), wire)
    monkeypatch.setattr(joins, "covers", lambda *_args: pytest.fail("asked twice"))
    assert not wire_runs_whenever(built.analysis, built.id("J"), wire)


def test_a_fold_leaves_the_other_choices_of_its_terms_alone() -> None:
    built = _build(
        _entry(),
        _if("I"),
        _switch("S", "r1", "r2"),
        _node("A1"),
        _node("A2"),
        _node("A3"),
        _node("J"),
        edges=[
            ("start", "out", "I"),
            ("I", "true", "S"),
            ("S", "r1", "A1"),
            ("S", "r2", "A2"),
            ("S", "otherwise", "A3"),
            ("A1", "out", "J"),
            ("A2", "out", "J"),
            ("A3", "out", "J"),
        ],
    )
    assert built.condition("J").terms == {frozenset({(built.id("I"), "true")})}
