"""PDF exports retain App audience checks and the renderer's isolation."""

import base64
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pymupdf
import pytest

from app.agents.audience import RunAudience
from app.agents.capabilities.artifacts._toolset import build_artifacts_toolset
from app.agents.deps import AgentDeps
from app.core.exceptions import ConfigurationError, ExternalServiceError, NotFoundError
from app.services import artifact_render as renderer
from app.services.artifact import ArtifactPreview
from app.services.artifact_render import CdpPayload, Rendered, RenderRequest
from tests.test_artifact_render import FakeBrowser
from tests.test_artifacts_capability import _ctx, _deps, _preview

pytestmark = pytest.mark.anyio


def pdf(pages: int = 2) -> bytes:
    with pymupdf.open() as document:
        for index in range(pages):
            page = document.new_page()
            page.insert_text((40, 40), f"Slide {index + 1}")
        return document.tobytes()


class PrintBrowser(FakeBrowser):
    def __init__(self, data: bytes) -> None:
        super().__init__(events=[("Page.loadEventFired", {}, "PAGE")])
        self.data = data

    async def send(
        self, method: str, params: CdpPayload | None = None, *, session_id: str | None = None
    ) -> CdpPayload:
        result = await super().send(method, params, session_id=session_id)
        if method == "Page.printToPDF":
            return {"stream": "pdf-stream"}
        if method == "IO.read":
            return {
                "data": base64.b64encode(self.data).decode(),
                "base64Encoded": True,
                "eof": True,
            }
        return result


@pytest.mark.parametrize("paper", ["a4", "slides"])
async def test_real_pdf_uses_a_separate_context_and_closes_the_stream(
    paper: Literal["a4", "slides"], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(renderer.settings, "ARTIFACT_RENDER_CDP_URL", "http://renderer:9222")
    monkeypatch.setattr(renderer, "SETTLE_SECONDS", 0)
    browser = PrintBrowser(pdf())

    async def connect(endpoint: str) -> PrintBrowser:
        return browser

    request = RenderRequest(
        document=b"<!doctype html><h1>Slides</h1>",
        nonce="n",
        bindings=None,
        output="pdf",
        paper=paper,
    )
    found = await renderer.render(request, connect=connect)
    assert found.pdf == browser.data and found.image is None
    assert browser.commands("Page.captureScreenshot") == []
    options = browser.commands("Page.printToPDF")[0][0]
    assert options is not None and options["pageRanges"] == "1-51"
    assert options["paperWidth"] == (13.333 if paper == "slides" else 8.2677)
    assert browser.commands("IO.close")[0] == ({"handle": "pdf-stream"}, "PAGE")
    assert browser.commands("IO.read")[0][1] == "PAGE"
    assert browser.closed and browser.commands("Target.disposeBrowserContext")


@pytest.mark.parametrize("data", [b"", b"<html>not PDF</html>", pdf(51)])
def test_invalid_or_truncated_exports_are_refused(data: bytes) -> None:
    with pytest.raises(ExternalServiceError):
        renderer._checked_pdf(data)


@pytest.mark.security
async def test_print_document_keeps_the_sandbox_and_bound_data() -> None:
    request = RenderRequest(
        document=b"<!doctype html><h1>Print</h1>",
        nonce="n",
        bindings=_preview().bindings,
        output="pdf",
    )
    drawing = renderer._Render(request, Rendered(), PrintBrowser(pdf()))
    served = await drawing.serve(drawing.shell, "GET")
    assert served is not None
    assert "sandbox allow-scripts allow-modals" in served.headers["Content-Security-Policy"]
    assert "connect-src 'none'" in served.headers["Content-Security-Policy"]
    assert b"event.source!==window" in served.body
    assert b"agenticos:data" in served.body and b"tickets" in served.body
    assert await drawing.serve("https://untrusted.example", "GET") is None


async def exported(
    *,
    source: ArtifactPreview | Exception | None = None,
    drawn: Rendered | Exception | None = None,
    workspace: MagicMock | None = None,
    deps: AgentDeps | None = None,
    filename: str | None = None,
) -> tuple[str, MagicMock]:
    workspace = workspace or MagicMock(attached=True, write_bytes=AsyncMock())
    tool = build_artifacts_toolset(table_grants={}).tools["export_artifact"].function
    with (
        patch(
            "app.services.artifact.preview_source",
            AsyncMock(
                side_effect=source if isinstance(source, Exception) else None,
                return_value=source or _preview(binding_names=[], bindings=None),
            ),
        ),
        patch(
            "app.services.artifact_render.render",
            AsyncMock(
                side_effect=drawn if isinstance(drawn, Exception) else None,
                return_value=drawn or Rendered(pdf=pdf()),
            ),
        ),
    ):
        result = await tool(
            _ctx(deps or _deps(), workspace=workspace),
            name="weekly-report",
            filename=filename,
            paper="slides",
        )
    assert isinstance(result, str)
    return result, workspace


async def test_tool_writes_actual_bytes_to_a_unique_file() -> None:
    result, workspace = await exported()
    path, data = workspace.write_bytes.await_args.args
    assert path.startswith("weekly-report-") and path.endswith(".pdf")
    assert "version 5" in result and path in result
    assert renderer._checked_pdf(data) == data


@pytest.mark.security
async def test_room_export_refuses_withheld_bindings() -> None:
    deps = _deps()
    assert deps.audience is not None
    deps.audience = RunAudience(user_id=deps.audience.user_id, room_key="mattermost:room")
    result, workspace = await exported(source=_preview(bindings={}), deps=deps)
    assert "bound data is unavailable" in result
    workspace.write_bytes.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize("filename", ["../report.pdf", "/outside/report.pdf", "report.html"])
async def test_output_filenames_cannot_escape_the_workspace(filename: str) -> None:
    result, workspace = await exported(filename=filename)
    assert "plain filename" in result
    workspace.write_bytes.assert_not_awaited()


@pytest.mark.parametrize(
    "drawn",
    [
        Rendered(timed_out=True),
        Rendered(),
        Rendered(pdf=b"pdf", errors=["bad script"]),
        Rendered(pdf=b"pdf", blocked=["https://x.example"]),
        ConfigurationError(message="Renderer missing"),
        ExternalServiceError(message="Renderer unavailable"),
    ],
)
async def test_failed_exports_never_create_a_misleading_file(drawn: Rendered | Exception) -> None:
    result, workspace = await exported(drawn=drawn)
    assert "not exported" in result
    workspace.write_bytes.assert_not_awaited()


@pytest.mark.security
async def test_unavailable_workspace_reader_and_source_are_controlled_refusals() -> None:
    result, _ = await exported(workspace=MagicMock(attached=False))
    assert "attached workspace" in result
    result, _ = await exported(deps=_deps(audience=RunAudience()))
    assert "not available" in result
    result, _ = await exported(source=NotFoundError(message="No such page"))
    assert result == "No such page"


@pytest.mark.parametrize("response", [{}, {"stream": ""}])
async def test_missing_pdf_stream_is_an_explicit_renderer_failure(
    response: CdpPayload, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(renderer.settings, "ARTIFACT_RENDER_CDP_URL", "http://renderer:9222")
    monkeypatch.setattr(renderer, "SETTLE_SECONDS", 0)
    browser = PrintBrowser(pdf())
    original = browser.send

    async def send(
        method: str, params: CdpPayload | None = None, *, session_id: str | None = None
    ) -> CdpPayload:
        result = await original(method, params, session_id=session_id)
        return response if method == "Page.printToPDF" else result

    browser.send = send
    with pytest.raises(ExternalServiceError):
        await renderer.render(
            RenderRequest(document=b"<h1>Report</h1>", nonce="n", bindings=None, output="pdf"),
            connect=AsyncMock(return_value=browser),
        )
    assert browser.closed


@pytest.mark.parametrize("chunk", [{"data": None}, {"data": "???", "base64Encoded": True}])
async def test_malformed_pdf_chunks_still_release_the_stream(
    chunk: CdpPayload, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(renderer.settings, "ARTIFACT_RENDER_CDP_URL", "http://renderer:9222")
    monkeypatch.setattr(renderer, "SETTLE_SECONDS", 0)
    browser = PrintBrowser(pdf())
    original = browser.send

    async def send(
        method: str, params: CdpPayload | None = None, *, session_id: str | None = None
    ) -> CdpPayload:
        result = await original(method, params, session_id=session_id)
        return chunk if method == "IO.read" else result

    browser.send = send
    with pytest.raises(ExternalServiceError):
        await renderer.render(
            RenderRequest(document=b"<h1>Report</h1>", nonce="n", bindings=None, output="pdf"),
            connect=AsyncMock(return_value=browser),
        )
    assert browser.commands("IO.close") and browser.closed


async def test_pdf_byte_limit_is_enforced_before_a_file_is_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(renderer.settings, "ARTIFACT_RENDER_CDP_URL", "http://renderer:9222")
    monkeypatch.setattr(renderer, "SETTLE_SECONDS", 0)
    monkeypatch.setattr(renderer, "PDF_MAX_BYTES", 10)
    browser = PrintBrowser(pdf())
    with pytest.raises(ExternalServiceError, match="20 MB"):
        await renderer.render(
            RenderRequest(document=b"<h1>Report</h1>", nonce="n", bindings=None, output="pdf"),
            connect=AsyncMock(return_value=browser),
        )
    assert browser.commands("IO.close") and browser.closed


async def test_a_missing_agent_and_a_refused_workspace_write_never_claim_an_export():
    result, workspace = await exported(deps=AgentDeps())
    assert "agent" in result.lower()
    workspace.write_bytes.assert_not_awaited()
    workspace = MagicMock(attached=True, write_bytes=AsyncMock(side_effect=PermissionError()))
    result, _ = await exported(workspace=workspace)
    assert "PDF not saved" in result


def test_a_corrupted_pdf_stream_is_a_controlled_refusal():
    with pytest.raises(ExternalServiceError, match="invalid PDF"):
        renderer._checked_pdf(b"%PDF-broken")


def test_a_non_pdf_document_reported_by_the_reader_is_refused(monkeypatch):
    opened = MagicMock()
    opened.__enter__.return_value.is_pdf = False
    monkeypatch.setattr(pymupdf, "open", MagicMock(return_value=opened))
    with pytest.raises(ExternalServiceError, match="invalid PDF"):
        renderer._checked_pdf(b"%PDF-pretending")


@pytest.mark.parametrize("close_error", [None, renderer.CdpError("already closed"), TimeoutError()])
async def test_pdf_reads_all_stream_chunks_and_disposes_the_context_if_stream_close_fails(
    monkeypatch, close_error
):
    monkeypatch.setattr(renderer.settings, "ARTIFACT_RENDER_CDP_URL", "http://renderer:9222")
    monkeypatch.setattr(renderer, "SETTLE_SECONDS", 0)
    data = pdf()
    browser = PrintBrowser(data)
    send = browser.send
    reads = 0

    async def chunks(method, params=None, *, session_id=None):
        nonlocal reads
        result = await send(method, params, session_id=session_id)
        if method == "IO.read":
            reads += 1
            piece = data[:10] if reads == 1 else data[10:]
            return {
                "data": base64.b64encode(piece).decode(),
                "base64Encoded": True,
                "eof": reads == 2,
            }
        if method == "IO.close" and close_error is not None:
            raise close_error
        return result

    monkeypatch.setattr(browser, "send", chunks)
    rendered = await renderer.render(
        RenderRequest(document=b"<h1>Report</h1>", nonce="n", bindings=None, output="pdf"),
        connect=AsyncMock(return_value=browser),
    )
    assert rendered.pdf == data and reads == 2
    assert browser.closed and browser.commands("Target.disposeBrowserContext")
