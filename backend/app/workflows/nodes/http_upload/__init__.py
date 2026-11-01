"""`http.upload` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes._http import HttpResponseOutput
from app.workflows.nodes.http_upload._handler import (
    HttpUploadConfig,
    HttpUploadInput,
    check_resources,
    handle,
    retry_guarantee_for,
)

__all__ = ["HttpUploadConfig", "HttpUploadInput"]

register(
    NodeDefinition(
        id="http.upload",
        version=1,
        name="Upload a file",
        category="http",
        description="Send one of the run's files to an HTTP endpoint, streamed from storage.",
        kind="action",
        config_schema=HttpUploadConfig,
        input_schema=HttpUploadInput,
        output_schema=HttpResponseOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=HttpResponseOutput),
        ),
        effect_kind="write",
        retry_guarantee="at_least_once",
        handler=handle,
        resource_check=check_resources,
        retry_guarantee_for=retry_guarantee_for,
    )
)
