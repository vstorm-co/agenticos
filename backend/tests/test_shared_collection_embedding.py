"""One collection name is one vector table, so it is one embedding space.

`knowledge_bases.collection_name` is not unique: several knowledge bases can
index into the same physical table. Nothing used to make them agree on *how* to
index, and the day per-collection resolution started answering per organization
(#913) that stopped being harmless - two rows on one table with different widths
make pgvector refuse the comparison, and two with the same width and different
models rank one embedding space against another and answer with plausible
nonsense. The credential has the same shape of problem: whichever sibling the
resolver happened to read is the vault key that gets billed.

So a row joining an occupied name adopts that name's configuration, and an
explicit disagreement is refused rather than silently overridden.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.repositories import collection_teardown_repo, knowledge_base_repo
from app.schemas.knowledge_base import KnowledgeBaseCreate
from app.services.knowledge_base import KnowledgeBaseService

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()
SECRET = uuid.uuid4()


def _ctx() -> AuthContext:
    return AuthContext(
        user_id=uuid.uuid4(),
        organization_id=ORG,
        role=OrgRoleName.OWNER.value,
        is_app_admin=False,
    )


def _held(**overrides) -> KnowledgeBase:
    """The row already indexing into `shared`, as the database would hand it back."""
    fields = {
        "id": uuid.uuid4(),
        "name": "Held",
        "scope": KBScope.ORG.value,
        "collection_name": "shared",
        "embedding_model": "text-embedding-3-large",
        "embedding_dim": 3072,
        "embedding_provider": "openai",
        "embedding_secret_id": SECRET,
        "organization_id": ORG,
    } | overrides
    return KnowledgeBase(**fields)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> KnowledgeBaseService:
    """A service whose only live collaborator is `knowledge_base_repo.create`.

    Everything the claim reads is mocked at the repository boundary; each test
    sets `list_by_collection_name` to say who holds the name, which is the one
    input the behaviour turns on.
    """
    monkeypatch.setattr(collection_teardown_repo, "is_reserved", AsyncMock(return_value=False))
    monkeypatch.setattr(knowledge_base_repo, "create", AsyncMock(side_effect=_created))
    monkeypatch.setattr("app.services.collection_access.hold_name", AsyncMock())
    return KnowledgeBaseService(MagicMock())


async def _created(_db: object, **kwargs) -> dict[str, object]:
    """Stand in for the insert, answering with what would have been written."""
    return kwargs


def _holders(monkeypatch: pytest.MonkeyPatch, rows: list[KnowledgeBase]) -> None:
    monkeypatch.setattr(
        knowledge_base_repo, "list_by_collection_name", AsyncMock(return_value=rows)
    )


class TestARowJoiningAnOccupiedName:
    async def test_adopts_the_collections_model_width_and_provider(
        self, service: KnowledgeBaseService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _holders(monkeypatch, [_held()])

        written = await service.create(
            KnowledgeBaseCreate(name="Second", collection_name="shared"), ctx=_ctx()
        )

        assert written["embedding_model"] == "text-embedding-3-large"
        assert written["embedding_dim"] == 3072
        assert written["embedding_provider"] == "openai"

    async def test_adopts_the_credential_so_the_bill_does_not_depend_on_which_row_is_read(
        self, service: KnowledgeBaseService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _holders(monkeypatch, [_held()])

        written = await service.create(
            KnowledgeBaseCreate(name="Second", collection_name="shared"), ctx=_ctx()
        )

        assert written["embedding_secret_id"] == SECRET

    async def test_takes_the_oldest_holder_when_several_already_share_the_name(
        self, service: KnowledgeBaseService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`list_by_collection_name` orders by `created_at`, and the table's width
        was fixed by whichever row was created first."""
        _holders(
            monkeypatch,
            [_held(), _held(embedding_model="text-embedding-3-small", embedding_dim=1536)],
        )

        written = await service.create(
            KnowledgeBaseCreate(name="Third", collection_name="shared"), ctx=_ctx()
        )

        assert written["embedding_dim"] == 3072

    @pytest.mark.parametrize(
        ("field", "payload"),
        [
            ("embedding_model", {"embedding_model": "text-embedding-3-small"}),
            ("embedding_provider", {"embedding_provider": "openrouter"}),
            ("embedding_secret_id", {"embedding_secret_id": uuid.uuid4()}),
        ],
    )
    async def test_refuses_a_choice_that_disagrees_with_the_collection(
        self,
        service: KnowledgeBaseService,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        payload: dict[str, object],
    ) -> None:
        """Silently overriding is worse than refusing: the caller asked for one
        embedding space and would have been given another with nothing on screen
        to say so."""
        _holders(monkeypatch, [_held()])

        with pytest.raises(BadRequestError) as refused:
            await service.create(
                KnowledgeBaseCreate(name="Second", collection_name="shared", **payload),
                ctx=_ctx(),
            )

        assert refused.value.details["fields"][0]["field"] == field

    async def test_accepts_a_choice_that_restates_what_the_collection_already_uses(
        self, service: KnowledgeBaseService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _holders(monkeypatch, [_held()])

        written = await service.create(
            KnowledgeBaseCreate(
                name="Second",
                collection_name="shared",
                embedding_model="text-embedding-3-large",
                embedding_provider="openai",
                embedding_secret_id=SECRET,
            ),
            ctx=_ctx(),
        )

        assert written["embedding_model"] == "text-embedding-3-large"


class TestAFirstRowOnAFreeName:
    async def test_keeps_the_callers_own_choice(
        self, service: KnowledgeBaseService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _holders(monkeypatch, [])

        written = await service.create(
            KnowledgeBaseCreate(
                name="First",
                collection_name="unheld",
                embedding_model="text-embedding-3-small",
            ),
            ctx=_ctx(),
        )

        assert written["embedding_model"] == "text-embedding-3-small"
        assert written["embedding_dim"] == 1536
