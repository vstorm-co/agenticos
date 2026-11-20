"""Keys drafted from a case's reference answer: who may ask, what the job keeps, what erasure takes.

The key extractor is reached only through `SystemAgentRunner.run`, which these tests
stand in for; whether it refuses on budget before the model is called is the
runner's own to prove.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, update

from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    SystemAgentRunError,
    SystemAgentUnavailableError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.background_job import BackgroundJob
from app.db.models.case_key_draft import KEY_DRAFT_RETENTION_DAYS, CaseKeyDraft
from app.db.models.dataset import DatasetCase
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import personal_data_repo
from app.schemas.case_key_draft import ExtractedKeys
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate
from app.schemas.scoring import DocumentKey
from app.services import case_key_draft as drafts_module
from app.services.case_key_draft import (
    NO_REFERENCE,
    REQUESTER_GONE,
    STOPPED,
    CaseKeyDraftService,
    kept_keys,
)
from app.services.dataset import DatasetService
from app.services.system_agent_runner import SystemAgentResult, SystemAgentRunner
from app.worker.tasks.case_key_tasks import expire_case_key_drafts

pytestmark = pytest.mark.anyio

DOCUMENT = "Invoice INV-7 for Fernhill Ltd. Total 1 234,50 PLN, due 2026-12-01."


async def _user(db) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    return user


async def _owner(db) -> AuthContext:
    person = await _user(db)
    org = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=person.id
    )
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=person.id, role="owner"))
    await db.flush()
    return AuthContext(user_id=person.id, organization_id=org.id, role=OrgRoleName.OWNER.value)


async def _member(db, organization_id: uuid.UUID, role: OrgRoleName) -> AuthContext:
    person = await _user(db)
    db.add(OrganizationMember(organization_id=organization_id, user_id=person.id, role=role.value))
    await db.flush()
    return AuthContext(user_id=person.id, organization_id=organization_id, role=role.value)


async def _case(db, ctx: AuthContext, *, reference: str | None = DOCUMENT):
    datasets = DatasetService(db)
    dataset = await datasets.create(ctx, DatasetCreate(name=f"invoices-{uuid.uuid4().hex[:6]}"))
    content = DatasetCaseCreate(
        input="Write the invoice",
        reference_answer=reference,
        checks=[] if reference else [{"type": "contains", "value": "INV"}],
    )
    case = await datasets.add_case(ctx, dataset.id, content)
    return dataset, case


async def _run(db, ctx: AuthContext) -> AgentRun:
    agent = Agent(
        organization_id=ctx.organization_id, slug=f"x-{uuid.uuid4().hex[:8]}", name="Extractor"
    )
    db.add(agent)
    await db.flush()
    run = AgentRun(
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        user_id=ctx.user_id,
        status="completed",
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    return run


def _answer(monkeypatch, output: ExtractedKeys | Exception, run: AgentRun | None = None):
    calls = AsyncMock(
        side_effect=output
        if isinstance(output, Exception)
        else lambda *a, **k: SystemAgentResult(output=output, run=run)
    )
    monkeypatch.setattr(SystemAgentRunner, "run", calls)
    return calls


@pytest.fixture(autouse=True)
def _runnable(monkeypatch) -> None:
    # Whether the extractor could run is the runner's to prove; these are about the draft.
    monkeypatch.setattr(SystemAgentRunner, "require_runnable", AsyncMock())


async def _started(db, ctx: AuthContext):
    dataset, case = await _case(db, ctx)
    draft = await CaseKeyDraftService(db).start(ctx, dataset.id, case.case_id)
    return dataset, case, draft


class TestAsking:
    async def test_a_start_queues_a_running_draft_as_a_job_and_audits_it(self, db) -> None:
        owner = await _owner(db)

        dataset, case, draft = await _started(db, owner)

        assert (draft.status, draft.keys, draft.case_id) == ("running", [], case.case_id)
        job = (await db.execute(select(BackgroundJob))).scalar_one()
        assert (job.kind, job.payload) == (
            "extract-case-keys",
            {"draft_id": str(draft.id), "organization_id": str(owner.organization_id)},
        )
        details = await db.scalar(
            select(AppAdminAuditLog.details).where(
                AppAdminAuditLog.action == "dataset.keys_requested"
            )
        )
        assert details == {"case_id": str(case.case_id)}

    async def test_asking_again_replaces_the_case_s_draft(self, db) -> None:
        owner = await _owner(db)
        dataset, case, first = await _started(db, owner)

        second = await CaseKeyDraftService(db).start(owner, dataset.id, case.case_id)

        assert second.id != first.id
        assert await db.scalar(select(func.count(CaseKeyDraft.id))) == 1

    async def test_a_case_without_a_reference_answer_is_refused(self, db) -> None:
        owner = await _owner(db)
        dataset, case = await _case(db, owner, reference=None)

        with pytest.raises(BadRequestError, match=NO_REFERENCE):
            await CaseKeyDraftService(db).start(owner, dataset.id, case.case_id)
        assert await db.scalar(select(func.count(CaseKeyDraft.id))) == 0

    async def test_a_viewer_may_not_ask_and_another_organization_sees_nothing(self, db) -> None:
        owner = await _owner(db)
        dataset, case = await _case(db, owner)
        viewer = await _member(db, owner.organization_id, OrgRoleName.VIEWER)
        stranger = await _owner(db)

        with pytest.raises(AuthorizationError):
            await CaseKeyDraftService(db).start(viewer, dataset.id, case.case_id)
        with pytest.raises(NotFoundError):
            await CaseKeyDraftService(db).start(stranger, dataset.id, case.case_id)
        with pytest.raises(NotFoundError):
            await CaseKeyDraftService(db).get(stranger, dataset.id, case.case_id)

    async def test_an_extractor_that_cannot_run_is_refused_before_anything_is_queued(
        self, db, monkeypatch
    ) -> None:
        owner = await _owner(db)
        dataset, case = await _case(db, owner)
        refusal = SystemAgentUnavailableError(
            message="'Key extractor' is over its budget", key="key_extractor", reason="budget"
        )
        monkeypatch.setattr(SystemAgentRunner, "require_runnable", AsyncMock(side_effect=refusal))

        with pytest.raises(SystemAgentUnavailableError):
            await CaseKeyDraftService(db).start(owner, dataset.id, case.case_id)
        assert await db.scalar(select(func.count(BackgroundJob.id))) == 0
        assert await db.scalar(select(func.count(CaseKeyDraft.id))) == 0


class TestTheJob:
    async def test_only_values_the_document_states_are_kept_each_label_once(
        self, db, monkeypatch
    ) -> None:
        owner = await _owner(db)
        _, _, draft = await _started(db, owner)
        run = await _run(db, owner)
        calls = _answer(
            monkeypatch,
            ExtractedKeys(
                keys=[
                    DocumentKey(key="Invoice", value="INV-7"),
                    DocumentKey(key="Total", value="1234,50 PLN"),
                    DocumentKey(key="invoice ", value="INV-7"),
                    DocumentKey(key="VAT", value="23%"),
                    DocumentKey(key="Due", value="2026-12-01"),
                ]
            ),
            run,
        )

        await CaseKeyDraftService(db).extract(draft.id, owner.organization_id)

        row = await db.get(CaseKeyDraft, draft.id)
        assert row is not None
        assert (row.status, row.run_id, row.error) == ("ready", run.id, None)
        assert row.keys == [
            {"key": "Invoice", "value": "INV-7"},
            {"key": "Total", "value": "1234,50 PLN"},
            {"key": "Due", "value": "2026-12-01"},
        ]
        assert "INV-7" in calls.await_args.kwargs["prompt"]
        assert calls.await_args.kwargs["key"] == "key_extractor"

    async def test_a_run_that_ended_without_an_answer_fails_the_draft_and_keeps_the_run(
        self, db, monkeypatch
    ) -> None:
        owner = await _owner(db)
        _, _, draft = await _started(db, owner)
        run = await _run(db, owner)
        _answer(
            monkeypatch,
            SystemAgentRunError(
                message="did not finish: budget_exceeded", run_id=run.id, status="budget_exceeded"
            ),
        )

        await CaseKeyDraftService(db).extract(draft.id, owner.organization_id)

        row = await db.get(CaseKeyDraft, draft.id)
        assert row is not None
        assert (row.status, row.error, row.run_id, row.keys) == (
            "failed",
            "did not finish: budget_exceeded",
            run.id,
            [],
        )

    async def test_an_unexpected_failure_fails_the_draft_with_our_own_words(
        self, db, monkeypatch
    ) -> None:
        owner = await _owner(db)
        _, _, draft = await _started(db, owner)
        # The request committed the draft; the job's rollback must not take it with it.
        await db.commit()
        _answer(monkeypatch, RuntimeError("socket closed at 10.0.0.3"))

        await CaseKeyDraftService(db).extract(draft.id, owner.organization_id)

        row = await db.get(CaseKeyDraft, draft.id)
        assert row is not None
        assert (row.status, row.error) == ("failed", drafts_module.FAILED)

    async def test_a_requester_who_left_fails_the_draft_without_a_run(
        self, db, monkeypatch
    ) -> None:
        owner = await _owner(db)
        builder = await _member(db, owner.organization_id, OrgRoleName.BUILDER)
        dataset, case = await _case(db, owner)
        draft = await CaseKeyDraftService(db).start(builder, dataset.id, case.case_id)
        member = await db.scalar(
            select(OrganizationMember).where(OrganizationMember.user_id == builder.user_id)
        )
        await db.delete(member)
        await db.flush()
        calls = _answer(monkeypatch, RuntimeError("must not run"))

        await CaseKeyDraftService(db).extract(draft.id, owner.organization_id)

        row = await db.get(CaseKeyDraft, draft.id)
        assert row is not None
        assert (row.status, row.error) == ("failed", REQUESTER_GONE)
        calls.assert_not_awaited()

    async def test_a_draft_already_ended_is_left_as_it_is(self, db, monkeypatch) -> None:
        owner = await _owner(db)
        _, _, draft = await _started(db, owner)
        row = await db.get(CaseKeyDraft, draft.id)
        assert row is not None
        row.status = "ready"
        await db.flush()
        calls = _answer(monkeypatch, RuntimeError("must not run"))

        await CaseKeyDraftService(db).extract(draft.id, owner.organization_id)

        calls.assert_not_awaited()

    async def test_a_lost_job_fails_its_running_draft(self, db, monkeypatch) -> None:
        owner = await _owner(db)
        _, _, draft = await _started(db, owner)
        await db.commit()

        await drafts_module.settle_lost(draft.id, owner.organization_id)

        row = await db.get(CaseKeyDraft, draft.id)
        assert row is not None
        await db.refresh(row)
        assert (row.status, row.error) == ("failed", STOPPED)


class TestExpiry:
    async def test_a_draft_nobody_acted_on_expires_in_every_organization(self, db) -> None:
        now = datetime.now(UTC)
        drafts = []
        for age in (KEY_DRAFT_RETENTION_DAYS + 1, KEY_DRAFT_RETENTION_DAYS + 1, 1):
            _, _, draft = await _started(db, await _owner(db))
            await db.execute(
                update(CaseKeyDraft)
                .where(CaseKeyDraft.id == draft.id)
                .values(created_at=now - timedelta(days=age))
            )
            drafts.append(draft.id)
        await db.commit()

        assert await expire_case_key_drafts() == 2
        assert await expire_case_key_drafts() == 0

        left = await db.execute(select(CaseKeyDraft.id).execution_options(populate_existing=True))
        assert left.scalars().all() == [drafts[2]]


class TestReviewing:
    async def test_the_draft_is_read_and_dismissed_by_an_editor(self, db) -> None:
        owner = await _owner(db)
        dataset, case, draft = await _started(db, owner)
        service = CaseKeyDraftService(db)

        assert (await service.get(owner, dataset.id, case.case_id)).id == draft.id
        await service.dismiss(owner, dataset.id, case.case_id)
        with pytest.raises(NotFoundError):
            await service.get(owner, dataset.id, case.case_id)
        await service.dismiss(owner, dataset.id, case.case_id)

    async def test_anonymising_the_case_deletes_its_draft(self, db) -> None:
        owner = await _owner(db)
        dataset, case, draft = await _started(db, owner)
        row = await db.get(DatasetCase, case.id)
        assert row is not None
        row.asked_by_user_id = owner.user_id
        await db.flush()

        await personal_data_repo.anonymise_dataset_cases_of(
            db, owner.user_id, placeholder="[erased]", at=datetime.now(UTC)
        )

        assert await db.get(CaseKeyDraft, draft.id) is None


def test_kept_keys_drop_what_the_document_does_not_say_and_repeated_labels() -> None:
    keys = [
        DocumentKey(key="Invoice", value="INV-7"),
        DocumentKey(key="Invoice", value="INV-8"),
        DocumentKey(key="Partner", value="ACME"),
        DocumentKey(key="Total", value="1234,50"),
    ]

    assert kept_keys(DOCUMENT, keys) == [
        {"key": "Invoice", "value": "INV-7"},
        {"key": "Total", "value": "1234,50"},
    ]
