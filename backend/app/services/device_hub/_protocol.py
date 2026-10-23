"""The frames the desktop app and the server exchange over the device socket.

JSON text frames, each with a `type`. The server sends `call` and `cancel`; the
app sends `hello`, `result` and `ping`. A call's id ties its result back to the
caller, which may be on another API host or in the worker, so ids are random and
never reused. Bytes - a file, a screenshot - travel base64-encoded inside
`args` and `value`; the frame size the app accepts is the bound on them.
"""

import secrets
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

MAX_FRAME_BYTES = 16 * 2**20
"""The largest frame either side sends or accepts - a screenshot or a file read."""


class Capabilities(BaseModel):
    """What the app on this computer can do, as it announces it."""

    model_config = ConfigDict(extra="ignore")

    sandbox_modes: list[Literal["read_only", "workspace_write", "full_access"]] = Field(
        default_factory=list
    )
    """The local sandbox's modes this OS supports; empty when it has none."""

    screen: bool = False
    """Whether the app can capture the screen and send input (permissions granted)."""


class Hello(BaseModel):
    """The app's first frame, and again whenever what it can do changes."""

    type: Literal["hello"]
    version: str = Field(default="", max_length=32)
    capabilities: Capabilities = Field(default_factory=Capabilities)


class Result(BaseModel):
    """The answer to one call: a value, or an error the caller turns into a sentence."""

    type: Literal["result"]
    id: str = Field(min_length=1, max_length=64)
    ok: bool
    value: dict[str, Any] = Field(default_factory=dict)
    error: str | None = Field(default=None, max_length=2000)


class Ping(BaseModel):
    """Keeps the socket - and the device's presence - alive between calls."""

    type: Literal["ping"]


AppFrame = Annotated[Hello | Result | Ping, Field(discriminator="type")]
APP_FRAME: TypeAdapter[Hello | Result | Ping] = TypeAdapter(AppFrame)


class Call(BaseModel):
    """One operation for the app to run, as the server sends it."""

    type: Literal["call"] = "call"
    id: str
    op: str
    args: dict[str, Any] = Field(default_factory=dict)


class Cancel(BaseModel):
    """The caller gave up on a call - timed out, or its run was stopped."""

    type: Literal["cancel"] = "cancel"
    id: str


def new_call_id() -> str:
    """An id no other call, on any host, will have."""
    return secrets.token_urlsafe(18)
