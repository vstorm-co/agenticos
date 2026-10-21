"""`/embed/{public_key}/voice/ws`: a visitor's call, admitted as the embed's own socket (#54).

The handler is called directly, as the embed socket's own rate test does: the
async client speaks no WebSocket, and `TestClient` would run the lifespan.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes.v1.embed import embed_voice_socket
from app.core.exceptions import BadRequestError
from app.services import rate_limit
from app.services.agent_embed import EmbedDenied

pytestmark = [pytest.mark.anyio, pytest.mark.security]
_R = "app.api.routes.v1.embed"


@pytest.fixture(autouse=True)
def _no_limiter():
    rate_limit.configure(None)
    yield
    rate_limit.configure(None)


@asynccontextmanager
async def _db():
    yield MagicMock()


def _socket(origin: str | None = "https://acme.test") -> MagicMock:
    socket = MagicMock(
        headers={} if origin is None else {"origin": origin},
        client=MagicMock(host="203.0.113.9"),
    )
    socket.accept = AsyncMock()
    socket.close = AsyncMock()
    return socket


async def test_a_caller_past_the_call_limit_is_closed_4029_before_the_key_is_read():
    used = MagicMock(count_in_window=AsyncMock(return_value=999))
    rate_limit.configure(used)
    socket = _socket()
    with patch(f"{_R}.AgentEmbedService.admit_voice", AsyncMock()) as admit:
        await embed_voice_socket(socket, public_key="k", token=None, visitor=None)

    assert socket.close.await_args.kwargs["code"] == 4029
    admit.assert_not_awaited()


@pytest.mark.parametrize(
    "refusal",
    [EmbedDenied("voice calls are off"), BadRequestError(message="A visitor key is required")],
)
async def test_every_refusal_about_the_embed_closes_4003(refusal):
    socket = _socket()
    with (
        patch(f"{_R}.get_db_context", _db),
        patch(f"{_R}.AgentEmbedService.admit_voice", AsyncMock(side_effect=refusal)),
        patch(f"{_R}.VoiceCallSession") as session_cls,
    ):
        await embed_voice_socket(socket, public_key="k", token=None, visitor=None)

    socket.accept.assert_awaited_once()
    assert socket.close.await_args.kwargs["code"] == 4003
    session_cls.assert_not_called()


async def test_an_admitted_page_visitor_is_handed_to_the_call_as_an_anonymous_caller():
    socket = _socket("http://localhost:3000")
    admission = SimpleNamespace(embed=SimpleNamespace(kind="page"), visitor=None)
    caller = SimpleNamespace(anonymous=True)
    with (
        patch(f"{_R}.get_db_context", _db),
        patch(f"{_R}.AgentEmbedService.admit_voice", AsyncMock(return_value=admission)) as admit,
        patch(f"{_R}.embed_voice_caller", AsyncMock(return_value=caller)) as make_caller,
        patch(f"{_R}.VoiceCallSession") as session_cls,
    ):
        session_cls.return_value.run = AsyncMock()
        await embed_voice_socket(socket, public_key="k", token="t", visitor="a" * 32)

    assert admit.await_args.kwargs == {
        "origin": "http://localhost:3000",
        "token": "t",
        "visitor_key": "a" * 32,
    }
    assert make_caller.await_args.kwargs == {"visitor_key": "a" * 32}
    assert session_cls.call_args.args == (socket, caller)
    socket.close.assert_not_awaited()
    session_cls.return_value.run.assert_awaited_once()


async def test_a_visitor_key_that_is_not_one_the_page_mints_is_dropped():
    """`visitor=1` would be a thread anybody can walk into; only 128 random bits are a key."""
    socket = _socket()
    with (
        patch(f"{_R}.get_db_context", _db),
        patch(
            f"{_R}.AgentEmbedService.admit_voice", AsyncMock(side_effect=EmbedDenied("x"))
        ) as admit,
    ):
        await embed_voice_socket(socket, public_key="k", token=None, visitor="1")

    assert admit.await_args.kwargs["visitor_key"] is None


async def test_a_signed_in_visitor_past_their_own_calls_is_closed_4029():
    """Counted on the token's subject once it is verified, before any call is set up."""
    socket = _socket()
    admission = SimpleNamespace(embed=SimpleNamespace(kind="widget"), visitor="customer-42")
    refused = AsyncMock(return_value=SimpleNamespace(allowed=False))
    with (
        patch(f"{_R}.get_db_context", _db),
        patch(f"{_R}.AgentEmbedService.admit_voice", AsyncMock(return_value=admission)),
        patch(f"{_R}.rate_limit.embed_voice_visitor_allowed", refused),
        patch(f"{_R}.embed_voice_caller", AsyncMock()) as make_caller,
        patch(f"{_R}.VoiceCallSession") as session_cls,
    ):
        await embed_voice_socket(socket, public_key="k", token="t", visitor=None)

    assert refused.await_args.kwargs == {"public_key": "k", "visitor": "customer-42"}
    assert socket.close.await_args.kwargs["code"] == 4029
    make_caller.assert_not_awaited()
    session_cls.assert_not_called()


async def test_a_signed_in_visitor_within_their_calls_is_put_through():
    socket = _socket()
    admission = SimpleNamespace(embed=SimpleNamespace(kind="widget"), visitor="customer-42")
    with (
        patch(f"{_R}.get_db_context", _db),
        patch(f"{_R}.AgentEmbedService.admit_voice", AsyncMock(return_value=admission)),
        patch(
            f"{_R}.rate_limit.embed_voice_visitor_allowed",
            AsyncMock(return_value=SimpleNamespace(allowed=True)),
        ),
        patch(f"{_R}.embed_voice_caller", AsyncMock(return_value=SimpleNamespace())),
        patch(f"{_R}.VoiceCallSession") as session_cls,
    ):
        session_cls.return_value.run = AsyncMock()
        await embed_voice_socket(socket, public_key="k", token="t", visitor=None)

    socket.close.assert_not_awaited()
    session_cls.return_value.run.assert_awaited_once()


async def test_a_refused_token_spends_nothing_of_the_links_minute():
    """Codex on #2204: counted before admission, anybody with the public key could
    spend the link's calls for every signed-in visitor without a valid token."""
    socket = _socket()
    link = AsyncMock()
    with (
        patch(f"{_R}.get_db_context", _db),
        patch(f"{_R}.AgentEmbedService.admit_voice", AsyncMock(side_effect=EmbedDenied("bad"))),
        patch(f"{_R}.rate_limit.embed_voice_link_allowed", link),
    ):
        await embed_voice_socket(socket, public_key="k", token="forged", visitor=None)

    assert socket.close.await_args.kwargs["code"] == 4003
    link.assert_not_awaited()


async def test_an_admitted_visitor_past_the_links_minute_is_closed_4029():
    socket = _socket()
    admission = SimpleNamespace(embed=SimpleNamespace(kind="page"), visitor=None)
    link = AsyncMock(return_value=SimpleNamespace(allowed=False))
    with (
        patch(f"{_R}.get_db_context", _db),
        patch(f"{_R}.AgentEmbedService.admit_voice", AsyncMock(return_value=admission)),
        patch(f"{_R}.rate_limit.embed_voice_link_allowed", link),
        patch(f"{_R}.VoiceCallSession") as session_cls,
    ):
        await embed_voice_socket(socket, public_key="k", token=None, visitor=None)

    assert link.await_args.kwargs == {"public_key": "k"}
    assert socket.close.await_args.kwargs["code"] == 4029
    session_cls.assert_not_called()
