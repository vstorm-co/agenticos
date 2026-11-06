"""Mail adapter tests use fake HTTP; no live mailbox or credentials are used."""

from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from app.core.exceptions import ExternalServiceError
from app.services.portals.reply_metadata import MailReplyMetadataClient

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)
TOKEN = SecretStr("private-token")


def google_message() -> dict[str, object]:
    return {
        "id": "m",
        "threadId": "t",
        "internalDate": str(int(NOW.timestamp() * 1000)),
        "payload": {
            "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {
                    "name": "Authentication-Results",
                    "value": "mx.google.com; dmarc=pass header.from=example.com",
                },
                {"name": "Message-ID", "value": "<m@example.com>"},
            ]
        },
    }


def graph_message() -> dict[str, object]:
    return {
        "id": "m",
        "conversationId": "t",
        "receivedDateTime": NOW.isoformat(),
        "from": {"emailAddress": {"address": "alice@example.com"}},
        "parentFolderId": "inbox",
        "internetMessageId": "<m@example.com>",
        "internetMessageHeaders": [
            {"name": "X-MS-Exchange-Organization-AuthAs", "value": "Internal"}
        ],
    }


async def test_gmail_reads_only_metadata_and_authenticates_sender():
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "gmail.googleapis.com"
        assert request.url.params["format"] == "metadata"
        assert request.headers["Authorization"] == "Bearer private-token"
        return httpx.Response(200, json={"id": "t", "messages": [google_message()]})

    client = MailReplyMetadataClient(httpx.MockTransport(respond))
    try:
        messages = await client.read(
            provider="google", access_token=TOKEN, thread_id="t", not_before=NOW
        )
        assert len(messages) == 1 and messages[0].authenticated
        assert messages[0].sender == "alice@example.com" and messages[0].received_at == NOW
        assert messages[0].rfc_message_id == "<m@example.com>"
    finally:
        await client.aclose()


@pytest.mark.security
@pytest.mark.parametrize(
    "variant",
    ["wrong_thread", "wrong_message_thread", "invalid_date", "http", "invalid_json", "redirect"],
)
async def test_gmail_failures_have_no_reply_verdict_or_secret(variant: str):
    msg = google_message()
    if variant == "wrong_message_thread":
        msg["threadId"] = "other"
    if variant == "invalid_date":
        msg["internalDate"] = "9999999999999999"
    response = httpx.Response(
        200, json={"id": "other" if variant == "wrong_thread" else "t", "messages": [msg]}
    )
    if variant == "http":
        response = httpx.Response(401, text="private-token")
    if variant == "invalid_json":
        response = httpx.Response(200, text="private-token")
    if variant == "redirect":
        response = httpx.Response(302, headers={"Location": "https://evil.example"})
    client = MailReplyMetadataClient(httpx.MockTransport(lambda _: response))
    try:
        with pytest.raises(ExternalServiceError) as error:
            await client.read(provider="google", access_token=TOKEN, thread_id="t", not_before=NOW)
        assert "private-token" not in str(error.value)
    finally:
        await client.aclose()


async def test_graph_paginates_only_on_the_same_endpoint():
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if "mailFolders" in request.url.path:
            return httpx.Response(200, json={"id": "sent"})
        calls.append(request)
        if len(calls) == 1:
            assert "conversationId eq 't'" in request.url.params["$filter"]
            return httpx.Response(
                200,
                json={
                    "value": [],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=1",
                },
            )
        return httpx.Response(200, json={"value": [graph_message()]})

    client = MailReplyMetadataClient(httpx.MockTransport(respond))
    try:
        messages = await client.read(
            provider="outlook", access_token=TOKEN, thread_id="t", not_before=NOW
        )
        assert (
            len(calls) == 2
            and messages[0].authenticated
            and messages[0].rfc_message_id == "<m@example.com>"
        )
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "target",
    [
        "http://graph.microsoft.com/v1.0/me/messages",
        "https://evil.example/v1.0/me/messages",
        "https://graph.microsoft.com:444/v1.0/me/messages",
        "https://graph.microsoft.com/v1.0/me/contacts",
        "https://user:pass@graph.microsoft.com/v1.0/me/messages",
        "https://graph.microsoft.com/v1.0/me/messages#x",
    ],
)
async def test_graph_refuses_unsafe_pagination(target: str):
    client = MailReplyMetadataClient(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"id": "sent"}
                if "mailFolders" in request.url.path
                else {"value": [], "@odata.nextLink": target},
            )
        )
    )
    try:
        with pytest.raises(ExternalServiceError, match="unsafe continuation"):
            await client.read(provider="outlook", access_token=TOKEN, thread_id="t", not_before=NOW)
    finally:
        await client.aclose()


async def test_graph_limits_pages_instead_of_claiming_nobody_replied():
    requests = 0

    def respond(request: httpx.Request) -> httpx.Response:
        if "mailFolders" in request.url.path:
            return httpx.Response(200, json={"id": "sent"})
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            json={
                "value": [],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=1",
            },
        )

    client = MailReplyMetadataClient(httpx.MockTransport(respond))
    try:
        with pytest.raises(ExternalServiceError, match="page limit"):
            await client.read(provider="outlook", access_token=TOKEN, thread_id="t", not_before=NOW)
        assert requests == 5
    finally:
        await client.aclose()


@pytest.mark.parametrize("variant", ["wrong_thread", "sent", "draft", "headers", "too_many"])
async def test_graph_checks_thread_and_bounds_and_skips_sent_mail(variant: str):
    message = graph_message()
    if variant == "wrong_thread":
        message["conversationId"] = "other"
    if variant == "sent":
        message["parentFolderId"] = "sent"
    if variant == "draft":
        message["isDraft"] = True
    if variant == "headers":
        message["internetMessageHeaders"] = [
            {"name": "Message-ID", "value": "<present@example.com>"}
        ]
    pages = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal pages
        if "mailFolders" in request.url.path:
            assert "/users/shared%40example.com/" in request.url.raw_path.decode()
            return httpx.Response(200, json={"id": "sent"})
        pages += 1
        content: dict[str, object] = {"value": [message] * (300 if variant == "too_many" else 1)}
        if variant == "too_many":
            content["@odata.nextLink"] = (
                "https://graph.microsoft.com/v1.0/users/shared%40example.com/messages?$skip=300"
            )
        return httpx.Response(200, json=content)

    client = MailReplyMetadataClient(httpx.MockTransport(respond))
    try:
        if variant in ("wrong_thread", "too_many"):
            with pytest.raises(
                ExternalServiceError,
                match="another thread" if variant == "wrong_thread" else "message limit",
            ):
                await client.read(
                    provider="outlook",
                    access_token=TOKEN,
                    thread_id="t",
                    not_before=NOW,
                    mailbox="shared@example.com",
                )
        else:
            result = await client.read(
                provider="outlook",
                access_token=TOKEN,
                thread_id="t",
                not_before=NOW,
                mailbox="shared@example.com",
            )
            assert result[0].sent_or_draft == (variant in ("sent", "draft"))
            if variant == "headers":
                assert (
                    not result[0].authenticated
                    and result[0].rfc_message_id == "<present@example.com>"
                )
    finally:
        await client.aclose()


async def test_response_bytes_are_bounded(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.portals.reply_metadata.MAX_RESPONSE_BYTES", 10)
    client = MailReplyMetadataClient(
        httpx.MockTransport(lambda _: httpx.Response(200, text="x" * 11))
    )
    try:
        with pytest.raises(ExternalServiceError, match="size limit"):
            await client.read(provider="google", access_token=TOKEN, thread_id="t", not_before=NOW)
    finally:
        await client.aclose()


async def test_automatic_and_sent_gmail_are_metadata_only_non_replies():
    message = google_message()
    message["payload"] = {"headers": [{"name": "Auto-Submitted", "value": "auto-replied"}]}
    message["labelIds"] = ["SENT"]
    client = MailReplyMetadataClient(
        httpx.MockTransport(lambda _: httpx.Response(200, json={"id": "t", "messages": [message]}))
    )
    try:
        result = await client.read(
            provider="google", access_token=TOKEN, thread_id="t", not_before=NOW
        )
        assert result[0].automatic and result[0].sent_or_draft and not result[0].authenticated
    finally:
        await client.aclose()
