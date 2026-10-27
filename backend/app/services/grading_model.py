"""Which model a new judge grades on.

A judge weaker than the agent it grades misreads answers the agent got right, and
an improvement session then measures the grader rather than the agent. So a new
judge runs on the organization's Grading model when it named one, and otherwise on
a model that costs more to write with than the agent's - the only strength signal
every provider publishes. Existing judges are never moved: a judge's model is part
of what a stored grade means.
"""

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import price_request
from app.db.models.credential import ModelProfile
from app.repositories import credential_repo, organization_repo
from app.services.model_outputs import model_outputs

_PRICED_TOKENS = RunUsage(output_tokens=1_000_000)


def output_price(profile: ModelProfile) -> Decimal | None:
    """What a million written tokens cost on this profile; `None` where it is not priced."""
    return price_request(_PRICED_TOKENS, profile.model, profile.provider)


async def grading_profile(
    db: AsyncSession, *, organization_id: UUID, graded: Sequence[ModelProfile | None]
) -> ModelProfile | None:
    """The model a new judge of `graded` - the agent's models - grades on.

    The organization's Grading model when it names one of its chat models. Without
    one, the cheapest of its chat models that costs more to write with than every
    model in `graded`, the oldest of them on a tie. `None` when nothing qualifies -
    no price for a graded model, or nothing priced above it - and the caller keeps
    its own default.
    """
    organization = await organization_repo.get_by_id(db, organization_id)
    if organization is not None and organization.grading_model_profile_id is not None:
        chosen = await credential_repo.get_profile(
            db, organization.grading_model_profile_id, organization_id=organization_id
        )
        if chosen is not None and _chat(chosen):
            return chosen
    prices = [output_price(profile) for profile in graded if profile is not None]
    if not prices or any(price is None for price in prices):
        return None
    ceiling = max(price for price in prices if price is not None)
    above = [
        (price, profile.created_at, profile.id, profile)
        for profile in await credential_repo.list_profiles(db, organization_id=organization_id)
        if _chat(profile) and (price := output_price(profile)) is not None and price > ceiling
    ]
    return min(above, key=lambda row: row[:3])[3] if above else None


def _chat(profile: ModelProfile) -> bool:
    return model_outputs(profile.provider, profile.model, base_url=profile.base_url).chat
