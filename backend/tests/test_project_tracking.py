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
    binding = result.capabilities[0]
    assert binding.enabled and not binding.config["allow_create"]
    assert binding.config["tables"] == [
        {"table_id": str(table), "operations": ["read", "create", "update"]}
    ]
    assert not spec.capabilities[0].enabled


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


def test_collection_creation_permissions_are_required():
    with pytest.raises(AuthorizationError):
        ProjectTrackingService._can_create(
            AuthContext(user_id=uuid4(), organization_id=uuid4(), role="viewer")
        )
