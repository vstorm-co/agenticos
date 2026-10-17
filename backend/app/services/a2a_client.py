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

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

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


class A2AClientError(Exception):
    """A remote agent that could not be reached, read or understood. The message says which."""


@dataclass(frozen=True)
class A2AReply:
    """What a remote agent said, reduced to what a delegating agent reads."""

    text: str
    context_id: str | None
    state: str


def card_address(url: str) -> str:
    """The card's URL: as given when it names a JSON document, else the well-known path."""
    trimmed = url.strip()
    if trimmed.endswith(".json"):
        return trimmed
    return f"{trimmed.rstrip('/')}{CARD_PATH}"


async def fetch_card(url: str, *, transport: httpx2.AsyncBaseTransport | None = None) -> AgentCard:
    """Read and validate a remote agent's card.

    Raises:
        A2AClientError: The address is refused, unreachable, too large, not JSON or
            not a card - each said in a sentence somebody registering it can act on.
    """
    address = card_address(url)
    try:
        async with PinnedAsyncClient(timeout=_TIMEOUT, transport=transport) as client:
            response = await client.get(address, headers={"Accept": "application/json"})
    except UrlRefusedError as refused:
        raise A2AClientError(
            f"That address is not one this deployment may call: {refused}"
        ) from refused
    except httpx2.HTTPError as unreachable:
        raise A2AClientError("The agent card could not be fetched") from unreachable
    if response.status_code != 200:
        raise A2AClientError(f"The agent card answered HTTP {response.status_code}")
    if len(response.content) > MAX_CARD_BYTES:
        raise A2AClientError("The agent card is larger than an agent card should be")
    try:
        return AgentCard.model_validate_json(response.content)
    except ValidationError as invalid:
        raise A2AClientError("That address does not answer with an A2A agent card") from invalid


async def send_message(
    endpoint: str,
    text: str,
    *,
    context_id: str | None,
    bearer: str | None,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> A2AReply:
    """Send one message to a remote agent and read its answer.

    Raises:
        A2AClientError: The endpoint is refused or unreachable, answered something
            other than JSON-RPC, or answered with a JSON-RPC error.
    """
    message = Message(
        role="user",
        parts=[Part(kind="text", text=text)],
        messageId=uuid.uuid4().hex,
        contextId=context_id,
    )
    body = {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex,
        "method": "message/send",
        "params": {
            "message": message.model_dump(by_alias=True, exclude_none=True),
            "configuration": {"blocking": True, "acceptedOutputModes": ["text/plain"]},
        },
    }
    headers = {"Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    try:
        async with PinnedAsyncClient(timeout=_TIMEOUT, transport=transport) as client:
            response = await client.post(endpoint, json=body, headers=headers)
    except UrlRefusedError as refused:
        raise A2AClientError(
            f"The agent's address is not one this deployment may call: {refused}"
        ) from refused
    except httpx2.HTTPError as unreachable:
        raise A2AClientError("The agent could not be reached") from unreachable
    if response.status_code in (401, 403):
        raise A2AClientError("The agent refused the credential it was sent")
    if response.status_code != 200:
        raise A2AClientError(f"The agent answered HTTP {response.status_code}")
    try:
        payload: Any = response.json()
    except ValueError as invalid:
        raise A2AClientError("The agent did not answer with JSON") from invalid
    if not isinstance(payload, dict):
        raise A2AClientError("The agent did not answer with JSON-RPC")
    if "error" in payload:
        error = payload["error"] if isinstance(payload["error"], dict) else {}
        raise A2AClientError(
            f"The agent refused the task: {str(error.get('message', 'no reason given'))[:500]}"
        )
    return _reply(payload.get("result"))


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
    return A2AReply(text=_bounded(text), context_id=task.context_id, state=state)


def _bounded(text: str) -> str:
    if len(text) <= MAX_ANSWER_CHARS:
        return text
    return f"{text[:MAX_ANSWER_CHARS]}\n\n[The answer went on for {len(text) - MAX_ANSWER_CHARS} more characters.]"
