"""Slack sync reads only selected conversations and notices edits and replies."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError, ExternalServiceError
from app.core.secret_kinds import ApiKeySecret
from app.services.integrations import AccountToken
from app.services.rag.connectors import RemoteFile, slack

pytestmark = pytest.mark.anyio
CONFIG = {"connection_id": str(uuid4()), "channels": ["C1"]}


def token(provider="slack"):
    return AccountToken(api_key="private-token", connection_id=uuid4(), provider=provider)


def remote(identifier="C1:1.0"):
    return RemoteFile(
        id=identifier, name="thread.md", mime_type="text/markdown", source_path="slack://thread"
    )


async def test_source_config_requires_an_account_and_selected_conversations():
    connector = slack.SlackConnector()
    assert await connector.validate_config(CONFIG) is None
    error = await connector.validate_config({"connection_id": str(uuid4()), "channels": []})
    assert error.field == "channels"


@pytest.mark.parametrize(
    "credential", [None, ApiKeySecret(api_key="private-token"), token("google")]
)
async def test_slack_never_spends_an_unrelated_vault_credential(credential):
    with pytest.raises(BadRequestError):
        await slack.SlackConnector().list_files(CONFIG, credential)


async def test_selected_threads_are_unique_and_replies_or_edits_change_their_modified_time(
    monkeypatch,
):
    read = AsyncMock(
        side_effect=[
            {
                "messages": [
                    {"ts": "1.0", "latest_reply": "4.0", "edited": {"ts": "3.0"}},
                    {"ts": "2.0", "thread_ts": "1.0"},
                ],
                "response_metadata": {"next_cursor": "page2"},
            },
            {"messages": [{"ts": "5.0"}]},
        ]
    )
    monkeypatch.setattr(slack, "execute", read)
    result = await slack.SlackConnector().list_files(CONFIG, token())
    assert result.complete and [file.id for file in result.files] == ["C1:1.0", "C1:5.0"]
    assert result.files[0].modified_at.timestamp() == 4.0
    assert result.files[1].modified_at.timestamp() == 5.0
    assert read.await_args.kwargs["query"] == {"channel": "C1", "limit": "200", "cursor": "page2"}


async def test_incomplete_channel_listing_prevents_remote_deletions(monkeypatch):
    monkeypatch.setattr(slack, "_MAX_PAGES", 1)
    monkeypatch.setattr(
        slack,
        "execute",
        AsyncMock(return_value={"messages": [], "response_metadata": {"next_cursor": "more"}}),
    )
    result = await slack.SlackConnector().list_files(CONFIG, token())
    assert not result.complete and result.problems


async def test_bad_slack_page_is_an_explicit_refusal_not_an_empty_listing(monkeypatch):
    monkeypatch.setattr(
        slack,
        "execute",
        AsyncMock(return_value={"messages": [{"ts": "bad", "text": "private message"}]}),
    )
    with pytest.raises(ExternalServiceError) as error:
        await slack.SlackConnector().list_files(CONFIG, token())
    assert "private message" not in str(error.value)


async def test_thread_fetch_stays_in_its_selected_channel_and_writes_a_markdown_document(
    monkeypatch, tmp_path
):
    read = AsyncMock(
        side_effect=[
            {
                "messages": [{"ts": "1.0", "text": "Question", "user": "U1"}],
                "response_metadata": {"next_cursor": "next"},
            },
            {"messages": [{"ts": "2.0", "text": "Answer", "user": "U2"}]},
        ]
    )
    monkeypatch.setattr(slack, "execute", read)
    path = tmp_path / "thread.md"
    await slack.SlackConnector()._fetch(remote(), path, CONFIG, token())
    assert "Question" in path.read_text() and "Answer" in path.read_text()
    assert (
        read.await_args.kwargs["query"]["channel"] == "C1"
        and read.await_args.kwargs["query"]["cursor"] == "next"
    )


@pytest.mark.parametrize("identifier", ["C2:1.0", "C1:"])
async def test_thread_fetch_refuses_a_different_conversation(monkeypatch, tmp_path, identifier):
    read = AsyncMock()
    monkeypatch.setattr(slack, "execute", read)
    with pytest.raises(BadRequestError):
        await slack.SlackConnector()._fetch(
            remote(identifier), tmp_path / "thread.md", CONFIG, token()
        )
    read.assert_not_awaited()


@pytest.mark.parametrize("failure", ["pages", "bytes"])
async def test_incomplete_or_oversized_threads_never_become_knowledge(
    monkeypatch, tmp_path, failure
):
    monkeypatch.setattr(slack, "_MAX_PAGES", 1)
    if failure == "bytes":
        monkeypatch.setattr(slack, "_MAX_TEXT_BYTES", 100)
    monkeypatch.setattr(
        slack,
        "execute",
        AsyncMock(
            return_value={
                "messages": [{"ts": "1.0", "text": "x" * 200}],
                "response_metadata": {"next_cursor": "more"},
            }
        ),
    )
    path = tmp_path / "thread.md"
    with pytest.raises(ExternalServiceError):
        await slack.SlackConnector()._fetch(remote(), path, CONFIG, token())
    assert not path.exists()
