"""The one place a portal key resolves to its adapter.

A portal absent here has no auto-registration - the create flow reads `None` as
"manual", exactly what a manual-delivery portal wants. So adding an adapter is a
one-line entry, and a portal never needs one to work.
"""

from app.services.portals.base import PortalAdapter
from app.services.portals.github import GitHubPortalAdapter
from app.services.portals.github_app import GitHubAppPortalAdapter
from app.services.portals.google import GooglePortalAdapter
from app.services.portals.google_calendar import GoogleCalendarPortalAdapter
from app.services.portals.google_drive import GoogleDrivePortalAdapter
from app.services.portals.microsoft_files import MicrosoftFilesPortalAdapter
from app.services.portals.outlook import OutlookPortalAdapter
from app.services.portals.outlook_calendar import OutlookCalendarPortalAdapter

_ADAPTERS: dict[str, PortalAdapter] = {
    GitHubPortalAdapter.portal_key: GitHubPortalAdapter(),
    GitHubAppPortalAdapter.portal_key: GitHubAppPortalAdapter(),
    GooglePortalAdapter.portal_key: GooglePortalAdapter(),
    OutlookPortalAdapter.portal_key: OutlookPortalAdapter(),
    GoogleDrivePortalAdapter.portal_key: GoogleDrivePortalAdapter(),
    GoogleCalendarPortalAdapter.portal_key: GoogleCalendarPortalAdapter(),
    MicrosoftFilesPortalAdapter.portal_key: MicrosoftFilesPortalAdapter(),
    OutlookCalendarPortalAdapter.portal_key: OutlookCalendarPortalAdapter(),
}


def get_adapter(portal_key: str) -> PortalAdapter | None:
    """The adapter for a portal, or None when it registers no webhook automatically."""
    return _ADAPTERS.get(portal_key)
