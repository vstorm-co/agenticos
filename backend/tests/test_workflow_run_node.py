"""`workflow.run`'s guards, without a database."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from app.core.permissions import AuthContext
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
