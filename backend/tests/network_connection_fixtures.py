"""Synthetic network identities; no fixture contacts Tailscale or stores a real key."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.permissions import AuthContext
from app.db.models.network_connection import NetworkConnection
from app.worker.jobs import RunNetworkConnection


def network_row(**changes) -> NetworkConnection:
    now = datetime.now(UTC)
    values = {
        "id": uuid4(),
        "organization_id": uuid4(),
        "owner_user_id": uuid4(),
        "scope": "user",
        "visibility": "private",
        "name": "My devices",
        "desired_state": "paused",
        "auth_state": "not_connected",
        "runtime_state": "stopped",
        "cleanup_state": "none",
        "policy_generation": 1,
        "state_payload": None,
        "login_payload": None,
        "secret_key_version": 1,
        "enrollment_id": None,
        "enrollment_user_id": None,
        "enrollment_session_id": None,
        "enrollment_expires_at": None,
        "tailnet_name": None,
        "node_id": None,
        "peers": [],
        "last_seen_at": None,
        "last_error_code": None,
        "lease_id": None,
        "lease_expires_at": None,
        "state_sequence": 0,
        "created_at": now,
        "updated_at": now,
    }
    return NetworkConnection(**(values | changes))


def owner_context(row: NetworkConnection, **changes) -> AuthContext:
    return AuthContext(
        **(
            {
                "user_id": row.owner_user_id,
                "organization_id": row.organization_id,
                "role": "owner",
            }
            | changes
        )
    )


def admitted_row(**changes) -> NetworkConnection:
    row = network_row()
    values = {
        "id": row.id,
        "organization_id": row.organization_id,
        "owner_user_id": row.owner_user_id,
        "desired_state": "active",
        "runtime_state": "starting",
        "enrollment_id": uuid4(),
        "enrollment_user_id": row.owner_user_id,
        "enrollment_session_id": uuid4(),
        "enrollment_expires_at": datetime.now(UTC) + timedelta(minutes=10),
    }
    return network_row(**(values | changes))


def node_job(row: NetworkConnection, mode="enroll") -> RunNetworkConnection:
    return RunNetworkConnection(
        organization_id=row.organization_id,
        connection_id=row.id,
        enrollment_id=row.enrollment_id,
        policy_generation=row.policy_generation,
        mode=mode,
    )
