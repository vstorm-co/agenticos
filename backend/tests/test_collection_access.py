"""The tenant boundary under /rag, one predicate and one resolver at a time.

`tests/integration/test_platform_flows.py` proves the boundary holds through
the real routes against a real database - that is the test which would have
caught the bug, and it asserts refusals. This file covers the same module from
underneath: the rows a request in that suite never produces (an app-scoped
collection, an id that is not a UUID) and the success paths a refusal test
cannot reach.

The repositories are replaced with an in-memory set of rows that filters the way
the real query does, so `list_by_collection_name` returning two candidates for
one name - the case that makes `get_by_collection_name` unsafe - is expressible
here rather than only against Postgres.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.rag_document import RAGDocument
from app.db.models.resource_grant import GrantLevel, Visibility
from app.db.models.sync_log import SyncLog
from app.db.models.sync_source import SyncSource
from app.db.vector_tables import MAX_COLLECTION_NAME_LENGTH
from app.repositories import collection_teardown_repo
from app.repositories.rag_document import CollectionScope
from app.repositories.sync_log import SyncLogScope
from app.services.collection_access import CollectionAccessService, readable_kb, writable_kb

pytestmark = pytest.mark.anyio

HOME_ORG = uuid.uuid4()
OTHER_ORG = uuid.uuid4()
CALLER = uuid.uuid4()
STRANGER = uuid.uuid4()


def _ctx(
    *,
    organization_id: uuid.UUID = HOME_ORG,
    user_id: uuid.UUID = CALLER,
    role: str = OrgRoleName.OWNER.value,
    app_admin: bool = False,
) -> AuthContext:
    return AuthContext(
        user_id=user_id,
        organization_id=organization_id,
        role=role,
        is_app_admin=app_admin,
    )


def _kb(
    collection_name: str,
    *,
    scope: KBScope = KBScope.ORG,
    organization_id: uuid.UUID | None = HOME_ORG,
    owner_user_id: uuid.UUID | None = None,
    visibility: str = Visibility.PRIVATE.value,
) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=collection_name,
        collection_name=collection_name,
        scope=scope.value,
        organization_id=organization_id,
        owner_user_id=owner_user_id,
        visibility=visibility,
        ingestion_config={},
        embedding_model="text-embedding-3-large",
        embedding_dim=3072,
    )


def _source(*, organization_id: uuid.UUID, collection_name: str = "handbook") -> SyncSource:
    return SyncSource(
        id=uuid.uuid4(),
        organization_id=organization_id,
        name="Drive",
        connector_type="gdrive",
        collection_name=collection_name,
        config={},
    )


@dataclass
class Rows:
    """Everything the fake repositories know about."""

    collections: list[KnowledgeBase] = field(default_factory=list)
    accessible: list[KnowledgeBase] = field(default_factory=list)
    documents: list[RAGDocument] = field(default_factory=list)
    sources: list[SyncSource] = field(default_factory=list)
    logs: list[SyncLog] = field(default_factory=list)
    # (user_id, resource_id) -> grant level, read by the resolve_access fallback.
    grants: dict[tuple[uuid.UUID, uuid.UUID], GrantLevel] = field(default_factory=dict)


@pytest.fixture
def rows() -> Rows:
    return Rows()


@pytest.fixture(autouse=True)
def _grant_repo(rows: Rows, monkeypatch: pytest.MonkeyPatch) -> None:
    """`resolve_access` falls back to the grant table; give it these rows'.

    Autouse because the predicate functions consult it without going through
    the service fixture - a bare `readable_kb` call on an org row already can.
    """
    from app.repositories import resource_grant_repo

    async def get_level(
        _db: object,
        *,
        organization_id: uuid.UUID,
        subject_user_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
    ) -> GrantLevel | None:
        del organization_id, resource_type
        return rows.grants.get((subject_user_id, resource_id))

    async def list_shared_ids(
        _db: object,
        *,
        organization_id: uuid.UUID,
        subject_user_id: uuid.UUID,
        resource_type: str,
        minimum_level: GrantLevel,
    ) -> list[uuid.UUID]:
        del organization_id, resource_type, minimum_level
        return [rid for (uid, rid) in rows.grants if uid == subject_user_id]

    monkeypatch.setattr(resource_grant_repo, "get_level", get_level)
    monkeypatch.setattr(resource_grant_repo, "list_shared_ids", list_shared_ids)


@pytest.fixture
def service(rows: Rows, monkeypatch: pytest.MonkeyPatch) -> CollectionAccessService:
    from app.repositories import (
        collection_teardown_repo,
        knowledge_base_repo,
        rag_document_repo,
        sync_log_repo,
        sync_source_repo,
    )

    async def list_by_collection_name(_db: object, collection_name: str) -> list[KnowledgeBase]:
        return [kb for kb in rows.collections if kb.collection_name == collection_name]

    async def not_reserved(_db: object, _name: str) -> bool:
        return False

    monkeypatch.setattr(collection_teardown_repo, "is_reserved", not_reserved)

    async def get_accessible(_db: object, **_kwargs: object) -> list[KnowledgeBase]:
        return rows.accessible

    def by_id[T: RAGDocument | SyncSource | SyncLog](
        table: str,
    ) -> Callable[[object, uuid.UUID], Awaitable[T | None]]:
        """A `get_by_id` that reads the list at call time.

        Closing over `getattr(rows, table)` instead of the list itself: a test
        that assigns `rows.documents = [...]` rebinds the attribute, and a
        closure over the original list would never see the row.
        """

        async def get(_db: object, row_id: uuid.UUID) -> T | None:
            return next((row for row in getattr(rows, table) if row.id == row_id), None)

        return get

    async def list_by_collection_names(
        _db: object, collection_names: list[str]
    ) -> dict[str, list[KnowledgeBase]]:
        by_name: dict[str, list[KnowledgeBase]] = {}
        for kb in rows.collections:
            if kb.collection_name in collection_names:
                by_name.setdefault(kb.collection_name, []).append(kb)
        return by_name

    async def sources_by(
        _db: object, *, organization_id: uuid.UUID | None, collection_name: str
    ) -> list[SyncSource]:
        return [
            source
            for source in rows.sources
            if source.collection_name == collection_name
            and (organization_id is None or source.organization_id == organization_id)
        ]

    async def list_for_collections(_db: object, collection_names: list[str]) -> list[SyncSource]:
        return [source for source in rows.sources if source.collection_name in collection_names]

    async def is_in_collection_scope(
        _db: object, doc_id: uuid.UUID, *, scope: CollectionScope
    ) -> bool:
        """`in_collection_scope`, over these rows: filed under the base, or unfiled
        and tagged with its tenant when the base takes unfiled rows."""
        doc = next(row for row in rows.documents if row.id == doc_id)
        owned = doc.knowledge_base_id == scope.knowledge_base_id or (
            scope.takes_unfiled
            and doc.knowledge_base_id is None
            and doc.organization_id == scope.tenant
        )
        return doc.collection_name == scope.collection_name and owned

    monkeypatch.setattr(knowledge_base_repo, "list_by_collection_name", list_by_collection_name)
    monkeypatch.setattr(knowledge_base_repo, "list_by_collection_names", list_by_collection_names)
    monkeypatch.setattr(sync_source_repo, "get_all", sources_by)
    monkeypatch.setattr(sync_source_repo, "list_for_collections", list_for_collections)
    monkeypatch.setattr(knowledge_base_repo, "get_accessible", get_accessible)
    monkeypatch.setattr(rag_document_repo, "is_in_collection_scope", is_in_collection_scope)
    monkeypatch.setattr(rag_document_repo, "get_by_id", by_id("documents"))
    monkeypatch.setattr(sync_source_repo, "get_by_id", by_id("sources"))
    monkeypatch.setattr(sync_log_repo, "get_by_id", by_id("logs"))
    # A stand-in session whose only job is to carry the advisory-lock execute the
    # claim path takes (#1355); every repository call the tests exercise is patched.
    return CollectionAccessService(db=MagicMock(execute=AsyncMock()))  # ty: ignore[invalid-argument-type]


class TestWhoMayReadACollection:
    """`readable_kb`: the rule `/rag` and `/kb` share, scope and grants included."""

    async def test_an_org_collection_is_readable_by_a_role_that_sees_the_whole_org(self) -> None:
        assert await readable_kb(None, _ctx(), _kb("handbook"))

    async def test_a_private_org_collection_is_hidden_from_a_member_who_does_not_own_it(
        self,
    ) -> None:
        """The matrix says Member holds `collections:view: shared` - a private
        row someone else owns is exactly what that scope does not reach. This
        was the hole: any member could read any org collection.
        """
        kb = _kb("handbook", owner_user_id=STRANGER)

        assert not await readable_kb(None, _ctx(role=OrgRoleName.MEMBER.value), kb)

    async def test_a_member_reads_their_own_and_the_org_visible_collections(self) -> None:
        member = _ctx(role=OrgRoleName.MEMBER.value)

        assert await readable_kb(None, member, _kb("mine", owner_user_id=CALLER))
        assert await readable_kb(
            None, member, _kb("shared", owner_user_id=STRANGER, visibility=Visibility.ORG.value)
        )

    async def test_a_grant_lifts_one_collection_into_reach_without_a_promotion(
        self, rows: Rows
    ) -> None:
        kb = _kb("handbook", owner_user_id=STRANGER)
        viewer = _ctx(role=OrgRoleName.VIEWER.value)

        assert not await readable_kb(None, viewer, kb)
        rows.grants[(CALLER, kb.id)] = GrantLevel.READ
        assert await readable_kb(None, viewer, kb)

    async def test_an_organizations_collection_is_not_readable_from_another_organization(
        self,
    ) -> None:
        """Even by the user who owns the row - the organization is checked, not the owner."""
        kb = _kb("handbook", organization_id=OTHER_ORG, owner_user_id=CALLER)

        assert not await readable_kb(None, _ctx(), kb)

    async def test_an_org_collection_with_no_organization_matches_no_caller(self) -> None:
        assert not await readable_kb(None, _ctx(), _kb("orphan", organization_id=None))

    async def test_a_personal_collection_is_readable_only_by_its_owner(self) -> None:
        kb = _kb("notes", scope=KBScope.PERSONAL, owner_user_id=CALLER)

        assert await readable_kb(None, _ctx(), kb)
        assert not await readable_kb(None, _ctx(user_id=STRANGER), kb)

    async def test_a_key_reaches_its_issuers_personal_collection_only_within_its_scopes(
        self,
    ) -> None:
        """Codex on #2062: an `agents:view` key read and deleted personal documents."""
        kb = _kb("notes", scope=KBScope.PERSONAL, owner_user_id=CALLER)

        def key(*perms: Perm) -> AuthContext:
            return AuthContext(
                user_id=CALLER,
                organization_id=HOME_ORG,
                role=OrgRoleName.OWNER.value,
                api_key_id=uuid.uuid4(),
                key_scopes=frozenset(perms),
            )

        assert not await readable_kb(None, key(Perm.AGENTS_VIEW), kb)
        assert not await writable_kb(None, key(Perm.AGENTS_VIEW), kb)
        assert await readable_kb(None, key(Perm.COLLECTIONS_VIEW), kb)
        assert not await writable_kb(None, key(Perm.COLLECTIONS_VIEW), kb)
        assert await writable_kb(None, key(Perm.COLLECTIONS_EDIT), kb)

    async def test_an_app_collection_is_readable_by_everyone(self) -> None:
        """Deployment-wide by design: created only by a platform admin, for everyone."""
        kb = _kb("templates", scope=KBScope.APP, organization_id=None)

        assert await readable_kb(None, _ctx(user_id=STRANGER, organization_id=OTHER_ORG), kb)


class TestWhoMayWriteToACollection:
    async def test_an_owner_role_writes_any_org_collection(self) -> None:
        assert await writable_kb(None, _ctx(), _kb("handbook"))

    async def test_a_member_writes_their_own_collection_and_not_a_strangers(self) -> None:
        """`collections:edit: own` - and org-wide visibility only shares *reading*."""
        member = _ctx(role=OrgRoleName.MEMBER.value)

        assert await writable_kb(None, member, _kb("mine", owner_user_id=CALLER))
        assert not await writable_kb(
            None, member, _kb("shared", owner_user_id=STRANGER, visibility=Visibility.ORG.value)
        )

    async def test_an_edit_grant_admits_a_caller_whose_role_does_not(self, rows: Rows) -> None:
        kb = _kb("handbook", owner_user_id=STRANGER)
        member = _ctx(role=OrgRoleName.MEMBER.value)

        assert not await writable_kb(None, member, kb)
        rows.grants[(CALLER, kb.id)] = GrantLevel.EDIT
        assert await writable_kb(None, member, kb)

    async def test_a_read_grant_does_not_admit_a_write(self, rows: Rows) -> None:
        kb = _kb("handbook", owner_user_id=STRANGER)
        rows.grants[(CALLER, kb.id)] = GrantLevel.READ

        assert not await writable_kb(None, _ctx(role=OrgRoleName.MEMBER.value), kb)

    async def test_an_app_collection_is_writable_only_by_a_platform_admin(self) -> None:
        """Everyone reads it, so a single tenant editing it would edit everyone's."""
        kb = _kb("templates", scope=KBScope.APP, organization_id=None)

        assert not await writable_kb(None, _ctx(), kb)
        assert await writable_kb(None, _ctx(app_admin=True), kb)


class TestResolvingACollectionName:
    async def test_the_callers_own_row_decides_when_two_organizations_share_a_name(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """The reason this scans candidates instead of taking the first row.

        `collection_name` is not unique. Order the other tenant's row first,
        which is exactly what `get_by_collection_name` would have returned.
        """
        theirs = _kb("handbook", organization_id=OTHER_ORG)
        mine = _kb("handbook")
        rows.collections = [theirs, mine]

        assert (await service.readable(_ctx(), "handbook")).id == mine.id
        assert (await service.writable(_ctx(), "handbook")).id == mine.id

    async def test_a_name_nobody_reachable_owns_is_not_found(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        rows.collections = [_kb("handbook", organization_id=OTHER_ORG)]

        with pytest.raises(NotFoundError) as reading:
            await service.readable(_ctx(), "handbook")
        with pytest.raises(NotFoundError) as writing:
            await service.writable(_ctx(), "handbook")

        assert reading.value.message == "Collection not found"
        assert writing.value.message == reading.value.message

    async def test_every_name_in_a_search_must_resolve_or_none_of_them_do(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        rows.collections = [_kb("mine"), _kb("theirs", organization_id=OTHER_ORG)]

        assert [kb.collection_name for kb in await service.readable_all(_ctx(), ["mine"])] == [
            "mine"
        ]
        with pytest.raises(NotFoundError):
            await service.readable_all(_ctx(), ["mine", "theirs"])

    async def test_a_collection_named_twice_is_listed_once(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """Two knowledge bases can point at one collection; a listing names it once."""
        rows.accessible = [_kb("handbook"), _kb("handbook"), _kb("notes")]

        assert await service.readable_names(_ctx()) == ["handbook", "notes"]

    async def test_a_run_listing_filtered_to_one_collection_still_has_to_resolve_it(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        handbook, notes = _kb("handbook"), _kb("notes")
        rows.collections = [handbook, notes]
        rows.accessible = [handbook, notes]

        assert await service.readable_sync_log_scope(_ctx(), "handbook") == SyncLogScope(
            collections=["handbook"], sync_source_ids=[]
        )
        assert await service.readable_sync_log_scope(_ctx(), None) == SyncLogScope(
            collections=["handbook", "notes"], sync_source_ids=[]
        )
        with pytest.raises(NotFoundError):
            await service.readable_sync_log_scope(_ctx(), "someone_elses")

    @pytest.mark.security
    async def test_a_run_listing_takes_only_the_sources_feeding_a_base_the_caller_reads(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """#2486: a member reading only the app base must not list the runs of a
        private base of their organization sharing its name."""
        app_kb = _kb("handbook", scope=KBScope.APP, organization_id=None)
        private = _kb("handbook", owner_user_id=STRANGER)
        rows.collections = [app_kb, private]
        ours = _source(organization_id=HOME_ORG)
        apps = _source(organization_id=OTHER_ORG)
        rows.sources = [ours, apps]
        member = _ctx(role=OrgRoleName.MEMBER.value)

        scope = await service.readable_sync_log_scope(member, "handbook")

        assert scope == SyncLogScope(collections=["handbook"], sync_source_ids=[apps.id])

    async def test_a_document_listing_carries_each_collection_s_knowledge_base(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """The name alone is not a tenant; the listing filters on the base."""
        handbook = _kb("handbook")
        shared = _kb("shared", scope=KBScope.APP, organization_id=None)
        rows.collections = [handbook]
        rows.accessible = [handbook, shared]

        assert await service.readable_scopes_for(_ctx(), "handbook") == [
            CollectionScope.of(handbook)
        ]
        assert await service.readable_scopes_for(_ctx(), None) == [
            CollectionScope.of(handbook),
            CollectionScope.of(shared),
        ]

    @pytest.mark.security
    async def test_a_name_resolves_to_every_base_claiming_it_that_the_caller_reads(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """An app base and an organization's can share a name; each holds its own rows,
        so a caller reading both lists both, and one reading neither is refused."""
        app_kb = _kb("handbook", scope=KBScope.APP, organization_id=None)
        mine = _kb("handbook")
        rows.collections = [app_kb, mine, _kb("handbook", organization_id=OTHER_ORG)]

        assert await service.readable_scopes_for(_ctx(), "handbook") == [
            CollectionScope.of(app_kb),
            CollectionScope.of(mine),
        ]
        with pytest.raises(NotFoundError):
            await service.readable_scopes_for(_ctx(), "someone_elses")


class TestClaimingACollectionName:
    async def test_a_free_name_can_be_claimed(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        rows.collections = []

        await service.claim(_ctx(), "handbook")

    async def test_a_name_the_caller_already_owns_stays_claimable(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """Creating the same collection twice is idempotent, not a collision."""
        rows.collections = [_kb("handbook")]

        await service.claim(_ctx(), "handbook")

    async def test_claiming_a_valid_name_takes_the_teardown_lock(
        self, service: CollectionAccessService, rows: Rows, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The claim and a concurrent teardown of the same name serialize on one lock,
        so a base created between the drop's re-check and its DROP keeps its table
        (#1355). Taken after the identifier rule, which needs no database."""
        from app.db.locks import LockScope

        rows.collections = []
        lock = AsyncMock()
        monkeypatch.setattr("app.services.collection_access.hold_name", lock)

        await service.claim(_ctx(), "handbook")

        lock.assert_awaited_once_with(service.db, LockScope.COLLECTION_TEARDOWN, "handbook")

    async def test_a_name_another_organization_owns_is_refused(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """They would share one vector table, which is the whole problem."""
        rows.collections = [_kb("handbook", organization_id=OTHER_ORG)]

        with pytest.raises(AlreadyExistsError):
            await service.claim(_ctx(), "handbook")

    async def test_a_reserved_name_is_refused_until_its_teardown_finishes(
        self, service: CollectionAccessService, rows: Rows, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A name whose last row is gone but whose table has not been dropped yet
        carries a teardown reservation; claiming it would adopt that lingering,
        populated table, so it is refused until the cleanup releases it (#1362)."""
        rows.collections = []
        monkeypatch.setattr(collection_teardown_repo, "is_reserved", AsyncMock(return_value=True))

        with pytest.raises(AlreadyExistsError):
            await service.claim(_ctx(), "handbook")

    @pytest.mark.parametrize(
        "name", ["foo-bar", "all", "documents", "a" * (MAX_COLLECTION_NAME_LENGTH + 1)]
    )
    async def test_a_name_that_could_not_be_an_identifier_is_refused_before_the_rows(
        self, service: CollectionAccessService, rows: Rows, name: str
    ) -> None:
        """Claiming is two questions, and this is the one needing no database.

        Asserted here rather than only against the pure function because this is
        the method both write paths call, and it is the reason neither of them
        needs a rule of its own. The rules themselves are
        `tests/test_collection_name_rules.py`.
        """
        rows.collections = []

        with pytest.raises(BadRequestError):
            await service.claim(_ctx(), name)


def _document(
    collection_name: str,
    organization_id: uuid.UUID | None = HOME_ORG,
    *,
    kb: KnowledgeBase | None = None,
) -> RAGDocument:
    return RAGDocument(
        id=uuid.uuid4(),
        organization_id=organization_id,
        knowledge_base_id=None if kb is None else kb.id,
        collection_name=collection_name,
        filename="handbook.pdf",
        filesize=1,
        filetype="pdf",
        status="done",
    )


class TestResolvingADocument:
    async def test_a_document_in_a_reachable_collection_is_returned(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        doc = _document("handbook")
        rows.collections = [_kb("handbook")]
        rows.documents = [doc]

        assert (await service.readable_document(_ctx(), str(doc.id))).id == doc.id
        assert (await service.writable_document(_ctx(), str(doc.id))).id == doc.id

    @pytest.mark.security
    async def test_a_document_in_another_tenants_collection_is_reported_as_a_missing_document(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """Not as a missing *collection* - that would confirm the id exists."""
        doc = _document("handbook")
        rows.collections = [_kb("handbook", organization_id=OTHER_ORG)]
        rows.documents = [doc]

        with pytest.raises(NotFoundError) as reading:
            await service.readable_document(_ctx(), str(doc.id))
        with pytest.raises(NotFoundError) as writing:
            await service.writable_document(_ctx(), str(doc.id))

        assert reading.value.message == "Document not found"
        assert writing.value.message == "Document not found"

    @pytest.mark.security
    async def test_another_tenants_document_by_the_same_name_is_a_missing_document(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """Codex on #2062: the caller's own `handbook` admitted every `handbook` document."""
        doc = _document("handbook", organization_id=OTHER_ORG)
        rows.collections = [_kb("handbook")]
        rows.documents = [doc]

        with pytest.raises(NotFoundError):
            await service.readable_document(_ctx(), str(doc.id))
        with pytest.raises(NotFoundError):
            await service.writable_document(_ctx(), str(doc.id))

    async def test_a_document_with_no_knowledge_base_left_is_unreachable(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """An orphan - its collection was dropped - belongs to nobody, so nobody gets it."""
        doc = _document("handbook")
        rows.documents = [doc]

        with pytest.raises(NotFoundError):
            await service.readable_document(_ctx(), str(doc.id))

    async def test_an_id_that_is_not_a_uuid_is_a_missing_document_not_a_crash(
        self, service: CollectionAccessService
    ) -> None:
        """`UUID("../etc/passwd")` used to raise ValueError and answer 500."""
        with pytest.raises(NotFoundError):
            await service.readable_document(_ctx(), "not-an-id")

    @pytest.mark.security
    async def test_an_app_base_reaches_its_own_rows_and_not_a_same_named_tenants(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """#2486: an app base is readable by everyone, and used to match every row by
        its name - another organization's document, opened by any member of any."""
        app_kb = _kb("handbook", scope=KBScope.APP, organization_id=None)
        theirs = _kb("handbook", organization_id=OTHER_ORG)
        tenants = _document("handbook", OTHER_ORG, kb=theirs)
        uploaded_to_app = _document("handbook", OTHER_ORG, kb=app_kb)
        rows.collections = [app_kb, theirs]
        rows.documents = [tenants, uploaded_to_app]

        with pytest.raises(NotFoundError):
            await service.readable_document(_ctx(), str(tenants.id))
        assert (await service.readable_document(_ctx(), str(uploaded_to_app.id))).id == (
            uploaded_to_app.id
        )


class TestResolvingADocumentInAKnowledgeBase:
    """`kb_document`: the base is authorized already; is the document in it?"""

    async def test_a_document_in_the_base_is_returned(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        kb = _kb("handbook")
        doc = _document("handbook", kb=kb)
        rows.collections = [kb]
        rows.documents = [doc]

        assert (await service.kb_document(kb, str(doc.id))).id == doc.id

    @pytest.mark.security
    async def test_a_row_filed_under_a_same_named_app_base_is_not_the_tenants(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """Uploaded by one of the tenant's members, but into the app base."""
        kb = _kb("handbook")
        app_kb = _kb("handbook", scope=KBScope.APP, organization_id=None)
        doc = _document("handbook", kb=app_kb)
        rows.collections = [kb, app_kb]
        rows.documents = [doc]

        with pytest.raises(NotFoundError) as refusal:
            await service.kb_document(kb, str(doc.id))

        assert refusal.value.message == "Document not found in this knowledge base"
        assert (await service.kb_document(app_kb, str(doc.id))).id == doc.id

    @pytest.mark.security
    async def test_an_app_base_and_a_personal_base_outside_any_organization_keep_apart(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """#2486: neither has an organization, so only the base a row is filed under
        tells them apart; an unfiled row with no organization is the app's."""
        app_kb = _kb("handbook", scope=KBScope.APP, organization_id=None)
        mine = _kb("handbook", scope=KBScope.PERSONAL, organization_id=None, owner_user_id=CALLER)
        personal = _document("handbook", None, kb=mine)
        apps = _document("handbook", None, kb=app_kb)
        unfiled = _document("handbook", None)
        rows.collections = [app_kb, mine]
        rows.documents = [personal, apps, unfiled]

        with pytest.raises(NotFoundError):
            await service.kb_document(app_kb, str(personal.id))
        for doc in (apps, unfiled):
            with pytest.raises(NotFoundError):
                await service.kb_document(mine, str(doc.id))
            assert (await service.kb_document(app_kb, str(doc.id))).id == doc.id
        assert (await service.kb_document(mine, str(personal.id))).id == personal.id

    async def test_a_missing_document_is_reported_as_one(
        self, service: CollectionAccessService
    ) -> None:
        with pytest.raises(NotFoundError) as refusal:
            await service.kb_document(_kb("handbook"), str(uuid.uuid4()))

        assert refusal.value.message == "Document not found"


class TestResolvingASyncSource:
    def _source(self, *, organization_id: uuid.UUID) -> SyncSource:
        return SyncSource(
            id=uuid.uuid4(),
            organization_id=organization_id,
            name="Drive",
            connector_type="gdrive",
            collection_name="handbook",
            config={},
        )

    async def test_a_source_in_the_callers_organization_is_returned(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        source = self._source(organization_id=HOME_ORG)
        rows.sources = [source]

        assert (await service.sync_source(_ctx(), str(source.id))).id == source.id

    async def test_a_source_in_another_organization_is_not_found(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        source = self._source(organization_id=OTHER_ORG)
        rows.sources = [source]

        with pytest.raises(NotFoundError) as refusal:
            await service.sync_source(_ctx(), str(source.id))

        assert refusal.value.message == "Sync source not found"

    async def test_an_id_that_is_not_a_uuid_is_not_found(
        self, service: CollectionAccessService
    ) -> None:
        with pytest.raises(NotFoundError):
            await service.sync_source(_ctx(), "not-an-id")


class TestResolvingASyncSourceInAKnowledgeBase:
    """`kb_sync_source`: a source feeds the base its sync writes under."""

    def _source(
        self, *, organization_id: uuid.UUID, collection_name: str = "handbook"
    ) -> SyncSource:
        return SyncSource(
            id=uuid.uuid4(),
            organization_id=organization_id,
            name="Drive",
            connector_type="gdrive",
            collection_name=collection_name,
            config={},
        )

    async def test_a_source_feeding_the_base_is_returned(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        kb = _kb("handbook")
        source = self._source(organization_id=HOME_ORG)
        rows.collections = [kb]
        rows.sources = [source]

        assert (await service.kb_sync_source(kb, str(source.id))).id == source.id

    @pytest.mark.security
    async def test_an_app_base_reaches_no_source_of_a_tenant_with_its_own_base(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """#2486: by name and organization alone, an app base - readable by everyone -
        reached every organization's source by its name."""
        app_kb = _kb("handbook", scope=KBScope.APP, organization_id=None)
        theirs = _kb("handbook", organization_id=OTHER_ORG)
        tenants = self._source(organization_id=OTHER_ORG)
        apps = self._source(organization_id=HOME_ORG)
        rows.collections = [app_kb, theirs]
        rows.sources = [tenants, apps]

        with pytest.raises(NotFoundError) as refusal:
            await service.kb_sync_source(app_kb, str(tenants.id))
        with pytest.raises(NotFoundError):
            await service.kb_sync_source(theirs, str(apps.id))

        assert refusal.value.message == "Sync source not found in this knowledge base"
        assert (await service.kb_sync_source(theirs, str(tenants.id))).id == tenants.id
        assert (await service.kb_sync_source(app_kb, str(apps.id))).id == apps.id

    @pytest.mark.security
    async def test_a_base_with_no_tenant_reaches_only_the_sources_that_resolve_to_it(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """An app base and a personal base outside any organization share no tenant,
        so a source the sync files under the personal base is not the app base's."""
        mine = _kb("handbook", scope=KBScope.PERSONAL, organization_id=None, owner_user_id=CALLER)
        app_kb = _kb("handbook", scope=KBScope.APP, organization_id=None)
        source = self._source(organization_id=OTHER_ORG)
        rows.collections = [mine, app_kb]
        rows.sources = [source]

        with pytest.raises(NotFoundError):
            await service.kb_sync_source(app_kb, str(source.id))
        assert (await service.kb_sync_source(mine, str(source.id))).id == source.id

    @pytest.mark.security
    async def test_a_source_of_another_collection_or_organization_is_refused(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        kb = _kb("handbook")
        elsewhere = self._source(organization_id=HOME_ORG, collection_name="manuals")
        foreign = self._source(organization_id=OTHER_ORG)
        rows.collections = [kb]
        rows.sources = [elsewhere, foreign]

        for source in (elsewhere, foreign):
            with pytest.raises(NotFoundError):
                await service.kb_sync_source(kb, str(source.id))

    async def test_a_missing_source_is_reported_as_one(
        self, service: CollectionAccessService
    ) -> None:
        with pytest.raises(NotFoundError) as refusal:
            await service.kb_sync_source(_kb("handbook"), "not-an-id")

        assert refusal.value.message == "Sync source not found"


class TestListingAKnowledgeBasesSyncSources:
    """`kb_sync_sources`: the listing applies the rule `kb_sync_source` does."""

    @pytest.mark.security
    async def test_the_app_base_lists_no_source_of_a_private_same_named_base(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """#2486: listed on the name and the caller's organization, a member who
        reads only the app base saw the private base's sources."""
        app_kb = _kb("handbook", scope=KBScope.APP, organization_id=None)
        private = _kb("handbook", owner_user_id=STRANGER)
        ours = _source(organization_id=HOME_ORG)
        rows.collections = [app_kb, private]
        rows.sources = [ours, _source(organization_id=OTHER_ORG)]

        assert await service.kb_sync_sources(_ctx(), app_kb) == []
        assert await service.kb_sync_sources(_ctx(), private) == [ours]

    async def test_a_caller_with_no_organization_still_gets_only_the_bases_own(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """No organization filters nothing in the query; the rule still does."""
        mine = _kb("handbook", scope=KBScope.PERSONAL, organization_id=None, owner_user_id=CALLER)
        theirs = _kb("handbook", organization_id=OTHER_ORG)
        rows.collections = [mine, theirs]
        rows.sources = [_source(organization_id=OTHER_ORG)]
        ctx = AuthContext(user_id=CALLER, organization_id=None, role=None)

        assert await service.kb_sync_sources(ctx, mine) == []


class TestResolvingASyncRun:
    def _log(self, collection_name: str) -> SyncLog:
        return SyncLog(
            id=uuid.uuid4(),
            source="gdrive",
            collection_name=collection_name,
            mode="full",
            status="running",
        )

    async def test_a_run_against_the_callers_collection_is_returned(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        log = self._log("handbook")
        rows.collections = [_kb("handbook")]
        rows.logs = [log]

        assert (await service.sync_log(_ctx(), str(log.id))).id == log.id

    @pytest.mark.security
    async def test_a_run_against_another_tenants_collection_is_not_found(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """A run carries no organization, so its collection is what says whose it is."""
        log = self._log("handbook")
        rows.collections = [_kb("handbook", organization_id=OTHER_ORG)]
        rows.logs = [log]

        with pytest.raises(NotFoundError) as refusal:
            await service.sync_log(_ctx(), str(log.id))

        assert refusal.value.message == "Sync log not found"

    async def test_an_id_that_is_not_a_uuid_is_not_found(
        self, service: CollectionAccessService
    ) -> None:
        with pytest.raises(NotFoundError):
            await service.sync_log(_ctx(), "not-an-id")

    @pytest.mark.security
    async def test_a_sources_run_is_the_writer_of_the_base_the_source_feeds(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """#2486: a writer of one base must not cancel the run of a source feeding a
        same-named base of another tenant - here the app base's."""
        mine = _kb("handbook")
        app_kb = _kb("handbook", scope=KBScope.APP, organization_id=None)
        rows.collections = [app_kb, mine]
        ours, apps = _source(organization_id=HOME_ORG), _source(organization_id=OTHER_ORG)
        rows.sources = [ours, apps]
        our_run, app_run = self._log("handbook"), self._log("handbook")
        our_run.sync_source_id, app_run.sync_source_id = ours.id, apps.id
        rows.logs = [our_run, app_run]

        assert (await service.sync_log(_ctx(), str(our_run.id))).id == our_run.id
        with pytest.raises(NotFoundError):
            await service.sync_log(_ctx(), str(app_run.id))
        assert (await service.sync_log(_ctx(app_admin=True), str(app_run.id))).id == app_run.id

    async def test_a_run_whose_source_is_gone_is_decided_by_its_collection(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        log = self._log("handbook")
        log.sync_source_id = uuid.uuid4()
        rows.collections = [_kb("handbook")]
        rows.logs = [log]

        assert (await service.sync_log(_ctx(), str(log.id))).id == log.id
