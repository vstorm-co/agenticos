"""Coding agent - Claude Code or Codex doing software work in the agent's sandbox (#2092).

A general agent with a shell can edit code; a coding harness is better at it, and
both Claude Code and Codex run headless. This capability gives an agent one tool
that hands a task to one of them in the agent's own sandbox and lets it work -
a separate agent, shown working in the chat - with what it may do there decided
here rather than by the model.

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
from app.agents.capabilities.coding_agent._toolset import RUN_DESCRIPTION
from app.agents.capabilities.sandbox import WORKSPACE_SHARED_RESOURCE
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
    access: Literal["edit", "read_only"] = Field(
        title="What it may do",
        default="edit",
        description=(
            "Change files and run commands, such as tests - or only read the code "
            "and answer. Set Human approval to ask before each task either way."
        ),
        json_schema_extra={
            "x-enum-labels": {
                "edit": "Change files and run commands",
                "read_only": "Read the code and answer",
            },
            # Codex has no read-only mode that starts inside a container.
            "x-enum-when": {
                "field": "harness",
                "choices": {"claude_code": ["edit", "read_only"], "codex": ["edit"]},
            },
        },
    )
    model: CodingModel | None = Field(
        title="Model",
        default=None,
        description=(
            "The model the coding agent runs: a Claude model for Claude Code, an "
            "OpenAI one for Codex. Not set takes the coding agent's own default."
        ),
        json_schema_extra={
            "x-enum-labels": _MODEL_NAMES,
            # The Builder offers each harness only its own vendor's models.
            "x-enum-when": {
                "field": "harness",
                "choices": {
                    harness: [model for model in _MODEL_NAMES if model.startswith(f"{vendor}:")]
                    for harness, vendor in _VENDOR.items()
                },
            },
        },
    )
    base_url: HttpUrl | None = Field(
        title="Anthropic-compatible endpoint",
        default=None,
        description=(
            "Claude Code only: a gateway that speaks Anthropic's API, such as "
            "https://openrouter.ai/api, with the key in the vault being that "
            "gateway's. Empty calls Anthropic directly."
        ),
        json_schema_extra={
            "x-advanced": True,
            "x-visible-when": {"field": "harness", "equals": ["claude_code"]},
        },
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
        # Dropped rather than refused: the field is hidden once Codex is chosen,
        # so a value left from Claude Code is one nobody can see to clear.
        if self.harness != "claude_code":
            self.base_url = None
        return self

    @model_validator(mode="after")
    def _codex_may_edit(self) -> "CodingAgentConfig":
        if self.harness == "codex" and self.access == "read_only":
            raise ValueError(
                "Codex can only run with access to change files: its read-only mode is "
                "a sandbox of its own, which cannot start inside the agent's sandbox. "
                "Use Claude Code for read-only work."
            )
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
    description=(
        "Hand software work to Claude Code or Codex, which work on it in the agent's "
        "sandbox while you watch."
    ),
    tools=(CapabilityToolInfo(id="run_coding_agent", description=RUN_DESCRIPTION),),
    config_schema=CodingAgentConfig,
    # The harness runs commands in the sandbox, which is what this scope gates
    # for the sandbox's own shell.
    scopes=("sandbox:execute",),
    # It edits files and runs anything at `edit`, which is the default.
    side_effecting=True,
    # The one tool is the capability: its approval is the capability's.
    tool_settings=False,
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
        access=config.access,
        model=config.model_id,
        base_url=str(config.base_url).rstrip("/") if config.base_url is not None else None,
        timeout_seconds=config.timeout_minutes * 60,
        api_key=api_key,
        sign_in=sign_in,
        shared_sandbox=ctx.resources.get(WORKSPACE_SHARED_RESOURCE) is True,
    )
