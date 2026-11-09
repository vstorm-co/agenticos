"""What the curated MCP catalog offers for Microsoft 365 and Gmail.

The two self-hosted mail servers are listed; the six Work IQ application servers
Microsoft keeps for compatibility only are not, and `work-iq` states its terms.
"""

import json
from urllib.parse import urlsplit

from app.core import catalog
from app.services import mcp_audit
from app.services.mcp_catalog import BY_KEY, CATALOG

REMOVED = (
    "m365-mail",
    "m365-calendar",
    "m365-teams",
    "m365-sharepoint",
    "m365-onedrive",
    "m365-word",
)


def test_the_self_hosted_mail_servers_are_offered() -> None:
    for key in ("google-workspace", "ms-365"):
        entry = BY_KEY[key]
        assert entry.auth == "oauth"
        assert entry.url == ""
        assert entry.category == "communication"
    assert BY_KEY["google-workspace"].docs_url.endswith("taylorwilsdon/google_workspace_mcp")
    assert BY_KEY["ms-365"].docs_url.endswith("softeria/ms-365-mcp-server")
    assert "MCP_ENABLE_OAUTH21=true" in BY_KEY["google-workspace"].token_hint
    assert "--org-mode" in BY_KEY["ms-365"].token_hint


def test_the_work_iq_applications_are_gone_and_work_iq_stays() -> None:
    assert not set(REMOVED) & set(BY_KEY)
    work_iq = BY_KEY["work-iq"]
    assert work_iq.url == "https://workiq.svc.cloud.microsoft/mcp"
    assert work_iq.auth == "oauth"
    assert "Copilot Credits" in work_iq.description
    assert "25 results" in work_iq.description
    assert "tenant administrator" in work_iq.token_hint


def test_every_catalog_entry_has_a_check_and_no_check_names_a_removed_entry() -> None:
    rows = json.loads((catalog._DIR / mcp_audit.SNAPSHOT).read_text())
    checked = {row["key"] for row in rows if row["source"] == "catalog"}
    assert checked == {entry.key for entry in CATALOG}


def test_official_workspace_apps_have_independent_hosted_oauth_connections() -> None:
    hosts = {
        "google-gmail": "gmailmcp",
        "google-drive": "drivemcp",
        "google-docs": "docsmcp",
        "google-sheets": "sheetsmcp",
        "google-slides": "slidesmcp",
        "google-calendar": "calendarmcp",
        "google-chat": "chatmcp",
        "google-people": "people",
        "google-classroom": "classroommcp",
        "google-workspace-search": "workspacemcp",
    }
    for key, host in hosts.items():
        entry = BY_KEY[key]
        assert entry.url == f"https://{host}.googleapis.com/mcp/v1"
        assert entry.auth == "oauth"
        assert entry.docs_url.startswith("https://developers.google.com/")
        assert "Developer Preview" in entry.token_hint
        assert "OAuth client" in entry.token_hint
        assert entry.icon


def test_google_cloud_uses_verified_remote_addresses_without_region_placeholders() -> None:
    assert BY_KEY["bigquery"].url == "https://bigquery.googleapis.com/mcp"
    assert BY_KEY["bigquery"].docs_url
    official = [
        entry
        for entry in CATALOG
        if urlsplit(entry.url).scheme == "https"
        and (urlsplit(entry.url).hostname or "").endswith(".googleapis.com")
    ]
    assert len(official) >= 70
    assert len({entry.url for entry in official}) == len(official)
    for entry in official:
        assert entry.auth == "oauth"
        assert "REGION" not in entry.url
        assert entry.docs_url
        assert entry.token_hint
        assert entry.icon
