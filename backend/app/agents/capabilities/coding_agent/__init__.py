"""Coding agent - Claude Code or Codex doing software work in the agent's sandbox (#2092).

A general agent with a shell can edit code; a coding harness is better at it, and
both Claude Code and Codex run headless. This capability gives an agent two tools
that hand a task to one of them in the agent's own sandbox: one that reads and
plans, and one that changes files and runs commands, which the approval gate holds
for a person by default.

An agent with this capability is a coding agent; another agent reaches it the way
it reaches any specialist, through delegation, so "hand this to Claude Code" and
"hand this to the finance agent" are the same act.
"""

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.coding_agent._capability import CodingAgent
from app.core.secret_kinds import ApiKeySecret, SecretKind, SecretRequirement

__all__ = ["CODING_AGENT_ID", "CodingAgent", "CodingAgentConfig"]

CODING_AGENT_ID = "coding_agent"


class CodingAgentConfig(BaseModel):
    """Which harness works, on which model, and for how long a task may run."""

    harness: Literal["claude_code", "codex"] = Field(
        title="Coding agent",
        default="claude_code",
        description=(
            "Which coding agent does the work: Claude Code, with an Anthropic API key, "
            "or Codex, with an OpenAI API key."
        ),
    )
    model: str | None = Field(
        title="Model",
        default=None,
        max_length=128,
        description=(
            "The model the coding agent runs, by its own name for it, such as "
            "claude-sonnet-5-5 or gpt-5.5-codex. Empty takes its default."
        ),
    )
    base_url: HttpUrl | None = Field(
        title="Anthropic-compatible endpoint",
        default=None,
        description=(
            "Claude Code only: a gateway that speaks Anthropic's API, such as "
            "https://openrouter.ai/api, with the key in the vault being that "
            "gateway's. Empty calls Anthropic directly."
        ),
        json_schema_extra={"x-advanced": True},
    )
    timeout_minutes: int = Field(
        title="Time limit (minutes)",
        default=15,
        ge=1,
        le=60,
        description="How long one task may run before it is stopped.",
    )

    @model_validator(mode="after")
    def _endpoint_is_claude_codes(self) -> "CodingAgentConfig":
        if self.base_url is not None and self.harness != "claude_code":
            raise ValueError("Only Claude Code can be pointed at another endpoint.")
        return self


@register(
    id=CODING_AGENT_ID,
    name="Coding agent",
    category="analysis",
    description="Hand software work to Claude Code or Codex, running in the agent's sandbox.",
    tools=(
        CapabilityToolInfo(
            id="plan_code_change",
            description=(
                "Ask the coding agent to study the code and plan a change, without "
                "changing anything."
            ),
            side_effecting=False,
        ),
        CapabilityToolInfo(
            id="apply_code_change",
            description=(
                "Have the coding agent make a change in the sandbox: edit files and run commands."
            ),
        ),
    ),
    config_schema=CodingAgentConfig,
    # The harness runs commands in the sandbox, which is what this scope gates
    # for the sandbox's own shell.
    scopes=("sandbox:execute",),
    # Applying a change writes files and runs anything; planning says otherwise
    # for itself above.
    side_effecting=True,
    secret=SecretRequirement(
        kind=SecretKind.API_KEY,
        description="The Anthropic API key for Claude Code, or the OpenAI API key for Codex",
    ),
)
def _build(ctx: CapabilityBuildContext) -> CodingAgent:
    config = ctx.config if isinstance(ctx.config, CodingAgentConfig) else CodingAgentConfig()
    api_key = (
        ctx.secret.api_key.get_secret_value() if isinstance(ctx.secret, ApiKeySecret) else None
    )
    return CodingAgent(
        harness=config.harness,
        model=config.model,
        base_url=str(config.base_url).rstrip("/") if config.base_url is not None else None,
        timeout_seconds=config.timeout_minutes * 60,
        api_key=api_key,
    )
