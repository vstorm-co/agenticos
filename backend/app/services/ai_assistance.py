"""Whether an organization lets models assist its evals and authoring.

One switch, read by every service that starts a model-backed eval or authoring
run - the judge, the case generator, the authoring assistant, knowledge-gap
drafts. The check lives in the service rather than the client, so "off" holds for
a script, a stale tab and a trigger alike.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AiAssistanceDisabledError, NotFoundError
from app.repositories import organization_repo


class AiAssistanceService:
    """Read the organization's AI assistance switch."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def is_enabled(self, *, organization_id: UUID) -> bool:
        """Whether the organization allows model-backed evals and authoring.

        For a caller that degrades rather than refuses - scoring records a judge
        that could not run and carries on with its deterministic checks.

        Raises:
            NotFoundError: When the organization does not exist.
        """
        organization = await organization_repo.get_by_id(self.db, organization_id)
        if organization is None:
            raise NotFoundError(
                message="Organization not found", details={"organization_id": organization_id}
            )
        return organization.ai_assistance_enabled

    async def require_enabled(self, *, organization_id: UUID) -> None:
        """Refuse when the organization has switched AI assistance off.

        Raises:
            AiAssistanceDisabledError: When the switch is off.
            NotFoundError: When the organization does not exist.
        """
        if not await self.is_enabled(organization_id=organization_id):
            raise AiAssistanceDisabledError(
                message=(
                    "AI assistance is switched off for this organization. An owner or admin "
                    "can switch it on in the organization's settings."
                ),
                details={"organization_id": organization_id},
            )
