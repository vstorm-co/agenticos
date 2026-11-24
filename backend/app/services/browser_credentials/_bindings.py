"""Publishing cannot turn a typed browser reference into borrowed vault authority."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.browser_fill import BrowserFillRefused
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext

from . import _access

BINDING_REFUSAL = (
    "Saved browser credentials require this named agent, the provisioned browser, and "
    "credentials you own or are explicitly granted. Reselect the browser credentials."
)


async def binding_problem(
    db: AsyncSession,
    ctx: AuthContext,
    credential_ids: list[UUID],
    *,
    agent_id: UUID | None,
    provisioned: bool,
) -> str | None:
    if not credential_ids:
        return None
    if agent_id is None or not provisioned:
        return BINDING_REFUSAL
    try:
        current = await _access.person(db, ctx)
        _access.enabled(current.organization_id, current.subject_id)
        for secret_id in credential_ids:
            await _access.credential(db, current, secret_id=secret_id, agent_id=agent_id)
    except BrowserFillRefused, BadRequestError:
        return BINDING_REFUSAL
    return None
