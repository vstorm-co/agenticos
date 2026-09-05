import logging
import re
import secrets
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.locks import LockScope, hold_name
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.resource_grant import Visibility
from app.db.vector_tables import MAX_COLLECTION_NAME_LENGTH
from app.repositories import (
    collection_teardown_repo,
    knowledge_base_repo,
    organization_secret_repo,
    rag_document_repo,
    resource_grant_repo,
)
from app.repositories import sync_source as sync_source_repo
from app.repositories.rag_document import CollectionCounts
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseList,
    KnowledgeBaseRead,
    KnowledgeBaseUpdate,
)
from app.services.access import COLLECTION, SECRET, resolve_access, visible_resource_ids
from app.services.collection_access import CollectionAccessService, readable_kb, writable_kb
from app.services.ingestion_config import (
    IngestionConfig,
    IngestionConfigService,
    chosen_embedding,
    deployment_defaults,
    deployment_embedding,
)
from app.services.rag import embedding_providers

logger = logging.getLogger(__name__)


_DERIVED_SUFFIX_BYTES = 3
"""How much randomness a derived name carries, as bytes of `secrets.token_hex`."""

_DERIVED_SLUG_LENGTH = MAX_COLLECTION_NAME_LENGTH - 1 - 2 * _DERIVED_SUFFIX_BYTES
"""What is left for the slug: the bound, less the separator and the hex suffix."""


def _derive_collection_name(name: str) -> str:
    """Slugify the KB name and append a short random suffix to avoid collisions.

    The result has to satisfy
    :func:`app.db.vector_tables.validate_collection_name` like any other name,
    and two of its rules are why this is not one line. A slug is a leading digit
    away from an identifier the store cannot use unquoted - `2024 Reports`
    becomes `2024_reports` - so a slug that does not start with a letter is
    given one. And the slug is trimmed to what leaves room for the suffix,
    rather than to whatever fit under the old absent length bound.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "kb"
    if not slug[0].isalpha():
        slug = f"kb_{slug}"
    return f"{slug[:_DERIVED_SLUG_LENGTH]}_{secrets.token_hex(_DERIVED_SUFFIX_BYTES)}"


def _no_knowledge_base(kb_id: UUID) -> NotFoundError:
    """The one refusal for a base that is absent, and for one out of reach.

    Built in a single place so the two cannot drift apart: a caller must not be
    able to tell "there is no such id" from "that id is not yours", and two
    matching string literals in different methods is not a guarantee of that.
    """
    return NotFoundError(message="Knowledge base not found", details={"kb_id": str(kb_id)})


def _with_counts(kb: KnowledgeBase, counts: CollectionCounts | None) -> KnowledgeBaseRead:
    """A collection as the listing shows it, contents included.

    `counts` is `None` for a collection nothing has been written to - the group
    query has no row to return for it - and the zeros that stands for are the
    schema's own defaults.
    """
    read = KnowledgeBaseRead.model_validate(kb)
    if counts is None:
        return read
    return read.model_copy(
        update={
            "document_count": counts.documents,
            "indexed_count": counts.indexed,
            "chunk_count": counts.chunks,
        }
    )


class KnowledgeBaseService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_readable(
        self, ctx: AuthContext, *, shared_with_me: bool = False
    ) -> KnowledgeBaseList:
        """The listing: the bases this caller may read, each with its contents.

        The two halves below answer separate questions - which rows are in reach,
        and what each one holds - and joining them is this method's whole job, so
        the route never has to know that a listing takes two queries.
        """
        items = await self.list_accessible(ctx, shared_with_me=shared_with_me)
        counts = await self.counts_for(items)
        return KnowledgeBaseList(
            items=[_with_counts(kb, counts.get(kb.collection_name)) for kb in items],
            total=len(items),
        )

    async def list_accessible(
        self, ctx: AuthContext, *, shared_with_me: bool = False
    ) -> list[KnowledgeBase]:
        """The knowledge bases this caller may read: personal + reachable org + app.

        Which org rows are reachable is the caller's `collections:view` scope -
        own plus org-visible for a Member, everything for a Builder - widened
        by explicit grants, exactly as :func:`collection_access.readable_kb`
        answers per row. `shared_with_me` narrows to org rows deliberately
        shared with the caller - org-visible or explicitly granted, and not
        their own; personal and app-scope rows were never shared with anybody.
        """
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=COLLECTION, perm=Perm.COLLECTIONS_VIEW
        )
        grant_ids = shared or []
        if shared_with_me and shared is None:
            # A role that reaches everything never looks its grants up - but
            # "shared with me" is a question about grants and visibility, not
            # reach, and without them the answer would degenerate into "the
            # whole organization minus mine".
            grant_ids = await resource_grant_repo.list_shared_ids(
                self.db,
                organization_id=ctx.organization_id,
                subject_user_id=ctx.subject_id,
                resource_type=COLLECTION.key,
            )
        return await knowledge_base_repo.get_accessible(
            self.db,
            user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            see_all_org=shared is None,
            shared_org_ids=grant_ids,
            shared_with_me=shared_with_me,
        )

    async def counts_for(self, bases: list[KnowledgeBase]) -> dict[str, CollectionCounts]:
        """What each of these collections holds, keyed by collection name.

        Takes the rows the caller already resolved rather than re-deriving them:
        this is the second half of a listing whose first half already answered
        "which of these may they see", and asking that question twice is how the
        two answers drift.
        """
        return await rag_document_repo.counts_by_collection(
            self.db, collections=[kb.collection_name for kb in bases]
        )

    async def create_for_rag_collection(
        self,
        collection_name: str,
        *,
        user_id: UUID,
        organization_id: UUID | None = None,
    ) -> KnowledgeBase:
        """Create a KB backed by an explicit `collection_name` (idempotent).

        Used by `POST /rag/collections/{name}` so a collection created on the
        /rag page also appears on /kb. The collection name is used verbatim
        (the /rag endpoint already validates it) rather than slug-derived, and
        the KB is org-scoped so it is visible to the workspace. Returns the
        existing KB unchanged if one already maps to this collection.
        """
        existing = await knowledge_base_repo.get_by_collection_name(self.db, collection_name)
        if existing:
            return existing
        scope = KBScope.ORG.value if organization_id else KBScope.PERSONAL.value
        embedding_model, embedding_dim = deployment_embedding()
        return await knowledge_base_repo.create(
            self.db,
            name=collection_name,
            collection_name=collection_name,
            scope=scope,
            owner_user_id=user_id if scope == KBScope.PERSONAL.value else None,
            organization_id=organization_id,
            # Org-visible on purpose: the /rag page creates workspace-wide
            # collections, and an ownerless private row would be reachable
            # only by roles whose `collections:view` spans the organization.
            visibility=Visibility.ORG.value if scope == KBScope.ORG.value else None,
            ingestion_config=deployment_defaults().model_dump(mode="json"),
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
            # A collection that appeared under the vector store rather than
            # through the form embeds where the deployment's own key points,
            # because that is the only credential it has.
            embedding_provider=embedding_providers.deployment_provider().provider,
        )

    async def delete_for_rag_collection(self, kb: KnowledgeBase) -> None:
        """Clear a dropped collection: sync its KB row, and drop its vector table.

        Keeps the KB table in sync when a collection is dropped via
        `DELETE /rag/collections/{name}`. A default KB keeps its **row** so the org
        keeps a usable knowledge base, but its vector **table** is dropped all the
        same - so a cleared default stops returning the documents deleted with it, the
        stale-searchable-chunks bug a kept table left behind (#1361, #1364). A search
        reads an absent table as empty and the next upload recreates it
        (`_ensure_collection`); a non-default KB's row goes too.

        Takes the row rather than the name: the caller has already resolved
        which knowledge base it is allowed to act on, and looking the name up
        again would find whichever row the database returned first - possibly
        another organization's, where two of them share a collection name.

        The table is dropped only when no base *other than this one* still references
        the name. The vector namespace is not tenant-unique, so a name a sibling - or
        another org - still holds backs a table their chunks live in too, and dropping
        it would destroy theirs (#913). The drop is handed to the durable cleanup after
        the commit (`spawn_after_commit` → `dispatch_external_state_cleanup`), not run
        in the request: an in-request drop stranded a rolled-back delete on a dropped
        table, lost it to a worker restart, and raced a concurrent claim (#1347, #1349,
        #1355). The name is held against a claim while the reference check and the
        reservation are made, and reserved in `collection_teardowns` until the drop
        runs, so neither a create (`claim`) nor an upload (`dispatch_upload`) can slip
        onto the name and have this drop destroy its table (#1362, #1364).
        """
        collection = kb.collection_name
        # The teardown lock comes before the KB row delete, one order across every
        # path that takes both, so a concurrent purge cannot invert into a deadlock
        # (#1387).
        await hold_name(self.db, LockScope.COLLECTION_TEARDOWN, collection)
        if not kb.is_default:
            await knowledge_base_repo.delete(self.db, kb.id)
        # A default keeps its own row, so filter it out by id: the table is dropped
        # only when no base *other* than the one being cleared still references the
        # name, so a shared name a sibling holds is not dropped from under it (#913).
        others = [
            ref
            for ref in await knowledge_base_repo.list_by_collection_name(self.db, collection)
            if ref.id != kb.id
        ]
        if not others:
            await collection_teardown_repo.reserve(self.db, collection)
            from app.core.background import spawn_after_commit
            from app.worker.tasks.teardown_tasks import dispatch_external_state_cleanup

            spawn_after_commit(
                self.db,
                dispatch_external_state_cleanup([], [collection]),
                name="drop-rag-collection",
            )

    async def get(self, kb_id: UUID, *, ctx: AuthContext) -> KnowledgeBase:
        """The knowledge base, or "not found" - for absent and out-of-reach alike."""
        kb = await knowledge_base_repo.get_by_id(self.db, kb_id)
        if not kb or not await readable_kb(self.db, ctx, kb):
            raise _no_knowledge_base(kb_id)
        return kb

    async def get_for_write(self, kb_id: UUID, *, ctx: AuthContext) -> KnowledgeBase:
        """The knowledge base, resolved for a caller about to change it.

        :meth:`get` answers for reading; every route that renames or deletes a
        base, ingests a document, removes one, or wires a sync source resolves
        through here instead. The read rule alone let anyone who could *see* a
        base write into it - a Viewer holds `collections:view` and nothing
        else, and could still upload, delete documents and point sync sources
        at the collection.

        The decision is :func:`app.services.collection_access.writable_kb`:
        `collections:edit` reaching this row - the role's scope against the
        row's owner and visibility, or an explicit `edit` grant lifting this
        one base into reach. A grant widens what a role allows, it never
        narrows it, so a Viewer shared into one base can feed it without being
        promoted.

        A base the caller cannot read stays "not found", exactly as :meth:`get`
        answers, so the write path is not an oracle for ids. A refusal on a base
        they can read is a 403 - concealing a row the caller can already open
        would cost the sentence that explains the refusal and protect nothing.
        """
        kb = await knowledge_base_repo.get_by_id(self.db, kb_id)
        if not kb or not await readable_kb(self.db, ctx, kb):
            raise _no_knowledge_base(kb_id)
        if await writable_kb(self.db, ctx, kb):
            return kb
        if kb.scope == KBScope.APP.value:
            raise AuthorizationError(
                message="App admin required to modify app-scoped knowledge base"
            )
        raise AuthorizationError(
            message="Changing this knowledge base requires 'collections:edit' on it or an edit grant"
        )

    async def create(
        self,
        data: KnowledgeBaseCreate,
        *,
        ctx: AuthContext,
    ) -> KnowledgeBase:
        """Create a knowledge base, with the configuration its documents get.

        The embedding model is the caller's choice, frozen at creation: the
        vector column is created at the chosen model's width, so there is no
        endpoint that changes it afterwards. Omitted, it is the deployment's
        default - see :func:`app.services.ingestion_config.deployment_embedding`.
        The credential can be one of the organization's own vault keys, so a
        tenant's embeddings are billed to the tenant rather than the operator.

        The collection name is claimed through
        :meth:`app.services.collection_access.CollectionAccessService.claim`,
        which is the same call `POST /rag/collections/{name}` makes and which
        this route made no version of: an explicit `collection_name` was written
        to the row unexamined, so a member with `collections:edit` could aim a
        knowledge base at another organization's vector table and read and write
        it through every gate that came afterwards (#367).

        The derived name is claimed too, rather than trusted for having six hex
        characters on the end. It costs one indexed lookup, it is the only way
        the invariant "the name on this row was validated" is true of every row,
        and the alternative to a 409 once in sixteen million is silently sharing
        a table with a stranger.

        Raises:
            BadRequestError: If the named model has no known vector width, the
                named key is not an API key this organization holds, or the
                collection name could not safely become an identifier.
            AlreadyExistsError: If the collection name is already held outside
                this caller's reach.
        """
        self._check_create_permission(scope=data.scope, ctx=ctx)
        collection_name = data.collection_name or _derive_collection_name(data.name)
        await CollectionAccessService(self.db).claim(ctx, collection_name)
        config = await self._usable_config(ctx, data.ingestion_config)
        # The creator owns what they create, org scope included: `own` in the
        # permission matrix is meaningless for a row nobody owns, and sharing
        # starts from an owner. App-scoped bases stay ownerless - they belong
        # to the deployment.
        owner_user_id = None if data.scope == KBScope.APP.value else ctx.subject_id
        org_id = (
            ctx.organization_id
            if data.scope in (KBScope.ORG.value, KBScope.PERSONAL.value)
            else None
        )
        embedding_model, embedding_dim = chosen_embedding(data.embedding_model)
        provider = embedding_providers.require(
            data.embedding_provider, model=embedding_model, dim=embedding_dim
        )
        if data.embedding_secret_id is not None:
            await self._check_embedding_secret(
                data.embedding_secret_id, ctx=ctx, organization_id=org_id, provider=provider
            )
        return await knowledge_base_repo.create(
            self.db,
            name=data.name,
            collection_name=collection_name,
            scope=data.scope,
            description=data.description,
            owner_user_id=owner_user_id,
            organization_id=org_id,
            ingestion_config=config.model_dump(mode="json"),
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
            embedding_provider=provider.provider,
            embedding_secret_id=data.embedding_secret_id,
        )

    async def _check_embedding_secret(
        self,
        secret_id: UUID,
        *,
        ctx: AuthContext,
        organization_id: UUID | None,
        provider: embedding_providers.EmbeddingProviderEntry,
    ) -> None:
        """Refuse a key the organization does not hold, or one of the wrong kind.

        Checked at creation, where the person choosing can fix it - the
        resolver deliberately degrades to the deployment key at embed time, so
        this is the only moment a wrong choice is visible.

        Binding a key is lending it: the collection's embeddings bill it for
        everyone who can write the collection. So the chooser has to be able to
        reach the key themselves - the picker only offers what they can see, but
        the API takes an id and an id is guessable. A key they cannot view is
        phrased as one the vault does not hold, so a refusal cannot enumerate
        another member's private secrets.
        """
        if organization_id is None:
            raise BadRequestError(
                message="Only an organization collection can carry a vault key",
                details={"embedding_secret_id": str(secret_id)},
            )
        row = await organization_secret_repo.get(
            self.db, secret_id, organization_id=organization_id
        )
        if row is None or not await resolve_access(
            self.db, ctx, row, Perm.SECRETS_VIEW, resource_type=SECRET
        ):
            raise BadRequestError(
                message="That key is not in this organization's vault",
                details={"embedding_secret_id": str(secret_id)},
            )
        if row.purpose != provider.provider:
            raise refused_field(
                "embedding_secret_id",
                f"That key is for {row.purpose}, and this collection embeds through "
                f"{provider.name}. A key sent to the wrong provider is refused by it, "
                "and is somebody else's credential in somebody else's logs.",
                purpose=row.purpose,
            )

    async def update(
        self,
        kb_id: UUID,
        data: KnowledgeBaseUpdate,
        *,
        ctx: AuthContext,
    ) -> KnowledgeBase:
        kb = await self.get_for_write(kb_id, ctx=ctx)
        config = (
            None
            if data.ingestion_config is None
            else await self._usable_config(ctx, data.ingestion_config)
        )
        # The provider the collection will be on when this update lands, which is
        # what the key has to match: moving to OpenAI and choosing an OpenAI key
        # in one request must be accepted, and either half alone must be checked
        # against the other half as it already stands. The model and the width are
        # the collection's own - `require` refuses a provider that cannot serve
        # them, because the vectors already stored are in that model's space.
        provider = embedding_providers.require(
            data.embedding_provider or kb.embedding_provider,
            model=kb.embedding_model,
            dim=kb.embedding_dim,
        )
        if data.embedding_secret_id is not None:
            await self._check_embedding_secret(
                data.embedding_secret_id,
                ctx=ctx,
                organization_id=kb.organization_id,
                provider=provider,
            )
        elif data.embedding_provider is not None and not data.clear_embedding_secret:
            await self._check_kept_secret(kb, provider=provider)
        return await knowledge_base_repo.update(
            self.db,
            db_kb=kb,
            name=data.name,
            description=data.description,
            ingestion_config=None if config is None else config.model_dump(mode="json"),
            embedding_provider=data.embedding_provider,
            embedding_secret_id=data.embedding_secret_id,
            clear_embedding_secret=data.clear_embedding_secret,
        )

    async def _check_kept_secret(
        self,
        kb: KnowledgeBase,
        *,
        provider: embedding_providers.EmbeddingProviderEntry,
    ) -> None:
        """Refuse a provider change that would leave the old key pointed at it.

        The key stays where it is unless the caller says otherwise, so moving the
        provider on its own can produce a collection holding an OpenRouter key and
        an OpenAI address - which is the one thing this whole change exists to stop.
        Named on `embedding_provider`, because that is the control that moved.
        """
        if kb.embedding_secret_id is None or kb.organization_id is None:
            return
        row = await organization_secret_repo.get(
            self.db, kb.embedding_secret_id, organization_id=kb.organization_id
        )
        if row is None or row.purpose == provider.provider:
            return
        raise refused_field(
            "embedding_provider",
            f"This collection pays with a {row.purpose} key, which {provider.name} will "
            "not accept. Choose a key for the new provider, or fall back to the "
            "deployment's.",
            purpose=row.purpose,
        )

    async def _usable_config(
        self, ctx: AuthContext, config: IngestionConfig | None
    ) -> IngestionConfig:
        """The configuration to store, proven to work before it is stored.

        A collection that asks for image description needs a model profile the
        organization can actually run. Checking it while the form is open turns
        what would be an ingestion failure an hour later - on a document the
        uploader had nothing to do with - into a message on the field that
        caused it. This is the same trade
        :func:`app.services.model_profile._validate_model_id` makes.
        """
        chosen = config or deployment_defaults()
        service = IngestionConfigService(self.db)
        await service.resolved_image_model(ctx.organization_id, chosen)
        await service.check_llamaparse_secret(ctx.organization_id, chosen)
        return chosen

    async def delete(self, kb_id: UUID, *, ctx: AuthContext) -> None:
        """Delete a knowledge base and everything it owns.

        The row is not the whole of it: deleting only the `knowledge_bases` row
        left the `rag_documents` rows (their FK is `SET NULL`, so they survived
        detached and readable by a later same-named collection), the uploaded
        files, and the physical `rag_<collection>` vector table all behind, with
        the collection name still blocking reuse (#1266). So the documents go, then
        the row, then the table - dropped only when no other base still references
        the name, which is not tenant-unique (#913).

        The stored files and the vector table are torn down by a durable cleanup
        handed over after the commit (`spawn_after_commit` →
        `dispatch_external_state_cleanup`). Deferring past the commit means a
        rollback keeps them beside the rows it restores rather than stranding those
        rows on a missing file or a dropped table (#1293, #1347); a Prefect
        deployment run rather than an in-process task means a worker restart
        mid-cleanup no longer orphans them - the run is recorded on the server and
        retried (#1349). The flow re-reads the reference check on its own session
        before dropping, because the name is not tenant-unique and a second org can
        reclaim it in the window between the commit and the drop (#913), and it
        builds its own vector engine - which is why this no longer takes a store.
        """
        # Access first, then the rule about default bases: "cannot delete the
        # default knowledge base" is a statement about a row, so answering it for
        # another organization's id confirms both that the id exists and that it
        # is their default.
        kb = await self.get_for_write(kb_id, ctx=ctx)
        if kb.is_default:
            raise BadRequestError(message="Cannot delete the default knowledge base")
        collection = kb.collection_name
        # And the *name* before the base, because the drop below is decided by
        # counting the bases that still claim it. `collection_name` is not
        # tenant-unique (#913), so two teardowns of two bases sharing one name
        # each saw the other's not-yet-committed row under READ COMMITTED, both
        # took the "still referenced" branch, and the table nobody referenced was
        # left behind (#1273). Held for the transaction, so the second teardown
        # reads the first one's committed absence. Taken before the row lock so
        # every path holds teardown then rows, one order, and a concurrent purge
        # cannot invert it into a deadlock (#1387).
        await hold_name(self.db, LockScope.COLLECTION_TEARDOWN, collection)
        # Lock the base before enumerating its documents, so a concurrent upload
        # or sync inserting a row cannot slip in between the enumeration and the
        # base delete and survive detached under `ON DELETE SET NULL` (#1266).
        await knowledge_base_repo.lock(self.db, kb.id)
        storage_paths = await rag_document_repo.delete_by_knowledge_base(self.db, kb.id)
        await knowledge_base_repo.delete(self.db, kb.id)
        collections_to_drop: list[str] = []
        if not await knowledge_base_repo.list_by_collection_name(self.db, collection):
            # No base references the name any more, so any sync source still
            # pointing at it is dangling: `get_due_for_sync` would re-select it
            # and `_run_source_sync` would recreate the very table this drops
            # (#1266). Deactivate rather than delete - the source keeps its
            # connector and vault credential, but stops being scheduled.
            for source in await sync_source_repo.get_all(self.db, collection_name=collection):
                await sync_source_repo.update(self.db, source.id, is_active=False)
            collections_to_drop = [collection]
            # Reserve the name against reuse until the deferred drop runs, so a
            # concurrent claim cannot adopt the still-populated table (#1362).
            await collection_teardown_repo.reserve(self.db, collection)
        if storage_paths or collections_to_drop:
            from app.core.background import spawn_after_commit
            from app.worker.tasks.teardown_tasks import dispatch_external_state_cleanup

            spawn_after_commit(
                self.db,
                dispatch_external_state_cleanup(storage_paths, collections_to_drop),
                name="delete-kb-cleanup",
            )

    def _check_create_permission(self, *, scope: str, ctx: AuthContext) -> None:
        if scope == KBScope.APP.value and not ctx.is_app_admin:
            raise AuthorizationError(
                message="App admin required to create app-scoped knowledge base"
            )
