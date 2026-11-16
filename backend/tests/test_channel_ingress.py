"""Durable admission keeps identity and source references, not webhook secrets."""

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.agents.deps import AgentDeps
from app.agents.steering import ChannelTurnStopped
from app.services.channels import ingress
from app.services.channels.base import IncomingAttachment, IncomingMessage
from app.services.channels.router import ChannelMessageRouter
from app.worker.jobs import PROCESS_CHANNEL_MESSAGE

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def admission_limits(monkeypatch):
    monkeypatch.setattr(ChannelMessageRouter, "_check_rate_limit", AsyncMock())
    monkeypatch.setattr(ingress.job_repo, "channel_queue_has_room", AsyncMock(return_value=True))


def bot():
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        authorization_generation=uuid4(),
        is_active=True,
        access_policy={},
    )


def message(owner=None, **changes):
    owner = owner or bot()
    return IncomingMessage(
        platform="mattermost",
        bot_id=str(owner.id),
        platform_user_id="alice",
        platform_chat_id="room:thread",
        chat_type="group",
        text="Use Friday",
        message_id="post-1",
        **changes,
    )


def test_normalization_keeps_files_and_drops_tokens_and_raw_provider_envelopes():
    owner = bot()
    incoming = message(
        owner,
        raw={
            "token": "must-not-persist",
            "event": "posted",
            "guild_id": "server",
            "arbitrary": {"secret": "hidden"},
        },
        attachments=[
            IncomingAttachment(
                filename="a.pdf", mime_type="application/pdf", size=12, handle="native-file-id"
            )
        ],
    )
    queued = ingress.normalize(owner, incoming)
    assert (
        "must-not-persist" not in queued.model_dump_json()
        and "arbitrary" not in queued.model_dump_json()
    )
    restored = ingress.restore(queued)
    assert restored.attachments == incoming.attachments
    assert restored.text == incoming.text and restored.raw == {
        "event": "posted",
        "guild_id": "server",
    }
    assert not restored.dedupe_claimed
    assert ingress.conversation_queue(owner.id, "room:thread") != ingress.conversation_queue(
        owner.id, "room:other"
    )


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"message": {}},
        {"message": {"entities": [], "reply_to_message": {"from": {"id": 7}, "text": "unneeded"}}},
        {"edited_message": {"caption_entities": [], "reply_to_message": {"from": {"id": "bad"}}}},
    ],
)
def test_telegram_admission_retains_only_addressing_metadata(raw):
    incoming = replace(message(), platform="telegram", raw=raw)
    queued = ingress.normalize(bot(), incoming)
    assert "unneeded" not in queued.model_dump_json()


def test_discord_role_evidence_excludes_interaction_tokens():
    queued = ingress.normalize(
        bot(),
        replace(
            message(),
            platform="discord",
            raw={
                "guild_id": "g",
                "member": {"roles": ["r1", None], "token": "secret"},
                "token": "secret",
            },
        ),
    )
    assert queued.metadata == {"guild_id": "g", "member": {"roles": ["r1"]}}


@pytest.mark.parametrize("known", [False, True])
async def test_admission_deduplicates_durably_without_committing_the_request(monkeypatch, known):
    db = MagicMock(begin_nested=MagicMock())
    db.begin_nested.return_value.__aenter__ = AsyncMock()
    db.begin_nested.return_value.__aexit__ = AsyncMock(return_value=False)
    owner, incoming = bot(), message()
    lookup = AsyncMock(return_value=object() if known else None)
    enqueue = AsyncMock()
    monkeypatch.setattr(ingress.job_repo, "get_by_idempotency_key", lookup)
    monkeypatch.setattr(ingress, "enqueue", enqueue)
    await ingress.queue_message(db, owner, incoming)
    assert enqueue.await_count == (0 if known else 1)
    if not known:
        assert enqueue.await_args.args[1] is PROCESS_CHANNEL_MESSAGE
        assert enqueue.await_args.kwargs["idempotency_key"]
        assert enqueue.await_args.kwargs["concurrency_key"] == ingress.conversation_queue(
            owner.id, incoming.platform_chat_id
        )
        assert PROCESS_CHANNEL_MESSAGE.max_attempts == 1
    db.commit.assert_not_called()


@pytest.mark.parametrize("raced", [False, True])
async def test_a_raced_receipt_is_accepted_but_an_unrelated_constraint_error_escapes(
    monkeypatch, raced
):
    db = MagicMock()
    db.begin_nested.return_value.__aenter__ = AsyncMock()
    db.begin_nested.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        ingress.job_repo,
        "get_by_idempotency_key",
        AsyncMock(side_effect=[None, object() if raced else None]),
    )
    monkeypatch.setattr(
        ingress, "enqueue", AsyncMock(side_effect=IntegrityError("statement", {}, Exception()))
    )
    if raced:
        await ingress.queue_message(db, bot(), message())
    else:
        with pytest.raises(IntegrityError):
            await ingress.queue_message(db, bot(), message())


@pytest.mark.parametrize("active", [False, True])
async def test_stream_admission_reads_current_bot_before_queuing(monkeypatch, active):
    owner, db = bot(), MagicMock()
    owner.is_active = active

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(ingress, "get_db_context", session)
    monkeypatch.setattr(ingress.channel_bot_repo, "get_for_inbound", AsyncMock(return_value=owner))
    queue = AsyncMock()
    monkeypatch.setattr(ingress, "queue_message", queue)
    await ingress.admit_message(message(owner))
    assert queue.await_count == int(active)


@pytest.mark.parametrize("stop", [False, True])
async def test_same_sender_additions_are_recorded_before_the_queue_receipt_is_consumed(
    monkeypatch, stop
):
    from app.services.channels.router import ChannelMessageRouter

    owner, incoming, db = bot(), message(), MagicMock()
    run = SimpleNamespace(id=uuid4(), channel_identity_id=uuid4(), channel_stop_requested_at=None)
    deps = AgentDeps(run_id=run.id, conversation_id=uuid4(), organization_id=owner.organization_id)
    queued = ingress.normalize(owner, replace(incoming, text="stop" if stop else "Use Friday"))
    row = SimpleNamespace(
        id=uuid4(), payload=queued.model_dump(mode="json"), created_at=datetime.now(UTC)
    )

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(ingress, "get_db_context", session)
    monkeypatch.setattr(
        ingress.job_repo, "channel_message_is_running", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(ingress.agent_run_repo, "get_run", AsyncMock(return_value=run))
    monkeypatch.setattr(ChannelMessageRouter, "may_continue", AsyncMock(return_value=True))
    monkeypatch.setattr(ChannelMessageRouter, "_check_rate_limit", AsyncMock())
    monkeypatch.setattr(ingress.channel_bot_repo, "get_for_inbound", AsyncMock(return_value=owner))
    monkeypatch.setattr(ingress.job_repo, "queued_channel_additions", AsyncMock(return_value=[row]))
    consume, record = AsyncMock(), AsyncMock()
    monkeypatch.setattr(ingress.job_repo, "finish_channel_addition", consume)
    monkeypatch.setattr(ingress.conversation_repo, "remember_channel_source", record)
    if stop:
        with pytest.raises(ChannelTurnStopped):
            await ingress.collect_steering(uuid4(), incoming, deps)
        record.assert_not_awaited()
    else:
        assert await ingress.collect_steering(uuid4(), incoming, deps) == ["Use Friday"]
        record.assert_awaited_once()
    consume.assert_awaited_once()


@pytest.mark.parametrize(
    "scenario",
    [
        "missing_deps",
        "lost_lease",
        "stopped",
        "missing_run",
        "access_revoked",
        "missing_bot",
        "own_receipt",
        "rotated",
        "file",
        "empty",
        "overheard",
        "command",
        "no_source",
        "no_identity",
        "help",
        "telegram_unaddressed",
        "telegram_addressed",
    ],
)
async def test_queued_additions_respect_ownership_liveness_and_message_shape(monkeypatch, scenario):
    from app.core.exceptions import BadRequestError
    from app.services.channels.router import ChannelMessageRouter

    owner, incoming, db = bot(), message(), MagicMock()
    receipt_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        channel_identity_id=None if scenario == "no_identity" else uuid4(),
        channel_stop_requested_at=datetime.now(UTC) if scenario == "stopped" else None,
    )
    deps = AgentDeps(
        run_id=None if scenario == "missing_deps" else run.id,
        conversation_id=uuid4(),
        organization_id=owner.organization_id,
    )
    queued = ingress.normalize(owner, incoming)
    if scenario == "own_receipt":
        queued = queued.model_copy(update={"receipt_id": receipt_id})
    if scenario == "rotated":
        queued = queued.model_copy(update={"authorization_generation": uuid4()})
    if scenario == "file":
        queued = queued.model_copy(
            update={
                "attachments": [
                    ingress.ChannelMessageFile(
                        filename="a.txt", mime_type="text/plain", size=1, handle="a"
                    )
                ]
            }
        )
    if scenario == "empty":
        queued = queued.model_copy(update={"text": " "})
    if scenario == "overheard":
        queued = queued.model_copy(update={"addressed": False})
    if scenario == "command":
        queued = queued.model_copy(update={"text": "/new"})
    if scenario == "help":
        queued = queued.model_copy(update={"text": "help"})
    if scenario in {"telegram_unaddressed", "telegram_addressed"}:
        from app.services.channels import router

        queued = queued.model_copy(update={"platform": "telegram", "addressed": None})
        adapter = SimpleNamespace(
            resolve_addressing=AsyncMock(return_value=scenario == "telegram_addressed")
        )
        monkeypatch.setattr(router, "get_adapter", lambda platform: adapter)
        monkeypatch.setattr(router, "unseal_bot_token", lambda bot: "test-token")
    if scenario == "no_source":
        queued = queued.model_copy(update={"message_id": None})

    @asynccontextmanager
    async def context():
        yield db

    monkeypatch.setattr(ingress, "get_db_context", context)
    monkeypatch.setattr(
        ingress.job_repo,
        "channel_message_is_running",
        AsyncMock(return_value=scenario != "lost_lease"),
    )
    monkeypatch.setattr(
        ingress.agent_run_repo,
        "get_run",
        AsyncMock(return_value=None if scenario == "missing_run" else run),
    )
    monkeypatch.setattr(
        ChannelMessageRouter, "may_continue", AsyncMock(return_value=scenario != "access_revoked")
    )
    monkeypatch.setattr(ChannelMessageRouter, "_check_rate_limit", AsyncMock())
    monkeypatch.setattr(
        ingress.channel_bot_repo,
        "get_for_inbound",
        AsyncMock(return_value=None if scenario == "missing_bot" else owner),
    )
    monkeypatch.setattr(
        ingress.job_repo,
        "queued_channel_additions",
        AsyncMock(
            return_value=[SimpleNamespace(id=uuid4(), payload=queued.model_dump(mode="json"))]
        ),
    )
    consume = AsyncMock()
    monkeypatch.setattr(ingress.job_repo, "finish_channel_addition", consume)
    monkeypatch.setattr(ingress.conversation_repo, "remember_channel_source", AsyncMock())
    if scenario in {"lost_lease", "stopped", "no_source"}:
        with pytest.raises(BadRequestError if scenario == "no_source" else ChannelTurnStopped):
            await ingress.collect_steering(receipt_id, incoming, deps)
    else:
        assert await ingress.collect_steering(receipt_id, incoming, deps) == (
            [incoming.text] if scenario in {"no_identity", "telegram_addressed"} else []
        )
    assert consume.await_count == int(scenario in {"no_identity", "telegram_addressed"})


async def test_controls_have_their_own_lane_and_edits_their_own_receipt(monkeypatch):
    from app.worker.jobs import PROCESS_CHANNEL_CONTROL

    db = MagicMock()
    db.begin_nested.return_value.__aenter__ = AsyncMock()
    db.begin_nested.return_value.__aexit__ = AsyncMock(return_value=False)
    owner = bot()
    monkeypatch.setattr(ingress.job_repo, "get_by_idempotency_key", AsyncMock(return_value=None))
    enqueue = AsyncMock()
    monkeypatch.setattr(ingress, "enqueue", enqueue)
    await ingress.queue_message(db, owner, replace(message(owner), text="stop"))
    assert enqueue.await_args.args[1] is PROCESS_CHANNEL_CONTROL
    assert enqueue.await_args.kwargs["concurrency_key"] is None
    monkeypatch.setattr(ingress, "edited_delivery_is_eligible", AsyncMock(return_value=True))
    await ingress.queue_message(db, owner, message(owner, raw={"event": "post_edited"}))
    edit_key = enqueue.await_args.kwargs["idempotency_key"]
    await ingress.queue_message(db, owner, message(owner))
    assert enqueue.await_args.kwargs["idempotency_key"] != edit_key


@pytest.mark.parametrize("eligible", [False, True])
async def test_a_first_edit_needs_a_current_ignored_original_at_admission(monkeypatch, eligible):
    db, owner = MagicMock(), bot()
    db.begin_nested.return_value.__aenter__ = AsyncMock()
    db.begin_nested.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(ingress.job_repo, "get_by_idempotency_key", AsyncMock(return_value=None))
    monkeypatch.setattr(ingress, "edited_delivery_is_eligible", AsyncMock(return_value=eligible))
    enqueue = AsyncMock()
    monkeypatch.setattr(ingress, "enqueue", enqueue)
    await ingress.queue_message(db, owner, message(owner, raw={"event": "post_edited"}))
    assert enqueue.await_count == int(eligible)
    if eligible:
        assert enqueue.await_args.args[2].edit_admitted


@pytest.mark.parametrize(
    "raw",
    [
        {"message": {"reply_to_message": {"from": {"id": 42}}}},
        {"message": {"reply_to_message": {"from": {"id": 42}}, "entities": []}},
        {"message": {"reply_to_message": {"from": {"id": "bad"}}}},
        {"member": {}},
        {"member": {"roles": "invalid"}},
    ],
)
def test_optional_metadata_is_narrowed(raw):
    incoming = replace(message(), platform="discord" if "member" in raw else "telegram", raw=raw)
    normalized = ingress.normalize(bot(), incoming)
    assert (
        "reply_to_message" not in normalized.model_dump_json()
        or "42" in normalized.model_dump_json()
    )


def test_a_telegram_reply_without_a_native_author_id_does_not_invent_one():
    queued = ingress.normalize(
        bot(),
        replace(
            message(), platform="telegram", raw={"message": {"reply_to_message": {"from": None}}}
        ),
    )
    assert queued.metadata == {"message": {}}


async def test_workers_share_channel_limits_and_caches_for_their_full_lifetime(monkeypatch):
    from app.services import rate_limit
    from app.services.channels import connection_state, dedupe, email_state, membership, teams

    client = MagicMock(connect=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr(email_state, "RedisClient", lambda: client)
    stores = [rate_limit, connection_state, dedupe, membership, teams]
    with_clients = [MagicMock(wraps=store.configure) for store in stores]
    for store, configure in zip(stores, with_clients, strict=True):
        monkeypatch.setattr(store, "configure", configure)
    async with email_state.in_worker():
        for configure in with_clients:
            configure.assert_called_once_with(client)
    for configure in with_clients:
        assert configure.call_args.args == (None,)
    client.close.assert_awaited_once()


async def test_webhook_admission_uses_the_request_transaction(monkeypatch):
    from app.services.channel_bot import ChannelBotService

    owner, db = bot(), MagicMock()
    incoming = message(owner)
    queue = AsyncMock()
    monkeypatch.setattr(ingress, "queue_message", queue)
    await ChannelBotService(db).queue_message(owner, incoming)
    queue.assert_awaited_once_with(db, owner, incoming)
    db.commit.assert_not_called()


@pytest.mark.parametrize("platform", ["discord", "teams"])
def test_preauthenticated_attachment_handles_are_sealed_for_the_organization(platform):
    from app.core.exceptions import BadRequestError

    owner = bot()
    url = "https://cdn.example.test/file?signature=credential-do-not-store"
    incoming = replace(
        message(owner),
        platform=platform,
        attachments=[
            IncomingAttachment(filename="a.pdf", mime_type="application/pdf", size=12, handle=url)
        ],
    )
    payload = ingress.normalize(owner, incoming)
    assert "credential-do-not-store" not in payload.model_dump_json()
    assert url not in repr(payload)
    assert ingress.restore(payload).attachments[0].handle == url
    with pytest.raises(BadRequestError):
        ingress.restore(payload.model_copy(update={"organization_id": uuid4()}))


@pytest.mark.parametrize("reason", ["access", "rate", "capacity", "size", "files"])
async def test_admission_refuses_before_enqueue(monkeypatch, reason):
    from app.core.exceptions import AuthorizationError, BadRequestError

    owner, incoming = bot(), message()
    monkeypatch.setattr(ingress.job_repo, "get_by_idempotency_key", AsyncMock(return_value=None))
    if reason == "access":
        monkeypatch.setattr(
            ChannelMessageRouter,
            "_check_access",
            MagicMock(side_effect=AuthorizationError(message="Denied")),
        )
    elif reason == "rate":
        monkeypatch.setattr(
            ChannelMessageRouter,
            "_check_rate_limit",
            AsyncMock(side_effect=BadRequestError(message="Slow down")),
        )
    elif reason == "capacity":
        monkeypatch.setattr(
            ingress.job_repo, "channel_queue_has_room", AsyncMock(return_value=False)
        )
    elif reason == "size":
        incoming.text = "x" * (64 * 1024 + 1)
    else:
        incoming.attachments = [
            IncomingAttachment(filename="a", mime_type="text/plain", size=1, handle="id")
        ] * 11
    enqueue = AsyncMock()
    refusal = AsyncMock()
    monkeypatch.setattr(ChannelMessageRouter, "_refuse_if_named", refusal)
    monkeypatch.setattr(ingress, "enqueue", enqueue)
    await ingress.queue_message(MagicMock(), owner, incoming)
    enqueue.assert_not_awaited()
    assert refusal.await_count == int(reason in {"access", "rate"})


async def test_side_question_is_queued_without_the_active_threads_concurrency_key(monkeypatch):
    db = MagicMock()
    db.begin_nested.return_value.__aenter__ = AsyncMock()
    db.begin_nested.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(ingress.job_repo, "get_by_idempotency_key", AsyncMock(return_value=None))
    enqueue = AsyncMock()
    monkeypatch.setattr(ingress, "enqueue", enqueue)
    await ingress.queue_message(db, bot(), replace(message(), text="/btw status of the draft?"))
    assert enqueue.await_args.args[1] is PROCESS_CHANNEL_MESSAGE
    assert enqueue.await_args.kwargs["concurrency_key"] is None


def test_deferred_discord_reply_handle_survives_only_as_vault_ciphertext():
    incoming = replace(
        message(), platform="discord", discord_interaction=("application", "private-token")
    )
    queued = ingress.normalize(bot(), incoming)
    assert "private-token" not in queued.model_dump_json()
    assert ingress.restore(queued).discord_interaction == incoming.discord_interaction


@pytest.mark.parametrize("linked", [False, True])
async def test_unlinked_senders_do_not_take_shared_retained_capacity(monkeypatch, linked):
    owner, incoming = bot(), message()
    owner.access_policy = {"mode": "jwt_linked"}
    monkeypatch.setattr(ingress.job_repo, "get_by_idempotency_key", AsyncMock(return_value=None))
    monkeypatch.setattr(
        ChannelMessageRouter,
        "_resolve_identity",
        AsyncMock(return_value=SimpleNamespace(user_id=uuid4() if linked else None)),
    )
    monkeypatch.setattr(
        ChannelMessageRouter, "_sender_is_active_member", AsyncMock(return_value=linked)
    )
    route = AsyncMock()
    monkeypatch.setattr(ChannelMessageRouter, "route", route)
    enqueue = AsyncMock()
    monkeypatch.setattr(ingress, "enqueue", enqueue)
    db = MagicMock()
    await ingress.queue_message(db, owner, incoming)
    assert enqueue.await_count == int(linked)
    assert route.await_count == int(not linked)


async def test_telegram_overheard_stop_does_not_take_the_control_lane(monkeypatch):
    owner = bot()
    incoming = replace(message(owner), platform="telegram", addressed=None, text="stop")

    async def resolve(self, bot, incoming):
        incoming.addressed = False

    monkeypatch.setattr(ChannelMessageRouter, "resolve_addressing", resolve)
    monkeypatch.setattr(ingress.job_repo, "get_by_idempotency_key", AsyncMock(return_value=None))
    enqueue = AsyncMock()
    monkeypatch.setattr(ingress, "enqueue", enqueue)
    await ingress.queue_message(MagicMock(), owner, incoming)
    assert enqueue.await_args.args[1] == PROCESS_CHANNEL_MESSAGE
    assert not ingress.job_repo.channel_queue_has_room.await_args.kwargs["control"]


@pytest.mark.parametrize("failure", [None, "identity", "roles", "overheard"])
async def test_admission_preserves_link_refusals_and_discord_role_checks(monkeypatch, failure):
    from app.core.exceptions import AuthorizationError, BadRequestError

    owner = bot()
    owner.access_policy = {"mode": "jwt_linked", "discord_guild_ids": ["123456789"]}
    incoming = replace(
        message(owner),
        platform="discord",
        addressed=failure != "overheard",
        raw={"guild_id": "123456789"},
    )
    monkeypatch.setattr(ingress.job_repo, "get_by_idempotency_key", AsyncMock(return_value=None))
    monkeypatch.setattr(
        ChannelMessageRouter,
        "_resolve_identity",
        AsyncMock(
            return_value=SimpleNamespace(user_id=uuid4()),
            side_effect=AuthorizationError(message="Link required")
            if failure == "identity"
            else None,
        ),
    )
    roles = AsyncMock(
        side_effect=BadRequestError(message="Roles unavailable") if failure == "roles" else None
    )
    monkeypatch.setattr(ChannelMessageRouter, "_sync_discord_roles", roles)
    monkeypatch.setattr(
        ChannelMessageRouter, "_sender_is_active_member", AsyncMock(return_value=True)
    )
    if failure == "overheard":
        monkeypatch.setattr(
            ChannelMessageRouter,
            "_check_access",
            MagicMock(side_effect=AuthorizationError(message="Denied")),
        )
    refuse = AsyncMock()
    monkeypatch.setattr(ChannelMessageRouter, "_refuse_if_named", refuse)
    enqueue = AsyncMock()
    monkeypatch.setattr(ingress, "enqueue", enqueue)
    await ingress.queue_message(MagicMock(), owner, incoming)
    assert enqueue.await_count == int(failure is None)
    assert refuse.await_count == int(failure in {"identity", "roles"})
    assert roles.await_count == int(failure in {None, "roles"})
