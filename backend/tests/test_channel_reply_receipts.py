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
    if state in {"claimed", "failed", "refused"}:
        with pytest.raises(BadRequestError if state in {"claimed", "refused"} else RuntimeError):
            await channel_tasks.deliver_initial_reply(job)
    else:
        await channel_tasks.deliver_initial_reply(job)
    if state in {"missing", "claimed"}:
        deliver.assert_not_awaited()
        settle.assert_not_awaited()
    else:
        deliver.assert_awaited_once_with(job)
        settle.assert_not_awaited()


async def test_native_reply_id_is_remembered_without_adding_another_history_message(monkeypatch):
    reply = receipt()
    reply.run_id = uuid4()
    bind = AsyncMock()
    monkeypatch.setattr(module.conversation_repo, "bind_channel_source", bind)
    reply.job_id = uuid4()
    settled_db = MagicMock()

    @asynccontextmanager
    async def context():
        yield settled_db

    monkeypatch.setattr(module, "get_db_context", context)
    settle = AsyncMock()
    monkeypatch.setattr(module.job_repo, "settle_channel_reply", settle)
    await module.remember_delivered_post("ignored")
    with module.required_reply(reply):
        await module.remember_delivered_post(None)
        await module.remember_delivered_post("native-reply")
        bind.assert_not_awaited()
        await reply.settle(delivered=True)
    bind.assert_awaited_once_with(
        settled_db, run_id=reply.run_id, role="assistant", source_id="native-reply"
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
    monkeypatch.setattr(module.job_repo, "lock_channel_message_lease", AsyncMock(return_value=True))

    @asynccontextmanager
    async def context():
        yield MagicMock()

    monkeypatch.setattr(module, "get_db_context", context)
    monkeypatch.setattr(module, "enqueue", AsyncMock(return_value=uuid4()))
    monkeypatch.setattr(module.job_repo, "render_channel_reply", AsyncMock())
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


async def test_usage_rendering_is_in_the_terminal_snapshot_before_commit(monkeypatch):
    reply = receipt()
    monkeypatch.setattr(module.conversation_repo, "bind_channel_source", AsyncMock())
    enqueue = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(module, "enqueue", enqueue)
    renderer = AsyncMock(return_value="Answer\n\n_Cost: $0.03_")
    segment = RunSegment(
        output="Answer",
        run=SimpleNamespace(id=uuid4(), status="completed"),
        tool_calls=[],
        settled={},
    )
    with module.required_reply(reply):
        sink = module.segment_sink(renderer)
        assert sink is not None
        await sink(segment)
        assert module.saved_rendering() == "Answer\n\n_Cost: $0.03_"
    assert module.saved_rendering() is None
    assert (
        enqueue.await_args.args[2].output
        == "Answer\n\n_Cost: $0.03_\n\nAn attachment could not be read."
    )
    renderer.assert_awaited_once_with(segment)
    reply.db.commit.assert_not_called()


async def test_receipt_failure_prevents_delivery_settlement(monkeypatch):
    reply = receipt()
    reply.job_id, reply.run_id = uuid4(), uuid4()
    reply.native_ids.add("native-answer")
    db = MagicMock()
    events = []

    @asynccontextmanager
    async def context():
        try:
            yield db
        except RuntimeError:
            events.append("rollback")
            raise
        else:
            events.append("commit")

    monkeypatch.setattr(module, "get_db_context", context)
    monkeypatch.setattr(
        module.conversation_repo,
        "bind_channel_source",
        AsyncMock(side_effect=RuntimeError("database")),
    )
    settle = AsyncMock()
    monkeypatch.setattr(module.job_repo, "settle_channel_reply", settle)
    with pytest.raises(RuntimeError):
        await reply.settle(delivered=True)
    assert events == ["rollback"]
    settle.assert_not_awaited()


async def test_a_lease_lost_during_the_last_model_request_cannot_save_a_reply(monkeypatch):
    import asyncio

    from app.services.channels.steering import queued_turn

    reply = receipt()
    reply.db.rollback = AsyncMock()
    monkeypatch.setattr(
        module.job_repo, "lock_channel_message_lease", AsyncMock(return_value=False)
    )
    enqueue = AsyncMock()
    monkeypatch.setattr(module, "enqueue", enqueue)
    with queued_turn(uuid4()), pytest.raises(asyncio.CancelledError, match="lease"):
        await reply.persist(
            RunSegment(
                output="Late answer",
                run=SimpleNamespace(id=uuid4(), status="completed"),
                tool_calls=[],
                settled={},
            )
        )
    reply.db.rollback.assert_awaited_once()
    enqueue.assert_not_awaited()


async def test_rendering_before_a_snapshot_keeps_native_placeholder_without_a_job(monkeypatch):
    reply = receipt()
    write = AsyncMock()
    monkeypatch.setattr(module.job_repo, "render_channel_reply", write)
    await reply.render("Answer", native_id="placeholder")
    assert reply.native_ids == {"placeholder"}
    write.assert_not_awaited()


@pytest.mark.parametrize(
    "status,notice",
    [
        ("budget_exceeded", "usage limit"),
        ("loop_stopped", "repeating"),
        ("guardrail_blocked", "could not produce"),
        ("awaiting_approval", "approval"),
        ("awaiting_answer", "question"),
    ],
)
async def test_empty_terminal_segments_render_the_status_instead_of_an_internal_error(
    monkeypatch, status, notice
):
    monkeypatch.setattr(module.conversation_repo, "bind_channel_source", AsyncMock())
    enqueue = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(module, "enqueue", enqueue)
    reply = receipt()
    await reply.persist(
        RunSegment(
            output="", run=SimpleNamespace(id=uuid4(), status=status), tool_calls=[], settled={}
        )
    )
    assert notice in enqueue.await_args.args[2].output.lower()
    assert reply.rendered_output


@pytest.mark.parametrize(
    "quota,reservation,fails",
    [(True, True, False), (True, False, False), (False, False, False), (True, True, True)],
)
async def test_requested_files_are_stored_before_the_terminal_handback(
    monkeypatch, quota, reservation, fails
):
    from app.services.channels.base import OutgoingAttachment

    monkeypatch.setattr(module.conversation_repo, "bind_channel_source", AsyncMock())
    reservation_id = uuid4() if reservation else None
    monkeypatch.setattr(
        module.generated_media,
        "admit_generated_media",
        AsyncMock(return_value=SimpleNamespace(admitted=quota, reservation_id=reservation_id)),
    )
    store = AsyncMock(
        return_value="stored-report.csv",
        side_effect=RuntimeError("storage unavailable") if fails else None,
    )
    monkeypatch.setattr(module.generated_media, "keep_generated_media", store)
    release = AsyncMock()
    monkeypatch.setattr(module.generated_media, "release_generated_media", release)
    enqueue = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(module, "enqueue", enqueue)
    reply = receipt()
    segment = RunSegment(
        output="Report",
        run=SimpleNamespace(id=uuid4(), status="completed", conversation_id=uuid4()),
        tool_calls=[],
        settled={},
        outbound=(OutgoingAttachment("report.csv", b"a,b", "text/csv"),),
    )
    if not quota or fails:
        with pytest.raises(RuntimeError if fails else BadRequestError):
            await reply.persist(segment)
        enqueue.assert_not_awaited()
    else:
        await reply.persist(segment)
        file = enqueue.await_args.args[2].attachments[0]
        assert (file.filename, file.mime_type, file.stored_leaf) == (
            "report.csv",
            "text/csv",
            "stored-report.csv",
        )
        assert store.await_args.args == (reply.bot.organization_id, b"a,b")
    assert release.await_count == int(quota and reservation)
