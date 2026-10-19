"""Calling another vendor's agent over A2A (#2092).

Two requests, both through :class:`app.core.pinned_http.PinnedAsyncClient`: the
agent card, read when somebody registers the agent, and `message/send`, sent
whenever a delegating agent hands it work. A card and an endpoint are addresses
somebody outside the deployment chose, so every hop is checked against the SSRF
policy and dialled at the address that check approved - the remote party cannot
point this deployment at its own network.

What comes back is reduced to text: the answer, the conversation to continue,
and the task's state. An agent that answers `input-required` or `auth-required`
says so in the text, because a delegate that is waiting on its own user is an
answer the delegating model has to read, not an error.
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import anyio
import httpx2
from pydantic import ValidationError

from app.core.pinned_http import PinnedAsyncClient
from app.core.sanitize import UrlRefusedError
from app.schemas.a2a import AgentCard, Message, Part, Task

logger = logging.getLogger(__name__)

CARD_PATH = "/.well-known/agent-card.json"
"""Where A2A 0.3 publishes a card, relative to the agent's base address."""

MAX_CARD_BYTES = 256 * 1024
MAX_ANSWER_CHARS = 100_000
"""How much of a remote agent's answer reaches the delegating model."""

_TIMEOUT = httpx2.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
"""A remote agent may think for minutes; connecting to it should not take long."""

_WAITING = {
    "input-required": "It is waiting for more input from you",
    "auth-required": "It needs its own sign-in before it can continue",
    "working": "It is still working on it",
    "submitted": "It has accepted the task and not started it",
}


_STILL_GOING = frozenset({"working", "submitted"})
"""States a task is read again from - it is under way and will end on its own."""

POLL_SECONDS = 2.0
"""How long between reads of a task still under way."""

POLL_FOR_SECONDS = 600.0
"""How long a task still under way is waited for before its state is the answer."""

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
"""How much of a remote agent's reply is read before it is refused.

Counted while it arrives, not after: a remote agent is somebody else's server,
and one answering with an endless body would otherwise fill this worker's memory
twice over - once buffered, once parsed - before `MAX_ANSWER_CHARS` cut anything.
"""


class A2AClientError(Exception):
    """A remote agent that could not be reached, read or understood. The message says which."""


@dataclass(frozen=True)
class A2AReply:
    """What a remote agent said, reduced to what a delegating agent reads."""

    text: str
    context_id: str | None
    state: str
    # The remote task, kept so a task waiting on input or a sign-in is continued
    # rather than a new one started beside it. `None` for a plain message reply.
    task_id: str | None = None


def card_address(url: str) -> str:
    """The card's URL: as given when it names a JSON document, else the well-known path.

    Read off the path, not the end of the string: a signed card address ends in
    its query, and the well-known path appended after that lands in the query.
    """
    parts = urlsplit(url.strip())
    if parts.path.endswith(".json"):
        return urlunsplit(parts)
    return urlunsplit(parts._replace(path=f"{parts.path.rstrip('/')}{CARD_PATH}"))


async def fetch_card(url: str, *, transport: httpx2.AsyncBaseTransport | None = None) -> AgentCard:
    """Read and validate a remote agent's card.

    Raises:
        A2AClientError: The address is refused, unreachable, too large, not JSON or
            not a card - each said in a sentence somebody registering it can act on.
    """
    address = card_address(url)
    try:
        async with (
            PinnedAsyncClient(timeout=_TIMEOUT, transport=transport) as client,
            client.stream("GET", address, headers={"Accept": "application/json"}) as response,
        ):
            if response.status_code != 200:
                raise A2AClientError(f"The agent card answered HTTP {response.status_code}")
            content = await _read_bounded(
                response,
                MAX_CARD_BYTES,
                "The agent card is larger than an agent card should be",
            )
    except UrlRefusedError as refused:
        raise A2AClientError(
            f"That address is not one this deployment may call: {refused}"
        ) from refused
    except httpx2.HTTPError as unreachable:
        raise A2AClientError("The agent card could not be fetched") from unreachable
    try:
        card = AgentCard.model_validate_json(content)
    except ValidationError as invalid:
        raise A2AClientError("That address does not answer with an A2A agent card") from invalid
    # Every request this client sends is a JSON-RPC POST to the card's url; an
    # agent that serves gRPC or HTTP+JSON there would take the registration and
    # then fail every delegation.
    if card.preferred_transport.upper() != "JSONRPC":
        raise A2AClientError(
            f"That agent offers A2A over {card.preferred_transport[:40]}, and this "
            "deployment speaks only JSON-RPC"
        )
    return card


async def send_message(
    endpoint: str,
    text: str,
    *,
    context_id: str | None,
    task_id: str | None = None,
    bearer: str | None,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> A2AReply:
    """Send one message to a remote agent and read its answer.

    A task the agent accepted and is still working on is read again
    (`tasks/get`) until it ends, for up to `POLL_FOR_SECONDS`: the protocol lets
    an agent answer `message/send` before it is done, and the task is the only
    thing the answer will land on. `task_id` continues a task that was waiting
    for more input.

    Raises:
        A2AClientError: The endpoint is refused or unreachable, answered something
            other than JSON-RPC, or answered with a JSON-RPC error.
    """
    message = Message(
        role="user",
        parts=[Part(kind="text", text=text)],
        messageId=uuid.uuid4().hex,
        contextId=context_id,
        taskId=task_id,
    )
    reply = _reply(
        await _call(
            endpoint,
            "message/send",
            {
                "message": message.model_dump(by_alias=True, exclude_none=True),
                # Not blocking: an agent that holds the request until it is done
                # runs past the read timeout on a long task, and the task it had
                # accepted reads as an agent that could not be reached. The task
                # comes back at once and is polled below.
                "configuration": {"blocking": False, "acceptedOutputModes": ["text/plain"]},
            },
            bearer=bearer,
            transport=transport,
        )
    )
    deadline = time.monotonic() + POLL_FOR_SECONDS
    while reply.state in _STILL_GOING and reply.task_id and time.monotonic() < deadline:
        await anyio.sleep(POLL_SECONDS)
        reply = _reply(
            await _call(
                endpoint, "tasks/get", {"id": reply.task_id}, bearer=bearer, transport=transport
            )
        )
    return reply


async def _call(
    endpoint: str,
    method: str,
    params: dict[str, Any],
    *,
    bearer: str | None,
    transport: httpx2.AsyncBaseTransport | None,
) -> Any:
    """One JSON-RPC call, answering its `result`."""
    body = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method, "params": params}
    headers = {"Accept": "application/json"}
    if bearer:
        # Never over plain HTTP: anyone on the path, a proxy included, would read
        # the organization's key off the header.
        if urlsplit(endpoint).scheme != "https":
            raise A2AClientError("The agent's endpoint is not HTTPS, so its key was not sent")
        headers["Authorization"] = f"Bearer {bearer}"
    try:
        async with (
            PinnedAsyncClient(timeout=_TIMEOUT, transport=transport) as client,
            client.stream("POST", endpoint, json=body, headers=headers) as response,
        ):
            if response.status_code in (401, 403):
                raise A2AClientError("The agent refused the credential it was sent")
            if response.status_code != 200:
                raise A2AClientError(f"The agent answered HTTP {response.status_code}")
            raw = await _read_bounded(
                response,
                MAX_RESPONSE_BYTES,
                f"The agent answered with more than {MAX_RESPONSE_BYTES // (1024 * 1024)} MB",
            )
    except UrlRefusedError as refused:
        raise A2AClientError(
            f"The agent's address is not one this deployment may call: {refused}"
        ) from refused
    except httpx2.HTTPError as unreachable:
        raise A2AClientError("The agent could not be reached") from unreachable
    try:
        payload: Any = json.loads(raw)
    except ValueError as invalid:
        raise A2AClientError("The agent did not answer with JSON") from invalid
    if not isinstance(payload, dict):
        raise A2AClientError("The agent did not answer with JSON-RPC")
    if "error" in payload:
        error = payload["error"] if isinstance(payload["error"], dict) else {}
        raise A2AClientError(
            f"The agent refused the task: {str(error.get('message', 'no reason given'))[:500]}"
        )
    return payload.get("result")


async def _read_bounded(response: httpx2.Response, ceiling: int, refusal: str) -> bytes:
    """The body, refused with `refusal` as soon as it passes `ceiling` bytes."""
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body += chunk
        if len(body) > ceiling:
            raise A2AClientError(refusal)
    return bytes(body)


def _reply(result: Any) -> A2AReply:
    if not isinstance(result, dict):
        raise A2AClientError("The agent answered with no result")
    try:
        if result.get("kind") == "message":
            answer = Message.model_validate(result)
            return A2AReply(
                text=_bounded(answer.text()), context_id=answer.context_id, state="completed"
            )
        task = Task.model_validate(result)
    except ValidationError as invalid:
        raise A2AClientError("The agent answered with neither a task nor a message") from invalid
    state = task.status.state
    text = task.text()
    if state in _WAITING:
        text = f"{_WAITING[state]}.\n\n{text}".strip()
    elif state in ("failed", "rejected", "canceled"):
        text = f"The agent's task {state}.\n\n{text}".strip()
    return A2AReply(text=_bounded(text), context_id=task.context_id, state=state, task_id=task.id)


def _bounded(text: str) -> str:
    if len(text) <= MAX_ANSWER_CHARS:
        return text
    return f"{text[:MAX_ANSWER_CHARS]}\n\n[The answer went on for {len(text) - MAX_ANSWER_CHARS} more characters.]"
