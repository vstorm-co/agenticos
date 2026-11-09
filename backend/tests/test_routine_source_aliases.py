"""Reviewed account aliases remain valid after the MCP runtime normalizes them."""

from uuid import uuid4

from app.agents.mcp import tool_prefix
from app.db.models.mcp_connection import McpConnection
from app.services.mcp_connection import reviewed_personal_sources


def test_colliding_account_labels_keep_distinct_normalized_aliases() -> None:
    accounts = [
        McpConnection(
            id=uuid4(),
            name=name,
            is_default=index == 0,
            url=f"https://account{index}.example.com",
            authorization_generation=uuid4(),
        )
        for index, name in enumerate(("Work", "Sales US", "Sales-US"))
    ]
    identities = reviewed_personal_sources("github", accounts)
    aliases = [identity.tool_prefix for identity in identities.values()]
    assert len(set(aliases)) == 3
    assert all(alias is not None and alias == tool_prefix(alias) for alias in aliases)
    assert reviewed_personal_sources("github", []) == {}
