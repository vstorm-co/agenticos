"""Compaction capability - keep a long run inside the model's context window."""

from app.agents.capabilities._registry import CapabilityBuildContext, register
from app.agents.capabilities.compaction._capability import (
    CONTEXT_GAUGE_RESOURCE,
    DEFAULT_SUMMARY_PROMPT,
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
    "CONTEXT_GAUGE_RESOURCE",
    "DEFAULT_SUMMARY_PROMPT",
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
    gauge = ctx.resources.get(CONTEXT_GAUGE_RESOURCE)
    reading = gauge if isinstance(gauge, ContextGauge) else None
    return MeteredCompaction(
        wrapped=build_strategy(
            config,
            recorded_window=recorded if isinstance(recorded, int) else None,
            # So a summary that ran can be kept: the surface reads this off the
            # built agent once the run is over and persists the history rather
            # than paying for the same summary again next turn.
            gauge=reading,
        ),
        # The run's own reading, so the trigger can allow for what every request
        # carries before a single message. Absent in a preview or a test that
        # builds capabilities without a run; the trigger then measures the
        # messages alone, which is what it did before.
        gauge=reading,
    )
