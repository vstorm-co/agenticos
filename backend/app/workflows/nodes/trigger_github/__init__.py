"""`trigger.github` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition, Port
from app.workflows.nodes._triggers import GithubTriggerOutput
from app.workflows.nodes.trigger_github._handler import GithubTriggerConfig, handle
from app.workflows.triggers import GITHUB

register(
    NodeDefinition(
        id=GITHUB,
        version=1,
        name="GitHub",
        category=TRIGGER_CATEGORY,
        description="Something happens in a GitHub repository - an issue, a pull request, a push.",
        kind="action",
        config_schema=GithubTriggerConfig,
        input_schema=None,
        output_schema=GithubTriggerOutput,
        ports=(Port(id="out", label="Out", kind="output", schema=GithubTriggerOutput),),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
