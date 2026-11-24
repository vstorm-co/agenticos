"""Bounded, secret-aware messages exchanged with one dedicated node process.

The child receives no database or vault key. State writes are acknowledged only
after the parent commits a fenced vault envelope, and a missed heartbeat stops
the node. No socket or general-purpose proxy is exposed by this protocol.
"""

import base64
import binascii
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, TypeAdapter, field_validator

from app.schemas.network_connection import NetworkPeerRead

MAX_FRAME_BYTES = 1024 * 1024
MAX_STATE_BYTES = 512 * 1024
HEARTBEAT_SECONDS = 3
LEASE_SECONDS = 15


class BrokerFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class StateFrame(BrokerFrame):
    type: Literal["state"]
    sequence: int = Field(ge=1)
    state: dict[str, SecretStr] = Field(max_length=256)

    @field_validator("state")
    @classmethod
    def bounded_state(cls, value: dict[str, SecretStr]) -> dict[str, SecretStr]:
        size = 0
        for key, secret in value.items():
            if not key or len(key.encode()) > 256:
                raise ValueError("Invalid node state key")
            try:
                size += len(base64.b64decode(secret.get_secret_value(), validate=True))
            except (binascii.Error, ValueError) as exc:
                raise ValueError("Invalid node state encoding") from exc
            if size > MAX_STATE_BYTES:
                raise ValueError("Node state exceeds its limit")
        return value


class StatusFrame(BrokerFrame):
    type: Literal["status"]
    backend_state: str = Field(max_length=64)
    auth_url: SecretStr | None = None
    tailnet_name: str | None = Field(default=None, max_length=255)
    node_id: str | None = Field(default=None, max_length=128)
    key_expired: bool = False
    peers: list[NetworkPeerRead] = Field(default_factory=list, max_length=1024)

    @field_validator("auth_url")
    @classmethod
    def trusted_login_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value():
            return None
        raw = value.get_secret_value()
        try:
            url = urlsplit(raw)
            valid = (
                len(raw) <= 4096
                and raw.isascii()
                and not any(ord(char) < 33 or ord(char) == 127 for char in raw)
                and url.scheme == "https"
                and url.hostname == "login.tailscale.com"
                and url.port in (None, 443)
                and url.username is None
                and url.password is None
                and not url.fragment
                and url.path.startswith("/a/")
            )
        except ValueError as exc:
            raise ValueError("Invalid provider login URL") from exc
        if not valid:
            raise ValueError("Invalid provider login URL")
        return value


class CompleteFrame(BrokerFrame):
    type: Literal["complete"]
    reason: Literal["ready", "timeout", "logged_out", "stopped"]


class ErrorFrame(BrokerFrame):
    type: Literal["error"]
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z_]+$")


Frame = Annotated[
    StateFrame | StatusFrame | CompleteFrame | ErrorFrame, Field(discriminator="type")
]
FRAME_ADAPTER = TypeAdapter(Frame)


class NodeState(BaseModel):
    """Secrets are masked in repr; only the pipe writer reveals the values."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    state: dict[str, SecretStr] = Field(default_factory=dict, max_length=256)

    @field_validator("state")
    @classmethod
    def validate_state(cls, value: dict[str, SecretStr]) -> dict[str, SecretStr]:
        return StateFrame.bounded_state(value)

    def wire_state(self) -> dict[str, str]:
        return {key: value.get_secret_value() for key, value in self.state.items()}
