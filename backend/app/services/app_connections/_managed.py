"""Vendor knowledge for managed personal apps — the one place that names a vendor.

The shared MCP service enforces managed-account policy generically: a managed
account cannot be patched, deleted or probed as an ordinary MCP server, its auth
headers never come from the row, and it connects from Connections → Apps rather
than from the generic MCP flow. This module is the registry that says which auth
types and catalog keys are managed. A future provider registers here; no other
module names a vendor.
"""

MANAGED_AUTH_TYPES: frozenset[str] = frozenset({"composio"})
MANAGED_CATALOG_PREFIX = "composio-"


def is_managed_auth_type(auth_type: str | None) -> bool:
    """True when a stored auth type belongs to a managed provider."""
    return auth_type is not None and auth_type in MANAGED_AUTH_TYPES


def is_managed_catalog_key(catalog_key: str | None) -> bool:
    """True when a catalog key names a managed app (`composio-<toolkit>`)."""
    return catalog_key is not None and catalog_key.lower().startswith(MANAGED_CATALOG_PREFIX)
