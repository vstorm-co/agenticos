"""The platform's operations, as tools an agent calls.

The functions are the MCP server's - `app.services.platform_mcp.platform_tools` -
so the in-app assistant and Claude Code read the same names and descriptions and
make the same public API calls. Only two things differ here: the credential is the
one minted for the person this run acts for, and a refusal is the tool's result,
not an exception, so the model can tell the person why rather than retry.
"""

from __future__ import annotations

import importlib
from typing import Any

from pydantic_ai.toolsets import FunctionToolset
from starlette.types import ASGIApp

from app.services.platform_mcp import PlatformApi, platform_tools


def refused(message: str) -> dict[str, Any]:
    """A refusal as the tool's result: the model reads why, and tells the person."""
    return {"refused": message}


def _api_app() -> ASGIApp:
    """The API application, called in-process.

    Imported when a run needs it, not at module load: `app.main` imports the
    capability registry, and a worker running a scheduled agent has the
    application object without serving it - which is all an in-process call
    needs.
    """
    return importlib.import_module("app.main").app


def build_toolset(credential: str) -> FunctionToolset[Any]:
    api = PlatformApi(_api_app(), token=lambda: credential, on_refusal=refused)
    toolset: FunctionToolset[Any] = FunctionToolset()
    for tool in platform_tools(api):
        toolset.add_function(tool.function, takes_ctx=False, name=tool.name)
    return toolset
