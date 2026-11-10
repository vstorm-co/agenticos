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
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.base import Base
from app.db.locks import LockScope, hold_name, hold_name_within
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.rag_document import RAGDocument
from app.db.models.sync_log import SyncLog
from app.db.models.sync_source import SyncSource
from app.db.vector_tables import validate_collection_name
from app.repositories import (
    collection_teardown_repo,
    knowledge_base_repo,
    organization_repo,
    rag_document_repo,
    sync_log_repo,
    sync_source_repo,
    user_repo,
)
from app.repositories.rag_document import CollectionScope
from app.repositories.sync_log import SyncLogScope
from app.services.access import COLLECTION, resolve_access, visible_resource_ids

# How long a claim waits for its name, holding a pooled connection (#2747). An unfiled
# write holds the name through its commit, about 2ms a chunk, so this outlasts a
# document of a few hundred chunks; a longer hold is answered with a 409 to retry. It
# stays well under `DB_POOL_TIMEOUT`, five seconds: a pool's worth of claims gives its
# connections back in one of these, so a request queued behind them is served late
# and not refused, and it takes five such rounds queued at once to refuse one.
_CLAIM_WAIT_MS = 1000


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


def _feeds(source: SyncSource, kb: KnowledgeBase, candidates: Sequence[KnowledgeBase]) -> bool:
    """Whether a sync source feeds this knowledge base - the one rule for sources.

    A source has an organization and a collection name but no base of its own,
    so it feeds the base its sync writes under: its organization's base by that
    name, else an app-scoped one (`knowledge_base_repo.choose_for_collection`,
    the choice the sync itself makes). `candidates` are the bases claiming the
    name, oldest first. Only that base: bases of one organization used to share
    their sources because they shared their rows, and they no longer share rows
    (#2537) - a second base of the name would list and run a source whose
    documents it never holds.
    """
    if source.collection_name != kb.collection_name:
        return False
    target = knowledge_base_repo.choose_for_collection(candidates, source.organization_id)
    return target is not None and target.id == kb.id


def _reaches_source(ctx: AuthContext, source: SyncSource) -> bool:
    """Whether this caller may see a sync source that feeds a base they read.

    Feeding a readable base is not enough on its own: every member of every
    organization reads an app-scoped base, and a source of any organization
    with no base of the name feeds it (:func:`_feeds`). Its settings and run
    history - error text naming files and endpoints - are still that
    organization's, so a source is the caller organization's or, for a
    platform admin, anyone's (#2745).
    """
    return ctx.is_app_admin or source.organization_id == ctx.organization_id


def _taken(name: str) -> AlreadyExistsError:
    return AlreadyExistsError(
        message=f"A collection named '{name}' already exists",
        details={"collection": name},
    )


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
        the caller reads (:func:`_feeds`, the rule the per-source routes apply)
        and is the caller organization's (:func:`_reaches_source`); on the name
        alone, a member reading only an app-scoped base listed the runs - errors
        and file counts - of a private base sharing its name (#2486), and on the
        base alone, those of every organization feeding that app base (#2745). A
        run with no source carries nothing but its name, so it is listed by the
        name. The unfiltered case means "mine", never "everything".
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
                if _reaches_source(ctx, source)
                and any(_feeds(source, kb, candidates.get(kb.collection_name, [])) for kb in kbs)
            ],
        )

    async def readable_sync_sources(self, ctx: AuthContext, name: str | None) -> list[SyncSource]:
        """The caller organization's sync sources this caller may list, newest first.

        The whole list - every base's sources, with their config, credential id
        and last error, and the unassigned templates - is the organization's
        integrations, and `connections:manage` is what reads those, as on
        `/org/integrations`. Anybody else gets the sources feeding a base they
        read (:func:`_feeds`), which is what each base's own page lists: under
        `collections:view` alone this answered every reader of one base with
        everything (#2745). A `name` narrows either answer to that collection,
        and for a caller listing by base it must be one they read, or 404.
        """
        sources = await sync_source_repo.get_all(
            self.db, organization_id=ctx.organization_id, collection_name=name
        )
        if ctx.has(Perm.CONNECTIONS_MANAGE):
            return sources
        kbs = await self._readable_kbs_for(ctx, name)
        names = list(dict.fromkeys(kb.collection_name for kb in kbs))
        candidates = await knowledge_base_repo.list_by_collection_names(self.db, names)
        return [
            source
            for source in sources
            if any(_feeds(source, kb, candidates.get(kb.collection_name, [])) for kb in kbs)
        ]

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
        against a concurrent teardown of the same name: the teardown reads the same
        reference check to decide the drop, and without the lock a claim that
        reads "free" and a teardown that reads "unreferenced" both act, leaving this
        base's committed row pointing at a table the drop removed (#1355, #913). The
        lock is transaction-scoped, so it is held until this request commits the
        row - past `create_collection`, which builds the table this protects.

        The wait for that lock is bounded (`_CLAIM_WAIT_MS`), since a request waiting
        holds a connection and the holder can be a document's whole insert (#2747).
        Past it the claim is refused with a "try again", and the session stays usable.
        Nothing has been read or decided by then, so the refusal cannot weaken what
        the lock protects: a teardown still waits for whoever holds the name.

        Content no base owns is the third refusal (#2747). A name can hold rows
        and chunks with no knowledge base behind them - `rag-ingest` writes both,
        tagged with no organization. A claim adopting such a name let a member with
        ordinary `collections:edit` create a base on it and, in deleting that base,
        drop the operator's chunks. The last holder's teardown now keeps a table
        holding such chunks; this keeps the name from being adopted at all, an
        ingest still running included. So a name no base holds is refused while it
        holds unfiled rows describing chunks of any tenant but the caller's
        organization, or a vector table with such chunks. A name a base holds is
        not checked: the caller passed `writable_kb` on every holder, and may
        delete or clear them all anyway. Only an app admin passes: they administer the
        deployment and can already drop any collection with `rag-drop`. The
        refusal is the same "already exists", saying nothing about whose content
        it is; that the name holds content at all is the global namespace's
        price, as for a held name.

        Raises:
            BadRequestError: If the name could not safely become an identifier.
            AlreadyExistsError: If a knowledge base outside the caller's reach
                already owns the name, no base holds it, it holds content of another
                tenant and the caller is not an app admin, or something else held
                the name throughout the wait.
        """
        validate_collection_name(name, metadata=Base.metadata)
        if not await hold_name_within(
            self.db, LockScope.COLLECTION_TEARDOWN, name, wait_ms=_CLAIM_WAIT_MS
        ):
            raise AlreadyExistsError(
                message=f"The collection '{name}' is busy right now; try again shortly",
                details={"collection": name},
            )
        if await collection_teardown_repo.is_reserved(self.db, name):
            # The name's last row is gone but its vector table has not been dropped
            # yet, so claiming it now would adopt that lingering, populated table
            # (#1362). The reservation lifts when the durable cleanup drops the table.
            raise AlreadyExistsError(
                message=f"A collection named '{name}' is being torn down; try again shortly",
                details={"collection": name},
            )
        holders = await knowledge_base_repo.list_by_collection_name(self.db, name)
        for kb in holders:
            if not await writable_kb(self.db, ctx, kb):
                raise _taken(name)
        # A caller who may write every holder may already delete or clear them all,
        # so a held name has nothing more to refuse: the teardown spares what is not
        # theirs.
        if ctx.is_app_admin or holders:
            return
        if await rag_document_repo.holds_unfiled_outside(
            self.db, collection_name=name, tenant=ctx.organization_id
        ):
            raise _taken(name)
        if await rag_document_repo.table_holds_chunks_outside(
            self.db, collection_name=name, tenant=ctx.organization_id
        ):
            raise _taken(name)

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

    async def _hold_source(self, ctx: AuthContext, source: SyncSource) -> SyncSource | None:
        """The source as committed, locked until this transaction ends, or `None` if gone.

        Which base a source feeds is its `collection_name`, so an answer about
        that base is only good while the name cannot change: a move committing
        between an unlocked read and the write it authorized left a caller
        changing a source that now feeds a base they cannot write (#2745). Decide
        on the row this returns and hold it through the change.

        Locks are taken in the order the teardowns take them: a collection name a
        move targets (:meth:`source_target`) before this, as a base's deletion
        takes the name and then its sources; then the organization and the
        caller, as their foreign keys would take them, before the row, as a purge
        or an account deletion locks them and then deletes the source (#2682).
        The source's organization rather than the caller's: a platform admin
        reaches another organization's.
        """
        await organization_repo.hold_key_share(self.db, source.organization_id)
        await user_repo.hold_key_share(self.db, [] if ctx.user_id is None else [ctx.user_id])
        return await sync_source_repo.lock(self.db, source.id)

    async def kb_sync_source(
        self, ctx: AuthContext, kb: KnowledgeBase, source_id: str, *, for_update: bool = False
    ) -> SyncSource:
        """A sync source loaded by id, if it feeds this knowledge base, or 404.

        Which base a source feeds is :func:`_feeds`. On the name and organization
        alone, an app-scoped base would reach every organization's source by its
        name - its run history and settings shown to any member of any
        organization, since such a base is readable by all. On the base alone it
        still did, for every organization with no base of the name, which is why
        the source must also be the caller's (:func:`_reaches_source`, #2745).

        `for_update` is for a route that goes on to change or run the source: the
        source then stays where it was checked until that lands
        (:meth:`_hold_source`). A read leaves it off, and does not wait behind a
        change.
        """
        parsed = _as_uuid(source_id)
        source = None if parsed is None else await sync_source_repo.get_by_id(self.db, parsed)
        if for_update and source is not None and _reaches_source(ctx, source):
            source = await self._hold_source(ctx, source)
        if source is None:
            raise NotFoundError(message="Sync source not found", details={"source_id": source_id})
        candidates = await knowledge_base_repo.list_by_collection_name(self.db, kb.collection_name)
        if not _reaches_source(ctx, source) or not _feeds(source, kb, candidates):
            raise NotFoundError(
                message="Sync source not found in this knowledge base",
                details={"kb_id": kb.id, "source_id": source_id},
            )
        return source

    async def detach_sources_targeting(self, kb: KnowledgeBase) -> None:
        """Detach sources before deleting their resolved target, under the name lock.

        Keeping only the name would silently grant the source a different base
        after deletion. Preserve its configuration for an explicit reassignment.
        """
        await hold_name(self.db, LockScope.COLLECTION_TEARDOWN, kb.collection_name)
        candidates = await knowledge_base_repo.list_by_collection_name(self.db, kb.collection_name)
        sources = await sync_source_repo.get_all(
            self.db, collection_name=kb.collection_name, for_update=True
        )
        for source in sources:
            if _feeds(source, kb, candidates) or len(candidates) == 1:
                await sync_source_repo.update(
                    self.db, source.id, collection_name=None, is_active=False
                )

    async def source_target(self, ctx: AuthContext, name: str) -> KnowledgeBase:
        """The base a sync source naming this collection writes into, if writable, or 404.

        For the routes that point a source at a collection by name. A source
        records an organization and a name, not a base, so its sync writes into
        the base :func:`_feeds` resolves - the caller organization's oldest base
        by the name, else an app-scoped one. Authorizing any writable base of the
        name instead let a member who owns a newer same-named personal base point
        a source at the organization's base they cannot edit (#2537).

        Raises:
            BadRequestError: Eligible bases tie on the oldest creation time.
        """
        await hold_name(self.db, LockScope.COLLECTION_TEARDOWN, name)
        candidates = await knowledge_base_repo.list_by_collection_name(self.db, name)
        target = knowledge_base_repo.choose_for_collection(candidates, ctx.organization_id)
        if target is None or not await writable_kb(self.db, ctx, target):
            raise _no_collection(name)
        if any(
            kb.id != target.id
            and kb.organization_id == target.organization_id
            and (target.organization_id is not None or kb.scope == target.scope)
            and kb.created_at == target.created_at
            for kb in candidates
        ):
            raise refused_field(
                "collection_name",
                (
                    "This collection name has more than one knowledge base with the same "
                    "creation time. Use a knowledge base with a unique collection name."
                ),
            )
        return target

    async def new_source_feeds(self, ctx: AuthContext, kb: KnowledgeBase) -> None:
        """Refuse a sync source on a base its sync would not write into.

        A source records an organization and a collection name, not a base, so
        its sync writes into the base :func:`_feeds` resolves - the caller
        organization's oldest base by the name, else an app-scoped one. A source
        added to another same-named base would sync into that one, and would not
        be listed under the base it was added to (#2537).

        Raises:
            BadRequestError: The sync would write into a different base.
        """
        await hold_name(self.db, LockScope.COLLECTION_TEARDOWN, kb.collection_name)
        candidates = await knowledge_base_repo.list_by_collection_name(self.db, kb.collection_name)
        target = knowledge_base_repo.choose_for_collection(candidates, ctx.organization_id)
        if target is None or target.id != kb.id:
            raise BadRequestError(
                message=(
                    "A sync source here would sync into another knowledge base named "
                    f"'{kb.collection_name}', so it cannot be added to this one. "
                    "Use a knowledge base with a name of its own."
                ),
                details={"kb_id": str(kb.id), "collection": kb.collection_name},
            )

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

    async def writable_sync_source(self, ctx: AuthContext, source_id: str) -> SyncSource:
        """A sync source of the caller's organization they may change, run or delete.

        :meth:`sync_source`, and when the source feeds a base, write access to
        that base (:func:`writable_kb`) - the check the knowledge-base routes make
        through the base in their path. A source writes into its base, so
        detaching it, changing its config or credential, deleting it or running it
        changes that base; `/rag/sync/sources/{id}` checked the organization and,
        on a move, only the base the source was moved to (#2745). A source that
        feeds no base - an unassigned template, or a name no base holds - has only
        its organization to decide it. The refusal is the absent source's, so it
        does not confirm that the id exists.

        The decision is made on the locked row, which stays where it was checked
        until this transaction ends (:meth:`_hold_source`), so a route moving the
        source calls :meth:`source_target` first.
        """
        source = await self._hold_source(ctx, await self.sync_source(ctx, source_id))
        if source is None:
            raise NotFoundError(message="Sync source not found", details={"source_id": source_id})
        if source.collection_name is None:
            return source
        candidates = await knowledge_base_repo.list_by_collection_name(
            self.db, source.collection_name
        )
        target = knowledge_base_repo.choose_for_collection(candidates, source.organization_id)
        if target is not None and not await writable_kb(self.db, ctx, target):
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
