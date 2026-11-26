"""The Docling Serve client: what a connection's Test reads off the server.

Values are the ones measured against Docling Serve v1.39.0 (`GET /version` answers
without a key; an unknown task id is a 404 once the key is accepted and a 401
before).
"""

import dataclasses
import json
import time
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest

from app.services.rag import docling
from app.services.rag.config import RAGSettings
from app.services.rag.docling import (
    PAGE_BREAK,
    DoclingOptions,
    DoclingRefused,
    DoclingTarget,
    DoclingTaskGone,
    DoclingUnavailable,
    fetch_pages,
    submit,
    wait_until_done,
)
from app.services.rag.documents import DocumentProcessor

pytestmark = pytest.mark.anyio

_BASE = "http://docling.internal:5001"


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


def _target(api_key: str | None = None) -> DoclingTarget:
    return DoclingTarget(connection_id=None, base_url=_BASE, api_key=api_key)


def _server(*, poll_status: int, version: dict[str, str] | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/version":
            assert "x-api-key" not in request.headers
            return httpx.Response(200, json=version or {"docling-serve": "1.39.0"})
        assert request.url.path.startswith("/v1/status/poll/")
        return httpx.Response(poll_status, json={})

    return httpx.MockTransport(handle)


async def test_probe_ok_reports_version() -> None:
    async with _client(_server(poll_status=404)) as client:
        result = await docling.probe(_target("k"), client=client)

    assert (result.outcome, result.version) == ("ok", "1.39.0")


async def test_probe_sends_the_key_as_x_api_key_on_the_poll() -> None:
    seen: list[str | None] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/version":
            return httpx.Response(200, json={"docling-serve": "1.39.0"})
        seen.append(request.headers.get("x-api-key"))
        return httpx.Response(404)

    async with _client(httpx.MockTransport(handle)) as client:
        await docling.probe(_target("secret-key"), client=client)

    assert seen == ["secret-key"]


@pytest.mark.security
async def test_probe_key_refused() -> None:
    async with _client(_server(poll_status=401)) as client:
        result = await docling.probe(_target("stale"), client=client)

    assert (result.outcome, result.version) == ("key_refused", "1.39.0")


@pytest.mark.security
async def test_probe_key_required_without_key() -> None:
    async with _client(_server(poll_status=401)) as client:
        result = await docling.probe(_target(), client=client)

    assert result.outcome == "key_required"


@pytest.mark.parametrize(
    "failure", [httpx.ConnectError("boom"), httpx.ReadTimeout("slow")], ids=["connect", "timeout"]
)
async def test_probe_unreachable_on_connect_error(failure: Exception) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise failure

    async with _client(httpx.MockTransport(handle)) as client:
        result = await docling.probe(_target(), client=client)

    assert (result.outcome, result.version) == ("unreachable", None)


async def test_probe_unreachable_on_a_non_200_version() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(502))
    async with _client(transport) as client:
        result = await docling.probe(_target(), client=client)

    assert result.outcome == "unreachable"


async def test_probe_unreachable_when_the_poll_fails() -> None:
    async with _client(_server(poll_status=500)) as client:
        result = await docling.probe(_target("k"), client=client)

    assert (result.outcome, result.version) == ("unreachable", "1.39.0")


async def test_probe_unreachable_when_the_poll_cannot_connect() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/version":
            return httpx.Response(200, json={"docling-serve": "1.39.0"})
        raise httpx.ConnectError("gone")

    async with _client(httpx.MockTransport(handle)) as client:
        result = await docling.probe(_target(), client=client)

    assert result.outcome == "unreachable"


@pytest.mark.parametrize(
    "body", [{"version": "1"}, ["docling-serve"], {"docling-serve": 3}], ids=str
)
async def test_probe_not_docling_without_version_field(body: object) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    async with _client(transport) as client:
        result = await docling.probe(_target(), client=client)

    assert (result.outcome, result.version) == ("not_docling", None)


async def test_probe_not_docling_on_a_body_that_is_not_json() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="<html>"))
    async with _client(transport) as client:
        result = await docling.probe(_target(), client=client)

    assert result.outcome == "not_docling"


async def test_probe_builds_its_own_client_when_none_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = httpx.AsyncClient
    transport = _server(poll_status=404)
    monkeypatch.setattr(
        docling.httpx, "AsyncClient", lambda **kwargs: real(transport=transport, **kwargs)
    )

    result = await docling.probe(_target("k"))

    assert result.outcome == "ok"


def test_the_target_hides_its_key_from_repr() -> None:
    assert "secret-key" not in repr(_target("secret-key"))


@pytest.mark.parametrize("version", ["x" * 65, "1.0 <script>", "", "1.39.0\n"], ids=str)
async def test_probe_does_not_echo_an_odd_version(version: str) -> None:
    async with _client(_server(poll_status=404, version={"docling-serve": version})) as client:
        result = await docling.probe(_target("k"), client=client)

    assert result.version is None


# Converting: the shapes below are the ones measured against v1.39.0.

_HASH_TEXT = "Internal error in stage 7a3f9c1e5b2d (see http://docling.internal:5001/log)"


_DEFAULT_OPTIONS = DoclingOptions(
    do_ocr=True,
    force_ocr=False,
    ocr_languages=(),
    ocr_preset="auto",
    table_mode="accurate",
    max_pages=1000,
    timeout_seconds=600.0,
)


def _options(**changes: Any) -> DoclingOptions:
    return dataclasses.replace(_DEFAULT_OPTIONS, **changes)


def _prov(*pages: int) -> list[dict[str, int]]:
    return [{"page_no": p} for p in pages]


def _result(
    markdown: str,
    *,
    texts: tuple[int, ...] = (),
    tables: tuple[int, ...] = (),
    pictures: tuple[int, ...] = (),
    status: str = "success",
    errors: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "errors": errors or [],
        "document": {
            "md_content": markdown,
            "json_content": {
                "texts": [{"prov": _prov(p)} for p in texts],
                "tables": [{"prov": _prov(p)} for p in tables],
                "pictures": [{"prov": _prov(p)} for p in pictures],
            },
        },
    }


def _once(status: int, body: object) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, json=body))


async def _pages(body: dict[str, object]) -> list[tuple[int, str]]:
    async with _client(_once(200, body)) as client:
        return await fetch_pages(client, _target(), "t1")


def test_options_form_matches_contract() -> None:
    form = _options(ocr_languages=("en", "de"), force_ocr=True, max_pages=40).form()

    assert form == [
        ("to_formats", "md"),
        ("to_formats", "json"),
        ("image_export_mode", "placeholder"),
        ("md_page_break_placeholder", "<!-- agenticos:page-break -->"),
        ("do_ocr", "true"),
        ("force_ocr", "true"),
        ("ocr_preset", "auto"),
        ("ocr_lang", "en"),
        ("ocr_lang", "de"),
        ("do_table_structure", "true"),
        ("table_mode", "accurate"),
        ("page_range", "1"),
        ("page_range", "40"),
        ("document_timeout", "600"),
    ]


def test_options_without_languages_omit_ocr_lang_and_cap_the_deadline() -> None:
    form = _options(do_ocr=False, timeout_seconds=99999.0).form()

    assert "ocr_lang" not in [name for name, _ in form]
    assert ("do_ocr", "false") in form
    assert ("document_timeout", "3000") in form


async def test_page_range_sent_as_two_values(tmp_path: Path) -> None:
    sent: list[bytes] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        return httpx.Response(200, json={"task_id": "t1"})

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    async with _client(httpx.MockTransport(handle)) as client:
        task = await submit(client, _target(), pdf, _options(max_pages=7))

    body = sent[0]
    assert task == "t1"
    assert body.count(b'name="page_range"') == 2
    assert b"\r\n\r\n1\r\n" in body and b"\r\n\r\n7\r\n" in body
    assert b'name="files"; filename="a.pdf"' in body


async def test_submit_sends_key_header_only_when_set(tmp_path: Path) -> None:
    seen: list[str | None] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("x-api-key"))
        return httpx.Response(200, json={"task_id": "t1"})

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    async with _client(httpx.MockTransport(handle)) as client:
        await submit(client, _target("k-1"), pdf, _options())
        await submit(client, _target(), pdf, _options())

    assert seen == ["k-1", None]


@pytest.mark.security
@pytest.mark.parametrize("key", ["k-1", None])
async def test_401_is_refused_not_retried(tmp_path: Path, key: str | None) -> None:
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    async with _client(_once(401, {"detail": "Unauthorized"})) as client:
        with pytest.raises(DoclingRefused) as raised:
            await submit(client, _target(key), pdf, _options())
        with pytest.raises(DoclingRefused):
            await wait_until_done(
                client, _target(key), "t1", deadline=time.monotonic() + 5, budget_seconds=5
            )
        with pytest.raises(DoclingRefused):
            await fetch_pages(client, _target(key), "t1")

    assert not isinstance(raised.value, DoclingUnavailable)
    assert "key" in raised.value.message


async def test_422_names_the_option_only(tmp_path: Path) -> None:
    detail = {
        "detail": [{"loc": ["body", "table_mode"], "msg": "Input should be 'fast' " + _HASH_TEXT}]
    }
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    async with _client(_once(422, detail)) as client:
        with pytest.raises(DoclingRefused) as raised:
            await submit(client, _target(), pdf, _options())

    assert "table_mode" in raised.value.message
    assert "7a3f9c1e5b2d" not in str(raised.value)


async def test_422_without_a_readable_field_still_refuses(tmp_path: Path) -> None:
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    async with _client(_once(422, {"detail": "nope"})) as client:
        with pytest.raises(DoclingRefused, match="refused the option it was sent"):
            await submit(client, _target(), pdf, _options())


@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_5xx_and_connect_error_are_unavailable(tmp_path: Path, status: int) -> None:
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    async with _client(_once(status, {})) as client:
        with pytest.raises(DoclingUnavailable):
            await submit(client, _target(), pdf, _options())

    def refuse_connection(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom http://docling.internal:5001")

    async with _client(httpx.MockTransport(refuse_connection)) as client:
        with pytest.raises(DoclingUnavailable) as raised:
            await submit(client, _target(), pdf, _options())
    assert "docling.internal" not in str(raised.value)


async def test_other_client_errors_and_odd_bodies(tmp_path: Path) -> None:
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    async with _client(_once(413, {})) as client:
        with pytest.raises(DoclingRefused, match="HTTP 413"):
            await submit(client, _target(), pdf, _options())
    async with _client(_once(200, ["not", "an", "object"])) as client:
        with pytest.raises(DoclingUnavailable):
            await submit(client, _target(), pdf, _options())
    async with _client(_once(200, {"task_id": ""})) as client:
        with pytest.raises(DoclingUnavailable):
            await submit(client, _target(), pdf, _options())
    async with _client(
        httpx.MockTransport(lambda request: httpx.Response(200, content=b"<html>"))
    ) as client:
        with pytest.raises(DoclingUnavailable):
            await submit(client, _target(), pdf, _options())


async def test_wait_polls_until_success() -> None:
    states = iter(["pending", "started", "success"])
    waits: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        waits.append(request.url.params["wait"])
        return httpx.Response(200, json={"task_status": next(states)})

    async with _client(httpx.MockTransport(handle)) as client:
        await wait_until_done(
            client, _target(), "t1", deadline=time.monotonic() + 60, budget_seconds=60
        )

    assert waits == ["10", "10", "10"]


async def test_task_failure_is_refused() -> None:
    body = {"task_status": "failure", "error_message": "Internal processing error."}
    async with _client(_once(200, body)) as client:
        with pytest.raises(DoclingRefused) as raised:
            await wait_until_done(
                client, _target(), "t1", deadline=time.monotonic() + 60, budget_seconds=60
            )

    assert "OCR languages and preset" in raised.value.message
    assert not (raised.value.details or {}).get("keep_task")


async def test_unknown_task_state_is_unavailable() -> None:
    async with _client(_once(200, {"task_status": "weird"})) as client:
        with pytest.raises(DoclingUnavailable):
            await wait_until_done(
                client, _target(), "t1", deadline=time.monotonic() + 60, budget_seconds=60
            )


async def test_poll_404_is_task_gone() -> None:
    async with _client(_once(404, {"detail": "Task not found."})) as client:
        with pytest.raises(DoclingTaskGone):
            await wait_until_done(
                client, _target(), "t1", deadline=time.monotonic() + 60, budget_seconds=60
            )
        with pytest.raises(DoclingTaskGone):
            await fetch_pages(client, _target(), "t1")


async def test_deadline_refusal_keeps_task() -> None:
    async with _client(_once(200, {"task_status": "pending"})) as client:
        with pytest.raises(DoclingRefused) as raised:
            await wait_until_done(
                client, _target(), "t1", deadline=time.monotonic() - 1, budget_seconds=600
            )

    assert raised.value.message == (
        "Docling did not finish within 10 minutes; it may still be queued or running. "
        "Retry the document to collect it; a longer timeout starts a new conversion."
    )
    assert raised.value.details == {"provider": "docling", "keep_task": True}


@pytest.mark.parametrize("status", ["failure", "skipped", "mystery"])
async def test_failure_inside_successful_task_is_refused(status: str) -> None:
    body = {
        "status": status,
        "errors": [{"category": "backend_failure", "page_no": None, "error_message": _HASH_TEXT}],
        "document": {"md_content": "", "json_content": None},
    }

    with pytest.raises(DoclingRefused) as raised:
        await _pages(body)

    assert raised.value.message == "Docling could not read this file (backend_failure)."


async def test_failure_without_a_reason_says_so() -> None:
    with pytest.raises(DoclingRefused, match=r"\(no reason given\)"):
        await _pages({"status": "failure", "errors": "x"})


async def test_partial_success_names_pages() -> None:
    errors = [
        {"category": "timeout", "page_no": 5, "error_message": "document timeout exceeded"},
        {"category": "timeout", "page_no": 2, "error_message": "document timeout exceeded"},
        {"category": "timeout", "page_no": 2, "error_message": "x"},
        {"category": "Bad Category!", "page_no": None, "error_message": "x"},
    ]
    with pytest.raises(DoclingRefused) as raised:
        await _pages(_result("x", status="partial_success", errors=errors))
    assert raised.value.message == "Docling could not read pages 2, 5 (timeout)."

    with pytest.raises(DoclingRefused) as raised:
        await _pages(_result("x", status="partial_success"))
    assert raised.value.message == "Docling could not read some pages."


async def test_a_long_partial_failure_names_ten_pages_and_counts_the_rest() -> None:
    """A 1,000-page timeout reports one error per page; the refusal stays short."""
    errors = [{"category": "timeout", "page_no": n} for n in range(1, 1001)]
    with pytest.raises(DoclingRefused) as raised:
        await _pages(_result("x", status="partial_success", errors=errors))
    assert raised.value.message == (
        "Docling could not read pages 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 and 990 more (timeout)."
    )


async def test_pages_split_on_marker() -> None:
    md = f"one{PAGE_BREAK}two{PAGE_BREAK}three"

    pages = await _pages(_result(md, texts=(1, 2, 3)))

    assert pages == [(1, "one"), (2, "two"), (3, "three")]


async def test_blank_page_skipped_numbering_follows_provenance() -> None:
    """`mixed5.pdf`: a cover that is only an image, a blank page 3, text on 2, 4, 5."""
    md = f"cover text{PAGE_BREAK}two{PAGE_BREAK}four{PAGE_BREAK}five"

    pages = await _pages(_result(md, texts=(1, 2, 4, 5)))

    assert [n for n, _ in pages] == [1, 2, 4, 5]
    assert [t for _, t in pages] == ["cover text", "two", "four", "five"]


async def test_picture_and_table_pages_count() -> None:
    """`pic_table.pdf`: text on 1, a picture on 2, a drawn table on 3."""
    md = f"intro{PAGE_BREAK}{docling.IMAGE_PLACEHOLDER}{PAGE_BREAK}| a | b |"

    pages = await _pages(_result(md, texts=(1,), pictures=(2,), tables=(3,)))

    assert [n for n, _ in pages] == [1, 3]


async def test_picture_only_page_is_not_indexed() -> None:
    md = f"intro{PAGE_BREAK}{docling.IMAGE_PLACEHOLDER}{PAGE_BREAK}| a | b |"

    pages = await _pages(_result(md, texts=(1,), pictures=(2,), tables=(3,)))

    assert pages == [(1, "intro"), (3, "| a | b |")]


async def test_unpaged_format_is_one_page() -> None:
    for json_content in ({}, "nope"):
        body: dict[str, object] = {
            "status": "success",
            "errors": [],
            "document": {"md_content": "# Title", "json_content": json_content},
        }

        assert await _pages(body) == [(1, "# Title")]


async def test_page_count_mismatch_refused() -> None:
    with pytest.raises(DoclingRefused) as raised:
        await _pages(_result(f"a{PAGE_BREAK}b", texts=(1, 2, 3)))

    assert raised.value.message == "Docling returned 2 blocks of text for 3 pages."


async def test_a_success_with_no_markdown_is_unavailable() -> None:
    with pytest.raises(DoclingUnavailable):
        await _pages({"status": "success", "document": None})


async def test_provenance_that_is_not_a_page_is_ignored() -> None:
    body: dict[str, object] = {
        "status": "success",
        "document": {
            "md_content": "only",
            "json_content": {
                "texts": ["x", {"prov": ["y", {"page_no": True}, {"page_no": 4}]}, {"prov": "z"}]
            },
        },
    }

    assert await _pages(body) == [(4, "only")]


async def test_ocr_off_scan_is_refused_with_the_ocr_advice(tmp_path: Path) -> None:
    """`mixed5.pdf` with OCR off: every page is a picture, so nothing is left to index.

    Refused as Docling's own refusal, not left to `process_file`'s bare ValueError:
    that one is retried by the queue - a second full conversion - and the row would
    show only its type, not the advice to turn OCR on.
    """
    md = f"{docling.IMAGE_PLACEHOLDER}{PAGE_BREAK}{docling.IMAGE_PLACEHOLDER}"
    body = _result(md, pictures=(1, 2))
    processor = DocumentProcessor(settings=RAGSettings())
    processor.pdf_parser = _ParserOver(body)
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"%PDF")

    with pytest.raises(DoclingRefused) as raised:
        await processor.process_file(scan)
    assert raised.value.message == (
        "Docling found no text in this file. If it is a scan, turn OCR on for this collection."
    )


async def test_a_poll_that_returns_at_once_waits_before_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server that ignores `wait` is not polled back to back until the deadline."""
    states = iter(["pending", "success"])
    pauses: list[float] = []

    async def pause(seconds: float) -> None:
        pauses.append(seconds)

    monkeypatch.setattr(docling.anyio, "sleep", pause)

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"task_status": next(states)})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await wait_until_done(
            client, _target(), "t1", deadline=time.monotonic() + 60, budget_seconds=60
        )

    assert pauses == [docling.POLL_FLOOR_SECONDS]


async def test_a_poll_that_waited_on_the_server_is_not_slowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A long-poll that held the request is answered at once with the next poll."""
    states = iter(["started", "success"])
    pauses: list[float] = []
    real_sleep = anyio.sleep

    async def pause(seconds: float) -> None:
        pauses.append(seconds)

    async def handle(request: httpx.Request) -> httpx.Response:
        await real_sleep(1.05)
        return httpx.Response(200, json={"task_status": next(states)})

    monkeypatch.setattr(docling.anyio, "sleep", pause)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await wait_until_done(
            client, _target(), "t1", deadline=time.monotonic() + 60, budget_seconds=60
        )

    assert pauses == []


class _ParserOver(docling.DoclingParser):
    """A Docling parser whose server answers one finished task with `result`."""

    def __init__(self, result: dict[str, object]) -> None:
        def handle(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(200, json={"task_id": "t1"})
            if "status" in request.url.path:
                return httpx.Response(200, json={"task_status": "success"})
            return httpx.Response(200, json=result)

        super().__init__(
            _target(), _options(), client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
        )


@pytest.mark.security
async def test_refusal_never_carries_docling_text() -> None:
    errors = [{"category": "backend_failure", "page_no": None, "error_message": _HASH_TEXT}]
    for body in (
        _result("x", status="failure", errors=errors),
        _result("x", status="partial_success", errors=errors),
    ):
        with pytest.raises(DoclingRefused) as raised:
            await _pages(body)
        shown = f"{raised.value} {raised.value.message} {raised.value.details}"
        assert "7a3f9c1e5b2d" not in shown
        assert "docling.internal" not in shown
        assert raised.value.details == {"provider": "docling"}

    async with _client(_once(200, {"task_status": "failure", "error_message": _HASH_TEXT})) as c:
        with pytest.raises(DoclingRefused) as raised:
            await wait_until_done(
                c, _target("sekret"), "t1", deadline=time.monotonic() + 5, budget_seconds=5
            )
    assert "7a3f9c1e5b2d" not in str(raised.value) and "sekret" not in str(raised.value)
    assert json.dumps(raised.value.details) == '{"provider": "docling"}'


@pytest.mark.security
async def test_a_failing_call_logs_only_its_class_and_status(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    with caplog.at_level("WARNING", logger="app.services.rag.docling"):
        async with _client(_once(500, {"detail": _HASH_TEXT})) as client:
            with pytest.raises(DoclingUnavailable):
                await submit(client, _target("sekret"), pdf, _options())

    assert caplog.records and all(getattr(r, "status", None) == 500 for r in caplog.records)
    assert "7a3f9c1e5b2d" not in caplog.text and "sekret" not in caplog.text
    assert "docling.internal" not in caplog.text


async def test_a_404_on_submit_means_no_endpoint_there(tmp_path: Path) -> None:
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    async with _client(_once(404, {"detail": "Not Found"})) as client:
        with pytest.raises(DoclingRefused) as raised:
            await submit(client, _target(), pdf, _options())

    assert raised.value.message == (
        "Docling has no conversion endpoint at this connection's address."
    )
    assert "docling.internal" not in str(raised.value)


@pytest.mark.parametrize(
    ("resumable", "ending"),
    [
        (True, " Retry the document to collect it; a longer timeout starts a new conversion."),
        (False, ""),
    ],
)
async def test_deadline_wording_depends_on_whether_the_task_is_kept(
    resumable: bool, ending: str
) -> None:
    async with _client(_once(200, {"task_status": "pending"})) as client:
        with pytest.raises(DoclingRefused) as raised:
            await wait_until_done(
                client,
                _target(),
                "t1",
                deadline=time.monotonic() - 1,
                budget_seconds=600,
                resumable=resumable,
            )

    assert raised.value.message == (
        "Docling did not finish within 10 minutes; it may still be queued or running." + ending
    )
