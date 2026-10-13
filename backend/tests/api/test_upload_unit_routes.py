"""The organizational unit an upload names, at both addresses it can arrive at.

`organizational_unit` is one of the four FA-039 filter dimensions, and until
#1777 nothing wrote it: the filter matched nothing and the facet answered empty
for every collection. An upload names one in the multipart body, beside
`ingestion` and for the same reason - it has no schema of its own, because the
body already carries a file.

Both routes, because there are two and a field added to one of them is the
defect #560 was: the same operation answering differently depending on which
address a client reached it at.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.resource_grant import Visibility
from app.main import app
from app.schemas.rag import RAGIngestResponse

pytestmark = pytest.mark.anyio

_ORGANIZATION = uuid.uuid4()
_CALLER = uuid.uuid4()
# Fixed, because it is part of a parametrized route and so part of a test id.
_KB_ID = uuid.UUID("2c51f0a4-7b6d-4f3e-8a19-5d0e7c4b1f62")

_PATHS = [
    f"{settings.API_V1_STR}/rag/collections/handbook/ingest",
    f"{settings.API_V1_STR}/kb/{_KB_ID}/documents",
]


@pytest.fixture(autouse=True)
def caller() -> None:
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=_CALLER,
        organization_id=_ORGANIZATION,
        role=OrgRoleName.OWNER.value,
        is_app_admin=False,
    )


@pytest.fixture(autouse=True)
def collection() -> KnowledgeBase:
    """Reachable through both routes' resolvers; who may write here is settled
    elsewhere and is not what these are about."""
    row = KnowledgeBase(
        id=_KB_ID,
        name="Handbook",
        collection_name="handbook",
        scope=KBScope.ORG.value,
        organization_id=_ORGANIZATION,
        owner_user_id=None,
        visibility=Visibility.ORG.value,
        ingestion_config={},
        embedding_model="text-embedding-3-large",
        embedding_dim=3072,
    )
    access = MagicMock(writable=AsyncMock(return_value=row))
    app.dependency_overrides[deps.get_collection_access_service] = lambda: access
    knowledge_bases = MagicMock(get_for_write=AsyncMock(return_value=row))
    app.dependency_overrides[deps.get_knowledge_base_service] = lambda: knowledge_bases
    app.dependency_overrides[deps.get_vectorstore] = lambda: MagicMock(
        create_collection=AsyncMock()
    )
    return row


@pytest.fixture(autouse=True)
def documents() -> MagicMock:
    """The service stubbed, because the question is what the *route* forwards."""
    service = MagicMock()
    service.dispatch_upload = AsyncMock(
        return_value=RAGIngestResponse(
            id=str(uuid.uuid4()),
            status="processing",
            filename="handbook.pdf",
            collection="handbook",
            message="File accepted. Processing in background.",
        )
    )
    app.dependency_overrides[deps.get_rag_document_service] = lambda: service
    return service


def _upload() -> dict[str, Any]:
    return {"file": ("handbook.pdf", b"%PDF-1.4", "application/pdf")}


@pytest.mark.parametrize("path", _PATHS)
class TestTheUnitAnUploadNames:
    async def test_it_reaches_the_service(
        self, client: AsyncClient, documents: MagicMock, path: str
    ) -> None:
        response = await client.post(path, files=_upload(), data={"organizational_unit": "Legal"})

        assert response.status_code == 202
        assert documents.dispatch_upload.await_args.kwargs["organizational_unit"] == "Legal"

    async def test_an_upload_that_names_none_forwards_none(
        self, client: AsyncClient, documents: MagicMock, path: str
    ) -> None:
        """Which is what every upload sent before the field existed, and what a
        client that has never heard of it still sends."""
        response = await client.post(path, files=_upload())

        assert response.status_code == 202
        assert documents.dispatch_upload.await_args.kwargs["organizational_unit"] is None

    async def test_one_longer_than_the_column_is_refused_rather_than_truncated(
        self, client: AsyncClient, documents: MagicMock, path: str
    ) -> None:
        """`String(255)`. A value silently cut to fit is a unit nobody can
        filter on, because what they typed is not what was stored."""
        response = await client.post(path, files=_upload(), data={"organizational_unit": "L" * 256})

        assert response.status_code == 422
        documents.dispatch_upload.assert_not_awaited()
