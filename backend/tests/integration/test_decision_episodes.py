"""Decision evidence stays scoped, append-only and explicitly reviewed for Improve."""

from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.memory_keys import person_owner_key, room_owner_key
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.repositories.memory_claim import ClaimScope
from app.schemas.decision_episode import DecisionEpisode, ImproveCaseReview
from app.schemas.memory import MemoryClaimCorrect
from app.services.memory import MemoryService, claims
from tests.integration.workflow_run_support import seed_member

pytestmark = pytest.mark.anyio


async def seed(db: AsyncSession):
    user, org = await seed_member(db)
    agent = Agent(
        organization_id=org.id, name="Planner", slug=str(uuid4()), created_by_user_id=user.id
    )
    db.add(agent)
    await db.flush()
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    return user, org, agent, ctx


def episode() -> DecisionEpisode:
    return DecisionEpisode(
        situation="A delivery is overdue",
        choice="Ask the owner",
        alternatives=["Wait", "Escalate"],
        expected_outcome="A revised deadline",
    )


async def test_episode_retries_are_idempotent_but_outcomes_and_corrections_keep_history(
    db: AsyncSession,
):
    user, org, agent, ctx = await seed(db)
    args = {
        "organization_id": org.id,
        "scope": ClaimScope(person_owner_key(user.id), agent.id),
        "statement": "Ask the owner",
        "subject": "delivery_decision",
        "kind": "decision",
        "conversation_id": uuid4(),
        "run_id": uuid4(),
        "episode": episode(),
    }
    first = await claims.remember(db, **args)
    same = await claims.remember(db, **args)
    assert first.created and not same.created and same.claim.id == first.claim.id
    service = MemoryService(db)
    fixed = await service.correct_claim(
        ctx,
        first.claim.id,
        MemoryClaimCorrect(
            statement="Escalate after no reply",
            episode=episode().model_copy(
                update={"actual_outcome": "No reply", "correction": "Escalate after no reply"}
            ),
        ),
    )
    assert fixed.id != first.claim.id and fixed.supersedes_id == first.claim.id
    assert first.claim.status == "superseded" and first.claim.episode["actual_outcome"] is None
    assert fixed.episode is not None and fixed.episode.actual_outcome == "No reply"
    detail = await service.claim_detail(ctx, fixed.id)
    assert detail.superseded is not None and detail.superseded.episode == episode()
    with pytest.raises(ConflictError):
        await service.improve_case(
            ctx,
            first.claim.id,
            ImproveCaseReview(confirmed=True, input="Reviewed task", reference_answer="Escalate"),
        )


async def test_improve_exports_only_human_reviewed_case_fields_and_refuses_foreign_claims(
    db: AsyncSession,
):
    user, org, agent, ctx = await seed(db)
    result = await claims.remember(
        db,
        organization_id=org.id,
        scope=ClaimScope(person_owner_key(user.id), agent.id),
        statement="Ask the owner",
        kind="decision",
        episode=episode(),
    )
    review = ImproveCaseReview(
        confirmed=True, input="Reviewed problem", reference_answer="Reviewed expected action"
    )
    service = MemoryService(db)
    case = await service.improve_case(ctx, result.claim.id, review)
    assert case.input == review.input and case.reference_answer == review.reference_answer
    # #2172 dataset_files.COLUMNS and DatasetCaseContent accept this flat JSONL subset.
    assert set(case.model_dump()) == {"input", "reference_answer", "tags", "note"}
    assert episode().situation not in case.model_dump_json()
    other, other_org = await seed_member(db)
    with pytest.raises(NotFoundError):
        await service.improve_case(
            AuthContext(user_id=other.id, organization_id=other_org.id, role="owner"),
            result.claim.id,
            review,
        )
    room = await claims.remember(
        db,
        organization_id=org.id,
        scope=ClaimScope(room_owner_key("slack", "team"), agent.id),
        statement="Room decision",
        kind="decision",
        episode=episode(),
    )
    with pytest.raises(NotFoundError):
        await service.improve_case(ctx, room.claim.id, review)
    plain = await claims.remember(
        db,
        organization_id=org.id,
        scope=ClaimScope(person_owner_key(user.id), agent.id),
        statement="A fact",
    )
    with pytest.raises(BadRequestError):
        await service.improve_case(ctx, plain.claim.id, review)


async def test_consolidation_does_not_turn_distinct_decision_evidence_into_a_rule(db: AsyncSession):
    user, org, agent, _ = await seed(db)
    scope = ClaimScope(person_owner_key(user.id), agent.id)
    one = await claims.remember(
        db,
        organization_id=org.id,
        scope=scope,
        statement="Ask",
        subject="delivery",
        kind="decision",
        episode=episode(),
    )
    two = await claims.remember(
        db,
        organization_id=org.id,
        scope=scope,
        statement="Ask",
        subject="delivery",
        kind="decision",
        episode=episode().model_copy(update={"actual_outcome": "Deadline revised"}),
    )
    assert one.claim.id != two.claim.id
    consolidated = await claims.consolidate(db, organization_id=org.id, scope_key=scope.scope_key)
    assert consolidated.ran and consolidated.merged == 0
    with pytest.raises(BadRequestError):
        await claims.remember(
            db, organization_id=org.id, scope=scope, statement="Not a decision", episode=episode()
        )


@pytest.mark.parametrize(
    "data",
    [
        {"situation": "", "choice": "x"},
        {"situation": "x", "choice": "x", "alternatives": ["x"] * 9},
        {"situation": "x", "choice": "x", "actual_outcome": "x" * 1201},
    ],
)
async def test_episode_evidence_is_bounded(data: dict[str, object]):
    with pytest.raises(ValidationError):
        DecisionEpisode.model_validate(data)


async def test_case_export_requires_explicit_review():
    with pytest.raises(ValidationError):
        ImproveCaseReview(confirmed=False, input="x", reference_answer="x")


async def test_personal_claim_export_counts_non_episode_text_before_loading(db: AsyncSession):
    from app.db.models.memory_claim import MemoryClaim
    from app.repositories.personal_data import decision_episode_export_size

    user, org, _, _ = await seed(db)
    db.add(
        MemoryClaim(
            organization_id=org.id,
            scope_key=person_owner_key(user.id),
            statement="x" * 6000,
            kind="fact",
            origin="person",
            status="superseded",
            episode=None,
        )
    )
    await db.flush()
    assert await decision_episode_export_size(db, user.id) >= 12000
