"""Blocking file work runs off the request loop, not on it (#25).

Two request-path functions were `async def` over pure blocking work - parsing an
upload, and reading or writing it to local storage - so one large file froze
every other request and every agent stream on the worker until it finished. Both
offload to a thread now; each test asserts the blocking call lands on a thread
other than the event loop's, which fails if the `asyncio.to_thread` is removed.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.services.file_storage import LocalFileStorage
from app.services.file_upload import FileUploadService

pytestmark = pytest.mark.anyio


async def test_parsing_an_upload_runs_off_the_request_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    service = FileUploadService(db=None)  # ty: ignore[invalid-argument-type]
    loop_thread = threading.get_ident()
    ran_on: list[int] = []

    def record(_self: FileUploadService, _data: bytes) -> str:
        ran_on.append(threading.get_ident())
        return "parsed"

    monkeypatch.setattr(FileUploadService, "_parse_pdf_content", record)

    assert await service.parse_content(b"%PDF-1.7 fixture", "pdf") == "parsed"
    assert ran_on and ran_on[0] != loop_thread


async def test_saving_to_local_storage_runs_off_the_request_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalFileStorage(base_dir=tmp_path / "media")
    loop_thread = threading.get_ident()
    ran_on: list[int] = []
    real_write = Path.write_bytes

    def recording(self: Path, data: bytes) -> int:
        ran_on.append(threading.get_ident())
        return real_write(self, data)

    monkeypatch.setattr(Path, "write_bytes", recording)

    await storage.save("u1", "report.bin", b"payload")
    assert ran_on and ran_on[0] != loop_thread


async def test_loading_from_local_storage_runs_off_the_request_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalFileStorage(base_dir=tmp_path / "media")
    stored = await storage.save("u1", "report.bin", b"payload")
    loop_thread = threading.get_ident()
    ran_on: list[int] = []
    real_read = Path.read_bytes

    def recording(self: Path) -> bytes:
        ran_on.append(threading.get_ident())
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", recording)

    assert await storage.load(stored) == b"payload"
    assert ran_on and ran_on[0] != loop_thread


async def test_deleting_from_local_storage_runs_off_the_request_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bulk teardown unlinks one file per call, so the unlink must not run on
    the loop - a dropped collection would otherwise stall the worker (#1294)."""
    storage = LocalFileStorage(base_dir=tmp_path / "media")
    stored = await storage.save("u1", "report.bin", b"payload")
    loop_thread = threading.get_ident()
    ran_on: list[int] = []
    real_unlink = Path.unlink

    def recording(self: Path, *args: object, **kwargs: object) -> None:
        ran_on.append(threading.get_ident())
        real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", recording)

    await storage.delete(stored)
    assert ran_on and ran_on[0] != loop_thread
    assert not (tmp_path / "media" / stored).exists()
