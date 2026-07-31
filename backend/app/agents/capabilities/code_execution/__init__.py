"""Code execution capability - arithmetic and data work in a sandbox."""

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.code_execution._capability import CodeExecution
from app.agents.capabilities.code_execution._sandbox import (
    DEFAULT_MAX_MEMORY_MB,
    DEFAULT_TIMEOUT_SECS,
)

__all__ = ["CodeExecution", "CodeExecutionConfig"]


class CodeExecutionConfig(BaseModel):
    """What one `run_python` call may cost.

    Capped rather than open-ended: the sandbox has no network or filesystem,
    so time and memory are the only resources a runaway program can take -
    and an author raising a limit for one data-heavy agent should not need
    an operator or a redeploy to do it.
    """

    timeout_secs: float = Field(
        default=DEFAULT_TIMEOUT_SECS,
        gt=0,
        le=120,
        description="Wall-clock budget for one call, in seconds",
    )
    max_memory_mb: int = Field(
        default=DEFAULT_MAX_MEMORY_MB,
        ge=16,
        le=4096,
        description="Memory cap for one call, in megabytes",
    )


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
    config_schema=CodeExecutionConfig,
    scopes=("code:execute",),
)
def _build(ctx: CapabilityBuildContext) -> CodeExecution:
    config = ctx.config if isinstance(ctx.config, CodeExecutionConfig) else CodeExecutionConfig()
    return CodeExecution(timeout_secs=config.timeout_secs, max_memory_mb=config.max_memory_mb)
