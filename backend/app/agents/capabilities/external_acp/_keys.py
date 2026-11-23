"""Authorize a selected vault key before crossing to a member's native process."""

import json
from uuid import UUID

from pydantic_ai import RunContext

from app.agents.capabilities.coding_agent._acp import AcpError
from app.agents.capabilities.external_acp._catalog import AcpCatalog
from app.agents.deps import AgentDeps
from app.agents.pi_keys import NativeKeyProvider, NativeRuntimeKey
from app.core.exceptions import AuthorizationError, BadRequestError
from app.db.session import get_db_context
from app.services.device_hub import DeviceWorkspace
from app.services.organization_secret import OrganizationSecretService


async def selected_key(
    ctx: RunContext[AgentDeps], provider: NativeKeyProvider | None, secret_id: UUID | None
) -> NativeRuntimeKey | None:
    if provider is None:
        return None
    audience = ctx.deps.audience
    workspace = ctx.workspace.backend if ctx.workspace.attached else None
    person = ctx.deps.run_person
    if (
        ctx.deps.impersonated
        or person is None
        or ctx.deps.organization_id is None
        or audience is None
        or audience.user_id != person
        or audience.shared_transcript
        or audience.room_key is not None
        or not isinstance(workspace, DeviceWorkspace)
        or workspace.owner_id != person
        or ctx.deps.user_id != str(person)
    ):
        raise AuthorizationError(
            message="A vault key can reach only its initiating member's own approved computer"
        )
    if secret_id is None:
        raise BadRequestError(message="Choose a vault API key for this runtime")
    async with get_db_context() as db:
        return await OrganizationSecretService(db).native_runtime_key(
            organization_id=ctx.deps.organization_id,
            user_id=person,
            secret_id=secret_id,
            provider=provider,
        )


def catalog_json(catalog: AcpCatalog, key: NativeRuntimeKey | None) -> str:
    serialized = catalog.model_dump_json()
    if key is not None and json.dumps(key.api_key.get_secret_value())[1:-1] in serialized:
        raise AcpError(
            "The runtime exposed credential material in its catalog. No model list was returned."
        )
    return serialized
