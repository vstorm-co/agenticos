"""Learning keeps the authenticated caller and proposal provenance on the wire."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.auto_skill_learning import LearnedSkillRead, LearnSkillCreate

pytestmark = pytest.mark.anyio


async def test_learning_passes_the_caller_agent_and_proposal_to_the_skill_service(
    client: AsyncClient,
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    agent_id, proposal_id, skill_id = uuid4(), uuid4(), uuid4()
    learned = LearnedSkillRead(
        skill_id=skill_id,
        name="learned-refunds",
        version=1,
        content_sha256="a" * 64,
        created=True,
        already_learned=False,
        proposal_id=proposal_id,
    )
    service = MagicMock(learn=AsyncMock(return_value=learned))
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_auto_skill_learning_service] = lambda: service
    payload = {
        "proposal_id": str(proposal_id),
        "content": "Check the order before offering a refund.",
        "rationale": "An operator approved this procedure.",
    }

    response = await client.post(f"/api/v1/agents/{agent_id}/learned-skills", json=payload)

    assert response.status_code == 200
    assert response.json() == learned.model_dump(mode="json")
    service.learn.assert_awaited_once_with(ctx, agent_id, LearnSkillCreate.model_validate(payload))


@pytest.mark.security
async def test_an_inaccessible_skill_stays_not_found_in_the_learning_response(
    client: AsyncClient,
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.MEMBER)
    service = MagicMock(learn=AsyncMock(side_effect=NotFoundError(message="Skill not found")))
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_auto_skill_learning_service] = lambda: service
    agent_id = uuid4()

    response = await client.post(
        f"/api/v1/agents/{agent_id}/learned-skills",
        json={"proposal_id": str(uuid4()), "skill_id": str(uuid4()), "content": "Reviewed text"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    service.learn.assert_awaited_once()
    assert service.learn.await_args.args[:2] == (ctx, agent_id)
