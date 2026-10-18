"""Strangler: forward Shop AI BFF paths to services/multi-agent until D3 parity on Agentra."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from app.core.config import settings
from app.core.exceptions import BadRequestError, ExternalServiceError

logger = logging.getLogger(__name__)

SHOP_AI_LLM_PROXY_TIMEOUT_SEC = 180.0
SHOP_AI_DEFAULT_PROXY_TIMEOUT_SEC = 120.0

_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)

_LLM_SUBPATH_MARKERS = (
    "llm-generate",
    "merchant-assistant",
    "widget/chat",
)


def _multi_agent_base_and_key() -> tuple[str, str]:
    base = (settings.MULTI_AGENT_BACKEND_URL or "").rstrip("/")
    key = (settings.MULTI_AGENT_INTERNAL_API_KEY or "").strip()
    if not base or not key:
        raise BadRequestError(
            message="Shop AI strangler is not configured",
            details={
                "hint": "Set MULTI_AGENT_BACKEND_URL and MULTI_AGENT_INTERNAL_API_KEY on Agentra",
            },
        )
    return base, key


def _timeout_for_subpath(subpath: str) -> float:
    normalized = subpath.lower()
    if normalized.rstrip("/").endswith("/stream"):
        return SHOP_AI_LLM_PROXY_TIMEOUT_SEC
    if any(marker in normalized for marker in _LLM_SUBPATH_MARKERS):
        return SHOP_AI_LLM_PROXY_TIMEOUT_SEC
    return SHOP_AI_DEFAULT_PROXY_TIMEOUT_SEC


def _upstream_url(subpath: str, query: str) -> str:
    base, _ = _multi_agent_base_and_key()
    path = subpath.lstrip("/")
    if path:
        url = f"{base}/api/v1/internal/shop-ai/{path}"
    else:
        url = f"{base}/api/v1/internal/shop-ai"
    if query:
        url = f"{url}?{query}"
    return url


def _filter_response_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP
    }


def shop_ai_proxy_headers(
    *,
    api_key: str,
    tenant_id: UUID,
    organization_id: UUID | None = None,
    content_type: str | None = "application/json",
) -> dict[str, str]:
    headers: dict[str, str] = {
        settings.API_KEY_HEADER: api_key,
        "X-Tenant-Id": str(tenant_id),
    }
    if organization_id is not None:
        headers["X-Organization-Id"] = str(organization_id)
    if content_type:
        headers["Content-Type"] = content_type
    headers["Accept"] = "application/json"
    return headers


async def post_shop_ai_json(
    *,
    subpath: str,
    tenant_id: UUID,
    payload: dict,
    organization_id: UUID | None = None,
) -> dict:
    """Server-side POST to multi-agent shop-ai (B78 channel agent strangler)."""
    _, api_key = _multi_agent_base_and_key()
    url = _upstream_url(subpath, "")
    headers = shop_ai_proxy_headers(
        api_key=api_key,
        tenant_id=tenant_id,
        organization_id=organization_id,
    )
    timeout = httpx.Timeout(_timeout_for_subpath(subpath))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            upstream = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise ExternalServiceError(
            message="Shop AI upstream unavailable",
            details={"upstream": "multi-agent", "subpath": subpath},
        ) from exc
    if upstream.status_code >= 400:
        raise ExternalServiceError(
            message="Shop AI upstream rejected request",
            details={
                "upstream": "multi-agent",
                "subpath": subpath,
                "status_code": upstream.status_code,
            },
        )
    return upstream.json()


def _forward_headers(request: Request, *, api_key: str, tenant_id: UUID) -> dict[str, str]:
    headers: dict[str, str] = {
        settings.API_KEY_HEADER: api_key,
        "X-Tenant-Id": str(tenant_id),
    }
    org_id = request.headers.get("X-Organization-Id")
    if org_id:
        headers["X-Organization-Id"] = org_id
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    accept = request.headers.get("accept")
    if accept:
        headers["Accept"] = accept
    return headers


def _should_stream_response(request: Request, subpath: str) -> bool:
    if subpath.rstrip("/").endswith("/stream"):
        return True
    accept = (request.headers.get("accept") or "").lower()
    return "text/event-stream" in accept


async def proxy_shop_ai_request(
    *,
    request: Request,
    subpath: str,
    tenant_id: UUID,
    body_override: bytes | None = None,
) -> Response | StreamingResponse:
    """Proxy `/internal/shop-ai/{subpath}` to multi-agent with X-Tenant-Id."""
    from app.services.shop_ai_bff_native import maybe_proxy_bff_native_read

    native = await maybe_proxy_bff_native_read(
        request=request, subpath=subpath, tenant_id=tenant_id
    )
    if native is not None:
        return native

    if _should_stream_response(request, subpath):
        return await _proxy_shop_ai_stream(
            request=request,
            subpath=subpath,
            tenant_id=tenant_id,
            body_override=body_override,
        )
    return await _proxy_shop_ai_buffered(
        request=request,
        subpath=subpath,
        tenant_id=tenant_id,
        body_override=body_override,
    )


async def _proxy_shop_ai_buffered(
    *,
    request: Request,
    subpath: str,
    tenant_id: UUID,
    body_override: bytes | None = None,
) -> Response:
    _, api_key = _multi_agent_base_and_key()
    url = _upstream_url(subpath, request.url.query)
    body = body_override if body_override is not None else await request.body()
    headers = _forward_headers(request, api_key=api_key, tenant_id=tenant_id)
    timeout = httpx.Timeout(_timeout_for_subpath(subpath))

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            upstream = await client.request(
                request.method,
                url,
                headers=headers,
                content=body if body else None,
            )
    except httpx.HTTPError as exc:
        logger.warning(
            "multi_agent_shop_ai_proxy_failed",
            extra={"tenant_id": str(tenant_id), "subpath": subpath},
            exc_info=True,
        )
        raise ExternalServiceError(
            message="Shop AI upstream unavailable",
            details={"upstream": "multi-agent", "subpath": subpath},
        ) from exc

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=_filter_response_headers(upstream.headers),
        media_type=upstream.headers.get("content-type"),
    )


async def _proxy_shop_ai_stream(
    *,
    request: Request,
    subpath: str,
    tenant_id: UUID,
    body_override: bytes | None = None,
) -> Response | StreamingResponse:
    _, api_key = _multi_agent_base_and_key()
    url = _upstream_url(subpath, request.url.query)
    body = body_override if body_override is not None else await request.body()
    headers = _forward_headers(request, api_key=api_key, tenant_id=tenant_id)
    timeout = httpx.Timeout(_timeout_for_subpath(subpath))

    client = httpx.AsyncClient(timeout=timeout)
    try:
        req = client.build_request(
            request.method,
            url,
            headers=headers,
            content=body if body else None,
        )
        upstream = await client.send(req, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.warning(
            "multi_agent_shop_ai_stream_proxy_failed",
            extra={"tenant_id": str(tenant_id), "subpath": subpath},
            exc_info=True,
        )
        raise ExternalServiceError(
            message="Shop AI upstream unavailable",
            details={"upstream": "multi-agent", "subpath": subpath},
        ) from exc

    if upstream.status_code >= 400:
        error_body = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        return Response(
            content=error_body,
            status_code=upstream.status_code,
            headers=_filter_response_headers(upstream.headers),
            media_type=upstream.headers.get("content-type"),
        )

    async def generate() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        generate(),
        status_code=upstream.status_code,
        headers=_filter_response_headers(upstream.headers),
        media_type=upstream.headers.get("content-type") or "text/event-stream",
    )


async def proxy_shop_mcp_request(
    *,
    request: Request,
    subpath: str,
    tenant_id: UUID,
) -> Response | StreamingResponse:
    """Backward-compatible alias — subpath is relative to `mcp/`."""
    return await proxy_shop_ai_request(
        request=request,
        subpath=f"mcp/{subpath}".rstrip("/"),
        tenant_id=tenant_id,
    )
