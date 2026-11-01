"""`entry_graph`: the branch of a workflow that one trigger starts, and nothing else."""

from uuid import UUID, uuid4

import pytest

from app.workflows.contracts.io import Binding, LiteralValue
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.triggers import MANUAL, WEBHOOK, entry_graph


def _node(definition_id: str) -> NodeInstance:
    return NodeInstance(
        id=uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config={},
        layout=NodePosition(x=0, y=0),
    )


def _edge(source: NodeInstance, target: NodeInstance) -> Edge:
    return Edge(
        id=uuid4(),
        source_node_id=source.id,
        source_port="out",
        target_node_id=target.id,
        target_port="in",
    )


def _bound(target: NodeInstance) -> Binding:
    return Binding(target_node_id=target.id, target_field="value", source=LiteralValue(value=1))


def _ids(nodes: list[NodeInstance] | tuple[NodeInstance, ...]) -> set[UUID]:
    return {node.id for node in nodes}


class TestTheBranchOneTriggerStarts:
    def _two_roots(self) -> tuple[WorkflowGraph, dict[str, NodeInstance]]:
        """A manual root feeding `m`, and a webhook root feeding a diamond `a`/`b` -> `join`."""
        manual, webhook = _node(MANUAL), _node(WEBHOOK)
        m, a, b, join = _node("debug.echo"), _node("debug.echo"), _node("debug.echo"), _node("x")
        graph = WorkflowGraph(
            entry_node_id=manual.id,
            nodes=(manual, webhook, m, a, b, join),
            edges=(
                _edge(manual, m),
                _edge(webhook, a),
                _edge(webhook, b),
                _edge(a, join),
                _edge(b, join),
            ),
            bindings=(_bound(m), _bound(a), _bound(join)),
        )
        named = {"manual": manual, "webhook": webhook, "m": m, "a": a, "b": b, "join": join}
        return graph, named

    def test_a_node_reached_by_two_paths_is_kept_once(self) -> None:
        graph, n = self._two_roots()

        branch = entry_graph(graph, n["webhook"].id)

        assert branch.entry_node_id == n["webhook"].id
        assert _ids(branch.nodes) == _ids([n["webhook"], n["a"], n["b"], n["join"]])
        assert len(branch.nodes) == 4

    def test_the_other_root_and_everything_it_feeds_are_dropped_with_their_wiring(self) -> None:
        graph, n = self._two_roots()

        branch = entry_graph(graph, n["webhook"].id)

        assert n["manual"].id not in _ids(branch.nodes) and n["m"].id not in _ids(branch.nodes)
        assert len(branch.edges) == 4
        assert {edge.source_node_id for edge in branch.edges} <= _ids(branch.nodes)
        assert {binding.target_node_id for binding in branch.bindings} == {
            n["a"].id,
            n["join"].id,
        }
        assert list(branch.scopes) == []

    def test_the_default_entry_keeps_only_its_own_branch_too(self) -> None:
        graph, n = self._two_roots()

        branch = entry_graph(graph, n["manual"].id)

        assert _ids(branch.nodes) == _ids([n["manual"], n["m"]])
        assert [binding.target_node_id for binding in branch.bindings] == [n["m"].id]

    def test_a_node_that_is_not_a_trigger_root_cannot_be_chosen(self) -> None:
        graph, n = self._two_roots()

        with pytest.raises(GraphValidationError):
            entry_graph(graph, n["a"].id)
