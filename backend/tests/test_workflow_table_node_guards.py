"""The refusals the table nodes make before they reach the table service (#1784).

A published graph never hands these nodes another node's config or an unbound
input - the dispatcher validates both against the node's own schemas first - so
the guards are proved here directly, as `test_workflow_node_guards.py` does for
the other nodes.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError

from app.core.permissions import AuthContext
from app.services.virtual_tables.exceptions import InvalidSchemaError
from app.services.virtual_tables.tables import _checked_key
from app.services.workflow_registry import _table_references
from app.workflows.contracts.io import TableIORef
from app.workflows.contracts.results import Completed, Failed
from app.workflows.nodes import _tables
from app.workflows.nodes.table_create import _handler as table_create
from app.workflows.nodes.table_record_create import _handler as record_create
from app.workflows.nodes.table_record_delete import _handler as record_delete
from app.workflows.nodes.table_record_get import _handler as record_get
from app.workflows.nodes.table_record_query import _handler as record_query
from app.workflows.nodes.table_record_update import _handler as record_update
from app.workflows.nodes.table_record_upsert import _handler as record_upsert

pytestmark = pytest.mark.anyio

HANDLERS = [
    table_create,
    record_create,
    record_delete,
    record_get,
    record_query,
    record_update,
    record_upsert,
]
IDS = ["create-table", "create", "delete", "get", "query", "update", "upsert"]


class _Other(BaseModel):
    """Some other node's config - what a guard is there to turn away."""


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")


@pytest.mark.parametrize("module", HANDLERS, ids=IDS)
async def test_a_resource_check_handed_another_nodes_config_has_nothing_to_say(module: Any):
    assert await module.check_resources(MagicMock(), _ctx(), _Other()) == []


@pytest.mark.parametrize("module", HANDLERS, ids=IDS)
async def test_a_table_step_with_no_config_fails_rather_than_guessing(module: Any):
    result = await module.handle(None, None)
    assert isinstance(result, Failed) and result.error.code == "TABLE_STEP_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "lookup", [{}, {"record_id": str(uuid.uuid4()), "external_id": "A-1"}], ids=["none", "both"]
)
def test_a_lookup_names_exactly_one_key(lookup: dict[str, Any]):
    with pytest.raises(ValidationError, match="exactly one"):
        record_get.TableRecordGetInput.model_validate(lookup)


@pytest.mark.security
async def test_a_table_the_author_may_read_but_not_edit_cannot_be_written_to():
    ref = TableIORef(table_id=uuid.uuid4(), schema_version=1)
    with (
        patch.object(_tables, "table_ref_problems", new=AsyncMock(return_value=[])),
        patch.object(
            _tables.virtual_table_repo, "get_table", new=AsyncMock(return_value=SimpleNamespace())
        ),
        patch.object(_tables, "resolve_access", new=AsyncMock(return_value=False)),
    ):
        problems = await _tables.check_table(MagicMock(), _ctx(), ref, writes=True)
    assert problems == [("table", "You cannot write to this table")]


async def test_a_delete_at_a_bound_revision_does_not_read_the_record_first():
    table_id, record_id = uuid.uuid4(), uuid.uuid4()
    service = MagicMock(get_record=AsyncMock(), delete_record=AsyncMock())

    async def run(work):
        return await work(service, _ctx())

    with (
        patch.object(record_delete, "with_service", new=run),
        patch.object(record_delete, "operation_key", return_value="key"),
    ):
        result = await record_delete.handle(
            record_delete.TableRecordDeleteConfig(
                table=TableIORef(table_id=table_id, schema_version=1)
            ),
            record_delete.TableRecordDeleteInput(record_id=record_id, expected_revision=4),
        )

    assert isinstance(result, Completed)
    service.get_record.assert_not_awaited()
    assert service.delete_record.await_args.kwargs["expected_revision"] == 4


def test_an_operation_key_past_its_limits_is_refused_for_a_direct_caller():
    with pytest.raises(InvalidSchemaError):
        _checked_key("x" * 1000)
    assert _checked_key(None) is None


def test_a_stored_graph_naming_a_table_it_cannot_parse_names_no_table():
    table_id = uuid.uuid4()
    graph = {
        "nodes": [
            {"config": {"table": {"table_id": str(table_id), "schema_version": 1}}},
            {"config": {"table": {"table_id": "not-a-uuid"}}},
        ],
        "bindings": [{"source": {"kind": "table", "table_id": "nope"}}],
    }
    assert _table_references(graph) == [(table_id, None)]
