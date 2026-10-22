"""Who is on an embed call: an anonymous visitor, under the publisher's role (#54)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.voice import embed_voice_caller

pytestmark = pytest.mark.anyio
_M = "app.services.voice.embed"


def _embed(kind: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        kind=kind,
        organization_id=uuid4(),
        owner_user_id=uuid4(),
        agent_id=uuid4(),
        name="Help",
    )


async def test_a_page_visitor_calls_into_their_own_thread_as_an_anonymous_caller():
    embed = _embed("page")
    publisher = SimpleNamespace(organization_id=embed.organization_id)
    visitor = SimpleNamespace(conversation_id=uuid4())
    with (
        patch(f"{_M}.publisher_context", AsyncMock(return_value=publisher)) as context,
        patch(f"{_M}.embed_visitor_repo.claim", AsyncMock(return_value=visitor)) as claim,
    ):
        caller = await embed_voice_caller(
            MagicMock(), SimpleNamespace(embed=embed, visitor=None), visitor_key="v" * 32
        )

    assert context.await_args.kwargs["publisher_user_id"] == embed.owner_user_id
    assert claim.await_args.kwargs == {"embed_id": embed.id, "visitor_key": "v" * 32}
    assert caller.ctx is publisher
    assert caller.anonymous and caller.surface == "embed"
    assert caller.user_id is None and caller.user_name is None and caller.auth_token is None
    assert caller.conversation_id == visitor.conversation_id
    assert caller.agent_id == embed.agent_id and caller.embed_id == embed.id
    assert caller.visitor_key == "v" * 32
    assert caller.conversation_title == "Help - voice call"
    assert caller.embed is embed


async def test_a_widget_visitor_starts_a_fresh_conversation_whatever_key_it_sends():
    embed = _embed("widget")
    with (
        patch(f"{_M}.publisher_context", AsyncMock(return_value=SimpleNamespace())),
        patch(f"{_M}.embed_visitor_repo.claim", AsyncMock()) as claim,
    ):
        caller = await embed_voice_caller(
            MagicMock(), SimpleNamespace(embed=embed, visitor="sub-1"), visitor_key="v" * 32
        )

    claim.assert_not_awaited()
    assert caller.conversation_id is None and caller.visitor_key is None
    # A `jwt` visitor's subject names the thread, as their text conversations are named.
    assert caller.conversation_title == "Help - sub-1 - voice call"
