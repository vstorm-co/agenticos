"""`GET /rag/collections/{name}/info` reports whether the collection is still indexing.

It answered the constant `complete` while the worker was still ingesting 231
uploads and `total_vectors` climbed from 111 to 1852 under it, so a script that
waited for `complete` queried a half-built collection (#2486). The status now
comes from the collection's tracked documents. These pin each state, that a
failed document is visible without holding the collection at `indexing`, and
that the count is scoped to the knowledge base the caller was authorized for.
The SQL itself runs against Postgres in
`tests/integration/test_platform_flows.py::TestWhatACollectionReportsItHolds`.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.resource_grant import Visibility
from app.main import app
from app.repositories.rag_document import IngestionCounts
from app.services.rag.models import CollectionInfo
from app.services.rag_document import RAGDocumentService

pytestmark = pytest.mark.anyio

_ORGANIZATION = uuid.uuid4()
_INFO = f"{settings.API_V1_STR}/rag/collections/handbook/info"


@pytest.fixture(autouse=True)
def caller() -> None:
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(),
        organization_id=_ORGANIZATION,
        role=OrgRoleName.OWNER.value,
        is_app_admin=False,
    )


def _kb(organization_id: uuid.UUID | None) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name="handbook",
        collection_name="handbook",
        scope=KBScope.ORG.value if organization_id else KBScope.APP.value,
        organization_id=organization_id,
        owner_user_id=None,
        visibility=Visibility.ORG.value,
        ingestion_config={},
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
    )


@pytest.fixture
def access() -> MagicMock:
    stub = MagicMock()
    stub.readable = AsyncMock(return_value=_kb(_ORGANIZATION))
    app.dependency_overrides[deps.get_collection_access_service] = lambda: stub
    return stub


@pytest.fixture
def documents(mock_db_session: MagicMock) -> None:
    """The real service, so the route-to-repository path is the one under test."""
    app.dependency_overrides[deps.get_rag_document_service] = lambda: RAGDocumentService(
        mock_db_session
    )


@pytest.fixture
def vector_store() -> MagicMock:
    stub = MagicMock()
    stub.get_collection_info = AsyncMock(
        return_value=CollectionInfo(name="handbook", total_vectors=111, dim=1536)
    )
    app.dependency_overrides[deps.get_vectorstore] = lambda: stub
    return stub


def _counts(*, processing: int, indexed: int, failed: int) -> AsyncMock:
    return AsyncMock(
        return_value=IngestionCounts(processing=processing, indexed=indexed, failed=failed)
    )


@pytest.mark.usefixtures("access", "documents", "vector_store")
class TestIndexingStatus:
    async def test_a_collection_with_documents_still_processing_is_indexing(
        self, client: AsyncClient
    ) -> None:
        """The reported case: vectors present, most of the upload still queued."""
        with patch(
            "app.repositories.rag_document_repo.ingestion_counts",
            _counts(processing=220, indexed=11, failed=0),
        ):
            resp = await client.get(_INFO)

        assert resp.status_code == 200
        assert resp.json() == {
            "name": "handbook",
            "total_vectors": 111,
            "dim": 1536,
            "indexing_status": "indexing",
            "processing_count": 220,
            "indexed_count": 11,
            "failed_count": 0,
        }

    async def test_a_collection_with_nothing_processing_is_complete(
        self, client: AsyncClient
    ) -> None:
        with patch(
            "app.repositories.rag_document_repo.ingestion_counts",
            _counts(processing=0, indexed=231, failed=0),
        ):
            resp = await client.get(_INFO)

        assert resp.json()["indexing_status"] == "complete"
        assert resp.json()["indexed_count"] == 231

    async def test_a_failed_document_is_visible_and_does_not_hold_it_at_indexing(
        self, client: AsyncClient
    ) -> None:
        """A failure is terminal: waiting on it would wait forever, so it is counted."""
        with patch(
            "app.repositories.rag_document_repo.ingestion_counts",
            _counts(processing=0, indexed=229, failed=2),
        ):
            resp = await client.get(_INFO)

        assert resp.json()["indexing_status"] == "complete"
        assert resp.json()["failed_count"] == 2

    async def test_a_collection_nothing_was_uploaded_to_is_complete(
        self, client: AsyncClient
    ) -> None:
        with patch(
            "app.repositories.rag_document_repo.ingestion_counts",
            _counts(processing=0, indexed=0, failed=0),
        ):
            resp = await client.get(_INFO)

        assert resp.json()["indexing_status"] == "complete"
        assert resp.json()["processing_count"] == 0


@pytest.mark.usefixtures("documents", "vector_store")
class TestTheCountIsScopedToTheAuthorizedBase:
    @pytest.mark.parametrize("organization_id", [_ORGANIZATION, None])
    async def test_the_count_uses_the_resolved_knowledge_bases_organization(
        self, client: AsyncClient, access: MagicMock, organization_id: uuid.UUID | None
    ) -> None:
        """The base's organization, not anything the caller supplies.

        A collection name is not unique across tenants, so another tenant's
        upload into a same-named collection must not hold this one at
        `indexing`. A deployment-wide base has no organization and counts on
        the name alone, as the document listing does.
        """
        access.readable = AsyncMock(return_value=_kb(organization_id))
        counts = _counts(processing=0, indexed=1, failed=0)
        with patch("app.repositories.rag_document_repo.ingestion_counts", counts):
            resp = await client.get(_INFO)

        assert resp.status_code == 200
        assert counts.await_args.kwargs == {
            "collection_name": "handbook",
            "organization_id": organization_id,
        }

    async def test_an_unreachable_collection_is_refused_before_anything_is_counted(
        self, client: AsyncClient, access: MagicMock
    ) -> None:
        access.readable = AsyncMock(side_effect=NotFoundError(message="Collection not found"))
        counts = _counts(processing=1, indexed=0, failed=0)
        with patch("app.repositories.rag_document_repo.ingestion_counts", counts):
            resp = await client.get(_INFO)

        assert resp.status_code == 404
        counts.assert_not_awaited()
