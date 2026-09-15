"""The LibreOffice conversion, and above all its kill-on-timeout (#1685).

`liteparse` converts office documents by spawning `soffice` from its Rust core
with no way to kill it, so a hung conversion runs to completion (default 600s)
and leaves an orphaned process. `app.core.office_convert` owns the subprocess
instead and tears its whole process group down on timeout or cancellation. These
tests stand in a fake `soffice` for the real one - a small script that hangs,
ignores `SIGTERM`, forks a child, or exits a chosen way - so the teardown is
exercised on every machine, LibreOffice installed or not.
"""

from __future__ import annotations

import asyncio
import os
import signal
import stat
import sys
from pathlib import Path

import pytest

from app.core import office_convert
from app.core.office_convert import (
    OfficeConversionError,
    OfficeConversionTimeout,
    convert_to_pdf,
)

pytestmark = pytest.mark.anyio


def _write_fake_soffice(directory: Path, body: str, *, name: str = "fake_soffice") -> Path:
    """Write an executable fake `soffice` whose body is the given script.

    The body may use `outdir` (the `--outdir` value) and `source` (the last
    argument), which the preamble parses out of `sys.argv` the way the real
    command is called.
    """
    script = directory / name
    preamble = (
        f"#!{sys.executable}\n"
        "import os, signal, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "argv = sys.argv[1:]\n"
        "outdir = Path(argv[argv.index('--outdir') + 1])\n"
        "source = Path(argv[-1])\n"
    )
    script.write_text(preamble + body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _use_fake(monkeypatch: pytest.MonkeyPatch, script: Path) -> None:
    monkeypatch.setattr(office_convert, "soffice_command", lambda: str(script))


def _spy_group_pids(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Record the process-group ids teardown signals, then signal for real.

    Captures the pid convert_to_pdf actually spawned without depending on the
    fake writing it to a file - which races the conversion timeout under load.
    """
    seen: list[int] = []
    real = office_convert._signal_group

    def spy(pid: int, sig: signal.Signals) -> None:
        seen.append(pid)
        real(pid, sig)

    monkeypatch.setattr(office_convert, "_signal_group", spy)
    return seen


async def _wait_gone(pid: int, timeout: float = 5.0) -> bool:
    """Poll until `pid` no longer exists, returning whether it went away."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        await asyncio.sleep(0.02)
    return False


def test_soffice_command_prefers_libreoffice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        office_convert.shutil,
        "which",
        lambda name: "/usr/bin/libreoffice" if name == "libreoffice" else None,
    )
    assert office_convert.soffice_command() == "/usr/bin/libreoffice"


def test_soffice_command_falls_back_to_the_soffice_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        office_convert.shutil,
        "which",
        lambda name: "/usr/bin/soffice" if name == "soffice" else None,
    )
    assert office_convert.soffice_command() == "/usr/bin/soffice"


def test_soffice_command_finds_the_macos_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(office_convert.shutil, "which", lambda _name: None)
    bundle = tmp_path / "soffice"
    bundle.write_text("")
    monkeypatch.setattr(office_convert, "_MACOS_SOFFICE", bundle)
    assert office_convert.soffice_command() == str(bundle)


def test_soffice_command_is_none_when_libreoffice_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(office_convert.shutil, "which", lambda _name: None)
    monkeypatch.setattr(office_convert, "_MACOS_SOFFICE", tmp_path / "absent")
    assert office_convert.soffice_command() is None


async def test_a_successful_conversion_returns_the_pdf_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = _write_fake_soffice(
        tmp_path,
        "(outdir / (source.stem + '.pdf')).write_bytes(b'%PDF-1.4 fake')\nsys.exit(0)\n",
    )
    _use_fake(monkeypatch, script)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    source = tmp_path / "quarterly.xlsx"
    source.write_bytes(b"not really a spreadsheet")

    pdf = await convert_to_pdf(source, out_dir, timeout_seconds=10)

    assert pdf == out_dir / "quarterly.pdf"
    assert pdf.read_bytes().startswith(b"%PDF")


async def test_a_missing_libreoffice_is_named_without_a_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(office_convert, "soffice_command", lambda: None)
    source = tmp_path / "deck.pptx"

    with pytest.raises(OfficeConversionError) as excinfo:
        await convert_to_pdf(source, tmp_path, timeout_seconds=10)

    assert "deck.pptx" in str(excinfo.value)
    assert str(tmp_path) not in str(excinfo.value)


async def test_a_nonzero_exit_is_a_conversion_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = _write_fake_soffice(
        tmp_path,
        "print('conversion boom', file=sys.stderr)\nsys.exit(3)\n",
    )
    _use_fake(monkeypatch, script)

    with pytest.raises(OfficeConversionError) as excinfo:
        await convert_to_pdf(tmp_path / "notes.odt", tmp_path, timeout_seconds=10)

    assert "notes.odt" in str(excinfo.value)
    assert not isinstance(excinfo.value, OfficeConversionTimeout)


async def test_a_clean_exit_that_writes_no_pdf_is_a_conversion_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LibreOffice can return 0 and still produce nothing; that is a failure."""
    script = _write_fake_soffice(tmp_path, "sys.exit(0)\n")
    _use_fake(monkeypatch, script)

    with pytest.raises(OfficeConversionError) as excinfo:
        await convert_to_pdf(tmp_path / "empty.doc", tmp_path, timeout_seconds=10)

    assert "empty.doc" in str(excinfo.value)


async def test_a_conversion_past_its_deadline_is_killed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hang raises promptly and the subprocess is gone, not left running."""
    script = _write_fake_soffice(tmp_path, "time.sleep(3600)\n")
    _use_fake(monkeypatch, script)
    pids = _spy_group_pids(monkeypatch)

    with pytest.raises(OfficeConversionTimeout) as excinfo:
        await convert_to_pdf(tmp_path / "huge.doc", tmp_path, timeout_seconds=0.3)

    assert "huge.doc" in str(excinfo.value)
    assert pids, "teardown never signalled the process group"
    assert await _wait_gone(pids[0]), "soffice was left running after the timeout"


async def test_a_subprocess_that_ignores_sigterm_is_killed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The grace-then-SIGKILL path: a process trapping SIGTERM still dies."""
    monkeypatch.setattr(office_convert, "_KILL_GRACE_SECONDS", 0.2)
    script = _write_fake_soffice(
        tmp_path,
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(3600)\n",
    )
    _use_fake(monkeypatch, script)
    pids = _spy_group_pids(monkeypatch)

    with pytest.raises(OfficeConversionTimeout):
        await convert_to_pdf(tmp_path / "stubborn.doc", tmp_path, timeout_seconds=0.3)

    assert pids, "teardown never signalled the process group"
    assert await _wait_gone(pids[0]), "a SIGTERM-ignoring soffice survived"


async def test_the_whole_process_group_is_reaped_not_only_the_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The P1 case: the launcher exits on SIGTERM while a helper ignores it.

    soffice forks helpers into its group; if teardown waited only on the
    launcher it would return with a helper still running. The helper here traps
    SIGTERM and ticks a heartbeat file, so only the group-wide SIGKILL can stop
    it - a heartbeat that goes still proves the whole group was reaped, without
    the reap-timing ambiguity of polling for a zombie pid. Teardown is driven
    directly, after the group is confirmed up, so nothing races an internal
    timeout.
    """
    monkeypatch.setattr(office_convert, "_KILL_GRACE_SECONDS", 0.2)
    child = _write_fake_soffice(
        tmp_path,
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "n = 0\n"
        "while True:\n"
        "    (outdir / 'heartbeat.txt').write_text(str(n))\n"
        "    n += 1\n"
        "    time.sleep(0.02)\n",
        name="fake_soffice_child",
    )
    parent = _write_fake_soffice(
        tmp_path,
        f"subprocess.Popen([{str(child)!r}, '--outdir', str(outdir), 'x'])\ntime.sleep(3600)\n",
        name="fake_soffice_parent",
    )
    proc = await asyncio.create_subprocess_exec(
        str(parent),
        "--outdir",
        str(tmp_path),
        "x",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    heartbeat = tmp_path / "heartbeat.txt"
    for _ in range(500):
        if heartbeat.exists():
            break
        await asyncio.sleep(0.02)
    assert heartbeat.exists(), "the helper never started"

    await office_convert._terminate_process_group(proc)

    ticked = heartbeat.read_text()
    await asyncio.sleep(0.5)
    assert heartbeat.read_text() == ticked, "a soffice helper kept running"


async def test_cancellation_tears_the_subprocess_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancelled ingest must not leave soffice running behind it."""
    script = _write_fake_soffice(
        tmp_path,
        "(outdir / 'pids.txt').write_text(str(os.getpid()))\ntime.sleep(3600)\n",
    )
    _use_fake(monkeypatch, script)

    task = asyncio.ensure_future(
        convert_to_pdf(tmp_path / "slow.doc", tmp_path, timeout_seconds=60)
    )
    pids = tmp_path / "pids.txt"
    for _ in range(500):
        if pids.exists():
            break
        await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    pid = int(pids.read_text())
    assert await _wait_gone(pid), "cancellation left soffice running"


async def test_tearing_down_an_already_exited_process_is_a_noop() -> None:
    """Teardown races the process exiting; a finished, empty group is fine.

    Both signals land on a group that has gone, and reaping an already-reaped
    launcher must not raise - exercising the ProcessLookupError suppression.
    """
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "pass", start_new_session=True
    )
    await proc.wait()

    await office_convert._terminate_process_group(proc)
    # The group is gone; signalling it again must still not raise.
    office_convert._signal_group(proc.pid, signal.SIGTERM)
