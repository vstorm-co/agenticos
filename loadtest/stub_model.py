"""A model server that answers in a time you chose, for load rather than truth.

`frontend/e2e/stub-model-server.ts` already serves the Chat Completions API for
the end-to-end suite, and it is the wrong fixture here for one reason: it answers
as fast as it can. A load test whose model has no latency measures a platform
under a workload that cannot exist, because every real provider takes hundreds of
milliseconds and the concurrency a deployment actually holds is decided by how
long a run keeps its resources while waiting.

So this one is slow on purpose, and by a number the run states. It serves:

- `POST /v1/chat/completions`, streaming and not, with a first-token delay and a
  per-token pace;
- `POST /v1/embeddings`, so a seeded collection can be indexed and searched with
  no vendor involved at all. The vectors are derived from a hash of the text,
  which makes them stable across runs - a collection re-seeded between runs
  retrieves the same neighbours, and a retrieval-time comparison is therefore
  comparing the database rather than the embeddings.

It can also be told to fail: `--error-rate` refuses that share of requests with a
500 and `--timeout-rate` holds them open past any sane client deadline. Both exist
for the resilience half of NFA-004 - what the platform does when its provider
misbehaves is a property of the platform, and it cannot be measured against a
provider that is behaving.

Run it with the backend's interpreter, which already has uvicorn and FastAPI:

    uv run --directory backend python ../loadtest/stub_model.py --port 4020
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import random
import struct
import time
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

DEFAULT_PORT = 4020
"""Deliberately not 4010: the e2e stub owns that one, and a load run alongside a
Playwright run must not silently answer its requests."""

ANSWER = (
    "The stub model answered under load. This sentence exists to be several "
    "tokens long, so that a streamed reply has more than one frame in it and a "
    "time to first token means something."
)


class Behaviour:
    """How slow, and how unreliable, this server is being today."""

    def __init__(
        self,
        *,
        first_token_ms: float,
        token_ms: float,
        jitter: float,
        error_rate: float,
        timeout_rate: float,
        embedding_dim: int,
    ) -> None:
        self.first_token_ms = first_token_ms
        self.token_ms = token_ms
        self.jitter = jitter
        self.error_rate = error_rate
        self.timeout_rate = timeout_rate
        self.embedding_dim = embedding_dim
        # Seeded and reproducible on purpose: a run that injects failures has to
        # inject the same ones next time, or a comparison between two runs is
        # comparing dice. Nothing here is a secret.
        self._random = random.Random(20260916)  # noqa: S311

    def delay(self, milliseconds: float) -> float:
        """One wait, in seconds, spread by the configured jitter.

        Jitter rather than a constant because a fleet of identical waits makes
        the platform's own queueing invisible: every request arrives at the next
        stage at the same instant and the run measures a metronome.
        """
        if milliseconds <= 0:
            return 0.0
        spread = milliseconds * self.jitter
        return max(0.0, self._random.uniform(milliseconds - spread, milliseconds + spread)) / 1000

    def should_fail(self) -> bool:
        return self._random.random() < self.error_rate

    def should_hang(self) -> bool:
        return self._random.random() < self.timeout_rate


def vector_for(text: str, dimensions: int) -> list[float]:
    """A stable unit vector for a piece of text.

    Derived from the text's digest rather than from its meaning, so nothing here
    pretends to be an embedding model. What it has to be is *deterministic* and
    *normalised*: the same document seeded twice indexes to the same point, and
    cosine distance over unit vectors is what the store expects.
    """
    raw = b""
    counter = 0
    needed = dimensions * 4
    while len(raw) < needed:
        raw += hashlib.sha256(f"{text}:{counter}".encode()).digest()
        counter += 1
    numbers = [
        struct.unpack("<I", raw[index * 4 : index * 4 + 4])[0] / 0xFFFFFFFF - 0.5
        for index in range(dimensions)
    ]
    norm = math.sqrt(sum(number * number for number in numbers)) or 1.0
    return [number / norm for number in numbers]


def build(behaviour: Behaviour) -> FastAPI:
    """The server, with its behaviour bound in."""
    app = FastAPI(title="AgenticOS load-test stub model")

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Any:
        body = await request.json()
        if behaviour.should_hang():
            await asyncio.sleep(600)
        if behaviour.should_fail():
            return JSONResponse(
                status_code=500,
                content={"error": {"message": "The stub model was told to fail this one."}},
            )
        if body.get("stream"):
            return StreamingResponse(_stream(body), media_type="text/event-stream")
        await asyncio.sleep(behaviour.delay(behaviour.first_token_ms))
        await asyncio.sleep(behaviour.delay(behaviour.token_ms * len(ANSWER.split())))
        return JSONResponse(content=_completion(body, ANSWER))

    @app.post("/v1/embeddings")
    async def embeddings(request: Request) -> Any:
        body = await request.json()
        raw = body.get("input")
        texts = [raw] if isinstance(raw, str) else list(raw or [])
        await asyncio.sleep(behaviour.delay(behaviour.token_ms * max(1, len(texts))))
        return JSONResponse(
            content={
                "object": "list",
                "model": body.get("model", "stub-embedding"),
                "data": [
                    {
                        "object": "embedding",
                        "index": index,
                        "embedding": vector_for(str(text), behaviour.embedding_dim),
                    }
                    for index, text in enumerate(texts)
                ],
                "usage": {
                    "prompt_tokens": sum(len(str(text)) for text in texts),
                    "total_tokens": 0,
                },
            }
        )

    @app.get("/v1/models")
    async def models() -> Any:
        return JSONResponse(content={"object": "list", "data": [{"id": "stub-chat"}]})

    async def _stream(body: dict[str, Any]) -> AsyncIterator[bytes]:
        await asyncio.sleep(behaviour.delay(behaviour.first_token_ms))
        for word in ANSWER.split():
            frame = {
                "id": "stub",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": body.get("model", "stub-chat"),
                "choices": [{"index": 0, "delta": {"content": word + " "}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(frame)}\n\n".encode()
            await asyncio.sleep(behaviour.delay(behaviour.token_ms))
        done = {
            "id": "stub",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": body.get("model", "stub-chat"),
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(done)}\n\n".encode()
        yield b"data: [DONE]\n\n"

    return app


def _completion(body: dict[str, Any], text: str) -> dict[str, Any]:
    """One non-streamed answer, in the shape the Chat Completions API returns."""
    return {
        "id": "stub",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "stub-chat"),
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 64, "completion_tokens": len(text.split()), "total_tokens": 0},
    }


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "Loopback by default, because this answers anything that asks. A "
            "deployment whose API runs in a container cannot reach loopback on "
            "the host and needs 0.0.0.0 here - see docs/load-testing.md."
        ),
    )
    parser.add_argument(
        "--first-token-ms",
        type=float,
        default=400.0,
        help="How long before the first token. A hosted model's own is 300-900ms.",
    )
    parser.add_argument("--token-ms", type=float, default=12.0, help="Pace between tokens")
    parser.add_argument(
        "--jitter", type=float, default=0.3, help="Fraction each delay is spread by"
    )
    parser.add_argument(
        "--error-rate", type=float, default=0.0, help="Share of requests refused with a 500"
    )
    parser.add_argument(
        "--timeout-rate", type=float, default=0.0, help="Share of requests held open indefinitely"
    )
    parser.add_argument(
        "--embedding-dim",
        type=int,
        default=768,
        help="Width of the vectors served, which must match the collection's model",
    )
    return parser.parse_args(argv)


def main() -> None:
    arguments = parse()
    behaviour = Behaviour(
        first_token_ms=arguments.first_token_ms,
        token_ms=arguments.token_ms,
        jitter=arguments.jitter,
        error_rate=arguments.error_rate,
        timeout_rate=arguments.timeout_rate,
        embedding_dim=arguments.embedding_dim,
    )
    uvicorn.run(build(behaviour), host=arguments.host, port=arguments.port, log_level="warning")


if __name__ == "__main__":
    main()
