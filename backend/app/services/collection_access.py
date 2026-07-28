"""Who may reach a RAG collection, and a refusal that gives nothing away.

A collection has two names in this system. One is the vector table the chunks
live in - a string any caller can type into a URL. The other is the
``knowledge_bases`` row that owns it, and it is the only one of the two that
knows an organization. The row is therefore the authority: every ``/rag`` route
resolves the name through it before touching a vector, a document or a sync
source.

Refusals are reported as "not found", with the same message and details an
absent collection produces. Anything else turns the API into an oracle, and
these names are worth guessing: they are derived from what people call their
knowledge bases, so confirming that ``acme_handbook_d1fac1`` exists somewhere is
already information.

The read rule lives here rather than in :mod:`app.services.knowledge_base` on
purpose. Both surfaces answer the same question about the same rows, and it was
two copies of that question - ``/rag/collections`` filtering by organization
while ``/rag/collections/{name}/info`` did not - that let one tenant read
another's collection while the listing looked perfectly scoped.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.rag_document import RAGDocument
from app.db.models.sync_log import SyncLog
from app.db.models.sync_source import SyncSource
from app.repositories import (
    knowledge_base_repo,
    rag_document_repo,
    sync_log_repo,
    sync_source_repo,
)


def can_read(kb: KnowledgeBase, *, user_id: UUID, organization_id: UUID | None) -> bool:
    """Whether this caller may read the collection behind a knowledge base.

    Three ways in, and no fourth: an app-scoped base is deployment-wide by
    design, a personal one belongs to its owner, an org one to the members of
    that organization. The query form of this predicate is
    :func:`app.repositories.knowledge_base.get_accessible`; the two must keep
    agreeing, because a name a listing shows and a per-resource route refuses
    is as much a bug as the reverse.
    """
    if kb.scope == KBScope.APP.value:
        return True
    if kb.scope == KBScope.PERSONAL.value:
        return str(kb.owner_user_id) == str(user_id)
    return bool(organization_id) and str(kb.organization_id) == str(organization_id)


def can_write(
    kb: KnowledgeBase, *, user_id: UUID, organization_id: UUID | None, is_app_admin: bool
) -> bool:
    """Whether this caller may ingest into, or destroy, that collection.

    Reading it is the baseline; the one addition is that an app-scoped base is
    shared by every tenant in the deployment, so only a platform admin may write
    to one. Which *roles* may write at all is decided a layer up, by the
    ``collections:edit`` gate on the route - this answers "which rows".
    """
    if kb.scope == KBScope.APP.value:
        return is_app_admin
    return can_read(kb, user_id=user_id, organization_id=organization_id)


def _as_uuid(value: str) -> UUID | None:
    """The id, or ``None`` when the caller sent something that cannot be one.

    A malformed id is not a bad request, it is an id that matches nothing - and
    saying so keeps the 500 that ``UUID(value)`` used to raise out of the
    refusal path.
    """
    try:
        return UUID(value)
    except ValueError:
        return None


def _no_collection(name: str) -> NotFoundError:
    return NotFoundError(message="Collection not found", details={"collection": name})


def _no_document(doc_id: str) -> NotFoundError:
    return NotFoundError(message="Document not found", details={"doc_id": doc_id})


class CollectionAccessService:
    """Resolves what a caller named into a row they are allowed to have.

    Every method either returns the row or raises ``NotFoundError``. Nothing
    here returns a boolean to a route, so a route cannot forget to check one.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # -- collections ----------------------------------------------------

    async def _first_readable(self, ctx: AuthContext, name: str) -> KnowledgeBase | None:
        """The first knowledge base claiming this name that the caller may read.

        Plural candidates because ``collection_name`` is not unique: two
        organizations can pick the same name, and they then share one vector
        table. Scanning the candidates means the caller's own row decides,
        rather than whichever row the database happened to return first.
        """
        for kb in await knowledge_base_repo.list_by_collection_name(self.db, name):
            if can_read(kb, user_id=ctx.subject_id, organization_id=ctx.organization_id):
                return kb
        return None

    async def _first_writable(self, ctx: AuthContext, name: str) -> KnowledgeBase | None:
        for kb in await knowledge_base_repo.list_by_collection_name(self.db, name):
            if can_write(
                kb,
                user_id=ctx.subject_id,
                organization_id=ctx.organization_id,
                is_app_admin=ctx.is_app_admin,
            ):
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
        accessible = await knowledge_base_repo.get_accessible(
            self.db, user_id=ctx.subject_id, organization_id=ctx.organization_id
        )
        return list(dict.fromkeys(kb.collection_name for kb in accessible))

    async def readable_names_for(self, ctx: AuthContext, name: str | None) -> list[str]:
        """What a listing may include: the collection asked for, or all of theirs.

        The unfiltered case is the one that leaked - ``GET /rag/documents`` with
        no ``collection_name`` used to answer with every document in the
        deployment - so "no filter" now means "mine", never "everything".
        """
        if name is None:
            return await self.readable_names(ctx)
        return [(await self.readable(ctx, name)).collection_name]

    async def claim(self, ctx: AuthContext, name: str) -> None:
        """Refuse a collection name that is already somebody else's.

        The vector namespace is deployment-global: two knowledge bases with one
        collection name share one table, so granting a name that is taken
        elsewhere would wire this organization straight into another's chunks.
        The collision is reported, which does reveal that the name is in use
        somewhere - that is a property of every global namespace and the price
        of letting callers choose the name. It says nothing about who holds it or
        what is in it.

        Raises:
            AlreadyExistsError: If a knowledge base outside the caller's reach
                already owns the name.
        """
        for kb in await knowledge_base_repo.list_by_collection_name(self.db, name):
            if not can_write(
                kb,
                user_id=ctx.subject_id,
                organization_id=ctx.organization_id,
                is_app_admin=ctx.is_app_admin,
            ):
                raise AlreadyExistsError(
                    message=f"A collection named '{name}' already exists",
                    details={"collection": name},
                )

    # -- documents ------------------------------------------------------

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
        if await self._first_readable(ctx, doc.collection_name) is None:
            raise _no_document(doc_id)
        return doc

    async def writable_document(self, ctx: AuthContext, doc_id: str) -> RAGDocument:
        """A tracked document this caller may delete or re-ingest."""
        doc = await self._document(doc_id)
        if await self._first_writable(ctx, doc.collection_name) is None:
            raise _no_document(doc_id)
        return doc

    # -- sync ------------------------------------------------------------

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
        """A sync run whose collection this caller may write.

        A run carries no organization of its own, so the collection it wrote
        into is what says whose it is.
        """
        parsed = _as_uuid(sync_id)
        log = None if parsed is None else await sync_log_repo.get_by_id(self.db, parsed)
        if log is None or await self._first_writable(ctx, log.collection_name) is None:
            raise NotFoundError(message="Sync log not found", details={"sync_id": sync_id})
        return log
