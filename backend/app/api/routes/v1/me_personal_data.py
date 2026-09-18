"""What this deployment holds about the person asking, as one document."""

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, PersonalDataSvc, limit_personal_data_export
from app.schemas.personal_data import PersonalDataExport

router = APIRouter()


@router.get(
    "/export",
    response_model=PersonalDataExport,
    dependencies=[Depends(limit_personal_data_export)],
)
async def export_my_data(
    service: PersonalDataSvc,
    current_user: CurrentUser,
) -> Any:
    """Everything this deployment holds about you, as JSON.

    GDPR art. 15 in one request. The threads you started with every turn in
    them, what you rated, where you signed in, what agents have written down
    about you, the platform accounts you linked, the runs you started and what
    they cost.

    **Not in it, and `docs/security.md` says why in the same breath as the
    inventory:** the audit trail. An entry naming you as the actor is the
    organization's record of what was done in it rather than your data to take
    away, and one with its actor removed is worse than one naming a deleted
    account. Nor is anything you *created* on the organization's behalf - an
    agent, a knowledge base, a stored credential - which belongs to the
    organization and outlives your membership.

    Rate-limited per hour rather than per minute: it is the one route that puts
    everything about a person in one file, and a person does that once.

    The request is recorded in the audit trail, including when you export
    yourself. An export is the shape of a breach when the caller is not who they
    claim to be, and the entry is what makes that readable afterwards.
    """
    return await service.export(current_user.id, actor_user_id=current_user.id)
