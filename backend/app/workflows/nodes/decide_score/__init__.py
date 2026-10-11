"""`decide.score` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes._decide import DecisionInput, check_key
from app.workflows.nodes.decide_score._handler import ScoreConfig, ScoreOutput, handle, routes

__all__ = ["ScoreConfig", "ScoreOutput"]

register(
    NodeDefinition(
        id="decide.score",
        version=1,
        name="Score",
        category="decide",
        description="Ask Jev where a text sits on your rubric - urgency, fit, risk.",
        kind="control",
        config_schema=ScoreConfig,
        input_schema=DecisionInput,
        output_schema=ScoreOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Scored", kind="output", schema=ScoreOutput),
            Port(id="unsure", label="Unsure", kind="output", schema=ScoreOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
        routes=routes,
        resource_check=check_key,
    )
)
