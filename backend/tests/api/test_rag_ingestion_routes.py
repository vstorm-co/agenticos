"""The two routes that say whether documents are still indexing (#2486).

`GET /rag/collections/{name}/info` counts the collection, scoped to the
knowledge base the caller was authorized for; `GET /kb/{kb_id}/ingestion`
counts one knowledge base's own documents, which is what its page shows. The
status mapping is unit-tested in `tests/test_rag_ingestion_status.py`; the SQL
runs against Postgres in
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
from app.repositories.rag_document import CollectionScope, IngestionCounts
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
async def test_the_info_says_a_collection_with_documents_processing_is_indexing(
    client: AsyncClient,
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


@pytest.mark.usefixtures("documents", "vector_store")
class TestTheCountIsScopedToTheAuthorizedBase:
    @pytest.mark.parametrize("organization_id", [_ORGANIZATION, None])
    async def test_the_count_uses_the_resolved_knowledge_base(
        self, client: AsyncClient, access: MagicMock, organization_id: uuid.UUID | None
    ) -> None:
        """The base the caller was authorized through, not anything the caller supplies.

        A collection name is not unique, so another base's upload into a
        same-named collection must not hold this one at `indexing`; the count
        is this base's rows, as the document listing is.
        """
        kb = _kb(organization_id)
        access.readable = AsyncMock(return_value=kb)
        counts = _counts(processing=0, indexed=1, failed=0)
        with patch("app.repositories.rag_document_repo.ingestion_counts", counts):
            resp = await client.get(_INFO)

        assert resp.status_code == 200
        assert counts.await_args.kwargs == {"scope": CollectionScope.of(kb)}

    async def test_an_unreachable_collection_is_refused_before_anything_is_counted(
        self, client: AsyncClient, access: MagicMock
    ) -> None:
        access.readable = AsyncMock(side_effect=NotFoundError(message="Collection not found"))
        counts = _counts(processing=1, indexed=0, failed=0)
        with patch("app.repositories.rag_document_repo.ingestion_counts", counts):
            resp = await client.get(_INFO)

        assert resp.status_code == 404
        counts.assert_not_awaited()


@pytest.fixture
def knowledge_bases() -> MagicMock:
    stub = MagicMock()
    stub.get = AsyncMock(return_value=_kb(_ORGANIZATION))
    app.dependency_overrides[deps.get_knowledge_base_service] = lambda: stub
    return stub


@pytest.mark.usefixtures("documents")
class TestAKnowledgeBasesOwnIngestion:
    async def test_it_counts_the_knowledge_bases_own_documents(
        self, client: AsyncClient, knowledge_bases: MagicMock
    ) -> None:
        """By the base, not its collection name, which another base may share."""
        kb_id = uuid.uuid4()
        counts = _counts(processing=3, indexed=1, failed=2)
        with patch("app.repositories.rag_document_repo.ingestion_counts_for_kb", counts):
            resp = await client.get(f"{settings.API_V1_STR}/kb/{kb_id}/ingestion")

        assert resp.status_code == 200
        assert resp.json() == {
            "indexing_status": "indexing",
            "processing_count": 3,
            "indexed_count": 1,
            "failed_count": 2,
        }
        assert counts.await_args.args[1] == kb_id
        assert knowledge_bases.get.await_args.args == (kb_id,)

    async def test_an_unreadable_knowledge_base_is_refused_before_anything_is_counted(
        self, client: AsyncClient, knowledge_bases: MagicMock
    ) -> None:
        knowledge_bases.get = AsyncMock(
            side_effect=NotFoundError(message="Knowledge base not found")
        )
        counts = _counts(processing=1, indexed=0, failed=0)
        with patch("app.repositories.rag_document_repo.ingestion_counts_for_kb", counts):
            resp = await client.get(f"{settings.API_V1_STR}/kb/{uuid.uuid4()}/ingestion")

        assert resp.status_code == 404
        counts.assert_not_awaited()
