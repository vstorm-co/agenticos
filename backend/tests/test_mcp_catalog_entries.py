"""What the curated MCP catalog offers for Microsoft 365 and Gmail.

The two self-hosted mail servers are listed; the six Work IQ application servers
Microsoft keeps for compatibility only are not, and `work-iq` states its terms.
"""

import json

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
