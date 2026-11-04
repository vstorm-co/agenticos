"""The predicate that decides who continues a parked chat run, and the fixed notices (#2656)."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest

from app.agents.capabilities.channel_tools._directory import ChannelDestination
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import CHANNEL_SURFACES
from app.services.channels import _adapters, get_adapter, handback
from app.services.channels.base import OutgoingMessage
from app.services.channels.handback import (
    EXPIRED_NOTICE,
    REFUSED_NOTICE,
    STOPPED_NOTICE,
    STRANDED_NOTICE,
    ChatNotice,
    chat_destination,
    continues_in_chat,
    decided_by_a_person,
    ensure_channel_adapters,
    send_notice,
)

pytestmark = pytest.mark.anyio

_ORG = uuid4()


@pytest.fixture(autouse=True)
def admitted_notice():
    with (
        patch(
            "app.services.channels.handback.agent_run_repo.get_run",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "app.services.channels.next_steps.incoming_for_run",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "app.services.channels.router.ChannelMessageRouter.admission",
            new=AsyncMock(return_value=SimpleNamespace(verdict="admitted")),
        ),
    ):
        yield


def _person() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=_ORG, role=OrgRoleName.OWNER)


def _key() -> AuthContext:
    return AuthContext(
        user_id=uuid4(), organization_id=_ORG, role=OrgRoleName.OWNER, api_key_id=uuid4()
    )


def _run(surface: str, destination: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), surface=surface, paused_state={"channel_destination": destination}
    )


def _destination() -> dict[str, object]:
    return {"bot_id": str(uuid4()), "platform_chat_id": "C1:1.0", "private_chat": False}


@pytest.mark.parametrize("surface", sorted(s.value for s in CHANNEL_SURFACES))
def test_a_chat_run_parked_with_its_chat_continues_there_for_a_person(surface: str) -> None:
    run = _run(surface, _destination())

    assert continues_in_chat(run, _person()) is True  # type: ignore[arg-type]
    destination = chat_destination(run)  # type: ignore[arg-type]
    assert destination is not None and destination.platform_chat_id == "C1:1.0"


def test_a_key_never_continues_a_chat_run() -> None:
    assert continues_in_chat(_run("slack", _destination()), _key()) is False  # type: ignore[arg-type]


@pytest.mark.parametrize("paused_state", [{"channel_destination": None}, {}])
def test_a_run_parked_before_its_chat_was_recorded_continues_nowhere(
    paused_state: dict[str, object],
) -> None:
    run = SimpleNamespace(id=uuid4(), surface="slack", paused_state=paused_state)

    assert chat_destination(run) is None  # type: ignore[arg-type]
    assert continues_in_chat(run, _person()) is False  # type: ignore[arg-type]


def test_a_malformed_destination_reads_as_no_chat_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    run = _run("slack", {"bot_id": "x"})

    with caplog.at_level(logging.WARNING):
        assert chat_destination(run) is None  # type: ignore[arg-type]

    assert str(run.id) in caplog.text


@pytest.mark.parametrize("surface", ["web", "embed", "api", "a2a", "schedule", "workflow"])
def test_a_web_api_workflow_or_schedule_run_continues_nowhere(surface: str) -> None:
    assert continues_in_chat(_run(surface, _destination()), _person()) is False  # type: ignore[arg-type]


def test_nobody_signed_in_is_not_a_person() -> None:
    assert decided_by_a_person(AuthContext.anonymous(_ORG)) is False


def test_a_row_that_is_no_parked_state_reads_as_no_chat() -> None:
    assert chat_destination(MagicMock()) is None


def test_a_channel_run_with_no_parked_state_reads_as_no_chat() -> None:
    run = SimpleNamespace(id=uuid4(), surface="slack", paused_state=None)

    assert chat_destination(run) is None  # type: ignore[arg-type]


def test_the_notices_are_the_fixed_sentences() -> None:
    assert EXPIRED_NOTICE == "This request expired without a decision."
    assert STOPPED_NOTICE == "This run was stopped from the console."
    assert STRANDED_NOTICE == "A decision was recorded, but the run could not continue."
    assert REFUSED_NOTICE == ("That was decided outside the chat, but the run could not continue.")


def _bot(*, active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), platform="slack", is_active=active, api_base_url="https://x.example"
    )


def _destination_value() -> ChannelDestination:
    destination = chat_destination(_run("slack", _destination()))  # type: ignore[arg-type]
    assert destination is not None
    return destination


_DESTINATION = _destination_value()


async def _post(bot: object, adapter: object, *, text: str = EXPIRED_NOTICE) -> UUID:
    run_id = uuid4()
    context = MagicMock()
    context.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    context.return_value.__aexit__ = AsyncMock(return_value=False)
    with (
        patch.object(handback, "get_db_context", context),
        patch.object(handback.channel_bot_repo, "get_for_org", AsyncMock(return_value=bot)),
        patch.object(handback, "get_adapter", adapter),
        patch.object(handback, "unseal_bot_token", return_value="tok"),
    ):
        await send_notice(ChatNotice(_ORG, run_id, _DESTINATION, text))
    return run_id


async def test_a_notice_is_posted_to_the_recorded_chat_with_the_bots_current_token() -> None:
    bot = _bot()
    adapter = MagicMock(send_message=AsyncMock())

    await _post(bot, MagicMock(return_value=adapter))

    adapter.send_message.assert_awaited_once_with(
        "tok",
        OutgoingMessage(
            platform_chat_id="C1:1.0", text=EXPIRED_NOTICE, api_base_url=bot.api_base_url
        ),
    )


@pytest.mark.parametrize("bot", [None, _bot(active=False)])
async def test_a_notice_for_a_missing_or_switched_off_bot_is_not_sent(bot: object) -> None:
    adapter = MagicMock(send_message=AsyncMock())
    get = MagicMock(return_value=adapter)

    await _post(bot, get)

    adapter.send_message.assert_not_awaited()
    get.assert_not_called()


async def test_a_transport_failure_escapes_for_the_workers_bounded_retry() -> None:
    adapter = MagicMock(send_message=AsyncMock(side_effect=httpx.HTTPError("offline")))
    with pytest.raises(httpx.HTTPError, match="offline"):
        await _post(_bot(), MagicMock(return_value=adapter))


async def test_an_unregistered_adapter_fails_the_job_instead_of_losing_the_notice() -> None:
    with pytest.raises(KeyError):
        await _post(_bot(), MagicMock(side_effect=KeyError("slack")))


def _notices(count: int) -> list[ChatNotice]:
    return [
        ChatNotice(
            organization_id=_ORG, run_id=uuid4(), destination=_DESTINATION, text=EXPIRED_NOTICE
        )
        for _ in range(count)
    ]


async def test_no_session_is_open_while_the_adapter_sends() -> None:
    open_sessions = 0
    seen: list[int] = []

    class Session:
        async def __aenter__(self) -> MagicMock:
            nonlocal open_sessions
            open_sessions += 1
            return MagicMock()

        async def __aexit__(self, *_exc: object) -> bool:
            nonlocal open_sessions
            open_sessions -= 1
            return False

    async def send(*_args: object) -> None:
        seen.append(open_sessions)

    adapter = MagicMock(send_message=send)
    with (
        patch.object(handback, "get_db_context", lambda: Session()),
        patch.object(handback.channel_bot_repo, "get_for_org", AsyncMock(return_value=_bot())),
        patch.object(handback, "get_adapter", MagicMock(return_value=adapter)),
        patch.object(handback, "unseal_bot_token", return_value="tok"),
    ):
        for notice in _notices(2):
            await send_notice(notice)

    assert seen == [0, 0]


async def test_ensuring_adapters_registers_each_platform_once_and_starts_nothing() -> None:
    from app.services.channels.discord import DiscordAdapter
    from app.services.channels.mattermost import MattermostAdapter
    from app.services.channels.slack import SlackAdapter
    from app.services.channels.teams import TeamsAdapter
    from app.services.channels.telegram import TelegramAdapter

    platforms = ["slack", "telegram", "mattermost", "discord", "teams"]
    with patch.dict(_adapters, {}, clear=True):
        started = [
            patch.object(cls, name, AsyncMock())
            for cls in (
                SlackAdapter,
                TelegramAdapter,
                MattermostAdapter,
                DiscordAdapter,
                TeamsAdapter,
            )
            for name in ("start_polling", "stop_polling")
            if hasattr(cls, name)
        ]
        mocks = [p.start() for p in started]
        try:
            ensure_channel_adapters()
            first = {p: get_adapter(p) for p in platforms}
            ensure_channel_adapters()
            second = {p: get_adapter(p) for p in platforms}
        finally:
            for p in started:
                p.stop()

    assert all(first[p] is second[p] for p in platforms)
    assert all(m.await_count == 0 for m in mocks)


@pytest.mark.security
@pytest.mark.parametrize("revoked", ["run", "session", "admission"])
async def test_notices_recheck_admission_immediately_before_posting(revoked: str) -> None:
    adapter = MagicMock(send_message=AsyncMock())
    with (
        patch(
            "app.services.channels.handback.agent_run_repo.get_run",
            new=AsyncMock(return_value=None if revoked == "run" else MagicMock()),
        ),
        patch(
            "app.services.channels.next_steps.incoming_for_run",
            new=AsyncMock(return_value=None if revoked == "session" else MagicMock()),
        ),
        patch(
            "app.services.channels.router.ChannelMessageRouter.admission",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    verdict="refused" if revoked == "admission" else "allowed"
                )
            ),
        ),
    ):
        await _post(_bot(), MagicMock(return_value=adapter))
    adapter.send_message.assert_not_awaited()
