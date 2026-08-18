"""The one place a portal key resolves to its adapter.

A portal absent here has no auto-registration - the create flow reads `None` as
"manual", exactly what a manual-delivery portal wants. So adding an adapter is a
one-line entry, and a portal never needs one to work.
"""

from __future__ import annotations

from app.services.portals.base import PortalAdapter
from app.services.portals.github import GitHubPortalAdapter

_ADAPTERS: dict[str, PortalAdapter] = {
    GitHubPortalAdapter.portal_key: GitHubPortalAdapter(),
}


def get_adapter(portal_key: str) -> PortalAdapter | None:
    """The adapter for a portal, or None when it registers no webhook automatically."""
    return _ADAPTERS.get(portal_key)
