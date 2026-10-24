"""The Tables capability's build and its pieces that need no database (#1784).

The tools against a real service are `tests/integration/test_virtual_tables_capability.py`.
"""

import uuid
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.capabilities._registry import CapabilityBuildContext, get
from app.agents.capabilities.virtual_tables import (
    VirtualTables,
    VirtualTablesConfig,
    table_grants_of,
)
from app.agents.capabilities.virtual_tables._access import (
    Refused,
    TableOperation,
    acting_as,
    refusal_text,
    require,
)
from app.agents.capabilities.virtual_tables._toolset import _operation_key
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.services.agent_registry import AgentRegistryService

pytestmark = pytest.mark.anyio


def _build(config: VirtualTablesConfig) -> VirtualTables | None:
    definition = get("virtual_tables")
    return definition.builder(
        CapabilityBuildContext(
            binding=CapabilityBindingSpec(
                id="virtual_tables", config=config.model_dump(mode="json")
            ),
            config=config,
        )
    )


def test_a_binding_that_grants_nothing_and_creates_nothing_contributes_nothing():
    assert _build(VirtualTablesConfig()) is None


def test_the_grants_and_the_switch_reach_the_capability():
    table_id = uuid.uuid4()
    built = _build(
        VirtualTablesConfig.model_validate(
            {"tables": [{"table_id": str(table_id), "operations": ["read", "update"]}]}
        )
    )
    assert built is not None
    assert built.grants == {table_id: frozenset({TableOperation.READ, TableOperation.UPDATE})}
    assert built.allow_create is False


def test_only_creating_tables_is_enough_to_build():
    built = _build(VirtualTablesConfig(allow_create=True))
    assert built is not None and built.grants == {}


def test_a_table_granted_twice_is_refused():
    table_id = str(uuid.uuid4())
    with pytest.raises(ValidationError, match="once"):
        VirtualTablesConfig.model_validate(
            {"tables": [{"table_id": table_id}, {"table_id": table_id}]}
        )


@pytest.mark.security
async def test_a_run_acting_for_something_that_is_not_a_member_id_is_refused():
    with pytest.raises(Refused, match="acting for a member"):
        await acting_as(MagicMock(), uuid.uuid4(), "embed-visitor")


@pytest.mark.security
def test_an_operation_the_grant_leaves_out_names_what_it_does_allow():
    table_id = uuid.uuid4()
    with pytest.raises(Refused, match="may read"):
        require({table_id: frozenset({TableOperation.READ})}, table_id, TableOperation.DELETE)


def test_a_refusal_without_a_known_remedy_is_said_plainly():
    assert refusal_text(NotFoundError(message="Gone")).startswith("Refused (NOT_FOUND): Gone.")


def test_a_call_outside_a_run_has_no_operation_key():
    ctx = RunContext(deps=AgentDeps(), model=TestModel(), usage=RunUsage(), tool_call_id="c1")
    assert _operation_key(ctx) is None


def test_the_toolset_is_built_once_per_run():
    built = _build(VirtualTablesConfig(allow_create=True))
    assert built is not None and built.get_toolset() is built.get_toolset()


def test_table_grants_of_reads_the_enabled_binding_only():
    table_id = uuid.uuid4()
    config = {"tables": [{"table_id": str(table_id), "operations": ["read", "update"]}]}

    enabled = AgentSpec(name="Clerk", capabilities=[{"id": "virtual_tables", "config": config}])
    disabled = AgentSpec(
        name="Clerk", capabilities=[{"id": "virtual_tables", "enabled": False, "config": config}]
    )

    assert table_grants_of(enabled) == {table_id: frozenset({"read", "update"})}
    assert table_grants_of(disabled) == {}
    assert table_grants_of(AgentSpec(name="Clerk")) == {}


def test_no_tool_shares_a_view_any_more():
    """A page reads its own query with its owner's access: nothing shares a view for it."""
    built = _build(VirtualTablesConfig(allow_create=True))

    assert "share_view" not in get("virtual_tables").tool_ids
    assert built is not None and "share_view" not in built.get_toolset().tools


async def test_a_stored_spec_that_gated_share_view_still_publishes():
    """Saved while `share_view` existed, as it was written: publishing it again must not
    be refused for naming a tool that is gone, and what else it gated stays gated."""
    stored = {
        "id": "virtual_tables",
        "config": {"allow_create": True},
        "tool_approval": {"share_view": "required", "delete_record": "required"},
        "tool_overrides": {"share_view": {"name": "share_saved_view"}},
    }

    binding = CapabilityBindingSpec.model_validate(stored)
    problems = await AgentRegistryService(MagicMock())._binding_problems(
        AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner"), binding
    )

    assert binding.tool_approval == {"delete_record": "required"}
    assert binding.tool_overrides == {}
    assert (problems.messages, problems.fields) == ([], [])
