"""`http.download` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.http_download._handler import (
    HttpDownloadConfig,
    HttpDownloadOutput,
    check_resources,
    handle,
)

__all__ = ["HttpDownloadConfig", "HttpDownloadOutput"]

register(
    NodeDefinition(
        id="http.download",
        version=1,
        name="Download a file",
        category="http",
        description=(
            "Fetch a file over HTTP into the run, streamed and size-limited, its type "
            "read from its own bytes."
        ),
        kind="action",
        config_schema=HttpDownloadConfig,
        input_schema=None,
        output_schema=HttpDownloadOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=HttpDownloadOutput),
        ),
        effect_kind="write",
        retry_guarantee="at_least_once",
        handler=handle,
        resource_check=check_resources,
    )
)
