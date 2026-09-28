"""`http.request` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.http_request._handler import (
    HttpAuth,
    HttpRequestConfig,
    HttpRequestInput,
    HttpResponseOutput,
    check_resources,
    handle,
    retry_guarantee_for,
)

__all__ = ["HttpAuth", "HttpRequestConfig", "HttpRequestInput", "HttpResponseOutput"]

register(
    NodeDefinition(
        id="http.request",
        version=1,
        name="HTTP request",
        category="http",
        description="Call an HTTP API, with SSRF protection and a vault credential.",
        kind="action",
        config_schema=HttpRequestConfig,
        input_schema=HttpRequestInput,
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
