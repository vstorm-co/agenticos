"""`webhook.respond`: answer the delivery that started the run.

A webhook whose graph holds this step does not answer `202` on admission: the
door waits for the run, and the first respond step to complete names the
status, headers and JSON body its sender gets. The run goes on after it - the
step hands its response on, like any other output - and a second respond step
in the same run answers nobody. Outside a run a webhook started, nothing waits,
and the step only records what it would have answered.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._http import HEADER_NAME

# Headers the API's own response owns: its framing, its content type (the body
# is JSON), and anything that would let a workflow set a cookie or loosen a
# browser policy on the deployment's own origin.
RESERVED_RESPONSE_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "content-security-policy",
        "content-type",
        "keep-alive",
        "set-cookie",
        "strict-transport-security",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_RESERVED_PREFIXES = ("access-control-", "cross-origin-")


class WebhookRespondConfig(BaseModel):
    """The status and headers the delivery is answered with."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status_code: int = Field(
        default=200, ge=200, le=599, description="The HTTP status, 200 to 599."
    )
    headers: dict[str, str] = Field(default_factory=dict, max_length=20)

    @field_validator("headers")
    @classmethod
    def _headers_are_ours_to_send(cls, headers: dict[str, str]) -> dict[str, str]:
        for name, value in headers.items():
            if re.fullmatch(HEADER_NAME, name) is None:
                raise ValueError(f"{name!r} is not a header name")
            lowered = name.lower()
            if lowered in RESERVED_RESPONSE_HEADERS or lowered.startswith(_RESERVED_PREFIXES):
                raise ValueError(f"{name} cannot be set on a webhook's answer")
            if len(value) > 1024 or "\n" in value or "\r" in value:
                raise ValueError(f"The value of {name} is too long or spans lines")
        return headers


class WebhookRespondInput(BaseModel):
    """The JSON body, bound from an earlier step. Nothing bound answers `null`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    body: Any = None


class WebhookResponse(BaseModel):
    """What the delivery is answered with."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status_code: int
    headers: dict[str, str]
    body: Any


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Record the answer on the run, and hand it on."""
    settings = config if isinstance(config, WebhookRespondConfig) else WebhookRespondConfig()
    body = node_input.body if isinstance(node_input, WebhookRespondInput) else None
    response = WebhookResponse(
        status_code=settings.status_code, headers=settings.headers, body=body
    )
    context.report_webhook_response(response.model_dump(mode="json"))
    return Completed[WebhookResponse](output=response)
