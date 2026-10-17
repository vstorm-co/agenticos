"""Coding agent - Claude Code or Codex doing software work in the agent's sandbox (#2092).

A general agent with a shell can edit code; a coding harness is better at it, and
both Claude Code and Codex run headless. This capability gives an agent two tools
that hand a task to one of them in the agent's own sandbox: one that reads and
plans, and one that changes files and runs commands, which is the one to put
behind the approval gate.

An agent with this capability is a coding agent; another agent reaches it the way
it reaches any specialist, through delegation, so "hand this to Claude Code" and
"hand this to the finance agent" are the same act.
"""

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, JsonValue, model_validator

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.coding_agent._capability import CodingAgent
from app.core.secret_kinds import ApiKeySecret, OpenAICodexSecret, SecretKind, SecretRequirement
from app.services.openai_codex import VaultCodexCredentials

__all__ = ["CODING_AGENT_ID", "CodingAgent", "CodingAgentConfig"]

CODING_AGENT_ID = "coding_agent"

CodingModel = Literal[
    "anthropic:claude-opus-5-5",
    "anthropic:claude-sonnet-5-5",
    "anthropic:claude-haiku-5-5",
    "openai:gpt-5.6-sol",
    "openai:gpt-5.6-terra",
    "openai:gpt-5.6-luna",
    "openai:gpt-5.3-codex",
]
"""The models offered, each prefixed with its vendor so the Builder draws its mark.

The Claude ids are the ones Claude Code takes, directly and through OpenRouter,
both checked; the Codex ones are the curated `openai_codex` list.
"""

_MODEL_NAMES: dict[str, JsonValue] = {
    "anthropic:claude-opus-5-5": "Claude Opus 5.5",
    "anthropic:claude-sonnet-5-5": "Claude Sonnet 5.5",
    "anthropic:claude-haiku-5-5": "Claude Haiku 5.5",
    "openai:gpt-5.6-sol": "GPT-5.6 Sol",
    "openai:gpt-5.6-terra": "GPT-5.6 Terra",
    "openai:gpt-5.6-luna": "GPT-5.6 Luna",
    "openai:gpt-5.3-codex": "GPT-5.3 Codex",
}

_VENDOR = {"claude_code": "anthropic", "codex": "openai"}


class CodingAgentConfig(BaseModel):
    """Which harness works, on which model, and for how long a task may run."""

    harness: Literal["claude_code", "codex"] = Field(
        title="Coding agent",
        default="claude_code",
        description=(
            "Which coding agent does the work: Claude Code, on an Anthropic key or a "
            "Claude subscription token, or Codex, on an OpenAI key or a ChatGPT sign-in."
        ),
        json_schema_extra={"x-enum-labels": {"claude_code": "Claude Code", "codex": "Codex"}},
    )
    model: CodingModel | None = Field(
        title="Model",
        default=None,
        description=(
            "The model the coding agent runs: a Claude model for Claude Code, an "
            "OpenAI one for Codex. Not set takes the coding agent's own default."
        ),
        json_schema_extra={"x-enum-labels": _MODEL_NAMES},
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

    @model_validator(mode="after")
    def _model_fits_the_harness(self) -> "CodingAgentConfig":
        if self.model is not None and not self.model.startswith(f"{_VENDOR[self.harness]}:"):
            raise ValueError(
                "Claude Code runs Claude models and Codex runs OpenAI ones; pick a model "
                "of the chosen coding agent's vendor."
            )
        return self

    @property
    def model_id(self) -> str | None:
        """The model as the harness names it, without the vendor the Builder shows."""
        return self.model.split(":", 1)[1] if self.model is not None else None


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
        also_accepts=(SecretKind.OPENAI_CODEX,),
        description=(
            "Claude Code: an Anthropic API key or a Claude subscription token. "
            "Codex: an OpenAI API key or a ChatGPT sign-in."
        ),
    ),
)
def _build(ctx: CapabilityBuildContext) -> CodingAgent:
    config = ctx.config if isinstance(ctx.config, CodingAgentConfig) else CodingAgentConfig()
    api_key = (
        ctx.secret.api_key.get_secret_value() if isinstance(ctx.secret, ApiKeySecret) else None
    )
    secret_id = ctx.binding.secret_id
    # A sign-in is not handed over as the tokens it held at build time: its
    # refresh token is single-use, so each task reads the vault's current pair
    # and writes back whatever Codex rotated it to.
    sign_in = (
        (lambda org: VaultCodexCredentials(organization_id=org, secret_id=secret_id))
        if isinstance(ctx.secret, OpenAICodexSecret) and secret_id is not None
        else None
    )
    return CodingAgent(
        harness=config.harness,
        model=config.model_id,
        base_url=str(config.base_url).rstrip("/") if config.base_url is not None else None,
        timeout_seconds=config.timeout_minutes * 60,
        api_key=api_key,
        sign_in=sign_in,
    )
