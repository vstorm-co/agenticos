"""Durable channel admission and safe, sender-owned additions to an active turn."""

import hashlib
import logging
from dataclasses import asdict
from uuid import UUID, uuid4

from pydantic import JsonValue, TypeAdapter
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.deps import AgentDeps
from app.agents.steering import ChannelTurnStopped
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.vault import VaultScope, seal, unseal
from app.db.models.channel_bot import ChannelBot
from app.db.session import get_db_context
from app.repositories import agent_run_repo, channel_bot_repo, conversation_repo
from app.repositories import background_job as job_repo
from app.services.background_jobs import enqueue
from app.services.channels.base import IncomingAttachment, IncomingMessage, is_run_control
from app.services.channels.dedupe import edited_delivery_is_eligible
from app.worker.jobs import (
    PROCESS_CHANNEL_CONTROL,
    PROCESS_CHANNEL_MESSAGE,
    ChannelMessage,
    ChannelMessageFile,
)

logger = logging.getLogger(__name__)
_JSON = TypeAdapter(JsonValue)
_INTERACTION = TypeAdapter(tuple[str, str])


def conversation_queue(bot_id: UUID, chat_id: str) -> str:
    return f"channel:{bot_id}:{hashlib.sha256(chat_id.encode()).hexdigest()}"


def normalize(bot: ChannelBot, incoming: IncomingMessage) -> ChannelMessage:
    metadata: dict[str, JsonValue] = {}
    for key in ("event", "guild_id"):
        value = incoming.raw.get(key)
        if isinstance(value, str):
            metadata[key] = value
    if incoming.platform == "discord":
        member = incoming.raw.get("member")
        if isinstance(member, dict) and isinstance(roles := member.get("roles"), list):
            metadata["member"] = {"roles": [role for role in roles if isinstance(role, str)]}
    if incoming.platform == "telegram":
        raw = incoming.raw.get("message") or incoming.raw.get("edited_message")
        if isinstance(raw, dict):
            telegram_message: dict[str, JsonValue] = {
                key: _JSON.validate_python(raw[key])
                for key in ("entities", "caption_entities")
                if key in raw
            }
            reply = raw.get("reply_to_message")
            if isinstance(reply, dict) and isinstance(author := reply.get("from"), dict):
                reply_id = author.get("id")
                if isinstance(reply_id, int):
                    telegram_message["reply_to_message"] = {"from": {"id": reply_id}}
            metadata["message"] = telegram_message
    interaction = (
        None
        if incoming.discord_interaction is None
        else seal(
            _INTERACTION.dump_json(incoming.discord_interaction).decode(),
            scope=VaultScope.organization(bot.organization_id),
        )
    )
    return ChannelMessage.model_validate(
        {
            "receipt_id": uuid4(),
            "organization_id": bot.organization_id,
            "bot_id": bot.id,
            "authorization_generation": bot.authorization_generation,
            "interaction_handle": None if interaction is None else interaction.ciphertext,
            "interaction_key_version": 1 if interaction is None else interaction.key_version,
            **{
                key: getattr(incoming, key)
                for key in (
                    "platform",
                    "platform_user_id",
                    "platform_chat_id",
                    "chat_type",
                    "text",
                    "platform_username",
                    "platform_display_name",
                    "message_id",
                    "broadcast_mention",
                    "addressed",
                    "platform_team_id",
                )
            },
            "attachments": [
                ChannelMessageFile(
                    **{key: value for key, value in asdict(file).items() if key != "handle"},
                    handle=sealed.ciphertext,
                    handle_key_version=sealed.key_version,
                )
                for file in incoming.attachments
                for sealed in (
                    seal(file.handle, scope=VaultScope.organization(bot.organization_id)),
                )
            ],
            "metadata": metadata,
        }
    )


def restore(message: ChannelMessage) -> IncomingMessage:
    return IncomingMessage(
        **{
            key: getattr(message, key)
            for key in (
                "platform",
                "platform_user_id",
                "platform_chat_id",
                "chat_type",
                "text",
                "platform_username",
                "platform_display_name",
                "message_id",
                "broadcast_mention",
                "addressed",
                "platform_team_id",
            )
        },
        edit_admitted=message.edit_admitted,
        discord_interaction=None
        if message.interaction_handle is None
        else _INTERACTION.validate_json(
            unseal(
                message.interaction_handle,
                scope=VaultScope.organization(message.organization_id),
                key_version=message.interaction_key_version,
            )
        ),
        bot_id=str(message.bot_id),
        raw=dict(message.metadata),
        attachments=[
            IncomingAttachment(
                **file.model_dump(exclude={"handle", "handle_key_version"}),
                handle=file.handle
                if file.handle_key_version is None
                else unseal(
                    file.handle,
                    scope=VaultScope.organization(message.organization_id),
                    key_version=file.handle_key_version,
                ),
            )
            for file in message.attachments
        ],
    )


async def queue_message(db: AsyncSession, bot: ChannelBot, incoming: IncomingMessage) -> None:
    from app.services.channels.steering import aside_question

    aside = aside_question(incoming.text) is not None
    # Edits have their own admission, but the router's observed-original receipt
    # still decides whether an edit may start a run. Persist no arbitrary raw envelope.
    native = incoming.message_id
    edited = incoming.platform == "mattermost" and incoming.raw.get("event") == "post_edited"
    if native is not None and edited:
        native += ":edit"
    key = (
        None
        if native is None
        else "channel-message:"
        + hashlib.sha256(f"{bot.id}:{incoming.platform_chat_id}:{native}".encode()).hexdigest()
    )
    if key and await job_repo.get_by_idempotency_key(
        db, organization_id=bot.organization_id, idempotency_key=key
    ):
        return
    from app.services.channels.router import ChannelMessageRouter

    router = ChannelMessageRouter()
    await router.resolve_addressing(bot, incoming)
    overheard = router._is_overheard(incoming)
    control = is_run_control(incoming.text) and not overheard
    try:
        router._check_access(incoming, bot)
        await router._check_rate_limit(
            bot,
            incoming.platform_user_id,
            surface="channel-control-ingress" if control else "channel-ingress",
        )
    except (AuthorizationError, BadRequestError) as exc:
        if not overheard:
            await router._refuse_if_named(bot, incoming, exc.message)
        logger.info("channel_admission_refused", extra={"bot_id": str(bot.id)})
        return
    if not overheard and not router._admits_unlinked(incoming, bot):
        try:
            identity = await router._resolve_identity(incoming, bot, db)
            if incoming.platform == "discord":
                await router._sync_discord_roles(bot, identity, incoming, db)
        except (AuthorizationError, BadRequestError) as exc:
            await router._refuse_if_named(bot, incoming, exc.message)
            return
        if not await router._sender_is_active_member(db, bot, identity):
            # Link/help commands and the invitation remain available without
            # retaining an unauthorised sender's payload in the shared queue.
            await router.route(incoming, db)
            return
    if len(incoming.text.encode()) > 64 * 1024 or len(incoming.attachments) > 10:
        logger.info("channel_admission_too_large", extra={"bot_id": str(bot.id)})
        return
    message = normalize(bot, incoming)
    size = len(message.model_dump_json().encode())
    if size > 128 * 1024 or not await job_repo.channel_queue_has_room(
        db,
        organization_id=bot.organization_id,
        bot_id=bot.id,
        control=control,
        size=size,
        sender=incoming.platform_user_id,
    ):
        logger.warning("channel_admission_queue_full", extra={"bot_id": str(bot.id)})
        return
    if edited:
        if not await edited_delivery_is_eligible(incoming):
            return
        message = message.model_copy(update={"edit_admitted": True})
    try:
        async with db.begin_nested():
            await enqueue(
                db,
                PROCESS_CHANNEL_CONTROL if control else PROCESS_CHANNEL_MESSAGE,
                message,
                organization_id=bot.organization_id,
                idempotency_key=key,
                concurrency_key=None
                if control or aside
                else conversation_queue(bot.id, incoming.platform_chat_id),
            )
    except IntegrityError:
        if key and await job_repo.get_by_idempotency_key(
            db, organization_id=bot.organization_id, idempotency_key=key
        ):
            return
        raise


async def admit_message(incoming: IncomingMessage) -> None:
    """Used by native deliveries; the job commits before acknowledging the delivery."""
    async with get_db_context() as db:
        bot = await channel_bot_repo.get_for_inbound(db, UUID(incoming.bot_id))
        if bot is not None and bot.is_active:
            await queue_message(db, bot, incoming)


async def collect_steering(
    receipt_id: UUID,
    incoming: IncomingMessage,
    deps: AgentDeps,
) -> list[str]:
    from app.services.channels.router import ChannelMessageRouter, _as_command

    if deps.run_id is None or deps.conversation_id is None or deps.organization_id is None:
        return []
    stopped = False
    added: list[str] = []
    async with get_db_context() as db:
        if not await job_repo.channel_message_is_running(db, receipt_id=receipt_id):
            raise ChannelTurnStopped("lease_lost")
        run = await agent_run_repo.get_run(db, deps.run_id, organization_id=deps.organization_id)
        if run is not None and run.channel_stop_requested_at is not None:
            raise ChannelTurnStopped()
        if run is None or not await ChannelMessageRouter().may_continue(db, run, incoming):
            return []
        bot = await channel_bot_repo.get_for_inbound(db, UUID(incoming.bot_id))
        if bot is None:
            return []
        pending = await job_repo.queued_channel_additions(
            db,
            organization_id=bot.organization_id,
            concurrency_key=conversation_queue(bot.id, incoming.platform_chat_id),
            sender=incoming.platform_user_id,
        )
        for job in pending:
            message = ChannelMessage.model_validate(job.payload)
            if (
                message.receipt_id == receipt_id
                or message.authorization_generation != bot.authorization_generation
            ):
                continue
            next_message = restore(message)
            if next_message.attachments or not next_message.text.strip():
                continue
            command = _as_command(next_message.text).casefold()
            if command.startswith("/") and command != "/stop":
                continue
            router = ChannelMessageRouter()
            await router.resolve_addressing(bot, next_message)
            if router._is_overheard(next_message):
                continue
            if command in {"stop", "/stop"}:
                await job_repo.finish_channel_addition(db, job_id=job.id, run_id=run.id)
                stopped = True
                break
            text = next_message.text
            if run.channel_identity_id is not None:
                await ChannelMessageRouter()._check_rate_limit(bot, str(run.channel_identity_id))
            if message.message_id:
                await conversation_repo.remember_channel_source(
                    db, conversation_id=deps.conversation_id, source_id=message.message_id
                )
            else:
                raise BadRequestError(message="A queued addition needs its native message id")
            await job_repo.finish_channel_addition(db, job_id=job.id, run_id=run.id)
            added.append(text)
    if stopped:
        raise ChannelTurnStopped()
    return added
