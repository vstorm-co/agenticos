"""Who may reach a RAG collection, and a refusal that gives nothing away.

A collection has two names in this system. One is the vector table the chunks
live in - a string any caller can type into a URL. The other is the
`knowledge_bases` row that owns it, and it is the only one of the two that
knows an organization. The row is therefore the authority: every `/rag` route
resolves the name through it before touching a vector, a document or a sync
source.

Refusals are reported as "not found", with the same message and details an
absent collection produces. Anything else turns the API into an oracle, and
these names are worth guessing: they are derived from what people call their
knowledge bases, so confirming that `acme_handbook_d1fac1` exists somewhere is
already information.

The read rule lives here rather than in :mod:`app.services.knowledge_base` on
purpose. Both surfaces answer the same question about the same rows, and it was
two copies of that question - `/rag/collections` filtering by organization
while `/rag/collections/{name}/info` did not - that let one tenant read
another's collection while the listing looked perfectly scoped.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

# Registers every model table on `Base.metadata`, which `claim` judges a
# caller-chosen name against. Named here rather than left to whichever import
# happens to reach the models first: on an empty metadata the collision check
# answers "nothing collides" with no error to say so.
import app.db.models  # noqa: F401
from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.base import Base
from app.db.locks import LockScope, hold_name
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.rag_document import RAGDocument
from app.db.models.sync_log import SyncLog
from app.db.models.sync_source import SyncSource
from app.db.vector_tables import validate_collection_name
from app.repositories import (
    collection_teardown_repo,
    knowledge_base_repo,
    rag_document_repo,
    sync_log_repo,
    sync_source_repo,
)
from app.repositories.rag_document import CollectionScope
from app.repositories.sync_log import SyncLogScope
from app.services.access import COLLECTION, resolve_access, visible_resource_ids


async def readable_kb(db: AsyncSession, ctx: AuthContext, kb: KnowledgeBase) -> bool:
    """Whether this caller may read the collection behind a knowledge base.

    Three ways in, and no fourth: an app-scoped base is deployment-wide by
    design, a personal one belongs to its owner, and an org one is decided the
    way every other shareable resource is - the caller's `collections:view`
    scope against the row's owner and visibility, widened by any explicit
    grant (:func:`app.services.access.resolve_access`). The query form of this
    predicate is :func:`app.repositories.knowledge_base.get_accessible`; the
    two must keep agreeing, because a name a listing shows and a per-resource
    route refuses is as much a bug as the reverse.
    """
    if kb.scope == KBScope.APP.value:
        return True
    if kb.scope == KBScope.PERSONAL.value:
        # The owner's, and through a key only one issued to read collections.
        return _owns(ctx, kb) and ctx.key_allows(Perm.COLLECTIONS_VIEW)
    return await resolve_access(db, ctx, kb, Perm.COLLECTIONS_VIEW, resource_type=COLLECTION)


async def writable_kb(db: AsyncSession, ctx: AuthContext, kb: KnowledgeBase) -> bool:
    """Whether this caller may ingest into, or destroy, that collection.

    An app-scoped base is shared by every tenant in the deployment, so only a
    platform admin may write to one; a personal base belongs to its owner. An
    org base takes `collections:edit` reaching the row - the role's scope, or
    an explicit `edit` grant lifting a single base into reach without a
    promotion.
    """
    if kb.scope == KBScope.APP.value:
        return ctx.is_app_admin
    if kb.scope == KBScope.PERSONAL.value:
        return _owns(ctx, kb) and ctx.key_allows(Perm.COLLECTIONS_EDIT)
    return await resolve_access(db, ctx, kb, Perm.COLLECTIONS_EDIT, resource_type=COLLECTION)


def _owns(ctx: AuthContext, kb: KnowledgeBase) -> bool:
    return ctx.user_id is not None and kb.owner_user_id == ctx.user_id


def _as_uuid(value: str) -> UUID | None:
    """The id, or `None` when the caller sent something that cannot be one.

    A malformed id is not a bad request, it is an id that matches nothing - and
    saying so keeps the 500 that `UUID(value)` used to raise out of the
    refusal path.
    """
    try:
        return UUID(value)
    except ValueError:
        return None


def _same_tenant(target: KnowledgeBase, kb: KnowledgeBase) -> bool:
    """Whether a sync writing under `target` writes into `kb`'s share of the name.

    Bases of one organization share its tenant, and with it the rows. Bases with
    no tenant - an app-scoped one, and a personal one outside any organization -
    are each someone else's, so only the base itself is the same.
    """
    if kb.vector_tenant is None:
        return target.id == kb.id
    return target.vector_tenant == kb.vector_tenant


def _feeds(source: SyncSource, kb: KnowledgeBase, candidates: Sequence[KnowledgeBase]) -> bool:
    """Whether a sync source feeds this knowledge base - the one rule for sources.

    A source has an organization and a collection name but no base of its own,
    so it feeds the base its sync writes under: its organization's base by that
    name, else an app-scoped one (`knowledge_base_repo.choose_for_collection`,
    the choice the sync itself makes). `candidates` are the bases claiming the
    name, oldest first. Bases of one organization share its sources; a base with
    no tenant (see :func:`_same_tenant`) reaches only the sources that resolve
    to itself.
    """
    if source.collection_name != kb.collection_name:
        return False
    target = knowledge_base_repo.choose_for_collection(candidates, source.organization_id)
    return target is not None and _same_tenant(target, kb)


def _no_collection(name: str) -> NotFoundError:
    return NotFoundError(message="Collection not found", details={"collection": name})


def _no_document(doc_id: str) -> NotFoundError:
    return NotFoundError(message="Document not found", details={"doc_id": doc_id})


class CollectionAccessService:
    """Resolves what a caller named into a row they are allowed to have.

    Every method either returns the row or raises `NotFoundError`. Nothing
    here returns a boolean to a route, so a route cannot forget to check one.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _first_readable(self, ctx: AuthContext, name: str) -> KnowledgeBase | None:
        """The first knowledge base claiming this name that the caller may read.

        Plural candidates because `collection_name` is not unique: two
        organizations can pick the same name, and they then share one vector
        table. Scanning the candidates means the caller's own row decides,
        rather than whichever row the database happened to return first.
        """
        for kb in await knowledge_base_repo.list_by_collection_name(self.db, name):
            if await readable_kb(self.db, ctx, kb):
                return kb
        return None

    async def _first_writable(self, ctx: AuthContext, name: str) -> KnowledgeBase | None:
        for kb in await knowledge_base_repo.list_by_collection_name(self.db, name):
            if await writable_kb(self.db, ctx, kb):
                return kb
        return None

    async def readable(self, ctx: AuthContext, name: str) -> KnowledgeBase:
        """The collection this caller may read under that name, or 404."""
        kb = await self._first_readable(ctx, name)
        if kb is None:
            raise _no_collection(name)
        return kb

    async def writable(self, ctx: AuthContext, name: str) -> KnowledgeBase:
        """The collection this caller may ingest into or destroy, or 404."""
        kb = await self._first_writable(ctx, name)
        if kb is None:
            raise _no_collection(name)
        return kb

    async def readable_all(self, ctx: AuthContext, names: list[str]) -> list[KnowledgeBase]:
        """All of them, or none - one unreachable name refuses the request.

        A multi-collection search that quietly dropped the name it could not
        reach would answer with fewer results than were asked for and no sign
        that anything was missing. A partial answer that looks complete is worse
        than an error.
        """
        return [await self.readable(ctx, name) for name in names]

    async def readable_names(self, ctx: AuthContext) -> list[str]:
        """Every collection name this caller may read, in creation order.

        Deduplicated because several knowledge bases may point at one
        collection, and a listing should name it once.
        """
        return list(dict.fromkeys(kb.collection_name for kb in await self._readable_kbs(ctx)))

    async def _readable_kbs(self, ctx: AuthContext) -> list[KnowledgeBase]:
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=COLLECTION, perm=Perm.COLLECTIONS_VIEW
        )
        return await knowledge_base_repo.get_accessible(
            self.db,
            user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            see_all_org=shared is None,
            shared_org_ids=shared or [],
        )

    async def readable_scopes_for(
        self, ctx: AuthContext, name: str | None
    ) -> list[CollectionScope]:
        """The knowledge bases whose documents a listing may include.

        A base rather than a collection name, because the name is not unique: a
        document is listed when it is in the scope of a base this caller reads,
        by `rag_document_repo.in_collection_scope`. A name is resolved to every
        base claiming it that the caller reads - an organization's, an
        app-scoped and a personal one can share it, and each holds its own rows.
        """
        kbs = await self._readable_kbs_for(ctx, name)
        return list(dict.fromkeys(CollectionScope.of(kb) for kb in kbs))

    async def readable_sync_log_scope(self, ctx: AuthContext, name: str | None) -> SyncLogScope:
        """The sync runs a listing may include: the collection asked for, or all of theirs.

        A run started by a sync source is listed when that source feeds a base
        the caller reads (:func:`_feeds`, the rule the per-source routes apply);
        on the name alone, a member reading only an app-scoped base listed the
        runs - errors and file counts - of a private base sharing its name
        (#2486). A run with no source carries nothing but its name, so it is
        listed by the name. The unfiltered case means "mine", never "everything".
        """
        kbs = await self._readable_kbs_for(ctx, name)
        names = list(dict.fromkeys(kb.collection_name for kb in kbs))
        candidates = await knowledge_base_repo.list_by_collection_names(self.db, names)
        sources = await sync_source_repo.list_for_collections(self.db, names)
        return SyncLogScope(
            collections=names,
            sync_source_ids=[
                source.id
                for source in sources
                if any(_feeds(source, kb, candidates.get(kb.collection_name, [])) for kb in kbs)
            ],
        )

    async def _readable_kbs_for(self, ctx: AuthContext, name: str | None) -> list[KnowledgeBase]:
        """Every base claiming `name` that this caller reads, or all of theirs; 404 for none."""
        if name is None:
            return await self._readable_kbs(ctx)
        kbs = [
            kb
            for kb in await knowledge_base_repo.list_by_collection_name(self.db, name)
            if await readable_kb(self.db, ctx, kb)
        ]
        if not kbs:
            raise _no_collection(name)
        return kbs

    async def claim(self, ctx: AuthContext, name: str) -> None:
        """Refuse a collection name this caller may not have.

        Everything that writes a `collection_name` a caller chose comes through
        here - `POST /rag/collections/{name}` and `POST /kb` alike. The second
        one did not, and called nothing at all: a member with `collections:edit`
        could point a knowledge base at a name another organization holds, and
        every gate afterwards passed, because :meth:`_first_readable` stops at
        the row the caller *can* read - their own (#367). One call site is what
        made that possible, so this method now has the two it needs rather than
        the KB service growing a second opinion.

        Two refusals, and they are different questions. Whether the string can
        be an identifier at all is
        :func:`app.db.vector_tables.validate_collection_name`, which needs no
        database and is asked in the store as well. Whether it is *taken* needs
        the rows, and only this can ask it.

        The vector namespace is deployment-global: two knowledge bases with one
        collection name share one table, so granting a name that is taken
        elsewhere would wire this organization straight into another's chunks.
        The collision is reported, which does reveal that the name is in use
        somewhere - that is a property of every global namespace and the price
        of letting callers choose the name. It says nothing about who holds it or
        what is in it.

        The taken-check and the row this request goes on to write are serialized
        against a concurrent teardown of the same name: the drop re-reads the same
        reference check before dropping the table, and without the lock a claim that
        reads "free" and a drop that reads "unreferenced" both act, leaving this
        base's committed row pointing at a table the drop removed (#1355, #913). The
        lock is transaction-scoped, so it is held until this request commits the
        row - past `create_collection`, which builds the table this protects.

        Raises:
            BadRequestError: If the name could not safely become an identifier.
            AlreadyExistsError: If a knowledge base outside the caller's reach
                already owns the name.
        """
        validate_collection_name(name, metadata=Base.metadata)
        await hold_name(self.db, LockScope.COLLECTION_TEARDOWN, name)
        if await collection_teardown_repo.is_reserved(self.db, name):
            # The name's last row is gone but its vector table has not been dropped
            # yet, so claiming it now would adopt that lingering, populated table
            # (#1362). The reservation lifts when the durable cleanup drops the table.
            raise AlreadyExistsError(
                message=f"A collection named '{name}' is being torn down; try again shortly",
                details={"collection": name},
            )
        for kb in await knowledge_base_repo.list_by_collection_name(self.db, name):
            if not await writable_kb(self.db, ctx, kb):
                raise AlreadyExistsError(
                    message=f"A collection named '{name}' already exists",
                    details={"collection": name},
                )

    async def _document(self, doc_id: str) -> RAGDocument:
        parsed = _as_uuid(doc_id)
        doc = None if parsed is None else await rag_document_repo.get_by_id(self.db, parsed)
        if doc is None:
            raise _no_document(doc_id)
        return doc

    async def readable_document(self, ctx: AuthContext, doc_id: str) -> RAGDocument:
        """A tracked document whose collection this caller may read.

        The refusal is the document's own "not found", not the collection's:
        reporting a collection problem for a document id would confirm that the
        id exists.
        """
        doc = await self._document(doc_id)
        for kb in await knowledge_base_repo.list_by_collection_name(self.db, doc.collection_name):
            # The knowledge base the document is in, not merely one by the same
            # name: a collection's name is not unique across tenants.
            if await self._holds(kb, doc) and await readable_kb(self.db, ctx, kb):
                return doc
        raise _no_document(doc_id)

    async def writable_document(self, ctx: AuthContext, doc_id: str) -> RAGDocument:
        """A tracked document this caller may delete or re-ingest."""
        doc = await self._document(doc_id)
        for kb in await knowledge_base_repo.list_by_collection_name(self.db, doc.collection_name):
            if await self._holds(kb, doc) and await writable_kb(self.db, ctx, kb):
                return doc
        raise _no_document(doc_id)

    async def kb_document(self, kb: KnowledgeBase, doc_id: str) -> RAGDocument:
        """A document loaded by id, if it is this knowledge base's, or 404.

        For a route that has already authorized the base: what remains is
        whether the document is in it, which the collection's name alone cannot
        say (see :meth:`_holds`). Without it a caller could pass any id through a
        base they reach and download, read or delete another tenant's document.
        """
        doc = await self._document(doc_id)
        if not await self._holds(kb, doc):
            raise NotFoundError(
                message="Document not found in this knowledge base",
                details={"kb_id": kb.id, "doc_id": doc_id},
            )
        return doc

    async def kb_sync_source(self, kb: KnowledgeBase, source_id: str) -> SyncSource:
        """A sync source loaded by id, if it feeds this knowledge base, or 404.

        Which base a source feeds is :func:`_feeds`. On the name and organization
        alone, an app-scoped base would reach every organization's source by its
        name - its run history and settings shown to any member of any
        organization, since such a base is readable by all.
        """
        parsed = _as_uuid(source_id)
        source = None if parsed is None else await sync_source_repo.get_by_id(self.db, parsed)
        if source is None:
            raise NotFoundError(message="Sync source not found", details={"source_id": source_id})
        candidates = await knowledge_base_repo.list_by_collection_name(self.db, kb.collection_name)
        if not _feeds(source, kb, candidates):
            raise NotFoundError(
                message="Sync source not found in this knowledge base",
                details={"kb_id": kb.id, "source_id": source_id},
            )
        return source

    async def kb_sync_sources(self, ctx: AuthContext, kb: KnowledgeBase) -> list[SyncSource]:
        """The caller organization's sync sources feeding this knowledge base, newest first.

        For a route that has already authorized the base. By :func:`_feeds`, as
        :meth:`kb_sync_source` decides one: on the collection name and the
        caller's organization alone, a member who reads only an app-scoped base
        listed the sources - configuration, credential id, last error - of a
        private base of their organization sharing its name (#2486).
        """
        sources = await sync_source_repo.get_all(
            self.db, organization_id=ctx.organization_id, collection_name=kb.collection_name
        )
        candidates = await knowledge_base_repo.list_by_collection_name(self.db, kb.collection_name)
        return [source for source in sources if _feeds(source, kb, candidates)]

    async def _holds(self, kb: KnowledgeBase, doc: RAGDocument) -> bool:
        """Whether a document is in this knowledge base's scope.

        Asked of the database, by `rag_document_repo.in_collection_scope` - the
        rule the listing and the ingestion counts use, so the three cannot
        disagree.
        """
        return await rag_document_repo.is_in_collection_scope(
            self.db, doc.id, scope=CollectionScope.of(kb)
        )

    async def sync_source(self, ctx: AuthContext, source_id: str) -> SyncSource:
        """The integration with this id inside the caller's organization.

        The organization column is the whole rule here: a sync source has no
        owner and nothing to share, and it holds encrypted credentials - which
        is what made the unscoped version worth exploiting. Cloning one copies
        those credentials, so reading somebody else's row was enough to sync
        their Drive into your collection.
        """
        parsed = _as_uuid(source_id)
        source = None if parsed is None else await sync_source_repo.get_by_id(self.db, parsed)
        if source is None or source.organization_id != ctx.organization_id:
            raise NotFoundError(message="Sync source not found", details={"source_id": source_id})
        return source

    async def sync_log(self, ctx: AuthContext, sync_id: str) -> SyncLog:
        """A sync run in a collection this caller may write.

        A run carries no organization of its own. One a sync source started is
        that source's, so it is the caller's when the source feeds a base they
        write (:func:`_feeds`) - not merely one by the same name (#2486). One with
        no source has only the collection it wrote into to say whose it is.
        """
        parsed = _as_uuid(sync_id)
        log = None if parsed is None else await sync_log_repo.get_by_id(self.db, parsed)
        if log is None or not await self._writes_run(ctx, log):
            raise NotFoundError(message="Sync log not found", details={"sync_id": sync_id})
        return log

    async def _writes_run(self, ctx: AuthContext, log: SyncLog) -> bool:
        candidates = await knowledge_base_repo.list_by_collection_name(self.db, log.collection_name)
        source = (
            None
            if log.sync_source_id is None
            else await sync_source_repo.get_by_id(self.db, log.sync_source_id)
        )
        for kb in candidates:
            if (source is None or _feeds(source, kb, candidates)) and await writable_kb(
                self.db, ctx, kb
            ):
                return True
        return False
