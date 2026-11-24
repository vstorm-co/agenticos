"""Guardrails capability - a check that can redact or stop a run at its edges."""

from collections.abc import Iterable

from pydantic_ai.capabilities import CombinedCapability
from pydantic_ai_harness.ask_user import TOOL_NAME as ASK_USER_TOOL

from app.agents.capabilities._registry import (
    CapabilityBinding,
    CapabilityBuildContext,
    get,
    register,
)
from app.agents.capabilities.guardrails._capability import (
    GuardrailBlocked,
    GuardrailsConfig,
    ScreenedStream,
    TranscriptScreens,
    build_guardrails,
    input_screen,
    output_screen,
    tool_args_screen,
    transcript_screens,
)

__all__ = [
    "ANSWER_TOOLS_RESOURCE",
    "GuardrailBlocked",
    "GuardrailsConfig",
    "ScreenedStream",
    "TranscriptScreens",
    "answer_tools",
    "build_guardrails",
    "input_screen",
    "output_screen",
    "tool_args_screen",
    "transcript_screens",
]

ANSWER_TOOLS_RESOURCE = "answer_tools"
"""The resource naming the tools whose arguments are what the person is shown."""

_ANSWER_TOOLS = {
    "drafts": frozenset({"write_draft"}),
    "visuals": frozenset({"draw", "revise_visual"}),
    "charts": frozenset({"create_chart"}),
    "artifacts": frozenset({"publish_artifact"}),
    "ask_user": frozenset({ASK_USER_TOOL}),
}


def answer_tools(bindings: Iterable[CapabilityBinding]) -> frozenset[str]:
    """The model-facing names of the tools whose arguments are what the person is shown.

    A draft, a drawing, a chart, a page or a question is its call's arguments, so
    the output edge screens them as it screens the answer. The name is the one the
    model calls, which a binding may have changed.
    """
    return frozenset(
        tool.name
        for binding in bindings
        if binding.enabled and binding.capability_id in _ANSWER_TOOLS
        for tool in get(binding.capability_id).effective_tools(binding.tool_overrides)
        if tool.id in _ANSWER_TOOLS[binding.capability_id]
    )


@register(
    id="guardrails",
    name="Guardrails",
    category="utility",
    description=(
        "Redact secrets or personal data, or block a run, when a prompt, an answer or a tool "
        "result matches a rule."
    ),
    # No tools by design: this inspects and rewrites the text flowing through a run,
    # so there is nothing here for a person to approve. See `guardrails/_capability.py`.
    tools=(),
    config_schema=GuardrailsConfig,
    protective=True,
)
def _build(ctx: CapabilityBuildContext) -> CombinedCapability[object] | None:
    """Build the configured guardrail edges, or nothing when none are configured.

    Returns `None` for an all-default config: enabling the capability without
    turning on any edge attaches no guardrail, which is the "pays nothing when
    absent" contract. A configured edge that only redacts costs a few regex passes
    per request and never calls a model, so an agent's budget is untouched.
    """
    config = ctx.config if isinstance(ctx.config, GuardrailsConfig) else GuardrailsConfig()
    return build_guardrails(
        config, answer_tools=ctx.resources.get(ANSWER_TOOLS_RESOURCE) or frozenset()
    )
