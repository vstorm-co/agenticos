"""Stopping the dispatch heartbeat must not consume the worker's cancellation."""

import asyncio
from uuid import uuid4

import pytest

from app.services.workflow_execution.context import ClaimState
from app.worker.tasks import workflow_tasks

pytestmark = pytest.mark.anyio


async def test_worker_cancellation_during_heartbeat_cleanup_is_not_swallowed(monkeypatch):
    entered = asyncio.Event()
    closing = asyncio.Event()
    never = asyncio.Event()
    finished_body = asyncio.Event()

    async def renew(*_args):
        entered.set()
        try:
            await never.wait()
        finally:
            closing.set()
            await never.wait()

    monkeypatch.setattr(workflow_tasks, "_renew_until_lost", renew)

    async def worker():
        async with workflow_tasks._lease_kept_alive(uuid4(), uuid4(), ClaimState()):
            await entered.wait()
        finished_body.set()

    task = asyncio.create_task(worker())
    try:
        await closing.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not finished_body.is_set()
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_cancellation_during_the_dispatch_body_still_closes_heartbeat(monkeypatch):
    entered = asyncio.Event()
    closed = asyncio.Event()
    never = asyncio.Event()

    async def renew(*_args):
        entered.set()
        try:
            await never.wait()
        finally:
            closed.set()

    monkeypatch.setattr(workflow_tasks, "_renew_until_lost", renew)

    async def worker():
        async with workflow_tasks._lease_kept_alive(uuid4(), uuid4(), ClaimState()):
            await entered.wait()
            await never.wait()

    task = asyncio.create_task(worker())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


async def test_heartbeat_cleanup_failure_remains_visible(monkeypatch):
    entered = asyncio.Event()
    never = asyncio.Event()
    failure = RuntimeError("Heartbeat cleanup failed")

    async def renew(*_args):
        entered.set()
        try:
            await never.wait()
        finally:
            raise failure

    monkeypatch.setattr(workflow_tasks, "_renew_until_lost", renew)
    with pytest.raises(RuntimeError) as caught:
        async with workflow_tasks._lease_kept_alive(uuid4(), uuid4(), ClaimState()):
            await entered.wait()
    assert caught.value is failure


@pytest.mark.parametrize("body_fails", [False, True])
async def test_requested_child_cancellation_preserves_dispatch_outcome(monkeypatch, body_fails):
    entered = asyncio.Event()
    closed = asyncio.Event()
    never = asyncio.Event()
    failure = ValueError("Dispatch failed")

    async def renew(*_args):
        entered.set()
        try:
            await never.wait()
        finally:
            closed.set()

    monkeypatch.setattr(workflow_tasks, "_renew_until_lost", renew)

    async def dispatch():
        async with workflow_tasks._lease_kept_alive(uuid4(), uuid4(), ClaimState()):
            await entered.wait()
            if body_fails:
                raise failure
        return "settled"

    if body_fails:
        with pytest.raises(ValueError) as caught:
            await dispatch()
        assert caught.value is failure
    else:
        assert await dispatch() == "settled"
    assert closed.is_set()


async def test_heartbeat_normal_exit_after_losing_claim_does_not_cancel_dispatch(monkeypatch):
    ended = asyncio.Event()
    state = ClaimState()

    async def renew(_node, _token, claim):
        claim.lost = True
        ended.set()

    monkeypatch.setattr(workflow_tasks, "_renew_until_lost", renew)
    async with workflow_tasks._lease_kept_alive(uuid4(), uuid4(), state):
        await ended.wait()
        assert state.lost
