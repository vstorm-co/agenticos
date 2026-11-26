"""Docling Serve: the client a document parse and a connection's Test talk through.

Docling Serve is a self-hosted document converter the organization runs and names as
a `document_parser` service connection. Everything it says is untrusted text that may
carry content from a document, so nothing from a response body, the address or the key
is put into a message, a log line or an audit entry here: a failure is reported by its
kind alone.
"""

import hashlib
import json
import logging
import mimetypes
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, TypedDict
from uuid import UUID, uuid4

import anyio
import httpx

from app.core.exceptions import ExternalServiceError
from app.services.rag.config import DOCLING_PDF_FORMATS
from app.services.rag.documents import BaseDocumentParser, has_indexable_text
from app.services.rag.models import Document, DocumentPage

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 10.0
"""How long each of the Test's two calls may take."""

_SAFE_VERSION = re.compile(r"^[0-9A-Za-z.+_-]{1,64}$")

API_KEY_HEADER = "X-Api-Key"
"""The header Docling Serve reads its key from."""

PAGE_BREAK = "<!-- agenticos:page-break -->"
"""Asked of Docling as the markdown page separator, and split on to number pages."""

IMAGE_PLACEHOLDER = "<!-- image -->"
"""What Docling writes where a picture was, with `image_export_mode=placeholder`."""

DOCLING_MAX_WAIT_SECONDS = 3000
"""Docling's own deadline cap, so its refusal fires before the one-hour job timeout."""

POLL_WAIT_SECONDS = 10
POLL_TIMEOUT_SECONDS = 30.0
POLL_FLOOR_SECONDS = 2.0
"""Pause after a poll that came back at once: a server that ignores `wait` is not hammered."""
NAMED_PAGES_MAX = 10
"""Failed pages named in a refusal; a 1,000-page timeout lists one error per page."""
TRANSFER_TIMEOUT_SECONDS = 120.0
"""How long one upload or one result download may take."""

_CATEGORY = re.compile(r"[a-z_]{1,32}")
_PROVIDER = {"provider": "docling"}


class DoclingRefused(ExternalServiceError):
    """Docling's definitive answer: this document will not parse. The queue does not retry."""

    message = "Docling refused the document"
    code = "DOCLING_REFUSED"


class DoclingUnavailable(ExternalServiceError):
    """Docling did not answer well: the queue retries and the next attempt resumes."""

    message = "Docling is unavailable"
    code = "DOCLING_UNAVAILABLE"


class DoclingTaskGone(Exception):
    """Docling no longer knows a stored task (it restarted or forgot it): submit again."""


@dataclass(frozen=True)
class DoclingTarget:
    """Where a Docling Serve is and the key it takes, resolved for one use."""

    connection_id: UUID | None  # None only for the create-time Test
    base_url: str  # no trailing slash
    api_key: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class DoclingProbe:
    """What a Test learned: whether the address is a Docling Serve that accepts the key."""

    outcome: Literal["ok", "key_refused", "key_required", "unreachable", "not_docling"]
    version: str | None


async def probe(target: DoclingTarget, *, client: httpx.AsyncClient | None = None) -> DoclingProbe:
    """Check that `target` is a Docling Serve and that it accepts the key.

    `GET /version` answers without a key and names the server. A key is then proven
    with a status poll for a task id that cannot exist: an accepted key gets a 404, a
    refused or missing one a 401, and nothing is submitted or stored.
    """
    if client is not None:
        return await _probe(target, client)
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS, follow_redirects=False) as owned:
        return await _probe(target, owned)


async def _probe(target: DoclingTarget, client: httpx.AsyncClient) -> DoclingProbe:
    try:
        response = await client.get(f"{target.base_url}/version", timeout=PROBE_TIMEOUT_SECONDS)
    except httpx.HTTPError:
        return DoclingProbe("unreachable", None)
    if response.status_code != 200:
        return DoclingProbe("unreachable", None)
    named = _version_of(response)
    if named is None:
        return DoclingProbe("not_docling", None)
    # Shown to the operator, so only a plain version string is passed on: the
    # server is untrusted and a body of its choosing must not be echoed.
    version = named if _SAFE_VERSION.fullmatch(named) else None

    headers = {API_KEY_HEADER: target.api_key} if target.api_key else {}
    try:
        poll = await client.get(
            f"{target.base_url}/v1/status/poll/{uuid4()}",
            headers=headers,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        return DoclingProbe("unreachable", version)
    if poll.status_code == 404:
        return DoclingProbe("ok", version)
    if poll.status_code == 401:
        return DoclingProbe("key_refused" if target.api_key else "key_required", version)
    return DoclingProbe("unreachable", version)


def _version_of(response: httpx.Response) -> str | None:
    """The `docling-serve` version a `/version` body names, or None if it names none."""
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    version = body.get("docling-serve")
    return version if isinstance(version, str) else None


@dataclass(frozen=True)
class DoclingOptions:
    """What a collection asks Docling to do with a document."""

    do_ocr: bool
    force_ocr: bool
    ocr_languages: tuple[str, ...]
    ocr_preset: str
    table_mode: str
    max_pages: int
    timeout_seconds: float

    @property
    def wait_seconds(self) -> float:
        return min(self.timeout_seconds, DOCLING_MAX_WAIT_SECONDS)

    def form(self) -> list[tuple[str, str]]:
        """The form fields of a conversion; a name repeats where it takes a list."""
        return [
            ("to_formats", "md"),
            ("to_formats", "json"),
            ("image_export_mode", "placeholder"),
            ("md_page_break_placeholder", PAGE_BREAK),
            ("do_ocr", _flag(self.do_ocr)),
            ("force_ocr", _flag(self.force_ocr)),
            ("ocr_preset", self.ocr_preset),
            *[("ocr_lang", language) for language in self.ocr_languages],
            ("do_table_structure", "true"),
            ("table_mode", self.table_mode),
            ("page_range", "1"),
            ("page_range", str(self.max_pages)),
            ("document_timeout", str(int(self.wait_seconds))),
        ]


def _flag(value: bool) -> str:
    return "true" if value else "false"


def _headers(target: DoclingTarget) -> dict[str, str]:
    return {API_KEY_HEADER: target.api_key} if target.api_key else {}


def _unavailable(event: str, message: str, status: int | None = None) -> DoclingUnavailable:
    logger.warning("docling_%s", event, extra={"status": status})
    return DoclingUnavailable(message, details=dict(_PROVIDER))


def _refused(
    event: str, message: str, status: int | None = None, *, keep_task: bool = False
) -> DoclingRefused:
    logger.warning("docling_%s", event, extra={"status": status})
    details: dict[str, object] = dict(_PROVIDER)
    if keep_task:
        details["keep_task"] = True
    return DoclingRefused(message, details=details)


def _key_refused(target: DoclingTarget) -> DoclingRefused:
    message = (
        "Docling refused the connection's key. Check it, or replace it on the connection."
        if target.api_key
        else "Docling needs a key and the connection has none. Add one to the connection."
    )
    return _refused("key_refused", message, 401)


async def _send(
    client: httpx.AsyncClient,
    method: str,
    target: DoclingTarget,
    path: str,
    *,
    timeout: float,
    files: dict[str, tuple[str, bytes, str]] | None = None,
    data: dict[str, list[str]] | None = None,
) -> httpx.Response:
    """One call, with transport failures and shared statuses turned into our errors.

    A 404 and a 422 are handed back: only the caller knows what they mean.
    """
    try:
        response = await client.request(
            method,
            f"{target.base_url}{path}",
            headers=_headers(target),
            timeout=timeout,
            files=files,
            data=data,
        )
    except httpx.HTTPError as exc:
        raise _unavailable(type(exc).__name__.lower(), "Docling could not be reached.") from None
    status = response.status_code
    if status == 401:
        raise _key_refused(target)
    if status == 429 or status >= 500:
        raise _unavailable(
            "server_error", "Docling is busy or failing; it will be retried.", status
        )
    if status in (404, 422) or status < 400:
        return response
    raise _refused("client_error", f"Docling refused the request (HTTP {status}).", status)


def _json(response: httpx.Response) -> dict[str, object]:
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise _unavailable("bad_body", "Docling answered with something unreadable.")
    return body


async def submit(
    client: httpx.AsyncClient, target: DoclingTarget, filepath: Path, options: DoclingOptions
) -> str:
    """Start converting `filepath` and return the task id Docling gave it."""
    form: dict[str, list[str]] = {}
    for name, value in options.form():
        form.setdefault(name, []).append(value)
    mime = mimetypes.guess_type(filepath.name)[0] or "application/octet-stream"
    response = await _send(
        client,
        "POST",
        target,
        "/v1/convert/file/async",
        timeout=TRANSFER_TIMEOUT_SECONDS,
        files={"files": (filepath.name, filepath.read_bytes(), mime)},
        data=form,
    )
    if response.status_code == 404:
        raise _refused(
            "no_endpoint", "Docling has no conversion endpoint at this connection's address.", 404
        )
    if response.status_code == 422:
        raise _refused("bad_option", f"Docling refused the option {_option_named(response)}.", 422)
    task_id = _json(response).get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise _unavailable("no_task", "Docling accepted the file but gave no task.")
    return task_id


def _option_named(response: httpx.Response) -> str:
    """The field a 422 complains about; only its name, never the server's words."""
    try:
        loc = response.json()["detail"][0]["loc"][-1]
    except ValueError, KeyError, IndexError, TypeError:
        return "it was sent"
    return loc if isinstance(loc, str) and re.fullmatch(r"[a-z_]{1,40}", loc) else "it was sent"


async def wait_until_done(
    client: httpx.AsyncClient,
    target: DoclingTarget,
    task_id: str,
    *,
    deadline: float,
    budget_seconds: float,
    resumable: bool = True,
) -> None:
    """Poll until the task finishes; `deadline` is a `time.monotonic()` instant."""
    while True:
        if time.monotonic() >= deadline:
            minutes = max(1, round(budget_seconds / 60))
            raise _refused(
                "deadline",
                f"Docling did not finish within {minutes} minutes; it may still be queued or running."
                + (
                    " Retry the document to collect it; a longer timeout starts a new conversion."
                    if resumable
                    else ""
                ),
                keep_task=True,
            )
        asked = time.monotonic()
        response = await _send(
            client,
            "GET",
            target,
            f"/v1/status/poll/{task_id}?wait={POLL_WAIT_SECONDS}",
            timeout=POLL_TIMEOUT_SECONDS,
        )
        if response.status_code == 404:
            raise DoclingTaskGone
        state = _json(response).get("task_status")
        if state == "success":
            return
        if state == "failure":
            raise _refused(
                "task_failed",
                "Docling stopped with an internal error; its server log has the cause. "
                "Check the OCR languages and preset.",
            )
        if state not in ("pending", "started"):
            raise _unavailable("bad_state", "Docling reported a task state it should not.")
        if time.monotonic() - asked < 1.0:
            await anyio.sleep(POLL_FLOOR_SECONDS)


async def fetch_pages(
    client: httpx.AsyncClient, target: DoclingTarget, task_id: str
) -> list[tuple[int, str]]:
    """The text of each page that has any, as `(page number, markdown)`."""
    response = await _send(
        client, "GET", target, f"/v1/result/{task_id}", timeout=TRANSFER_TIMEOUT_SECONDS
    )
    if response.status_code == 404:
        raise DoclingTaskGone
    body = _json(response)
    status = body.get("status")
    errors = [e for e in _list(body.get("errors")) if isinstance(e, dict)]
    if status == "partial_success":
        raise _refused("partial", _partial_message(errors))
    if status != "success":
        raise _refused(
            "failed",
            f"Docling could not read this file ({_categories(errors) or 'no reason given'}).",
        )
    document = body.get("document")
    document = document if isinstance(document, dict) else {}
    markdown = document.get("md_content")
    if not isinstance(markdown, str):
        raise _unavailable("no_markdown", "Docling answered without any text.")
    parts = markdown.split(PAGE_BREAK)
    numbers = _page_numbers(document.get("json_content"))
    if not numbers:
        pages = [(1, markdown)]
    elif len(parts) == len(numbers):
        pages = list(zip(numbers, parts, strict=True))
    else:
        raise _refused(
            "page_mismatch",
            f"Docling returned {len(parts)} blocks of text for {len(numbers)} pages.",
        )
    cleaned = [(n, text.replace(IMAGE_PLACEHOLDER, "")) for n, text in pages]
    readable = [(n, text) for n, text in cleaned if has_indexable_text(text)]
    if not readable:
        # Raised here, as our own refusal, rather than left to `process_file`'s
        # generic no-text error: that one is a bare ValueError, which the queue
        # retries - a second full conversion - and the row would show only its type.
        raise _refused(
            "no_text",
            "Docling found no text in this file. If it is a scan, turn OCR on for this collection.",
        )
    return readable


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _page_numbers(json_content: object) -> list[int]:
    """Sorted distinct pages that carry an item, the pages the markdown has parts for."""
    if not isinstance(json_content, dict):
        return []
    found: set[int] = set()
    for kind in ("texts", "tables", "pictures"):
        for item in _list(json_content.get(kind)):
            for prov in _list(item.get("prov")) if isinstance(item, dict) else []:
                number = prov.get("page_no") if isinstance(prov, dict) else None
                if isinstance(number, int) and not isinstance(number, bool):
                    found.add(number)
    return sorted(found)


def _categories(errors: list[dict[str, object]]) -> str:
    """Docling's error categories, as a sorted list of words; its message text is dropped."""
    words = {
        c for e in errors if isinstance(c := e.get("category"), str) and _CATEGORY.fullmatch(c)
    }
    return ", ".join(sorted(words)) or ""


def _partial_message(errors: list[dict[str, object]]) -> str:
    numbers = sorted(
        {n for e in errors if isinstance(n := e.get("page_no"), int) and not isinstance(n, bool)}
    )
    named = ", ".join(map(str, numbers[:NAMED_PAGES_MAX]))
    more = len(numbers) - NAMED_PAGES_MAX
    where = (
        (f"pages {named}" + (f" and {more} more" if more > 0 else "")) if numbers else "some pages"
    )
    categories = _categories(errors)
    return f"Docling could not read {where}" + (f" ({categories})" if categories else "") + "."


class ParserTask(TypedDict):
    """The conversion a document is waiting on, kept so a retry collects it."""

    provider: str
    task_id: str
    fingerprint: str
    submitted_at: str


class ParserTaskStore(Protocol):
    """Where a parse keeps its task between attempts. A write returning False was fenced out."""

    async def load(self) -> ParserTask | None: ...

    async def save(self, task: ParserTask) -> bool: ...

    async def clear(self) -> bool: ...


class DoclingParser(BaseDocumentParser):
    """Parses through the organization's Docling Serve, resuming a task it already started."""

    allowed = sorted(DOCLING_PDF_FORMATS)

    def __init__(
        self,
        target: DoclingTarget,
        options: DoclingOptions,
        task_store: ParserTaskStore | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.target = target
        self.options = options
        self.task_store = task_store
        self._client = client

    def _fingerprint(self, content_hash: str | None) -> str:
        """What a stored task must match to be collected; never the key."""
        identity = {
            "connection_id": str(self.target.connection_id),
            "base_url": self.target.base_url,
            "form": self.options.form(),
            "content": content_hash,
        }
        return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()

    async def parse(self, filepath: Path) -> Document:
        if not self.is_extension_allowed(filepath):
            raise ValueError(f"Extension {filepath.suffix} not supported by Docling")
        if self._client is not None:
            return await self._parse(self._client, filepath)
        async with httpx.AsyncClient(follow_redirects=False) as client:
            return await self._parse(client, filepath)

    async def _parse(self, client: httpx.AsyncClient, filepath: Path) -> Document:
        meta = self.get_document_metadata(filepath)
        fingerprint = self._fingerprint(meta.content_hash)
        store = self.task_store
        wait = self.options.wait_seconds
        deadline = time.monotonic() + wait
        stored = await store.load() if store else None
        task_id = stored["task_id"] if stored and stored["fingerprint"] == fingerprint else None
        for _ in range(2):
            if task_id is None:
                task_id = await submit(client, self.target, filepath, self.options)
                if store:
                    await store.save(
                        {
                            "provider": "docling",
                            "task_id": task_id,
                            "fingerprint": fingerprint,
                            "submitted_at": datetime.now(UTC).isoformat(),
                        }
                    )
            try:
                await wait_until_done(
                    client,
                    self.target,
                    task_id,
                    deadline=deadline,
                    budget_seconds=wait,
                    resumable=store is not None,
                )
                pages = await fetch_pages(client, self.target, task_id)
            except DoclingTaskGone:
                task_id = None
                continue
            except DoclingRefused as exc:
                if store and not (exc.details or {}).get("keep_task"):
                    await store.clear()
                raise
            if store:
                await store.clear()
            return Document(
                pages=[DocumentPage(page_num=n, content=text) for n, text in pages], metadata=meta
            )
        raise _unavailable("task_gone", "Docling lost the task twice; it will be retried.")
