"""The tool the model is offered, and the text it reads before calling it.

The sandbox itself is `_sandbox.py`; this is only how it is presented to the
model. Kept apart for the same reason across this package: the tool's name and
description are prompt, and prompt lives where an author can find it.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities.code_execution._sandbox import (
    DEFAULT_MAX_MEMORY_MB,
    DEFAULT_TIMEOUT_SECS,
    run_python,
)


def build_toolset(
    *,
    timeout_secs: float = DEFAULT_TIMEOUT_SECS,
    max_memory_mb: int = DEFAULT_MAX_MEMORY_MB,
) -> FunctionToolset[Any]:
    """The single `run_python` tool, bound to this agent's sandbox limits.

    Registered under an explicit name because the Python function is called
    `run_python_tool` to avoid shadowing the sandbox it calls; the model must
    still see `run_python`, which is what the catalog and every stored override
    key on.
    """

    async def run_python_tool(code: str) -> str:
        """Run a small Python program to compute something.

        Use for arithmetic, date maths and data transformation you would
        otherwise do in your head. The sandbox has no network and no filesystem,
        so it is for calculation - not for fetching or storing anything.

        Args:
            code: The program. Print what you want to read back.

        Returns:
            Standard output and the value of the final expression.
        """
        return await run_python(code, timeout_secs=timeout_secs, max_memory_mb=max_memory_mb)

    toolset: FunctionToolset[Any] = FunctionToolset()
    toolset.add_function(run_python_tool, takes_ctx=False, name="run_python")
    return toolset
