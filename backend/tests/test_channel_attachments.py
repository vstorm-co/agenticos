"""Files across a channel, in both directions.

Inbound, the property that matters is that a bot is not the lenient edge. Anyone
in a Slack channel can drop a file on it, so it goes through exactly what the web
upload applies — and the size is checked twice, because a platform's claim about
how big a file is arrives before the bytes do.

Outbound, the property is that nothing is silently dropped. An agent told its
attachment was delivered will tell the user the same, so anything a reply cannot
carry is named in it.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai_backends import StateBackend

from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.chat_file import ChatFile
from app.services.channels.attachments import (
    MAX_OUTBOUND_BYTES,
    MAX_OUTBOUND_FILES,
    ChannelAttachmentService,
    DeliveredFiles,
    files_written,
    workspace_snapshot,
)
from app.services.channels.base import IncomingAttachment, IncomingMessage
from app.services.channels.mentions import AnsweredTurn, UnaddressedMessage
from app.services.channels.router import ChannelMessageRouter
from app.services.file_storage import LocalFileStorage
from app.services.file_upload import FileUploadService

pytestmark = pytest.mark.anyio


def _attachment(**overrides: Any) -> IncomingAttachment:
    fields: dict[str, Any] = {
        "filename": "report.csv",
        "mime_type": "text/csv",
        "size": 128,
        "handle": "https://files.slack.test/report.csv",
    }
    return IncomingAttachment(**{**fields, **overrides})


def _adapter(*, downloads: Any = b"month,total") -> MagicMock:
    adapter = MagicMock(platform="slack")
    adapter.download_attachment = AsyncMock(
        side_effect=downloads if isinstance(downloads, Exception) else None,
        return_value=downloads if not isinstance(downloads, Exception) else None,
    )
    return adapter


def _service(*, uploads: Any = None) -> ChannelAttachmentService:
    """A service whose vault-free upload path succeeds.

    `FileUploadService` is proven in its own tests; here the question is which
    files reach it and which are turned away before they do.
    """
    service = ChannelAttachmentService(MagicMock())
    real_validate = service.uploads.validate_upload
    service.uploads = MagicMock()
    service.uploads.validate_upload = real_validate
    service.uploads.upload = AsyncMock(return_value=uploads or MagicMock(filename="report.csv"))
    return service


def _incoming(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="slack",
        bot_id=str(uuid.uuid4()),
        platform_user_id="U1",
        platform_chat_id="C1",
        chat_type="channel",
        text=text,
        attachments=[_attachment()],
    )


def _router() -> tuple[ChannelMessageRouter, AsyncMock, list[Any]]:
    """A router whose replies are captured, and the files it is still holding."""
    router = ChannelMessageRouter()
    router._send_reply = AsyncMock()  # type: ignore[method-assign]
    return router, router._send_reply, []


def _agent_router(
    *, answer: Exception | None = None, answer_default: Exception | None = None
) -> Any:
    """`ChannelAgentRouter`, refusing where the test says to.

    A mention that is not the subject raises `UnaddressedMessage`, which is what
    sends an ordinary message on to the default path.
    """
    return MagicMock(
        return_value=MagicMock(
            answer=AsyncMock(side_effect=answer or UnaddressedMessage()),
            answer_default=AsyncMock(
                side_effect=answer_default,
                return_value=MagicMock(text="answered", refused=[]),
            ),
        )
    )


@contextlib.contextmanager
def _channel(agent_router: Any, rows: list[Any]) -> Iterator[None]:
    """One bot, one linked sender, one open session - and files that are counted.

    `rows` is what the attachment service is still holding: `receive` adds to it
    and `discard` takes back out, so a test asserts on what survived the turn
    rather than on which method was called.
    """

    class _Attachments:
        def __init__(self, db: Any) -> None:
            self.db = db

        async def receive(
            self, adapter: Any, token: str, attachments: list[Any], *, user_id: uuid.UUID
        ) -> tuple[list[Any], list[str]]:
            stored = [
                SimpleNamespace(id=uuid.uuid4(), filename=one.filename) for one in attachments
            ]
            rows.extend(stored)
            return stored, []

        async def discard(self, files: list[Any]) -> None:
            for stored in files:
                rows.remove(stored)

    bot = MagicMock(id=uuid.uuid4(), organization_id=uuid.uuid4(), is_active=True, access_policy={})
    identity = MagicMock(id=uuid.uuid4(), user_id=uuid.uuid4())
    session = MagicMock(id=uuid.uuid4(), conversation_id=uuid.uuid4(), turn_count=1)
    router = "app.services.channels.router"
    with (
        patch(f"{router}.channel_bot_repo.get_for_inbound", AsyncMock(return_value=bot)),
        patch(
            f"{router}.channel_identity_repo.get_by_platform_user",
            AsyncMock(return_value=identity),
        ),
        patch(
            f"{router}.channel_session_repo.get_by_bot_and_chat", AsyncMock(return_value=session)
        ),
        patch(f"{router}.channel_session_repo.touch", AsyncMock(return_value=session)),
        patch(
            f"{router}.conversation_repo.get_messages_by_conversation", AsyncMock(return_value=[])
        ),
        # The thread the model is told. Read through the service since #49,
        # because where a summary has run that is where the history starts.
        patch(
            f"{router}.ConversationService",
            return_value=MagicMock(model_history=AsyncMock(return_value=[])),
        ),
        patch(
            f"{router}.get_adapter",
            return_value=MagicMock(begin_reply=AsyncMock(return_value=None)),
        ),
        patch(f"{router}.unseal_bot_token", return_value="xoxb-token"),
        patch(f"{router}.ChannelAttachmentService", _Attachments),
        patch(f"{router}.ChannelAgentRouter", agent_router),
    ):
        yield


class TestReceivingWhatSomebodySent:
    async def test_a_supported_file_is_stored_as_the_web_upload_would(self):
        service = _service()
        adapter = _adapter()

        stored, refused = await service.receive(
            adapter, "xoxb-token", [_attachment()], user_id=uuid.uuid4()
        )

        assert len(stored) == 1
        assert refused == []
        assert service.uploads.upload.await_args.kwargs["filename"] == "report.csv"

    async def test_the_bot_token_is_what_fetches_it(self):
        """Slack's file URLs are private; an unauthenticated GET answers with a
        sign-in page rather than a 401."""
        service = _service()
        adapter = _adapter()

        await service.receive(adapter, "xoxb-token", [_attachment()], user_id=uuid.uuid4())

        assert adapter.download_attachment.await_args.args[0] == "xoxb-token"

    async def test_an_unsupported_type_is_refused_before_it_is_fetched(self):
        """A bot is the most permissive edge this platform has - anyone in a
        channel can drop a file on it - so it must not be the lenient one."""
        service = _service()
        adapter = _adapter()

        stored, refused = await service.receive(
            adapter,
            "t",
            [_attachment(filename="payload.exe", mime_type="application/x-msdownload")],
            user_id=uuid.uuid4(),
        )

        assert stored == []
        assert "payload.exe" in refused[0]
        adapter.download_attachment.assert_not_called()

    async def test_a_file_the_platform_says_is_huge_is_never_downloaded(self):
        """Fetching a gigabyte in order to reject it is the thing worth not doing."""
        service = _service()
        adapter = _adapter()

        stored, refused = await service.receive(
            adapter, "t", [_attachment(size=500 * 1024 * 1024)], user_id=uuid.uuid4()
        )

        assert stored == []
        assert "too large" in refused[0].lower()
        adapter.download_attachment.assert_not_called()

    async def test_the_bytes_are_checked_as_well_as_the_claim(self):
        """A claim is not a measurement: a platform that under-reported the size,
        or a handle that resolved to something else, is caught here."""
        service = _service()
        adapter = _adapter(downloads=b"x" * (60 * 1024 * 1024))

        stored, refused = await service.receive(
            adapter, "t", [_attachment(size=10)], user_id=uuid.uuid4()
        )

        assert stored == []
        assert "too large" in refused[0].lower()
        service.uploads.upload.assert_not_called()

    async def test_a_voice_note_is_refused_by_what_it_is_rather_than_by_its_type(self):
        """ "File type 'audio/ogg' is not supported" reads as a platform that cannot
        handle files. The truth is narrower and more useful: it arrived, and nothing
        here can listen to it yet."""
        service = _service()
        adapter = _adapter()

        stored, refused = await service.receive(
            adapter,
            "t",
            [_attachment(filename="voice.ogg", mime_type="audio/ogg", size=4211)],
            user_id=uuid.uuid4(),
        )

        assert stored == []
        assert "cannot listen to recordings yet" in refused[0]
        adapter.download_attachment.assert_not_called()

    async def test_a_video_is_refused_the_same_way(self):
        service = _service()

        _stored, refused = await service.receive(
            _adapter(),
            "t",
            [_attachment(filename="clip.mp4", mime_type="video/mp4")],
            user_id=uuid.uuid4(),
        )

        assert "cannot listen to recordings yet" in refused[0]

    async def test_a_platform_this_build_cannot_fetch_from_says_so(self):
        """Rather than a bot that ignores an attachment, which looks exactly like
        a bot that read it."""
        service = _service()
        adapter = _adapter(downloads=NotImplementedError("no"))

        stored, refused = await service.receive(adapter, "t", [_attachment()], user_id=uuid.uuid4())

        assert stored == []
        assert "cannot fetch files" in refused[0]

    async def test_a_download_that_failed_is_reported_not_raised(self):
        service = _service()
        adapter = _adapter(downloads=RuntimeError("connection reset"))

        stored, refused = await service.receive(adapter, "t", [_attachment()], user_id=uuid.uuid4())

        assert stored == []
        assert "could not be downloaded" in refused[0]

    async def test_one_bad_file_does_not_lose_the_others(self):
        """Or the question that came with them."""
        service = _service()
        adapter = _adapter()

        stored, refused = await service.receive(
            adapter,
            "t",
            [_attachment(filename="bad.exe", mime_type="application/x-msdownload"), _attachment()],
            user_id=uuid.uuid4(),
        )

        assert len(stored) == 1
        assert len(refused) == 1


class TestATurnRefusedBeforeTheRunKeepsNothing:
    """The bytes are stored before the agent is resolved, so whatever refuses in
    its place has to give them back (#661). `chat_files` carries no organization:
    a row with no message is scoped by `user_id` alone, and nothing collects it.
    """

    async def test_a_refused_turn_leaves_no_stored_file(self):
        router, replies, rows = _router()
        router._answer_mention = AsyncMock(return_value=False)  # type: ignore[method-assign]
        # The window is read off the database and these tests hand `_route_inner`
        # a mock; what they are about is the file rows, not the history.
        router._load_history = AsyncMock(return_value=[])  # type: ignore[method-assign]

        with _channel(
            _agent_router(
                answer_default=BadRequestError(message="No agent is available on this bot yet.")
            ),
            rows,
        ):
            await router._route_inner(_incoming("here is the report"), MagicMock())

        assert rows == []
        assert "No agent is available" in replies.await_args.args[2]

    async def test_a_refused_mention_leaves_no_stored_file(self):
        """The same defect on the path that stores first and refuses second."""
        router, replies, rows = _router()

        with _channel(
            _agent_router(answer=NotFoundError(message="No agent here answers to @support.")), rows
        ):
            await router._route_inner(_incoming("@support where is my refund"), MagicMock())

        assert rows == []
        assert "@support" in replies.await_args.args[2]

    async def test_a_turn_that_actually_ran_keeps_its_file(self):
        """The file is the user's, and the run it fed is in the transcript."""
        router, _replies, rows = _router()
        router._answer_mention = AsyncMock(return_value=False)  # type: ignore[method-assign]
        router._deliver = AsyncMock()  # type: ignore[method-assign]
        router._load_history = AsyncMock(return_value=[])  # type: ignore[method-assign]

        with _channel(_agent_router(answer_default=None), rows):
            await router._route_inner(_incoming("here is the report"), MagicMock())

        assert [stored.filename for stored in rows] == ["report.csv"]

    async def test_a_file_that_cannot_be_deleted_costs_neither_the_others_nor_the_reply(self):
        """A cleanup that raised would replace a refusal somebody can act on with
        a bot that answered nothing at all."""
        service = _service()
        service.uploads.discard = AsyncMock(side_effect=[RuntimeError("storage is down"), None])
        stuck, next_one = MagicMock(id=uuid.uuid4()), MagicMock(id=uuid.uuid4())

        await service.discard([stuck, next_one])

        assert service.uploads.discard.await_count == 2

    async def test_discarding_removes_the_bytes_and_the_row(self, tmp_path):
        db = AsyncMock()
        storage = LocalFileStorage(base_dir=tmp_path)
        path = await storage.save("u1", "report.csv", b"month,total")
        chat_file = ChatFile(
            user_id=uuid.uuid4(),
            filename="report.csv",
            mime_type="text/csv",
            size=11,
            storage_path=path,
            file_type="spreadsheet",
        )

        with patch("app.services.file_upload.get_file_storage", return_value=storage):
            await FileUploadService(db).discard(chat_file)

        assert not (tmp_path / path).exists()
        assert db.delete.await_args.args[0] is chat_file

    async def test_a_message_with_no_files_asks_nothing_of_the_platform(self):
        service = _service()
        adapter = _adapter()

        assert await service.receive(adapter, "t", [], user_id=uuid.uuid4()) == ([], [])
        adapter.download_attachment.assert_not_called()


class TestChoosingWhatToSendBack:
    """What a reply carries, and what it declines to.

    Both functions are awaited: a container-backed workspace answers a glob and a
    read over a synchronous HTTP client, so calling them from a coroutine held the
    event loop for a round trip per file. The backends below stay synchronous on
    purpose - `ensure_async` wraps one, which is exactly the arrangement in
    production for a `state` workspace.
    """

    async def test_a_file_the_turn_wrote_is_sent(self):
        backend = StateBackend()
        before = await workspace_snapshot(backend)
        backend.write("/report.csv", "month,total")

        delivered = await files_written(backend, before)

        assert [a.filename for a in delivered.attachments] == ["report.csv"]
        assert delivered.attachments[0].content == b"month,total"
        assert delivered.attachments[0].mime_type == "text/csv"

    async def test_a_produced_file_carries_its_own_type(self):
        """A chart is the commonest thing an agent writes, and every file used to
        go out as `application/octet-stream` - so the picture somebody asked for
        arrived as a blob they had to download to identify."""
        backend = StateBackend()
        before = await workspace_snapshot(backend)
        backend.write("/chart.png", b"\x89PNG\r\n")

        delivered = await files_written(backend, before)

        assert delivered.attachments[0].mime_type == "image/png"

    async def test_a_name_with_no_recognisable_suffix_stays_opaque(self):
        backend = StateBackend()
        before = await workspace_snapshot(backend)
        backend.write("/dump", "raw")

        delivered = await files_written(backend, before)

        assert delivered.attachments[0].mime_type == "application/octet-stream"

    async def test_a_dotfile_that_was_already_there_is_not_sent_again(self):
        """`glob_info("**/*")` does not match a leading dot, so a `.env` written
        before the turn was absent from the snapshot - and rewriting it during the
        turn read as new and would have been posted into the channel."""
        backend = StateBackend()
        backend.write("/.env", "A=1")
        before = await workspace_snapshot(backend)
        backend.write("/.env", "A=2")

        assert (await files_written(backend, before)).attachments == []

    async def test_a_file_that_was_already_there_is_not_sent_again(self):
        """Rewriting a script it is iterating on is ordinary work, and posting it
        every turn would fill the channel with the same attachment."""
        backend = StateBackend()
        backend.write("/run.py", "print(1)")
        before = await workspace_snapshot(backend)
        backend.write("/run.py", "print(2)")

        assert (await files_written(backend, before)).attachments == []

    async def test_the_users_own_upload_is_not_posted_back_at_them(self):
        backend = StateBackend()
        before = await workspace_snapshot(backend)
        backend.write("/uploads/theirs.csv", "a,b")

        assert (await files_written(backend, before)).attachments == []

    async def test_a_materialised_skill_is_not_the_agents_work(self):
        backend = StateBackend()
        before = await workspace_snapshot(backend)
        backend.write("/skills/refunds/SKILL.md", "---\nname: refunds\n---\n\nbody")

        assert (await files_written(backend, before)).attachments == []

    async def test_a_file_too_large_for_a_reply_is_named_rather_than_dropped(self):
        """An agent told its file was delivered will tell the user the same."""
        backend = StateBackend()
        before = await workspace_snapshot(backend)
        backend.write("/huge.csv", "x" * (MAX_OUTBOUND_BYTES + 1))

        delivered = await files_written(backend, before)

        assert delivered.attachments == []
        assert delivered.refused == ["/huge.csv"]
        assert "stayed in the workspace" in delivered.note()

    async def test_past_the_per_reply_cap_the_rest_are_named(self):
        """A turn that writes twelve intermediate CSVs should not post twelve."""
        backend = StateBackend()
        before = await workspace_snapshot(backend)
        for index in range(MAX_OUTBOUND_FILES + 2):
            backend.write(f"/out-{index}.csv", "a")

        delivered = await files_written(backend, before)

        assert len(delivered.attachments) == MAX_OUTBOUND_FILES
        assert len(delivered.refused) == 2

    async def test_nothing_written_is_nothing_said(self):
        backend = StateBackend()
        before = await workspace_snapshot(backend)

        delivered = await files_written(backend, before)

        assert delivered.attachments == []
        assert delivered.note() == ""

    async def test_a_file_that_cannot_be_read_is_skipped_rather_than_failing_the_reply(self):
        class _Backend:
            def glob_info(self, pattern, path="/"):
                return [{"path": "/gone.csv", "is_dir": False}]

            def read_bytes(self, path):
                raise RuntimeError("vanished between the listing and the read")

        assert (await files_written(_Backend(), set())).attachments == []

    async def test_a_workspace_that_cannot_be_listed_means_no_attachments_not_no_reply(self):
        class _Broken:
            def glob_info(self, pattern, path="/"):
                raise RuntimeError("the service is down")

        assert await files_written(_Broken(), set()) == DeliveredFiles(attachments=[], refused=[])

    async def test_a_snapshot_of_an_unreadable_workspace_is_not_an_empty_one(self):
        """It used to answer `set()`, and that is the unsafe direction.

        `files_written` answers `paths - before`, so an empty `before` does not
        mean "nothing to compare against" - it means "the workspace was empty",
        and every file already in it reads as this turn's output.
        """

        class _Broken:
            def glob_info(self, pattern, path="/"):
                raise RuntimeError("no")

        assert await workspace_snapshot(_Broken()) is None

    async def test_a_turn_whose_snapshot_failed_posts_nothing(self):
        """The refusal the return type exists for.

        Under `agent` or `channel` scope the files already in the workspace belong
        to other people, so treating them as this turn's output would post a
        colleague's work into a shared channel. It needs only a transient failure:
        both calls read the same workspace, so a persistently broken listing fails
        both and posts nothing anyway.
        """
        backend = StateBackend()
        backend.write("/someone-elses.csv", "month,total")
        backend.write("/another.txt", "private")

        assert await files_written(backend, None) == DeliveredFiles(attachments=[], refused=[])

    async def test_directories_are_not_files(self):
        class _WithDirectories:
            def glob_info(self, pattern, path="/"):
                return [
                    {"path": "/out", "is_dir": True},
                    {"path": "/out/report.csv", "is_dir": False},
                ]

            def read_bytes(self, path):
                return b"a,b"

        delivered = await files_written(_WithDirectories(), set())

        assert [a.filename for a in delivered.attachments] == ["report.csv"]


async def _route_one_file(text: str) -> tuple[MagicMock, MagicMock, AsyncMock]:
    """Route one message carrying one file, and report what the turn did.

    Returns the platform adapter, the agent router standing in for a run, and the
    upload the attachment service reaches - so a caller can count the downloads
    and the stored rows one message cost. Everything a turn touches on the way is
    replaced; the question here is how many times the file is fetched, not what
    the agent said about it.
    """
    bot = MagicMock(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        is_active=True,
        access_policy={},
        api_base_url=None,
    )
    identity = MagicMock(id=uuid.uuid4(), user_id=uuid.uuid4())
    session = MagicMock(conversation_id=uuid.uuid4(), turn_count=1)

    adapter = _adapter()
    adapter.begin_reply = AsyncMock(return_value=None)
    adapter.send_message = AsyncMock()

    agents = MagicMock()
    agents.answer = AsyncMock(
        return_value=AnsweredTurn(text="answered"),
        side_effect=None if text.startswith("@") else UnaddressedMessage,
    )
    agents.answer_default = AsyncMock(return_value=AnsweredTurn(text="answered"))
    upload = AsyncMock(return_value=MagicMock(filename="report.csv"))

    incoming = IncomingMessage(
        platform="slack",
        bot_id=str(uuid.uuid4()),
        platform_user_id="U1",
        platform_chat_id="C1",
        chat_type="group",
        text=text,
        message_id="m1",
        attachments=[_attachment()],
    )

    router = "app.services.channels.router"
    with (
        patch(f"{router}.get_adapter", return_value=adapter),
        patch(f"{router}.unseal_bot_token", return_value="tok"),
        patch(f"{router}.channel_bot_repo.get_for_inbound", AsyncMock(return_value=bot)),
        patch(
            f"{router}.channel_identity_repo.get_by_platform_user",
            AsyncMock(return_value=identity),
        ),
        patch(
            f"{router}.channel_session_repo.get_by_bot_and_chat", AsyncMock(return_value=session)
        ),
        patch(f"{router}.channel_session_repo.touch", AsyncMock(return_value=session)),
        patch(
            f"{router}.conversation_repo.get_messages_by_conversation", AsyncMock(return_value=[])
        ),
        # The window is sized off a `COUNT`, and the session here is a mock. What
        # this helper is about is which files reach the run.
        patch(f"{router}.conversation_repo.count_messages", AsyncMock(return_value=0)),
        patch(
            f"{router}.ConversationService",
            return_value=MagicMock(model_history=AsyncMock(return_value=[])),
        ),
        patch(f"{router}.ChannelAgentRouter", return_value=agents),
        patch.object(FileUploadService, "upload", upload),
    ):
        await ChannelMessageRouter()._route_inner(incoming, MagicMock())

    return adapter, agents, upload


class TestOneMessageOneStoredFile:
    """What arrives with a message is fetched once, whichever path answers it.

    The mention path runs first and needs the files; a message naming no agent
    then fell through to the default path, which fetched and stored the same
    files all over again - two downloads and two `ChatFile` rows per attachment,
    only the second of each linked to the turn (#660).
    """

    async def test_a_message_naming_no_agent_stores_its_file_once(self):
        """One download and one row - and the row is what the turn runs with. The
        duplicate was not only wasted work: the run was handed the second set,
        leaving the first stored against the sender and referenced by nothing."""
        adapter, agents, upload = await _route_one_file("here is the report")

        assert adapter.download_attachment.await_count == 1
        assert upload.await_count == 1
        assert agents.answer_default.await_args.kwargs["attachments"] == [upload.return_value]

    async def test_a_mention_still_gets_the_file_it_came_with(self):
        adapter, agents, upload = await _route_one_file("@support what is in this")

        assert adapter.download_attachment.await_count == 1
        assert agents.answer.await_args.kwargs["attachments"] == [upload.return_value]
        agents.answer_default.assert_not_awaited()
