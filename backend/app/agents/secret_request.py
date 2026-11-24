"""Asking the person for a secret the agent needs but does not have.

An agent that needs an API key, token or credential it was not given asks
for it with the `request_secret` tool, naming exactly which secret and what
it is for. The run parks on the call - the same `CallDeferred` mechanism
`ask_user` parks on - and the person supplies the value through the card
the run's secret request draws. The value is sealed into the vault by the
fulfil endpoint and never enters the run: not the tool call, not the
transcript, not the manifest, not a log line. What the model reads back on
resume names the stored secret and its hint, never the value.

A run whose person declines is ended failed by the decline endpoint, with
the refusal as its error, rather than resumed to a model that would ask
again or stall. An unanswered request expires with the question window
(`QUESTION_EXPIRY_HOURS`), settled like an unanswered question.
"""

import json
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai.exceptions import CallDeferred
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse, ToolCallPart

SECRET_REQUEST_DEFERRED_KIND = "secret_request"
SECRET_REQUEST_TOOL = "request_secret"

MAX_SECRET_NAME_CHARS = 128
MAX_WHAT_FOR_CHARS = 1000

#: What the model reads when a request is fulfilled. Names the secret and its
#: hint only - the value is never a tool result, or the chat would render it.
SECRET_FULFILLED_PREFIX = "Secret provided and stored"


def secret_request_result(secret_name: str, hint: str) -> str:
    """The tool result a fulfilled request resumes with: name and hint only."""
    return (
        f"{SECRET_FULFILLED_PREFIX}: '{secret_name}'"
        + (f" (hint …{hint})" if hint else "")
        + ". Continue the work; the credential is stored under that name. "
        "Never ask the user for its value."
    )


#: What the model reads when a request is resumed without a value: the
#: decline the resume path supplies, so a call left without a result cannot
#: leave the run unresumable.
SECRET_DECLINED_RESULT = (
    "The user declined to provide this secret. Do not ask for it again; "
    "end with a failed report explaining the run cannot continue without it."
)


class SecretRequestItem(BaseModel):
    """One secret an agent asked its person for, as the card draws it."""

    secret_name: str = Field(
        min_length=1,
        max_length=MAX_SECRET_NAME_CHARS,
        description="The name the secret will be stored under.",
    )
    what_for: str = Field(
        min_length=1,
        max_length=MAX_WHAT_FOR_CHARS,
        description="What the secret is for, in the agent's own words.",
    )
    kind: str = Field(
        default="api_key",
        description="The shape of the credential, as the vault names it.",
    )


def _call_args(call: ToolCallPart) -> dict[str, Any]:
    """A parked call's arguments, as a mapping, whatever shape they stored in."""
    args = call.args
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def secret_request_item(call: ToolCallPart) -> SecretRequestItem:
    """Read a call already identified as a secret request, as the card draws it."""
    args = _call_args(call)
    return SecretRequestItem(
        secret_name=str(args.get("secret_name", "")).strip(),
        what_for=str(args.get("what_for", "")).strip(),
        kind=str(args.get("kind", "api_key") or "api_key"),
    )


def parked_secret_requests_by_call(
    paused_state: dict[str, Any] | None,
) -> dict[str, SecretRequestItem]:
    """The secret requests a parked run is waiting on, by tool call id.

    A pure mapping over the persisted state, like `parked_question_items`:
    a malformed call must not break an otherwise readable run list, so a
    call whose arguments do not parse is skipped rather than raised.
    """
    if paused_state is None:
        return {}
    payload = dict(paused_state)
    request_ids = payload.get("secret_requests", [])
    if not isinstance(request_ids, list):
        return {}
    wanted = {value for value in request_ids if isinstance(value, str)}
    if not wanted:
        return {}
    items: dict[str, SecretRequestItem] = {}
    for message in ModelMessagesTypeAdapter.validate_python(payload.get("messages", [])):
        if not isinstance(message, ModelResponse):
            continue
        for part in message.parts:
            if isinstance(part, ToolCallPart) and part.tool_call_id in wanted:
                try:
                    items[part.tool_call_id] = secret_request_item(part)
                except ValueError:
                    continue
    return items


def parked_secret_request_items(paused_state: dict[str, Any] | None) -> list[SecretRequestItem]:
    """The secret requests a parked run is waiting on, in call order."""
    return list(parked_secret_requests_by_call(paused_state).values())


async def park_the_secret_request() -> None:
    """The channel of a surface that answers later: the run parks on the call.

    Raising `CallDeferred` from inside the tool is what ends the run waiting
    on this call. Its metadata identifies a secret request even when a tool
    override changed the tool's exposed name.
    """
    raise CallDeferred(metadata={"kind": SECRET_REQUEST_DEFERRED_KIND})
