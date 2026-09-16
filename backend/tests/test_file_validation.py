"""What the two-phase validator accepts and refuses (#1591, §6.3 step 5).

The metadata phase runs before the bytes exist and accepts on MIME *or* extension,
because browsers send `application/octet-stream` for `.msg`/`.odt`/`.xls`; it refuses
a specific MIME that contradicts the extension. The byte phase runs once the bytes are
in hand and refuses a forged signature — an OLE/ZIP/TIFF container that is not what the
resolved format needs.
"""

from __future__ import annotations

import pytest

from app.services.file_upload import FileUploadService

pytestmark = pytest.mark.anyio

validate = FileUploadService.validate_upload
validate_bytes = FileUploadService.validate_bytes

OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest"
ZIP = b"PK\x03\x04rest"
TIFF_LE = b"II*\x00rest"


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
