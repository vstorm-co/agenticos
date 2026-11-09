"""`0301_workflow_loop_scope` rewrites stored graphs from wired bodies to named ones (#2770)."""

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any


def _migration() -> ModuleType:
    path = Path(__file__).parents[1] / "alembic/versions/0301_workflow_loop_scope.py"
    spec = importlib.util.spec_from_file_location("workflow_loop_scope_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _id() -> str:
    return str(uuid.uuid4())


def _node(node_id: str, definition_id: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "definition_id": definition_id,
        "definition_version": 1,
        "config": {},
        "layout": {"x": 0, "y": 0},
    }


def _edge(source: str, port: str, target: str) -> dict[str, Any]:
    return {
        "id": _id(),
        "source_node_id": source,
        "source_port": port,
        "target_node_id": target,
        "target_port": "in",
    }


class _Shape:
    """entry -> loop; loop -body-> item -> inner -body-> inner_item -> inner_yield;
    inner -done-> yield; loop -done-> out."""

    def __init__(self) -> None:
        self.entry, self.loop, self.item, self.yield_ = _id(), _id(), _id(), _id()
        self.inner, self.inner_item, self.inner_yield, self.out = _id(), _id(), _id(), _id()

    def graph(self, *extra: dict[str, Any]) -> dict[str, Any]:
        return {
            "entry_node_id": self.entry,
            "nodes": [
                _node(self.entry, "core.input"),
                _node(self.loop, "control.foreach"),
                _node(self.item, "loop.item"),
                _node(self.inner, "control.foreach"),
                _node(self.inner_item, "loop.item"),
                _node(self.inner_yield, "loop.yield"),
                _node(self.yield_, "loop.yield"),
                _node(self.out, "core.output"),
            ],
            "edges": [
                _edge(self.entry, "out", self.loop),
                _edge(self.loop, "body", self.item),
                _edge(self.item, "out", self.inner),
                _edge(self.inner, "body", self.inner_item),
                _edge(self.inner_item, "out", self.inner_yield),
                _edge(self.inner, "done", self.yield_),
                _edge(self.loop, "done", self.out),
                *extra,
            ],
            "bindings": [],
            "scopes": [
                {
                    "scope_node_id": self.loop,
                    "body_node_ids": [
                        self.item,
                        self.inner,
                        self.inner_item,
                        self.inner_yield,
                        self.yield_,
                    ],
                    "entry_port": "body",
                    "exit_node_id": self.loop,
                    "exit_port": "done",
                },
                {
                    "scope_node_id": self.inner,
                    "body_node_ids": [self.inner_item, self.inner_yield],
                    "entry_port": "body",
                    "exit_node_id": self.inner,
                    "exit_port": "done",
                },
            ],
        }


def _scopes(graph: dict[str, Any]) -> dict[str, str | None]:
    return {node["id"]: node.get("scope_id") for node in graph["nodes"]}


def test_each_step_names_its_innermost_loop_and_the_body_wires_go():
    shape = _Shape()
    upgraded = _migration().upgrade_graph(shape.graph())
    assert _scopes(upgraded) == {
        shape.entry: None,
        shape.loop: None,
        shape.item: shape.loop,
        shape.inner: shape.loop,
        shape.inner_item: shape.inner,
        shape.inner_yield: shape.inner,
        shape.yield_: shape.loop,
        shape.out: None,
    }
    assert not any(edge["source_port"] == "body" for edge in upgraded["edges"])
    assert len(upgraded["edges"]) == 5
    assert all("entry_port" not in scope for scope in upgraded["scopes"])


def test_an_extra_body_wire_leaves_from_the_loop_item_instead():
    shape = _Shape()
    stray = _edge(shape.loop, "body", shape.yield_)
    upgraded = _migration().upgrade_graph(shape.graph(stray))
    rewired = next(edge for edge in upgraded["edges"] if edge["id"] == stray["id"])
    assert (rewired["source_node_id"], rewired["source_port"]) == (shape.item, "out")
    assert rewired["target_node_id"] == shape.yield_


def test_an_extra_body_wire_already_drawn_from_the_loop_item_is_dropped():
    shape = _Shape()
    graph = shape.graph(
        _edge(shape.loop, "body", shape.inner), _edge(shape.item, "out", shape.yield_)
    )
    upgraded = _migration().upgrade_graph(graph)
    pairs = [(edge["source_node_id"], edge["target_node_id"]) for edge in upgraded["edges"]]
    assert pairs.count((shape.item, shape.inner)) == 1


def test_a_body_with_no_loop_item_loses_its_body_wires_but_keeps_its_steps():
    loop, step, entry = _id(), _id(), _id()
    graph = {
        "entry_node_id": entry,
        "nodes": [
            _node(entry, "core.input"),
            _node(loop, "control.foreach"),
            _node(step, "data.map"),
        ],
        "edges": [_edge(entry, "out", loop), _edge(loop, "body", step)],
        "bindings": [],
        "scopes": [],
    }
    upgraded = _migration().upgrade_graph(graph)
    assert _scopes(upgraded)[step] == loop
    assert len(upgraded["edges"]) == 1


def test_a_graph_without_loops_is_left_as_it_was():
    entry, out = _id(), _id()
    graph = {
        "entry_node_id": entry,
        "nodes": [_node(entry, "core.input"), _node(out, "core.output")],
        "edges": [_edge(entry, "out", out)],
        "bindings": [],
        "scopes": [],
    }
    assert _migration().upgrade_graph(graph) == graph


def test_an_empty_draft_is_left_as_it_was():
    assert _migration().upgrade_graph({}) == {}


def test_upgrading_twice_changes_nothing_more():
    migration = _migration()
    once = migration.upgrade_graph(_Shape().graph())
    assert migration.upgrade_graph(once) == once


def test_downgrading_wires_each_body_from_its_loop_again():
    shape = _Shape()
    migration = _migration()
    restored = migration.downgrade_graph(migration.upgrade_graph(shape.graph()))
    assert all("scope_id" not in node for node in restored["nodes"])
    body_wires = {
        (edge["source_node_id"], edge["target_node_id"])
        for edge in restored["edges"]
        if edge["source_port"] == "body"
    }
    assert body_wires == {(shape.loop, shape.item), (shape.inner, shape.inner_item)}
    assert all(scope["entry_port"] == "body" for scope in restored["scopes"])
