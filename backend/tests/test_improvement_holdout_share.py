"""A session pins its held-out share only from an accessible dataset."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.repositories import dataset_repo
from app.schemas.authoring import ProposalCheck
from app.schemas.improvement import ImprovementTarget
from app.services.improvement_pipeline import ImprovementPipelineService

pytestmark = pytest.mark.anyio


@pytest.mark.security
async def test_missing_dataset_is_refused_before_measurement_inputs_are_pinned(
    monkeypatch: pytest.MonkeyPatch, mock_db_session: AsyncMock
) -> None:
    gone = uuid.uuid4()
    monkeypatch.setattr(dataset_repo, "get", AsyncMock(return_value=None))
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)
    agent = Agent(id=uuid.uuid4(), name="Agent", kind="agent", status="draft")
    service = ImprovementPipelineService(mock_db_session)
    monkeypatch.setattr(service.registry, "get", AsyncMock(return_value=agent))
    monkeypatch.setattr(
        service.authoring,
        "_check_request",
        AsyncMock(return_value=SimpleNamespace(request=ProposalCheck(dataset_id=gone))),
    )
    estimate = AsyncMock()
    monkeypatch.setattr(service.evals, "plan", estimate)

    with pytest.raises(NotFoundError) as refused:
        await service._inputs(ctx, agent.id, ImprovementTarget(dataset_id=gone))

    assert refused.value.message == "Dataset not found"
    estimate.assert_not_awaited()
