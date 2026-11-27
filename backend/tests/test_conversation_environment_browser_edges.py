"""The retained browser owner fails visibly and always detaches its creating transport."""

import asyncio
from contextlib import asynccontextmanager, suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anyio
import pytest

from app.services import conversation_environment_browser as browser
from tests.test_conversation_environment_browser import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_owner_loop_failure_after_ready_disposes_transport_and_retires_admission(
    case, monkeypatch, caplog
):
    detached = anyio.Event()

    @asynccontextmanager
    async def page(**options):
        await options["keep"](case.target)
        try:
            yield AsyncMock()
        finally:
            detached.set()

    async def fail_sleep(_seconds):
        raise OSError("Guard transport stopped")

    monkeypatch.setattr(browser, "open_page", page)
    monkeypatch.setattr(browser, "_still_owned", AsyncMock(return_value=True))
    monkeypatch.setattr(browser.anyio, "sleep", fail_sleep)
    assert (
        await browser.retain_tab(case.resolved, case.payload, start_url=None, keep=AsyncMock())
        == case.target
    )
    await detached.wait()
    await anyio.lowlevel.checkpoint()
    assert "conversation_browser_guard_failed" in caplog.text
    browser.ConversationEnvironmentService.expire.assert_awaited_once()


async def test_provider_that_does_not_journal_target_is_refused_before_readiness(case, monkeypatch):
    detached = []

    @asynccontextmanager
    async def page(**options):
        try:
            yield AsyncMock()
        finally:
            detached.append(True)

    monkeypatch.setattr(browser, "open_page", page)
    with pytest.raises(RuntimeError, match="did not journal"):
        await browser.retain_tab(case.resolved, case.payload, start_url=None, keep=AsyncMock())
    assert detached == [True]
    browser.ConversationEnvironmentService.expire.assert_not_awaited()


async def test_guard_settlement_failure_remains_visible_after_transport_detaches(
    case, monkeypatch, caplog
):
    detached = []

    @asynccontextmanager
    async def page(**options):
        await options["keep"](case.target)
        try:
            yield AsyncMock()
        finally:
            detached.append(True)

    monkeypatch.setattr(browser, "open_page", page)
    monkeypatch.setattr(browser, "_still_owned", AsyncMock(return_value=False))
    monkeypatch.setattr(browser, "_ended", AsyncMock(side_effect=OSError("Cleanup DB unavailable")))
    await browser.retain_tab(case.resolved, case.payload, start_url=None, keep=AsyncMock())
    await anyio.lowlevel.checkpoint()
    assert detached == [True]
    assert "conversation_browser_guard_settlement_failed" in caplog.text


async def test_cancelling_ready_owner_joins_transport_and_retires_known_target(case, monkeypatch):
    owners = []
    detached = anyio.Event()
    waiting = anyio.Event()

    def owned(coro, **options):
        task = asyncio.create_task(coro, **options)
        owners.append(task)
        return task

    @asynccontextmanager
    async def page(**options):
        await options["keep"](case.target)
        try:
            yield AsyncMock()
        finally:
            detached.set()

    async def alive(*_args):
        waiting.set()
        await anyio.sleep_forever()

    monkeypatch.setattr(browser, "spawn", owned)
    monkeypatch.setattr(browser, "open_page", page)
    monkeypatch.setattr(browser, "_still_owned", alive)
    try:
        assert (
            await browser.retain_tab(case.resolved, case.payload, start_url=None, keep=AsyncMock())
            == case.target
        )
        await waiting.wait()
    finally:
        for task in owners:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    assert detached.is_set()
    browser.ConversationEnvironmentService.expire.assert_awaited_once()


async def test_active_run_owner_still_guards_original_target(case, monkeypatch):
    case.row.session_lifetime, case.row.source_run_id = "run", case.payload.environment_id
    monkeypatch.setattr(
        browser.run_repo, "get_run", AsyncMock(return_value=SimpleNamespace(status="running"))
    )
    assert await browser._still_owned(case.payload, case.target)


async def test_guard_exit_after_resource_was_cleared_does_not_attempt_unseal(case, monkeypatch):
    case.row.resource_ciphertext = None
    resource = AsyncMock()
    monkeypatch.setattr(browser.ConversationEnvironmentService, "resource", resource)
    await browser._ended(case.payload, case.target)
    resource.assert_not_called()
    browser.ConversationEnvironmentService.expire.assert_awaited_once()


async def test_owner_shutdown_before_ready_cancels_waiting_admission_and_detaches(
    case, monkeypatch
):
    owners = []
    opened, detached = anyio.Event(), anyio.Event()

    def owned(coro, **options):
        task = asyncio.create_task(coro, **options)
        owners.append(task)
        return task

    @asynccontextmanager
    async def page(**options):
        opened.set()
        try:
            await anyio.sleep_forever()
            yield AsyncMock()
        finally:
            detached.set()

    monkeypatch.setattr(browser, "spawn", owned)
    monkeypatch.setattr(browser, "open_page", page)
    caller = asyncio.create_task(
        browser.retain_tab(case.resolved, case.payload, start_url=None, keep=AsyncMock())
    )
    try:
        await opened.wait()
        owners[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
    finally:
        caller.cancel()
        with suppress(asyncio.CancelledError):
            await caller
        for task in owners:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    assert detached.is_set()
    browser.ConversationEnvironmentService.expire.assert_not_awaited()


async def test_caller_cancel_racing_completed_journal_never_resolves_cancelled_readiness(
    case, monkeypatch, caplog
):
    journaled, commit = anyio.Event(), anyio.Event()
    guard_entered, detached = anyio.Event(), anyio.Event()

    @asynccontextmanager
    async def page(**options):
        try:
            await options["keep"](case.target)
            yield AsyncMock()
        finally:
            detached.set()

    async def keep(_target):
        journaled.set()
        await commit.wait()

    async def alive(*_args):
        guard_entered.set()
        await anyio.sleep_forever()

    monkeypatch.setattr(browser, "open_page", page)
    monkeypatch.setattr(browser, "_still_owned", alive)
    caller = asyncio.create_task(
        browser.retain_tab(case.resolved, case.payload, start_url=None, keep=keep)
    )
    try:
        await journaled.wait()
        # Journal completion queues the owner first; cancelling the caller
        # cancels its readiness Future immediately, before caller cleanup runs.
        commit.set()
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
    finally:
        caller.cancel()
        with suppress(asyncio.CancelledError):
            await caller
    assert guard_entered.is_set() and detached.is_set()
    assert "conversation_browser_guard_failed" not in caplog.text
