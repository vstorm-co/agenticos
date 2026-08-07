"""API dependencies.

Dependency injection factories for services, repositories, and authentication.

**The session aliases below decide when the transaction commits.** A dependency
with `yield` runs its exit code when the exit stack it was registered on
unwinds, and FastAPI keeps two of them per request: the *function* stack, which
unwinds after the path operation returns and **before** the response is sent,
and the *request* stack, which unwinds **after**. `scope=` on `Depends` chooses
between them, and `"request"` is the default for a generator dependency - which
is why every write in this API used to be acknowledged before it was durable
(#353).
"""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from fastapi import Header
from fastapi import Query
from fastapi import WebSocket, Cookie, WebSocketException
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session

DBSession = Annotated[AsyncSession, Depends(get_db_session, scope="function")]
"""The request's session, committed before the response leaves the process.

`scope="function"` is load-bearing, not decoration: it puts the commit on the
exit stack FastAPI unwinds *between* the path operation returning and the
response being written, so a 2xx means the write is readable rather than merely
accepted. Without it a client acting on its own 2xx - a browser refetching after
a mutation, an agent reading back what it just wrote, an E2E fixture - can be
answered from a database the write has not reached (#353, #230, #335).

A failed request is unaffected in ordering and unchanged in behaviour: the
exception unwinds this stack too, so the rollback still happens, and it still
happens before the error response is built.
"""

StreamingDBSession = Annotated[AsyncSession, Depends(get_db_session, scope="request")]
"""A session that outlives the response start, for a body produced while sending.

A `StreamingResponse` over a generator is iterated during `await response(...)`,
which is after the function stack has unwound - so a body that pages through the
database needs the session to survive that long, and this alias is the only
supported way to ask for one.

**Read-only.** Its transaction resolves after the client has been answered,
which is exactly the ordering #353 is about, so a write made through it is a
write nobody can be told the truth about. One endpoint uses it: the ratings
export. `tests/api/test_db_session_scope.py` refuses a second without a decision
being made about it.

Taking this alias costs a second session, because FastAPI's dependency cache
keys on the computed scope: the export endpoint holds this one *and* the
function-scoped one its authentication resolves through, on two pool
connections, in two transactions. Unavoidable while authentication reads the
database, and free for a read - under `READ COMMITTED` every statement takes a
fresh snapshot anyway, so one transaction guarantees these two reads no more
than two do. Do not build on it: a *write* split across the two is two
transactions that can half-commit.
"""
from uuid import UUID

from app.db.session import get_db_context
from fastapi import Request

from app.clients.redis import RedisClient


async def get_redis(request: Request) -> RedisClient:
    """Get Redis client from lifespan state."""
    return request.state.redis  # type: ignore[no-any-return]


Redis = Annotated[RedisClient, Depends(get_redis)]


from app.services.user import UserService
from app.services.session import SessionService
from app.services.conversation import ConversationService
from app.services.sandbox_connection import SandboxConnectionService
from app.services.sandbox_workspace import SandboxWorkspaceService
from app.services.conversation_share import ConversationShareService


def get_user_service(db: DBSession) -> UserService:
    """Create UserService instance with database session."""
    return UserService(db)


def get_session_service(db: DBSession) -> SessionService:
    """Create SessionService instance with database session."""
    return SessionService(db)


UserSvc = Annotated[UserService, Depends(get_user_service)]
SessionSvc = Annotated[SessionService, Depends(get_session_service)]


def get_conversation_service(db: DBSession) -> ConversationService:
    """Create ConversationService instance with database session."""
    return ConversationService(db)


ConversationSvc = Annotated[ConversationService, Depends(get_conversation_service)]


def get_sandbox_workspace_service(db: DBSession) -> SandboxWorkspaceService:
    return SandboxWorkspaceService(db)


WorkspaceSvc = Annotated[SandboxWorkspaceService, Depends(get_sandbox_workspace_service)]


def get_sandbox_connection_service(db: DBSession) -> SandboxConnectionService:
    return SandboxConnectionService(db)


SandboxConnectionSvc = Annotated[SandboxConnectionService, Depends(get_sandbox_connection_service)]


def get_conversation_share_service(db: DBSession) -> ConversationShareService:
    """Create ConversationShareService instance with database session."""
    return ConversationShareService(db)


ConversationShareSvc = Annotated[ConversationShareService, Depends(get_conversation_share_service)]
from app.services.channel_bot import ChannelBotService


def get_channel_bot_service(db: DBSession) -> ChannelBotService:
    """Unscoped ChannelBotService - inbound webhook dispatch only.

    An inbound request is made by a chat platform, not by a member, so there is
    no active organization to scope to; the bot row carries it. Management
    endpoints must use `OrgChannelBotSvc` instead.
    """
    return ChannelBotService(db)


ChannelBotSvc = Annotated[ChannelBotService, Depends(get_channel_bot_service)]

from app.services.message_rating import MessageRatingService


def get_rating_service(db: DBSession) -> MessageRatingService:
    """Create MessageRatingService instance with database session."""
    return MessageRatingService(db)


MessageRatingSvc = Annotated[MessageRatingService, Depends(get_rating_service)]


def get_streaming_rating_service(db: StreamingDBSession) -> MessageRatingService:
    """The ratings service for the CSV export, and nothing else.

    `MessageRatingService.export_all_ratings` is an async generator that pages
    through the database as the CSV is written, so it runs while the response is
    being sent - after an ordinary `DBSession` has committed and closed. The
    export writes nothing, which is what makes a request-scoped session
    acceptable here; see `StreamingDBSession`.
    """
    return MessageRatingService(db)


StreamingMessageRatingSvc = Annotated[MessageRatingService, Depends(get_streaming_rating_service)]
from app.services.rag_document import RAGDocumentService
from app.services.rag_sync import RAGSyncService
from app.services.sync_source import SyncSourceService


def get_rag_document_service(db: DBSession) -> RAGDocumentService:
    """Create RAGDocumentService instance with database session."""
    return RAGDocumentService(db)


def get_rag_sync_service(db: DBSession) -> RAGSyncService:
    """Create RAGSyncService instance with database session."""
    return RAGSyncService(db)


def get_sync_source_service(db: DBSession) -> SyncSourceService:
    """Create SyncSourceService instance with database session."""
    return SyncSourceService(db)


RAGDocumentSvc = Annotated[RAGDocumentService, Depends(get_rag_document_service)]
RAGSyncSvc = Annotated[RAGSyncService, Depends(get_rag_sync_service)]
SyncSourceSvc = Annotated[SyncSourceService, Depends(get_sync_source_service)]
from app.services.knowledge_base import KnowledgeBaseService


def get_knowledge_base_service(db: DBSession) -> KnowledgeBaseService:
    """Create KnowledgeBaseService instance with database session."""
    return KnowledgeBaseService(db)


KnowledgeBaseSvc = Annotated[KnowledgeBaseService, Depends(get_knowledge_base_service)]
from app.services.collection_access import CollectionAccessService


def get_collection_access_service(db: DBSession) -> CollectionAccessService:
    """Create CollectionAccessService - the tenant boundary for every /rag route."""
    return CollectionAccessService(db)


CollectionAccessSvc = Annotated[CollectionAccessService, Depends(get_collection_access_service)]
from app.services.file_upload import FileUploadService


def get_file_upload_service(db: DBSession) -> FileUploadService:
    """Create FileUploadService instance with database session."""
    return FileUploadService(db)


FileUploadSvc = Annotated[FileUploadService, Depends(get_file_upload_service)]
from app.repositories import member_repo, organization_repo
from app.services.organization import OrganizationService
from app.services.member import MemberService
from app.services.invitation import InvitationService


def get_organization_service(db: DBSession) -> OrganizationService:
    """Create OrganizationService instance with database session."""
    return OrganizationService(db)


def get_member_service(db: DBSession) -> MemberService:
    """Create MemberService instance with database session."""
    return MemberService(db)


def get_invitation_service(db: DBSession) -> InvitationService:
    """Create InvitationService instance with database session."""
    return InvitationService(db)


OrganizationSvc = Annotated[OrganizationService, Depends(get_organization_service)]
MemberSvc = Annotated[MemberService, Depends(get_member_service)]
InvitationSvc = Annotated[InvitationService, Depends(get_invitation_service)]
from app.core.exceptions import AuthenticationError, AuthorizationError, NotFoundError
from app.core.security import verify_token
from app.db.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    user_service: UserSvc,
) -> User:
    """Get current authenticated user from JWT token.

    Returns the full User object including role information.

    Raises:
        AuthenticationError: If token is invalid or user not found.
    """

    payload = verify_token(token)
    if payload is None:
        raise AuthenticationError(message="Invalid or expired token")

    # Ensure this is an access token, not a refresh token
    if payload.get("type") != "access":
        raise AuthenticationError(message="Invalid token type")

    user_id = payload.get("sub")
    if user_id is None:
        raise AuthenticationError(message="Invalid token payload")

    user = await user_service.get_by_id(UUID(user_id))
    if not user.is_active:
        raise AuthenticationError(message="User account is disabled")

    return user


# There is deliberately no role-based dependency here. Authorization inside an
# organization is a permission from the catalog, checked with `require(...)` or
# resolved per row by `resolve_access` - never a role name on a route. The one
# global privilege is `CurrentAppAdmin` below, which gates the deployment's own
# administration rather than a tenant's.
CurrentUser = Annotated[User, Depends(get_current_user)]
from app.db.models.organization import Organization, OrgRole

# Module-level alias so tests can patch via `app.api.deps._member_repo`.
# RequireOrgRole methods reference this alias instead of importing the repo
# inline; routes using member_repo continue to import via the canonical path.
from app.repositories import member_repo as _member_repo


async def get_active_organization(
    user: CurrentUser,
    db: DBSession,
    x_organization_id: UUID | None = Header(None),
) -> Organization:
    """Resolve the active Organization for the current request.

    Reads `X-Organization-Id` header. Falls back to the user's Personal Org
    when the header is absent. Raises 404 if the user is not a member.
    """

    if x_organization_id is None:
        org = await organization_repo.get_personal_for_user(db, user.id)
        if not org:
            raise NotFoundError(message="Personal organization not found - please re-register")
        return org

    membership = await member_repo.get(db, organization_id=x_organization_id, user_id=user.id)
    if not membership:
        raise NotFoundError(
            message="Organization not found or access denied",
            details={"org_id": str(x_organization_id)},
        )
    org = await organization_repo.get_by_id(db, x_organization_id)
    if not org:
        raise NotFoundError(
            message="Organization not found", details={"org_id": str(x_organization_id)}
        )
    return org


ActiveOrg = Annotated[Organization, Depends(get_active_organization)]


def get_org_channel_bot_service(db: DBSession, org: ActiveOrg) -> ChannelBotService:
    """ChannelBotService scoped to the caller's active organization."""
    return ChannelBotService(db, organization_id=org.id)


OrgChannelBotSvc = Annotated[ChannelBotService, Depends(get_org_channel_bot_service)]

from app.services.model_profile import ModelProfileService


def get_model_profile_service(db: DBSession) -> ModelProfileService:
    """Create ModelProfileService instance with database session."""
    return ModelProfileService(db)


ModelProfileSvc = Annotated[ModelProfileService, Depends(get_model_profile_service)]

from app.services.agent_registry import AgentRegistryService


def get_agent_registry_service(db: DBSession) -> AgentRegistryService:
    """Create AgentRegistryService instance with database session."""
    return AgentRegistryService(db)


AgentRegistrySvc = Annotated[AgentRegistryService, Depends(get_agent_registry_service)]

from app.services.agent_exposure import AgentExposureService


def get_agent_exposure_service(db: DBSession) -> AgentExposureService:
    """Create AgentExposureService instance with database session."""
    return AgentExposureService(db)


AgentExposureSvc = Annotated[AgentExposureService, Depends(get_agent_exposure_service)]

from app.services.agent_environment import AgentEnvironmentService


def get_agent_environment_service(db: DBSession) -> AgentEnvironmentService:
    """Create AgentEnvironmentService instance with database session."""
    return AgentEnvironmentService(db)


AgentEnvironmentSvc = Annotated[AgentEnvironmentService, Depends(get_agent_environment_service)]

from app.services.agent_embed import AgentEmbedService


def get_agent_embed_service(db: DBSession) -> AgentEmbedService:
    """Create AgentEmbedService instance with database session."""
    return AgentEmbedService(db)


EmbedSvc = Annotated[AgentEmbedService, Depends(get_agent_embed_service)]

from app.services.agent_runner import AgentRunnerService
from app.services.approvals import ApprovalService


def get_agent_runner_service(db: DBSession) -> AgentRunnerService:
    """Create AgentRunnerService instance with database session."""
    return AgentRunnerService(db)


def get_approval_service(db: DBSession) -> ApprovalService:
    """Create ApprovalService instance with database session."""
    return ApprovalService(db)


AgentRunnerSvc = Annotated[AgentRunnerService, Depends(get_agent_runner_service)]
ApprovalSvc = Annotated[ApprovalService, Depends(get_approval_service)]

from app.services.skill_proposal import SkillProposalService
from app.services.skills import SkillService


def get_skill_service(db: DBSession) -> SkillService:
    """Create SkillService instance with database session."""
    return SkillService(db)


SkillSvc = Annotated[SkillService, Depends(get_skill_service)]


def get_skill_proposal_service(db: DBSession) -> SkillProposalService:
    return SkillProposalService(db)


SkillProposalSvc = Annotated[SkillProposalService, Depends(get_skill_proposal_service)]

from app.core.permissions import AuthContext, Perm
from app.services.sharing import SharingService


def get_sharing_service(db: DBSession) -> SharingService:
    """Create SharingService instance with database session."""
    return SharingService(db)


SharingSvc = Annotated[SharingService, Depends(get_sharing_service)]


async def get_auth_context(user: CurrentUser, org: ActiveOrg, db: DBSession) -> AuthContext:
    """Build the caller's authorization context for the active organization.

    One membership lookup per request; everything downstream reads permissions
    off the returned context instead of querying roles again.
    """
    membership = await _member_repo.get(db, organization_id=org.id, user_id=user.id)
    if membership is None and not user.is_app_admin:
        raise NotFoundError(
            message="Organization not found or access denied",
            details={"org_id": str(org.id)},
        )
    return AuthContext(
        user_id=user.id,
        organization_id=org.id,
        role=membership.role if membership else "",
        is_app_admin=user.is_app_admin,
    )


Auth = Annotated[AuthContext, Depends(get_auth_context)]


def require(*perms: Perm) -> Callable[..., Awaitable[AuthContext]]:
    """Dependency asserting the caller holds every listed permission.

    Endpoints check permissions, never role names - so re-shaping a role is a
    change to `ROLE_PERMS` alone. For a resource permission this guards the
    *kind* of thing; which rows are reachable is
    :func:`app.services.access.resolve_access`.

    Usage::

        @router.post("/agents", dependencies=[Depends(require(Perm.AGENTS_EDIT))])
        async def create_agent(...): ...
    """

    async def dependency(ctx: Auth) -> AuthContext:
        missing = [perm.value for perm in perms if not ctx.has(perm)]
        if missing:
            raise AuthorizationError(
                message="Insufficient permissions",
                details={"required": missing, "org_id": str(ctx.organization_id)},
            )
        return ctx

    return dependency


class RequireOrgRole:
    """Dependency that verifies the requester has one of the allowed roles in the active org.

    Usage::

        @router.delete("/{org_id}")
        async def delete(org: RequireOwner, ...) -> None: ...
    """

    def __init__(self, *allowed_roles: str) -> None:
        self.allowed_roles = set(allowed_roles)

    async def __call__(self, org: ActiveOrg, user: CurrentUser, db: DBSession) -> Organization:
        membership = await _member_repo.get(db, organization_id=org.id, user_id=user.id)
        if not membership or membership.role not in self.allowed_roles:
            raise AuthorizationError(
                message="Insufficient organization role",
                details={"required": list(self.allowed_roles), "org_id": str(org.id)},
            )
        return org


RequireOwner = Annotated[Organization, Depends(RequireOrgRole(OrgRole.OWNER.value))]
RequireAdminPlus = Annotated[
    Organization, Depends(RequireOrgRole(OrgRole.OWNER.value, OrgRole.ADMIN.value))
]
RequireMemberPlus = Annotated[
    Organization,
    Depends(RequireOrgRole(OrgRole.OWNER.value, OrgRole.ADMIN.value, OrgRole.MEMBER.value)),
]


# is_app_admin is a global flag on the User model - independent of team
# membership. Routes guarded by this dep (e.g. /admin/users) stay reachable
# even when teams are disabled, so the dep itself must not be gated.
async def _require_app_admin(user: CurrentUser) -> User:
    """Raises 403 unless the user has the is_app_admin flag set."""
    if not user.is_app_admin:
        raise AuthorizationError(message="App admin privileges required")
    return user


CurrentAppAdmin = Annotated[User, Depends(_require_app_admin)]


_WS_TOKEN_PROTOCOL_PREFIX = "access_token."


def _extract_ws_auth(websocket: WebSocket) -> tuple[str | None, str | None]:
    """Parse Sec-WebSocket-Protocol header for an auth token + app subprotocol.

    Clients pass the token as a subprotocol of the form
    `access_token.<JWT>` alongside an optional application subprotocol
    (e.g. `chat`). Returns (token, app_subprotocol) - either may be None.
    """
    raw = websocket.headers.get("sec-websocket-protocol") or ""
    token: str | None = None
    app_subprotocol: str | None = None
    for proto in (p.strip() for p in raw.split(",") if p.strip()):
        if proto.startswith(_WS_TOKEN_PROTOCOL_PREFIX):
            token = proto[len(_WS_TOKEN_PROTOCOL_PREFIX) :]
        elif app_subprotocol is None:
            app_subprotocol = proto
    return token, app_subprotocol


async def get_current_user_ws(
    websocket: WebSocket,
    access_token: str | None = Cookie(None),
) -> User:
    """Authenticate a WebSocket connection.

    Token sources, checked in order:
    1. `Sec-WebSocket-Protocol` header, in the form `access_token.<JWT>`.
       The chosen application subprotocol (e.g. `chat`) is echoed back on
       `accept()` via `websocket.state.accept_subprotocol`.
    2. Same-origin `access_token` cookie (fallback for same-origin clients).

    Tokens in query strings are NOT accepted - they leak into logs and
    Referer headers.

    Raises:
        WebSocketException: If token is invalid or user not found. Raising the
            WebSocket-native exception lets Starlette close the handshake cleanly
            (close code 4001) - raising an HTTP-domain exception here instead
            bubbles up unhandled and yields an HTTP 500 on the WS upgrade.
    """

    subprotocol_token, app_subprotocol = _extract_ws_auth(websocket)
    websocket.state.accept_subprotocol = app_subprotocol

    auth_token = subprotocol_token or access_token

    if not auth_token:
        raise WebSocketException(code=4001, reason="Missing authentication token")

    payload = verify_token(auth_token)
    if payload is None:
        raise WebSocketException(code=4001, reason="Invalid or expired token")

    if payload.get("type") != "access":
        raise WebSocketException(code=4001, reason="Invalid token type")

    user_id = payload.get("sub")
    if user_id is None:
        raise WebSocketException(code=4001, reason="Invalid token payload")

    async with get_db_context() as db:
        user_service = UserService(db)
        try:
            user = await user_service.get_by_id(UUID(user_id))
        except NotFoundError:
            raise WebSocketException(code=4001, reason="User not found") from None

        if not user.is_active:
            raise WebSocketException(code=4001, reason="User account is disabled")

        # Eagerly load all columns, then detach from session to avoid
        # "instance not bound to a Session" errors after the context manager exits
        await db.refresh(user)
        db.expunge(user)
        return user


CurrentUserWS = Annotated[User, Depends(get_current_user_ws)]


async def get_active_organization_ws(
    user: CurrentUserWS,
    organization_id: UUID | None = Query(None),
) -> Organization:
    """Resolve the active Organization for a WebSocket session.

    The WebSocket counterpart of :func:`get_active_organization`. Browsers cannot
    set headers on a WebSocket handshake, so the org arrives as the
    `organization_id` query parameter instead of `X-Organization-Id`. Unlike a
    token, an org id is not a secret - membership is verified here, so an id the
    user does not belong to closes the socket rather than granting anything.

    Falls back to the user's Personal organization when the parameter is absent,
    which keeps single-org clients working unchanged.

    Raises:
        WebSocketException: If the user has no Personal org (4001), or is not a
            member of the requested org (4003). Membership failure and a
            non-existent org return the same reason so the socket cannot be used
            to probe which organizations exist.
    """

    async with get_db_context() as db:
        if organization_id is None:
            org = await organization_repo.get_personal_for_user(db, user.id)
            if org is None:
                raise WebSocketException(code=4001, reason="Personal organization not found")
        else:
            membership = await _member_repo.get(
                db, organization_id=organization_id, user_id=user.id
            )
            if membership is None:
                raise WebSocketException(code=4003, reason="Organization access denied")
            org = await organization_repo.get_by_id(db, organization_id)
            if org is None:
                raise WebSocketException(code=4003, reason="Organization access denied")

        # Detach so attribute access survives the session closing (same reason as
        # the user in get_current_user_ws).
        await db.refresh(org)
        db.expunge(org)
        return org


ActiveOrgWS = Annotated[Organization, Depends(get_active_organization_ws)]

import secrets

from fastapi.security import APIKeyHeader


api_key_header = APIKeyHeader(name=settings.API_KEY_HEADER, auto_error=False)


async def verify_api_key(
    api_key: Annotated[str | None, Depends(api_key_header)],
) -> str:
    """Verify API key from header.

    Uses constant-time comparison to prevent timing attacks.

    Raises:
        AuthenticationError: If API key is missing.
        AuthorizationError: If API key is invalid.
    """
    if api_key is None:
        raise AuthenticationError(message="API Key header missing")
    if not secrets.compare_digest(api_key, settings.API_KEY):
        raise AuthorizationError(message="Invalid API Key")
    return api_key


ValidAPIKey = Annotated[str, Depends(verify_api_key)]


from fastapi import Request

from app.core.config import settings
from app.services.rag.embeddings import EmbeddingService
from app.services.embedding_resolution import embeddings_for_collection
from app.services.rag.ingestion import IngestionService
from app.services.rag.documents import DocumentProcessor
from app.services.rag.retrieval import RetrievalService
from app.services.rag.vectorstore import PgVectorStore
from app.services.rag.vectorstore import BaseVectorStore


def get_embedding_service(request: Request) -> EmbeddingService:
    """Get embedding service from lifespan state or create new if not available."""
    if hasattr(request.state, "embedding_service"):
        return request.state.embedding_service  # type: ignore[no-any-return]
    return EmbeddingService(settings=settings.rag)


EmbeddingSvc = Annotated[EmbeddingService, Depends(get_embedding_service)]


def get_vectorstore(request: Request, embedder: EmbeddingSvc) -> BaseVectorStore:
    """Get vector store client from lifespan state or create new."""
    if hasattr(request.state, "vector_store"):
        return request.state.vector_store  # type: ignore[no-any-return]
    return PgVectorStore(
        settings=settings.rag, embedding_service=embedder, resolver=embeddings_for_collection
    )


VectorStoreSvc = Annotated[BaseVectorStore, Depends(get_vectorstore)]


def get_retrieval_service(vector_store: VectorStoreSvc) -> RetrievalService:
    """Create RetrievalService instance."""
    return RetrievalService(vector_store=vector_store, settings=settings.rag)


RetrievalSvc = Annotated[RetrievalService, Depends(get_retrieval_service)]


def get_document_processor() -> DocumentProcessor:
    """Create DocumentProcessor instance."""
    return DocumentProcessor(settings=settings.rag)


DocumentProcessorSvc = Annotated[DocumentProcessor, Depends(get_document_processor)]


def get_ingestion_service(
    processor: DocumentProcessorSvc,
    vector_store: VectorStoreSvc,
) -> IngestionService:
    """Create IngestionService instance."""
    return IngestionService(processor=processor, vector_store=vector_store)


IngestionSvc = Annotated[IngestionService, Depends(get_ingestion_service)]

from app.services.user_slash_command import UserSlashCommandService


def get_user_slash_command_service(db: DBSession) -> UserSlashCommandService:
    return UserSlashCommandService(db)


UserSlashCommandSvc = Annotated[UserSlashCommandService, Depends(get_user_slash_command_service)]
from app.services.admin import AdminService


def get_admin_service(db: DBSession) -> AdminService:
    """Create AdminService instance - used by admin REST routes (always
    available, independent of the optional SQLAdmin UI)."""
    return AdminService(db)


AdminSvc = Annotated[AdminService, Depends(get_admin_service)]
from app.services.mcp_connection import McpConnectionService


def get_mcp_connection_service(db: DBSession) -> McpConnectionService:
    return McpConnectionService(db)


McpConnectionSvc = Annotated[McpConnectionService, Depends(get_mcp_connection_service)]
from app.services.organization_secret import OrganizationSecretService


def get_secret_service(db: DBSession) -> OrganizationSecretService:
    """Create OrganizationSecretService instance with database session."""
    return OrganizationSecretService(db)


SecretSvc = Annotated[OrganizationSecretService, Depends(get_secret_service)]
from app.services.audit import AuditService


def get_audit_service(db: DBSession) -> AuditService:
    """Create AuditService instance with database session."""
    return AuditService(db)


AuditSvc = Annotated[AuditService, Depends(get_audit_service)]
