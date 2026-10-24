"""Approved local model and MCP services reached through one person's paired device.

The desktop owns the address and consent. Requests carry an opaque service ID;
neither the model nor the API may select a URL on the person's network.
"""

import base64
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.toolsets import AbstractToolset

from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.core.exceptions import BadRequestError
from app.core.secret_kinds import NoSecret
from app.services.device_hub import _hub

MAX_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 125.0


class LocalService(BaseModel):
    """A service's public identity, as approved and described by the desktop."""

    model_config = ConfigDict(extra="ignore")
    id: str = Field(pattern=r"^[a-zA-Z0-9_]{1,48}$")
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["model", "mcp"]
    model: str | None = Field(default=None, min_length=1, max_length=200)


class _Reply(BaseModel):
    status: int = Field(ge=100, le=599)
    headers: dict[str, str]
    body: str = Field(max_length=MAX_BYTES * 2)


async def describe(
    session_id: UUID, service_id: str, kind: Literal["model", "mcp"]
) -> LocalService:
    """Resolve a service from native grants, refusing a removed or wrong-kind grant."""
    raw = await _hub.call(session_id, "service.describe", {"service": service_id}, timeout=30)
    try:
        service = LocalService.model_validate(raw)
    except ValidationError as exc:
        raise BadRequestError(message="The computer described an invalid local service") from exc
    if (
        service.id != service_id
        or service.kind != kind
        or (kind == "model" and service.model is None)
    ):
        raise BadRequestError(message="This local service is not the requested kind")
    return service


async def _request(
    session_id: UUID, service_id: str, method: str, path: str, headers: dict[str, str], body: bytes
) -> tuple[_Reply, bytes]:
    if len(body) > MAX_BYTES:
        raise BadRequestError(message="The request exceeds the local service's 8 MiB limit")
    raw = await _hub.call(
        session_id,
        "service.request",
        {
            "service": service_id,
            "method": method,
            "path": path,
            "headers": headers,
            "body": base64.b64encode(body).decode("ascii"),
        },
        timeout=TIMEOUT_SECONDS,
    )
    reply = _Reply.model_validate(raw)
    decoded = base64.b64decode(reply.body, validate=True)
    if len(decoded) > MAX_BYTES:
        raise BadRequestError(message="The local service's response exceeds 8 MiB")
    return reply, decoded


class _ModelTransport(httpx2.AsyncBaseTransport):
    def __init__(self, session_id: UUID, service_id: str) -> None:
        self.session_id, self.service_id = session_id, service_id

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.host != "device.invalid" or request.url.path != "/chat/completions":
            raise httpx2.RequestError("Request outside the local model grant", request=request)
        reply, body = await _request(
            self.session_id,
            self.service_id,
            request.method,
            request.url.path,
            dict(request.headers),
            await request.aread(),
        )
        return httpx2.Response(reply.status, headers=reply.headers, content=body, request=request)


class _McpTransport(httpx2.AsyncBaseTransport):
    def __init__(self, session_id: UUID, service_id: str) -> None:
        self.session_id, self.service_id = session_id, service_id

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.host != "device.invalid" or request.url.path != "/mcp":
            raise httpx2.RequestError("Request outside the local MCP grant", request=request)
        reply, body = await _request(
            self.session_id,
            self.service_id,
            request.method,
            "",
            dict(request.headers),
            await request.aread(),
        )
        return httpx2.Response(reply.status, headers=reply.headers, content=body, request=request)


@dataclass(frozen=True, kw_only=True)
class DeviceModelSpec(ModelRequestSpec):
    """A per-run model choice. No cloud fallback, credential or direct network client."""

    session_id: UUID
    service_id: str

    def build(self) -> Model:
        client = httpx2.AsyncClient(
            transport=_ModelTransport(self.session_id, self.service_id), timeout=TIMEOUT_SECONDS
        )
        return OpenAIChatModel(
            self.model,
            provider=OpenAIProvider(
                base_url="http://device.invalid", api_key="local", http_client=client
            ),
        )


def model_spec(base: ModelRequestSpec, session_id: UUID, service: LocalService) -> DeviceModelSpec:
    """Keep the agent's profile attribution; inference uses the approved local model."""
    if service.kind != "model" or service.model is None:
        raise BadRequestError(message="Choose a local model service")
    return DeviceModelSpec(
        profile_id=base.profile_id,
        label=f"{service.name[:100]} (this computer)",
        provider="ollama",
        model=service.model,
        params={},
        credential=ResolvedCredential(provider="ollama", secret=NoSecret()),
        fallbacks=[],
        context_length=None,
        session_id=session_id,
        service_id=service.id,
    )


def mcp_toolset(session_id: UUID, service: LocalService) -> AbstractToolset[object]:
    """An HTTP MCP session on the native grant, with a stable prefix per service."""
    client = httpx2.AsyncClient(
        transport=_McpTransport(session_id, service.id), timeout=TIMEOUT_SECONDS
    )
    return MCPToolset(
        "http://device.invalid/mcp",
        http_client=client,
        id=f"local:{service.id}",
        init_timeout=TIMEOUT_SECONDS,
        tool_error_behavior="failed",
    ).prefixed(f"local_{service.id}")
