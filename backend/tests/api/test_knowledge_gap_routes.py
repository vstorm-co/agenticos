"""An agent's knowledge gap list narrows to the topics a caller names."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.knowledge_gap import KnowledgeGapTopicList
from app.services.knowledge_gaps import KnowledgeGapService

pytestmark = pytest.mark.anyio


def _service(mock_db_session: MagicMock) -> KnowledgeGapService:
    service = KnowledgeGapService(mock_db_session)
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_knowledge_gap_service] = lambda: service
    return service


def _empty() -> AsyncMock:
    return AsyncMock(
        return_value=KnowledgeGapTopicList(items=[], total=0, by_knowledge_base=[], ungrouped=0)
    )


async def test_each_named_topic_reaches_the_service(
    client: AsyncClient, mock_db_session: MagicMock
) -> None:
    agent, first, second = uuid4(), uuid4(), uuid4()

    with patch.object(_service(mock_db_session), "list_for_agent", _empty()) as listed:
        response = await client.get(
            f"{settings.API_V1_STR}/knowledge-gaps/agents/{agent}",
            params={"topic_id": [str(first), str(second)], "limit": 100},
        )

    assert response.status_code == 200, response.text
    assert listed.await_args is not None
    assert listed.await_args.kwargs["topic_ids"] == [first, second]


async def test_more_than_a_page_of_topics_is_refused_before_the_service(
    client: AsyncClient, mock_db_session: MagicMock
) -> None:
    with patch.object(_service(mock_db_session), "list_for_agent", _empty()) as listed:
        response = await client.get(
            f"{settings.API_V1_STR}/knowledge-gaps/agents/{uuid4()}",
            params={"topic_id": [str(uuid4()) for _ in range(101)]},
        )

    assert response.status_code == 422
    listed.assert_not_awaited()
