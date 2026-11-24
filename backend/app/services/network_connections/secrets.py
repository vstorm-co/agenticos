"""Vault ownership follows the connection, organization and personal owner together."""

from app.core.exceptions import BadRequestError
from app.core.vault import VaultScope, current_key_version
from app.db.models.network_connection import NetworkConnection


def connection_scope(row: NetworkConnection) -> VaultScope:
    if row.scope == "user" and row.owner_user_id is None:
        raise BadRequestError(message="This connection no longer has an owner")
    return VaultScope.network_connection(
        organization_id=row.organization_id,
        connection_id=row.id,
        owner_user_id=row.owner_user_id if row.scope == "user" else None,
    )


def write_key_version(row: NetworkConnection) -> int:
    """An empty row starts at today's key; existing envelopes rotate together."""
    if row.state_payload is not None or row.login_payload is not None:
        return row.secret_key_version
    return current_key_version()
