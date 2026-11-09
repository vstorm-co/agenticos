"""Cloning a tracker cannot activate previously disabled table authority."""

from uuid import uuid4

import pytest

from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.services.project_tracking import ProjectTrackingService, _with_task_table


def test_disabled_binding_drops_old_grants_and_create_authority():
    table = uuid4()
    spec = AgentSpec(
        name="Planner",
        capabilities=[
            CapabilityBindingSpec(
                id="virtual_tables",
                enabled=False,
                config={
                    "allow_create": True,
                    "tables": [{"table_id": str(uuid4()), "operations": ["delete"]}],
                },
            )
        ],
    )
    result = _with_task_table(spec, table, name="Tracker")
    assert result.capabilities == []
    assert result.table_bindings[0].table_id == table
    assert result.table_bindings[0].operations == ("read", "create", "update")
    assert spec.table_bindings == []
    assert result.mcp_servers[0].account == "platform"
    assert "add_virtual_table_record" in result.mcp_servers[0].allowed_tools


def test_full_table_grants_refuse_extension():
    spec = AgentSpec(
        name="Planner",
        capabilities=[
            CapabilityBindingSpec(
                id="virtual_tables",
                config={
                    "tables": [
                        {"table_id": str(uuid4()), "operations": ["read"]} for _ in range(50)
                    ]
                },
            )
        ],
    )
    with pytest.raises(BadRequestError):
        _with_task_table(spec, uuid4(), name="Tracker")


@pytest.mark.security
def test_collection_creation_permissions_are_required():
    with pytest.raises(AuthorizationError):
        ProjectTrackingService._can_create(
            AuthContext(user_id=uuid4(), organization_id=uuid4(), role="viewer")
        )


def test_tracker_adds_only_table_operations_to_a_restricted_platform_connection():
    spec = AgentSpec.model_validate(
        {
            "name": "Planner",
            "mcp_servers": [
                {"account": "platform", "allowed_tools": ["list_agents"], "approval": "all"}
            ],
        }
    )
    result = _with_task_table(spec, uuid4(), name="Tracker")
    assert len(result.mcp_servers) == 1
    assert result.mcp_servers[0].approval == "all"
    assert set(result.mcp_servers[0].allowed_tools or []) == {
        "list_agents",
        "list_virtual_tables",
        "get_virtual_table",
        "query_virtual_table",
        "get_virtual_table_record",
        "add_virtual_table_record",
        "update_virtual_table_record",
    }
    assert spec.mcp_servers[0].allowed_tools == ["list_agents"]
