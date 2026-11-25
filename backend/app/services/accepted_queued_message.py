"""Atomically accept, send, cancel or transfer a personal chat queue item."""

import hashlib
import json
import re
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.locks import LockScope, hold_subject
from app.db.models.accepted_queued_message import AcceptedQueuedMessage
from app.db.models.agent import Agent
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message
from app.db.models.conversation_task import ConversationTask
from app.repositories import agent_run as agent_run_repo
from app.repositories import chat_file as chat_file_repo
from app.repositories import conversation_task as task_repo
from app.repositories import queued_message_receipt as receipt_repo
from app.repositories import user as user_repo
from app.schemas.accepted_queued_message import (
    AcceptedQueuedMessageCreate,
    AcceptedQueuedMessageList,
    AcceptedQueuedMessageRead,
)
from app.schemas.conversation_task import ConversationTaskRead
from app.schemas.mention import MentionRef
from app.services.access import member_context
from app.services.agent_registry import AgentRegistryService
from app.services.background_jobs import enqueue
from app.services.conversation import (
    ConversationService,
    _excerpt,
    _normalize_quote,
    _rendered_quote_text,
)
from app.services.mentions import ResolvedMentions
from app.services.transcript import what_arrived
from app.worker.jobs import RUN_CONVERSATION_TASK, ConversationTaskJob

_TITLE_LIMIT = 160
MAX_PENDING_PER_CONVERSATION = 100


def _fingerprint(payload: JsonValue) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _file_ids(receipt: AcceptedQueuedMessage) -> list[UUID]:
    return _payload_model(receipt).file_ids


def _payload_model(receipt: AcceptedQueuedMessage) -> AcceptedQueuedMessageCreate:
    """Validate database JSON before it drives any send or attachment lookup."""
    return AcceptedQueuedMessageCreate.model_validate(
        {key: value for key, value in receipt.payload.items() if key != "quote_snapshot"}
    )


def _mention_parts(resolved: ResolvedMentions | None) -> list[dict[str, str]] | None:
    if resolved is None or not resolved.mentions:
        return None
    return [
        {
            "type": "mention",
            "mention_kind": mention.kind,
            "mention_id": mention.id,
            "text": mention.name,
        }
        for mention in resolved.mentions
    ]


class AcceptedQueuedMessageService:
    """The database receipt is the serialization point shared by send and task transfer."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.conversations = ConversationService(db)

    async def _current_personal_context(self, ctx: AuthContext) -> AuthContext:
        """Refresh member authority before accepting or executing a receipt."""
        if (
            ctx.user_id is None
            or ctx.subject_id != ctx.user_id
            or ctx.organization_id is None
            or ctx.api_key_id is not None
            or ctx.key_scopes is not None
            or ctx.is_impersonated
            or ctx.is_workflow
            or ctx.fired_as_creator is not None
            or ctx.routine_id is not None
            or ctx.routine_source_policy_id is not None
            or ctx.routine_activation_id is not None
            or ctx.source_conversation_id is not None
        ):
            raise AuthorizationError(message="Queued messages need a signed-in organization member")
        current = await member_context(
            self.db, organization_id=ctx.organization_id, user_id=ctx.subject_id
        )
        if current is None:
            raise AuthorizationError(message="The organization membership is no longer active")
        return current

    async def _personal_source(self, ctx: AuthContext, conversation_id: UUID) -> Conversation:
        if (
            ctx.user_id is None
            or ctx.subject_id != ctx.user_id
            or ctx.organization_id is None
            or ctx.api_key_id is not None
            or ctx.key_scopes is not None
            or ctx.is_impersonated
            or ctx.is_workflow
            or ctx.fired_as_creator is not None
            or ctx.routine_id is not None
            or ctx.routine_source_policy_id is not None
            or ctx.routine_activation_id is not None
            or ctx.source_conversation_id is not None
        ):
            raise AuthorizationError(message="Queued messages need a signed-in organization member")
        conversation = await self.conversations.get_conversation(
            conversation_id,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            for_write=True,
            turn=True,
            include_favourite=False,
            ctx=ctx,
        )
        if (
            conversation.user_id != ctx.subject_id
            or conversation.organization_id != ctx.organization_id
            or conversation.room_visibility is not None
            or conversation.project_id is not None
            or conversation.workflow_id is not None
            or conversation.source_conversation_id is not None
            or conversation.origin == "api"
            or conversation.is_archived
            or await receipt_repo.is_channel_conversation(self.db, conversation.id)
        ):
            raise NotFoundError(message="Queued messages are available only in your personal chats")
        return conversation

    async def _validate_agent(
        self, ctx: AuthContext, agent_id: UUID
    ) -> tuple[Agent, AgentSpec, UUID]:
        agent, spec, version_id = await AgentRegistryService(self.db).get_runnable_spec(
            ctx, agent_id
        )
        if agent.organization_id != ctx.organization_id:
            raise NotFoundError(message="Agent not found")
        return agent, spec, version_id

    async def _validate_mentions(
        self, ctx: AuthContext, agent_id: UUID, refs: list[MentionRef]
    ) -> ResolvedMentions | None:
        if not refs:
            return None
        user = await user_repo.get_by_id(self.db, ctx.subject_id)
        if user is None:
            raise NotFoundError(message="Member not found")
        from app.services.agent_chat import ChatAgentRunner

        return await ChatAgentRunner(self.db).mentions(
            user=user,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            refs=refs,
            draft=False,
        )

    async def _validate_files(
        self, ctx: AuthContext, file_ids: list[UUID], *, receipt_id: UUID | None = None
    ) -> list[ChatFile]:
        if not file_ids:
            return []
        rows = await receipt_repo.files_for_owner(
            self.db, set(file_ids), user_id=ctx.subject_id, lock=True
        )
        by_id = {row.id: row for row in rows}
        if len(by_id) != len(set(file_ids)):
            raise NotFoundError(message="One or more queued files are no longer available")
        if any(
            row.message_id is not None or row.queue_receipt_id not in (None, receipt_id)
            for row in rows
        ):
            raise AlreadyExistsError(message="A queued file has already been claimed")
        return [by_id[file_id] for file_id in file_ids]

    async def _quote_snapshot(
        self, conversation_id: UUID, payload: AcceptedQueuedMessageCreate
    ) -> dict[str, JsonValue] | None:
        if payload.reply_to_message_id is None:
            return None
        message = await receipt_repo.quote_message(
            self.db,
            conversation_id=conversation_id,
            message_id=payload.reply_to_message_id,
        )
        if message is None or message.guardrail_refused:
            raise NotFoundError(message="Quoted message not found")
        visible = _rendered_quote_text(message.content)
        excerpt = (
            _normalize_quote(payload.reply_to_excerpt)
            if payload.reply_to_excerpt is not None
            else _excerpt(visible)
        )
        if not excerpt or excerpt not in visible:
            raise BadRequestError(message="The quoted text is no longer visible in that message")
        return {"message_id": str(message.id), "role": message.role, "excerpt": excerpt}

    def _read(
        self,
        receipt: AcceptedQueuedMessage,
        task_id: UUID | None = None,
        task_conversation_id: UUID | None = None,
    ) -> AcceptedQueuedMessageRead:
        payload = _payload_model(receipt)
        quote = receipt.payload.get("quote_snapshot")
        quote_role = None
        quote_excerpt = None
        if quote is not None:
            if (
                not isinstance(quote, dict)
                or set(quote) != {"message_id", "role", "excerpt"}
                or quote.get("message_id") != str(payload.reply_to_message_id)
                or quote.get("role") is None
                or quote.get("excerpt") is None
            ):
                raise AlreadyExistsError(
                    message="The accepted queue quote snapshot is inconsistent"
                )
            quote_role = quote["role"]
            quote_excerpt = quote["excerpt"]
        elif payload.reply_to_message_id is not None:
            raise AlreadyExistsError(message="The accepted queue quote snapshot is missing")
        return AcceptedQueuedMessageRead.model_validate(
            {
                "id": receipt.id,
                "conversation_id": receipt.conversation_id,
                "client_queue_id": receipt.client_queue_id,
                "agent_id": receipt.agent_id,
                "content": payload.content,
                "file_ids": payload.file_ids,
                "mentions": payload.mentions,
                "reply_to_message_id": payload.reply_to_message_id,
                "reply_to_excerpt": payload.reply_to_excerpt,
                "reply_to_role": quote_role,
                "quote_excerpt": quote_excerpt,
                "page_context": payload.page_context,
                "local_target": payload.local_target,
                "state": receipt.state,
                "message_id": receipt.message_id,
                "task_id": task_id,
                "task_conversation_id": task_conversation_id,
                "steering_run_id": receipt.steering_run_id,
                "created_at": receipt.created_at,
            }
        )

    async def accept(
        self, ctx: AuthContext, conversation_id: UUID, data: AcceptedQueuedMessageCreate
    ) -> AcceptedQueuedMessageRead:
        """Persist the server receipt before the current turn has ended."""
        ctx = await self._current_personal_context(ctx)
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation_id)
        conversation = await self._personal_source(ctx, conversation_id)
        await self._validate_agent(ctx, data.agent_id)
        refs = list(data.mentions)
        await self._validate_mentions(ctx, data.agent_id, refs)
        request_payload: dict[str, JsonValue] = data.model_dump(mode="json")
        fingerprint = _fingerprint(request_payload)
        existing = await receipt_repo.for_client_key(
            self.db,
            organization_id=ctx.organization_id,
            requester_id=ctx.subject_id,
            conversation_id=conversation.id,
            client_queue_id=data.client_queue_id,
            lock=True,
        )
        if existing is not None:
            if existing.payload_hash != fingerprint:
                raise AlreadyExistsError(message="That queue key names a different queued message")
            task = await receipt_repo.task_for_receipt(
                self.db, organization_id=ctx.organization_id, receipt_id=existing.id
            )
            return self._read(
                existing,
                None if task is None else task.id,
                None if task is None else task.conversation_id,
            )

        pending_count = await receipt_repo.pending_count(
            self.db,
            organization_id=ctx.organization_id,
            requester_id=ctx.subject_id,
            conversation_id=conversation.id,
        )
        if pending_count >= MAX_PENDING_PER_CONVERSATION:
            raise AlreadyExistsError(message="This conversation already has 100 queued messages")

        quote = await self._quote_snapshot(conversation.id, data)
        stored_payload = dict(request_payload)
        stored_payload["quote_snapshot"] = quote
        receipt = AcceptedQueuedMessage(
            id=uuid4(),
            organization_id=ctx.organization_id,
            conversation_id=conversation.id,
            requester_id=ctx.subject_id,
            client_queue_id=data.client_queue_id,
            agent_id=data.agent_id,
            payload=stored_payload,
            payload_hash=fingerprint,
            state="pending",
        )
        saved = await receipt_repo.add_if_absent(self.db, receipt)
        if saved.payload_hash != fingerprint:
            raise AlreadyExistsError(message="That queue key names a different queued message")
        if saved.state != "pending":
            return self._read(saved)
        files = await self._validate_files(ctx, data.file_ids, receipt_id=saved.id)
        if files:
            reserved = await receipt_repo.reserve_files(
                self.db,
                {file.id for file in files},
                user_id=ctx.subject_id,
                receipt_id=saved.id,
            )
            if reserved != {file.id for file in files}:
                raise AlreadyExistsError(message="A queued file was claimed by another message")
        return self._read(saved)

    async def get_for_owner(
        self, ctx: AuthContext, conversation_id: UUID, receipt_id: UUID
    ) -> AcceptedQueuedMessageRead:
        ctx = await self._current_personal_context(ctx)
        await self._personal_source(ctx, conversation_id)
        receipt = await receipt_repo.get(
            self.db,
            receipt_id,
            organization_id=ctx.organization_id,
            requester_id=ctx.subject_id,
        )
        if receipt is None or receipt.conversation_id != conversation_id:
            raise NotFoundError(message="Queued message not found")
        task = await receipt_repo.task_for_receipt(
            self.db, organization_id=ctx.organization_id, receipt_id=receipt.id
        )
        return self._read(
            receipt,
            None if task is None else task.id,
            None if task is None else task.conversation_id,
        )

    async def list_pending(
        self, ctx: AuthContext, conversation_id: UUID, cursor: UUID | None = None
    ) -> AcceptedQueuedMessageList:
        ctx = await self._current_personal_context(ctx)
        await self._personal_source(ctx, conversation_id)
        rows = await receipt_repo.pending_for_owner(
            self.db,
            organization_id=ctx.organization_id,
            requester_id=ctx.subject_id,
            conversation_id=conversation_id,
            cursor=cursor,
        )
        has_more = len(rows) > 100
        page = rows[:100]
        return AcceptedQueuedMessageList(
            items=[self._read(row) for row in page],
            next_cursor=page[-1].id if has_more and page else None,
        )

    async def cancel(
        self, ctx: AuthContext, conversation_id: UUID, receipt_id: UUID
    ) -> AcceptedQueuedMessageRead:
        ctx = await self._current_personal_context(ctx)
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation_id)
        await self._personal_source(ctx, conversation_id)
        receipt = await receipt_repo.get(
            self.db,
            receipt_id,
            organization_id=ctx.organization_id,
            requester_id=ctx.subject_id,
            lock=True,
        )
        if receipt is None or receipt.conversation_id != conversation_id:
            raise NotFoundError(message="Queued message not found")
        if receipt.state == "cancelled":
            return self._read(receipt)
        if receipt.state != "pending":
            raise AlreadyExistsError(message="The queued message has already been claimed")
        ids = _file_ids(receipt)
        await receipt_repo.release_files(
            self.db, ids, user_id=ctx.subject_id, receipt_id=receipt.id
        )
        receipt.state = "cancelled"
        await self.db.flush()
        return self._read(receipt)

    async def _locked_receipt(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        receipt_id: UUID,
        data: AcceptedQueuedMessageCreate | None = None,
    ) -> tuple[Conversation, AcceptedQueuedMessage]:
        conversation = await self._personal_source(ctx, conversation_id)
        receipt = await receipt_repo.get(
            self.db,
            receipt_id,
            organization_id=ctx.organization_id,
            requester_id=ctx.subject_id,
            lock=True,
        )
        if receipt is None or receipt.conversation_id != conversation_id:
            raise NotFoundError(message="Queued message not found")
        if data is not None and (
            receipt.client_queue_id != data.client_queue_id
            or receipt.payload_hash != _fingerprint(data.model_dump(mode="json"))
        ):
            raise AlreadyExistsError(message="The queued payload changed after it was accepted")
        return conversation, receipt

    async def claim_for_send(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        receipt_id: UUID,
        data: AcceptedQueuedMessageCreate | None = None,
    ) -> Message:
        """Claim and persist one queued user message in the same transaction."""
        ctx = await self._current_personal_context(ctx)
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation_id)
        _conversation, receipt = await self._locked_receipt(ctx, conversation_id, receipt_id, data)
        # The receipt is the authority for accepted content. The optional payload
        # remains useful to reject legacy clients that resend an edited body, but
        # a caller may claim by its owner-scoped receipt id alone.
        data = _payload_model(receipt)
        if receipt.state == "sent" and receipt.message_id is not None:
            message = await receipt_repo.message_by_id(self.db, receipt.message_id)
            if message is not None:
                return message
            raise AlreadyExistsError(message="The accepted message no longer exists")
        if receipt.state != "pending":
            raise AlreadyExistsError(message="The queued message was cancelled or transferred")
        await self._validate_agent(ctx, receipt.agent_id)
        refs = data.mentions
        resolved_mentions = await self._validate_mentions(ctx, receipt.agent_id, list(refs))
        files = await self._validate_files(ctx, data.file_ids, receipt_id=receipt.id)
        quote = await self._quote_snapshot(conversation_id, data)
        if quote != receipt.payload.get("quote_snapshot"):
            raise AlreadyExistsError(message="The quoted message changed after it was queued")
        content = data.content or what_arrived(files)
        message = Message(
            id=uuid4(),
            conversation_id=conversation_id,
            role="user",
            content=content,
            author_user_id=ctx.subject_id,
            reply_to_message_id=data.reply_to_message_id,
            reply_to_excerpt=None if quote is None else quote["excerpt"],
            parts=_mention_parts(resolved_mentions),
            accepted_queue_id=receipt.id,
        )
        self.db.add(message)
        await self.db.flush()
        if files and await receipt_repo.attach_reserved_files(
            self.db,
            {file.id for file in files},
            user_id=ctx.subject_id,
            receipt_id=receipt.id,
            message_id=message.id,
        ) != {file.id for file in files}:
            raise AlreadyExistsError(message="A queued file was claimed by another message")
        receipt.state = "sent"
        receipt.message_id = message.id
        await self.db.flush()
        return message

    async def claim_for_steer(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        receipt_id: UUID,
        *,
        run_id: UUID,
        active_agent_id: UUID,
    ) -> str:
        """Claim a text-only receipt for the exact active personal chat run."""
        ctx = await self._current_personal_context(ctx)
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation_id)
        await self._personal_source(ctx, conversation_id)
        receipt = await receipt_repo.get(
            self.db,
            receipt_id,
            organization_id=ctx.organization_id,
            requester_id=ctx.subject_id,
            lock=True,
        )
        if receipt is None or receipt.conversation_id != conversation_id:
            raise NotFoundError(message="Queued message not found")
        if receipt.agent_id != active_agent_id:
            raise AlreadyExistsError(message="The queued message targets a different active agent")
        if receipt.state in {"steering", "steered"}:
            if receipt.steering_run_id != run_id:
                raise AlreadyExistsError(message="The queued message belongs to another run")
            return receipt.state
        if receipt.state != "pending":
            raise AlreadyExistsError(message="The queued message was already sent or cancelled")
        payload = _payload_model(receipt)
        if (
            not payload.content.strip()
            or payload.file_ids
            or payload.mentions
            or payload.reply_to_message_id is not None
            or payload.reply_to_excerpt is not None
            or payload.page_context is not None
            or payload.local_target is not None
        ):
            raise BadRequestError(message="Send now can steer only a plain text queued message")
        await self._validate_agent(ctx, receipt.agent_id)
        run = await agent_run_repo.active_personal_chat_run(
            self.db,
            run_id=run_id,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            conversation_id=conversation_id,
            agent_id=active_agent_id,
        )
        if run is None:
            raise AlreadyExistsError(message="The active chat run is no longer available")
        receipt.state = "steering"
        receipt.steering_run_id = run.id
        await self.db.flush()
        return "claimed"

    async def finish_steer(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        receipt_id: UUID,
        *,
        run_id: UUID,
    ) -> bool:
        """Fence runner consumption before the corresponding provider request."""
        ctx = await self._current_personal_context(ctx)
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation_id)
        await self._personal_source(ctx, conversation_id)
        receipt = await receipt_repo.get(
            self.db,
            receipt_id,
            organization_id=ctx.organization_id,
            requester_id=ctx.subject_id,
            lock=True,
        )
        if receipt is None or receipt.conversation_id != conversation_id:
            raise NotFoundError(message="Queued message not found")
        if receipt.state == "steered" and receipt.steering_run_id == run_id:
            return False
        if receipt.state != "steering" or receipt.steering_run_id != run_id:
            raise AlreadyExistsError(message="The queued message is not claimed by this run")
        receipt.state = "steered"
        await self.db.flush()
        return True

    async def release_unconsumed_steer(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        receipt_id: UUID,
        *,
        run_id: UUID,
    ) -> bool:
        """Release only a same-run receipt proven untouched by every inbox."""
        ctx = await self._current_personal_context(ctx)
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation_id)
        await self._personal_source(ctx, conversation_id)
        receipt = await receipt_repo.get(
            self.db,
            receipt_id,
            organization_id=ctx.organization_id,
            requester_id=ctx.subject_id,
            lock=True,
        )
        if receipt is None or receipt.conversation_id != conversation_id:
            raise NotFoundError(message="Queued message not found")
        if receipt.state == "pending":
            return True
        if receipt.state != "steering" or receipt.steering_run_id != run_id:
            return False
        receipt.state = "pending"
        receipt.steering_run_id = None
        await self.db.flush()
        return True

    async def run_as_task(
        self, ctx: AuthContext, conversation_id: UUID, receipt_id: UUID
    ) -> ConversationTaskRead:
        """Transfer one pending receipt into a private task topic under the same lock as send."""
        ctx = await self._current_personal_context(ctx)
        await hold_subject(self.db, LockScope.CONVERSATION_TASKS, ctx.subject_id)
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation_id)
        conversation = await self._personal_source(ctx, conversation_id)
        receipt = await receipt_repo.get(
            self.db,
            receipt_id,
            organization_id=ctx.organization_id,
            requester_id=ctx.subject_id,
            lock=True,
        )
        if receipt is None or receipt.conversation_id != conversation_id:
            raise NotFoundError(message="Queued message not found")
        if receipt.state == "task":
            task = await receipt_repo.task_for_receipt(
                self.db, organization_id=ctx.organization_id, receipt_id=receipt.id
            )
            if task is None:
                raise AlreadyExistsError(message="Task transfer is already claimed")
            return ConversationTaskRead.model_validate(task)
        if receipt.state != "pending":
            raise AlreadyExistsError(message="The queued message was already sent or cancelled")
        payload = AcceptedQueuedMessageCreate.model_validate(
            {key: value for key, value in receipt.payload.items() if key != "quote_snapshot"}
        )
        if (
            payload.agent_id != receipt.agent_id
            or payload.client_queue_id != receipt.client_queue_id
        ):
            raise AlreadyExistsError(message="The accepted queue record is inconsistent")
        agent, _spec, version_id = await self._validate_agent(ctx, receipt.agent_id)
        resolved_mentions = await self._validate_mentions(
            ctx, receipt.agent_id, list(payload.mentions)
        )
        files = await self._validate_files(ctx, payload.file_ids, receipt_id=receipt.id)
        quote = await self._quote_snapshot(conversation_id, payload)
        if quote != receipt.payload.get("quote_snapshot"):
            raise AlreadyExistsError(message="The quoted message changed after it was queued")
        if payload.local_target is not None and (
            payload.local_target.computer_grant is not None
            or payload.local_target.routine_grant is not None
            or payload.local_target.device_id is None
        ):
            raise BadRequestError(
                message=(
                    "Choose an approved folder and a specific computer before delegating local work"
                )
            )
        if (
            await task_repo.active_count(
                self.db, organization_id=ctx.organization_id, user_id=ctx.subject_id
            )
            >= 4
        ):
            raise AlreadyExistsError(message="Four tasks are already active")

        title_source = (
            payload.content.strip().splitlines()[0] if payload.content.strip() else "Queued message"
        )
        title = re.sub(r"\s+", " ", title_source)[:_TITLE_LIMIT] or "Queued message"
        topic = Conversation(
            id=uuid4(),
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            title=title,
        )
        self.db.add(topic)
        await self.db.flush()
        seed_content = payload.content or what_arrived(files)
        if quote is not None:
            quoted = f"Quoted earlier {quote['role']} message:\n> {quote['excerpt']}"
            seed_content = f"{seed_content}\n\n{quoted}" if seed_content else quoted
        seed_message = Message(
            id=uuid4(),
            conversation_id=topic.id,
            role="user",
            content=seed_content,
            author_user_id=ctx.subject_id,
            reply_to_message_id=None,
            reply_to_excerpt=None,
            parts=_mention_parts(resolved_mentions),
            accepted_queue_id=receipt.id,
        )
        self.db.add(seed_message)
        await self.db.flush()
        if files and await receipt_repo.attach_reserved_files(
            self.db,
            {file.id for file in files},
            user_id=ctx.subject_id,
            receipt_id=receipt.id,
            message_id=seed_message.id,
        ) != {file.id for file in files}:
            raise AlreadyExistsError(message="A queued file was claimed by another task")

        prompt = payload.content
        if quote is not None:
            prompt = (
                f"{prompt}\n\nQuoted earlier {quote['role']} message:\n> {quote['excerpt']}"
                if prompt
                else f"Quoted earlier {quote['role']} message:\n> {quote['excerpt']}"
            )
        if resolved_mentions is not None and resolved_mentions.note:
            prompt = f"{prompt}\n\n{resolved_mentions.note}" if prompt else resolved_mentions.note
        task = ConversationTask(
            id=uuid4(),
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            source_conversation_id=conversation.id,
            conversation_id=topic.id,
            source_run_id=None,
            source_agent_id=agent.id,
            source_version_id=version_id,
            agent_id=agent.id,
            version_id=version_id,
            source_model_profile_id=None,
            tool_call_id=None,
            queue_receipt_id=receipt.id,
            title=title,
            prompt=prompt,
            local_target=(
                None
                if payload.local_target is None
                else payload.local_target.model_dump(mode="json")
            ),
            status="queued",
            delivery="pending",
        )
        await task_repo.add(self.db, task)
        task.job_id = await enqueue(
            self.db,
            RUN_CONVERSATION_TASK,
            ConversationTaskJob(task_id=task.id, organization_id=ctx.organization_id),
            organization_id=ctx.organization_id,
            idempotency_key=f"conversation-task:{task.id}",
        )
        await task_repo.save(self.db, task)
        receipt.state = "task"
        receipt.message_id = seed_message.id
        await self.db.flush()
        return ConversationTaskRead.model_validate(task)

    async def task_input_for_worker(
        self, ctx: AuthContext, task: ConversationTask
    ) -> tuple[str, UUID | None, list[ChatFile]]:
        """Reload the frozen task input and attachments under current authority."""
        ctx = await self._current_personal_context(ctx)
        if task.queue_receipt_id is None:
            return task.prompt, None, []
        receipt = await receipt_repo.get(
            self.db,
            task.queue_receipt_id,
            organization_id=ctx.organization_id,
            requester_id=ctx.subject_id,
        )
        if (
            receipt is None
            or receipt.state != "task"
            or receipt.conversation_id != task.source_conversation_id
            or receipt.message_id is None
            or task.user_id != ctx.subject_id
            or task.organization_id != ctx.organization_id
            or task.agent_id != receipt.agent_id
            or task.source_run_id is not None
            or task.tool_call_id is not None
        ):
            raise NotFoundError(message="The accepted task receipt is no longer available")
        payload = _payload_model(receipt)
        expected_local = (
            None if payload.local_target is None else payload.local_target.model_dump(mode="json")
        )
        if (
            payload.agent_id != task.agent_id
            or payload.client_queue_id != receipt.client_queue_id
            or task.local_target != expected_local
        ):
            raise AlreadyExistsError(message="The accepted task receipt no longer matches its task")
        source = await self._personal_source(ctx, task.source_conversation_id)
        seed = await receipt_repo.task_seed_message(
            self.db,
            message_id=receipt.message_id,
            conversation_id=task.conversation_id,
            receipt_id=receipt.id,
            user_id=ctx.subject_id,
        )
        if seed is None:
            raise NotFoundError(message="The accepted task's message is no longer available")
        await self._validate_agent(ctx, task.agent_id)
        quote = await self._quote_snapshot(source.id, payload)
        if quote != receipt.payload.get("quote_snapshot"):
            raise AlreadyExistsError(
                message="The quoted message changed after this task was queued"
            )
        resolved_mentions = await self._validate_mentions(
            ctx, task.agent_id, list(payload.mentions)
        )
        attachments = await chat_file_repo.for_message(
            self.db,
            message_id=seed.id,
            conversation_id=task.conversation_id,
            user_id=ctx.subject_id,
            include_content=True,
        )
        files_by_id = {file.id: file for file in attachments}
        if set(files_by_id) != set(payload.file_ids):
            raise NotFoundError(message="One or more queued task files are no longer available")
        if any(file.queue_receipt_id is not None for file in attachments):
            raise AlreadyExistsError(message="A queued task file is still reserved")
        attachments = [files_by_id[file_id] for file_id in payload.file_ids]
        prompt = payload.content
        if quote is not None:
            quoted = f"Quoted earlier {quote['role']} message:\n> {quote['excerpt']}"
            prompt = f"{prompt}\n\n{quoted}" if prompt else quoted
        if resolved_mentions is not None and resolved_mentions.note:
            prompt = f"{prompt}\n\n{resolved_mentions.note}" if prompt else resolved_mentions.note
        if payload.page_context is not None:
            from app.services.agent_chat import page_context_note, requested_page_context

            page_context = requested_page_context(
                {"page_context": payload.page_context.model_dump(mode="json")}
            )
            if page_context is None:
                raise BadRequestError(message="The queued page context is no longer valid")
            page_note = page_context_note(page_context)
            prompt = f"{prompt}\n\n{page_note}" if prompt else page_note
        return prompt, seed.id, attachments

    async def prompt_for_task(self, ctx: AuthContext, task: ConversationTask) -> str:
        """Compatibility helper for callers that only need the rebuilt text."""
        prompt, _seed_id, _attachments = await self.task_input_for_worker(ctx, task)
        return prompt

    async def pending_for_conversation(
        self, *, organization_id: UUID, conversation_id: UUID
    ) -> list[AcceptedQueuedMessage]:
        """Fresh-chat arbitration reads pending receipts without cancelling them."""
        return await receipt_repo.pending_for_conversation(
            self.db, organization_id=organization_id, conversation_id=conversation_id
        )
