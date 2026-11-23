"""Durable human posts with explicitly mentioned or opted-in agent replies."""

import hashlib
import json
import re
from collections.abc import Sequence
from typing import Literal
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
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.db.locks import LockScope, hold_subject
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message
from app.db.models.room_submission import RoomSubmission
from app.db.models.user import User
from app.repositories import background_job as job_repo
from app.repositories import chat_file as chat_file_repo
from app.repositories import conversation as conversation_repo
from app.repositories import room_message_reaction as reaction_repo
from app.repositories import room_submission as room_repo
from app.schemas.conversation import ChatPerson, MessageCreate, MessageFileRead, MessageRead
from app.schemas.room_participant import RoomMentionRead, RoomParticipantRead, RoomParticipantRef
from app.schemas.room_submission import (
    RoomAgentRequestList,
    RoomAgentRequestRead,
    RoomMessageCreate,
    RoomMessageRead,
    RoomThreadRead,
)
from app.services import chat_room
from app.services.access import acting_member
from app.services.agent_registry import AgentRegistryService
from app.services.background_jobs import enqueue
from app.services.conversation import ConversationService
from app.worker.jobs import RUN_ROOM_REQUEST, RoomRequestJob

TERMINAL = frozenset({"completed", "failed", "cancelled", "interrupted"})
MAX_ACTIVE = 50
MAX_AUTOMATIC_AGENTS = 4


def automatic_targets(
    content: str, candidates: Sequence[RoomParticipantRead]
) -> list[RoomParticipantRead]:
    """Choose only opted-in, already-authorized members without buying a router model call.

    Acknowledgements need no answer. A broad request reaches up to four bots;
    otherwise a named candidate wins, then the first configured candidate.
    Explicit mentions bypass this rule and are never expanded automatically.
    """
    normalized = " ".join(content.casefold().split())
    if re.fullmatch(r"(?:thanks?|thank you|ok(?:ay)?|got it|understood)[.! ]*", normalized):
        return []
    if re.search(r"(?:^|\s)@everyone\b|\ball agents\b", normalized):
        return list(candidates[:MAX_AUTOMATIC_AGENTS])
    named = [
        item
        for item in candidates
        if item.name and re.search(rf"(?<!\w){re.escape(item.name.casefold())}(?!\w)", normalized)
    ]
    return named[:MAX_AUTOMATIC_AGENTS] if named else list(candidates[:1])


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
        raise BadRequestError(message="Choose a cloud agent for this room")


def fingerprint(request: RoomMessageCreate) -> str:
    # Existing accepted posts retain their exact digest after this additive
    # upgrade. A null root is the old main-room submission, not a new hash shape.
    scope: dict[str, object] = (
        {"thread_root_message_id": str(request.thread_root_message_id)}
        if request.thread_root_message_id is not None
        else {}
    )
    if request.intent == "ask_lead":
        scope.update(
            intent=request.intent, expected_policy_revision=request.expected_policy_revision
        )
    if request.mentions:
        scope["mentions"] = [
            {"kind": mention.kind, "id": str(mention.id)}
            for mention in sorted(request.mentions, key=lambda item: (item.kind, str(item.id)))
        ]
    if request.file_ids:
        scope["file_ids"] = sorted(str(file_id) for file_id in request.file_ids)
    quote = {"reply_to_excerpt": request.reply_to_excerpt} if request.reply_to_excerpt else {}
    encoded = json.dumps(
        {
            "content": request.content,
            "reply_to_message_id": str(request.reply_to_message_id)
            if request.reply_to_message_id
            else None,
            "agent_id": str(request.agent_id) if request.agent_id else None,
            **scope,
            **quote,
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
        if conversation.project_id is None and conversation.room_visibility is None:
            raise BadRequestError(message="Add participants to make this conversation a room")
        if for_write and conversation.is_archived:
            raise BadRequestError(message="Conversation is archived")
        return conversation

    async def attachments(
        self, message: Message, requester_id: UUID, *, include_content: bool = False
    ) -> list[ChatFile]:
        return await chat_file_repo.for_message(
            self.db,
            message_id=message.id,
            conversation_id=message.conversation_id,
            user_id=requester_id,
            include_content=include_content,
        )

    async def read_message(
        self, message: Message, user: User, *, organization_id: UUID
    ) -> MessageRead:
        if message.role != "user":
            raise BadRequestError(message="The original room message is not a human post")
        reactions = await reaction_repo.list_aggregates(
            self.db,
            organization_id=organization_id,
            conversation_id=message.conversation_id,
            message_ids=[message.id],
            user_id=user.id,
        )
        return MessageRead(
            id=message.id,
            conversation_id=message.conversation_id,
            role="user",
            content=message.content,
            client_message_id=message.client_message_id,
            run_id=message.run_id,
            created_at=message.created_at,
            updated_at=message.updated_at,
            room_mentions=[
                RoomMentionRead.model_validate(value) for value in message.room_mentions or []
            ],
            files=[
                MessageFileRead.model_validate(file)
                for file in await self.attachments(message, user.id)
            ],
            sender=ChatPerson.of(user),
            reactions=reactions.get(message.id, []),
            reply_to=await self.conversations.reply_quoted(message),
            thread_root_message_id=message.thread_root_message_id,
        )

    async def post(
        self, ctx: AuthContext, conversation_id: UUID, request: RoomMessageCreate, user: User
    ) -> RoomMessageRead:
        signed_in(ctx)
        if user.id != ctx.subject_id:
            raise AuthorizationError(message="Post room messages as yourself")
        # Admission and turn claiming share this transaction lock: once a room
        # request is accepted, a new legacy foreground turn cannot overtake it.
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation_id)
        conversation = await self.room(ctx, conversation_id, for_write=True)
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
            return await self._result(existing, message, user)

        if request.thread_root_message_id is not None:
            from app.services.room_thread import RoomThreadService

            try:
                await RoomThreadService(self.db).assert_replyable(
                    conversation_id, request.thread_root_message_id
                )
            except NotFoundError as exc:
                # Keep the existing post-validation contract for malformed or
                # foreign roots while checking archive state before any write.
                raise refused_field(
                    "thread_root_message_id", "Choose a top-level message in this room"
                ) from exc

        from app.services.room_participant import RoomParticipantService

        participants = RoomParticipantService(self.db)
        mentions = (
            await participants.validate_mentions(ctx, conversation_id, request.mentions)
            if request.mentions
            else []
        )
        dispatch, targets = await self._targets(ctx, conversation, request, mentions)
        if request.file_ids:
            await self.conversations.list_attached_files(
                [str(file_id) for file_id in request.file_ids], user_id=ctx.subject_id
            )
        if (
            targets
            and await room_repo.active_count(self.db, conversation_id=conversation_id)
            + len(targets)
            > MAX_ACTIVE
        ):
            raise AlreadyExistsError(message="This room already has fifty agent requests waiting")
        message = await self.conversations.add_message(
            conversation_id,
            MessageCreate(
                role="user",
                content=request.content,
                client_message_id=request.client_message_id,
                reply_to_message_id=request.reply_to_message_id,
                reply_to_excerpt=request.reply_to_excerpt,
            ),
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            thread_root_message_id=request.thread_root_message_id,
        )
        if request.file_ids:
            await self.conversations.link_files_to_message(
                message.id,
                [str(file_id) for file_id in request.file_ids],
                user_id=ctx.subject_id,
            )
        if mentions:
            await room_repo.keep_mentions(
                self.db,
                message=message,
                mentions=[
                    {"kind": mention.kind, "id": str(mention.id), "name": mention.name}
                    for mention in mentions
                ],
            )
        agent_id, version_id = targets[0] if targets else (None, None)
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
                dispatch=dispatch,
                agent_id=agent_id,
                version_id=version_id,
                intent=request.intent,
                lead_policy_revision=request.expected_policy_revision,
                status="queued" if agent_id is not None else "posted",
            ),
        )
        if agent_id is not None:
            await self.queue(submission)
            announce_request(self.db, submission)
        requests = [RoomAgentRequestRead.model_validate(submission)] if agent_id is not None else []
        for extra_agent_id, extra_version_id in targets[1:]:
            extra = await room_repo.add(
                self.db,
                RoomSubmission(
                    id=uuid4(),
                    organization_id=ctx.organization_id,
                    conversation_id=conversation_id,
                    requester_id=ctx.subject_id,
                    message_id=message.id,
                    client_message_id=request.client_message_id,
                    fingerprint=digest,
                    parent_submission_id=submission.id,
                    dispatch=dispatch,
                    agent_id=extra_agent_id,
                    version_id=extra_version_id,
                    intent="message",
                    status="queued",
                ),
            )
            await self.queue(extra)
            announce_request(self.db, extra)
            requests.append(RoomAgentRequestRead.model_validate(extra))
        recipients = [
            mention.id
            for mention in mentions
            if mention.kind == "user" and mention.id != ctx.subject_id
        ]
        if recipients:
            from app.services.notifications import NotificationService

            await NotificationService(self.db).room_mentioned(
                recipients=recipients,
                organization_id=ctx.organization_id,
                conversation_id=conversation_id,
                message_id=message.id,
                thread_root_message_id=message.thread_root_message_id,
                title=conversation.title,
                sender=user.full_name or user.email,
                actor_user_id=ctx.subject_id,
            )
        if message.thread_root_message_id is not None:
            from app.services.room_thread import RoomThreadService

            await RoomThreadService(self.db).reply_saved(
                organization_id=ctx.organization_id,
                conversation_id=conversation_id,
                root_message_id=message.thread_root_message_id,
                reply_message_id=message.id,
                actor_user_id=ctx.subject_id,
                sender=user.full_name or user.email,
                excluded_user_ids=set(recipients),
            )
        spawn_after_commit(
            self.db,
            chat_room.room_message(str(conversation_id), message.id),
            name="room-message-posted",
        )
        return RoomMessageRead(
            message=await self.read_message(message, user, organization_id=ctx.organization_id),
            request=RoomAgentRequestRead.model_validate(submission)
            if submission.agent_id is not None
            else None,
            requests=requests,
        )

    async def _result(
        self, submission: RoomSubmission, message: Message, user: User
    ) -> RoomMessageRead:
        rows = (
            await room_repo.for_post(self.db, root=submission)
            if submission.dispatch in {"mention", "automatic"}
            else [submission]
        )
        requests = [
            RoomAgentRequestRead.model_validate(row) for row in rows if row.agent_id is not None
        ]
        return RoomMessageRead(
            message=await self.read_message(
                message, user, organization_id=submission.organization_id
            ),
            request=requests[0] if requests else None,
            requests=requests,
        )

    async def _targets(
        self,
        ctx: AuthContext,
        conversation: Conversation,
        request: RoomMessageCreate,
        mentions: Sequence[RoomParticipantRead],
    ) -> tuple[Literal["explicit", "mention", "automatic"], list[tuple[UUID, UUID]]]:
        from app.services.room_participant import RoomParticipantService

        participants = RoomParticipantService(self.db)
        if request.intent == "ask_lead":
            from app.services.room_routing import RoomRoutingService

            assert request.expected_policy_revision is not None, "validated Ask lead request"
            target = await RoomRoutingService(self.db).admit(
                ctx, conversation.id, request.expected_policy_revision
            )
            return "explicit", [target]
        selected = [mention.id for mention in mentions if mention.kind == "agent"]
        dispatch: Literal["explicit", "mention", "automatic"] = (
            "mention" if selected else "explicit"
        )
        if request.agent_id is not None:
            if conversation.room_visibility is not None:
                await participants.validate_mentions(
                    ctx,
                    conversation.id,
                    [RoomParticipantRef(kind="agent", id=request.agent_id)],
                )
            selected = [request.agent_id]
        elif not mentions:
            candidates = await participants.automatic_agents(ctx, conversation.id)
            selected = [item.id for item in automatic_targets(request.content, candidates)]
            if selected:
                dispatch = "automatic"
        registry = AgentRegistryService(self.db)
        targets: list[tuple[UUID, UUID]] = []
        for agent_id in selected:
            _, spec, version_id = await registry.get_runnable_spec(ctx, agent_id)
            cloud_agent(spec)
            targets.append((agent_id, version_id))
        return dispatch, targets

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
        dispatch = submission.dispatch or "explicit"
        if conversation.room_visibility is not None or dispatch in {"mention", "automatic"}:
            from app.services.room_participant import RoomParticipantService

            members = await RoomParticipantService(self.db).validate_mentions(
                ctx,
                conversation.id,
                [RoomParticipantRef(kind="agent", id=submission.agent_id)],
            )
            if dispatch == "automatic" and not members[0].auto_reply:
                raise AuthorizationError(message="Automatic replies were disabled for this agent")
        if submission.intent == "ask_lead":
            from app.services.room_routing import RoomRoutingService

            await RoomRoutingService(self.db).submission_policy(ctx, submission)
        message = await conversation_repo.get_message_by_id(self.db, submission.message_id)
        if (
            message is None
            or message.conversation_id != submission.conversation_id
            or message.role != "user"
            or message.author_user_id != submission.requester_id
        ):
            raise NotFoundError(message="The original room message is unavailable")
        if message.thread_root_message_id is not None:
            from app.services.room_thread import RoomThreadService

            await RoomThreadService(self.db).assert_replyable(
                submission.conversation_id, message.thread_root_message_id
            )
        mentions = [
            RoomParticipantRef.model_validate(value) for value in message.room_mentions or []
        ]
        if dispatch == "mention" and not any(
            mention.kind == "agent" and mention.id == submission.agent_id for mention in mentions
        ):
            raise AlreadyExistsError(message="The original post did not mention this agent")
        if submission.parent_submission_id is not None:
            parent = await room_repo.get(
                self.db, submission.parent_submission_id, organization_id=submission.organization_id
            )
            if (
                parent is None
                or parent.parent_submission_id is not None
                or parent.conversation_id != submission.conversation_id
                or parent.message_id != submission.message_id
                or parent.requester_id != submission.requester_id
                or parent.client_message_id != submission.client_message_id
                or parent.fingerprint != submission.fingerprint
                or parent.dispatch != dispatch
            ):
                raise AlreadyExistsError(
                    message="This answer no longer belongs to its original post"
                )
        files = await self.attachments(message, submission.requester_id)
        if not message.content.strip() and not files:
            raise AlreadyExistsError(message="The original room attachments are unavailable")
        saved = RoomMessageCreate(
            client_message_id=submission.client_message_id,
            content=message.content,
            file_ids=[file.id for file in files],
            reply_to_message_id=message.reply_to_message_id,
            reply_to_excerpt=message.reply_to_excerpt,
            thread_root_message_id=message.thread_root_message_id,
            agent_id=(
                submission.agent_id
                if dispatch == "explicit" and submission.intent != "ask_lead"
                else None
            ),
            mentions=mentions,
            intent="ask_lead" if submission.intent == "ask_lead" else "message",
            expected_policy_revision=submission.lead_policy_revision,
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
        if submission.intent == "ask_lead":
            raise AlreadyExistsError(
                message="Start a new Ask lead request instead of resuming a planning run"
            )
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

    async def thread(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        root_message_id: UUID,
        *,
        limit: int = 50,
        latest: bool = True,
        before: UUID | None = None,
    ) -> RoomThreadRead:
        """Read a root and paged replies under the conversation's current audience.

        Existing subthreads remain readable, including after a project chat loses
        its project. Posts are accepted only in a project chat or an explicit room.
        """
        signed_in(ctx)
        room = await self.conversations.get_conversation(
            conversation_id,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            include_favourite=False,
            ctx=ctx,
        )
        items, total, _ = await self.conversations.transcript(
            conversation_id,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            ctx=ctx,
            include_tool_calls=True,
            limit=limit,
            latest=latest,
            before=before,
            thread_root_message_id=root_message_id,
        )
        root = MessageRead.model_validate(items[0])
        summary = root.thread_summary
        thread_archived = summary is not None and summary.state == "archived"
        can_post = (
            (room.project_id is not None or room.room_visibility is not None)
            and not room.is_archived
            and not thread_archived
        )
        if can_post:
            try:
                await self.room(ctx, conversation_id, for_write=True)
            except AuthorizationError, NotFoundError:
                can_post = False
        return RoomThreadRead(
            root=root,
            items=[MessageRead.model_validate(item) for item in items[1:]],
            total=total - 1,
            can_post=can_post,
            state=summary.state if summary else "open",
            can_manage=summary.can_manage if summary else False,
            following=summary.following if summary else False,
            unread=summary.unread if summary else 0,
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
