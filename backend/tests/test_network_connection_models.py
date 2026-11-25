"""Safe network-connection schemas and their resource permission contract."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.permissions import ROLE_PERMS, OrgRoleName, Perm, Scope
from app.db.models.network_connection import NetworkConnection
from app.schemas.network_connection import (
    NetworkConnectionRead,
    NetworkEnrollmentRead,
    NetworkPeerRead,
)


def test_connection_read_never_serializes_encrypted_payloads_or_lease_tokens():
    now = datetime.now(UTC)
    row = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        owner_user_id=uuid4(),
        scope="user",
        visibility="private",
        name="Personal laptop",
        desired_state="paused",
        auth_state="authenticated",
        runtime_state="stopped",
        cleanup_state="none",
        policy_generation=2,
        enrollment_expires_at=None,
        tailnet_name="tailnet.example",
        node_id="node-1",
        peers=[],
        last_seen_at=now,
        last_error_code=None,
        created_at=now,
        updated_at=None,
        state_payload="secret-state-ciphertext",
        login_payload="secret-login-ciphertext",
        lease_id=uuid4(),
        lease_expires_at=now,
    )

    response = NetworkConnectionRead.model_validate(row)
    output = response.model_dump(mode="json")

    assert "state_payload" not in output
    assert "login_payload" not in output
    assert "lease_id" not in output
    assert "lease_expires_at" not in output
    assert "secret-state-ciphertext" not in str(output)
    assert "secret-login-ciphertext" not in str(output)


def test_login_url_is_not_in_enrollment_repr():
    response = NetworkEnrollmentRead(login_url="https://login.tailscale.com/secret")

    assert "login.tailscale.com" not in repr(response)
    assert response.login_url == "https://login.tailscale.com/secret"


@pytest.mark.parametrize("ip", ["192.0.2.1", "2001:db8::1"])
def test_peer_accepts_valid_ip_addresses(ip: str):
    peer = NetworkPeerRead(id="node-1", ips=[ip], online=True)

    assert peer.ips == [ip]


def test_peer_rejects_invalid_ip_addresses():
    with pytest.raises(ValidationError):
        NetworkPeerRead(id="node-1", ips=["not-an-ip"], online=True)


def test_peer_rejects_unmodeled_fields():
    with pytest.raises(ValidationError):
        NetworkPeerRead.model_validate(
            {"id": "node-1", "online": True, "auth_key": "must-not-be-kept"}
        )


def test_network_role_scopes_match_connection_lifecycle_authority():
    assert ROLE_PERMS[OrgRoleName.OWNER][Perm.NETWORKS_VIEW] is Scope.ALL
    assert ROLE_PERMS[OrgRoleName.OWNER][Perm.NETWORKS_MANAGE] is Scope.ALL
    assert ROLE_PERMS[OrgRoleName.OWNER][Perm.NETWORKS_USE] is Scope.ALL

    for role in (OrgRoleName.ADMIN, OrgRoleName.BUILDER):
        assert ROLE_PERMS[role][Perm.NETWORKS_VIEW] is Scope.SHARED
        assert ROLE_PERMS[role][Perm.NETWORKS_MANAGE] is Scope.SHARED
        assert ROLE_PERMS[role][Perm.NETWORKS_USE] is Scope.SHARED

    for permission in (Perm.NETWORKS_VIEW, Perm.NETWORKS_MANAGE, Perm.NETWORKS_USE):
        assert ROLE_PERMS[OrgRoleName.MEMBER][permission] is Scope.OWN

    assert ROLE_PERMS[OrgRoleName.OPERATOR][Perm.NETWORKS_VIEW] is Scope.SHARED
    assert ROLE_PERMS[OrgRoleName.OPERATOR][Perm.NETWORKS_USE] is Scope.SHARED
    assert Perm.NETWORKS_MANAGE not in ROLE_PERMS[OrgRoleName.OPERATOR]
    assert all(
        permission not in ROLE_PERMS[OrgRoleName.VIEWER]
        for permission in (Perm.NETWORKS_VIEW, Perm.NETWORKS_MANAGE, Perm.NETWORKS_USE)
    )


@pytest.mark.security
def test_connection_table_has_tenant_identity_and_state_checks():
    table = NetworkConnection.__table__
    unique_column_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert ("id", "organization_id") in unique_column_sets
    assert {"organization_id", "owner_user_id"} <= set(table.columns.keys())
    check_names = {
        constraint.name
        for constraint in table.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    }
    assert "network_connections_ck_network_connection_scope_check" in check_names
    assert "network_connections_ck_network_connection_lease_pair_check" in check_names
