"""Nested pins share a bounded, deduplicated import contract with direct bindings."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.core.permissions import AuthContext
from app.workflows.contracts.io import Binding, FileRef
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import file_binding_problems, graph_file_refs

pytestmark = pytest.mark.anyio


def _ref() -> FileRef:
    return FileRef(file_id=uuid.uuid4(), content_type="text/plain", byte_size=1)


def _graph(refs: list[FileRef]) -> WorkflowGraph:
    node = NodeInstance(
        id=uuid.uuid4(),
        definition_id="core.input",
        definition_version=1,
        layout=NodePosition(x=0, y=0),
        pinned_output={"payload": {"nested": [ref.model_dump(mode="json") for ref in refs]}},
    )
    return WorkflowGraph(entry_node_id=node.id, nodes=(node,))


def test_repeated_refs_across_bindings_and_pins_are_imported_once():
    ref = _ref()
    graph = _graph([ref, ref])
    graph = graph.model_copy(
        update={
            "bindings": (
                Binding(target_node_id=graph.entry_node_id, target_field="data", source=ref),
                Binding(target_node_id=graph.entry_node_id, target_field="other", source=ref),
            )
        }
    )
    assert [item.file_id for _field, item in graph_file_refs(graph)] == [ref.file_id]


@pytest.mark.security
async def test_implicit_imports_cannot_exceed_the_binding_allowance_before_database_work(
    monkeypatch,
):
    monkeypatch.setattr(settings, "WORKFLOW_GRAPH_MAX_BINDINGS", 1)
    graph = _graph([_ref(), _ref()])
    db = AsyncMock()
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")
    assert await file_binding_problems(db, ctx, graph) == [
        ("files", "A graph imports at most 1 unique files")
    ]
    db.execute.assert_not_awaited()
