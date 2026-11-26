"""`channel-forget-customer`: the number or id is read from a prompt or stdin, never argv (#2076)."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from click.testing import CliRunner

from app.commands import channel as cmd
from app.commands.channel import channel_forget_customer
from app.core.exceptions import ConflictError
from app.schemas.channel_bot import WhatsAppCustomerList, WhatsAppCustomerRead
from app.services.channels.whatsapp_erasure import CustomerErasure

BOT = str(uuid4())


def _match(bsuid: str = "US.111", *, linked: bool = False) -> WhatsAppCustomerRead:
    return WhatsAppCustomerRead(
        id=uuid4(), bsuid=bsuid, phone="48600700800", profile_name="Ana", username="•••• 0800",
        last_message_at=datetime(2026, 11, 4, tzinfo=UTC), linked=linked,
    )  # fmt: skip


def _invoke(args: list[str], *, input: str | None = None, service: MagicMock):
    assert service is not None

    @asynccontextmanager
    async def opened(org_id):
        yield service

    with patch.object(cmd, "_channel_service", opened):
        outcome = CliRunner().invoke(channel_forget_customer, args, input=input)
    return outcome, service


def _service(*, matches: list[WhatsAppCustomerRead] | None = None, error=None) -> MagicMock:
    service = MagicMock()
    service.get = AsyncMock(return_value=SimpleNamespace(platform="whatsapp"))
    service.find_whatsapp_customers = AsyncMock(
        return_value=WhatsAppCustomerList(items=matches or [], total=len(matches or []))
    )
    service.forget_whatsapp_bsuid = AsyncMock(
        return_value=CustomerErasure(identities=1, conversations=2), side_effect=error
    )
    return service


@pytest.mark.security
def test_there_is_no_option_that_takes_the_value_so_it_never_reaches_argv():
    names = {name for param in channel_forget_customer.params for name in param.opts}

    assert names >= {"--bot-id", "--by", "--yes", "--org"}
    assert not names & {"--phone", "--bsuid", "--value", "--number"}
    assert not [p for p in channel_forget_customer.params if p.prompt]


@pytest.mark.security
def test_the_value_is_read_from_stdin_when_it_is_not_a_terminal():
    service = _service()

    outcome, _ = _invoke(
        ["--bot-id", BOT, "--by", "bsuid", "--yes"], input="US.111\n", service=service
    )

    assert outcome.exit_code == 0, outcome.output
    assert service.forget_whatsapp_bsuid.await_args.kwargs == {
        "bsuid": "US.111", "named_by": "bsuid", "actor_user_id": None, "via": "cli",
    }  # fmt: skip
    assert "US.111" not in outcome.output
    assert "conversations" in outcome.output


@pytest.mark.security
def test_a_terminal_is_asked_with_a_hidden_prompt():
    service = _service()
    with (
        patch.object(cmd, "_stdin_is_terminal", return_value=True),
        patch.object(cmd.click, "prompt", return_value="US.111") as prompt,
    ):
        outcome, _ = _invoke(["--bot-id", BOT, "--by", "bsuid", "--yes"], service=service)

    assert outcome.exit_code == 0, outcome.output
    assert prompt.call_args.kwargs["hide_input"] is True


@pytest.mark.security
def test_a_phone_lists_its_matches_masked_and_asks_before_forgetting():
    service = _service(matches=[_match()])

    declined, _ = _invoke(
        ["--bot-id", BOT, "--by", "phone"], input="+48 600 700 800\nn\n", service=service
    )

    assert declined.exit_code == 0
    assert "•••• 0800" in declined.output and "Ana" in declined.output
    assert "unverified" in declined.output
    assert "48600700800" not in declined.output and "600 700" not in declined.output
    service.forget_whatsapp_bsuid.assert_not_awaited()

    confirmed, _ = _invoke(
        ["--bot-id", BOT, "--by", "phone"], input="+48 600 700 800\ny\n", service=service
    )

    assert confirmed.exit_code == 0
    assert service.forget_whatsapp_bsuid.await_args.kwargs == {
        "bsuid": "US.111", "named_by": "phone", "actor_user_id": None, "via": "cli",
    }  # fmt: skip


@pytest.mark.security
def test_yes_skips_the_confirmation_and_forgets_every_match():
    service = _service(matches=[_match("US.1"), _match("US.2")])

    outcome, _ = _invoke(
        ["--bot-id", BOT, "--by", "phone", "--yes"], input="48600700800\n", service=service
    )

    assert outcome.exit_code == 0
    assert [c.kwargs["bsuid"] for c in service.forget_whatsapp_bsuid.await_args_list] == [
        "US.1",
        "US.2",
    ]
    assert {c.kwargs["via"] for c in service.forget_whatsapp_bsuid.await_args_list} == {"cli"}


@pytest.mark.security
def test_a_phone_with_no_match_says_so_and_erases_nothing():
    service = _service(matches=[])

    outcome, _ = _invoke(
        ["--bot-id", BOT, "--by", "phone", "--yes"], input="48600700800\n", service=service
    )

    assert "No customer" in outcome.output
    service.forget_whatsapp_bsuid.assert_not_awaited()


@pytest.mark.security
def test_a_linked_customer_is_refused_in_words_and_the_command_fails():
    service = _service(error=ConflictError(message="This customer is linked to a member account."))

    outcome, _ = _invoke(
        ["--bot-id", BOT, "--by", "bsuid", "--yes"], input="US.111\n", service=service
    )

    assert outcome.exit_code == 1
    assert "linked to a member account" in outcome.output
    assert "US.111" not in outcome.output


@pytest.mark.security
def test_an_empty_value_and_a_malformed_bot_id_are_refused():
    service = _service()

    empty, _ = _invoke(["--bot-id", BOT, "--by", "bsuid", "--yes"], input="\n", service=service)
    bad, _ = _invoke(
        ["--bot-id", "nope", "--by", "bsuid", "--yes"], input="US.1\n", service=service
    )

    assert empty.exit_code == 1 and bad.exit_code == 1
    service.forget_whatsapp_bsuid.assert_not_awaited()


@pytest.mark.security
def test_a_linked_match_refuses_the_whole_command_before_anything_is_erased():
    service = _service(matches=[_match("US.1"), _match("US.2", linked=True)])

    outcome, _ = _invoke(
        ["--bot-id", BOT, "--by", "phone", "--yes"], input="48600700800\n", service=service
    )

    assert outcome.exit_code == 1
    service.forget_whatsapp_bsuid.assert_not_awaited()
    assert "Erased" not in outcome.output
    assert "linked to a member account" in outcome.output
    assert "48600700800" not in outcome.output


@pytest.mark.security
def test_a_phone_search_on_another_platforms_bot_is_a_clean_error():
    service = _service()
    service.get = AsyncMock(return_value=SimpleNamespace(platform="telegram"))

    outcome, _ = _invoke(
        ["--bot-id", BOT, "--by", "phone", "--yes"], input="48600700800\n", service=service
    )

    assert outcome.exit_code == 1
    assert "not a WhatsApp bot" in outcome.output
    assert outcome.exception is None or isinstance(outcome.exception, SystemExit)
    service.find_whatsapp_customers.assert_not_awaited()
