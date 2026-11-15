"""Harness - a local CLI session as an agent's working backend.

A general agent with a shell can edit code; a coding harness is better at it,
and Claude Code, Codex, OpenCode, Gemini CLI and Pi all run headless. The coding
agent hands one task to one of them and reports back. This capability goes one
step further: the agent is *backed by* a harness session - one of those CLIs in
the agent's sandbox - that it drives across turns, starting one session per line
of work and prompting it as the work proceeds, while a person watches.

An agent with this capability is a harness-backed agent; another agent reaches
it the way it reaches any specialist, through delegation, so "ask the harness
agent" and "hand this to the finance agent" are the same act.
"""

from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.coding_agent import (
    _MODEL_NAMES,
    CodingModel,
)
from app.agents.capabilities.coding_agent._harness import LABELS, Access, Harness
from app.agents.capabilities.harness._capability import HarnessAgent
from app.core.secret_kinds import (
    ApiKeySecret,
    PurposesByValue,
    SecretKind,
    SecretRequirement,
)
from app.services.openai_codex import PURPOSE as OPENAI_CODEX_PURPOSE

__all__ = [
    "HARNESS_ID",
    "HarnessAgent",
    "HarnessConfig",
]

HARNESS_ID = "harness"

# Which model vendors each harness runs, by the vendor prefix on the model id.
# Claude Code and Codex run one vendor each; Gemini CLI runs Google's; OpenCode
# and Pi run any provider's model, so the key they run on follows the model.
_HARNESS_VENDORS: dict[Harness, tuple[str, ...]] = {
    "claude_code": ("anthropic",),
    "codex": ("openai",),
    "opencode": ("anthropic", "openai", "google"),
    "gemini": ("google",),
    "pi": ("anthropic", "openai", "google"),
}

_VENDOR_NAMES: dict[str, str] = {
    "anthropic": "Claude",
    "openai": "OpenAI",
    "google": "Gemini",
}
"""The vendor prefixes as the Builder's refusals name them."""


class HarnessConfig(BaseModel):
    """Which harness backs the agent, and what it may do in the sandbox."""

    harness: Harness = Field(
        default="claude_code",
        title="Harness",
        description=(
            "The CLI session that does the agent's work: Claude Code, Codex, "
            "OpenCode, Gemini CLI or Pi."
        ),
    )
    access: Access = Field(
        default="read_only",
        title="Access",
        description=(
            "What the harness may do in the agent's sandbox: only read code, or "
            "change code and run commands."
        ),
        json_schema_extra={
            # Codex has no read-only mode that starts inside a container.
            "x-enum-when": {
                "field": "harness",
                "choices": {
                    "claude_code": ["edit", "read_only"],
                    "codex": ["edit"],
                    "opencode": ["edit", "read_only"],
                    "gemini": ["edit", "read_only"],
                    "pi": ["edit", "read_only"],
                },
            },
        },
    )
    model: CodingModel | None = Field(
        default=None,
        title="Model",
        description=(
            "The model the harness runs on: a Claude model for Claude Code, an "
            "OpenAI one for Codex, a Gemini one for Gemini CLI, or any of those "
            "vendors' models for OpenCode or Pi. Not set takes the harness's own "
            "default."
        ),
        json_schema_extra={
            "x-enum-labels": _MODEL_NAMES,
            # The Builder offers each harness only its own vendors' models.
            "x-enum-when": {
                "field": "harness",
                "choices": {
                    harness: [model for model in _MODEL_NAMES if model.split(":", 1)[0] in vendors]
                    for harness, vendors in _HARNESS_VENDORS.items()
                },
            },
        },
    )
    base_url: HttpUrl | None = Field(
        default=None,
        title="Anthropic-compatible endpoint",
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
        default=30,
        title="Prompt timeout (minutes)",
        ge=1,
        le=60,
        description="How long one prompt may run before it is stopped. The session stays open.",
    )

    @model_validator(mode="after")
    def _endpoint_is_claude_codes(self) -> HarnessConfig:
        # Dropped rather than refused: the field is hidden once Codex is chosen,
        # so a value left from Claude Code is one nobody can see to clear.
        if self.harness != "claude_code":
            self.base_url = None
        return self

    @model_validator(mode="after")
    def _codex_may_edit(self) -> HarnessConfig:
        if self.harness == "codex" and self.access == "read_only":
            raise ValueError(
                "Codex can only run with access to change files: its read-only mode is "
                "a sandbox of its own, which cannot start inside the agent's sandbox. "
                "Use Claude Code for read-only work."
            )
        return self

    @model_validator(mode="after")
    def _model_fits_the_harness(self) -> HarnessConfig:
        if self.model is not None:
            vendor = self.model.split(":", 1)[0]
            if vendor not in _HARNESS_VENDORS[self.harness]:
                if self.harness in ("claude_code", "codex"):
                    raise ValueError(
                        "Claude Code runs Claude models and Codex runs OpenAI ones; "
                        "pick a model of the chosen harness's vendor."
                    )
                names = ", ".join(_VENDOR_NAMES[name] for name in _HARNESS_VENDORS[self.harness])
                raise ValueError(f"{LABELS[self.harness]} runs {names} models; pick one of those.")
        return self

    @model_validator(mode="after")
    def _model_required_for_multi_provider(self) -> HarnessConfig:
        # OpenCode and Pi run any provider's model, so with no model picked
        # there is no vendor to take the key from: the CLI's default model
        # would decide, and a key for another provider would fail at run time.
        # Gemini CLI's default is a Gemini model either way, so it keeps the
        # harness's own default.
        if self.harness in ("opencode", "pi") and self.model is None:
            raise ValueError(
                f"{LABELS[self.harness]} runs any provider's model, so pick one: "
                "the key it runs on follows the model."
            )
        return self

    @property
    def model_id(self) -> str | None:
        """The model as the harness names it, without the vendor the Builder shows."""
        return self.model.split(":", 1)[1] if self.model is not None else None

    @property
    def model_vendor(self) -> str | None:
        """The vendor of the model picked, for the CLIs that take `provider/model`."""
        return self.model.split(":", 1)[0] if self.model is not None else None


@register(
    id=HARNESS_ID,
    name="Harness",
    category="analysis",
    description=(
        "Drive a Claude Code, Codex, OpenCode, Gemini CLI or Pi session in the "
        "agent's sandbox across turns, as the agent's working backend, while you watch."
    ),
    tools=(
        CapabilityToolInfo(
            id="harness_start",
            description="Open a named harness session with a first prompt, and keep it open.",
        ),
        CapabilityToolInfo(
            id="harness_prompt",
            description="Send a follow-up prompt to a named harness session.",
        ),
        CapabilityToolInfo(
            id="harness_stop",
            description="Close a named harness session.",
        ),
        CapabilityToolInfo(
            id="harness_sessions",
            description="List the harness sessions this conversation has open.",
            read_only=True,
        ),
    ),
    config_schema=HarnessConfig,
    # The harness runs commands in the sandbox, which is what this scope gates
    # for the sandbox's own shell.
    scopes=("sandbox:execute",),
    # It edits files and runs anything at `edit`, which is the default.
    side_effecting=True,
    # The four tools are one surface: the approval is the capability's.
    tool_settings=False,
    # A harness session runs in the sandbox, which a realtime session cannot open.
    voice="hand_off",
    secret=SecretRequirement(
        kind=SecretKind.API_KEY,
        # A ChatGPT sign-in is not accepted here yet: the coding agent's
        # sign-in flow - an isolated home, a visibility check, token rotation
        # read back out of the sandbox - is not wired into this capability, and
        # offering a sign-in the harness cannot use would fail at first run
        # rather than at publish. An OpenAI API key is what Codex runs on here.
        purposes_by=PurposesByValue(
            field="harness",
            purposes={
                "claude_code": ("anthropic",),
                "codex": ("openai", OPENAI_CODEX_PURPOSE),
                # Gemini CLI takes a Gemini API key: a personal Google sign-in
                # no longer serves it.
                "gemini": ("google",),
                # OpenCode and Pi run any provider's model, so the key follows
                # the model the binding picks; a key for another provider fails
                # at run time with the CLI's own auth error.
                "opencode": ("anthropic", "openai", "google"),
                "pi": ("anthropic", "openai", "google"),
            },
            open_when_set={"claude_code": "base_url"},
        ),
        description=(
            "Claude Code: an Anthropic API key or a Claude subscription token. "
            "Codex: an OpenAI API key. Gemini CLI: a Gemini API key. OpenCode "
            "and Pi: a key for the chosen model's provider - Anthropic, OpenAI "
            "or Google."
        ),
    ),
)
def _build(ctx: CapabilityBuildContext) -> HarnessAgent:
    config = ctx.config if isinstance(ctx.config, HarnessConfig) else HarnessConfig()
    return HarnessAgent(
        harness=config.harness,
        access=config.access,
        model=config.model_id,
        model_vendor=config.model_vendor,
        base_url=str(config.base_url).rstrip("/") if config.base_url is not None else None,
        timeout_seconds=config.timeout_minutes * 60,
        api_key=ctx.secret.api_key if isinstance(ctx.secret, ApiKeySecret) else None,
    )
