"""Compaction capability - keep a long run inside the model's context window."""

from app.agents.capabilities._registry import CapabilityBuildContext, register
from app.agents.capabilities.compaction._capability import (
    MODEL_CONTEXT_WINDOW_RESOURCE,
    CompactionConfig,
    ContextGauge,
    MeteredCompaction,
    NotifyingSummarizingCompaction,
    ReportContextSize,
    StrategyName,
    build_gauge,
    build_strategy,
)

__all__ = [
    "MODEL_CONTEXT_WINDOW_RESOURCE",
    "CompactionConfig",
    "ContextGauge",
    "MeteredCompaction",
    "NotifyingSummarizingCompaction",
    "ReportContextSize",
    "StrategyName",
    "build_gauge",
    "build_strategy",
]


@register(
    id="compaction",
    name="Context management",
    category="utility",
    description=(
        "Trim a long run's history so it keeps working instead of hitting the model's limit."
    ),
    # No tools by design: this rewrites the history a request carries, so there
    # is nothing here for a person to approve. See `compaction/_capability.py`.
    tools=(),
    config_schema=CompactionConfig,
)
def _build(ctx: CapabilityBuildContext) -> MeteredCompaction[object]:
    """Build the configured strategy, wrapped so its spend is billed.

    Always returns something. Binding the capability *is* the decision to
    compact, the way binding `thinking` is the decision to think, so there is no
    configuration that means "on but inert" - and a builder that answered `None`
    would drop out of the registry's drift test, which is what
    `test_no_capability_escapes_the_drift_check` refuses.
    """
    config = ctx.config if isinstance(ctx.config, CompactionConfig) else CompactionConfig()
    recorded = ctx.resources.get(MODEL_CONTEXT_WINDOW_RESOURCE)
    return MeteredCompaction(
        wrapped=build_strategy(
            config, recorded_window=recorded if isinstance(recorded, int) else None
        )
    )
