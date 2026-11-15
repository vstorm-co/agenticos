"""Source accounts erased before a draft is claimed cannot be copied into a case."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConcurrentChangeError
from app.core.permissions import AuthContext, OrgRoleName
from app.repositories import user_repo
from app.schemas.dataset import DatasetCaseContent
from app.services import dataset as dataset_module
from app.services.dataset import Authorship, DatasetService, GeneratedCase

pytestmark = pytest.mark.anyio


async def test_an_account_deleted_before_source_admission_is_refused(
    mock_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    person = uuid4()
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)
    service = DatasetService(mock_db_session)
    monkeypatch.setattr(
        service, "_generated_from", AsyncMock(return_value=Authorship(asked_by=person))
    )
    monkeypatch.setattr(user_repo, "hold_key_share", AsyncMock())
    monkeypatch.setattr(dataset_module, "hold_subject", AsyncMock())
    monkeypatch.setattr(user_repo, "existing_ids", AsyncMock(return_value=set()))
    with pytest.raises(ConcurrentChangeError, match="source account was erased"):
        await service.hold_generated_sources(
            ctx,
            [
                GeneratedCase(
                    content=DatasetCaseContent(
                        input="A private question", reference_answer="A reference"
                    )
                )
            ],
        )
