"""Provider cursors are opaque, source-bound and committed only after a consumed batch."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.exceptions import BadRequestError, ExternalServiceError
from app.services.integrations import delta, feeds, sheets_feed, teams_feed
from app.services.trigger_events import event_matches

pytestmark = pytest.mark.anyio
TOKEN = SecretStr("never-log")


@pytest.mark.parametrize("following", [False, True])
async def test_google_calendar_pages_establish_a_quiet_baseline(monkeypatch, following):
    call = AsyncMock(
        return_value={
            "items": [{"id": "old"}],
            "nextPageToken" if following else "nextSyncToken": "resume",
        }
    )
    monkeypatch.setattr(delta.client, "execute", call)
    read = await delta.google_calendar(TOKEN, None)
    assert not read.events
    assert read.cursor == (
        {"sync_token": "", "page_token": "resume"} if following else {"sync_token": "resume"}
    )
    if following:
        await delta.google_calendar(TOKEN, read.cursor)
        assert call.await_args.kwargs["query"]["pageToken"] == "resume"


async def test_google_calendar_reports_changes_after_sync_and_resets_expired_tokens(monkeypatch):
    call = AsyncMock(
        side_effect=[
            ExternalServiceError(message="expired", details={"status": 410}),
            {"items": [{"id": "old"}], "nextSyncToken": "fresh"},
            {"items": [{"id": "changed", "updated": "today"}, {}], "nextSyncToken": "next"},
        ]
    )
    monkeypatch.setattr(delta.client, "execute", call)
    read = await delta.google_calendar(TOKEN, {"sync_token": "expired"})
    assert not read.events
    read = await delta.google_calendar(TOKEN, read.cursor)
    assert [e.id for e in read.events] == ["calendar:changed:today"]
    assert read.cursor == {"sync_token": "next"}


@pytest.mark.parametrize("result", [{}, {"items": []}])
async def test_calendar_cannot_advance_without_both_a_list_and_resume_token(monkeypatch, result):
    monkeypatch.setattr(delta.client, "execute", AsyncMock(return_value=result))
    with pytest.raises(ExternalServiceError):
        await delta.google_calendar(TOKEN, None)


async def test_calendar_does_not_disguise_a_provider_failure_as_a_reset(monkeypatch):
    monkeypatch.setattr(
        delta.client,
        "execute",
        AsyncMock(side_effect=ExternalServiceError(message="denied", details={"status": 403})),
    )
    with pytest.raises(ExternalServiceError, match="denied"):
        await delta.google_calendar(TOKEN, {"sync_token": "old"})


@pytest.mark.parametrize(
    "teams,subject,path",
    [
        (True, "person", "/v1.0/users/person/chats/getAllMessages/delta"),
        (False, None, "/v1.0/me/calendarView/delta"),
        (False, "shared@example.com", "/v1.0/users/shared%40example.com/calendarView/delta"),
    ],
)
async def test_graph_baseline_covers_all_pages_before_emitting(monkeypatch, teams, subject, path):
    root = "https://graph.microsoft.com" + path
    call = AsyncMock(
        side_effect=[
            {"value": [{"id": "old"}], "@odata.nextLink": root + "?$skiptoken=page"},
            {"value": [{"id": "old2"}], "@odata.deltaLink": root + "?$deltatoken=one"},
            {
                "value": [{"id": "new", "lastModifiedDateTime": "now"}, {}],
                "@odata.deltaLink": root + "?$deltatoken=two",
            },
        ]
    )
    monkeypatch.setattr(delta.client, "execute", call)
    a = await delta.graph_delta(TOKEN, None, subject=subject, teams=teams)
    b = await delta.graph_delta(TOKEN, a.cursor, subject=subject, teams=teams)
    c = await delta.graph_delta(TOKEN, b.cursor, subject=subject, teams=teams)
    assert not a.events and not b.events
    assert a.cursor["baseline"] is True and b.cursor["baseline"] is False
    assert [e.id for e in c.events] == ["graph:new:now"]
    assert call.await_args_list[1].args[0].url == root + "?$skiptoken=page"


@pytest.mark.parametrize(
    "bad_link",
    [
        "https://evil.example/v1.0/me/calendarView/delta",
        "https://graph.microsoft.com/v1.0/users/other/messages/delta",
        "http://graph.microsoft.com/v1.0/me/calendarView/delta",
    ],
)
async def test_graph_refuses_cursor_retargeting_before_sending_a_bearer(monkeypatch, bad_link):
    call = AsyncMock()
    monkeypatch.setattr(delta.client, "execute", call)
    with pytest.raises(ExternalServiceError, match="outside"):
        await delta.graph_delta(TOKEN, {"link": bad_link}, subject=None, teams=False)
    call.assert_not_awaited()


@pytest.mark.parametrize(
    "result", [{}, {"value": []}, {"value": [], "@odata.deltaLink": "https://evil.example/x"}]
)
async def test_graph_refuses_incomplete_or_external_resume_positions(monkeypatch, result):
    monkeypatch.setattr(delta.client, "execute", AsyncMock(return_value=result))
    with pytest.raises(ExternalServiceError):
        await delta.graph_delta(TOKEN, None, subject=None, teams=False)


@pytest.mark.parametrize("status", [404, 410, 403])
async def test_graph_only_resets_expired_positions(monkeypatch, status):
    link = "https://graph.microsoft.com/v1.0/me/calendarView/delta"
    call = AsyncMock(
        side_effect=[
            ExternalServiceError(message="denied", details={"status": status}),
            {"value": [{"id": "old"}], "@odata.deltaLink": link},
        ]
    )
    monkeypatch.setattr(delta.client, "execute", call)
    if status == 403:
        with pytest.raises(ExternalServiceError):
            await delta.graph_delta(TOKEN, {"link": link}, subject=None, teams=False)
    else:
        assert not (
            await delta.graph_delta(TOKEN, {"link": link}, subject=None, teams=False)
        ).events


@pytest.mark.parametrize("window", ["2020-01-01T00:00:00+00:00", "invalid", "2020-01-01"])
async def test_calendar_delta_renews_its_finite_window_quietly(monkeypatch, window):
    link = "https://graph.microsoft.com/v1.0/me/calendarView/delta"
    monkeypatch.setattr(
        delta.client,
        "execute",
        AsyncMock(return_value={"value": [{"id": "old"}], "@odata.deltaLink": link}),
    )
    read = await delta.graph_delta(
        TOKEN, {"link": link, "window_end": window}, subject=None, teams=False
    )
    assert not read.events
    assert read.cursor["window_end"] != window


async def test_teams_application_feed_requires_an_explicit_subject():
    with pytest.raises(ExternalServiceError, match="user"):
        await delta.graph_delta(TOKEN, None, subject=None, teams=True)


@pytest.mark.parametrize("position", [None, "bad", "2026-01-01", 3])
async def test_teams_new_or_invalid_timestamp_is_a_quiet_baseline(monkeypatch, position):
    call = AsyncMock()
    monkeypatch.setattr(teams_feed.client, "execute", call)
    read = await teams_feed.changes(TOKEN, {"chat": position}, channels=("chat",))
    assert not read.events
    assert isinstance(read.cursor["chat"], str)
    call.assert_not_awaited()


async def test_teams_delegated_chats_page_with_the_supported_timestamp_query(monkeypatch):
    stamp = "2026-11-07T10:00:00Z"
    link = "https://graph.microsoft.com/v1.0/chats/chat/messages?$skiptoken=page"
    call = AsyncMock(
        side_effect=[
            {
                "value": [
                    {
                        "id": "one",
                        "lastModifiedDateTime": stamp,
                        "body": {"content": "hello"},
                        "mentions": [{"mentioned": {"user": {"id": "me"}}}],
                    }
                ],
                "@odata.nextLink": link,
            },
            {"value": []},
            {"id": "me"},
        ]
    )
    monkeypatch.setattr(teams_feed.client, "execute", call)
    read = await teams_feed.changes(
        TOKEN, {"chat": "2026-11-07T09:00:00+00:00"}, channels=("chat",)
    )
    assert len(read.events) == 1
    assert read.events[0].payload["mentions_me"] is True
    assert read.events[0].payload["text"] == "hello"
    assert read.cursor == {"chat": "2026-11-07T10:00:00+00:00"}
    assert call.await_args_list[0].kwargs["query"]["$orderby"] == "lastModifiedDateTime desc"
    assert call.await_args_list[1].args[0].url == link


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"value": [{"id": "bad"}]},
        {"value": [{"id": "bad", "lastModifiedDateTime": "bad"}]},
        {"value": [{"id": "bad", "lastModifiedDateTime": "2026-11-07"}]},
        {"value": [], "@odata.nextLink": "https://evil.example/x"},
    ],
)
async def test_teams_does_not_lose_events_on_invalid_provider_data(monkeypatch, response):
    monkeypatch.setattr(teams_feed.client, "execute", AsyncMock(return_value=response))
    old = {"chat": "2026-11-07T09:00:00+00:00"}
    with pytest.raises(ExternalServiceError):
        await teams_feed.changes(TOKEN, old, channels=("chat",))
    assert old == {"chat": "2026-11-07T09:00:00+00:00"}


async def test_teams_page_bound_refuses_to_skip_a_backlog(monkeypatch):
    monkeypatch.setattr(
        teams_feed.client,
        "execute",
        AsyncMock(
            return_value={
                "value": [],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/chats/chat/messages?$skiptoken=more",
            }
        ),
    )
    with pytest.raises(ExternalServiceError, match="Too many"):
        await teams_feed.changes(TOKEN, {"chat": "2026-11-07T09:00:00+00:00"}, channels=("chat",))


@pytest.mark.parametrize(
    "channels,application",
    [
        ((), False),
        (tuple(str(i) for i in range(21)), False),
        (("channel/bad",), False),
        (("chat",), True),
    ],
)
async def test_teams_refuses_unbounded_or_invalid_conversation_selection(channels, application):
    with pytest.raises(BadRequestError):
        await teams_feed.changes(
            TOKEN, None, channels=channels, application=application, subject="user"
        )


async def test_teams_channel_uses_its_own_delta_not_unsupported_list_filters(monkeypatch):
    path = "https://graph.microsoft.com/v1.0/teams/team/channels/channel/messages/delta"
    call = AsyncMock(return_value={"value": [], "@odata.deltaLink": path + "?$deltatoken=first"})
    monkeypatch.setattr(teams_feed.client, "execute", call)
    read = await teams_feed.changes(TOKEN, None, channels=("channel/team/channel",))
    assert not read.events
    assert read.cursor["channel/team/channel"]["link"] == path + "?$deltatoken=first"
    assert call.await_args.kwargs["query"] == {}


async def test_app_teams_mentions_compare_the_approved_directory_id(monkeypatch):
    user = str(uuid4())
    monkeypatch.setattr(
        delta,
        "graph_delta",
        AsyncMock(
            return_value=feeds.Changes(
                cursor={},
                events=[
                    feeds.Change(
                        id="one", payload={"mentions": [{"mentioned": {"user": {"id": user}}}]}
                    )
                ],
            )
        ),
    )
    read = await teams_feed.changes(TOKEN, {}, channels=(), application=True, subject=user)
    assert read.events[0].payload["mentions_me"] is True


async def test_new_sheet_rows_resume_in_bounded_windows_without_replaying_history(monkeypatch):
    call = AsyncMock(side_effect=[{"values": [["header"], ["old"]]}, {"values": [["new", 42]]}])
    monkeypatch.setattr(sheets_feed.client, "execute", call)
    first = await sheets_feed.rows_since(TOKEN, None, spreadsheet_id="book", sheet_name="O'Brien")
    assert not first.events and first.cursor == {"last_row": 2}
    next_read = await sheets_feed.rows_since(
        TOKEN, first.cursor, spreadsheet_id="book", sheet_name="O'Brien"
    )
    assert next_read.events[0].payload == {
        "spreadsheet_id": "book",
        "sheet_name": "O'Brien",
        "row": 3,
        "values": ["new", 42],
    }
    assert next_read.cursor == {"last_row": 3}
    assert "A3%3AZZ102" in call.await_args.args[0].url
    assert sheets_feed.sheet_key("a", "b") != sheets_feed.sheet_key("ab", "")


async def test_malformed_sheet_data_cannot_advance_the_cursor(monkeypatch):
    monkeypatch.setattr(sheets_feed.client, "execute", AsyncMock(return_value={"values": {}}))
    with pytest.raises(ExternalServiceError):
        await sheets_feed.rows_since(
            TOKEN, {"last_row": 2}, spreadsheet_id="book", sheet_name="Sheet1"
        )


@pytest.mark.parametrize("source", ["slack", "teams", "imap_mail"])
@pytest.mark.parametrize(
    "config,expected",
    [
        ({}, True),
        ({"channels": ["other"]}, False),
        ({"channels": ["here"]}, True),
        ({"mentions_only": True}, False),
        ({"direct_only": True}, False),
        ({"contains": "HELLO"}, True),
        ({"contains": "absent"}, False),
    ],
)
async def test_native_trigger_filters_never_fire_on_an_unmatched_event(source, config, expected):
    assert (
        event_matches(
            source, headers={}, payload={"channel": "here", "text": "hello there"}, config=config
        )
        is expected
    )


async def test_sheet_triggers_cannot_cross_spreadsheets():
    assert event_matches(
        "google_sheets",
        headers={},
        payload={"spreadsheet_id": "book", "sheet_name": "Sheet1"},
        config={"spreadsheet_id": "book"},
    )
    assert not event_matches(
        "google_sheets",
        headers={},
        payload={"spreadsheet_id": "other", "sheet_name": "Sheet1"},
        config={"spreadsheet_id": "book"},
    )


async def test_teams_ignores_old_and_nonmessage_entries_without_advancing(monkeypatch):
    monkeypatch.setattr(
        teams_feed.client,
        "execute",
        AsyncMock(
            return_value={
                "value": [
                    "not-message",
                    {},
                    {"id": "old", "lastModifiedDateTime": "2026-11-07T08:00:00Z"},
                ]
            }
        ),
    )
    prior = {"chat": "2026-11-07T09:00:00+00:00"}
    read = await teams_feed.changes(TOKEN, prior, channels=("chat",))
    assert not read.events and read.cursor == prior


async def test_teams_cannot_classify_mentions_without_a_subject_identity(monkeypatch):
    monkeypatch.setattr(
        teams_feed.client,
        "execute",
        AsyncMock(
            side_effect=[
                {"value": [{"id": "new", "lastModifiedDateTime": "2026-11-07T10:00:00Z"}]},
                {},
            ]
        ),
    )
    with pytest.raises(ExternalServiceError, match="identify"):
        await teams_feed.changes(TOKEN, {"chat": "2026-11-07T09:00:00+00:00"}, channels=("chat",))


async def test_graph_cursor_accepts_equivalent_encoded_channel_ids_without_widening_the_path(
    monkeypatch,
):
    path = "/v1.0/teams/team/channels/19%3Achannel%40thread.tacv2/messages/delta"
    resume = "https://graph.microsoft.com/v1.0/teams/team/channels/19:channel@thread.tacv2/messages/delta?$deltatoken=opaque"
    monkeypatch.setattr(
        delta.client, "execute", AsyncMock(return_value={"value": [], "@odata.deltaLink": resume})
    )
    read = await delta.read_graph_delta(TOKEN, None, path=path)
    assert read.cursor["link"] == resume
    assert not read.events
    with pytest.raises(ExternalServiceError):
        await delta.read_graph_delta(
            TOKEN, {"link": resume.replace("19:channel@thread.tacv2", "other")}, path=path
        )
