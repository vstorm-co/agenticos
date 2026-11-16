"""Final delivery is persisted with the run and claimed before a network effect."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError
from app.services.agent_runner import RunSegment
from app.services.channels import reply_receipts as module
from app.services.channels.base import IncomingMessage
from app.worker.jobs import DELIVER_CHANNEL_REPLY, ChannelHandback
from app.worker.tasks import channel_tasks

pytestmark = pytest.mark.anyio


def receipt():
    bot = SimpleNamespace(id=uuid4(), organization_id=uuid4())
    incoming = IncomingMessage(
        platform="mattermost",
        bot_id=str(bot.id),
        platform_user_id="alice",
        platform_chat_id="room:thread",
        chat_type="group",
        text="hi",
        message_id="source",
    )
    return module.RequiredReply(
        MagicMock(), bot, incoming, file_refusals=["An attachment could not be read."]
    )


async def test_final_snapshot_and_file_limitations_share_the_terminal_transaction(monkeypatch):
    monkeypatch.setattr(module.conversation_repo, "bind_channel_source", AsyncMock())
    reply = receipt()
    enqueue = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(module, "enqueue", enqueue)
    run = SimpleNamespace(id=uuid4(), status="completed")
    segment = RunSegment(output="Answer", run=run, tool_calls=[], settled={})
    assert module.segment_sink() is None
    with module.required_reply(reply):
        assert module.segment_sink() is not None
        await reply.persist(segment)
    assert module.segment_sink() is None
    call = enqueue.await_args
    assert call.args[:2] == (reply.db, DELIVER_CHANNEL_REPLY)
    assert call.args[2].output == "Answer\n\nAn attachment could not be read."
    assert call.args[2].message_id == "source"
    assert call.args[2].initial_reply_id is not None
    reply.db.commit.assert_not_called()


async def test_cancelled_snapshot_explains_the_stop(monkeypatch):
    monkeypatch.setattr(module.conversation_repo, "bind_channel_source", AsyncMock())
    reply = receipt()
    enqueue = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(module, "enqueue", enqueue)
    await reply.persist(
        RunSegment(
            output="",
            run=SimpleNamespace(id=uuid4(), status="cancelled"),
            tool_calls=[],
            settled={},
        )
    )
    assert "stopped" in enqueue.await_args.args[2].output.lower()


@pytest.mark.parametrize("persisted", [False, True])
async def test_submission_claim_uses_its_own_committing_context(monkeypatch, persisted):
    reply, db = receipt(), MagicMock()
    if persisted:
        reply.job_id = uuid4()

    @asynccontextmanager
    async def context():
        yield db

    claim = AsyncMock(return_value=False)
    settle = AsyncMock()
    monkeypatch.setattr(module, "get_db_context", context)
    monkeypatch.setattr(module.job_repo, "claim_channel_reply", claim)
    monkeypatch.setattr(module.job_repo, "settle_channel_reply", settle)
    assert await reply.begin_submission() is (not persisted)
    await reply.settle(delivered=True)
    assert claim.await_count == settle.await_count == int(persisted)


@pytest.mark.parametrize("state", ["missing", "claimed", "delivered", "refused", "failed"])
async def test_recovery_only_delivers_a_saved_unattempted_answer(monkeypatch, state):
    job = ChannelHandback(
        initial_reply_id=uuid4(),
        organization_id=uuid4(),
        run_id=uuid4(),
        bot_id=uuid4(),
        platform_chat_id="room:thread",
        private_chat=False,
        output="Saved answer",
    )

    @asynccontextmanager
    async def context():
        yield MagicMock()

    monkeypatch.setattr(channel_tasks, "get_db_context", context)
    monkeypatch.setattr(
        module.job_repo,
        "get_channel_reply",
        AsyncMock(return_value=None if state == "missing" else SimpleNamespace(id=uuid4())),
    )
    monkeypatch.setattr(
        module.job_repo, "claim_channel_reply", AsyncMock(return_value=state != "claimed")
    )
    settle = AsyncMock()
    deliver = AsyncMock(
        return_value=state != "refused",
        side_effect=RuntimeError("transport") if state == "failed" else None,
    )
    monkeypatch.setattr(module.job_repo, "settle_channel_reply", settle)
    monkeypatch.setattr(channel_tasks, "deliver_handback", deliver)
    if state in {"claimed", "failed"}:
        with pytest.raises(BadRequestError if state == "claimed" else RuntimeError):
            await channel_tasks.deliver_initial_reply(job)
    else:
        await channel_tasks.deliver_initial_reply(job)
    if state in {"missing", "claimed"}:
        deliver.assert_not_awaited()
        settle.assert_not_awaited()
    else:
        deliver.assert_awaited_once_with(job)
        assert settle.await_args.kwargs["delivered"] is (state == "delivered")


async def test_native_reply_id_is_remembered_without_adding_another_history_message(monkeypatch):
    reply = receipt()
    reply.run_id = uuid4()
    bind = AsyncMock()
    monkeypatch.setattr(module.conversation_repo, "bind_channel_source", bind)
    await module.remember_delivered_post("ignored")
    with module.required_reply(reply):
        await module.remember_delivered_post(None)
        await module.remember_delivered_post("native-reply")
    bind.assert_awaited_once_with(
        reply.db, run_id=reply.run_id, role="assistant", source_id="native-reply"
    )


@pytest.mark.parametrize(
    "outcome", ["completed", "already_claimed", "refused", "crashed", "delivery_failed"]
)
async def test_the_live_turn_and_recovery_never_both_submit_the_terminal_response(
    monkeypatch, outcome
):
    from app.services.channels import router as routing
    from app.services.channels.mentions import AnsweredTurn
    from app.services.channels.steering import queued_turn

    reply = receipt()
    run = SimpleNamespace(id=uuid4(), status="completed")

    @asynccontextmanager
    async def context():
        yield MagicMock()

    monkeypatch.setattr(module, "get_db_context", context)
    monkeypatch.setattr(module, "enqueue", AsyncMock(return_value=uuid4()))
    monkeypatch.setattr(module.conversation_repo, "bind_channel_source", AsyncMock())
    monkeypatch.setattr(
        module.job_repo, "claim_channel_reply", AsyncMock(return_value=outcome != "already_claimed")
    )
    settle = AsyncMock()
    monkeypatch.setattr(module.job_repo, "settle_channel_reply", settle)
    monkeypatch.setattr(
        "app.core.background.spawn_after_commit", lambda _db, coro, **_kw: coro.close()
    )

    async def turn():
        sink = module.segment_sink()
        assert sink is not None
        await sink(RunSegment(output="Saved answer", run=run, tool_calls=[], settled={}))
        if outcome == "refused":
            raise BadRequestError(message="Refused")
        if outcome == "crashed":
            raise RuntimeError("model failed after terminal persistence")
        return AnsweredTurn(text="Saved answer", run_id=run.id)

    router = routing.ChannelMessageRouter()
    deliver = AsyncMock(
        return_value=True, side_effect=OSError("network") if outcome == "delivery_failed" else None
    )
    failure = AsyncMock(return_value=True)
    monkeypatch.setattr(router, "_deliver", deliver)
    monkeypatch.setattr(router, "_post_failure", failure)
    monkeypatch.setattr(router, "_discard_files", AsyncMock())
    with queued_turn(uuid4()):
        if outcome == "delivery_failed":
            with pytest.raises(OSError):
                await router._run_turn(
                    reply.bot,
                    reply.incoming,
                    reply.db,
                    run=turn(),
                    handle=lambda: None,
                    files=[],
                    file_refusals=[],
                )
        else:
            assert await router._run_turn(
                reply.bot,
                reply.incoming,
                reply.db,
                run=turn(),
                handle=lambda: None,
                files=[],
                file_refusals=[],
            )
    assert deliver.await_count == int(outcome in {"completed", "delivery_failed"})
    assert failure.await_count == int(outcome in {"refused", "crashed"})
    assert settle.await_count == int(outcome != "already_claimed")
    if outcome != "already_claimed":
        assert settle.await_args.kwargs["delivered"] is (outcome != "delivery_failed")
