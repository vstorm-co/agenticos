"""Bound archive queries keep destination, filters and paging together."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import ValidationError

from app.agents.capabilities.channel_tools._directory import (
    ChannelDirectoryUnsupported,
    ChannelPost,
    HistoryPage,
    HistoryQuery,
)
from app.services.channels.directory import BoundChannelDirectory
from app.services.channels.mattermost import MattermostAdapter
from app.services.channels.slack import SlackAdapter
from app.services.channels.telegram import TelegramAdapter
from tests.test_channel_tools import call

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 11, 13, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    "changes",
    [
        {"channel_id": "elsewhere"},
        {"thread_id": "other-thread"},
        {"api_base_url": "https://other.example"},
        {"bot_token": "other-token"},
    ],
)
@pytest.mark.security
async def test_a_cursor_cannot_move_to_another_destination(changes: dict[str, str]) -> None:
    adapter = MattermostAdapter()
    directory = BoundChannelDirectory(adapter, "secret", "room", thread_id="thread")
    native = AsyncMock(return_value=HistoryPage((), 20, "native-next"))
    with patch.object(adapter, "channel_history_page", native):
        first = await directory.history_page(limit=20, scope="thread", filters=HistoryQuery())
        with pytest.raises(ChannelDirectoryUnsupported, match="different filters"):
            await replace(directory, **changes).history_page(
                limit=20, scope="thread", filters=HistoryQuery(cursor=first.cursor)
            )
    assert native.await_count == 1


@pytest.mark.security
@pytest.mark.parametrize("change", ["query", "author", "window", "limit", "scope", "tamper"])
async def test_a_cursor_cannot_change_the_query(change: str) -> None:
    adapter = MattermostAdapter()
    directory = BoundChannelDirectory(adapter, "secret", "room", thread_id="thread")
    native = AsyncMock(return_value=HistoryPage((), 20, "native-next"))
    with patch.object(adapter, "channel_history_page", native):
        first = await directory.history_page(limit=20, scope="thread", filters=HistoryQuery())
        assert first.cursor is not None
        filters = HistoryQuery(cursor=first.cursor)
        if change == "query":
            filters = filters.model_copy(update={"query": "different"})
        if change == "author":
            filters = filters.model_copy(update={"author_id": "other"})
        if change == "window":
            filters = filters.model_copy(update={"before": NOW})
        if change == "tamper":
            filters = filters.model_copy(update={"cursor": first.cursor + "0"})
        with pytest.raises(ChannelDirectoryUnsupported):
            await directory.history_page(
                limit=10 if change == "limit" else 20,
                scope="channel" if change == "scope" else "thread",
                filters=filters,
            )
    assert native.await_count == 1


async def test_a_valid_cursor_passes_only_the_native_position_and_ends() -> None:
    adapter = MattermostAdapter()
    directory = BoundChannelDirectory(adapter, "secret", "room")
    native = AsyncMock(side_effect=[HistoryPage((), 20, "next"), HistoryPage((), 3)])
    with patch.object(adapter, "channel_history_page", native):
        first = await directory.history_page(limit=20, scope="channel", filters=HistoryQuery())
        last = await directory.history_page(
            limit=20, scope="channel", filters=HistoryQuery(cursor=first.cursor)
        )
    assert native.await_args.kwargs["filters"].cursor == "next"
    assert last.cursor is None


@pytest.mark.parametrize("cursor", ["broken", ".signature", "%%%.*", "_w==.signature"])
async def test_an_unreadable_cursor_is_a_controlled_refusal(cursor: str) -> None:
    directory = BoundChannelDirectory(MattermostAdapter(), "secret", "room")
    with pytest.raises(ChannelDirectoryUnsupported, match="invalid"):
        await directory.history_page(limit=20, scope="channel", filters=HistoryQuery(cursor=cursor))


def test_filters_require_an_ordered_aware_window() -> None:
    with pytest.raises(ValidationError):
        HistoryQuery(after=NOW, before=NOW)
    with pytest.raises(ValidationError):
        HistoryQuery(before=NOW.replace(tzinfo=None))
    filters = HistoryQuery(query="report", author_id="u", after=NOW)
    assert not filters.includes(ChannelPost("u", "REPORT", NOW, author_id="u"))
    assert not filters.includes(ChannelPost("u", "REPORT", author_id="u"))
    assert filters.includes(ChannelPost("u", "REPORT", NOW.replace(hour=13), author_id="u"))


async def test_no_matches_can_still_offer_an_older_page() -> None:
    directory = BoundChannelDirectory(MattermostAdapter(), "secret", "room")
    with patch.object(
        MattermostAdapter,
        "channel_history_page",
        AsyncMock(return_value=HistoryPage((), 20, "older")),
    ):
        output = await call(directory, "read_channel_history", query="invoice")
    assert "0 matches from 20 scanned" in output
    assert "Continue with cursor:" in output
    assert "secret" not in output


async def test_unsupported_paging_and_invalid_windows_do_not_end_the_run() -> None:
    directory = BoundChannelDirectory(TelegramAdapter(), "secret", "room")
    assert "does not support" in await call(directory, "read_channel_history", cursor="start")
    assert "Invalid history filters" in await call(
        directory, "read_channel_history", after=NOW.isoformat(), before=NOW.isoformat()
    )


def _post(
    channel: str, text: str, *, hour: int = 11, root: str = "", kind: str = ""
) -> dict[str, str | int]:
    return {
        "channel_id": channel,
        "user_id": "u",
        "message": text,
        "create_at": int(NOW.replace(hour=hour).timestamp() * 1000),
        "root_id": root,
        "type": kind,
    }


@pytest.mark.security
async def test_mattermost_search_cannot_return_other_rooms_or_interpret_query_operators() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/channels/room"):
            return httpx.Response(200, json={"name": "sales", "team_id": "team"})
        return httpx.Response(
            200,
            json={
                "order": ["foreign", "match", "old"],
                "posts": {
                    "foreign": _post("other", "report in:other", hour=11),
                    "match": _post("room", "report in:other", hour=10),
                    "old": _post("room", "report in:other", hour=9),
                },
            },
        )

    adapter = MattermostAdapter()
    with patch.object(
        adapter, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond))
    ):
        page = await adapter.channel_history_page(
            "token",
            "room",
            api_base_url="https://mm.example",
            limit=1,
            thread_id=None,
            filters=HistoryQuery(query="report in:other", before=NOW),
        )
    assert [post.post_id for post in page.posts] == ["match"]
    assert page.cursor == "match"
    body = json.loads(requests[-1].content)
    assert body["terms"].startswith('in:sales "report" "in" "other"')
    assert "in:other" not in body["terms"]
    assert "page" not in body


async def test_mattermost_thread_and_native_pages_filter_exactly() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "order": ["anchor", "system", "match", "wrong-thread"],
                "posts": {
                    "anchor": _post("room", "report", root="thread"),
                    "system": _post("room", "report", root="thread", kind="system_join_channel"),
                    "match": _post("room", "report", hour=10, root="thread"),
                    "wrong-thread": _post("room", "report", root="other"),
                },
            },
        )

    adapter = MattermostAdapter()
    with patch.object(
        adapter, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond))
    ):
        page = await adapter.channel_history_page(
            "token",
            "room",
            api_base_url="https://mm.example",
            limit=2,
            thread_id="thread",
            filters=HistoryQuery(query="report", cursor="anchor"),
        )
        native = await adapter.channel_history_page(
            "token",
            "room",
            api_base_url="https://mm.example",
            limit=2,
            thread_id=None,
            filters=HistoryQuery(cursor="anchor", after=NOW),
        )
    assert [post.post_id for post in page.posts] == ["match"]
    assert page.cursor == "match"
    assert requests[0].url.params["fromPost"] == "anchor"
    assert requests[0].url.params["perPage"] == "3"
    assert requests[1].url.params["before"] == "anchor"
    assert native.posts == () and native.cursor is None


@pytest.mark.parametrize("thread", [None, "thread"])
async def test_slack_uses_native_time_bounds_and_preserves_an_empty_page_cursor(
    thread: str | None,
) -> None:
    client = MagicMock()
    response = {
        "messages": [{"ts": str(NOW.timestamp()), "user": "u", "text": "other"}],
        "response_metadata": {"next_cursor": "next"},
    }
    client.conversations_history = AsyncMock(return_value=response)
    client.conversations_replies = AsyncMock(return_value=response)
    adapter = SlackAdapter()
    with patch.object(adapter, "_web", return_value=client):
        page = await adapter.channel_history_page(
            "token",
            "room",
            api_base_url=None,
            limit=20,
            thread_id=thread,
            filters=HistoryQuery(
                query="invoice",
                after=NOW.replace(hour=1),
                before=NOW.replace(hour=13),
                cursor="position",
            ),
        )
    method = client.conversations_replies if thread else client.conversations_history
    assert method.await_args.kwargs["channel"] == "room"
    assert method.await_args.kwargs["oldest"] == str(NOW.replace(hour=1).timestamp())
    assert method.await_args.kwargs["latest"] == str(NOW.replace(hour=13).timestamp())
    assert method.await_args.kwargs["cursor"] == "position"
    assert page.posts == () and page.cursor == "next"


@pytest.mark.parametrize(
    "query,team,message",
    [
        ("report", "", "direct conversation"),
        ("!!!", "team", "letter or number"),
    ],
)
async def test_mattermost_unavailable_search_is_explicit(
    query: str, team: str, message: str
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "room", "team_id": team})

    adapter = MattermostAdapter()
    with (
        patch.object(
            adapter, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond))
        ),
        pytest.raises(ChannelDirectoryUnsupported, match=message),
    ):
        await adapter.channel_history_page(
            "token",
            "room",
            api_base_url="https://mm.example",
            limit=20,
            thread_id=None,
            filters=HistoryQuery(query=query),
        )


async def test_mattermost_time_search_and_thread_anchor_do_not_round_the_actual_filter() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/channels/room"):
            return httpx.Response(200, json={"name": "room", "team_id": "team"})
        return httpx.Response(
            200,
            json={
                "order": ["match", "boundary"],
                "posts": {
                    "match": _post("room", "REPORT", hour=11, root="thread"),
                    "boundary": _post("room", "REPORT", hour=10, root="thread"),
                },
            },
        )

    adapter = MattermostAdapter()
    with patch.object(
        adapter, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond))
    ):
        page = await adapter.channel_history_page(
            "token",
            "room",
            api_base_url="https://mm.example",
            limit=20,
            thread_id=None,
            filters=HistoryQuery(
                query="report", after=NOW.replace(hour=10), before=NOW, author_id="u"
            ),
        )
        thread = await adapter.channel_history_page(
            "token",
            "room",
            api_base_url="https://mm.example",
            limit=20,
            thread_id="thread",
            filters=HistoryQuery(before=NOW, author_id="different"),
        )
    assert [post.post_id for post in page.posts] == ["match"]
    assert thread.posts == ()
    assert requests[-1].url.params["fromCreateAt"] == str(int(NOW.timestamp() * 1000))
    assert "after:2026-11-12" in json.loads(requests[1].content)["terms"]


async def test_paged_tool_formats_messages_and_masks_provider_failures() -> None:
    adapter = MattermostAdapter()
    directory = BoundChannelDirectory(adapter, "secret", "room")
    with patch.object(
        adapter,
        "channel_history_page",
        AsyncMock(return_value=HistoryPage((ChannelPost("Ada", "a" * 600, NOW),), 1)),
    ):
        output = await call(directory, "read_channel_history", cursor="start")
    assert "Ada" in output and "End of the available" in output
    assert "a" * 501 not in output
    with patch.object(
        adapter, "channel_history_page", AsyncMock(side_effect=RuntimeError("PRIVATE TOKEN"))
    ):
        output = await call(directory, "read_channel_history", cursor="start")
    assert "PRIVATE TOKEN" not in output and "refused" in output


async def test_native_first_page_can_be_empty_without_claiming_a_match() -> None:
    adapter = MattermostAdapter()
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"order": [], "posts": {}})

    with patch.object(
        adapter, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond))
    ):
        page = await adapter.channel_history_page(
            "token",
            "room",
            api_base_url="https://mm.example",
            limit=20,
            thread_id=None,
            filters=HistoryQuery(),
        )
    assert page.posts == () and page.cursor is None and page.scanned == 0
    assert "before" not in requests[0].url.params


async def test_slack_first_page_sorts_messages_and_skips_housekeeping() -> None:
    client = MagicMock(
        conversations_history=AsyncMock(
            return_value={
                "messages": [
                    {"ts": "2.000", "user": "u", "text": "second"},
                    {"ts": "1.000", "bot_id": "b", "text": "first"},
                    {"ts": "3.000", "subtype": "channel_join", "text": "joined"},
                ]
            }
        )
    )
    adapter = SlackAdapter()
    with patch.object(adapter, "_web", return_value=client):
        page = await adapter.channel_history_page(
            "token", "room", api_base_url=None, limit=20, thread_id=None, filters=HistoryQuery()
        )
    assert [post.text for post in page.posts] == ["first", "second"]
    assert page.posts[0].author == "b" and page.posts[0].author_id is None
    assert page.cursor is None


async def test_mattermost_repeated_thread_root_does_not_end_paging_early() -> None:
    adapter = MattermostAdapter()
    root = _post("room", "root", hour=1)
    replies = {
        "a": _post("room", "first", hour=9, root="thread"),
        "b": _post("room", "second", hour=10, root="thread"),
        "c": _post("room", "third", hour=11, root="thread"),
    }

    def respond(request: httpx.Request) -> httpx.Response:
        anchor = request.url.params.get("fromPost")
        ids = ["c", "b"] if anchor is None else (["b", "a"] if anchor == "b" else ["a"])
        return httpx.Response(
            200,
            json={
                "order": ["thread", *ids],
                "posts": {"thread": root, **{key: replies[key] for key in ids}},
            },
        )

    with patch.object(
        adapter, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond))
    ):
        first = await adapter.channel_history_page(
            "token",
            "room",
            api_base_url="https://mm.example",
            limit=2,
            thread_id="thread",
            filters=HistoryQuery(),
        )
        second = await adapter.channel_history_page(
            "token",
            "room",
            api_base_url="https://mm.example",
            limit=2,
            thread_id="thread",
            filters=HistoryQuery(cursor=first.cursor),
        )
        last = await adapter.channel_history_page(
            "token",
            "room",
            api_base_url="https://mm.example",
            limit=2,
            thread_id="thread",
            filters=HistoryQuery(cursor=second.cursor),
        )
    assert [post.post_id for post in first.posts] == ["b", "c"]
    assert [post.post_id for post in second.posts] == ["a"]
    assert [post.post_id for post in last.posts] == ["thread"]
    assert last.cursor is None
