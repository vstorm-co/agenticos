"""Code execution capability — arithmetic and data work in a sandbox."""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.code_execution._capability import CodeExecution

__all__ = ["CodeExecution"]


@register(
    id="code_execution",
    name="Run Python",
    category="analysis",
    description="Compute with a short Python program in a restricted sandbox.",
    tools=(
        CapabilityToolInfo(
            id="run_python",
            description="Run a small Python program to compute something.",
        ),
    ),
    scopes=("code:execute",),
)
def _build(ctx: CapabilityBuildContext) -> CodeExecution:
    return CodeExecution()
