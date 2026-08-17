"""Guardrails capability - a check that can redact or stop a run at its edges."""

from pydantic_ai.capabilities import CombinedCapability

from app.agents.capabilities._registry import CapabilityBuildContext, register
from app.agents.capabilities.guardrails._capability import (
    GuardrailBlocked,
    GuardrailsConfig,
    build_guardrails,
)

__all__ = ["GuardrailBlocked", "GuardrailsConfig", "build_guardrails"]


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
)
def _build(ctx: CapabilityBuildContext) -> CombinedCapability[object] | None:
    """Build the configured guardrail edges, or nothing when none are configured.

    Returns `None` for an all-default config: enabling the capability without
    turning on any edge attaches no guardrail, which is the "pays nothing when
    absent" contract. A configured edge that only redacts costs a few regex passes
    per request and never calls a model, so an agent's budget is untouched.
    """
    config = ctx.config if isinstance(ctx.config, GuardrailsConfig) else GuardrailsConfig()
    return build_guardrails(config)
