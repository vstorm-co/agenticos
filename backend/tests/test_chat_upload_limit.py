"""What refuses a chat attachment, and whether an operator can move it.

#498. Three numbers claimed to be the chat upload limit and they disagreed. The
one that decided was `MAX_UPLOAD_SIZE`, a 10 MiB literal in `file_storage.py`
that no setting produced and no operator could raise, while
`MAX_UPLOAD_SIZE_MB` (50) was what `/health` published and what the composer
checked against. So a 20MB attachment passed the client check, was read into
memory, crossed the wire in full, and came back refused by a limit that appeared
in no configuration file - and `frontend/README.md` told the operator to keep the
client value "at or below the backend's", which was advice they could not follow.

The decision the issue asked for: **two settings, not one.** A knowledge-base
document is chunked, embedded and read back through retrieval; an attachment to
an agent with no workspace is pasted whole into the prompt
(`app/services/attachments.py`). The same size fails differently on each surface,
so each carries its own ceiling and both are published.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.file_upload import FileUploadService

pytestmark = pytest.mark.anyio


def _mb(size: int) -> int:
    return size * 1024 * 1024


class TestWhatRefusesAnAttachment:
    def test_a_file_over_the_configured_limit_is_refused(self):
        valid, message = FileUploadService.validate_upload(
            "application/pdf", _mb(settings.CHAT_MAX_UPLOAD_SIZE_MB) + 1
        )

        assert valid is False
        assert message is not None

    def test_a_file_at_the_configured_limit_is_accepted(self):
        """Exactly the limit is inside it - the refusal is `>`, not `>=`."""
        valid, message = FileUploadService.validate_upload(
            "application/pdf", _mb(settings.CHAT_MAX_UPLOAD_SIZE_MB)
        )

        assert (valid, message) == (True, None)

    def test_the_refusal_names_the_limit_that_produced_it(self, monkeypatch):
        """The sentence used to name a constant nobody could find. An operator
        reading it has to be able to look the number up in their configuration.
        """
        monkeypatch.setattr(settings, "CHAT_MAX_UPLOAD_SIZE_MB", 25)

        _, message = FileUploadService.validate_upload("application/pdf", _mb(30))

        assert message == "File too large. Maximum size is 25MB."

    def test_raising_the_setting_raises_the_limit(self, monkeypatch):
        """The whole of #498: the number that refuses is configurable now.

        The same file, refused and then accepted, with nothing changed but the
        setting - which is what could not be done while the limit was a literal.
        """
        thirty_megabytes = _mb(30)
        monkeypatch.setattr(settings, "CHAT_MAX_UPLOAD_SIZE_MB", 10)
        refused, _ = FileUploadService.validate_upload("application/pdf", thirty_megabytes)

        monkeypatch.setattr(settings, "CHAT_MAX_UPLOAD_SIZE_MB", 50)
        accepted, _ = FileUploadService.validate_upload("application/pdf", thirty_megabytes)

        assert (refused, accepted) == (False, True)

    def test_the_type_allowlist_is_checked_before_the_size(self, monkeypatch):
        """An enormous `.exe` is refused for being an `.exe`. The order matters
        because the type refusal names the type and the size refusal names a
        number, and a caller shown the wrong one fixes the wrong thing."""
        monkeypatch.setattr(settings, "CHAT_MAX_UPLOAD_SIZE_MB", 1)

        _, message = FileUploadService.validate_upload("application/x-msdownload", _mb(500))

        assert message is not None
        assert "not supported" in message


class TestWhatTheDeploymentPublishes:
    async def test_health_reports_both_ceilings(self, client):
        """A client that reads one number cannot know the other, and the two
        surfaces refuse at different sizes. This probe published only the
        knowledge base's, which is not the one a chat upload meets.
        """
        response = await client.get("/api/v1/health")

        body = response.json()
        assert body["max_upload_size_mb"] == settings.MAX_UPLOAD_SIZE_MB
        assert body["chat_max_upload_size_mb"] == settings.CHAT_MAX_UPLOAD_SIZE_MB

    async def test_the_two_ceilings_are_separately_configurable(self, client, monkeypatch):
        """Not one setting read twice: moving one must not move the other."""
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 80)
        monkeypatch.setattr(settings, "CHAT_MAX_UPLOAD_SIZE_MB", 15)

        body = (await client.get("/api/v1/health")).json()

        assert body["max_upload_size_mb"] == 80
        assert body["chat_max_upload_size_mb"] == 15
