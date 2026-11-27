"""Whether publishing an accepted attempt would release draft edits no check measured."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.spec import AgentSpec
from app.db.models.improvement import ImprovementRun
from app.services.eval_run import spec_hash
from app.services.improvement_pipeline import ImprovementPipelineService

pytestmark = pytest.mark.anyio


async def test_a_session_on_an_agent_never_published_releases_unmeasured_edits(mock_db_session):
    """With no published version, publishing releases the whole draft, which no check
    measured as a change."""
    run = ImprovementRun(base_version_id=None, base_draft_hash="0" * 64, organization_id=uuid4())

    assert await ImprovementPipelineService(mock_db_session)._unmeasured_draft_edits(run)


async def test_a_session_started_from_its_published_version_releases_nothing_unmeasured(
    mock_db_session,
):
    spec = AgentSpec(name="Clerk", instructions="Answer.")
    run = ImprovementRun(
        base_version_id=uuid4(), base_draft_hash=spec_hash(spec), organization_id=uuid4()
    )
    version = type("Version", (), {"spec": spec.model_dump(mode="json")})()
    service = ImprovementPipelineService(mock_db_session)

    with patch(
        "app.services.improvement_pipeline.agent_repo.get_version",
        AsyncMock(side_effect=[version, None]),
    ):
        assert not await service._unmeasured_draft_edits(run)
        assert await service._unmeasured_draft_edits(run)
