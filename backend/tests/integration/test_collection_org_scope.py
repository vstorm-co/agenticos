"""Per-collection resolution stays inside the caller's organization (#913).

`knowledge_bases.collection_name` is indexed but not unique: two organizations
can name a collection the same thing and share one vector table. Resolving by
name alone - `get_by_collection_name(...).first()` - returns whichever row the
database orders first, so an embedding call for org A could land on org B's
knowledge base and unseal *B's* vault key for *A's* request, billing B and
running A's text through B's credential.

A mock would only restate the `WHERE`; these seed two real tenants that share a
name and prove the resolution picks each tenant's own row, falls back to an
app-scoped one, and never crosses to a third tenant - and that the embedding
resolver unseals only the caller organization's key.
"""

import uuid

import pytest
from pydantic import SecretStr

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import Organization
from app.db.models.rag_document import RAGDocument
from app.db.models.sync_log import SyncLog
from app.db.models.sync_source import SyncSource
from app.db.models.user import User
from app.repositories import knowledge_base_repo, rag_document_repo
from app.repositories.rag_document import CollectionScope, IngestionCounts
from app.services.collection_access import CollectionAccessService
from app.services.embedding_resolution import EmbeddingKeySource, embeddings_for_collection
from app.services.knowledge_base import KnowledgeBaseService
from app.services.organization_secret import OrganizationSecretService
from app.services.rag_sync import RAGSyncService

pytestmark = pytest.mark.anyio


async def _org(db, *, name: str) -> tuple[Organization, User]:
    founder = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(founder)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization, founder


def _kb(
    organization_id: uuid.UUID | None,
    collection_name: str,
    *,
    scope: str = KBScope.ORG.value,
    secret_id: uuid.UUID | None = None,
) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=collection_name,
        scope=scope,
        collection_name=collection_name,
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        embedding_provider="openrouter",
        organization_id=organization_id,
        embedding_secret_id=secret_id,
        visibility="org" if scope == KBScope.ORG.value else None,
    )


class TestTheLookupStaysInsideTheOrganization:
    async def test_a_shared_name_resolves_each_organizations_own_row(self, db) -> None:
        org_a, _ = await _org(db, name="Alpha")
        org_b, _ = await _org(db, name="Beta")
        kb_a = _kb(org_a.id, "shared")
        kb_b = _kb(org_b.id, "shared")
        db.add_all([kb_a, kb_b])
        await db.flush()

        resolved_a = await knowledge_base_repo.get_for_collection(db, "shared", org_a.id)
        resolved_b = await knowledge_base_repo.get_for_collection(db, "shared", org_b.id)

        assert resolved_a is not None and resolved_a.id == kb_a.id
        assert resolved_b is not None and resolved_b.id == kb_b.id

    async def test_a_third_organization_gets_no_row_rather_than_a_foreign_one(self, db) -> None:
        """The refusal: a tenant that holds no such collection resolves to None,
        never to another tenant's row of the same name."""
        org_a, _ = await _org(db, name="Alpha")
        org_c, _ = await _org(db, name="Gamma")
        db.add(_kb(org_a.id, "shared"))
        await db.flush()

        assert await knowledge_base_repo.get_for_collection(db, "shared", org_c.id) is None

    async def test_an_app_scoped_row_is_the_fallback_a_foreign_org_row_is_not(self, db) -> None:
        """An app-scoped collection belongs to no organization and is deployment-wide,
        so it is the second-pass match; a third tenant's org-scoped row is never one."""
        org_a, _ = await _org(db, name="Alpha")
        org_c, _ = await _org(db, name="Gamma")
        kb_a = _kb(org_a.id, "shared")
        kb_app = _kb(None, "shared", scope=KBScope.APP.value)
        db.add_all([kb_a, kb_app])
        await db.flush()

        assert (await knowledge_base_repo.get_for_collection(db, "shared", org_a.id)).id == kb_a.id
        assert (
            await knowledge_base_repo.get_for_collection(db, "shared", org_c.id)
        ).id == kb_app.id


class TestTheEmbeddingResolverUnsealsOnlyTheCallersKey:
    @pytest.mark.security
    async def test_a_shared_name_never_unseals_another_tenants_vault_key(self, db) -> None:
        """The security payoff (#913): org A chose its own key; resolving the same
        collection name for org B must not open A's vault entry and bill A - it
        resolves B's own configuration, which here is no key at all."""
        org_a, owner_a = await _org(db, name="Alpha")
        org_b, _ = await _org(db, name="Beta")
        secret = await OrganizationSecretService(db).create(
            AuthContext(user_id=owner_a.id, organization_id=org_a.id, role=OrgRoleName.OWNER),
            name="Alpha key",
            value=ApiKeySecret(api_key=SecretStr("sk-alpha-only")),
            purpose="openrouter",
        )
        db.add_all([_kb(org_a.id, "shared", secret_id=secret.id), _kb(org_b.id, "shared")])
        # The resolver opens its own session, so the rows must be committed.
        await db.commit()

        resolved_a = await embeddings_for_collection("shared", org_a.id)
        resolved_b = await embeddings_for_collection("shared", org_b.id)

        assert resolved_a is not None and resolved_a.api_key == "sk-alpha-only"
        assert resolved_a.key_source is EmbeddingKeySource.ORGANIZATION

        assert resolved_b is not None
        assert resolved_b.api_key == ""
        assert resolved_b.key_source is EmbeddingKeySource.NONE_CHOSEN


class TestTheDocumentListingStaysInsideTheOrganization:
    @pytest.mark.security
    async def test_a_shared_name_lists_only_this_organizations_documents(self, db) -> None:
        """Codex on #2062: the legacy listing filtered on the collection's name alone.

        An app-scoped base is no longer the name alone either: of the rows filed
        under no base, it holds only the untagged one (#2486).
        """
        mine, _ = await _org(db, name="Acme")
        theirs, _ = await _org(db, name="Globex")
        kb_mine = _kb(mine.id, "handbook")
        kb_app = _kb(None, "handbook", scope=KBScope.APP.value)
        db.add_all([kb_mine, kb_app])
        for organization_id, filename in (
            (mine.id, "ours.pdf"),
            (theirs.id, "theirs.pdf"),
            (None, "everyones.pdf"),
        ):
            db.add(
                RAGDocument(
                    organization_id=organization_id,
                    collection_name="handbook",
                    filename=filename,
                    filesize=1,
                    filetype="pdf",
                    status="done",
                )
            )
        await db.flush()

        org_rows, org_total = await rag_document_repo.get_all(
            db, scopes=[CollectionScope.of(kb_mine)]
        )
        app_rows, app_total = await rag_document_repo.get_all(
            db, scopes=[CollectionScope.of(kb_app)]
        )

        assert [row.filename for row in org_rows] == ["ours.pdf"] and org_total == 1
        assert [row.filename for row in app_rows] == ["everyones.pdf"] and app_total == 1
        assert await rag_document_repo.get_all(db, scopes=[]) == ([], 0)


async def _document(
    db, filename: str, *, organization_id: uuid.UUID | None, kb: KnowledgeBase | None
) -> RAGDocument:
    doc = RAGDocument(
        organization_id=organization_id,
        knowledge_base_id=None if kb is None else kb.id,
        collection_name="both",
        filename=filename,
        filesize=1,
        filetype="pdf",
        status="done",
    )
    db.add(doc)
    await db.flush()
    return doc


class TestAnAppCollectionKeepsApartFromASameNamedTenantBase:
    """#2486: an app-scoped base and an organization's base claiming one name.

    An app-scoped base is readable by every member of every organization, and an
    app admin who also edits in organization A can give both bases one name. A
    row matched on that name alone - or on the uploader's organization alone -
    is then org A's document shown to org B through the app base, or an app
    upload by an org A member counted as org A's.
    """

    async def _seed(self, db) -> dict[str, object]:
        org_a, owner_a = await _org(db, name="Alpha")
        org_b, member_b = await _org(db, name="Beta")
        kb_a = _kb(org_a.id, "both")
        db.add(kb_a)
        await db.flush()
        kb_app = _kb(None, "both", scope=KBScope.APP.value)
        db.add(kb_app)
        await db.flush()
        return {
            "kb_a": kb_a,
            "kb_app": kb_app,
            "org_a": org_a,
            "ctx_a": AuthContext(
                user_id=owner_a.id, organization_id=org_a.id, role=OrgRoleName.OWNER
            ),
            "ctx_b": AuthContext(
                user_id=member_b.id, organization_id=org_b.id, role=OrgRoleName.MEMBER
            ),
            "tenant": await _document(db, "tenant.pdf", organization_id=org_a.id, kb=kb_a),
            # An app admin who is an org A member uploads into the app base.
            "app_by_a": await _document(db, "app-by-a.pdf", organization_id=org_a.id, kb=kb_app),
            "app_by_b": await _document(db, "app-by-b.pdf", organization_id=org_b.id, kb=kb_app),
            # A deployment-wide sync's row: no base, no organization.
            "untagged": await _document(db, "untagged.pdf", organization_id=None, kb=None),
        }

    @pytest.mark.security
    async def test_another_organization_lists_only_the_app_bases_documents(self, db) -> None:
        seeded = await self._seed(db)
        access = CollectionAccessService(db)

        scopes = await access.readable_scopes_for(seeded["ctx_b"], "both")
        rows, total = await rag_document_repo.get_all(db, scopes=scopes)

        assert sorted(row.filename for row in rows) == [
            "app-by-a.pdf",
            "app-by-b.pdf",
            "untagged.pdf",
        ]
        assert total == 3

    @pytest.mark.security
    async def test_the_tenants_listing_leaves_out_rows_filed_under_the_app_base(self, db) -> None:
        seeded = await self._seed(db)

        rows, total = await rag_document_repo.get_all(
            db, scopes=[CollectionScope.of(seeded["kb_a"])]
        )

        assert [row.filename for row in rows] == ["tenant.pdf"] and total == 1

    @pytest.mark.security
    async def test_a_tenants_document_is_not_reachable_through_the_app_base(self, db) -> None:
        seeded = await self._seed(db)
        access = CollectionAccessService(db)
        kb_app, kb_a = seeded["kb_app"], seeded["kb_a"]

        with pytest.raises(NotFoundError):
            await access.readable_document(seeded["ctx_b"], str(seeded["tenant"].id))
        with pytest.raises(NotFoundError):
            await access.kb_document(kb_app, str(seeded["tenant"].id))
        # Nor is an app-base row reachable through the tenant's own base.
        with pytest.raises(NotFoundError):
            await access.kb_document(kb_a, str(seeded["app_by_a"].id))

        for key in ("app_by_a", "app_by_b", "untagged"):
            doc_id = str(seeded[key].id)
            assert (await access.readable_document(seeded["ctx_b"], doc_id)).id == seeded[key].id
            assert (await access.kb_document(kb_app, doc_id)).id == seeded[key].id
        assert (await access.kb_document(kb_a, str(seeded["tenant"].id))).id == seeded["tenant"].id

    @pytest.mark.security
    async def test_a_tenants_sync_source_is_not_reachable_through_the_app_base(self, db) -> None:
        """A source carries an organization and no base: it belongs to the base its
        sync writes under, which is its organization's own before an app one."""
        seeded = await self._seed(db)
        access = CollectionAccessService(db)
        kb_app, kb_a = seeded["kb_app"], seeded["kb_a"]
        tenants = SyncSource(
            organization_id=seeded["org_a"].id,
            name="Alpha drive",
            connector_type="gdrive",
            collection_name="both",
            config={},
        )
        # An app admin's source for the app base, filed under an organization
        # that holds no base by this name.
        apps = SyncSource(
            organization_id=seeded["ctx_b"].organization_id,
            name="App drive",
            connector_type="gdrive",
            collection_name="both",
            config={},
        )
        db.add_all([tenants, apps])
        await db.flush()

        with pytest.raises(NotFoundError):
            await access.kb_sync_source(kb_app, str(tenants.id))
        with pytest.raises(NotFoundError):
            await access.kb_sync_source(kb_a, str(apps.id))

        assert (await access.kb_sync_source(kb_a, str(tenants.id))).id == tenants.id
        assert (await access.kb_sync_source(kb_app, str(apps.id))).id == apps.id


class TestAnAppCollectionKeepsApartFromASameNamedPersonalBase:
    """#2486: an app-scoped base and a personal base outside any organization.

    Both have no organization, so a scope keyed on the organization alone cannot
    tell their rows apart: the app base - readable by every member of every
    organization - listed and served the person's documents, and the personal
    base counted the app's. A personal base loses its organization when that
    organization is purged, and its rows are untagged with it.
    """

    async def _seed(self, db) -> dict[str, object]:
        org_b, member_b = await _org(db, name="Beta")
        org_c, owner = await _org(db, name="Gamma")
        kb_app = _kb(None, "both", scope=KBScope.APP.value)
        kb_mine = _kb(None, "both", scope=KBScope.PERSONAL.value)
        kb_mine.owner_user_id = owner.id
        db.add_all([kb_app, kb_mine])
        await db.flush()
        return {
            "kb_app": kb_app,
            "kb_mine": kb_mine,
            "ctx_b": AuthContext(
                user_id=member_b.id, organization_id=org_b.id, role=OrgRoleName.MEMBER
            ),
            "ctx_owner": AuthContext(
                user_id=owner.id, organization_id=org_c.id, role=OrgRoleName.MEMBER
            ),
            "personal": await _document(db, "personal.pdf", organization_id=None, kb=kb_mine),
            "app": await _document(db, "app.pdf", organization_id=org_b.id, kb=kb_app),
            # A deployment-wide sync's row: no base, no organization - the app's.
            "untagged": await _document(db, "untagged.pdf", organization_id=None, kb=None),
        }

    @pytest.mark.security
    async def test_another_organization_does_not_list_the_personal_bases_documents(
        self, db
    ) -> None:
        seeded = await self._seed(db)
        access = CollectionAccessService(db)

        scopes = await access.readable_scopes_for(seeded["ctx_b"], "both")
        rows, total = await rag_document_repo.get_all(db, scopes=scopes)

        assert sorted(row.filename for row in rows) == ["app.pdf", "untagged.pdf"]
        assert total == 2

    @pytest.mark.security
    async def test_a_personal_document_is_not_reachable_through_the_app_base(self, db) -> None:
        seeded = await self._seed(db)
        access = CollectionAccessService(db)
        personal = str(seeded["personal"].id)

        with pytest.raises(NotFoundError):
            await access.readable_document(seeded["ctx_b"], personal)
        with pytest.raises(NotFoundError):
            await access.kb_document(seeded["kb_app"], personal)
        # Nor is an app row reachable through the personal base.
        with pytest.raises(NotFoundError):
            await access.kb_document(seeded["kb_mine"], str(seeded["app"].id))
        with pytest.raises(NotFoundError):
            await access.kb_document(seeded["kb_mine"], str(seeded["untagged"].id))

        assert (await access.readable_document(seeded["ctx_owner"], personal)).id == seeded[
            "personal"
        ].id
        assert (await access.kb_document(seeded["kb_mine"], personal)).id == seeded["personal"].id

    @pytest.mark.security
    async def test_the_personal_listing_holds_its_own_rows_and_not_the_apps(self, db) -> None:
        seeded = await self._seed(db)
        access = CollectionAccessService(db)

        mine, mine_total = await rag_document_repo.get_all(
            db, scopes=[CollectionScope.of(seeded["kb_mine"])]
        )
        # The owner reads both bases by the name, and each brings its own rows.
        both, both_total = await rag_document_repo.get_all(
            db, scopes=await access.readable_scopes_for(seeded["ctx_owner"], "both")
        )

        assert [row.filename for row in mine] == ["personal.pdf"] and mine_total == 1
        assert sorted(row.filename for row in both) == ["app.pdf", "personal.pdf", "untagged.pdf"]
        assert both_total == 3

    @pytest.mark.security
    async def test_the_counts_agree_with_each_bases_listing(self, db) -> None:
        seeded = await self._seed(db)
        seeded["personal"].status = "processing"
        await db.flush()

        mine = await rag_document_repo.ingestion_counts(
            db, scope=CollectionScope.of(seeded["kb_mine"])
        )
        apps = await rag_document_repo.ingestion_counts(
            db, scope=CollectionScope.of(seeded["kb_app"])
        )

        assert mine == IngestionCounts(processing=1, indexed=0, failed=0)
        assert apps == IngestionCounts(processing=0, indexed=2, failed=0)


class TestWhatABaseReportsStaysItsOwn:
    """#2486, the listings around a base: the counts on `GET /kb`, a base's sync
    sources and the sync history under `/rag/sync/logs`.

    Each was keyed on the collection name and the caller's organization, so with
    an app base and a private org base sharing a name, every base reported the
    other's documents and an org member who reads only the app base listed the
    private base's sources and runs.
    """

    async def _seed(self, db) -> dict[str, object]:
        org_a, owner_a = await _org(db, name="Alpha")
        org_b, member_b = await _org(db, name="Beta")
        member_a = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex}@example.com",
            hashed_password="x",
            is_active=True,
        )
        db.add(member_a)
        kb_a = _kb(org_a.id, "both")
        kb_a.owner_user_id = owner_a.id
        kb_a.visibility = "private"
        db.add(kb_a)
        await db.flush()
        kb_app = _kb(None, "both", scope=KBScope.APP.value)
        db.add(kb_app)
        await db.flush()
        tenants = SyncSource(
            organization_id=org_a.id,
            name="Alpha drive",
            connector_type="gdrive",
            collection_name="both",
            config={"folder_id": "alpha-private"},
        )
        # Org B holds no base by the name, so its source's sync writes under the
        # app base.
        apps = SyncSource(
            organization_id=org_b.id,
            name="App drive",
            connector_type="gdrive",
            collection_name="both",
            config={},
        )
        db.add_all([tenants, apps])
        await db.flush()
        tenant_run = SyncLog(
            source="gdrive", collection_name="both", mode="full", sync_source_id=tenants.id
        )
        app_run = SyncLog(
            source="gdrive", collection_name="both", mode="full", sync_source_id=apps.id
        )
        db.add_all([tenant_run, app_run])
        await db.flush()
        await _document(db, "tenant.pdf", organization_id=org_a.id, kb=kb_a)
        await _document(db, "app-by-a.pdf", organization_id=org_a.id, kb=kb_app)
        await _document(db, "app-by-b.pdf", organization_id=org_b.id, kb=kb_app)
        await _document(db, "untagged.pdf", organization_id=None, kb=None)
        return {
            "kb_a": kb_a,
            "kb_app": kb_app,
            "tenants": tenants,
            "apps": apps,
            "tenant_run": tenant_run,
            "app_run": app_run,
            "ctx_owner_a": AuthContext(
                user_id=owner_a.id, organization_id=org_a.id, role=OrgRoleName.OWNER
            ),
            "ctx_member_a": AuthContext(
                user_id=member_a.id, organization_id=org_a.id, role=OrgRoleName.MEMBER
            ),
            "ctx_b": AuthContext(
                user_id=member_b.id, organization_id=org_b.id, role=OrgRoleName.MEMBER
            ),
        }

    @pytest.mark.security
    async def test_each_base_on_the_listing_counts_only_its_own_documents(self, db) -> None:
        seeded = await self._seed(db)

        listing = await KnowledgeBaseService(db).list_readable(seeded["ctx_owner_a"])
        counts = {item.id: item.document_count for item in listing.items}
        other_org = await KnowledgeBaseService(db).list_readable(seeded["ctx_b"])

        assert counts[seeded["kb_a"].id] == 1
        assert counts[seeded["kb_app"].id] == 3
        assert [(item.id, item.document_count) for item in other_org.items] == [
            (seeded["kb_app"].id, 3)
        ]

    @pytest.mark.security
    async def test_the_app_bases_sources_leave_out_a_private_same_named_bases(self, db) -> None:
        seeded = await self._seed(db)
        access = CollectionAccessService(db)

        member_a = await access.kb_sync_sources(seeded["ctx_member_a"], seeded["kb_app"])
        owner_a = await access.kb_sync_sources(seeded["ctx_owner_a"], seeded["kb_a"])
        org_b = await access.kb_sync_sources(seeded["ctx_b"], seeded["kb_app"])

        assert member_a == []
        assert [source.id for source in owner_a] == [seeded["tenants"].id]
        assert [source.id for source in org_b] == [seeded["apps"].id]

    @pytest.mark.security
    async def test_the_sync_history_leaves_out_a_private_same_named_bases_runs(self, db) -> None:
        seeded = await self._seed(db)
        access = CollectionAccessService(db)
        runs = RAGSyncService(db)

        member_a = await runs.list_sync_logs(
            scope=await access.readable_sync_log_scope(seeded["ctx_member_a"], "both")
        )
        owner_a = await runs.list_sync_logs(
            scope=await access.readable_sync_log_scope(seeded["ctx_owner_a"], None)
        )

        assert [item.id for item in member_a.items] == [str(seeded["app_run"].id)]
        assert sorted(item.id for item in owner_a.items) == sorted(
            [str(seeded["app_run"].id), str(seeded["tenant_run"].id)]
        )
