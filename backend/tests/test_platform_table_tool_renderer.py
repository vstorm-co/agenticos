"""The web chat's table renderer names the platform's record tools by name.

The console reads a platform table call - `agenticos_query_virtual_table` and the
record tools - through the table it names, and it recognizes those calls by tool
name in `frontend/src/lib/table-tool-calls.ts`. MCP tools have no row in the
capability catalog, so nothing else ties that list to the server: a rename here
would leave the renderer and its tests green while every call fell back to raw ids.
"""

import re
from pathlib import Path
from unittest.mock import MagicMock

from app.services.platform_mcp._tools import platform_tools

RENDERER_PATH = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "table-tool-calls.ts"
)


def _rendered_tools() -> frozenset[str]:
    """The tool names the renderer's `TOOLS` table holds, without the server prefix."""
    source = RENDERER_PATH.read_text(encoding="utf-8")
    start = source.index("const TOOLS")
    body = source[source.index("{", start) : source.index("\n};", start)]
    return frozenset(re.findall(r"^  agenticos_([a-z][a-z0-9_]*): ", body, flags=re.MULTILINE))


def _record_tools() -> frozenset[str]:
    """Every platform tool that queries or touches a table's records."""
    names = {tool.name for tool in platform_tools(MagicMock())}
    return frozenset(
        name for name in names if name == "query_virtual_table" or "virtual_table_record" in name
    )


def test_every_tool_the_renderer_names_is_one_the_platform_server_offers():
    rendered = _rendered_tools()
    assert rendered, "the renderer's TOOLS table could not be read"
    assert rendered <= {tool.name for tool in platform_tools(MagicMock())}


def test_every_platform_record_tool_has_a_renderer():
    assert _record_tools() == _rendered_tools()
