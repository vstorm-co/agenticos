"""`workflow.run`'s guards, without a database."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from app.core.permissions import AuthContext
from app.services.workflow_execution import context
from app.workflows.contracts.results import Failed
from app.workflows.nodes.workflow_run import _handler

pytestmark = pytest.mark.anyio


class _Other(BaseModel):
    pass


async def test_a_step_with_no_workflow_to_run_fails_rather_than_guessing():
    result = await _handler.handle(None, None)
    assert isinstance(result, Failed) and result.error.code == "WORKFLOW_RUN_NOT_CONFIGURED"


async def test_a_resource_check_handed_another_nodes_config_has_nothing_to_say():
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")
    assert await _handler.check_resources(MagicMock(), ctx, _Other()) == []


def _caller() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        root_run_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        visited_trigger_ids=[],
        depth=0,
        public_origin=False,
        triggered_by="manual",
        impersonated=False,
    )


async def _admit_losing_the_link(existing: object | None) -> object:
    @asynccontextmanager
    async def savepoint():
        yield

    org = uuid.uuid4()
    dispatch = context.DispatchContext(
        organization_id=org,
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=AuthContext(user_id=uuid.uuid4(), organization_id=org, role="owner"),
        resumed_agent_run_id=None,
        workflow_id=uuid.uuid4(),
    )
    db = MagicMock()
    db.begin_nested = savepoint
    lost = IntegrityError("insert", {}, Exception("duplicate parent_node_run_id"))
    with (
        context.dispatching_as(dispatch),
        patch(
            "app.services.workflow_execution.facade.WorkflowExecutionService.admit_call",
            new=AsyncMock(side_effect=lost),
        ),
        patch.object(
            _handler.workflow_run_repo, "get_run_called_by", AsyncMock(return_value=existing)
        ),
    ):
        return await _handler._admit(db, _caller(), MagicMock(), MagicMock(), {}, "workflow:x")


async def test_a_step_that_lost_the_race_to_call_adopts_the_run_that_won():
    winner = object()

    assert await _admit_losing_the_link(winner) is winner


async def test_an_integrity_error_with_no_call_behind_it_is_raised():
    with pytest.raises(IntegrityError):
        await _admit_losing_the_link(None)
