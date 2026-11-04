"""The API delegates only the updater's fixed protocol over its local socket."""

from uuid import UUID

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConfigurationError
from app.schemas.updates import (
    AgentUpdateRead,
    UpdateApply,
    UpdateCancel,
    UpdatePrepare,
    UpdateStatusRead,
)


class UpdateService:
    async def _request(
        self,
        method: str,
        path: str,
        data: UpdatePrepare | UpdateApply | UpdateCancel | None = None,
        actor_user_id: UUID | None = None,
    ) -> AgentUpdateRead:
        if settings.UPDATE_AGENT_SOCKET is None:
            raise ConfigurationError(message="The local Compose updater has not been configured")
        transport = httpx.AsyncHTTPTransport(uds=str(settings.UPDATE_AGENT_SOCKET))
        try:
            async with (
                httpx.AsyncClient(
                    transport=transport, timeout=5, trust_env=False, follow_redirects=False
                ) as client,
                client.stream(
                    method,
                    f"http://updater/v1/{path}",
                    json={**data.model_dump(mode="json"), "actor_id": str(actor_user_id)}
                    if data
                    else None,
                ) as response,
            ):
                if response.status_code == 409:
                    raise BadRequestError(
                        message="The updater refused this operation; refresh its status before retrying"
                    )
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 16_384:
                        raise ConfigurationError(message="The updater returned an invalid status")
                return AgentUpdateRead.model_validate_json(bytes(body))
        except (httpx.HTTPError, ValidationError) as exc:
            raise ConfigurationError(
                message="The local Compose updater is unavailable or incompatible"
            ) from exc

    async def status(self) -> UpdateStatusRead:
        if settings.UPDATE_AGENT_SOCKET is None:
            return UpdateStatusRead(
                configured=False,
                reachable=False,
                operation=None,
                pipeline_url=settings.UPDATE_PIPELINE_URL,
            )
        try:
            state = await self._request("GET", "status")
        except ConfigurationError:
            return UpdateStatusRead(
                configured=True,
                reachable=False,
                operation=None,
                pipeline_url=settings.UPDATE_PIPELINE_URL,
            )
        return UpdateStatusRead(
            configured=True,
            reachable=True,
            operation=state.operation,
            pipeline_url=settings.UPDATE_PIPELINE_URL,
        )

    async def prepare(self, data: UpdatePrepare, *, actor_user_id: UUID) -> AgentUpdateRead:
        return await self._request("POST", "prepare", data, actor_user_id)

    async def apply(self, data: UpdateApply, *, actor_user_id: UUID) -> AgentUpdateRead:
        return await self._request("POST", "apply", data, actor_user_id)

    async def cancel(self, data: UpdateCancel, *, actor_user_id: UUID) -> AgentUpdateRead:
        return await self._request("POST", "cancel", data, actor_user_id)
