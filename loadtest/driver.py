"""Offering work at a stated rate, and recording what came back.

The whole of NFA-004's method is in one decision here: requests are issued on a
**schedule**, not by a pool of workers each waiting for its predecessor. A closed
loop of N workers reduces its own arrival rate exactly when the server slows
down, so a server that has fallen over reports comfortable latencies and a
throughput that quietly halved - the shape that makes load tests agree with
whatever you hoped. An open arrival model keeps offering work at the stated rate
and lets the queue grow, which is the thing being measured.

Each workload is one coroutine, each request its own task, and every task records
exactly one :class:`Sample` whatever happens to it - a refusal, a timeout, a
socket that closed mid-answer. A request that recorded nothing would be a request
subtracted from both the numerator and the denominator, which is how an error
rate reaches zero by losing its errors.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
import websockets
from metrics import Recorder, Sample
from scenario import CANCELLED_STREAM_SHARE, MIX, PHASES, Phase, WorkloadShare, normalized, pick
from seed import WEBHOOK_SECRET, Fixture, document

REQUEST_TIMEOUT = 60.0
"""How long one request may take before the driver gives up on it.

A ceiling on the *measurement*, not on the server: a request abandoned here is
recorded as a timeout, which is what it was to the caller. Longer than any
threshold in `thresholds.py`, so a timeout is always a finding rather than an
artefact of the driver being impatient.
"""

STREAM_TIMEOUT = 90.0
"""The same, for a chat turn, which has a model's own latency inside it."""


@dataclass
class Traffic:
    """What one workload needs to issue a request."""

    fixture: Fixture
    client: httpx.AsyncClient
    recorder: Recorder
    started: float
    random: random.Random
    access_token: str
    """Held for the run rather than stored with the fixture: a bearer token
    written to disk is a bearer token in clear text, and an expiring one makes a
    fixture that was fine an hour ago refuse to start."""


def headers(traffic: Traffic) -> dict[str, str]:
    """The two headers every authenticated call on this API carries."""
    return {
        "Authorization": f"Bearer {traffic.access_token}",
        "X-Organization-Id": traffic.fixture.organization_id,
    }


async def api_read(traffic: Traffic, phase: str) -> Sample:
    """An ordinary authenticated list, of the kind the console makes constantly."""
    path = traffic.random.choice(["/agents", "/runs", "/conversations"])
    return await _timed(
        traffic,
        "api_read",
        phase,
        lambda: traffic.client.get(path, params={"limit": 20}, headers=headers(traffic)),
    )


async def agent_run(traffic: Traffic, phase: str) -> Sample:
    """The non-streaming run another system calls."""
    return await _timed(
        traffic,
        "agent_run",
        phase,
        lambda: traffic.client.post(
            f"/agents/{traffic.fixture.agent_id}/run",
            json={"prompt": "Say something short."},
            headers=headers(traffic),
            timeout=STREAM_TIMEOUT,
        ),
    )


async def rag_query(traffic: Traffic, phase: str) -> Sample:
    """Retrieval against the seeded collection: one embedding, one vector search."""
    index = traffic.random.randrange(1000)
    return await _timed(
        traffic,
        "rag_query",
        phase,
        lambda: traffic.client.post(
            "/rag/search",
            json={
                "collection_name": traffic.fixture.collection,
                "query": f"procedure {index} of the municipal service catalogue",
                "limit": 4,
            },
            headers=headers(traffic),
        ),
    )


async def ingest(traffic: Traffic, phase: str) -> Sample:
    """An upload, which this API accepts and hands to a worker.

    What is measured is **admission**: the endpoint answers 202 and the parse,
    the chunking and the embedding happen in a flow. A run without the worker
    stack up therefore leaves these documents queued, which is correct for this
    measurement and stated in the report rather than left to be discovered.
    """
    index = traffic.random.randrange(100_000)
    return await _timed(
        traffic,
        "ingest",
        phase,
        lambda: traffic.client.post(
            f"/rag/collections/{traffic.fixture.collection}/ingest",
            files={"file": (f"load-{index:06d}.txt", document(index), "text/plain")},
            headers=headers(traffic),
        ),
    )


async def trigger_fire(traffic: Traffic, phase: str) -> Sample:
    """A webhook delivery. Admission again: the run it dispatches is the worker's."""
    fixture = traffic.fixture
    if fixture.trigger_id is None:
        return Sample(
            workload="trigger_fire",
            phase=phase,
            started_at=_now(traffic),
            duration_ms=0.0,
            ok=False,
            detail="no trigger was seeded",
        )
    body = json.dumps({"event": "load-test", "at": _now(traffic)}).encode()
    signature = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return await _timed(
        traffic,
        "trigger_fire",
        phase,
        lambda: traffic.client.post(
            f"/webhooks/triggers/{fixture.trigger_source}/{fixture.trigger_id}",
            content=body,
            headers={
                "Content-Type": "application/json",
                # The same HMAC-SHA256 over the raw body that GitHub sends, under
                # this source's own header name. Signed here rather than sent as a
                # bare secret because that is the delivery the platform accepts,
                # and a load test that bypassed the check would measure a route
                # nobody can reach.
                "X-Signature-256": f"sha256={signature}",
            },
        ),
    )


async def chat_stream(traffic: Traffic, phase: str) -> Sample:
    """A chat turn over the WebSocket, with a share of them cancelled part-way.

    Two numbers come out of this and they answer different questions. Time to
    first token is what a person feels; the whole turn is what holds a socket, a
    run row and a model request open. A cancelled turn records neither as a
    failure - it is a person changing their mind, and what it exercises is the
    `stop` frame and the teardown behind it.
    """
    fixture = traffic.fixture
    address = fixture.base_url.replace("http://", "ws://").replace("https://", "wss://")
    url = f"{address}/api/v1/ws/agent?organization_id={fixture.organization_id}"
    cancelling = traffic.random.random() < CANCELLED_STREAM_SHARE
    began = _now(traffic)
    clock = asyncio.get_running_loop().time
    opened = clock()
    first_token: float | None = None
    try:
        async with asyncio.timeout(STREAM_TIMEOUT):
            async with websockets.connect(
                url,
                subprotocols=[f"access_token.{traffic.access_token}", "chat"],  # type: ignore[list-item]
            ) as socket:
                await socket.send(
                    json.dumps(
                        {
                            "message": "Say something short.",
                            "conversation_id": None,
                            "agent_id": fixture.agent_id,
                        }
                    )
                )
                async for raw in socket:
                    frame = json.loads(raw)
                    kind = frame.get("type")
                    if kind == "text_delta" and first_token is None:
                        first_token = (clock() - opened) * 1000
                        if cancelling:
                            await socket.send(json.dumps({"type": "stop"}))
                    if kind == "error":
                        return Sample(
                            workload="chat_stream",
                            phase=phase,
                            started_at=began,
                            duration_ms=(clock() - opened) * 1000,
                            ok=False,
                            detail="the socket answered an error frame",
                        )
                    if kind == "complete":
                        break
    except TimeoutError:
        return _failed(traffic, "chat_stream", phase, began, opened, "timed out")
    except websockets.exceptions.WebSocketException as failure:
        return _failed(traffic, "chat_stream", phase, began, opened, type(failure).__name__)
    except OSError as failure:
        return _failed(traffic, "chat_stream", phase, began, opened, type(failure).__name__)
    return Sample(
        workload="chat_stream",
        phase=phase,
        started_at=began,
        duration_ms=(clock() - opened) * 1000,
        ok=True,
        first_token_ms=first_token,
    )


WORKLOADS: dict[str, Callable[[Traffic, str], Awaitable[Sample]]] = {
    "api_read": api_read,
    "chat_stream": chat_stream,
    "agent_run": agent_run,
    "rag_query": rag_query,
    "ingest": ingest,
    "trigger_fire": trigger_fire,
}


def _now(traffic: Traffic) -> float:
    return asyncio.get_running_loop().time() - traffic.started


def _failed(
    traffic: Traffic, workload: str, phase: str, began: float, opened: float, detail: str
) -> Sample:
    del traffic
    return Sample(
        workload=workload,
        phase=phase,
        started_at=began,
        duration_ms=(asyncio.get_running_loop().time() - opened) * 1000,
        ok=False,
        detail=detail,
    )


async def _timed(
    traffic: Traffic,
    workload: str,
    phase: str,
    call: Callable[[], Awaitable[httpx.Response]],
) -> Sample:
    """Issue one HTTP request and record what happened to it, whatever that was.

    A 4xx is a failure here and deliberately so: on this fixture every request is
    legal, so a refusal means the platform refused work it should have done - a
    rate limit reached, a pool exhausted, a body rejected under pressure. The
    status travels with the sample so the report can name which.
    """
    clock = asyncio.get_running_loop().time
    began = clock() - traffic.started
    opened = clock()
    try:
        response = await call()
    except httpx.TimeoutException:
        return _failed(traffic, workload, phase, began, opened, "timed out")
    except httpx.HTTPError as failure:
        return _failed(traffic, workload, phase, began, opened, type(failure).__name__)
    return Sample(
        workload=workload,
        phase=phase,
        started_at=began,
        duration_ms=(clock() - opened) * 1000,
        ok=response.status_code < 400,
        status=response.status_code,
        detail="" if response.status_code < 400 else f"HTTP {response.status_code}",
    )


async def drive(
    traffic: Traffic,
    *,
    phases: tuple[Phase, ...] = PHASES,
    mix: tuple[WorkloadShare, ...] = MIX,
    on_phase: Callable[[Phase], None] | None = None,
) -> None:
    """Offer work at each phase's rate, and wait for what is still in flight.

    The schedule is absolute rather than cumulative - each request's due time is
    computed from the phase's start - so a slow dispatch does not push the whole
    run later and quietly reduce the offered rate. When the driver falls behind
    its own schedule it says so in the report rather than pretending it kept up.
    """
    shares = normalized(mix)
    clock = asyncio.get_running_loop().time
    in_flight: set[asyncio.Task[None]] = set()
    issued = 0
    elapsed = 0.0

    async def one(name: str, phase: str) -> None:
        traffic.recorder.record(await WORKLOADS[name](traffic, phase))

    for phase in phases:
        if on_phase is not None:
            on_phase(phase)
        phase_started = traffic.started + elapsed
        total = int(phase.seconds * phase.rate_per_second)
        for index in range(total):
            due = phase_started + index / phase.rate_per_second
            delay = due - clock()
            if delay > 0:
                await asyncio.sleep(delay)
            name = pick(issued, shares)
            issued += 1
            task = asyncio.create_task(one(name, phase.name))
            in_flight.add(task)
            task.add_done_callback(in_flight.discard)
        elapsed += phase.seconds

    if in_flight:
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(STREAM_TIMEOUT):
                await asyncio.gather(*in_flight, return_exceptions=True)
    for task in in_flight:
        task.cancel()
