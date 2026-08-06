"""What the two routes that accept a collection name answer to a bad one.

They are the same resource at two addresses, and they did not agree about it.
`POST /rag/collections/{name}` claimed the name and reached the store, so it
refused a name another organization held - and answered `500` for a malformed
or reserved one, because the store raised `ValueError` and no handler maps that
(#371). `POST /kb` called neither: an explicit `collection_name` was written to
the row unexamined, which is a knowledge base pointed at another tenant's
vector table and readable and writable through every gate after it (#367).

Routes rather than services because both defects are route-shaped. The service
tests underneath (`tests/test_collection_access.py`,
`tests/test_collection_name_rules.py`) were passing while `POST /kb` reached
none of the code they cover.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.resource_grant import Visibility
from app.db.vector_tables import MAX_COLLECTION_NAME_LENGTH
from app.main import app
from app.repositories import knowledge_base_repo

pytestmark = pytest.mark.anyio

_ORGANIZATION = uuid.uuid4()
_ANOTHER_ORGANIZATION = uuid.uuid4()
_CALLER = uuid.uuid4()

_TOO_LONG = "a" * (MAX_COLLECTION_NAME_LENGTH + 1)


@pytest.fixture(autouse=True)
def caller() -> None:
    """An owner, so nothing here is refused for want of a permission.

    `collections:edit` is what both routes gate on and
    `tests/api/test_platform_routes.py` is what proves they do. Holding every
    permission keeps that out of the way: a 400 here is a statement about the
    name.
    """
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=_CALLER,
        organization_id=_ORGANIZATION,
        role=OrgRoleName.OWNER.value,
        is_app_admin=False,
    )


@pytest.fixture
def store() -> MagicMock:
    """A stand-in for the vector store, so "never reached" is assertable.

    The real dependency builds an engine per request from the deployment
    settings, which is a connection pool this test has no use for.
    """
    stub = MagicMock()
    app.dependency_overrides[deps.get_vectorstore] = lambda: stub
    return stub


def _held_by(organization_id: uuid.UUID, name: str) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=name,
        collection_name=name,
        scope=KBScope.ORG.value,
        organization_id=organization_id,
        owner_user_id=None,
        visibility=Visibility.ORG.value,
        ingestion_config={},
        embedding_model="text-embedding-3-large",
        embedding_dim=3072,
    )


@pytest.fixture
def claimed_by_another_organization(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every name is already held by somebody the caller cannot reach."""

    async def rows(_db: object, collection_name: str) -> list[KnowledgeBase]:
        return [_held_by(_ANOTHER_ORGANIZATION, collection_name)]

    monkeypatch.setattr(knowledge_base_repo, "list_by_collection_name", rows)


@pytest.fixture
def claimed_by_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    async def rows(_db: object, collection_name: str) -> list[KnowledgeBase]:
        del collection_name
        return []

    monkeypatch.setattr(knowledge_base_repo, "list_by_collection_name", rows)


def _error(response: Any) -> dict[str, Any]:
    body: dict[str, Any] = response.json()["error"]
    return body


class TestCreatingACollectionOnTheRagRoute:
    @pytest.mark.parametrize("name", ["foo-bar", "all", "documents", _TOO_LONG])
    async def test_a_name_the_store_cannot_use_is_a_400(
        self, client: AsyncClient, store: MagicMock, claimed_by_nobody: None, name: str
    ) -> None:
        """It was a 500 for two of these, and a 500 says the server broke.

        The request was understood perfectly and declined, which is a different
        thing and a different status. `all` and `foo-bar` are the two that
        raised `ValueError`; `documents` already answered 400 and is here to
        show they now answer alike.
        """
        response = await client.post(f"{settings.API_V1_STR}/rag/collections/{name}")

        assert response.status_code == 400
        assert _error(response)["code"] == "BAD_REQUEST"
        assert _error(response)["details"]["collection"] == name
        store.create_collection.assert_not_called()

    async def test_a_name_another_organization_holds_is_a_409(
        self, client: AsyncClient, store: MagicMock, claimed_by_another_organization: None
    ) -> None:
        response = await client.post(f"{settings.API_V1_STR}/rag/collections/handbook")

        assert response.status_code == 409
        store.create_collection.assert_not_called()


class TestCreatingAKnowledgeBase:
    @staticmethod
    def _payload(collection_name: str) -> dict[str, Any]:
        return {"name": "Handbook", "collection_name": collection_name}

    async def test_a_name_another_organization_holds_is_refused(
        self, client: AsyncClient, claimed_by_another_organization: None
    ) -> None:
        """The whole of #367 in one request.

        This answered 201 and wrote a row naming the other organization's
        vector table. Everything afterwards then passed: the collection resolves
        through whichever knowledge base the caller may read, and now one of
        them is theirs.
        """
        response = await client.post(
            f"{settings.API_V1_STR}/kb", json=self._payload("their_handbook")
        )

        assert response.status_code == 409
        assert _error(response)["code"] == "ALREADY_EXISTS"

    @pytest.mark.parametrize("name", ["foo-bar", "all", "documents", _TOO_LONG])
    async def test_a_name_that_could_not_be_an_identifier_is_a_400(
        self, client: AsyncClient, claimed_by_nobody: None, name: str
    ) -> None:
        """The route reached no rule at all; only `documents` was refused.

        A row with a 70-character name was accepted here and truncated onto
        another collection's table at the first ingest, because nothing between
        this schema's `max_length=255` and Postgres bounded it (#368).
        """
        response = await client.post(f"{settings.API_V1_STR}/kb", json=self._payload(name))

        assert response.status_code == 400
        assert _error(response)["details"]["collection"] == name
