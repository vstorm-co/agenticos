"""Required handbacks are transactional jobs; retries only send the saved segment."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.capabilities.channel_tools._directory import ChannelDestination
from app.services.agent_runner import RunSegment
from app.services.channels.handback import EXPIRED_NOTICE, ChatNotice
from app.services.channels.handback_jobs import queue_notices, queue_segment
from app.services.transcript import RecordedToolCall
from app.worker.jobs import DELIVER_CHANNEL_HANDBACK, ChannelHandback
from app.worker.tasks.channel_tasks import deliver_handback

pytestmark = pytest.mark.anyio


def _job(*, notice: bool = False) -> ChannelHandback:
    return ChannelHandback(
        organization_id=uuid4(),
        run_id=uuid4(),
        bot_id=uuid4(),
        platform_chat_id="C1:123",
        private_chat=False,
        output="Saved answer",
        notice=notice,
        tool_calls=[
            {
                "tool_call_id": "c1",
                "tool_name": "send_email",
                "args": {"to": "demo@example.com"},
                "result": "Sent",
            }
        ],
        generated_files=frozenset({"chart.png"}),
    )


async def test_each_notice_is_queued_in_the_callers_transaction_with_independent_retries() -> None:
    db = MagicMock()
    job = _job()
    destination = ChannelDestination(
        bot_id=job.bot_id, platform_chat_id=job.platform_chat_id, private_chat=False
    )
    notices = [
        ChatNotice(job.organization_id, uuid4(), destination, EXPIRED_NOTICE) for _ in range(2)
    ]
    with patch("app.services.channels.handback_jobs.enqueue", new=AsyncMock()) as enqueue:
        await queue_notices(db, notices)
    assert enqueue.await_count == 2
    first, second = enqueue.await_args_list
    assert first.args[:2] == (db, DELIVER_CHANNEL_HANDBACK)
    assert first.args[2].notice is True
    assert first.args[2].output == EXPIRED_NOTICE
    assert first.kwargs["organization_id"] == job.organization_id
    assert first.kwargs["dedupe_key"] != second.kwargs["dedupe_key"]
    assert first.kwargs["concurrency_key"] == second.kwargs["concurrency_key"]
    db.commit.assert_not_called()


@pytest.mark.parametrize("cancelled", [True, False])
async def test_segment_snapshot_includes_inherited_results_and_never_commits_itself(
    cancelled: bool,
) -> None:
    db = MagicMock()
    job = _job()
    destination = ChannelDestination(
        bot_id=job.bot_id, platform_chat_id=job.platform_chat_id, private_chat=False
    )
    run = MagicMock(
        id=job.run_id,
        organization_id=job.organization_id,
        status="cancelled" if cancelled else "completed",
    )
    segment = RunSegment(
        output="" if cancelled else "Sent",
        run=run,
        tool_calls=[],
        settled={"c1": "OK"},
        generated_files=job.generated_files,
    )
    persist = queue_segment(
        db, destination, [RecordedToolCall("c1", "send_email", {"to": "a@example.com"})]
    )
    with patch("app.services.channels.handback_jobs.enqueue", new=AsyncMock()) as enqueue:
        await persist(segment)
    saved = enqueue.await_args.args[2]
    assert DELIVER_CHANNEL_HANDBACK.load(DELIVER_CHANNEL_HANDBACK.dump(saved)) == saved
    assert saved.output == ("This run was stopped from the console." if cancelled else "Sent")
    assert saved.tool_calls[0].result == "OK"
    assert saved.generated_files == job.generated_files
    db.commit.assert_not_called()


@pytest.mark.parametrize("notice", [True, False])
async def test_handler_only_sends_and_propagates_transport_failure_for_retry(notice: bool) -> None:
    job = _job(notice=notice)
    with (
        patch("app.worker.tasks.channel_tasks.ensure_channel_adapters") as adapters,
        patch("app.worker.tasks.channel_tasks.send_notice", new=AsyncMock()) as send,
        patch("app.worker.tasks.channel_tasks.deliver_in_chat", new=AsyncMock()) as deliver,
    ):
        chosen = send if notice else deliver
        chosen.side_effect = RuntimeError("offline")
        with pytest.raises(RuntimeError, match="offline"):
            await deliver_handback(job)
        chosen.side_effect = None
        await deliver_handback(job)
        assert chosen.await_count == 2
        assert adapters.call_count == 2
        if notice:
            deliver.assert_not_awaited()
            assert send.await_args.args[0].run_id == job.run_id
        else:
            send.assert_not_awaited()
            snapshot = deliver.await_args.kwargs["said"]
            assert snapshot.output == job.output
            assert snapshot.tool_calls[0].result == "Sent"
            assert snapshot.generated_files == job.generated_files
