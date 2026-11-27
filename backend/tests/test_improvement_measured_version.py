"""Which published version, if any, a kept session measured."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.db.models.improvement import ImprovementIteration, ImprovementRun
from app.services.improvement_pipeline import ImprovementPipelineService

pytestmark = pytest.mark.anyio


async def test_an_agent_never_published_has_no_measured_version(mock_db_session):
    run = ImprovementRun(agent_id=uuid4(), organization_id=uuid4())
    service = ImprovementPipelineService(mock_db_session)

    with patch(
        "app.services.improvement_pipeline.agent_repo.list_versions_after",
        AsyncMock(return_value=[]),
    ):
        assert await service._measured_version(run, ImprovementIteration(), []) == {}
