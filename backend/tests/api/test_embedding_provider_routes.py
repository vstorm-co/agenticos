"""Moving a collection's embeddings to another provider, over the wire.

The model is fixed by the vectors already stored, so `PATCH /kb/{id}` has never
taken one and still does not. The provider is not fixed - the same model at the
same width produces vectors in the same space wherever it is served from - and
until this it could not be changed either: every request went to `openrouter.ai`,
hardcoded in `EmbeddingService`, so an organization holding an OpenAI key had no
way to use it and a rotated key meant re-ingesting the collection.

Routes rather than the service alone, because two halves of it are route-shaped:
the refusal has to arrive in the shape a form marks its inputs from, and the
catalog the form is built out of has to be what the deployment will actually act
on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
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
from app.services.knowledge_base import KnowledgeBaseService

pytestmark = pytest.mark.anyio

_ORGANIZATION = uuid.uuid4()
_KB_ID = uuid.UUID("2b1c4f8e-6a77-4d2e-9f31-5c8ab0d17e64")
_V1 = settings.API_V1_STR


@pytest.fixture(autouse=True)
def caller() -> None:
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(),
        organization_id=_ORGANIZATION,
        role=OrgRoleName.OWNER.value,
        is_app_admin=False,
    )
    yield
    app.dependency_overrides.clear()


def _collection(**overrides: Any) -> KnowledgeBase:
    """A row as the response schema will read it, never inserted.

    `is_default` and `created_at` are server defaults, so a row built in memory
    holds `None` for both and `KnowledgeBaseRead` refuses it - a 500 about the
    fixture rather than about the code under test.
    """
    return KnowledgeBase(
        is_default=False,
        created_at=datetime(2026, 8, 22, tzinfo=UTC),
        id=_KB_ID,
        name="Handbook",
        collection_name="handbook",
        scope=KBScope.ORG.value,
        organization_id=_ORGANIZATION,
        owner_user_id=None,
        visibility=Visibility.ORG.value,
        ingestion_config={},
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        embedding_provider="openrouter",
        **overrides,
    )


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> KnowledgeBase:
    """The real service over a stubbed row, so the validation under test runs."""
    row = _collection()
    monkeypatch.setattr(KnowledgeBaseService, "get_for_write", AsyncMock(return_value=row))
    monkeypatch.setattr("app.repositories.knowledge_base_repo.update", AsyncMock(return_value=row))
    app.dependency_overrides[deps.get_knowledge_base_service] = lambda: KnowledgeBaseService(
        MagicMock()
    )
    return row


class TestWhatTheCatalogOffers:
    async def test_the_models_are_grouped_by_the_provider_that_serves_them(
        self, client: AsyncClient
    ):
        """A flat list of every model this build knows a *width* for is what the
        create form used to be built from - so it offered sentence-transformer
        weights nothing here can call, whose first document failed to index."""
        body = (await client.get(f"{_V1}/rag/embedding-models")).json()

        assert body["default_provider"] == "openrouter"
        providers = {entry["provider"]: entry for entry in body["providers"]}
        assert "openrouter" in providers
        assert providers["openrouter"]["deployment_key"] is True
        assert all(entry["models"] for entry in body["providers"])

    async def test_exactly_one_provider_claims_the_deployments_key(self, client: AsyncClient):
        """The form offers "the deployment's key" only where it applies: that key
        belongs to one endpoint, and offering it elsewhere offers a collection
        that cannot index anything."""
        body = (await client.get(f"{_V1}/rag/embedding-models")).json()

        claiming = [entry for entry in body["providers"] if entry["deployment_key"]]
        assert len(claiming) == 1


class TestMovingACollection:
    async def test_a_provider_that_serves_the_model_is_accepted(
        self, client: AsyncClient, service: KnowledgeBase
    ):
        response = await client.patch(
            f"{_V1}/kb/{_KB_ID}",
            json={"embedding_provider": "openai", "clear_embedding_secret": True},
        )

        assert response.status_code == 200

    async def test_a_provider_this_build_does_not_offer_names_the_field(
        self, client: AsyncClient, service: KnowledgeBase
    ):
        """In the shape `fieldProblems` reads, so the select that named it is the
        thing marked - not a toast about a collection somebody has to re-find."""
        response = await client.patch(
            f"{_V1}/kb/{_KB_ID}", json={"embedding_provider": "a-vendor-we-cannot-call"}
        )

        assert response.status_code == 400
        fields = response.json()["error"]["details"]["fields"]
        assert fields[0]["field"] == "embedding_provider"

    async def test_the_model_is_still_not_something_a_patch_can_change(
        self, client: AsyncClient, service: KnowledgeBase
    ):
        """Ignored rather than refused, as it always has been: the field is not on
        the update schema at all, so a client sending one is sending a key the
        server has never read."""
        response = await client.patch(
            f"{_V1}/kb/{_KB_ID}", json={"embedding_model": "text-embedding-3-large"}
        )

        assert response.status_code == 200
        assert response.json()["embedding_model"] == "text-embedding-3-small"
