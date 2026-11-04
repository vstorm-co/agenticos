"""`html.parse` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.html_parse._handler import (
    HtmlLink,
    HtmlMatch,
    HtmlParseConfig,
    HtmlParseInput,
    HtmlParseOutput,
    handle,
)

__all__ = ["HtmlLink", "HtmlMatch", "HtmlParseConfig", "HtmlParseInput", "HtmlParseOutput"]

register(
    NodeDefinition(
        id="html.parse",
        version=1,
        name="Parse HTML",
        category="data",
        description=(
            "Read HTML into its text, its links and what a CSS selector picks - "
            "nothing is fetched or run."
        ),
        kind="action",
        config_schema=HtmlParseConfig,
        input_schema=HtmlParseInput,
        output_schema=HtmlParseOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=HtmlParseOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
