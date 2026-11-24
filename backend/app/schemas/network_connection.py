"""Network connection request and response schemas.

Encrypted node and enrollment payloads are deliberately absent. The login URL is
returned only by the session-bound enrollment response and is hidden from repr.
"""

import ipaddress
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from app.schemas.base import BaseSchema, TimestampSchema

NetworkScope = Literal["user", "org"]
NetworkVisibility = Literal["private", "team", "org"]
NetworkDesiredState = Literal["active", "paused", "revoked"]
NetworkAuthState = Literal[
    "not_connected",
    "sign_in_required",
    "approval_required",
    "authenticated",
    "expired",
    "error",
]
NetworkRuntimeState = Literal["stopped", "starting", "running", "unavailable"]
NetworkCleanupState = Literal["none", "pending", "manual", "complete"]
NetworkErrorCode = Literal[
    "runtime_unavailable",
    "runtime_disconnected",
    "invalid_runtime_response",
    "invalid_runtime_sequence",
    "runtime_failed",
    "runtime_timeout",
    "control_plane_unavailable",
    "runtime_frame_too_large",
    "authority_revoked",
    "enrollment_expired",
    "identity_changed",
    "lease_lost",
]
NETWORK_ERROR_CODES: tuple[NetworkErrorCode, ...] = (
    "runtime_unavailable",
    "runtime_disconnected",
    "invalid_runtime_response",
    "invalid_runtime_sequence",
    "runtime_failed",
    "runtime_timeout",
    "control_plane_unavailable",
    "runtime_frame_too_large",
    "authority_revoked",
    "enrollment_expired",
    "identity_changed",
    "lease_lost",
)


class NetworkConnectionCreate(BaseSchema):
    """Create a paused user or organization connection record."""

    name: str = Field(min_length=1, max_length=120)
    scope: NetworkScope


class NetworkPeerRead(BaseSchema):
    """One validated peer identity snapshot; it conveys presence, not action consent."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    hostname: str = Field(default="", max_length=255)
    dns_name: str | None = Field(default=None, max_length=255)
    ips: list[str] = Field(default_factory=list, max_length=16)
    online: bool
    os: str = Field(default="", max_length=32)

    @field_validator("ips")
    @classmethod
    def valid_ips(cls, value: list[str]) -> list[str]:
        for ip in value:
            ipaddress.ip_address(ip)
        return value


class NetworkConnectionRead(TimestampSchema, BaseSchema):
    """Safe projection of a connection; encrypted payloads and leases stay private."""

    id: UUID
    organization_id: UUID
    owner_user_id: UUID | None
    scope: NetworkScope
    visibility: NetworkVisibility
    name: str
    desired_state: NetworkDesiredState
    auth_state: NetworkAuthState
    runtime_state: NetworkRuntimeState
    cleanup_state: NetworkCleanupState
    policy_generation: int
    enrollment_expires_at: datetime | None = None
    tailnet_name: str | None = None
    node_id: str | None = None
    peers: list[NetworkPeerRead]
    last_seen_at: datetime | None = None
    last_error_code: NetworkErrorCode | None = None
    can_manage: bool = False


class NetworkConnectionList(BaseSchema):
    items: list[NetworkConnectionRead]
    total: int
    available: bool


class NetworkEnrollmentRead(BaseSchema):
    """Only the session that began an enrollment may receive its login URL."""

    attempt_id: UUID | None = None
    expires_at: datetime | None = None
    login_url: str | None = Field(default=None, repr=False)


class NetworkPeerList(BaseSchema):
    items: list[NetworkPeerRead]
    observed_at: datetime | None = None
