"""Read-only IMAP through Mirage's client and MIME parser, with durable UID cursors."""

import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from mirage.accessor.email import EmailAccessor
from mirage.core.email._parse import parse_rfc822
from mirage.core.email.client import quote_string
from mirage.core.email.config import EmailConfig
from pydantic import JsonValue, TypeAdapter

from app.core.config import settings
from app.core.exceptions import AuthorizationError, BadRequestError, ExternalServiceError
from app.core.mail_credential import ImapCredential

_JSON = TypeAdapter(dict[str, JsonValue])
_NUMBER = re.compile(rb"\b(UIDVALIDITY|UIDNEXT) ([0-9]+)\b")
_UIDS = re.compile(rb"^(?:[0-9]+(?: [0-9]+)*)?$")
_MAX_MESSAGE_BYTES = 100_000
_MAX_BATCH = 25


class MailSession:
    def __init__(self, accessor: EmailAccessor, credential: ImapCredential) -> None:
        self.accessor = accessor
        self.credential = credential

    async def position(self) -> tuple[int, int]:
        imap = await self.accessor.get_imap()
        selected = await imap.select(quote_string(self.credential.folder))
        if selected.result != "OK":
            raise ExternalServiceError(message="The IMAP mailbox could not be selected")
        values = {
            match[0].decode(): int(match[1])
            for line in selected.lines
            for match in _NUMBER.findall(bytes(line))
        }
        if "UIDVALIDITY" not in values or "UIDNEXT" not in values:
            raise ExternalServiceError(
                message="The IMAP server did not provide a stable mailbox cursor"
            )
        return values["UIDVALIDITY"], values["UIDNEXT"] - 1

    async def search(self, criteria: str) -> list[int]:
        if len(criteria) > 2000 or any(character in criteria for character in "\r\n\0"):
            raise BadRequestError(
                message="IMAP search must be one command line of at most 2000 characters"
            )
        imap = await self.accessor.get_imap()
        response = await imap.uid("SEARCH", criteria)
        if response.result != "OK":
            raise ExternalServiceError(message="The IMAP server refused the search")
        identifiers: list[int] = []
        for line in response.lines:
            if _UIDS.fullmatch(bytes(line).strip()):
                identifiers.extend(int(value) for value in bytes(line).split())
        return sorted(set(identifiers))

    async def message(self, uid: int) -> dict[str, JsonValue]:
        imap = await self.accessor.get_imap()
        response = await imap.uid("FETCH", str(uid), f"(UID BODY.PEEK[]<0.{_MAX_MESSAGE_BYTES}>)")
        if response.result != "OK":
            raise ExternalServiceError(message="The IMAP message could not be read")
        literal = next(
            (bytes(line) for line in response.lines if isinstance(line, bytearray)), None
        )
        if literal is None:
            raise ExternalServiceError(message="The IMAP message no longer exists")
        parsed = _JSON.validate_python(parse_rfc822(literal))
        for field in ("body_text", "body_html"):
            value = parsed.get(field)
            if isinstance(value, str):
                parsed[field] = value[:8000]
        return {**parsed, "uid": uid, "truncated": len(literal) >= _MAX_MESSAGE_BYTES}


@asynccontextmanager
async def mailbox(credential: ImapCredential) -> AsyncGenerator[MailSession]:
    if credential.host.casefold() not in {
        host.casefold() for host in settings.MIRAGE_ALLOWED_HOSTS
    }:
        raise AuthorizationError(
            message="Add this IMAP hostname to MIRAGE_ALLOWED_HOSTS before connecting it"
        )
    accessor = EmailAccessor(
        EmailConfig(
            imap_host=credential.host,
            imap_port=credential.port,
            smtp_host=credential.host,
            username=credential.username,
            password=credential.password,
            use_ssl=True,
            timeout=15,
        )
    )
    try:
        session = MailSession(accessor, credential)
        await session.position()
        yield session
    except OSError, TimeoutError, ConnectionError:
        raise ExternalServiceError(
            message="The IMAP account could not be reached or authenticated"
        ) from None
    finally:
        await accessor.close()


async def execute_mail(
    credential: ImapCredential, operation: str, *, parameters: dict[str, str], query: dict[str, str]
) -> dict[str, JsonValue]:
    async with mailbox(credential) as session:
        if operation == "search_messages":
            ids = await session.search(query.get("query", "ALL"))
            return _JSON.validate_python(
                {"message_ids": ids[-_MAX_BATCH:], "truncated": len(ids) > _MAX_BATCH}
            )
        if operation == "read_message":
            value = parameters.get("message_id", "")
            if not value.isascii() or not value.isdigit() or len(value) > 20 or int(value) < 1:
                raise BadRequestError(message="An IMAP message id is a positive UID")
            return await session.message(int(value))
    raise BadRequestError(message="Unknown IMAP operation")


async def changed_mail(
    credential: ImapCredential, cursor: dict[str, JsonValue] | None
) -> tuple[list[dict[str, JsonValue]], dict[str, JsonValue]]:
    async with mailbox(credential) as session:
        validity, latest = await session.position()
        last = (cursor or {}).get("last_uid")
        if cursor is None or cursor.get("uidvalidity") != validity or not isinstance(last, int):
            return [], {"uidvalidity": validity, "last_uid": latest}
        ids = [uid for uid in await session.search(f"UID {last + 1}:*") if uid > last][:_MAX_BATCH]
        messages = [await session.message(uid) for uid in ids]
        return messages, {"uidvalidity": validity, "last_uid": ids[-1] if ids else last}
