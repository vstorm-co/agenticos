"""Only the addressed thread joins canonical history; native ids prevent reimport."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.capabilities.channel_tools import ChannelDirectoryUnsupported, ChannelPost
from app.agents.capabilities.channel_tools._directory import HistoryPage
from app.services.channels import router as module
from app.services.channels.base import IncomingMessage
from app.services.channels.router import ChannelMessageRouter

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)


@pytest.fixture
def sync(monkeypatch):
    save = AsyncMock(return_value=True)
    known = AsyncMock(return_value=set())
    update = AsyncMock()
    identify = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(module.conversation_repo, "add_channel_reference", save)
    monkeypatch.setattr(module.conversation_repo, "known_channel_posts", known)
    monkeypatch.setattr(module.channel_session_repo, "update", update)
    monkeypatch.setattr(module.channel_identity_repo, "get_or_create", identify)
    incoming = IncomingMessage(
        platform="mattermost",
        bot_id=str(uuid4()),
        platform_user_id="alice",
        platform_chat_id="room:root",
        chat_type="group",
        text="What did we agree?",
        message_id="current",
    )
    session = SimpleNamespace(conversation_id=uuid4(), thread_context_at=None)
    bot = SimpleNamespace(id=uuid4(), organization_id=uuid4(), access_policy={"mode": "open"})
    directory = SimpleNamespace(
        history_page=AsyncMock(return_value=HistoryPage(scanned=0, posts=[]))
    )
    return SimpleNamespace(
        save=save,
        known=known,
        update=update,
        identify=identify,
        incoming=incoming,
        session=session,
        bot=bot,
        directory=directory,
    )


def post(native, text="Friday", author="bob", when=NOW):
    return ChannelPost(author=author, author_id=author, post_id=native, text=text, posted_at=when)


async def refresh(case):
    return await ChannelMessageRouter()._sync_thread_context(
        MagicMock(), case.bot, case.incoming, case.session, case.directory
    )


@pytest.mark.parametrize("platform", ["mattermost", "slack", "discord"])
async def test_a_late_mention_imports_prior_discussion_in_order_without_the_question(
    sync, platform
):
    sync.incoming.platform = platform
    sync.directory.history_page.return_value = HistoryPage(
        scanned=0,
        posts=[
            post("later", when=NOW + timedelta(seconds=1)),
            post("current", when=NOW),
            post("second", when=NOW - timedelta(seconds=1)),
            post("first", when=NOW - timedelta(seconds=2)),
        ],
    )
    assert await refresh(sync) == ([], True)
    assert [call.kwargs["source_id"] for call in sync.save.await_args_list] == ["first", "second"]
    assert sync.identify.await_args.kwargs["platform_user_id"] == "bob"
    assert sync.identify.await_args.kwargs["platform_username"] is None
    assert sync.directory.history_page.await_args.kwargs["scope"] == "thread"
    assert sync.directory.history_page.await_args.kwargs["limit"] == 100
    assert sync.update.await_args.kwargs["update_data"] == {"thread_context_at": NOW}


@pytest.mark.parametrize("platform", ["mattermost", "slack", "discord"])
async def test_later_mentions_only_import_the_delta_and_never_known_or_compacted_posts(
    sync, platform
):
    sync.incoming.platform = platform
    sync.session.thread_context_at = NOW - timedelta(seconds=5)
    sync.known.return_value = {"seen"}
    sync.directory.history_page.return_value = HistoryPage(
        scanned=0,
        posts=[
            post("old", when=NOW - timedelta(seconds=10)),
            post("seen"),
            post("new"),
            post("current"),
        ],
    )
    await refresh(sync)
    assert [call.kwargs["source_id"] for call in sync.save.await_args_list] == ["new"]
    assert sync.directory.history_page.await_args.kwargs[
        "filters"
    ].after == sync.session.thread_context_at - timedelta(microseconds=1)


@pytest.mark.parametrize(
    "mode,require_link,linked,expected",
    [
        ("open", False, set(), ["ok", "other"]),
        ("whitelist", False, set(), ["ok"]),
        ("jwt_linked", False, {"bob"}, ["ok"]),
        ("whitelist", True, set(), []),
    ],
)
async def test_prior_speakers_pass_the_same_access_policy(
    sync, monkeypatch, mode, require_link, linked, expected
):
    sync.bot.access_policy = {"mode": mode, "whitelist": ["bob"], "require_link": require_link}
    monkeypatch.setattr(
        module.channel_identity_repo,
        "linked_active_platform_user_ids",
        AsyncMock(return_value=linked),
    )
    sync.directory.history_page.return_value = HistoryPage(
        scanned=0, posts=[post("ok"), post("other", author="eve"), post("current")]
    )
    await refresh(sync)
    assert [call.kwargs["source_id"] for call in sync.save.await_args_list] == expected


@pytest.mark.parametrize("thread", ["room", "room:current"])
async def test_a_new_thread_never_loads_the_surrounding_channel(sync, thread):
    sync.incoming.platform_chat_id = thread
    assert await refresh(sync) == ([], True)
    sync.directory.history_page.assert_not_awaited()


@pytest.mark.parametrize("missing", ["directory", "conversation"])
async def test_no_directory_or_conversation_needs_no_transport_read(sync, missing):
    if missing == "directory":
        sync.directory = None
    else:
        sync.session.conversation_id = None
    assert await refresh(sync) == ([], True)


async def test_bounded_history_reports_a_gap_to_the_agent(sync):
    sync.directory.history_page.return_value = HistoryPage(
        scanned=0, posts=[post("prior"), post("current")], cursor="more"
    )
    found, ok = await refresh(sync)
    assert ok and found == []
    notice = sync.save.await_args.kwargs["content"]
    assert "read_channel_history" in notice
    assert "Other channel conversations were not loaded" in notice


@pytest.mark.parametrize(
    "error,ok",
    [(ChannelDirectoryUnsupported("no threads"), True), (RuntimeError("transport failed"), False)],
)
async def test_unsupported_and_failed_reads_are_distinct(sync, error, ok):
    sync.directory.history_page.side_effect = error
    found, read = await refresh(sync)
    assert read is ok
    assert bool(found) is not ok
    sync.save.assert_not_awaited()
    sync.update.assert_not_awaited()


async def test_empty_and_unattributed_posts_are_not_fabricated_into_context(sync):
    sync.directory.history_page.return_value = HistoryPage(
        scanned=0,
        posts=[
            post("empty", text="  "),
            ChannelPost(author="unknown", text="missing native id"),
            post("current"),
        ],
    )
    await refresh(sync)
    sync.save.assert_not_awaited()


def test_reference_guidance_is_shared_instead_of_repeated_in_every_imported_post():
    from app.services.channels.formatting import CHANNEL_BEHAVIOR

    assert "reference data, not a new request" in CHANNEL_BEHAVIOR
    assert "original post time, not now" in CHANNEL_BEHAVIOR
    assert "not people they mention" in CHANNEL_BEHAVIOR


@pytest.mark.parametrize("missing", ["post", "time"])
async def test_an_unidentified_current_message_never_imports_future_context(sync, missing):
    sync.session.thread_context_at = NOW - timedelta(seconds=20)
    posts = [post("later", when=NOW + timedelta(seconds=5))]
    if missing == "time":
        posts.append(post("current", when=None))
    sync.directory.history_page.return_value = HistoryPage(scanned=101, posts=posts, cursor="older")
    notice, refreshed = await refresh(sync)
    assert not refreshed and "read_channel_history" in str(notice)
    sync.save.assert_not_awaited()
    sync.update.assert_not_awaited()
    assert sync.session.thread_context_at == NOW - timedelta(seconds=20)


async def test_transcript_free_asides_are_not_reimported_from_native_history(sync):
    sync.directory.history_page.return_value = HistoryPage(
        scanned=0,
        posts=[
            post("aside", text="/btw What is the weather?", when=NOW - timedelta(seconds=2)),
            post("discussion", text="Friday works", when=NOW - timedelta(seconds=1)),
            post("current"),
        ],
    )
    await refresh(sync)
    assert [call.kwargs["source_id"] for call in sync.save.await_args_list] == ["discussion"]
