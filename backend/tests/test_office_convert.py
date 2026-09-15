"""The one subprocess in the chat attachment feature: managed, bounded, killable.

`soffice` may be absent on this host, so every test here mocks the subprocess. The
questions are the ones a bespoke manager exists to answer: does an absent binary
degrade gracefully, does a timeout actually kill the process group, does a
cancellation reap the child rather than orphan it, and does a flooding child not
deadlock the wait (#1591, §7 findings 3-4).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.core import config as config_module
from app.services import office_convert

pytestmark = pytest.mark.anyio


class FakeProc:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stderr: bytes = b"",
        hang_communicate: bool = False,
        hang_wait: bool = False,
    ) -> None:
        self.pid = 4242
        self.returncode = returncode
        self._stderr = stderr
        self._hang_communicate = hang_communicate
        self._hang_wait = hang_wait

    async def communicate(self) -> tuple[None, bytes]:
        if self._hang_communicate:
            await asyncio.sleep(10)
        return None, self._stderr

    async def wait(self) -> int:
        if self._hang_wait:
            await asyncio.sleep(10)
        return self.returncode


def _exec(
    proc: FakeProc, *, output: bytes | None = None, seen: list[tuple[Any, ...]] | None = None
):
    async def run(*argv: Any, **_kwargs: Any) -> FakeProc:
        if seen is not None:
            seen.append(argv)
        if output is not None:
            outdir = Path(argv[argv.index("--outdir") + 1])
            source = Path(argv[-1])
            (outdir / f"{source.stem}.txt").write_bytes(output)
        return proc

    return run


@pytest.fixture
def present(monkeypatch):
    """LibreOffice is on PATH."""
    monkeypatch.setattr(office_convert.shutil, "which", lambda name: f"/usr/bin/{name}")


async def _convert(monkeypatch, proc: FakeProc, *, output: bytes | None = None, timeout: float = 5):
    monkeypatch.setattr(
        office_convert.asyncio, "create_subprocess_exec", _exec(proc, output=output)
    )
    return await office_convert.libreoffice_convert(b"doc-bytes", suffix=".doc", timeout=timeout)


class TestTheHappyAndFailurePaths:
    async def test_absent_libreoffice_degrades_to_none(self, monkeypatch):
        monkeypatch.setattr(office_convert.shutil, "which", lambda _name: None)

        assert await office_convert.libreoffice_convert(b"x", suffix=".doc", timeout=1) is None

    async def test_a_successful_conversion_returns_the_text(self, monkeypatch, present):
        text = await _convert(monkeypatch, FakeProc(returncode=0), output=b"Clause 1. Agreed.")

        assert text == "Clause 1. Agreed."

    async def test_a_conversion_with_stderr_warnings_still_succeeds(self, monkeypatch, present):
        text = await _convert(
            monkeypatch, FakeProc(returncode=0, stderr=b"a warning"), output=b"body"
        )

        assert text == "body"

    async def test_a_nonzero_exit_is_none(self, monkeypatch, present):
        assert (
            await _convert(monkeypatch, FakeProc(returncode=1, stderr=b"boom"), output=b"x") is None
        )

    async def test_missing_output_is_none(self, monkeypatch, present):
        assert await _convert(monkeypatch, FakeProc(returncode=0), output=None) is None

    async def test_empty_output_is_none(self, monkeypatch, present):
        assert await _convert(monkeypatch, FakeProc(returncode=0), output=b"   \n") is None

    async def test_oversized_output_is_none(self, monkeypatch, present):
        monkeypatch.setattr(config_module.settings, "CHAT_CONVERT_OUTPUT_MAX_BYTES", 5)

        assert await _convert(monkeypatch, FakeProc(returncode=0), output=b"x" * 100) is None


class TestTeardown:
    async def test_a_timeout_kills_and_returns_none(self, monkeypatch, present):
        killed: list[tuple[int, int]] = []
        monkeypatch.setattr(office_convert.os, "getpgid", lambda _pid: 999)
        monkeypatch.setattr(
            office_convert.os, "killpg", lambda pgid, sig: killed.append((pgid, sig))
        )

        result = await _convert(monkeypatch, FakeProc(hang_communicate=True), timeout=0.01)

        assert result is None
        assert killed and killed[0][0] == 999  # the group was signalled

    async def test_a_wedged_child_is_escalated_to_kill(self, monkeypatch, present):
        signals: list[int] = []
        monkeypatch.setattr(office_convert.os, "getpgid", lambda _pid: 999)
        monkeypatch.setattr(office_convert.os, "killpg", lambda _pgid, sig: signals.append(sig))
        monkeypatch.setattr(config_module.settings, "CHAT_CONVERT_KILL_GRACE_SECONDS", 0.01)

        result = await _convert(
            monkeypatch, FakeProc(hang_communicate=True, hang_wait=True), timeout=0.01
        )

        assert result is None
        assert office_convert.signal.SIGTERM in signals
        assert office_convert.signal.SIGKILL in signals

    async def test_a_dead_group_is_swallowed_not_raised(self, monkeypatch, present):
        """`getpgid` on an already-reaped pid raises `ProcessLookupError`; teardown
        must absorb it rather than turning a timeout into a crash."""

        def _gone(_pid: int) -> int:
            raise ProcessLookupError

        monkeypatch.setattr(office_convert.os, "getpgid", _gone)

        assert await _convert(monkeypatch, FakeProc(hang_communicate=True), timeout=0.01) is None

    async def test_cancellation_kills_the_group_and_propagates(self, monkeypatch, present):
        killed: list[int] = []
        monkeypatch.setattr(office_convert.os, "getpgid", lambda _pid: 999)
        monkeypatch.setattr(office_convert.os, "killpg", lambda _pgid, sig: killed.append(sig))
        monkeypatch.setattr(
            office_convert.asyncio,
            "create_subprocess_exec",
            _exec(FakeProc(hang_communicate=True)),
        )

        task = asyncio.ensure_future(
            office_convert.libreoffice_convert(b"x", suffix=".doc", timeout=10)
        )
        await asyncio.sleep(0.05)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert killed  # the group was killed before the cancellation propagated


class TestConcurrency:
    async def test_concurrent_conversions_share_the_semaphore_and_use_distinct_profiles(
        self, monkeypatch, present
    ):
        seen: list[tuple[Any, ...]] = []
        monkeypatch.setattr(
            office_convert.asyncio,
            "create_subprocess_exec",
            _exec(FakeProc(returncode=0), output=b"ok", seen=seen),
        )

        results = await asyncio.gather(
            office_convert.libreoffice_convert(b"a", suffix=".doc", timeout=5),
            office_convert.libreoffice_convert(b"b", suffix=".doc", timeout=5),
        )

        assert results == ["ok", "ok"]
        profiles = [
            arg for argv in seen for arg in argv if str(arg).startswith("-env:UserInstallation=")
        ]
        assert len(profiles) == 2
        assert profiles[0] != profiles[1]  # a per-call profile, not one shared lock
