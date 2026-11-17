"""UID cursors survive checks, and the reused client only issues read commands."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from mirage.accessor.imap import IMAPResponse

from app.core.exceptions import AuthorizationError, BadRequestError, ExternalServiceError
from app.core.mail_credential import ImapCredential
from app.services.integrations import imap

pytestmark = pytest.mark.anyio


def credential() -> ImapCredential:
    return ImapCredential(
        host="imap.example.com", username="user@example.com", password="private-password"
    )


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, AsyncMock]:
    client = AsyncMock()
    client.select.return_value = IMAPResponse(
        "OK", [b"[UIDVALIDITY 123]", b"[UIDNEXT 21]", b"Selected"]
    )
    accessor = MagicMock()
    accessor.get_imap = AsyncMock(return_value=client)
    accessor.close = AsyncMock()
    monkeypatch.setattr(imap, "EmailAccessor", lambda config: accessor)
    monkeypatch.setattr(imap.settings, "MIRAGE_ALLOWED_HOSTS", ["imap.example.com"])
    return accessor, client


async def test_first_check_and_a_uidvalidity_reset_are_quiet(
    server: tuple[MagicMock, AsyncMock],
) -> None:
    accessor, client = server
    for old in [None, {"uidvalidity": 122, "last_uid": 1}]:
        events, cursor = await imap.changed_mail(credential(), old)
        assert events == []
        assert cursor == {"uidvalidity": 123, "last_uid": 20}
    client.uid.assert_not_awaited()
    assert accessor.close.await_count == 2


async def test_only_new_uids_are_read_with_body_peek_and_a_bounded_literal(
    server: tuple[MagicMock, AsyncMock],
) -> None:
    accessor, client = server
    client.uid.side_effect = [
        IMAPResponse("OK", [b"19 20 21", b"SEARCH complete"]),
        IMAPResponse(
            "OK",
            [
                b"1 FETCH (UID 21",
                bytearray(b"Subject: New mail\r\nFrom: sender@example.com\r\n\r\nA new body"),
                b")",
            ],
        ),
    ]
    events, cursor = await imap.changed_mail(credential(), {"uidvalidity": 123, "last_uid": 20})
    assert [message["uid"] for message in events] == [21]
    assert events[0]["subject"] == "New mail"
    assert cursor["last_uid"] == 21
    assert client.uid.await_args_list[0].args == ("SEARCH", "UID 21:*")
    assert client.uid.await_args_list[1].args == ("FETCH", "21", "(UID BODY.PEEK[]<0.100000>)")
    accessor.close.assert_awaited_once()


async def test_disallowed_host_is_refused_before_any_connection(
    server: tuple[MagicMock, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    accessor, _ = server
    monkeypatch.setattr(imap.settings, "MIRAGE_ALLOWED_HOSTS", [])
    with pytest.raises(AuthorizationError, match="MIRAGE_ALLOWED_HOSTS"):
        await imap.changed_mail(credential(), None)
    accessor.get_imap.assert_not_awaited()


async def test_protocol_failure_is_a_failure_and_always_closes_the_mailbox(
    server: tuple[MagicMock, AsyncMock],
) -> None:
    accessor, client = server
    client.uid.return_value = IMAPResponse("NO", [b"refused"])
    with pytest.raises(ExternalServiceError, match="refused"):
        await imap.changed_mail(credential(), {"uidvalidity": 123, "last_uid": 20})
    accessor.close.assert_awaited_once()


async def test_search_cannot_inject_another_imap_command(
    server: tuple[MagicMock, AsyncMock],
) -> None:
    _, client = server
    with pytest.raises(BadRequestError):
        await imap.execute_mail(
            credential(), "search_messages", parameters={}, query={"query": "ALL\r\nDELETE INBOX"}
        )
    client.uid.assert_not_awaited()


async def test_repr_masks_the_password_while_the_vault_payload_preserves_it() -> None:
    value = credential()
    assert "private-password" not in repr(value)
    assert (
        ImapCredential.model_validate_json(value.model_dump_json()).password.get_secret_value()
        == "private-password"
    )


@pytest.mark.parametrize(
    "selected", [IMAPResponse("NO", []), IMAPResponse("OK", [b"no uid metadata"])]
)
async def test_mailbox_selection_requires_stable_uids(server, selected):
    accessor, client = server
    client.select.return_value = selected
    with pytest.raises(ExternalServiceError):
        await imap.changed_mail(credential(), None)
    accessor.close.assert_awaited_once()


@pytest.mark.parametrize("response", [IMAPResponse("NO", []), IMAPResponse("OK", [])])
async def test_failed_or_disappeared_message_is_not_returned_as_success(server, response):
    accessor, client = server
    client.uid.return_value = response
    with pytest.raises(ExternalServiceError):
        await imap.execute_mail(
            credential(), "read_message", parameters={"message_id": "3"}, query={}
        )
    accessor.close.assert_awaited_once()


@pytest.mark.parametrize("uid", ["0", "-1", "not-number", "1" * 21, "٣"])
async def test_message_uid_is_a_bounded_ascii_number(server, uid):
    with pytest.raises(BadRequestError):
        await imap.execute_mail(
            credential(), "read_message", parameters={"message_id": uid}, query={}
        )


async def test_imap_tool_search_is_bounded_and_unknown_operation_refused(server):
    _, client = server
    client.uid.return_value = IMAPResponse("OK", [b" ".join(str(i).encode() for i in range(1, 30))])
    result = await imap.execute_mail(credential(), "search_messages", parameters={}, query={})
    assert result["message_ids"] == list(range(5, 30)) and result["truncated"] is True
    with pytest.raises(BadRequestError):
        await imap.execute_mail(credential(), "delete_message", parameters={}, query={})


async def test_imap_transport_error_closes_without_leaking_credentials(server):
    accessor, client = server
    client.select.side_effect = ConnectionError("private-password")
    with pytest.raises(ExternalServiceError) as error:
        await imap.changed_mail(credential(), None)
    assert "private-password" not in str(error.value)
    accessor.close.assert_awaited_once()


async def test_imap_quiet_tick_and_invalid_uid_cursor_do_not_replay_history(server):
    _, client = server
    client.uid.return_value = IMAPResponse("OK", [b""])
    events, cursor = await imap.changed_mail(credential(), {"uidvalidity": 123, "last_uid": 20})
    assert not events and cursor == {"uidvalidity": 123, "last_uid": 20}
    events, cursor = await imap.changed_mail(
        credential(), {"uidvalidity": 123, "last_uid": "invalid"}
    )
    assert not events and cursor["last_uid"] == 20


async def test_a_parser_body_field_that_is_not_text_is_never_stringified(server, monkeypatch):
    _, client = server
    client.uid.return_value = IMAPResponse("OK", [bytearray(b"Subject: test\r\n\r\nbody")])
    monkeypatch.setattr(imap, "parse_rfc822", lambda raw: {"body_text": "body", "body_html": None})
    read = await imap.execute_mail(
        credential(), "read_message", parameters={"message_id": "1"}, query={}
    )
    assert read["body_text"] == "body" and read["body_html"] is None


async def test_imap_password_cannot_inject_a_protocol_command():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ImapCredential(
            host="imap.example.com", username="member", password="app-password\r\nDELETE INBOX"
        )
