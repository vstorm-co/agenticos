"""The RAG search route builds the tenant scope and carries business filters.

The security-bearing part is that the scope is built from the caller's context
after collection access resolves, never from the request body - so a supplied
filter can only narrow. These pin: the structured filters reach the service under
the caller's own tenant, a smuggled tenant key is rejected, the deprecated filter
string folds into parent_doc_id or is refused, and the facet read is tenant
scoped and omits absent values.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.resource_grant import Visibility
from app.main import app
from app.services.rag.filters import TenantScope

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_ORGANIZATION = uuid.uuid4()
_CALLER = uuid.uuid4()
_SEARCH = f"{settings.API_V1_STR}/rag/search"


@pytest.fixture(autouse=True)
def caller() -> None:
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=_CALLER,
        organization_id=_ORGANIZATION,
        role=OrgRoleName.OWNER.value,
        is_app_admin=False,
    )


def _kb(name: str) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=name,
        collection_name=name,
        scope=KBScope.ORG.value,
        organization_id=_ORGANIZATION,
        owner_user_id=None,
        visibility=Visibility.ORG.value,
        ingestion_config={},
        embedding_model="text-embedding-3-large",
        embedding_dim=3072,
    )


@pytest.fixture
def access() -> MagicMock:
    stub = MagicMock()
    stub.readable_all = AsyncMock(side_effect=lambda _ctx, names: [_kb(n) for n in names])
    stub.readable = AsyncMock(side_effect=lambda _ctx, name: _kb(name))
    app.dependency_overrides[deps.get_collection_access_service] = lambda: stub
    return stub


@pytest.fixture
def retrieval() -> MagicMock:
    stub = MagicMock()
    stub.retrieve = AsyncMock(return_value=[])
    stub.retrieve_multi = AsyncMock(return_value=[])
    app.dependency_overrides[deps.get_retrieval_service] = lambda: stub
    return stub


class TestScopeAndFilters:
    async def test_the_scope_is_the_callers_own_tenant(
        self, client: AsyncClient, access: MagicMock, retrieval: MagicMock
    ) -> None:
        resp = await client.post(_SEARCH, json={"query": "x", "collection_name": "handbook"})
        assert resp.status_code == 200
        scope = retrieval.retrieve.await_args.kwargs["scope"]
        assert isinstance(scope, TenantScope)
        assert scope.organization_id == _ORGANIZATION

    async def test_business_filters_reach_the_service_and_cannot_set_tenant(
        self, client: AsyncClient, access: MagicMock, retrieval: MagicMock
    ) -> None:
        resp = await client.post(
            _SEARCH,
            json={
                "query": "x",
                "collection_name": "handbook",
                "filters": {"source": ["upload"], "document_type": ["pdf"]},
            },
        )
        assert resp.status_code == 200
        kwargs = retrieval.retrieve.await_args.kwargs
        assert kwargs["filters"].source == ["upload"]
        assert kwargs["filters"].document_type == ["pdf"]
        # The tenant is still the caller's own, not anything from the body.
        assert kwargs["scope"].organization_id == _ORGANIZATION

    async def test_a_smuggled_tenant_key_is_rejected(
        self, client: AsyncClient, access: MagicMock, retrieval: MagicMock
    ) -> None:
        resp = await client.post(
            _SEARCH,
            json={
                "query": "x",
                "collection_name": "handbook",
                "filters": {"organization_id": str(uuid.uuid4())},
            },
        )
        assert resp.status_code == 422
        retrieval.retrieve.assert_not_awaited()

    async def test_an_empty_business_list_is_rejected(
        self, client: AsyncClient, access: MagicMock, retrieval: MagicMock
    ) -> None:
        resp = await client.post(
            _SEARCH,
            json={"query": "x", "collection_name": "handbook", "filters": {"source": []}},
        )
        assert resp.status_code == 422

    async def test_several_collections_use_the_multi_path_with_scope(
        self, client: AsyncClient, access: MagicMock, retrieval: MagicMock
    ) -> None:
        resp = await client.post(
            _SEARCH,
            json={"query": "x", "collection_names": ["a", "b"]},
        )
        assert resp.status_code == 200
        scope = retrieval.retrieve_multi.await_args.kwargs["scope"]
        assert scope.organization_id == _ORGANIZATION


class TestLegacyFilterShim:
    async def test_a_full_match_string_folds_into_parent_doc_id(
        self, client: AsyncClient, access: MagicMock, retrieval: MagicMock
    ) -> None:
        resp = await client.post(
            _SEARCH,
            json={"query": "x", "collection_name": "handbook", "filter": 'parent_doc_id == "d1"'},
        )
        assert resp.status_code == 200
        assert retrieval.retrieve.await_args.kwargs["filters"].parent_doc_id == "d1"

    async def test_any_other_string_is_refused(
        self, client: AsyncClient, access: MagicMock, retrieval: MagicMock
    ) -> None:
        resp = await client.post(
            _SEARCH,
            json={"query": "x", "collection_name": "handbook", "filter": 'filetype == "pdf"'},
        )
        assert resp.status_code == 400
        retrieval.retrieve.assert_not_awaited()

    async def test_supplying_both_sources_is_a_conflict(
        self, client: AsyncClient, access: MagicMock, retrieval: MagicMock
    ) -> None:
        resp = await client.post(
            _SEARCH,
            json={
                "query": "x",
                "collection_name": "handbook",
                "filter": 'parent_doc_id == "a"',
                "filters": {"parent_doc_id": "b"},
            },
        )
        assert resp.status_code == 400


class TestFilterValuesFacet:
    async def test_the_facet_is_tenant_scoped_and_returns_present_values(
        self, client: AsyncClient, access: MagicMock
    ) -> None:
        store = MagicMock()
        store.distinct_metadata_values = AsyncMock(
            return_value={"organizational_unit": ["legal", "sales"]}
        )
        app.dependency_overrides[deps.get_vectorstore] = lambda: store

        resp = await client.get(f"{settings.API_V1_STR}/rag/collections/handbook/filter-values")
        assert resp.status_code == 200
        assert resp.json()["organizational_unit"] == ["legal", "sales"]
        scope = store.distinct_metadata_values.await_args.args[2]
        assert isinstance(scope, TenantScope)
        assert scope.organization_id == _ORGANIZATION
