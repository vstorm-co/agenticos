"""What the two-phase validator accepts and refuses (#1591, §6.3 step 5).

The metadata phase runs before the bytes exist and accepts on MIME *or* extension,
because browsers send `application/octet-stream` for `.msg`/`.odt`/`.xls`; it refuses
a specific MIME that contradicts the extension. The byte phase runs once the bytes are
in hand and refuses a forged signature — an OLE/ZIP/TIFF container that is not what the
resolved format needs.
"""

import pytest

from app.services.file_upload import FileUploadService

pytestmark = pytest.mark.anyio

validate = FileUploadService.validate_upload
validate_bytes = FileUploadService.validate_bytes

OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest"
ZIP = b"PK\x03\x04rest"
TIFF_LE = b"II*\x00rest"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
GIF = b"GIF89a" + b"\x00" * 16


class TestTheMetadataPhase:
    @pytest.mark.parametrize(
        "mime",
        [
            "application/msword",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.ms-outlook",
            "image/tiff",
            "application/vnd.oasis.opendocument.presentation",
            "application/vnd.oasis.opendocument.spreadsheet",
            "application/vnd.oasis.opendocument.text",
            "application/xml",
            "text/xml",
        ],
    )
    def test_each_new_mime_is_accepted(self, mime):
        assert validate(mime, 1024, "file")[0] is True

    @pytest.mark.parametrize(
        "filename",
        ["m.doc", "b.xls", "d.pptx", "e.msg", "s.tiff", "s.tif", "p.odp", "b.ods", "n.odt"],
    )
    def test_each_new_extension_is_accepted_when_the_type_is_octet_stream(self, filename):
        assert validate("application/octet-stream", 1024, filename)[0] is True

    def test_an_empty_type_falls_back_to_the_extension(self):
        assert validate(None, 1024, "notes.odt")[0] is True

    def test_a_genuinely_unknown_type_and_extension_is_refused(self):
        valid, message = validate("application/x-msdownload", 1024, "payload.exe")
        assert valid is False
        assert message is not None and "not supported" in message

    def test_a_specific_mime_that_contradicts_the_extension_is_refused(self):
        assert validate("application/msword", 1024, "photo.tiff")[0] is False
        assert validate("image/png", 1024, "payload.doc")[0] is False

    def test_a_text_mime_on_a_binary_extension_is_refused(self):
        """A specific text MIME on a binary extension is a contradiction the byte
        phase cannot catch (images/PDF are not sniffed), so it is refused here rather
        than routed as an image by extension (#1591)."""
        valid, message = validate("text/plain", 1024, "photo.png")
        assert valid is False
        assert message is not None and "does not match" in message
        assert validate("application/xml", 1024, "report.pdf")[0] is False

    def test_a_text_mime_on_a_text_extension_is_accepted(self):
        """A text MIME refines a text extension rather than contradicting it."""
        assert validate("text/plain", 1024, "notes.csv")[0] is True
        assert validate("application/xml", 1024, "data.xml")[0] is True

    def test_a_mime_with_a_charset_parameter_is_accepted(self):
        assert validate("application/xml; charset=utf-8", 1024, "data.xml")[0] is True

    def test_an_uppercase_extension_is_accepted(self):
        assert validate("application/octet-stream", 1024, "REPORT.ODT")[0] is True

    def test_the_size_ceiling_still_applies(self):
        from app.core.config import settings

        oversized = settings.CHAT_MAX_UPLOAD_SIZE_MB * 1024 * 1024 + 1
        valid, message = validate("application/pdf", oversized, "big.pdf")
        assert valid is False
        assert "too large" in message.lower()


class TestTheBytePhase:
    def test_a_format_with_no_cheap_signature_is_not_sniffed(self):
        assert validate_bytes(b"anything", "application/pdf", "x.pdf") == (True, None)
        assert validate_bytes(b"plain text", "text/plain", "x.txt") == (True, None)

    def test_an_ole_format_needs_the_ole_signature(self):
        assert validate_bytes(OLE, "application/msword", "m.doc")[0] is True
        assert validate_bytes(b"not ole", "application/msword", "m.doc")[0] is False

    def test_a_zip_format_needs_the_zip_signature(self):
        assert validate_bytes(ZIP, "application/octet-stream", "n.odt")[0] is True
        assert validate_bytes(b"not zip", "application/octet-stream", "n.odt")[0] is False

    def test_a_forged_tiff_is_caught(self):
        assert validate_bytes(TIFF_LE, "image/tiff", "s.tiff")[0] is True
        valid, message = validate_bytes(b"GIF89a...", "image/tiff", "s.tiff")
        assert valid is False
        assert message is not None and "do not match" in message

    def test_a_valid_web_safe_image_passes(self):
        assert validate_bytes(PNG, "image/png", "a.png")[0] is True
        assert validate_bytes(JPEG, None, "b.jpg")[0] is True
        assert validate_bytes(GIF, "application/octet-stream", "c.gif")[0] is True

    def test_a_corrupt_web_safe_image_is_refused(self):
        # A `.png` whose bytes are not a PNG would be stored under `image/png` and
        # then fail at the vision provider, killing the turn: refuse it here (#1654).
        valid, message = validate_bytes(b"not an image at all", None, "a.png")
        assert valid is False
        assert message is not None and "do not match" in message

    def test_a_web_safe_image_whose_bytes_are_a_different_image_is_refused(self):
        assert validate_bytes(PNG, "image/jpeg", "b.jpg")[0] is False


class TestArchives:
    """A `.zip` or `.tar.gz` is accepted, to be unpacked into a workspace (#2479)."""

    @pytest.mark.parametrize(
        ("mime", "filename"),
        [
            ("application/zip", "repo.zip"),
            ("application/x-zip-compressed", "repo.zip"),
            ("application/gzip", "repo.tar.gz"),
            ("application/x-gzip", "repo.tgz"),
            ("application/octet-stream", "repo.zip"),
            ("application/octet-stream", "repo.tar.gz"),
            ("application/zip", "repo"),
        ],
    )
    def test_an_archive_is_accepted(self, mime, filename):
        assert validate(mime, 1024, filename) == (True, None)

    def test_an_archive_is_its_own_kind(self):
        from app.services.file_storage import canonical_mime, classify_file

        assert classify_file("application/octet-stream", "repo.zip") == "archive"
        assert classify_file("application/zip", "repo") == "archive"
        assert canonical_mime("application/octet-stream", "repo.tar.gz") == "application/gzip"
        assert canonical_mime("application/x-zip-compressed", "repo.zip") == "application/zip"

    def test_a_zip_type_on_a_known_extension_is_still_that_file(self):
        """A `.docx` is a zip, and a client saying so is describing the container."""
        from app.services.file_storage import classify_file

        assert validate("application/zip", 1024, "report.docx") == (True, None)
        assert classify_file("application/zip", "report.docx") == "docx"
        assert classify_file("application/zip", "notes.txt") == "text"

    def test_a_text_file_labelled_an_archive_is_stored_as_text(self):
        from app.services.file_storage import canonical_mime

        assert canonical_mime("application/zip", "notes.txt") == "text/plain"
        assert canonical_mime("application/gzip", "run.py") == "text/x-python"

    def test_a_contradicting_type_on_an_archive_is_refused(self):
        assert validate("image/png", 1024, "repo.zip")[0] is False
        assert validate("text/plain", 1024, "repo.zip")[0] is False

    def test_an_empty_zip_is_a_zip(self):
        # An archive with no members is only its end-of-directory record.
        assert validate_bytes(b"PK\x05\x06" + b"\x00" * 18, "application/zip", "e.zip")[0]

    def test_each_archive_needs_its_own_signature(self):
        assert validate_bytes(ZIP, "application/zip", "repo.zip")[0] is True
        assert validate_bytes(b"\x1f\x8brest", None, "repo.tar.gz")[0] is True
        assert validate_bytes(ZIP, None, "repo.tar.gz")[0] is False
        assert validate_bytes(b"\x1f\x8brest", None, "repo.zip")[0] is False


def _zip_of(*members: tuple[str, bytes]) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members:
            archive.writestr(name, data)
    return buffer.getvalue()


@pytest.mark.security
class TestAnArchiveIsReadWholeAtUpload:
    async def test_a_zip_climbing_out_of_its_folder_is_refused_before_it_is_stored(
        self, monkeypatch
    ):
        from unittest.mock import AsyncMock, MagicMock

        from app.core.exceptions import BadRequestError
        from app.services import file_upload as upload_module

        storage = MagicMock(save=AsyncMock())
        monkeypatch.setattr(upload_module, "get_file_storage", lambda: storage)

        with pytest.raises(BadRequestError, match=r"outside it"):
            await FileUploadService(db=None).upload(
                user_id="u",
                file_data=_zip_of(("../../etc/passwd", b"x")),
                filename="repo.zip",
                content_type="application/zip",
            )
        storage.save.assert_not_awaited()

    async def test_a_safe_zip_is_stored_with_its_tree_as_its_text(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock

        from app.services import file_upload as upload_module

        storage = MagicMock(save=AsyncMock(return_value="u/1/repo.zip"))
        monkeypatch.setattr(upload_module, "get_file_storage", lambda: storage)
        created = AsyncMock(side_effect=lambda db, **row: row)
        monkeypatch.setattr(upload_module.chat_file_repo, "create", created)

        row = await FileUploadService(db=None).upload(
            user_id="u",
            file_data=_zip_of(("repo/a.py", b"print(1)")),
            filename="repo.zip",
            content_type="application/zip",
        )

        assert row["file_type"] == "archive"
        assert row["mime_type"] == "application/zip"
        assert row["parsed_content"] == "1 files, 8 bytes unpacked\nrepo/a.py"
