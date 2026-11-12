"""Decision evidence stays scoped, append-only and explicitly reviewed for Improve."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.memory_keys import person_owner_key, room_owner_key
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.repositories.memory_claim import ClaimScope
from app.schemas.dataset import DatasetCreate
from app.schemas.decision_episode import DecisionEpisode, ImproveCaseReview
from app.schemas.memory import MemoryClaimCorrect
from app.services.dataset import DatasetService
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
            ImproveCaseReview(
                confirmed=True,
                dataset_id=uuid4(),
                input="Reviewed task",
                reference_answer="Escalate",
            ),
        )


async def test_improve_adds_only_human_reviewed_case_fields_and_refuses_foreign_claims(
    db: AsyncSession,
):
    user, org, agent, ctx = await seed(db)
    dataset = await DatasetService(db).create(ctx, DatasetCreate(name="Decisions"))
    result = await claims.remember(
        db,
        organization_id=org.id,
        scope=ClaimScope(person_owner_key(user.id), agent.id),
        statement="Ask the owner",
        kind="decision",
        episode=episode(),
    )
    review = ImproveCaseReview(
        confirmed=True,
        dataset_id=dataset.id,
        input="Reviewed problem",
        reference_answer="Reviewed expected action",
    )
    service = MemoryService(db)
    case = await service.improve_case(ctx, result.claim.id, review)
    assert case.input == review.input and case.reference_answer == review.reference_answer
    assert case.tags == ["decision-episode"]
    assert episode().situation not in case.model_dump_json()
    with pytest.raises(NotFoundError):
        await service.improve_case(
            ctx, result.claim.id, review.model_copy(update={"dataset_id": uuid4()})
        )
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


async def test_an_improve_case_is_anonymised_when_its_person_is_erased(db: AsyncSession) -> None:
    from app.db.models.agent_run import AgentRun
    from app.db.models.conversation import Conversation
    from app.db.models.dataset import DatasetCase
    from app.services.personal_data import ANONYMISED_CASE_INPUT, PersonalDataService

    user, org, agent, ctx = await seed(db)
    curator, _ = await seed_member(db)
    from app.db.models.organization import OrganizationMember

    db.add(OrganizationMember(organization_id=org.id, user_id=curator.id, role="owner"))
    chat = Conversation(organization_id=org.id, user_id=user.id, title="Delivery")
    db.add(chat)
    await db.flush()
    run = AgentRun(
        organization_id=org.id,
        agent_id=agent.id,
        user_id=user.id,
        conversation_id=chat.id,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    curator_ctx = AuthContext(user_id=curator.id, organization_id=org.id, role="owner")
    dataset = await DatasetService(db).create(curator_ctx, DatasetCreate(name="Decisions"))
    result = await claims.remember(
        db,
        organization_id=org.id,
        scope=ClaimScope(person_owner_key(user.id), agent.id),
        statement="Ask the owner",
        kind="decision",
        conversation_id=chat.id,
        run_id=run.id,
        episode=episode(),
    )
    added = await MemoryService(db).improve_case(
        ctx,
        result.claim.id,
        ImproveCaseReview(
            confirmed=True,
            dataset_id=dataset.id,
            input="Ada's delivery from Acme is overdue",
            reference_answer="Ask the owner",
        ),
    )
    case = await db.get(DatasetCase, added.id)
    assert case is not None
    assert (case.asked_by_user_id, case.source_run_id, case.source_conversation_id) == (
        user.id,
        run.id,
        chat.id,
    )

    await PersonalDataService(db).purge(user.id)

    await db.refresh(case)
    assert case.input == ANONYMISED_CASE_INPUT
    assert case.anonymised_at is not None


async def test_an_improve_case_links_no_source_that_is_gone_or_in_another_organization(
    db: AsyncSession,
) -> None:
    from app.db.models.conversation import Conversation
    from app.db.models.dataset import DatasetCase

    user, org, agent, ctx = await seed(db)
    other, other_org = await seed_member(db)
    elsewhere = Conversation(organization_id=other_org.id, user_id=other.id, title="Theirs")
    db.add(elsewhere)
    await db.flush()
    dataset = await DatasetService(db).create(ctx, DatasetCreate(name="Decisions"))
    result = await claims.remember(
        db,
        organization_id=org.id,
        scope=ClaimScope(person_owner_key(user.id), agent.id),
        statement="Ask the owner",
        kind="decision",
        conversation_id=elsewhere.id,
        run_id=uuid4(),
        episode=episode(),
    )

    added = await MemoryService(db).improve_case(
        ctx,
        result.claim.id,
        ImproveCaseReview(
            confirmed=True, dataset_id=dataset.id, input="Overdue", reference_answer="Ask"
        ),
    )

    case = await db.get(DatasetCase, added.id)
    assert case is not None
    assert (case.asked_by_user_id, case.source_run_id, case.source_conversation_id) == (
        user.id,
        None,
        None,
    )


async def test_a_reviewed_case_for_an_account_being_erased_is_refused(db: AsyncSession) -> None:
    from app.core.exceptions import ConcurrentChangeError
    from app.schemas.dataset import DatasetCaseContent

    _, _, _, ctx = await seed(db)
    dataset = await DatasetService(db).create(ctx, DatasetCreate(name="Decisions"))

    gone = uuid4()
    with pytest.raises(ConcurrentChangeError) as refused:
        await DatasetService(db).add_reviewed_case(
            ctx,
            dataset.id,
            DatasetCaseContent(input="Overdue", reference_answer="Ask"),
            asked_by=gone,
            source_run_id=None,
            source_conversation_id=None,
        )
    assert refused.value.details == {"user_id": gone}


async def test_the_source_of_a_reviewed_case_cannot_be_deleted_before_it_is_linked(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    from sqlalchemy import select
    from sqlalchemy.exc import DBAPIError

    from app.db.models.conversation import Conversation
    from app.schemas.dataset import DatasetCaseContent

    user, org, _, ctx = await seed(db)
    chat = Conversation(organization_id=org.id, user_id=user.id, title="Delivery")
    db.add(chat)
    await db.flush()
    dataset = await DatasetService(db).create(ctx, DatasetCreate(name="Decisions"))
    # Committed, so the other session can see the row it tries to take.
    await db.commit()

    await DatasetService(db).add_reviewed_case(
        ctx,
        dataset.id,
        DatasetCaseContent(input="Overdue", reference_answer="Ask"),
        asked_by=user.id,
        source_run_id=None,
        source_conversation_id=chat.id,
    )

    async with AsyncSession(engine) as other:
        with pytest.raises(DBAPIError, match="could not obtain lock"):
            await other.execute(
                select(Conversation.id)
                .where(Conversation.id == chat.id)
                .with_for_update(nowait=True)
            )
