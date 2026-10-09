"""The shared Microsoft Graph client, where it differs from SharePoint's use of it.

`tests/test_sharepoint_connector.py` drives the client through an app
registration, end to end; what is left here is the delegated token a connected
account spends and the refusal a caller sees when it does not word its own.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from app.core.exceptions import BadRequestError
from app.services.microsoft_graph import GRAPH, DelegatedToken, GraphClient

pytestmark = pytest.mark.anyio

TOKEN = "member-access-token-123"


def _client(handler: httpx.MockTransport) -> GraphClient:
    return GraphClient(
        DelegatedToken(access_token=SecretStr(TOKEN)),
        httpx.AsyncClient(transport=handler),
        backoff=0.0,
    )


async def test_a_delegated_token_is_sent_to_graph_as_given_with_no_sign_in() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "me", "displayName": "Jane"})

    graph = _client(httpx.MockTransport(handler))
    try:
        body = await graph.get(f"{GRAPH}/me", what="your profile")
    finally:
        await graph.aclose()

    assert body == {"id": "me", "displayName": "Jane"}
    assert [request.url.host for request in requests] == ["graph.microsoft.com"]
    assert requests[0].headers["authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {}, "did not accept the token for your profile"),
        (
            403,
            {"error": {"code": "accessDenied"}},
            r"denied access to your profile \(accessDenied\)",
        ),
        (403, {}, r"denied access to your profile \(HTTP 403\)"),
    ],
)
async def test_a_refusal_is_worded_neutrally_unless_the_caller_words_it(
    status: int, body: dict[str, object], expected: str
) -> None:
    graph = _client(httpx.MockTransport(lambda _: httpx.Response(status, json=body)))
    try:
        with pytest.raises(BadRequestError, match=expected):
            await graph.get(f"{GRAPH}/me", what="your profile")
    finally:
        await graph.aclose()
