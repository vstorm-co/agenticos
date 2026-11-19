"""Persisted grade evidence follows current access in the inbox and delayed delivery."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Perm
from app.db.models.notification import Notification, NotificationChannel, NotificationEventType
from app.db.models.organization import OrganizationMember
from app.db.models.user import User
from app.schemas.notification import CriterionSources
from app.services.notification_center import NotificationCenterService
from app.services.notification_delivery import NotificationDeliveryService
from tests.integration.test_authoring import _owner
from tests.integration.test_eval_suites import _dataset
from tests.integration.test_notification_delivery import _delivery, _sent
from tests.integration.test_skill_bindings import _skill

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize(
    "denied",
    [
        None,
        "runs",
        "dataset",
        "skill",
        "missing_sources",
        "malformed_sources",
        "deleted_dataset",
        "deleted_skill",
        "reused_skill_name",
        "renamed_skill",
        "legacy_names",
    ],
)
async def test_stored_criterion_notifications_recheck_their_sources(
    db: AsyncSession, denied: str | None
):
    ctx = await _owner(db)
    dataset = await _dataset(db, ctx, cases=1)
    skill = await _skill(db, ctx)
    sources = CriterionSources(dataset_id=dataset.id, skill_ids=[skill.id]).model_dump(mode="json")
    context = {"criteria": [{"name": "private rubric"}], "criterion_sources": sources}
    if denied == "missing_sources":
        del context["criterion_sources"]
    elif denied == "legacy_names":
        context["criterion_sources"] = {"dataset_id": str(dataset.id), "skill_names": [skill.name]}
    elif denied == "malformed_sources":
        context["criterion_sources"] = {"dataset_id": "invalid"}
    row = Notification(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        recipient_user_id=ctx.user_id,
        event_type=NotificationEventType.IMPROVEMENT_FINISHED.value,
        occurrence_id=str(uuid.uuid4()),
        summary="Private rubric improved",
        render_context=context,
        in_app_visible=True,
    )
    coarse = Notification(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        recipient_user_id=ctx.user_id,
        event_type=NotificationEventType.IMPROVEMENT_FINISHED.value,
        occurrence_id=str(uuid.uuid4()),
        summary="Improve finished",
        render_context={},
        in_app_visible=True,
    )
    db.add_all([row, coarse])
    if denied == "deleted_dataset":
        await db.delete(dataset)
    elif denied in {"deleted_skill", "reused_skill_name"}:
        await db.delete(skill)
        await db.flush()
        if denied == "reused_skill_name":
            await _skill(db, ctx, name=skill.name)
    elif denied == "renamed_skill":
        skill.name = "renamed-source"
    await db.flush()
    scopes = {Perm.RUNS_VIEW, Perm.DATASETS_VIEW, Perm.SKILLS_VIEW}
    removed = {
        "runs": Perm.RUNS_VIEW,
        "dataset": Perm.DATASETS_VIEW,
        "skill": Perm.SKILLS_VIEW,
    }.get(denied)
    reader = replace(ctx, key_scopes=frozenset(scopes - {removed})) if removed else ctx
    center = NotificationCenterService(db)
    rows, _, _ = await center.list_inbox(reader, after=None, limit=20)
    assert (row.id in {item.id for item in rows}) is (denied in {None, "renamed_skill"})
    assert coarse.id in {item.id for item in rows}
    assert (await center.gate_for(reader, row)).visible is (denied in {None, "renamed_skill"})


@pytest.mark.parametrize("revoked", [False, True])
async def test_delayed_criterion_email_rechecks_membership_before_sending(
    db: AsyncSession, revoked: bool
):
    ctx = await _owner(db)
    dataset = await _dataset(db, ctx, cases=1)
    skill = await _skill(db, ctx)
    recipient = await db.get(User, ctx.user_id)
    assert recipient is not None
    await NotificationCenterService(db).update_preference(
        ctx,
        event_type=NotificationEventType.IMPROVEMENT_FINISHED,
        channel=NotificationChannel.EMAIL,
        enabled=True,
    )
    now = datetime.now(UTC)
    delivery = await _delivery(
        db,
        recipient=recipient,
        organization_id=ctx.organization_id,
        event_type=NotificationEventType.IMPROVEMENT_FINISHED,
        claimed_at=now,
        attempts=1,
        render_context={
            "agent_name": "Agent",
            "status": "ready",
            "reason": None,
            "app_name": "AgenticOS",
            "run_url": "https://example.com/improve",
            "criteria": [
                {
                    "name": "private rubric",
                    "graded": 5,
                    "before": 0,
                    "after": 5,
                    "direction": "better",
                }
            ],
            "criterion_sources": CriterionSources(
                dataset_id=dataset.id, skill_ids=[skill.id]
            ).model_dump(mode="json"),
        },
    )
    if revoked:
        member = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == ctx.organization_id,
                OrganizationMember.user_id == ctx.user_id,
            )
        )
        assert member is not None
        member.role = "member"
        await db.flush()
    provider = _sent()
    with patch("app.services.notification_delivery.get_email_service", new=provider):
        outcome = await NotificationDeliveryService(db).send_and_settle(delivery.id, claimed_at=now)
    assert outcome == ("skipped" if revoked else "sent")
    assert provider.return_value.send.await_count == (0 if revoked else 1)


async def test_a_criterion_notice_keeps_provenance_and_refuses_missing_sources(db: AsyncSession):
    from app.db.models.improvement import CriterionDetail
    from app.services.notifications import NotificationService
    from tests.integration.test_eval_suites import _agent

    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    criterion: CriterionDetail = {
        "scorer": "judge",
        "name": "private rubric",
        "graded": 5,
        "before": 0,
        "after": 5,
        "fixed": 5,
        "broken": 0,
    }
    service = NotificationService(db)
    run_id = uuid.uuid4()
    with pytest.raises(ValueError, match="source provenance"):
        await service.improvement_finished(
            agent=agent,
            run_id=run_id,
            user_id=ctx.user_id,
            status="ready",
            reason=None,
            end="ready",
            verdict="criteria_better",
            criteria=[criterion],
        )
    assert list(await db.scalars(select(Notification))) == []
    # No recipient remains a no-op, even if the caller supplies criterion evidence.
    await service.improvement_finished(
        agent=agent,
        run_id=run_id,
        user_id=None,
        status="ready",
        reason=None,
        end="ready",
        verdict="criteria_better",
        criteria=[criterion],
    )
    sources = CriterionSources(dataset_id=dataset.id, skill_ids=[])
    await service.improvement_finished(
        agent=agent,
        run_id=run_id,
        user_id=ctx.user_id,
        status="ready",
        reason=None,
        end="ready",
        verdict="criteria_better",
        criteria=[criterion],
        criterion_sources=sources,
    )
    row = await db.scalar(select(Notification))
    assert row is not None and row.render_context is not None
    assert row.render_context["criterion_sources"] == sources.model_dump(mode="json")
    assert (await NotificationCenterService(db).gate_for(ctx, row)).visible
