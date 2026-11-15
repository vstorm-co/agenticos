"""Generated summaries and proposed text are evidence, even without explicit quotes."""

from typing import Literal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.schemas.authoring import HunkDecision
from app.services.authoring import AuthoringService

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("target", ["agent", "skill", "context", "changes", "decision"])
async def test_derived_details_and_decisions_need_runs_view(
    mock_db_session: AsyncSession,
    target: Literal["agent", "skill", "context", "changes", "decision"],
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.MEMBER.value)
    service = AuthoringService(mock_db_session)
    identifier = uuid4()
    with (
        patch.object(service.registry, "get", AsyncMock(return_value=Agent(id=identifier))),
        pytest.raises(AuthorizationError, match="runs:view"),
    ):
        match target:
            case "agent":
                await service.for_agent(ctx, identifier)
            case "skill":
                await service.for_skill(ctx, identifier)
            case "context":
                await service.for_context(ctx, identifier)
            case "changes":
                await service.changes_of(ctx, Agent(id=identifier), uuid4(), None)
            case "decision":
                await service.decide(ctx, identifier, uuid4(), HunkDecision(action="dismiss"))
