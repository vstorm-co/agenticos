"""Exercise the parser's process boundary with real, disposable children."""

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

import pytest

from app.services.ml import parsing
from app.services.rag.documents import PyMuPDFParser

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.security,
    pytest.mark.skipif(os.name != "posix", reason="POSIX parser containment"),
]


@pytest.mark.parametrize("cancel", [False, True])
async def test_office_descendants_and_profiles_do_not_survive_the_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    record = tmp_path / "converter.json"
    command = tmp_path / "soffice"
    command.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"pathlib.Path({str(record)!r}).write_text(json.dumps({{'pid':os.getpid(), 'child':child.pid, 'group':os.getpgrp(), 'parent':os.getppid(), 'args':sys.argv}}))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    command.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(parsing, "PARSE_TIMEOUT_SECONDS", 8.0)
    workspace = tmp_path / "workspace"

    def make_workspace(*, prefix: str) -> str:
        workspace.mkdir()
        return str(workspace)

    monkeypatch.setattr(parsing.tempfile, "mkdtemp", make_workspace)
    task = asyncio.create_task(parsing.analyze(b"office input", "slides.pptx", parser="liteparse"))
    try:
        async with asyncio.timeout(6):
            while not record.exists():
                if task.done():
                    await task
                await asyncio.sleep(0.02)
        data = json.loads(record.read_text())
        assert data["group"] == data["parent"]
        profile = next(arg for arg in data["args"] if arg.startswith("-env:UserInstallation="))
        assert workspace.as_uri() in profile
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else parsing.ExternalServiceError):
            await task
        assert not workspace.exists()
        for pid in (data["pid"], data["child"]):
            state = Path(f"/proc/{pid}/stat")
            for _ in range(50):
                if not state.exists() or state.read_text().split()[2] == "Z":
                    break
                await asyncio.sleep(0.02)
            assert not state.exists() or state.read_text().split()[2] == "Z"
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.parametrize("parser", ["pymupdf", "liteparse"])
async def test_a_real_pdf_table_crosses_the_bounded_worker(parser: str, tmp_path: Path) -> None:
    import pymupdf

    with pymupdf.open() as document:
        page = document.new_page()
        for y in (60, 100, 140, 180):
            page.draw_line((60, y), (300, y))
        for x in (60, 180, 300):
            page.draw_line((x, 60), (x, 180))
        for row, y in enumerate((85, 125, 165)):
            page.insert_text((75, y), f"Name {row}")
            page.insert_text((195, y), f"Value {row}")
        content = document.tobytes()
    result = await parsing.analyze(content, "table.pdf", parser=parser)
    assert result.pages and result.chunks
    assert "Value" in result.pages[0].content
    if parser == "pymupdf":
        path = tmp_path / "table.pdf"
        path.write_bytes(content)
        baseline = await PyMuPDFParser().parse(path)
        assert result.pages[0].content == baseline.pages[0].content


@pytest.mark.parametrize("cancel", [False, True])
async def test_an_unresponsive_child_is_killed_and_reaped(cancel: bool) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-c",
        "import time; time.sleep(60)",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        deadline = asyncio.get_running_loop().time() + (10 if cancel else 0.05)
        exchange = asyncio.create_task(parsing._exchange_parse_child(process, b"{}", deadline))
        if cancel:
            await asyncio.sleep(0.02)
            exchange.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await exchange
        assert process.returncode == -signal.SIGKILL
        with pytest.raises(ProcessLookupError):
            os.kill(process.pid, 0)
    finally:
        if process.returncode is None:
            await parsing._reap_parse_child(process)


async def test_a_child_that_exits_silently_cannot_supply_a_result() -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-c",
        "import sys; sys.stdin.buffer.read(); sys.exit(9)",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        with pytest.raises(RuntimeError, match="exited without a result"):
            await parsing._exchange_parse_child(
                process, b"{}", asyncio.get_running_loop().time() + 5
            )
        assert process.returncode == 9
        with pytest.raises(ProcessLookupError):
            os.kill(process.pid, 0)
    finally:
        await parsing._reap_parse_child(process)


@pytest.mark.parametrize("budget", ["cpu", "memory"])
async def test_worker_resource_limits_are_enforced_by_the_kernel(budget: str) -> None:
    worker = str(Path(parsing._PARSE_WORKER_PATH))
    operation = "while True: pass" if budget == "cpu" else "data = bytearray(128 * 1024 * 1024)"
    code = (
        f"import runpy; worker = runpy.run_path({worker!r}); "
        "worker['_apply_limits'](1, 64 * 1024 * 1024)\n" + operation
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-c",
        code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        _, diagnostic = await asyncio.wait_for(process.communicate(), 5)
        if budget == "cpu":
            assert process.returncode == -signal.SIGKILL
        else:
            assert process.returncode == 1
            assert b"MemoryError" in diagnostic
    finally:
        if process.returncode is None:
            await parsing._reap_parse_child(process)
