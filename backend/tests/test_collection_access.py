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

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import pytest

from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.rag_document import RAGDocument
from app.db.models.resource_grant import GrantLevel, Visibility
from app.db.models.sync_log import SyncLog
from app.db.models.sync_source import SyncSource
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
        knowledge_base_repo,
        rag_document_repo,
        sync_log_repo,
        sync_source_repo,
    )

    async def list_by_collection_name(_db: object, collection_name: str) -> list[KnowledgeBase]:
        return [kb for kb in rows.collections if kb.collection_name == collection_name]

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

    monkeypatch.setattr(knowledge_base_repo, "list_by_collection_name", list_by_collection_name)
    monkeypatch.setattr(knowledge_base_repo, "get_accessible", get_accessible)
    monkeypatch.setattr(rag_document_repo, "get_by_id", by_id("documents"))
    monkeypatch.setattr(sync_source_repo, "get_by_id", by_id("sources"))
    monkeypatch.setattr(sync_log_repo, "get_by_id", by_id("logs"))
    return CollectionAccessService(db=None)  # ty: ignore[invalid-argument-type]


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

    async def test_a_listing_filtered_to_one_collection_still_has_to_resolve_it(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        rows.collections = [_kb("handbook")]
        rows.accessible = [_kb("handbook"), _kb("notes")]

        assert await service.readable_names_for(_ctx(), "handbook") == ["handbook"]
        assert await service.readable_names_for(_ctx(), None) == ["handbook", "notes"]
        with pytest.raises(NotFoundError):
            await service.readable_names_for(_ctx(), "someone_elses")


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

    async def test_a_name_another_organization_owns_is_refused(
        self, service: CollectionAccessService, rows: Rows
    ) -> None:
        """They would share one vector table, which is the whole problem."""
        rows.collections = [_kb("handbook", organization_id=OTHER_ORG)]

        with pytest.raises(AlreadyExistsError):
            await service.claim(_ctx(), "handbook")


def _document(collection_name: str) -> RAGDocument:
    return RAGDocument(
        id=uuid.uuid4(),
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
