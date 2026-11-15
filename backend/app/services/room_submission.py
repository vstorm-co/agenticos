"""A human post is durable by itself; an explicit agent request is queued with it."""

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.background import spawn_after_commit
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.locks import LockScope, hold_subject
from app.db.models.conversation import Conversation, Message
from app.db.models.room_submission import RoomSubmission
from app.db.models.user import User
from app.repositories import background_job as job_repo
from app.repositories import conversation as conversation_repo
from app.repositories import room_submission as room_repo
from app.schemas.conversation import ChatPerson, MessageCreate, MessageRead
from app.schemas.room_submission import (
    RoomAgentRequestList,
    RoomAgentRequestRead,
    RoomMessageCreate,
    RoomMessageRead,
)
from app.services import chat_room
from app.services.access import acting_member
from app.services.agent_registry import AgentRegistryService
from app.services.background_jobs import enqueue
from app.services.conversation import ConversationService
from app.worker.jobs import RUN_ROOM_REQUEST, RoomRequestJob

TERMINAL = frozenset({"completed", "failed", "cancelled", "interrupted"})
MAX_ACTIVE = 50


def cloud_agent(spec: AgentSpec) -> None:
    if any(
        binding.enabled
        and (
            (binding.id == "sandbox" and binding.config.get("backend") == "local")
            or (
                binding.id == "coding_agent"
                and binding.config.get("runs_on") in {"this_computer", "personal_sandbox"}
            )
        )
        for binding in spec.capabilities
    ):
        raise BadRequestError(message="Choose a cloud agent for a project room")


def fingerprint(request: RoomMessageCreate) -> str:
    encoded = json.dumps(
        {
            "content": request.content,
            "reply_to_message_id": str(request.reply_to_message_id)
            if request.reply_to_message_id
            else None,
            "agent_id": str(request.agent_id) if request.agent_id else None,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def signed_in(ctx: AuthContext) -> None:
    # Reconstructing an API-key issuer or an impersonated member at dequeue would
    # silently discard their narrowed authority and open their personal accounts.
    if ctx.user_id is None or ctx.api_key_id is not None or ctx.is_impersonated:
        raise AuthorizationError(message="Room messaging requires your own signed-in session")


def announce_request(db: AsyncSession, submission: RoomSubmission) -> None:
    spawn_after_commit(
        db,
        chat_room.room_request(str(submission.conversation_id), submission.id),
        name="room-request-changed",
    )


class RoomSubmissionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.conversations = ConversationService(db)

    async def room(
        self, ctx: AuthContext, conversation_id: UUID, *, for_write: bool = False
    ) -> Conversation:
        conversation = await self.conversations.get_conversation(
            conversation_id,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            for_write=for_write,
            turn=True,
            include_favourite=False,
            ctx=ctx,
        )
        if conversation.project_id is None:
            raise BadRequestError(message="Room messages belong to a project chat")
        if for_write and conversation.is_archived:
            raise BadRequestError(message="Conversation is archived")
        return conversation

    async def read_message(self, message: Message, user: User) -> MessageRead:
        if message.role != "user":
            raise BadRequestError(message="The original room message is not a human post")
        return MessageRead(
            id=message.id,
            conversation_id=message.conversation_id,
            role="user",
            content=message.content,
            client_message_id=message.client_message_id,
            run_id=message.run_id,
            created_at=message.created_at,
            updated_at=message.updated_at,
            sender=ChatPerson.of(user),
            reply_to=await self.conversations.reply_quoted(message),
        )

    async def post(
        self, ctx: AuthContext, conversation_id: UUID, request: RoomMessageCreate, user: User
    ) -> RoomMessageRead:
        signed_in(ctx)
        if user.id != ctx.subject_id:
            raise AuthorizationError(message="Post room messages as yourself")
        await self.room(ctx, conversation_id, for_write=True)
        # Admission and turn claiming share this transaction lock: once a room
        # request is accepted, a new legacy foreground turn cannot overtake it.
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation_id)
        existing = await room_repo.for_client(
            self.db,
            organization_id=ctx.organization_id,
            conversation_id=conversation_id,
            requester_id=ctx.subject_id,
            client_message_id=request.client_message_id,
        )
        digest = fingerprint(request)
        if existing is not None:
            if existing.fingerprint != digest:
                raise AlreadyExistsError(
                    message="That client message id already names a different post"
                )
            message = await self.conversations.get_message(existing.message_id)
            return RoomMessageRead(
                message=await self.read_message(message, user),
                request=RoomAgentRequestRead.model_validate(existing)
                if existing.agent_id is not None
                else None,
            )

        version_id = None
        if request.agent_id is not None:
            _, spec, version_id = await AgentRegistryService(self.db).get_runnable_spec(
                ctx, request.agent_id
            )
            cloud_agent(spec)
            if await room_repo.active_count(self.db, conversation_id=conversation_id) >= MAX_ACTIVE:
                raise AlreadyExistsError(
                    message="This room already has fifty agent requests waiting"
                )
        message = await self.conversations.add_message(
            conversation_id,
            MessageCreate(
                role="user",
                content=request.content,
                client_message_id=request.client_message_id,
                reply_to_message_id=request.reply_to_message_id,
            ),
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
        )
        submission = await room_repo.add(
            self.db,
            RoomSubmission(
                id=uuid4(),
                organization_id=ctx.organization_id,
                conversation_id=conversation_id,
                requester_id=ctx.subject_id,
                message_id=message.id,
                client_message_id=request.client_message_id,
                fingerprint=digest,
                agent_id=request.agent_id,
                version_id=version_id,
                status="queued" if request.agent_id is not None else "posted",
            ),
        )
        if request.agent_id is not None:
            await self.queue(submission)
            announce_request(self.db, submission)
        spawn_after_commit(
            self.db,
            chat_room.room_message(str(conversation_id), message.id),
            name="room-message-posted",
        )
        return RoomMessageRead(
            message=await self.read_message(message, user),
            request=RoomAgentRequestRead.model_validate(submission)
            if submission.agent_id is not None
            else None,
        )

    async def queue(self, submission: RoomSubmission) -> None:
        job_id = await enqueue(
            self.db,
            RUN_ROOM_REQUEST,
            RoomRequestJob(request_id=submission.id, organization_id=submission.organization_id),
            organization_id=submission.organization_id,
            dedupe_key=f"room-request:{submission.id}",
            dedupe_active=True,
            concurrency_key=f"room:{submission.conversation_id}",
        )
        if job_id is not None:
            submission.job_id = job_id
            await room_repo.save(self.db, submission)

    async def authority(
        self, submission: RoomSubmission
    ) -> tuple[AuthContext, Conversation, Message]:
        ctx = await acting_member(self.db, submission.organization_id, str(submission.requester_id))
        if ctx is None:
            raise AuthorizationError(
                message="The member who requested this answer no longer has access"
            )
        conversation = await self.room(ctx, submission.conversation_id, for_write=True)
        if submission.agent_id is None or submission.version_id is None:
            raise BadRequestError(message="This post did not request an agent")
        registry = AgentRegistryService(self.db)
        _, current_spec, _ = await registry.get_runnable_spec(ctx, submission.agent_id)
        _, pinned_spec, _ = await registry.get_pinned_spec(
            ctx, submission.agent_id, submission.version_id
        )
        cloud_agent(current_spec)
        cloud_agent(pinned_spec)
        message = await conversation_repo.get_message_by_id(self.db, submission.message_id)
        if (
            message is None
            or message.conversation_id != submission.conversation_id
            or message.role != "user"
            or message.author_user_id != submission.requester_id
        ):
            raise NotFoundError(message="The original room message is unavailable")
        saved = RoomMessageCreate(
            client_message_id=submission.client_message_id,
            content=message.content,
            reply_to_message_id=message.reply_to_message_id,
            agent_id=submission.agent_id,
        )
        if fingerprint(saved) != submission.fingerprint:
            raise AlreadyExistsError(message="The original room message has changed")
        return ctx, conversation, message

    async def resume_authority(
        self, run_id: UUID, organization_id: UUID, *, required: bool = False
    ) -> AuthContext | None:
        """Keep a resumed room run on its original requester's current authority."""
        submission = await room_repo.for_run(self.db, run_id, organization_id=organization_id)
        if submission is None:
            if required:
                raise AlreadyExistsError(message="This room request no longer owns its run")
            return None
        if submission.status not in {"running", "awaiting_approval", "awaiting_answer"}:
            raise AlreadyExistsError(message="This room request no longer owns its run")
        first = await room_repo.head(self.db, submission.conversation_id)
        if first is None or first.id != submission.id:
            raise AlreadyExistsError(message="This room request is not the room's current turn")
        ctx, _, _ = await self.authority(submission)
        return ctx

    async def list_for_room(
        self, ctx: AuthContext, conversation_id: UUID, *, skip: int = 0, limit: int = 50
    ) -> RoomAgentRequestList:
        signed_in(ctx)
        room = await self.room(ctx, conversation_id)
        can_post = not room.is_archived
        if can_post:
            try:
                await self.room(ctx, conversation_id, for_write=True)
            except AuthorizationError, NotFoundError:
                can_post = False
        rows, total = await room_repo.list_requests(
            self.db,
            organization_id=ctx.organization_id,
            conversation_id=conversation_id,
            skip=skip,
            limit=limit,
        )
        return RoomAgentRequestList(
            items=[RoomAgentRequestRead.model_validate(row) for row in rows],
            total=total,
            can_post=can_post,
        )

    async def cancel(
        self, ctx: AuthContext, conversation_id: UUID, request_id: UUID
    ) -> RoomAgentRequestRead:
        signed_in(ctx)
        await self.room(ctx, conversation_id, for_write=True)
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation_id)
        submission = await room_repo.get(
            self.db, request_id, organization_id=ctx.organization_id, lock=True
        )
        if (
            submission is None
            or submission.conversation_id != conversation_id
            or submission.agent_id is None
            or submission.requester_id != ctx.subject_id
        ):
            raise NotFoundError(message="Room request not found")
        if submission.status == "cancelled":
            return RoomAgentRequestRead.model_validate(submission)
        if submission.status != "queued":
            raise AlreadyExistsError(message="Only a queued room request can be cancelled")
        submission.status = "cancelled"
        if submission.job_id is not None:
            await job_repo.cancel_queued(self.db, submission.job_id)
        await room_repo.save(self.db, submission)
        announce_request(self.db, submission)
        return RoomAgentRequestRead.model_validate(submission)
