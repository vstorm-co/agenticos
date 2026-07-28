import logging
import re
import secrets
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.repositories import conversation_repo, knowledge_base_repo
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.services.collection_access import can_read, can_write
from app.services.ingestion_config import (
    IngestionConfig,
    IngestionConfigService,
    deployment_defaults,
    deployment_embedding,
)

logger = logging.getLogger(__name__)


def _derive_collection_name(name: str) -> str:
    """Slugify the KB name and append a short random suffix to avoid collisions."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "kb"
    return f"{slug[:48]}_{secrets.token_hex(3)}"


def _no_knowledge_base(kb_id: UUID) -> NotFoundError:
    """The one refusal for a base that is absent, and for one out of reach.

    Built in a single place so the two cannot drift apart: a caller must not be
    able to tell "there is no such id" from "that id is not yours", and two
    matching string literals in different methods is not a guarantee of that.
    """
    return NotFoundError(message="Knowledge base not found", details={"kb_id": str(kb_id)})


class KnowledgeBaseService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_accessible(
        self,
        user_id: UUID,
        organization_id: UUID | None = None,
    ) -> list[KnowledgeBase]:
        return await knowledge_base_repo.get_accessible(
            self.db, user_id=user_id, organization_id=organization_id
        )

    async def create_for_rag_collection(
        self,
        collection_name: str,
        *,
        user_id: UUID,
        organization_id: UUID | None = None,
    ) -> KnowledgeBase:
        """Create a KB backed by an explicit ``collection_name`` (idempotent).

        Used by ``POST /rag/collections/{name}`` so a collection created on the
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
            ingestion_config=deployment_defaults().model_dump(mode="json"),
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
        )

    async def delete_for_rag_collection(self, kb: KnowledgeBase) -> None:
        """Delete the KB row a dropped collection belonged to.

        Keeps the KB table in sync when a collection is dropped via
        ``DELETE /rag/collections/{name}``. A default KB is left intact so the
        org keeps a usable knowledge base.

        Takes the row rather than the name: the caller has already resolved
        which knowledge base it is allowed to act on, and looking the name up
        again would find whichever row the database returned first — possibly
        another organization's, where two of them share a collection name.
        """
        if not kb.is_default:
            await knowledge_base_repo.delete(self.db, kb.id)

    async def resolve_active_collection_names(
        self,
        conversation_id: UUID,
        user_id: UUID | None,
    ) -> list[str]:
        """Return active KB collection names for a conversation.

        Always resolved server-side from `Conversation.active_knowledge_base_ids`,
        intersected with KBs the user can access. Falls back to the org default
        KB when no KBs are explicitly active. Never trust collection names from
        the LLM or client.
        """
        try:
            conv = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
            if not conv:
                return []
            org_id = getattr(conv, "organization_id", None)
            active: list[UUID] = conv.active_knowledge_base_ids or []
            if not active:
                if org_id:
                    default_kb = await knowledge_base_repo.get_default_for_org(self.db, org_id)
                    if default_kb:
                        return [default_kb.collection_name]
                return []
            accessible = await knowledge_base_repo.get_accessible(
                self.db,
                user_id=user_id,
                organization_id=org_id,
            )
            active_set = {str(i) for i in active}
            return [kb.collection_name for kb in accessible if str(kb.id) in active_set]
        except Exception as exc:
            logger.warning("KB collection resolution failed: %s", exc)
            return []

    async def resolve_collection_names_for_ids(
        self,
        *,
        kb_ids: list[UUID],
        user_id: UUID | None,
        organization_id: UUID | None,
    ) -> list[str]:
        """Resolve a client-supplied list of KB IDs to collection names.

        Used when the conversation hasn't been saved yet so we can't read
        ``Conversation.active_knowledge_base_ids`` from DB. Intersects with
        the caller's accessible KBs — clients can never reach a KB they
        don't own (or that isn't shared with their org).
        """
        if not kb_ids:
            return []
        try:
            accessible = await knowledge_base_repo.get_accessible(
                self.db,
                user_id=user_id,
                organization_id=organization_id,
            )
            wanted = {str(i) for i in kb_ids}
            return [kb.collection_name for kb in accessible if str(kb.id) in wanted]
        except Exception as exc:
            logger.warning("KB collection override resolution failed: %s", exc)
            return []

    async def get(
        self,
        kb_id: UUID,
        *,
        user_id: UUID,
        organization_id: UUID | None = None,
    ) -> KnowledgeBase:
        kb = await knowledge_base_repo.get_by_id(self.db, kb_id)
        if not kb:
            raise _no_knowledge_base(kb_id)
        self._check_read_access(kb, user_id=user_id, organization_id=organization_id)
        return kb

    async def create(
        self,
        data: KnowledgeBaseCreate,
        *,
        ctx: AuthContext,
        user_id: UUID,
        organization_id: UUID | None = None,
        is_app_admin: bool = False,
    ) -> KnowledgeBase:
        """Create a knowledge base, with the configuration its documents get.

        The embedding model is read from the deployment and written onto the
        row; it is not something the caller supplies, and there is no endpoint
        that changes it afterwards. See
        :func:`app.services.ingestion_config.deployment_embedding`.
        """
        self._check_create_permission(
            scope=data.scope,
            user_id=user_id,
            organization_id=organization_id,
            is_app_admin=is_app_admin,
        )
        config = await self._usable_config(ctx, data.ingestion_config)
        owner_user_id = user_id if data.scope == KBScope.PERSONAL.value else None
        org_id = (
            organization_id if data.scope in (KBScope.ORG.value, KBScope.PERSONAL.value) else None
        )
        embedding_model, embedding_dim = deployment_embedding()
        return await knowledge_base_repo.create(
            self.db,
            name=data.name,
            collection_name=data.collection_name or _derive_collection_name(data.name),
            scope=data.scope,
            description=data.description,
            owner_user_id=owner_user_id,
            organization_id=org_id,
            ingestion_config=config.model_dump(mode="json"),
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
        )

    async def create_default_for_org(
        self,
        organization_id: UUID,
        collection_name: str,
    ) -> KnowledgeBase:
        existing = await knowledge_base_repo.get_default_for_org(self.db, organization_id)
        if existing:
            return existing
        embedding_model, embedding_dim = deployment_embedding()
        return await knowledge_base_repo.create(
            self.db,
            name="Default",
            collection_name=collection_name,
            scope=KBScope.ORG.value,
            description="Default knowledge base",
            organization_id=organization_id,
            is_default=True,
            ingestion_config=deployment_defaults().model_dump(mode="json"),
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
        )

    async def update(
        self,
        kb_id: UUID,
        data: KnowledgeBaseUpdate,
        *,
        ctx: AuthContext,
        user_id: UUID,
        organization_id: UUID | None = None,
        is_app_admin: bool = False,
    ) -> KnowledgeBase:
        kb = await knowledge_base_repo.get_by_id(self.db, kb_id)
        if not kb:
            raise _no_knowledge_base(kb_id)
        self._check_write_access(
            kb, user_id=user_id, organization_id=organization_id, is_app_admin=is_app_admin
        )
        config = (
            None
            if data.ingestion_config is None
            else await self._usable_config(ctx, data.ingestion_config)
        )
        return await knowledge_base_repo.update(
            self.db,
            db_kb=kb,
            name=data.name,
            description=data.description,
            ingestion_config=None if config is None else config.model_dump(mode="json"),
        )

    async def _usable_config(
        self, ctx: AuthContext, config: IngestionConfig | None
    ) -> IngestionConfig:
        """The configuration to store, proven to work before it is stored.

        A collection that asks for image description needs a model profile the
        organization can actually run. Checking it while the form is open turns
        what would be an ingestion failure an hour later — on a document the
        uploader had nothing to do with — into a message on the field that
        caused it. This is the same trade
        :func:`app.services.model_profile._validate_model_id` makes.
        """
        chosen = config or deployment_defaults()
        await IngestionConfigService(self.db).resolved_image_model(ctx.organization_id, chosen)
        return chosen

    async def delete(
        self,
        kb_id: UUID,
        *,
        user_id: UUID,
        organization_id: UUID | None = None,
        is_app_admin: bool = False,
    ) -> None:
        kb = await knowledge_base_repo.get_by_id(self.db, kb_id)
        if not kb:
            raise _no_knowledge_base(kb_id)
        # Access first, then the rule about default bases: "cannot delete the
        # default knowledge base" is a statement about a row, so answering it for
        # another organization's id confirms both that the id exists and that it
        # is their default.
        self._check_write_access(
            kb, user_id=user_id, organization_id=organization_id, is_app_admin=is_app_admin
        )
        if kb.is_default:
            raise BadRequestError(message="Cannot delete the default knowledge base")
        await knowledge_base_repo.delete(self.db, kb_id)

    def _check_read_access(
        self,
        kb: KnowledgeBase,
        *,
        user_id: UUID,
        organization_id: UUID | None,
    ) -> None:
        """Refuse a knowledge base out of reach, as though it were not there.

        The rule itself is :func:`app.services.collection_access.can_read`,
        shared with the ``/rag`` routes: the same rows, the same question, and
        one implementation — two of them is how the collection a listing hid
        stayed readable by name.
        """
        if not can_read(kb, user_id=user_id, organization_id=organization_id):
            raise _no_knowledge_base(kb.id)

    def _check_write_access(
        self,
        kb: KnowledgeBase,
        *,
        user_id: UUID,
        organization_id: UUID | None,
        is_app_admin: bool,
    ) -> None:
        """Refuse a write, revealing only what the caller could already read.

        The rule is :func:`app.services.collection_access.can_write`, shared with
        the ``/rag`` routes rather than restated here — this method used to be a
        third copy of the scope rules, and it answered 403. "Forbidden" on
        another organization's ``kb_id`` confirms that the id exists, which is
        precisely the oracle ``_check_read_access`` reports as not-found to
        avoid; one surface out of step is enough to reinstate it, and a write
        refusal is as good a probe as a read.

        The single refusal that stays a 403 is an app-scoped base a non-admin may
        read but not modify. They can see the row through ``GET /kb/{kb_id}``, so
        calling it missing would conceal nothing and would cost them the one
        sentence that explains the refusal.
        """
        if can_write(
            kb, user_id=user_id, organization_id=organization_id, is_app_admin=is_app_admin
        ):
            return
        if kb.scope == KBScope.APP.value:
            raise AuthorizationError(
                message="App admin required to modify app-scoped knowledge base"
            )
        raise _no_knowledge_base(kb.id)

    def _check_create_permission(
        self,
        *,
        scope: str,
        user_id: UUID,
        organization_id: UUID | None,
        is_app_admin: bool,
    ) -> None:
        if scope == KBScope.APP.value and not is_app_admin:
            raise AuthorizationError(
                message="App admin required to create app-scoped knowledge base"
            )
        if scope == KBScope.ORG.value and not organization_id:
            raise AuthorizationError(
                message="Organization context required to create org-scoped knowledge base"
            )
