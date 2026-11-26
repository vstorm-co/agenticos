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
from app.db.models.agent import Agent, AgentKind
from app.db.models.agent_run import AgentRun
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.background_job import BackgroundJob
from app.db.models.case_key_draft import KEY_DRAFT_RETENTION_DAYS, CaseKeyDraft, KeyDraftStatus
from app.db.models.dataset import DatasetCase
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import ResourceGrant
from app.db.models.run_manifest import RunManifest
from app.db.models.user import User
from app.repositories import case_key_draft_repo, personal_data_repo
from app.schemas.case_key_draft import ExtractedKeys
from app.schemas.dataset import (
    DatasetCaseCreate,
    DatasetCaseFromMessage,
    DatasetCaseUpdate,
    DatasetCreate,
)
from app.schemas.scoring import MAX_KEYS, DocumentKey
from app.services import case_key_draft as drafts_module
from app.services.agent_runner import AgentRunnerService
from app.services.api_key import KEY_GONE
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
from tests.integration.test_datasets import _rated_down_turn

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


async def _remembered(db, ctx: AuthContext) -> AgentRun:
    """An extractor run whose manifest still holds the reference answer."""
    run = await _run(db, ctx)
    db.add(
        RunManifest(
            run_id=run.id,
            organization_id=ctx.organization_id,
            payload={"instructions": "List the facts.", "messages": [{"content": DOCUMENT}]},
        )
    )
    await db.flush()
    return run


async def _forgotten(db, run: AgentRun | uuid.UUID) -> bool:
    run_id = run if isinstance(run, uuid.UUID) else run.id
    manifest = await db.scalar(
        select(RunManifest)
        .where(RunManifest.run_id == run_id)
        .execution_options(populate_existing=True)
    )
    assert manifest is not None
    return manifest.truncated and manifest.payload == {"instructions": "List the facts."}


async def _gone(db, how: str, ctx: AuthContext, dataset, case) -> None:
    """Delete a case's draft the way `how` names."""
    service = CaseKeyDraftService(db)
    if how == "replaced":
        await service.start(ctx, dataset.id, case.case_id)
    elif how == "dismissed":
        await service.dismiss(ctx, dataset.id, case.case_id)
    elif how == "expired":
        await case_key_draft_repo.delete_expired(
            db, created_before=datetime.now(UTC) + timedelta(1)
        )
    elif how == "anonymised":
        revision = await db.get(DatasetCase, case.id)
        assert revision is not None
        revision.asked_by_user_id = ctx.user_id
        await db.flush()
        await personal_data_repo.anonymise_dataset_cases_of(
            db, ctx.user_id, placeholder="[erased]", at=datetime.now(UTC)
        )
    else:
        await DatasetService(db).delete(ctx, dataset.id)


_WAYS = ["replaced", "dismissed", "expired", "anonymised", "dataset deleted"]


def _failed_after_starting(monkeypatch, run: AgentRun, *, gone=None) -> None:
    """The extractor's run is recorded, then fails with a provider's own exception."""

    run_id = run.id

    async def failing(runner: SystemAgentRunner, ctx, **_: object) -> SystemAgentResult:
        if gone is not None:
            await _gone(runner.db, "dismissed", *gone)
            await runner.db.commit()
        runner.failed_run_id = run_id
        raise RuntimeError("socket closed at 10.0.0.3")

    monkeypatch.setattr(SystemAgentRunner, "run", failing)


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

    async def test_a_case_whose_conversation_the_editor_may_not_read_is_refused(self, db) -> None:
        owner = await _owner(db)
        editor = await _member(db, owner.organization_id, OrgRoleName.VIEWER)
        datasets = DatasetService(db)
        dataset = await datasets.create(owner, DatasetCreate(name="from chats"))
        _, answer = await _rated_down_turn(db, owner)
        case = await datasets.add_from_message(
            owner, dataset.id, DatasetCaseFromMessage(message_id=answer.id)
        )
        await datasets.update_case(
            owner, dataset.id, case.case_id, DatasetCaseUpdate(reference_answer=DOCUMENT)
        )
        db.add(
            ResourceGrant(
                organization_id=owner.organization_id,
                subject_user_id=editor.user_id,
                resource_type="dataset",
                resource_id=dataset.id,
                level="edit",
            )
        )
        await db.flush()

        with pytest.raises(AuthorizationError, match="source conversation"):
            await CaseKeyDraftService(db).start(editor, dataset.id, case.case_id)

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
        run = await _remembered(db, owner)
        run_id = run.id
        # The request committed the draft; the job's rollback must not take it with it.
        await db.commit()
        _failed_after_starting(monkeypatch, run)

        await CaseKeyDraftService(db).extract(draft.id, owner.organization_id)

        row = await db.get(CaseKeyDraft, draft.id, populate_existing=True)
        assert row is not None
        assert (row.status, row.error, row.run_id) == ("failed", drafts_module.FAILED, run_id)
        assert not await _forgotten(db, run_id)

    async def test_an_unexpected_failure_of_a_draft_gone_meanwhile_forgets_its_run(
        self, db, monkeypatch
    ) -> None:
        owner = await _owner(db)
        dataset, case, draft = await _started(db, owner)
        run = await _remembered(db, owner)
        run_id = run.id
        await db.commit()
        _failed_after_starting(monkeypatch, run, gone=(owner, dataset, case))

        await CaseKeyDraftService(db).extract(draft.id, owner.organization_id)

        assert await db.get(CaseKeyDraft, draft.id, populate_existing=True) is None
        assert await _forgotten(db, run_id)

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

    async def test_a_revoked_key_fails_the_draft(self, db, monkeypatch) -> None:
        owner = await _owner(db)
        _, _, draft = await _started(db, owner)
        row = await db.get(CaseKeyDraft, draft.id)
        assert row is not None
        row.created_by_api_key_id = uuid.uuid4()
        await db.flush()
        calls = _answer(monkeypatch, RuntimeError("must not run"))

        await CaseKeyDraftService(db).extract(draft.id, owner.organization_id)

        await db.refresh(row)
        assert (row.status, row.error) == ("failed", KEY_GONE)
        calls.assert_not_awaited()

    async def test_a_requester_who_may_no_longer_edit_fails_the_draft(
        self, db, monkeypatch
    ) -> None:
        owner = await _owner(db)
        builder = await _member(db, owner.organization_id, OrgRoleName.BUILDER)
        dataset, case = await _case(db, owner)
        draft = await CaseKeyDraftService(db).start(builder, dataset.id, case.case_id)
        member = await db.scalar(
            select(OrganizationMember).where(OrganizationMember.user_id == builder.user_id)
        )
        assert member is not None
        member.role = OrgRoleName.VIEWER.value
        await db.flush()
        calls = _answer(monkeypatch, RuntimeError("must not run"))

        await CaseKeyDraftService(db).extract(draft.id, owner.organization_id)

        row = await db.get(CaseKeyDraft, draft.id)
        assert row is not None
        assert row.status == "failed" and row.error
        calls.assert_not_awaited()

    async def test_a_reference_answer_removed_since_fails_the_draft(self, db, monkeypatch) -> None:
        owner = await _owner(db)
        _, case, draft = await _started(db, owner)
        revision = await db.get(DatasetCase, case.id)
        assert revision is not None
        revision.reference_answer = "  "
        await db.flush()
        calls = _answer(monkeypatch, RuntimeError("must not run"))

        await CaseKeyDraftService(db).extract(draft.id, owner.organization_id)

        row = await db.get(CaseKeyDraft, draft.id)
        assert row is not None
        assert (row.status, row.error) == ("failed", NO_REFERENCE)
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
        await drafts_module.settle_lost(draft.id, owner.organization_id)
        await drafts_module.extract_case_keys(uuid.uuid4(), owner.organization_id)

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


class TestRevisions:
    async def test_a_draft_from_an_earlier_reference_answer_is_not_offered(self, db) -> None:
        owner = await _owner(db)
        dataset, case, _ = await _started(db, owner)
        service, datasets = CaseKeyDraftService(db), DatasetService(db)

        await datasets.update_case(owner, dataset.id, case.case_id, DatasetCaseUpdate(tags=["vat"]))
        assert (await service.get(owner, dataset.id, case.case_id)).status == "running"

        await datasets.update_case(
            owner, dataset.id, case.case_id, DatasetCaseUpdate(reference_answer="Invoice INV-9")
        )
        with pytest.raises(NotFoundError):
            await service.get(owner, dataset.id, case.case_id)

    async def test_a_job_whose_reference_answer_changed_meanwhile_lists_nothing(
        self, db, monkeypatch
    ) -> None:
        owner = await _owner(db)
        dataset, case, draft = await _started(db, owner)
        await DatasetService(db).update_case(
            owner, dataset.id, case.case_id, DatasetCaseUpdate(reference_answer="Invoice INV-9")
        )
        calls = _answer(monkeypatch, RuntimeError("must not run"))

        await CaseKeyDraftService(db).extract(draft.id, owner.organization_id)

        row = await db.get(CaseKeyDraft, draft.id, populate_existing=True)
        assert row is not None
        assert (row.status, row.error, row.keys) == ("failed", drafts_module.REFERENCE_CHANGED, [])
        calls.assert_not_awaited()


class TestActivity:
    async def test_an_extractor_run_reads_as_a_key_draft_of_its_dataset(self, db) -> None:
        owner = await _owner(db)
        dataset, _, draft = await _started(db, owner)
        extractor = Agent(
            organization_id=owner.organization_id,
            slug=f"key-extractor-{uuid.uuid4().hex[:8]}",
            name="Key extractor",
            kind=AgentKind.EXTRACTOR.value,
        )
        db.add(extractor)
        await db.flush()
        run = AgentRun(
            organization_id=owner.organization_id,
            agent_id=extractor.id,
            user_id=owner.user_id,
            status="completed",
            started_at=datetime.now(UTC),
        )
        db.add(run)
        await db.flush()
        await case_key_draft_repo.finish(
            db,
            draft.id,
            organization_id=owner.organization_id,
            status=KeyDraftStatus.READY,
            finished_at=datetime.now(UTC),
            run_id=run.id,
        )

        origins = await AgentRunnerService(db).origins(owner, [run.id])

        assert origins[run.id].model_dump(exclude_none=True) == {
            "kind": "key_drafts",
            "agent_name": "Key extractor",
            "dataset_id": dataset.id,
        }


class TestForgetting:
    """The extractor's run read the reference answer; it keeps it no longer than the draft."""

    @pytest.mark.parametrize("how", _WAYS)
    async def test_every_way_a_draft_goes_forgets_its_run(self, db, how) -> None:
        owner = await _owner(db)
        dataset, case, draft = await _started(db, owner)
        run = await _remembered(db, owner)
        await case_key_draft_repo.finish(
            db,
            draft.id,
            organization_id=owner.organization_id,
            status=KeyDraftStatus.READY,
            finished_at=datetime.now(UTC),
            run_id=run.id,
        )

        await _gone(db, how, owner, dataset, case)

        assert await db.get(CaseKeyDraft, draft.id, populate_existing=True) is None
        assert await _forgotten(db, run)
        assert await db.get(AgentRun, run.id) is not None

    @pytest.mark.parametrize("how", _WAYS)
    async def test_a_draft_gone_while_its_job_ran_ends_the_job_quietly(
        self, db, monkeypatch, how
    ) -> None:
        owner = await _owner(db)
        dataset, case, draft = await _started(db, owner)
        run = await _remembered(db, owner)

        async def answered(*_: object, **__: object) -> SystemAgentResult:
            await _gone(db, how, owner, dataset, case)
            return SystemAgentResult(output=ExtractedKeys(keys=[]), run=run)

        monkeypatch.setattr(SystemAgentRunner, "run", AsyncMock(side_effect=answered))

        await CaseKeyDraftService(db).extract(draft.id, owner.organization_id)

        assert await db.get(CaseKeyDraft, draft.id, populate_existing=True) is None
        assert await _forgotten(db, run)
        if how == "replaced":
            fresh = (await db.execute(select(CaseKeyDraft))).scalar_one()
            assert (fresh.status, fresh.run_id) == ("running", None)

    async def test_a_refused_run_of_a_draft_gone_meanwhile_is_forgotten(
        self, db, monkeypatch
    ) -> None:
        owner = await _owner(db)
        dataset, case, draft = await _started(db, owner)
        run = await _remembered(db, owner)

        async def refused(*_: object, **__: object) -> SystemAgentResult:
            await _gone(db, "dismissed", owner, dataset, case)
            raise SystemAgentRunError(
                message="over budget", run_id=run.id, status="budget_exceeded"
            )

        monkeypatch.setattr(SystemAgentRunner, "run", AsyncMock(side_effect=refused))

        await CaseKeyDraftService(db).extract(draft.id, owner.organization_id)

        assert await _forgotten(db, run)


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


def test_kept_keys_stop_at_the_keys_a_check_may_hold() -> None:
    document = " ".join(f"V{number}" for number in range(MAX_KEYS + 5))
    keys = [DocumentKey(key=f"K{number}", value=f"V{number}") for number in range(MAX_KEYS + 5)]

    assert len(kept_keys(document, keys)) == MAX_KEYS
