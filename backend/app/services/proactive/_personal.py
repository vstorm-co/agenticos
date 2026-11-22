"""Membership-private, incremental personal assistance over current authorized sources."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, JsonValue, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.locks import LockScope, hold_subject, hold_subject_shared
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.conversation import Conversation, Message
from app.db.models.suggestion import SuggestionKind
from app.repositories import (
    audit_log_repo,
    conversation_repo,
    member_repo,
    organization_repo,
    suggestion_repo,
    user_repo,
)
from app.repositories import personal_context as context_repo
from app.repositories.conversation import PersonRequest
from app.schemas.personal_context import ContextDigest, ContextTurn, ConversationContext
from app.services.conversation import ConversationService
from app.services.memory.extraction import answered_question_turns
from app.services.notifications import NotificationService
from app.services.proactive._context_pipeline import (
    EXTRACTOR_VERSION,
    chunks,
    extract_context,
    fingerprint,
    propose_context,
)
from app.services.proactive._context_snapshot import current_packet
from app.services.proactive._nightly import NightlyLook, _key
from app.services.proactive._thinker import ProactiveThinker

_JSON = TypeAdapter(dict[str, JsonValue])
MAX_NEW_CHUNKS = 8


def source_speaker(
    message: Message,
    run: AgentRun | None,
    conversation: Conversation,
    *,
    channel_user_id: UUID | None = None,
) -> str:
    """Use attributed turns or an admitted web caller; never guess a project author."""
    if message.role != "user":
        return "assistant"
    if message.author_user_id is not None:
        return str(message.author_user_id)
    if message.channel_identity_id is not None:
        return str(channel_user_id) if channel_user_id is not None else "unknown"
    if run is not None and run.surface == RunSurface.WEB.value and run.user_id is not None:
        return str(run.user_id)
    if run is None and conversation.project_id is None and conversation.user_id is not None:
        return str(conversation.user_id)
    return "unknown"


class PersonalModel:
    def __init__(self, db: AsyncSession, ctx: AuthContext, now: datetime, snapshot: str) -> None:
        self.thinker = ProactiveThinker(db)
        self.ctx, self.now, self.snapshot = ctx, now, snapshot

    async def read[Result: BaseModel](
        self, *, stage: str, instructions: str, material: object, output_type: type[Result]
    ) -> Result | None:
        import json

        return await self.thinker.think(
            self.ctx,
            feature="nightly",
            output_type=output_type,
            instructions=instructions,
            prompt=json.dumps(
                {"stage": stage, "context": material}, ensure_ascii=False, default=str
            ),
            started_at=self.now,
            erased_since=self.now,
            erased_snapshot=self.snapshot,
        )


class PersonalLook(NightlyLook):
    """The old contract remains replayable; production uses this source-aware path."""

    async def _conversations(self, ctx: AuthContext) -> list[Conversation]:
        service = ConversationService(self.db)
        rows: list[Conversation] = []
        skip = 0
        while True:
            page, total = await service.list_conversations(
                ctx.user_id,
                organization_id=ctx.organization_id,
                reader=ctx,
                skip=skip,
                limit=100,
                include_archived=True,
                sort_dir="desc",
                for_model=True,
            )
            rows.extend(page)
            if skip + len(page) >= total or not page:
                return rows
            skip += len(page)

    async def _turns(
        self, ctx: AuthContext, conversation: Conversation, since: datetime
    ) -> tuple[list[ContextTurn], list[dict[str, JsonValue]]]:
        turns: list[ContextTurn] = []
        receipts: list[dict[str, JsonValue]] = []
        after = -1
        while True:
            page = await context_repo.transcript_page(
                self.db,
                organization_id=ctx.organization_id,
                conversation_id=conversation.id,
                after=after,
                since=since,
            )
            if not page:
                break
            admissible = await self._past_the_input_edge(
                ctx.organization_id,
                [PersonRequest(message, run) for message, run in page if message.role == "user"],
            )
            admitted_runs = {row.message.run_id for row in admissible}
            authors = await conversation_repo.authors_of(
                self.db,
                [
                    message.channel_identity_id
                    for message, _ in page
                    if message.channel_identity_id is not None
                ],
            )
            for message, run in page:
                if message.role == "user" and message.run_id not in admitted_runs:
                    continue
                # Outputs from a model-less failed run are not input-edge evidence.
                if (
                    run is not None
                    and run.status != RunStatus.COMPLETED.value
                    and run.input_tokens <= 0
                ):
                    continue
                author = (
                    authors.get(message.channel_identity_id)
                    if message.channel_identity_id
                    else None
                )
                if message.created_at >= since:
                    turns.append(
                        ContextTurn(
                            id=str(message.id),
                            thread_id=str(conversation.id),
                            occurred_at=message.created_at,
                            speaker_id=source_speaker(
                                message,
                                run,
                                conversation,
                                channel_user_id=author.user_id
                                if author is not None and author.is_active
                                else None,
                            ),
                            role="user" if message.role == "user" else "assistant",
                            text=message.content,
                        )
                    )
                # Raw external results stay out. Native submitted values can be
                # attributed only to a run actually admitted for this person.
                if run is not None and run.user_id == ctx.user_id:
                    for call in message.tool_calls:
                        if (call.completed_at or call.started_at) < since:
                            continue
                        human = answered_question_turns([call])
                        if human:
                            text = "\n".join(value for role, value in human if role == "user")
                            turns.append(
                                ContextTurn(
                                    id=f"answer:{call.id}",
                                    thread_id=str(conversation.id),
                                    occurred_at=call.completed_at or call.started_at,
                                    speaker_id=str(ctx.user_id),
                                    role="user",
                                    text=text,
                                )
                            )
                            receipts.append(
                                _JSON.validate_python(
                                    {
                                        "id": str(call.id),
                                        "thread_id": str(conversation.id),
                                        "action": "ask_user_question",
                                        "status": "completed",
                                        "submitted_at": (
                                            call.completed_at or call.started_at
                                        ).isoformat(),
                                        "answered_by_user_id": str(ctx.user_id),
                                        "questions": call.args.get("questions"),
                                        "submitted_answers": call.result,
                                    }
                                )
                            )
                        elif call.tool_id is not None and call.presentation_kind != "generic":
                            receipts.append(
                                {
                                    "id": str(call.id),
                                    "thread_id": str(conversation.id),
                                    "action": call.tool_id,
                                    "status": call.status,
                                }
                            )
            after = page[-1][0].ordinal
            if len(page) < 100:
                break
        turns.sort(key=lambda turn: turn.occurred_at)
        return turns, receipts

    async def look(
        self, organization_id: UUID, user_id: UUID, *, refresh_open: bool = False
    ) -> int:
        user = await user_repo.get_by_id(self.db, user_id)
        member = await member_repo.get_active(
            self.db, organization_id=organization_id, user_id=user_id
        )
        if user is None or member is None or not user.is_active or user.proactive_opt_out:
            return 0
        ctx = AuthContext(organization_id=organization_id, user_id=user_id, role=member.role)
        if await self.thinker.allowance(ctx, "nightly") is None:
            return 0
        starter = await self.thinker.starter_agent(organization_id)
        if starter is None:
            return 0
        now = datetime.now(UTC)
        snapshot = await audit_log_repo.current_snapshot(self.db)
        erased = await audit_log_repo.latest_memory_erasure(
            self.db, organization_id=organization_id, user_id=user_id
        )
        since = erased or datetime.min.replace(tzinfo=UTC)
        packet = await current_packet(self.db, ctx, user, now=now, starter_id=starter.id)
        replacing = {
            row.id
            for row in await suggestion_repo.list_open(
                self.db, organization_id=organization_id, user_id=user_id
            )
            if row.watch_id is None
            and row.outcome_id is None
            and (
                row.payload.get("personal_context") is True
                or (refresh_open and row.kind != SuggestionKind.FINDING.value)
            )
        }

        reader = PersonalModel(self.db, ctx, now, snapshot)
        cached = await context_repo.load(self.db, organization_id=organization_id, user_id=user_id)
        conversations = await self._conversations(ctx)
        keys = {f"conversation:{row.id}" for row in conversations}
        await context_repo.retain(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            keys=keys
            | {key for key in cached if key.startswith("removed-routine:")}
            | {"reading"}
            | {
                key
                for key in cached
                if key.startswith("part:")
                and key.split(":")[1] in {str(row.id) for row in conversations}
            },
        )
        digests: list[ContextDigest] = []
        messages: list[ContextTurn] = []
        receipts: list[dict[str, JsonValue]] = []
        revisions: dict[str, str] = {}
        used = 0
        for conversation in conversations:
            key = f"conversation:{conversation.id}"
            raw_revision = await context_repo.conversation_revision(
                self.db, organization_id=organization_id, conversation_id=conversation.id
            )
            revision = fingerprint(
                [
                    EXTRACTOR_VERSION,
                    erased,
                    conversation.user_id,
                    conversation.project_id,
                    raw_revision,
                ]
            )
            revisions[key] = revision
            stored = cached.get(key, {})
            if stored.get("revision") == revision:
                index = ConversationContext.model_validate(stored)
                digests.extend(index.digests)
                messages.extend(index.messages)
                receipts.extend(index.receipts)
                continue
            turns, answers = await self._turns(ctx, conversation, since)
            parts = chunks(turns)
            fresh: list[ContextDigest] = []
            # Per-segment progress is durable even when a conversation is large.
            for index, part in enumerate(parts):
                part_key = f"part:{conversation.id}:{fingerprint([revision, index])[:32]}"
                existing = cached.get(part_key)
                keys.add(part_key)
                if existing is not None:
                    digest = ContextDigest.model_validate(existing)
                else:
                    if used >= MAX_NEW_CHUNKS:
                        await self._continue(ctx)
                        return 0
                    digest = await extract_context(
                        reader,
                        packet.model_copy(
                            update={
                                "messages": part,
                                "tool_receipts": [
                                    receipt
                                    for receipt in answers
                                    if f"answer:{receipt['id']}" in {turn.id for turn in part}
                                ],
                            }
                        ),
                    )
                    if digest is None:
                        return 0
                    used += 1
                    if not await self._checkpoint(
                        ctx,
                        starter.id,
                        now,
                        snapshot,
                        conversation.id,
                        raw_revision,
                        key=part_key,
                        payload=digest.model_dump(mode="json"),
                    ):
                        return 0
                fresh.append(digest)
            # Retain only quoted original snippets, not a second whole transcript.
            refs = {
                ref.source_id
                for digest in fresh
                for topic in digest.topics
                for ref in topic.evidence
            }
            quotes = {
                source: list(
                    dict.fromkeys(
                        ref.quote
                        for digest in fresh
                        for topic in digest.topics
                        for ref in topic.evidence
                        if ref.source_id == source
                    )
                )
                for source in refs
            }
            kept = [
                turn.model_copy(
                    update={
                        "text": "\n".join(quotes[f"message:{turn.id}"]),
                        "source_fragments": quotes[f"message:{turn.id}"],
                    }
                )
                for turn in turns
                if f"message:{turn.id}" in refs
            ]
            payload: dict[str, object] = {
                "revision": revision,
                "digests": [digest.model_dump(mode="json") for digest in fresh],
                "messages": [turn.model_dump(mode="json") for turn in kept],
                "receipts": answers,
            }
            if not await self._checkpoint(
                ctx,
                starter.id,
                now,
                snapshot,
                conversation.id,
                raw_revision,
                key=key,
                payload=payload,
            ):
                return 0
            digests.extend(fresh)
            messages.extend(kept)
            receipts.extend(answers)
        packet = packet.model_copy(update={"messages": messages, "tool_receipts": receipts})
        state_hash = fingerprint(
            [
                revisions,
                packet.model_dump(
                    mode="json",
                    exclude={"as_of", "messages", "tool_receipts", "changed_source_ids"},
                ),
            ]
        )
        if not refresh_open and cached.get("reading", {}).get("fingerprint") == state_hash:
            return 0
        reading = await propose_context(reader, packet, digests)
        if reading is None:
            return 0
        await hold_subject(self.db, LockScope.PERSONAL_DATA_PER_USER, user_id)
        await hold_subject_shared(self.db, LockScope.MEMORY_PER_AGENT, starter.id)
        if await audit_log_repo.memory_erased_since(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            agent_id=starter.id,
            since=now,
            snapshot=snapshot,
        ):
            return 0
        from app.db.session import get_worker_db_context

        await context_repo.lock_delivery_sources(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            conversation_ids=[row.id for row in conversations],
        )
        async with get_worker_db_context() as fresh_db:
            fresh_member = await member_repo.get_active(
                fresh_db, organization_id=organization_id, user_id=user_id
            )
            fresh_user = await user_repo.get_by_id(fresh_db, user_id)
            fresh_org = await organization_repo.get_by_id(fresh_db, organization_id)
            if (
                fresh_org is None
                or not fresh_org.proactive_enabled
                or fresh_org.proactive_model_profile_id is None
                or fresh_member is None
                or fresh_user is None
                or not fresh_user.is_active
                or fresh_user.proactive_opt_out
                or fresh_member.role != member.role
            ):
                return 0
            fresh_ctx = AuthContext(
                organization_id=organization_id, user_id=user_id, role=fresh_member.role
            )
            service = ConversationService(fresh_db)
            ids = {row.id for row in conversations}
            if await service.visible_conversation_ids(fresh_ctx, ids) != ids:
                return 0
            current = await current_packet(
                fresh_db, fresh_ctx, fresh_user, now=now, starter_id=starter.id
            )
        if (current.current_state, current.memory, current.profile, current.available_features) != (
            packet.current_state,
            packet.memory,
            packet.profile,
            packet.available_features,
        ):
            await self._continue(ctx)
            return 0
        for row in conversations:
            current_revision = fingerprint(
                [
                    EXTRACTOR_VERSION,
                    erased,
                    row.user_id,
                    row.project_id,
                    await context_repo.conversation_revision(
                        self.db, organization_id=organization_id, conversation_id=row.id
                    ),
                ]
            )
            if current_revision != revisions[f"conversation:{row.id}"]:
                await self._continue(ctx)
                return 0
        if replacing and not await suggestion_repo.remove_open_generated(
            self.db, organization_id=organization_id, user_id=user_id, expected_ids=replacing
        ):
            return 0
        count = 0
        for card in reading.opportunities:
            created = await suggestion_repo.propose(
                self.db,
                organization_id=organization_id,
                user_id=user_id,
                kind=SuggestionKind.PERSONAL.value,
                title=card.title,
                detail=card.detail,
                payload={
                    "personal_context": True,
                    "category": card.kind,
                    "intent": card.identity,
                    "chat_prompt": card.chat_prompt,
                    "resource_ids": card.resource_ids,
                    "evidence": [ref.model_dump(mode="json") for ref in card.evidence],
                },
                dedupe_key=_key("personal", card.identity),
            )
            count += int(created is not None)
        if reading.starters:
            await member_repo.set_personal_starters(
                self.db, member, starters=[text[:80] for text in reading.starters], at=now
            )
        await context_repo.save(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            key="reading",
            payload={"fingerprint": state_hash},
        )
        await context_repo.retain(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            keys=keys | {"reading"} | {key for key in cached if key.startswith("removed-routine:")},
        )
        if count:
            await NotificationService(self.db).suggestions_ready(
                organization_id=organization_id, user_id=user_id, count=count, now=now
            )
        return count

    async def _checkpoint(
        self,
        ctx: AuthContext,
        starter_id: UUID,
        read_at: datetime,
        snapshot: str,
        conversation_id: UUID,
        revision: str,
        *,
        key: str,
        payload: dict[str, object],
    ) -> bool:
        """Commit bounded progress with its own privacy fence before the next model call.

        A partial backfill must survive a later budget refusal, but must never
        resurrect data erased while the model read it. No outer cache write is
        allowed before the final delivery fence.
        """
        from app.db.session import get_worker_db_context

        assert ctx.user_id is not None
        async with get_worker_db_context() as writer:
            await hold_subject(writer, LockScope.PERSONAL_DATA_PER_USER, ctx.user_id)
            await hold_subject_shared(writer, LockScope.MEMORY_PER_AGENT, starter_id)
            await context_repo.lock_delivery_sources(
                writer,
                organization_id=ctx.organization_id,
                user_id=ctx.user_id,
                conversation_ids=[conversation_id],
            )
            member = await member_repo.get_active(
                writer, organization_id=ctx.organization_id, user_id=ctx.user_id
            )
            person = await user_repo.get_by_id(writer, ctx.user_id)
            organization = await organization_repo.get_by_id(writer, ctx.organization_id)
            if (
                member is None
                or member.role != ctx.role
                or person is None
                or not person.is_active
                or person.proactive_opt_out
                or organization is None
                or not organization.proactive_enabled
                or organization.proactive_model_profile_id is None
            ):
                return False
            if await audit_log_repo.memory_erased_since(
                writer,
                organization_id=ctx.organization_id,
                user_id=ctx.user_id,
                agent_id=starter_id,
                since=read_at,
                snapshot=snapshot,
            ):
                return False
            ids = await ConversationService(writer).visible_conversation_ids(ctx, {conversation_id})
            if conversation_id not in ids or revision != await context_repo.conversation_revision(
                writer, organization_id=ctx.organization_id, conversation_id=conversation_id
            ):
                return False
            await context_repo.save(
                writer,
                organization_id=ctx.organization_id,
                user_id=ctx.user_id,
                key=key,
                payload=payload,
            )
        return True

    async def _continue(self, ctx: AuthContext) -> None:
        from app.services.proactive.facade import ProactiveService

        assert ctx.user_id is not None
        await ProactiveService(self.db).queue_context_change(ctx.organization_id, ctx.user_id)
