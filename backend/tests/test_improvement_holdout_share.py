"""The held-out share a session pins when it starts."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.repositories import dataset_repo
from app.services.improvement_pipeline import ImprovementPipelineService

pytestmark = pytest.mark.anyio


async def test_a_dataset_deleted_while_the_session_starts_is_not_found(
    monkeypatch, mock_db_session
) -> None:
    """Deleting the dataset commits on its own, between the estimate and the start."""
    gone = uuid.uuid4()
    monkeypatch.setattr(dataset_repo, "get", AsyncMock(return_value=None))
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)

    with pytest.raises(NotFoundError) as refused:
        await ImprovementPipelineService(mock_db_session)._holdout_share(ctx, gone)

    assert refused.value.details == {"dataset_id": gone}
