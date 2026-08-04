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

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai_backends import StateBackend

from app.services.channels.attachments import (
    MAX_OUTBOUND_BYTES,
    MAX_OUTBOUND_FILES,
    ChannelAttachmentService,
    DeliveredFiles,
    files_written,
    workspace_snapshot,
)
from app.services.channels.base import IncomingAttachment

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

    async def test_a_message_with_no_files_asks_nothing_of_the_platform(self):
        service = _service()
        adapter = _adapter()

        assert await service.receive(adapter, "t", [], user_id=uuid.uuid4()) == ([], [])
        adapter.download_attachment.assert_not_called()


class TestChoosingWhatToSendBack:
    def test_a_file_the_turn_wrote_is_sent(self):
        backend = StateBackend()
        before = workspace_snapshot(backend)
        backend.write("/report.csv", "month,total")

        delivered = files_written(backend, before)

        assert [a.filename for a in delivered.attachments] == ["report.csv"]
        assert delivered.attachments[0].content == b"month,total"
        assert delivered.attachments[0].mime_type == "text/csv"

    def test_a_produced_file_carries_its_own_type(self):
        """A chart is the commonest thing an agent writes, and every file used to
        go out as `application/octet-stream` - so the picture somebody asked for
        arrived as a blob they had to download to identify."""
        backend = StateBackend()
        before = workspace_snapshot(backend)
        backend.write("/chart.png", b"\x89PNG\r\n")

        delivered = files_written(backend, before)

        assert delivered.attachments[0].mime_type == "image/png"

    def test_a_name_with_no_recognisable_suffix_stays_opaque(self):
        backend = StateBackend()
        before = workspace_snapshot(backend)
        backend.write("/dump", "raw")

        delivered = files_written(backend, before)

        assert delivered.attachments[0].mime_type == "application/octet-stream"

    def test_a_dotfile_that_was_already_there_is_not_sent_again(self):
        """`glob_info("**/*")` does not match a leading dot, so a `.env` written
        before the turn was absent from the snapshot - and rewriting it during the
        turn read as new and would have been posted into the channel."""
        backend = StateBackend()
        backend.write("/.env", "A=1")
        before = workspace_snapshot(backend)
        backend.write("/.env", "A=2")

        assert files_written(backend, before).attachments == []

    def test_a_file_that_was_already_there_is_not_sent_again(self):
        """Rewriting a script it is iterating on is ordinary work, and posting it
        every turn would fill the channel with the same attachment."""
        backend = StateBackend()
        backend.write("/run.py", "print(1)")
        before = workspace_snapshot(backend)
        backend.write("/run.py", "print(2)")

        assert files_written(backend, before).attachments == []

    def test_the_users_own_upload_is_not_posted_back_at_them(self):
        backend = StateBackend()
        before = workspace_snapshot(backend)
        backend.write("/uploads/theirs.csv", "a,b")

        assert files_written(backend, before).attachments == []

    def test_a_materialised_skill_is_not_the_agents_work(self):
        backend = StateBackend()
        before = workspace_snapshot(backend)
        backend.write("/skills/refunds/SKILL.md", "---\nname: refunds\n---\n\nbody")

        assert files_written(backend, before).attachments == []

    def test_a_file_too_large_for_a_reply_is_named_rather_than_dropped(self):
        """An agent told its file was delivered will tell the user the same."""
        backend = StateBackend()
        before = workspace_snapshot(backend)
        backend.write("/huge.csv", "x" * (MAX_OUTBOUND_BYTES + 1))

        delivered = files_written(backend, before)

        assert delivered.attachments == []
        assert delivered.refused == ["/huge.csv"]
        assert "stayed in the workspace" in delivered.note()

    def test_past_the_per_reply_cap_the_rest_are_named(self):
        """A turn that writes twelve intermediate CSVs should not post twelve."""
        backend = StateBackend()
        before = workspace_snapshot(backend)
        for index in range(MAX_OUTBOUND_FILES + 2):
            backend.write(f"/out-{index}.csv", "a")

        delivered = files_written(backend, before)

        assert len(delivered.attachments) == MAX_OUTBOUND_FILES
        assert len(delivered.refused) == 2

    def test_nothing_written_is_nothing_said(self):
        backend = StateBackend()
        before = workspace_snapshot(backend)

        delivered = files_written(backend, before)

        assert delivered.attachments == []
        assert delivered.note() == ""

    def test_a_file_that_cannot_be_read_is_skipped_rather_than_failing_the_reply(self):
        class _Backend:
            def glob_info(self, pattern):
                return [{"path": "/gone.csv", "is_dir": False}]

            def read_bytes(self, path):
                raise RuntimeError("vanished between the listing and the read")

        assert files_written(_Backend(), set()).attachments == []

    def test_a_workspace_that_cannot_be_listed_means_no_attachments_not_no_reply(self):
        class _Broken:
            def glob_info(self, pattern):
                raise RuntimeError("the service is down")

        assert files_written(_Broken(), set()) == DeliveredFiles(attachments=[], refused=[])

    def test_a_snapshot_of_an_unreadable_workspace_is_not_an_empty_one(self):
        """It used to answer `set()`, and that is the unsafe direction.

        `files_written` answers `paths - before`, so an empty `before` does not
        mean "nothing to compare against" - it means "the workspace was empty",
        and every file already in it reads as this turn's output.
        """

        class _Broken:
            def glob_info(self, pattern):
                raise RuntimeError("no")

        assert workspace_snapshot(_Broken()) is None

    def test_a_turn_whose_snapshot_failed_posts_nothing(self):
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

        assert files_written(backend, None) == DeliveredFiles(attachments=[], refused=[])

    def test_directories_are_not_files(self):
        class _WithDirectories:
            def glob_info(self, pattern):
                return [
                    {"path": "/out", "is_dir": True},
                    {"path": "/out/report.csv", "is_dir": False},
                ]

            def read_bytes(self, path):
                return b"a,b"

        delivered = files_written(_WithDirectories(), set())

        assert [a.filename for a in delivered.attachments] == ["report.csv"]
