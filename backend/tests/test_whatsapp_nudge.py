"""The sweep that nudges a customer before their window closes (#2076)."""

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.channels.base import PromptMessage
from app.services.channels.whatsapp_nudge import send_due_nudges
from app.services.channels.whatsapp_window import NUDGE_BUTTON, NUDGE_REPLY_ID, NUDGE_TEXT
from app.worker import jobs
from app.worker.handlers import production
from app.worker.schedules import SCHEDULES
from app.worker.tasks import channel_tasks

pytestmark = pytest.mark.anyio

MODULE = "app.services.channels.whatsapp_nudge"
NOW = datetime(2026, 11, 5, 8, tzinfo=UTC)
ORG = uuid.uuid4()
BOT = uuid.uuid4()
BSUID = "US.secret-customer"


def _customer(bsuid: str = BSUID) -> MagicMock:
    return MagicMock(id=uuid.uuid4(), organization_id=ORG, bot_id=BOT, bsuid=bsuid)


class World:
    def __init__(self) -> None:
        self.customers = [_customer()]
        self.won: bool | Exception = True
        self.bot: MagicMock | None = MagicMock(id=BOT, is_active=True)
        self.token: str | Exception = "tok"
        self.adapter = MagicMock(send_prompt=AsyncMock(side_effect=self._send))
        self.marked: list[uuid.UUID] = []
        self.events: list[str] = []
        """What happened in order: a session opening or exiting, a mark, a send."""

    async def _send(self, *args: object) -> None:
        self.events.append("send")


@pytest.fixture
def world():
    world = World()

    @asynccontextmanager
    async def session():
        world.events.append("open")
        yield MagicMock()
        world.events.append("exit")

    async def candidates(db, *, now, limit=100):
        assert now == NOW
        return world.customers

    async def mark(db, *, customer_id, now):
        assert now == NOW
        world.marked.append(customer_id)
        world.events.append("mark")
        if isinstance(world.won, Exception):
            raise world.won
        return world.won

    def unseal(bot):
        if isinstance(world.token, Exception):
            raise world.token
        return world.token

    with (
        patch(f"{MODULE}.get_db_context", session),
        patch(f"{MODULE}.whatsapp_customer_repo.nudge_candidates", candidates),
        patch(f"{MODULE}.whatsapp_customer_repo.mark_nudged", mark),
        patch(
            f"{MODULE}.channel_bot_repo.get_for_org",
            AsyncMock(side_effect=lambda *a, **k: world.bot),
        ),
        patch(f"{MODULE}.unseal_bot_token", unseal),
        patch(f"{MODULE}.whatsapp_adapter", return_value=world.adapter),
    ):
        yield world


async def test_a_due_customer_gets_one_prompt_with_one_button_and_no_run(world):
    assert await send_due_nudges(NOW) == 1

    world.adapter.send_prompt.assert_awaited_once()
    token, prompt = world.adapter.send_prompt.await_args.args
    assert token == "tok"
    assert isinstance(prompt, PromptMessage)
    assert (prompt.platform_chat_id, prompt.text, prompt.bot_id, prompt.run_id) == (
        BSUID,
        NUDGE_TEXT,
        str(BOT),
        None,
    )
    [choice] = prompt.choices
    assert (choice.label, choice.value) == (NUDGE_BUTTON, NUDGE_REPLY_ID)
    assert world.marked == [world.customers[0].id]


async def test_a_nudge_lost_to_another_sweep_sends_nothing(world):
    world.won = False
    assert await send_due_nudges(NOW) == 0
    world.adapter.send_prompt.assert_not_awaited()


async def test_a_failed_send_is_logged_without_the_customer_and_the_rest_still_go(world, caplog):
    world.customers = [_customer("US.first"), _customer("US.second")]
    world.adapter.send_prompt.side_effect = [RuntimeError("to US.first"), None]

    with caplog.at_level(logging.WARNING):
        assert await send_due_nudges(NOW) == 1

    assert [c.args[1].platform_chat_id for c in world.adapter.send_prompt.await_args_list] == [
        "US.first",
        "US.second",
    ]
    [record] = [r for r in caplog.records if r.message == "whatsapp_nudge_failed"]
    assert (record.bot_id, record.error) == (str(BOT), "RuntimeError")
    assert "US.first" not in caplog.text
    assert len(world.marked) == 2


async def test_an_inactive_or_missing_bot_sends_nothing(world):
    world.bot = MagicMock(id=BOT, is_active=False)
    assert await send_due_nudges(NOW) == 0
    world.bot = None
    assert await send_due_nudges(NOW) == 0
    world.adapter.send_prompt.assert_not_awaited()


@pytest.mark.security
async def test_a_token_that_cannot_be_unsealed_sends_nothing_and_logs_no_secret(world, caplog):
    world.token = ValueError("sealed-secret-value")
    with caplog.at_level(logging.WARNING):
        assert await send_due_nudges(NOW) == 0
    world.adapter.send_prompt.assert_not_awaited()
    [record] = [r for r in caplog.records if r.message == "whatsapp_nudge_unsent"]
    assert (record.bot_id, record.error) == (str(BOT), "ValueError")
    assert "sealed-secret-value" not in caplog.text


async def test_the_marking_is_committed_before_the_send(world):
    """A crash or a failed send after the mark never sends the nudge twice."""
    await send_due_nudges(NOW)

    after_mark = world.events[world.events.index("mark") :]
    assert after_mark.index("exit") < after_mark.index("send")


async def test_one_customers_database_error_does_not_stop_the_tick(world, caplog):
    world.customers = [_customer("US.first"), _customer("US.second")]
    answers = iter([RuntimeError("db for US.first"), True])

    async def mark(db, *, customer_id, now):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    with (
        patch(f"{MODULE}.whatsapp_customer_repo.mark_nudged", mark),
        caplog.at_level(logging.WARNING),
    ):
        assert await send_due_nudges(NOW) == 1

    [(_, prompt)] = [c.args for c in world.adapter.send_prompt.await_args_list]
    assert prompt.platform_chat_id == "US.second"
    [record] = [r for r in caplog.records if r.message == "whatsapp_nudge_failed"]
    assert (record.bot_id, record.error) == (str(BOT), "RuntimeError")
    assert "US.first" not in caplog.text


async def test_the_task_registers_the_adapters_before_it_sweeps():
    order: list[str] = []

    async def sweep(now: datetime) -> int:
        order.append("sweep")
        return 3

    with (
        patch.object(channel_tasks, "ensure_channel_adapters", lambda: order.append("ensure")),
        patch.object(channel_tasks, "send_due_nudges", sweep),
    ):
        assert await channel_tasks.send_whatsapp_nudges() == 3
    assert order == ["ensure", "sweep"]


def test_the_sweep_is_bound_and_runs_every_five_minutes():
    assert jobs.WHATSAPP_NUDGES.kind in production()
    [schedule] = [s for s in SCHEDULES if s.task is jobs.WHATSAPP_NUDGES]
    assert schedule.every.total_seconds() == 300
    assert jobs.WHATSAPP_NUDGES.max_attempts == 1
