"""Tests for Knowledge Base scoping - personal / org / app access rules."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.resource_grant import GrantLevel, Visibility
from app.repositories.rag_document import CollectionCounts
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.services.ingestion_config import deployment_defaults
from app.services.knowledge_base import KnowledgeBaseService, _with_counts


def _ctx(
    *,
    organization_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    role: str = OrgRoleName.OWNER.value,
    app_admin: bool = False,
) -> AuthContext:
    return AuthContext(
        user_id=user_id or uuid.uuid4(),
        organization_id=organization_id or uuid.uuid4(),
        role=role,
        is_app_admin=app_admin,
    )


@pytest.fixture
def unclaimed_collection_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Creating a base claims its collection name, which reads the KB table.

    Nobody holds the names these tests use, and the answer is not what they are
    about - see `tests/api/test_collection_name_routes.py` for the claim itself.
    Without this, the lookup reaches the `MagicMock` standing in for a session.
    """
    from app.repositories import knowledge_base_repo

    async def held_by_nobody(_db: object, collection_name: str) -> list[KnowledgeBase]:
        del collection_name
        return []

    monkeypatch.setattr(knowledge_base_repo, "list_by_collection_name", held_by_nobody)


def _kb(
    scope: str,
    owner_user_id=None,
    organization_id=None,
    is_default: bool = False,
    visibility: str = Visibility.PRIVATE.value,
):
    kb = MagicMock()
    kb.id = uuid.uuid4()
    kb.scope = scope
    kb.owner_user_id = owner_user_id
    kb.organization_id = organization_id
    kb.is_default = is_default
    kb.visibility = visibility
    return kb


def _readable_kb(collection_name: str) -> KnowledgeBase:
    """A real ORM row, because this one goes through the response schema.

    Deliberately not the `MagicMock` the scoping tests use. `KnowledgeBaseRead`
    validates `from_attributes`, and a `MagicMock` answers *every* attribute -
    including the three counts, which it hands over as mocks that Pydantic
    coerces to `1`. The test then passes while asserting nothing, or fails while
    the code is correct. A real row has no such attributes, so the schema
    defaults are what get exercised.
    """
    return KnowledgeBase(
        id=uuid.uuid4(),
        name="Collection",
        description=None,
        scope=KBScope.ORG.value,
        collection_name=collection_name,
        is_default=False,
        visibility=Visibility.ORG.value,
        ingestion_config=deployment_defaults().model_dump(mode="json"),
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        embedding_secret_id=None,
        organization_id=uuid.uuid4(),
        owner_user_id=None,
        created_at=datetime(2026, 7, 31, tzinfo=UTC),
        updated_at=None,
    )


class TestKBAccessControl:
    """Service-level access checks for all 3 scopes (PostgreSQL async)."""

    @pytest.fixture
    def mock_db(self):
        return MagicMock()

    @pytest.mark.anyio
    async def test_personal_kb_visible_to_owner(self, mock_db):
        user_id = uuid.uuid4()
        kb = _kb("personal", owner_user_id=user_id)

        with patch(
            "app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)
        ):
            svc = KnowledgeBaseService(mock_db)
            result = await svc.get(kb.id, ctx=_ctx(user_id=user_id))
            assert result is kb

    @pytest.mark.anyio
    async def test_personal_kb_hidden_from_other_user(self, mock_db):
        kb = _kb("personal", owner_user_id=uuid.uuid4())

        with patch(
            "app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)
        ):
            svc = KnowledgeBaseService(mock_db)
            with pytest.raises(NotFoundError):
                await svc.get(kb.id, ctx=_ctx())

    @pytest.mark.anyio
    async def test_org_kb_visible_to_a_role_that_sees_the_whole_org(self, mock_db):
        org_id = uuid.uuid4()
        kb = _kb("org", organization_id=org_id)

        with patch(
            "app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)
        ):
            svc = KnowledgeBaseService(mock_db)
            result = await svc.get(kb.id, ctx=_ctx(organization_id=org_id))
            assert result is kb

    @pytest.mark.anyio
    async def test_a_private_org_kb_is_hidden_from_a_member_who_does_not_own_it(self, mock_db):
        """The audit finding: membership alone used to read every org collection."""
        org_id = uuid.uuid4()
        kb = _kb("org", organization_id=org_id, owner_user_id=uuid.uuid4())

        with (
            patch("app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)),
            patch(
                "app.repositories.resource_grant_repo.get_level", new=AsyncMock(return_value=None)
            ),
        ):
            svc = KnowledgeBaseService(mock_db)
            with pytest.raises(NotFoundError):
                await svc.get(kb.id, ctx=_ctx(organization_id=org_id, role="member"))

    @pytest.mark.anyio
    async def test_an_org_visible_kb_is_readable_by_a_member(self, mock_db):
        org_id = uuid.uuid4()
        kb = _kb(
            "org",
            organization_id=org_id,
            owner_user_id=uuid.uuid4(),
            visibility=Visibility.ORG.value,
        )

        with patch(
            "app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)
        ):
            svc = KnowledgeBaseService(mock_db)
            result = await svc.get(kb.id, ctx=_ctx(organization_id=org_id, role="member"))
            assert result is kb

    @pytest.mark.anyio
    async def test_org_kb_hidden_from_other_org(self, mock_db):
        kb = _kb("org", organization_id=uuid.uuid4())

        with patch(
            "app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)
        ):
            svc = KnowledgeBaseService(mock_db)
            with pytest.raises(NotFoundError):
                await svc.get(kb.id, ctx=_ctx())

    @pytest.mark.anyio
    async def test_app_kb_visible_to_anyone(self, mock_db):
        kb = _kb("app")

        with patch(
            "app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)
        ):
            svc = KnowledgeBaseService(mock_db)
            result = await svc.get(kb.id, ctx=_ctx(role="viewer"))
            assert result is kb

    @pytest.mark.anyio
    async def test_cannot_delete_default_kb(self, mock_db):
        org_id = uuid.uuid4()
        kb = _kb("org", organization_id=org_id, is_default=True)

        with patch(
            "app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)
        ):
            svc = KnowledgeBaseService(mock_db)
            with pytest.raises(BadRequestError):
                await svc.delete(kb.id, ctx=_ctx(organization_id=org_id))

    @pytest.mark.anyio
    async def test_default_kb_in_another_org_is_reported_as_missing_not_undeletable(self, mock_db):
        """The "cannot delete the default" rule must not answer for a row out of reach.

        It is a statement about a specific row, so a caller outside the
        organization getting it back learns that the id exists *and* that it is
        that organization's default base.
        """
        kb = _kb("org", organization_id=uuid.uuid4(), is_default=True)

        with patch(
            "app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)
        ):
            svc = KnowledgeBaseService(mock_db)
            with pytest.raises(NotFoundError):
                await svc.delete(kb.id, ctx=_ctx())

    @pytest.mark.anyio
    async def test_non_app_admin_cannot_create_app_kb(self, mock_db):
        data = KnowledgeBaseCreate(name="Global KB", scope="app", collection_name="global")

        svc = KnowledgeBaseService(mock_db)
        with pytest.raises(AuthorizationError):
            await svc.create(data, ctx=_ctx())

    @pytest.mark.anyio
    async def test_app_admin_can_create_app_kb(self, mock_db, unclaimed_collection_name):
        data = KnowledgeBaseCreate(name="Global KB", scope="app", collection_name="global")
        mock_kb = MagicMock()

        with patch(
            "app.repositories.knowledge_base_repo.create", new=AsyncMock(return_value=mock_kb)
        ):
            svc = KnowledgeBaseService(mock_db)
            result = await svc.create(data, ctx=_ctx(app_admin=True))
            assert result is mock_kb

    @pytest.mark.anyio
    async def test_an_org_kb_is_created_owned_by_its_creator(
        self, mock_db, unclaimed_collection_name
    ):
        """`own` in the matrix is meaningless for a row nobody owns."""
        creator = uuid.uuid4()
        data = KnowledgeBaseCreate(name="Team KB", scope="org", collection_name="team")

        with patch(
            "app.repositories.knowledge_base_repo.create", new=AsyncMock(return_value=MagicMock())
        ) as created:
            svc = KnowledgeBaseService(mock_db)
            await svc.create(data, ctx=_ctx(user_id=creator))

        assert created.call_args.kwargs["owner_user_id"] == creator

    @pytest.mark.anyio
    async def test_personal_kb_owner_can_delete(self, mock_db):
        user_id = uuid.uuid4()
        kb = _kb("personal", owner_user_id=user_id)

        with (
            patch("app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)),
            patch("app.repositories.knowledge_base_repo.delete", new=AsyncMock(return_value=True)),
        ):
            svc = KnowledgeBaseService(mock_db)
            await svc.delete(kb.id, ctx=_ctx(user_id=user_id))

    @pytest.mark.anyio
    async def test_personal_kb_non_owner_is_refused_as_missing(self, mock_db):
        """Somebody else's personal base is reported absent, not forbidden.

        The read path has always answered this way; the write path answering 403
        made it a way to confirm that a `kb_id` belongs to somebody.
        """
        kb = _kb("personal", owner_user_id=uuid.uuid4())

        with patch(
            "app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)
        ):
            svc = KnowledgeBaseService(mock_db)
            with pytest.raises(NotFoundError):
                await svc.delete(kb.id, ctx=_ctx())

    @pytest.mark.anyio
    async def test_app_kb_non_admin_is_refused_as_forbidden(self, mock_db):
        """The one write refusal that stays a 403: the caller can read the row anyway."""
        kb = _kb("app")

        with patch(
            "app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)
        ):
            svc = KnowledgeBaseService(mock_db)
            with pytest.raises(AuthorizationError):
                await svc.delete(kb.id, ctx=_ctx())

    @pytest.mark.anyio
    async def test_a_viewer_who_can_read_an_org_kb_cannot_write_to_it(self, mock_db):
        """The audit finding: the six per-KB write routes resolved READ access only.

        A Viewer holds `collections:view` and nothing else, so uploading,
        deleting documents and wiring sync sources must refuse them - as a 403,
        because an org-visible row is one they can already open through
        `GET /kb/{kb_id}`.
        """
        org_id = uuid.uuid4()
        kb = _kb("org", organization_id=org_id, visibility=Visibility.ORG.value)
        ctx = _ctx(organization_id=org_id, role=OrgRoleName.VIEWER.value)

        with (
            patch("app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)),
            patch(
                "app.repositories.resource_grant_repo.get_level", new=AsyncMock(return_value=None)
            ),
        ):
            svc = KnowledgeBaseService(mock_db)
            with pytest.raises(AuthorizationError):
                await svc.get_for_write(kb.id, ctx=ctx)

    @pytest.mark.anyio
    async def test_an_edit_grant_lets_a_viewer_write_to_that_one_kb(self, mock_db):
        """A grant widens what a role allows; a role gate on the route could not see it."""
        org_id = uuid.uuid4()
        kb = _kb("org", organization_id=org_id)
        ctx = _ctx(organization_id=org_id, role=OrgRoleName.VIEWER.value)

        with (
            patch("app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)),
            patch(
                "app.repositories.resource_grant_repo.get_level",
                new=AsyncMock(return_value=GrantLevel.EDIT),
            ),
        ):
            svc = KnowledgeBaseService(mock_db)
            assert await svc.get_for_write(kb.id, ctx=ctx) is kb

    @pytest.mark.anyio
    async def test_a_read_grant_is_not_an_edit_grant(self, mock_db):
        """Levels are ordered: being shown a base is not being handed its contents."""
        org_id = uuid.uuid4()
        kb = _kb("org", organization_id=org_id)
        ctx = _ctx(organization_id=org_id, role=OrgRoleName.VIEWER.value)

        with (
            patch("app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)),
            patch(
                "app.repositories.resource_grant_repo.get_level",
                new=AsyncMock(return_value=GrantLevel.READ),
            ),
        ):
            svc = KnowledgeBaseService(mock_db)
            with pytest.raises(AuthorizationError):
                await svc.get_for_write(kb.id, ctx=ctx)

    @pytest.mark.anyio
    async def test_a_member_writes_their_own_kb_without_a_grant(self, mock_db):
        """`collections:edit: own` reaches the member's own row with no grant lookup."""
        org_id = uuid.uuid4()
        member_id = uuid.uuid4()
        kb = _kb("org", organization_id=org_id, owner_user_id=member_id)
        ctx = _ctx(organization_id=org_id, user_id=member_id, role=OrgRoleName.MEMBER.value)
        grant_lookup = AsyncMock(return_value=None)

        with (
            patch("app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)),
            patch("app.repositories.resource_grant_repo.get_level", new=grant_lookup),
        ):
            svc = KnowledgeBaseService(mock_db)
            assert await svc.get_for_write(kb.id, ctx=ctx) is kb

        grant_lookup.assert_not_called()

    @pytest.mark.anyio
    async def test_a_member_cannot_write_an_org_visible_kb_they_do_not_own(self, mock_db):
        """Org-wide visibility shares *reading*; writing still takes ownership or a grant."""
        org_id = uuid.uuid4()
        kb = _kb(
            "org",
            organization_id=org_id,
            owner_user_id=uuid.uuid4(),
            visibility=Visibility.ORG.value,
        )
        ctx = _ctx(organization_id=org_id, role=OrgRoleName.MEMBER.value)

        with (
            patch("app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)),
            patch(
                "app.repositories.resource_grant_repo.get_level", new=AsyncMock(return_value=None)
            ),
        ):
            svc = KnowledgeBaseService(mock_db)
            with pytest.raises(AuthorizationError):
                await svc.get_for_write(kb.id, ctx=ctx)

    @pytest.mark.anyio
    async def test_a_write_from_another_tenant_is_reported_as_missing(self, mock_db):
        """The write path answers exactly as the read path: 404, never an oracle."""
        kb = _kb("org", organization_id=uuid.uuid4())
        ctx = _ctx()
        grant_lookup = AsyncMock(return_value=GrantLevel.EDIT)

        with (
            patch("app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)),
            patch("app.repositories.resource_grant_repo.get_level", new=grant_lookup),
        ):
            svc = KnowledgeBaseService(mock_db)
            with pytest.raises(NotFoundError):
                await svc.get_for_write(kb.id, ctx=ctx)

        grant_lookup.assert_not_called()

    @pytest.mark.anyio
    async def test_an_app_scoped_kb_refuses_a_member_write_as_forbidden(self, mock_db):
        """Everyone can read an app base, so only the write refusal protects it."""
        kb = _kb("app")

        with patch(
            "app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)
        ):
            svc = KnowledgeBaseService(mock_db)
            with pytest.raises(AuthorizationError):
                await svc.get_for_write(kb.id, ctx=_ctx())

    @pytest.mark.anyio
    async def test_an_app_admin_writes_to_an_app_scoped_kb(self, mock_db):
        kb = _kb("app")
        ctx = _ctx(role=OrgRoleName.VIEWER.value, app_admin=True)

        with patch(
            "app.repositories.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)
        ):
            svc = KnowledgeBaseService(mock_db)
            assert await svc.get_for_write(kb.id, ctx=ctx) is kb

    @pytest.mark.anyio
    async def test_list_accessible_passes_the_callers_scope_to_the_query(self, mock_db):
        """An org-wide role skips the ownership predicate; a narrow one narrows it."""
        ctx = _ctx()

        with patch(
            "app.repositories.knowledge_base_repo.get_accessible",
            new=AsyncMock(return_value=[]),
        ) as mock_list:
            svc = KnowledgeBaseService(mock_db)
            await svc.list_accessible(ctx)

            mock_list.assert_called_once()
            _, kwargs = mock_list.call_args
            assert kwargs.get("user_id") == ctx.user_id
            assert kwargs.get("organization_id") == ctx.organization_id
            assert kwargs.get("see_all_org") is True

    @pytest.mark.anyio
    async def test_list_accessible_narrows_for_a_member_and_carries_their_grants(self, mock_db):
        granted = uuid.uuid4()
        ctx = _ctx(role=OrgRoleName.MEMBER.value)

        with (
            patch(
                "app.repositories.knowledge_base_repo.get_accessible",
                new=AsyncMock(return_value=[]),
            ) as mock_list,
            patch(
                "app.repositories.resource_grant_repo.list_shared_ids",
                new=AsyncMock(return_value=[granted]),
            ),
        ):
            svc = KnowledgeBaseService(mock_db)
            await svc.list_accessible(ctx)

            _, kwargs = mock_list.call_args
            assert kwargs.get("see_all_org") is False
            assert list(kwargs.get("shared_org_ids")) == [granted]


class TestBindingAnEmbeddingSecret:
    """Choosing a vault key for a collection's embeddings.

    Binding a key lends it: the collection bills it for everyone who can write
    the collection. So the chooser has to be able to reach the key themselves,
    and a key they cannot view is refused as one the vault does not hold.
    """

    @pytest.fixture
    def mock_db(self):
        return MagicMock()

    def _secret(self, purpose: str = "openrouter"):
        secret = MagicMock()
        secret.id = uuid.uuid4()
        secret.purpose = purpose
        return secret

    @pytest.mark.anyio
    async def test_a_private_secret_the_caller_cannot_view_is_refused(
        self, mock_db, unclaimed_collection_name
    ):
        """Another member's private key, supplied by id, is turned away.

        Without the caller's `secrets:view` check the org-scoped lookup alone
        binds it - the picker only ever offered keys they can see, but the API
        takes an id and an id is guessable.
        """
        secret = self._secret()
        data = KnowledgeBaseCreate(
            name="Team KB",
            scope="org",
            collection_name="team",
            embedding_secret_id=secret.id,
        )

        with (
            patch(
                "app.repositories.organization_secret_repo.get",
                new=AsyncMock(return_value=secret),
            ),
            patch(
                "app.services.knowledge_base.resolve_access",
                new=AsyncMock(return_value=False),
            ),
            patch("app.repositories.knowledge_base_repo.create", new=AsyncMock()) as created,
        ):
            svc = KnowledgeBaseService(mock_db)
            with pytest.raises(BadRequestError) as exc:
                await svc.create(data, ctx=_ctx(role=OrgRoleName.MEMBER.value))

        assert "not in this organization's vault" in exc.value.message
        created.assert_not_called()

    @pytest.mark.anyio
    async def test_a_secret_the_caller_can_view_is_bound(self, mock_db, unclaimed_collection_name):
        secret = self._secret()
        data = KnowledgeBaseCreate(
            name="Team KB",
            scope="org",
            collection_name="team",
            embedding_secret_id=secret.id,
        )

        with (
            patch(
                "app.repositories.organization_secret_repo.get",
                new=AsyncMock(return_value=secret),
            ),
            patch(
                "app.services.knowledge_base.resolve_access",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.repositories.knowledge_base_repo.create",
                new=AsyncMock(return_value=MagicMock()),
            ) as created,
        ):
            svc = KnowledgeBaseService(mock_db)
            await svc.create(data, ctx=_ctx(role=OrgRoleName.MEMBER.value))

        assert created.call_args.kwargs["embedding_secret_id"] == secret.id


class TestCollectionCounts:
    """The listing's document and chunk counts.

    They exist so a picker can tell a filled collection from an empty one, so
    what matters is that the count reaches the response - not that a repository
    was called.
    """

    @pytest.fixture
    def mock_db(self):
        return MagicMock()

    @pytest.mark.anyio
    async def test_counts_are_asked_for_by_collection_name_not_by_id(self, mock_db):
        """`rag_documents` is keyed by collection name; the KB id is not in it.

        A count keyed on the wrong column comes back empty rather than wrong,
        which reads on screen as every collection being empty.
        """
        first = _kb("org")
        first.collection_name = "docs_a1b2c3"
        second = _kb("org")
        second.collection_name = "wiki_d4e5f6"

        with patch(
            "app.repositories.rag_document_repo.counts_by_collection",
            new=AsyncMock(return_value={}),
        ) as mock_counts:
            await KnowledgeBaseService(mock_db).counts_for([first, second])

        _, kwargs = mock_counts.call_args
        assert kwargs.get("collections") == ["docs_a1b2c3", "wiki_d4e5f6"]

    @pytest.mark.anyio
    async def test_counting_nothing_asks_the_database_nothing(self, mock_db):
        """An organization with no collections must not issue an `IN ()` query."""
        counts = await KnowledgeBaseService(mock_db).counts_for([])
        assert counts == {}

    def test_a_collection_nothing_was_written_to_reads_as_zero(self):
        """The group query returns no row for an empty collection, not a zero row.

        The listing defaults that absence, so a brand-new collection has to
        render as `0 documents` rather than as a missing key blowing up the
        listing.
        """
        read = _with_counts(_readable_kb("fresh_000000"), None)

        assert read.document_count == 0
        assert read.indexed_count == 0
        assert read.chunk_count == 0

    def test_a_failed_document_still_counts_as_a_document(self):
        """`indexed_count` below `document_count` is how a failure stays visible.

        Reporting only what indexed would make a collection where half the
        uploads died look like a collection half that size, with nothing on the
        listing to suggest otherwise.
        """
        read = _with_counts(
            _readable_kb("half_broken"),
            CollectionCounts(documents=12, chunks=340, indexed=8),
        )

        assert read.document_count == 12
        assert read.indexed_count == 8
        assert read.chunk_count == 340

    @pytest.mark.anyio
    async def test_the_listing_gives_each_row_its_own_counts(self, mock_db):
        """The join is by collection name, so a count cannot land on a sibling.

        Both halves are ordered lists of the same length, which is exactly the
        shape that hides an off-by-one: the filled collection here is second.
        """
        empty = _readable_kb("empty_000000")
        filled = _readable_kb("filled_111111")

        with (
            patch(
                "app.repositories.knowledge_base_repo.get_accessible",
                new=AsyncMock(return_value=[empty, filled]),
            ),
            patch(
                "app.repositories.rag_document_repo.counts_by_collection",
                new=AsyncMock(
                    return_value={
                        "filled_111111": CollectionCounts(documents=3, chunks=90, indexed=3)
                    }
                ),
            ),
        ):
            listing = await KnowledgeBaseService(mock_db).list_readable(_ctx())

        assert listing.total == 2
        assert [item.document_count for item in listing.items] == [0, 3]
        assert [item.chunk_count for item in listing.items] == [0, 90]


class TestRerankConfig:
    """Setting a collection's reranker, and the ways it is refused.

    Reranking is a model and a key together; a lone half reads as configured
    and does nothing, and a key of the wrong purpose bills nobody's reranking.
    Both are refused where the person setting them can see why."""

    @pytest.fixture
    def mock_db(self):
        return MagicMock()

    def _cohere_secret(self, purpose: str = "cohere") -> MagicMock:
        return MagicMock(purpose=purpose)

    @pytest.mark.anyio
    async def test_a_model_without_a_key_is_refused(self, mock_db, unclaimed_collection_name):
        data = KnowledgeBaseCreate(
            name="KB", scope="org", collection_name="c", rerank_model="rerank-v3.5"
        )
        with pytest.raises(BadRequestError, match="both a model and a key"):
            await KnowledgeBaseService(mock_db).create(data, ctx=_ctx())

    @pytest.mark.anyio
    async def test_a_key_without_a_model_is_refused(self, mock_db, unclaimed_collection_name):
        data = KnowledgeBaseCreate(
            name="KB", scope="org", collection_name="c", rerank_secret_id=uuid.uuid4()
        )
        with pytest.raises(BadRequestError, match="both a model and a key"):
            await KnowledgeBaseService(mock_db).create(data, ctx=_ctx())

    @pytest.mark.anyio
    async def test_an_unsupported_model_is_refused_before_the_key_is_read(
        self, mock_db, unclaimed_collection_name
    ):
        # A typo'd model with an otherwise valid key would be stored and shown as
        # configured, then fail every search inside Cohere where the error is
        # swallowed - reranking silently off. Refused at create, and before the
        # vault is even consulted.
        data = KnowledgeBaseCreate(
            name="KB",
            scope="org",
            collection_name="c",
            rerank_model="rerank-v3.5x",
            rerank_secret_id=uuid.uuid4(),
        )
        with (
            patch("app.repositories.organization_secret_repo.get", new=AsyncMock()) as secret_get,
            pytest.raises(BadRequestError, match="Unsupported rerank model"),
        ):
            await KnowledgeBaseService(mock_db).create(data, ctx=_ctx())
        secret_get.assert_not_called()

    @pytest.mark.anyio
    async def test_an_update_to_an_unsupported_model_is_refused(self, mock_db):
        kb = _kb("org", organization_id=uuid.uuid4())
        data = KnowledgeBaseUpdate(rerank_model="bogus", rerank_secret_id=uuid.uuid4())
        with (
            patch.object(KnowledgeBaseService, "get_for_write", new=AsyncMock(return_value=kb)),
            pytest.raises(BadRequestError, match="Unsupported rerank model"),
        ):
            await KnowledgeBaseService(mock_db).update(kb.id, data, ctx=_ctx())

    @pytest.mark.anyio
    async def test_a_configured_pair_is_written_through(self, mock_db, unclaimed_collection_name):
        secret_id = uuid.uuid4()
        data = KnowledgeBaseCreate(
            name="KB",
            scope="org",
            collection_name="c",
            rerank_model="rerank-v3.5",
            rerank_secret_id=secret_id,
        )
        with (
            patch(
                "app.repositories.organization_secret_repo.get",
                new=AsyncMock(return_value=self._cohere_secret()),
            ),
            patch(
                "app.services.knowledge_base.resolve_access",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.repositories.knowledge_base_repo.create",
                new=AsyncMock(return_value=MagicMock()),
            ) as created,
        ):
            await KnowledgeBaseService(mock_db).create(data, ctx=_ctx())

        assert created.call_args.kwargs["rerank_model"] == "rerank-v3.5"
        assert created.call_args.kwargs["rerank_secret_id"] == secret_id

    @pytest.mark.anyio
    async def test_a_key_the_caller_cannot_reach_is_refused_as_missing(
        self, mock_db, unclaimed_collection_name
    ):
        # In the organization's vault, but private to another member: binding it
        # would lend a key `secrets:view` refuses the caller. Refused as a miss,
        # so the refusal cannot be told from "no such key" and used to enumerate.
        data = KnowledgeBaseCreate(
            name="KB",
            scope="org",
            collection_name="c",
            rerank_model="rerank-v3.5",
            rerank_secret_id=uuid.uuid4(),
        )
        with (
            patch(
                "app.repositories.organization_secret_repo.get",
                new=AsyncMock(return_value=self._cohere_secret()),
            ),
            patch(
                "app.services.knowledge_base.resolve_access",
                new=AsyncMock(return_value=False),
            ),
            pytest.raises(BadRequestError, match="not in this organization's vault"),
        ):
            await KnowledgeBaseService(mock_db).create(data, ctx=_ctx())

    @pytest.mark.anyio
    async def test_a_key_of_the_wrong_purpose_is_refused(self, mock_db, unclaimed_collection_name):
        data = KnowledgeBaseCreate(
            name="KB",
            scope="org",
            collection_name="c",
            rerank_model="rerank-v3.5",
            rerank_secret_id=uuid.uuid4(),
        )
        with (
            patch(
                "app.repositories.organization_secret_repo.get",
                new=AsyncMock(return_value=self._cohere_secret(purpose="openrouter")),
            ),
            patch(
                "app.services.knowledge_base.resolve_access",
                new=AsyncMock(return_value=True),
            ),
            pytest.raises(BadRequestError, match="reranking runs through"),
        ):
            await KnowledgeBaseService(mock_db).create(data, ctx=_ctx())

    @pytest.mark.anyio
    async def test_an_update_turns_reranking_off_by_sending_both_null(self, mock_db):
        kb = _kb("org", organization_id=uuid.uuid4())
        data = KnowledgeBaseUpdate(rerank_model=None, rerank_secret_id=None)
        with (
            patch.object(KnowledgeBaseService, "get_for_write", new=AsyncMock(return_value=kb)),
            patch(
                "app.repositories.knowledge_base_repo.update",
                new=AsyncMock(return_value=kb),
            ) as updated,
        ):
            await KnowledgeBaseService(mock_db).update(kb.id, data, ctx=_ctx())

        assert updated.call_args.kwargs["set_rerank"] is True
        assert updated.call_args.kwargs["rerank_model"] is None

    @pytest.mark.anyio
    async def test_an_update_about_something_else_leaves_reranking_alone(self, mock_db):
        kb = _kb("org", organization_id=uuid.uuid4())
        data = KnowledgeBaseUpdate(name="Renamed")
        with (
            patch.object(KnowledgeBaseService, "get_for_write", new=AsyncMock(return_value=kb)),
            patch(
                "app.repositories.knowledge_base_repo.update",
                new=AsyncMock(return_value=kb),
            ) as updated,
        ):
            await KnowledgeBaseService(mock_db).update(kb.id, data, ctx=_ctx())

        assert updated.call_args.kwargs["set_rerank"] is False
