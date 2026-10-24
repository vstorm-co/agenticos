"""A change of model is accepted on a check of exactly what accepting it leaves.

The combination is the draft with every suggestion still waiting made - what
Check with evals measures. Dismissing another suggestion or editing the draft
makes the last check one of something else, so it no longer counts.
"""

import pytest

from app.core.exceptions import BadRequestError
from app.schemas.authoring import HunkDecision, ProposalCheck
from app.services.authoring import AuthoringService
from tests.integration.test_authoring import (
    COMMENT,
    _environment,  # noqa: F401 - the autouse fixture that scripts the improver's model
    _improve,
    _setup,
)
from tests.integration.test_authoring_check_base import _finish, _shop_dataset
from tests.integration.test_authoring_fields_flow import _change, _improver, _profile

pytestmark = pytest.mark.anyio


async def _model_and_window(db):
    """A batch changing the model and naming the refund window, and a dataset to check it on."""
    ctx, agent, run = await _setup(db)
    cheap = await _profile(db, ctx, "gpt-4o-mini")
    run_id = str(run.id)
    model = _improver(
        db,
        run_id,
        [_change(run_id, "model_profile_id", "set", str(cheap.id))],
        instructions=[
            {
                "old_text": "Be brief.",
                "new_text": "Be brief. Refunds take 30 days.",
                "rationale": "Readers corrected the window",
                "evidence": [{"run_id": run_id, "quote": COMMENT}],
            }
        ],
    )
    await _improve(db, ctx, agent, model)
    dataset = await _shop_dataset(db, ctx)
    service = AuthoringService(db)
    batch = (await service.for_agent(ctx, agent.id)).batch
    assert batch is not None
    by_path = {hunk.path: hunk for hunk in batch.hunks}
    return ctx, agent, dataset, service, by_path["model_profile_id"], by_path[None]


async def _checked(db, ctx, agent, dataset, service: AuthoringService) -> None:
    started = await service.check(ctx, agent.id, ProposalCheck(dataset_id=dataset.id))
    await _finish(db, ctx, started.id)


async def _blocked(ctx, agent, service: AuthoringService, hunk_id) -> str | None:
    batch = (await service.for_agent(ctx, agent.id)).batch
    assert batch is not None
    return next(hunk.blocked for hunk in batch.hunks if hunk.id == hunk_id)


async def test_a_check_of_another_combination_is_out_of_date_until_checked_again(db):
    ctx, agent, dataset, service, model, window = await _model_and_window(db)
    await _checked(db, ctx, agent, dataset, service)
    assert await _blocked(ctx, agent, service, model.id) is None

    await service.decide(ctx, agent.id, window.id, HunkDecision(action="dismiss"))

    assert await _blocked(ctx, agent, service, model.id) == "check_outdated"
    with pytest.raises(BadRequestError, match="out of date"):
        await service.decide(ctx, agent.id, model.id, HunkDecision(action="accept"))

    await _checked(db, ctx, agent, dataset, service)
    accepted = await service.decide(ctx, agent.id, model.id, HunkDecision(action="accept"))
    assert accepted.draft_spec["model_profile_id"] == model.new_value


async def test_accepting_the_other_suggestions_first_keeps_the_check(db):
    ctx, agent, dataset, service, model, window = await _model_and_window(db)
    await _checked(db, ctx, agent, dataset, service)

    await service.decide(ctx, agent.id, window.id, HunkDecision(action="accept"))
    accepted = await service.decide(ctx, agent.id, model.id, HunkDecision(action="accept"))

    assert accepted.draft_spec["model_profile_id"] == model.new_value


async def test_an_edit_of_the_draft_makes_the_check_out_of_date(db):
    ctx, agent, dataset, service, model, _ = await _model_and_window(db)
    await _checked(db, ctx, agent, dataset, service)

    await db.refresh(agent)
    agent.draft_spec = {**agent.draft_spec, "description": "Edited by hand"}
    await db.flush()

    with pytest.raises(BadRequestError, match="out of date"):
        await service.decide(ctx, agent.id, model.id, HunkDecision(action="accept"))
