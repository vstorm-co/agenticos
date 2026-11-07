"""File payloads for native APIs; no model argument is ever a local filesystem path."""

import base64
import binascii
import io
import json
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.core.exceptions import BadRequestError, ExternalServiceError


class Upload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_base64: str = Field(max_length=28_000_000)
    content_type: str = Field(
        default="application/octet-stream",
        max_length=255,
        pattern=r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$",
    )
    name: str | None = Field(default=None, max_length=255)
    parent_id: str | None = Field(default=None, max_length=255)


class WordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paragraphs: list[str] = Field(max_length=1000)
    title: str = Field(default="", max_length=255)


def upload_bytes(body: dict[str, JsonValue] | None) -> tuple[bytes, str, bytes]:
    try:
        value = Upload.model_validate(body)
        content = base64.b64decode(value.content_base64, validate=True)
    except ValidationError, binascii.Error:
        raise BadRequestError(
            message="File upload needs content_base64, an optional content_type, name and parent_id"
        ) from None
    if len(content) > 20_000_000:
        raise BadRequestError(message="A native integration upload may contain at most 20 MB")
    metadata: dict[str, JsonValue] = {}
    if value.name:
        metadata["name"] = value.name
    if value.parent_id:
        metadata["parents"] = [value.parent_id]
    return content, value.content_type, json.dumps(metadata).encode()


def word_bytes(body: dict[str, JsonValue] | None) -> bytes:
    from docx import Document

    try:
        value = WordBody.model_validate(body)
    except ValidationError:
        raise BadRequestError(
            message="Writing a Word document needs paragraphs and an optional title"
        ) from None
    document = Document()
    if value.title:
        document.add_heading(value.title, 0)
    for paragraph in value.paragraphs:
        document.add_paragraph(paragraph)
    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


def file_text(content: bytes, content_type: str, *, word: bool) -> dict[str, JsonValue]:
    if word or "wordprocessingml" in content_type:
        try:
            with ZipFile(io.BytesIO(content)) as archive:
                if archive.getinfo("word/document.xml").file_size > 2_000_000:
                    raise ExternalServiceError(
                        message="The Word document is too large to read safely"
                    )
                root = ElementTree.fromstring(archive.read("word/document.xml"))
        except BadZipFile, KeyError, DefusedXmlException, ElementTree.ParseError:
            raise ExternalServiceError(message="The Word document could not be read") from None
        paragraphs = [
            "".join(
                text.text or ""
                for text in paragraph.iter(
                    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
                )
            )
            for paragraph in root.iter(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
            )
        ]
        text = "\n".join(paragraphs)
    elif "application/pdf" in content_type:
        import pymupdf

        try:
            with pymupdf.open(stream=content, filetype="pdf") as document:
                text = "\n".join(
                    document[index].get_text() for index in range(min(len(document), 100))
                )
        except pymupdf.FileDataError, RuntimeError:
            raise ExternalServiceError(message="The PDF could not be read") from None
    elif content_type.startswith("text/") or "json" in content_type:
        text = content.decode("utf-8", errors="replace")
    else:
        raise ExternalServiceError(
            message="This file format cannot be read as text; use its product's document tools"
        )
    return {"text": text[:100_000], "truncated": len(text) > 100_000, "content_type": content_type}
