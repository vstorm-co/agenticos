"""Each consumer advances independently, and a new Slack channel starts quietly."""

from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from app.core.exceptions import BadRequestError, ExternalServiceError
from app.services.integrations import feeds
from app.services.portals import PolledEvent, PolledEvents

pytestmark = pytest.mark.anyio


async def test_slack_baseline_does_not_read_or_emit_the_existing_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = AsyncMock()
    monkeypatch.setattr(feeds.client, "execute", call)
    baseline = await feeds.changes_since(
        "slack", SecretStr("secret"), cursor=None, channels=("C1", "C2")
    )
    assert baseline.events == []
    assert set(baseline.cursor) == {"C1", "C2"}
    call.assert_not_awaited()


async def test_slack_reads_only_after_its_cursor_and_keeps_each_consumers_input_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = AsyncMock(
        side_effect=[
            {
                "messages": [{"ts": "20", "text": "new"}],
                "response_metadata": {"next_cursor": "page2"},
                "ok": True,
            },
            {"messages": [{"ts": "15", "text": "older but new"}], "ok": True},
            {"user_id": "U1"},
        ]
    )
    monkeypatch.setattr(feeds.client, "execute", call)
    old = {"C1": "10"}
    read = await feeds.changes_since(
        "slack", SecretStr("secret"), cursor=old, channels=("C1", "C2")
    )
    assert [event.id for event in read.events] == ["slack:C1:20", "slack:C1:15"]
    assert old == {"C1": "10"}
    assert all(args.kwargs["query"]["oldest"] == "10" for args in call.await_args_list[:2])
    assert call.await_args_list[1].kwargs["query"]["cursor"] == "page2"
    assert all(args.kwargs["query"]["channel"] == "C1" for args in call.await_args_list[:2])


async def test_a_slack_backlog_over_the_page_bound_cannot_silently_advance_the_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = AsyncMock(
        return_value={"ok": True, "messages": [], "response_metadata": {"next_cursor": "more"}}
    )
    monkeypatch.setattr(feeds.client, "execute", call)
    old = {"C1": "10"}
    with pytest.raises(ExternalServiceError, match="Too many"):
        await feeds.changes_since("slack", SecretStr("secret"), cursor=old, channels=("C1",))
    assert old == {"C1": "10"}


@pytest.mark.parametrize("product,channels", [("slack", ()), ("google_docs", ())])
async def test_unsupported_feed_or_missing_channel_selection_is_a_refusal(
    product: str, channels: tuple[str, ...]
) -> None:
    with pytest.raises(BadRequestError):
        await feeds.changes_since(product, SecretStr("secret"), cursor=None, channels=channels)


@pytest.mark.parametrize("product,key", [("gmail", "google"), ("outlook_mail", "microsoft")])
async def test_mail_reuses_the_trigger_portal_adapter_and_its_resume_cursor(
    monkeypatch: pytest.MonkeyPatch, product: str, key: str
) -> None:
    adapter = AsyncMock()
    adapter.poll.return_value = PolledEvents(
        events=(PolledEvent(delivery_id="mail:42", payload={"text": "new"}),),
        cursor={"history": "43"},
    )
    monkeypatch.setattr(
        feeds, "get_adapter", lambda portal_key: adapter if portal_key == key else None
    )
    read = await feeds.changes_since(product, SecretStr("secret"), cursor={"history": "41"})
    assert read.events[0].id == "mail:42"
    assert read.cursor == {"history": "43"}
    assert adapter.poll.await_args.kwargs["cursor"] == {"history": "41"}
    if product == "outlook_mail":
        assert "|inbox" in adapter.poll.await_args.kwargs["places"]


@pytest.mark.parametrize("product", ["google_calendar", "outlook_calendar", "teams"])
async def test_calendar_and_teams_watch_dispatch_uses_the_shared_feed(monkeypatch, product):
    from app.services.integrations import delta, teams_feed

    read = AsyncMock(return_value=feeds.Changes(cursor={"resume": "here"}))
    target = delta if product != "teams" else teams_feed
    method = {
        "google_calendar": "google_calendar",
        "outlook_calendar": "graph_delta",
        "teams": "changes",
    }[product]
    monkeypatch.setattr(target, method, read)
    assert (
        await feeds.changes_since(product, SecretStr("token"), cursor=None, channels=("chat",))
    ).cursor == {"resume": "here"}
    read.assert_awaited_once()


async def test_app_outlook_mail_watch_has_an_explicit_mailbox(monkeypatch):
    read = AsyncMock(return_value=PolledEvents(events=(), cursor={"next": "here"}))
    subjects = []

    def adapter(*, subject):
        from types import SimpleNamespace

        subjects.append(subject)
        return SimpleNamespace(poll=read)

    monkeypatch.setattr("app.services.portals.outlook.OutlookPortalAdapter", adapter)
    await feeds.changes_since(
        "outlook_mail", SecretStr("token"), cursor=None, subject="shared@example.com"
    )
    assert subjects == ["shared@example.com"]


@pytest.mark.parametrize(
    "result,cursor",
    [
        ({"messages": []}, {"C": "not-time"}),
        ({"messages": [{"ts": "not-time"}]}, {"C": "10"}),
        ({"messages": [{"ts": "20"}]}, {"C": "10"}),
    ],
)
async def test_slack_invalid_cursor_timestamp_or_identity_never_advances(
    monkeypatch, result, cursor
):
    monkeypatch.setattr(feeds.client, "execute", AsyncMock(return_value=result))
    with pytest.raises((BadRequestError, ExternalServiceError)):
        await feeds.changes_since("slack", SecretStr("token"), cursor=cursor, channels=("C",))


async def test_slack_mentions_and_dm_classification_are_subject_specific(monkeypatch):
    call = AsyncMock(
        side_effect=[
            {"messages": [{"ts": "20", "text": "hello <@U1>"}, "not a message", {}]},
            {"user_id": "U1"},
        ]
    )
    monkeypatch.setattr(feeds.client, "execute", call)
    read = await feeds.changes_since(
        "slack", SecretStr("token"), cursor={"D1": "10"}, channels=("D1",)
    )
    assert (
        read.events[0].payload["mentions_me"] is True
        and read.events[0].payload["direct_message"] is True
    )
    assert read.cursor == {"D1": "20"}


async def test_slack_missing_message_list_is_a_failure(monkeypatch):
    monkeypatch.setattr(feeds.client, "execute", AsyncMock(return_value={"ok": True}))
    with pytest.raises(ExternalServiceError, match="list"):
        await feeds.changes_since("slack", SecretStr("token"), cursor={"C": "10"}, channels=("C",))
