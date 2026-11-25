"""The ML parser child's hard limits and one-shot protocol."""

import builtins
import io
import json
import resource
import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.ml import _parse_worker as worker
from app.services.rag.config import RAGSettings
from app.services.rag.documents import DocumentLimitExceeded
from app.services.rag.models import Document, DocumentMetadata, DocumentPage, DocumentPageChunk


def test_entrypoint_reserves_a_protocol_pipe_before_loading_the_parser() -> None:
    output, diagnostic = MagicMock(), MagicMock()
    output.fileno.return_value = 10
    diagnostic.fileno.return_value = 20
    with (
        patch("sys.argv", ["worker"]),
        patch("sys.stdin", SimpleNamespace(buffer=io.BytesIO())),
        patch("sys.stdout", output),
        patch("sys.stderr", diagnostic),
        patch("os.dup", return_value=30) as duplicate,
        patch("os.dup2") as redirect,
        patch("os.fdopen") as opened,
        pytest.raises(SystemExit) as caught,
    ):
        runpy.run_path(str(Path(worker.__file__)), run_name="__main__")
    assert caught.value.code == 1
    duplicate.assert_called_once_with(10)
    redirect.assert_called_once_with(20, 10)
    opened.assert_called_once_with(30, "wb")


def _settings() -> bytes:
    return RAGSettings().model_dump_json().encode()


def _document() -> Document:
    document = Document(
        pages=[DocumentPage(page_num=1, content="ordinary content")],
        metadata=DocumentMetadata(
            filename="document.pdf",
            filesize=10,
            filetype="pdf",
            content_hash="abc",
        ),
    )
    document.metadata.additional_info = {"pdf_title": "not needed by the ML response"}
    document.chunked_pages = [
        DocumentPageChunk(
            page_num=1,
            content="ordinary content",
            chunk_content="ordinary content",
        )
    ]
    return document


def test_resource_limits_are_hard_and_cover_cpu_and_address_space(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []
    monkeypatch.setattr(resource, "getrlimit", lambda _kind: (0, resource.RLIM_INFINITY))
    monkeypatch.setattr(
        resource,
        "setrlimit",
        lambda kind, limits: calls.append((kind, limits)),
    )

    worker._apply_limits(7, 1024)

    assert calls == [
        (resource.RLIMIT_CPU, (7, 7)),
        (resource.RLIMIT_AS, (1024, 1024)),
    ]


def test_a_host_that_rejects_a_resource_limit_does_not_start_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(resource, "getrlimit", lambda _kind: (0, resource.RLIM_INFINITY))
    monkeypatch.setattr(
        resource,
        "setrlimit",
        lambda _kind, _limits: (_ for _ in ()).throw(OSError("not permitted")),
    )

    with pytest.raises(RuntimeError, match="could not install"):
        worker._apply_limits(7, 1024)


def test_a_host_without_resource_limits_does_not_start_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported = builtins.__import__

    def without_resource(name: str, *args: object, **kwargs: object) -> object:
        if name == "resource":
            raise ImportError
        return imported(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_resource)

    with pytest.raises(RuntimeError, match="cannot isolate"):
        worker._apply_limits(7, 1024)


@pytest.mark.parametrize("argv", [["worker"], ["worker", "x"], ["worker", "0"]])
def test_missing_or_invalid_resource_limits_are_refused(argv: list[str]) -> None:
    with pytest.raises(RuntimeError, match="resource limit"):
        worker._bounded_positive(argv, 1)


def test_worker_request_input_is_bounded() -> None:
    assert worker._request(io.BytesIO(b"{}")) == b"{}"
    with pytest.raises(ValueError, match="missing or oversized"):
        worker._request(io.BytesIO())
    with pytest.raises(ValueError, match="missing or oversized"):
        worker._request(io.BytesIO(b"x" * (worker._REQUEST_MAX_BYTES + 1)))


def test_a_legitimate_document_crosses_the_worker_protocol() -> None:
    class Processor:
        def __init__(self, settings: RAGSettings) -> None:
            assert settings.pdf_parser.method == "pymupdf"

        async def process_file(self, path: Path) -> Document:
            assert path == Path("document.pdf")
            return _document()

    with (
        patch.object(worker, "_apply_limits"),
        patch("app.services.rag.documents.DocumentProcessor", Processor),
    ):
        response = worker._run(
            ["worker", "7", "1024", "document.pdf"],
            io.BytesIO(_settings()),
        )

    decoded = json.loads(response)
    assert decoded["ok"] is True
    assert decoded["document"]["pages"][0]["content"] == "ordinary content"
    assert decoded["document"]["chunked_pages"][0]["content"] == ""
    assert decoded["document"]["metadata"]["additional_info"] is None


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        (DocumentLimitExceeded("pages", 1), "limit"),
        (ValueError("empty"), "value_error"),
        (RuntimeError("engine"), "runtime_error"),
        (TypeError("malformed"), "bad_document"),
    ],
)
def test_worker_failures_cross_only_as_controlled_kinds(
    failure: Exception,
    kind: str,
) -> None:
    class Processor:
        def __init__(self, settings: RAGSettings) -> None:
            del settings

        async def process_file(self, path: Path) -> Document:
            del path
            raise failure

    with (
        patch.object(worker, "_apply_limits"),
        patch("app.services.rag.documents.DocumentProcessor", Processor),
    ):
        response = worker._run(
            ["worker", "7", "1024", "document.pdf"],
            io.BytesIO(_settings()),
        )

    decoded = json.loads(response)
    assert decoded["ok"] is False
    assert decoded["kind"] == kind
    assert str(failure) not in response.decode()
    if isinstance(failure, DocumentLimitExceeded):
        assert decoded == {
            "ok": False,
            "kind": "limit",
            "budget": "pages",
            "maximum": 1,
        }


def test_main_writes_one_result_or_exits_nonzero() -> None:
    stdout = io.BytesIO()
    with patch.object(worker, "_run", return_value=b'{"ok":true}'):
        assert worker.main([], io.BytesIO(), stdout) == 0
    assert stdout.getvalue() == b'{"ok":true}'

    with patch.object(worker, "_run", side_effect=RuntimeError("limits")):
        assert worker.main([], io.BytesIO(), io.BytesIO()) == 1
