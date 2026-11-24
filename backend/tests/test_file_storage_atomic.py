"""A repeated media collector cannot truncate or remove a committed output."""

import asyncio
import os
import stat
import threading
from pathlib import Path
from uuid import UUID

import pytest

from app.services.file_storage import LocalFileStorage

pytestmark = pytest.mark.anyio


async def test_readers_see_complete_bytes_while_two_collectors_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalFileStorage(tmp_path)
    target = tmp_path / "output.bin"
    target.write_bytes(b"already committed")
    ready = threading.Barrier(3)
    release = threading.Event()
    replace = os.replace

    def paused_replace(source: Path, destination: Path) -> None:
        ready.wait(timeout=5)
        assert release.wait(timeout=5)
        replace(source, destination)

    monkeypatch.setattr("app.services.file_storage.os.replace", paused_replace)
    payload = b"same verified output" * 65536
    writers = [asyncio.create_task(storage.save_at("output.bin", payload)) for _ in range(2)]
    try:
        await asyncio.to_thread(ready.wait, 5)
        assert target.read_bytes() == b"already committed"
    finally:
        release.set()
        results = await asyncio.gather(*writers, return_exceptions=True)
    assert results.count(None) >= 1
    for result in results:
        # Windows can refuse a simultaneous rename while the competing rename
        # owns its handle. That refusal must leave the published target intact.
        assert result is None or (
            os.name == "nt" and isinstance(result, PermissionError) and result.winerror in (5, 32)
        )
    assert target.read_bytes() == payload
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("stage", ["flush", "replace"])
@pytest.mark.parametrize("existing", [False, True])
async def test_failed_publish_removes_only_its_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str, existing: bool
) -> None:
    storage = LocalFileStorage(tmp_path)
    target = tmp_path / "output.bin"
    if existing:
        target.write_bytes(b"already committed")

    def fail(*_args: object) -> None:
        raise OSError("synthetic write failure")

    monkeypatch.setattr(
        f"app.services.file_storage.os.{'fsync' if stage == 'flush' else 'replace'}", fail
    )
    with pytest.raises(OSError, match="synthetic write failure"):
        await storage.save_at("output.bin", b"uncommitted replacement")
    if existing:
        assert target.read_bytes() == b"already committed"
    assert list(tmp_path.iterdir()) == ([target] if existing else [])


async def test_cancelled_collector_cannot_remove_a_competing_committed_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalFileStorage(tmp_path)
    target = tmp_path / "output.bin"
    target.write_bytes(b"already committed")
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    gate = threading.Lock()
    calls = 0
    replace = os.replace

    def pause_first(source: Path, destination: Path) -> None:
        nonlocal calls
        with gate:
            calls += 1
            first = calls == 1
        if first:
            entered.set()
            assert release.wait(timeout=5)
        replace(source, destination)
        if first:
            finished.set()

    monkeypatch.setattr("app.services.file_storage.os.replace", pause_first)
    payload = b"same verified output" * 1024
    cancelled = asyncio.create_task(storage.save_at("output.bin", payload))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        assert target.read_bytes() == b"already committed"
        await storage.save_at("output.bin", payload)
        assert target.read_bytes() == payload
    finally:
        release.set()
        if not cancelled.done():
            await cancelled
        assert await asyncio.to_thread(finished.wait, 5)
    assert target.read_bytes() == payload
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.security
async def test_replacement_keeps_the_existing_file_permissions(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    target = tmp_path / "output.bin"
    target.write_bytes(b"old")
    target.chmod(0o640)
    mode = stat.S_IMODE(target.stat().st_mode)
    await storage.save_at("output.bin", b"replacement")
    assert target.read_bytes() == b"replacement"
    assert stat.S_IMODE(target.stat().st_mode) == mode


async def test_a_temporary_name_collision_does_not_delete_another_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalFileStorage(tmp_path)
    token = UUID("00000000-0000-4000-8000-000000000116")
    owned_elsewhere = tmp_path / f".storage-{token.hex}.tmp"
    owned_elsewhere.write_bytes(b"another writer")
    monkeypatch.setattr("app.services.file_storage.uuid.uuid4", lambda: token)
    with pytest.raises(FileExistsError):
        await storage.save_at("output.bin", b"our bytes")
    assert owned_elsewhere.read_bytes() == b"another writer"
    assert list(tmp_path.iterdir()) == [owned_elsewhere]


async def test_failed_read_only_replacement_reaps_its_own_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalFileStorage(tmp_path)
    target = tmp_path / "output.bin"
    target.write_bytes(b"already committed")
    unlink = Path.unlink
    refused: set[Path] = set()

    def refuse_first_temporary_unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path.suffix == ".tmp" and path not in refused:
            refused.add(path)
            raise PermissionError("synthetic Windows read-only temporary")
        unlink(path, missing_ok=missing_ok)

    def fail_replace(*_args: object) -> None:
        raise PermissionError("synthetic read-only destination")

    monkeypatch.setattr(Path, "unlink", refuse_first_temporary_unlink)
    monkeypatch.setattr("app.services.file_storage.os.replace", fail_replace)
    with pytest.raises(PermissionError, match="synthetic read-only destination"):
        await storage.save_at("output.bin", b"uncommitted")
    assert len(refused) == 1
    assert target.read_bytes() == b"already committed"
    assert list(tmp_path.iterdir()) == [target]
