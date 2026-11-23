"""Which of a dataset's keys an agent's sources cover: who may ask, what the job reads, what it keeps.

The source coverage agent is reached only through `SystemAgentRunner.run`, which
these tests stand in for; whether it refuses on budget before the model is called
is the runner's own to prove. Searching a knowledge base is stood in for too: the
tests are about what reaches the agent and the report, not about retrieval.
"""

import json
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.exceptions import (
    BadRequestError,
    NotFoundError,
    SystemAgentRunError,
    SystemAgentUnavailableError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentKind, AgentVersion
from app.db.models.agent_run import AgentRun
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.background_job import BackgroundJob
from app.db.models.context import ContextFile
from app.db.models.dataset import Dataset
from app.db.models.key_coverage_report import KeyCoverageReport
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.rag_document import RAGDocument
from app.db.models.resource_grant import Visibility
from app.db.models.skill import Skill
from app.db.models.user import User
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate
from app.schemas.key_coverage import JudgedCoverage, JudgedKey
from app.schemas.skill import SkillUpdate
from app.services import key_coverage as coverage_module
from app.services.agent_runner import AgentRunnerService
from app.services.api_key import KEY_GONE
from app.services.dataset import DatasetService
from app.services.key_coverage import (
    FAILED,
    NO_KEYS,
    NOT_PUBLISHED,
    REQUESTER_GONE,
    SEARCH_FAILED,
    STOPPED,
    UNCHECKED_SERVER,
    KeyCoverageService,
)
from app.services.skills import SkillService
from app.services.system_agent_runner import SystemAgentResult, SystemAgentRunner

pytestmark = pytest.mark.anyio

INVOICE = [
    {"key": "Invoice number", "value": "INV-7731"},
    {"key": "Due date", "value": "2026-12-01"},
]
TOTALS = [
    {"key": "invoice NUMBER", "value": "INV-7731"},
    {"key": "Total", "value": "1 234,50 PLN"},
    {"key": "Customer", "value": "Fernhill Ltd"},
]
VALUES = ["INV-7731", "2026-12-01", "1 234,50 PLN", "Fernhill Ltd"]


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


async def _member(db, organization_id: uuid.UUID) -> AuthContext:
    person = await _user(db)
    db.add(OrganizationMember(organization_id=organization_id, user_id=person.id, role="member"))
    await db.flush()
    return AuthContext(
        user_id=person.id, organization_id=organization_id, role=OrgRoleName.MEMBER.value
    )


async def _dataset(db, ctx: AuthContext, *keyed: list[dict[str, str]]) -> Dataset:
    datasets = DatasetService(db)
    dataset = await datasets.create(ctx, DatasetCreate(name=f"invoices-{uuid.uuid4().hex[:6]}"))
    for keys in keyed:
        checks = [{"type": "keys", "keys": keys}] if keys else [{"type": "contains", "value": "x"}]
        await datasets.add_case(
            ctx, dataset.id, DatasetCaseCreate(input="Write the invoice", checks=checks)
        )
    row = await db.get(Dataset, dataset.id)
    assert row is not None
    row.visibility = "org"
    await db.flush()
    return row


async def _sources(db, ctx: AuthContext) -> dict[str, list[str]]:
    org = ctx.organization_id
    bases = []
    for name, description in (("invoices", "Every invoice we issued"), ("archive", None)):
        kb = KnowledgeBase(
            organization_id=org,
            owner_user_id=ctx.user_id,
            name=name,
            description=description,
            scope="org",
            collection_name=f"kb_{name}_{uuid.uuid4().hex[:8]}",
            embedding_model="text-embedding-3-small",
            embedding_dim=1536,
            embedding_provider="openrouter",
            visibility="org",
        )
        db.add(kb)
        bases.append(kb)
    skill = Skill(
        organization_id=org,
        owner_user_id=ctx.user_id,
        visibility="org",
        name="billing",
        description="How to bill",
        content="Put the due date under the total.",
    )
    notes = ContextFile(
        organization_id=org,
        owner_user_id=ctx.user_id,
        visibility="private",
        name="notes",
        content="Customers are named on the first line.",
        mode="inject",
    )
    crm = McpConnection(
        organization_id=org,
        scope="org",
        purpose="mcp",
        name="crm",
        url="https://crm.example/mcp",
        last_tools=[
            {"name": "find_customer", "description": "Look a customer up by name"},
            {"name": "delete_customer", "description": "Delete one"},
        ],
    )
    fresh = McpConnection(
        organization_id=org, scope="org", purpose="mcp", name="fresh", url="https://f.example/mcp"
    )
    db.add_all([skill, notes, crm, fresh])
    await db.flush()
    return {
        "collection_ids": [str(kb.id) for kb in bases],
        "skill_ids": [str(skill.id)],
        "context_ids": [str(notes.id), str(uuid.uuid4())],
        "mcp_servers": [
            {
                "account": "organization",
                "connection_id": str(crm.id),
                "allowed_tools": ["find_customer"],
            },
            {"account": "organization", "connection_id": str(fresh.id)},
        ],
    }


async def _agent(db, ctx: AuthContext, *, published: bool = True, **spec) -> Agent:
    agent = Agent(
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        slug=f"writer-{uuid.uuid4().hex[:8]}",
        name="Writer",
        visibility="org",
    )
    db.add(agent)
    await db.flush()
    if published:
        version = AgentVersion(
            id=uuid.uuid4(),
            agent_id=agent.id,
            organization_id=ctx.organization_id,
            version=1,
            spec={"name": "Writer", **spec},
        )
        db.add(version)
        await db.flush()
        agent.current_version_id = version.id
        await db.flush()
    return agent


async def _run(db, ctx: AuthContext, agent: Agent) -> AgentRun:
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


def _answer(
    monkeypatch,
    output: JudgedCoverage | Callable[[str], JudgedCoverage] | Exception,
    run: AgentRun | None = None,
):
    def judged(*_: object, prompt: str, **__: object) -> SystemAgentResult:
        verdicts = output(prompt) if callable(output) else output
        return SystemAgentResult(output=verdicts, run=run)

    calls = AsyncMock(side_effect=output if isinstance(output, Exception) else judged)
    monkeypatch.setattr(SystemAgentRunner, "run", calls)
    return calls


@pytest.fixture(autouse=True)
def _runnable(monkeypatch) -> None:
    # Whether the agent could run is the runner's to prove; these are about the report.
    monkeypatch.setattr(SystemAgentRunner, "require_runnable", AsyncMock())


def _ref(prompt: str, title: str) -> str:
    """The reference the prompt gives the source headed `title`."""
    found = re.search(rf"^## (S\d+) - {re.escape(title)}$", prompt, re.MULTILINE)
    assert found is not None, title
    return found.group(1)


@pytest.fixture
def searched(monkeypatch) -> AsyncMock:
    async def search(query: str, *, kb_collection_names: list[str], **_: object) -> str:
        if "archive" in kb_collection_names[0]:
            raise RuntimeError("no embedding key")
        return f"[1] {query}: printed at the top of every invoice"

    mock = AsyncMock(side_effect=search)
    monkeypatch.setattr(coverage_module, "search_knowledge_base", mock)
    return mock


async def _started(db, ctx: AuthContext):
    dataset = await _dataset(db, ctx, INVOICE, TOTALS)
    agent = await _agent(db, ctx, **await _sources(db, ctx))
    report = await KeyCoverageService(db).start(ctx, dataset.id, agent.id)
    return dataset, agent, report


async def _complete(db, ctx: AuthContext, **spec):
    """A report on an agent whose every source the requester can read."""
    dataset = await _dataset(db, ctx, INVOICE, TOTALS)
    agent = await _agent(db, ctx, **spec)
    report = await KeyCoverageService(db).start(ctx, dataset.id, agent.id)
    return dataset, agent, report


class TestAsking:
    async def test_a_start_queues_a_running_report_as_a_job_and_audits_it(self, db) -> None:
        owner = await _owner(db)

        dataset, agent, report = await _started(db, owner)

        assert (report.status, report.items, report.dataset_version) == ("running", [], 2)
        job = (await db.execute(select(BackgroundJob))).scalar_one()
        assert (job.kind, job.payload) == (
            "report-key-coverage",
            {"report_id": str(report.id), "organization_id": str(owner.organization_id)},
        )
        audit = (
            await db.execute(
                select(AppAdminAuditLog).where(
                    AppAdminAuditLog.action == "agent.key_coverage_requested"
                )
            )
        ).scalar_one()
        assert audit.target_id == str(agent.id)
        assert audit.details == {"dataset_id": str(dataset.id), "dataset_version": 2}

    async def test_asking_again_replaces_the_pairs_report(self, db) -> None:
        owner = await _owner(db)
        dataset, agent, first = await _started(db, owner)

        second = await KeyCoverageService(db).start(owner, dataset.id, agent.id)

        ids = (await db.execute(select(KeyCoverageReport.id))).scalars().all()
        assert ids == [second.id] and second.id != first.id

    async def test_a_dataset_without_keys_is_refused(self, db) -> None:
        owner = await _owner(db)
        dataset = await _dataset(db, owner, [])
        agent = await _agent(db, owner)

        with pytest.raises(BadRequestError, match=NO_KEYS):
            await KeyCoverageService(db).start(owner, dataset.id, agent.id)

    async def test_an_agent_never_published_is_refused(self, db) -> None:
        owner = await _owner(db)
        dataset = await _dataset(db, owner, INVOICE)
        agent = await _agent(db, owner, published=False)

        with pytest.raises(BadRequestError, match=NOT_PUBLISHED):
            await KeyCoverageService(db).start(owner, dataset.id, agent.id)

    async def test_a_member_who_may_not_edit_the_agent_is_refused(self, db) -> None:
        owner = await _owner(db)
        dataset = await _dataset(db, owner, INVOICE)
        agent = await _agent(db, owner)
        member = await _member(db, owner.organization_id)

        with pytest.raises(NotFoundError):
            await KeyCoverageService(db).start(member, dataset.id, agent.id)
        assert (await db.execute(select(KeyCoverageReport))).first() is None

    async def test_another_organizations_dataset_is_not_found(self, db) -> None:
        owner, stranger = await _owner(db), await _owner(db)
        dataset = await _dataset(db, owner, INVOICE)
        agent = await _agent(db, stranger)

        with pytest.raises(NotFoundError):
            await KeyCoverageService(db).start(stranger, dataset.id, agent.id)

    async def test_an_agent_that_cannot_run_is_refused_before_anything_is_queued(
        self, db, monkeypatch
    ) -> None:
        owner = await _owner(db)
        dataset = await _dataset(db, owner, INVOICE)
        agent = await _agent(db, owner)
        refused = SystemAgentUnavailableError(
            message="'Source coverage' is over its budget", key="source_coverage", reason="budget"
        )
        monkeypatch.setattr(SystemAgentRunner, "require_runnable", AsyncMock(side_effect=refused))

        with pytest.raises(SystemAgentUnavailableError):
            await KeyCoverageService(db).start(owner, dataset.id, agent.id)
        assert (await db.execute(select(BackgroundJob))).first() is None


class TestJudging:
    async def test_the_agent_reads_labels_and_sources_never_a_value(
        self, db, monkeypatch, searched
    ) -> None:
        owner = await _owner(db)
        _, agent, report = await _started(db, owner)
        run = await _run(db, owner, agent)
        calls = _answer(
            monkeypatch,
            lambda prompt: JudgedCoverage(
                keys=[
                    JudgedKey(
                        key="invoice number",
                        verdict="covered",
                        source_ids=[_ref(prompt, "knowledge base 'invoices'"), "S99"],
                    ),
                    JudgedKey(
                        key="Due date",
                        verdict="not_covered",
                        source_ids=[_ref(prompt, "skill 'billing'")],
                        why="No",
                    ),
                    JudgedKey(key="Total", verdict="covered", why="Somewhere"),
                ]
            ),
            run,
        )

        await KeyCoverageService(db).judge(report.id, owner.organization_id)

        prompt = calls.await_args.kwargs["prompt"]
        assert not [value for value in VALUES if value in prompt]
        for label in ("Invoice number", "Due date", "Total", "Customer"):
            assert f"- {label}" in prompt
        assert "invoice NUMBER" not in prompt
        assert "printed at the top of every invoice" in prompt
        assert SEARCH_FAILED in prompt and UNCHECKED_SERVER in prompt
        assert "Tool crm_find_customer" in prompt and "delete_customer" not in prompt
        assert "Mentions 'Due date': Put the due date under the total." in prompt
        assert "Description: Every invoice we issued" in prompt
        assert "Search for 'Customer':" in prompt
        row = await db.get(KeyCoverageReport, report.id)
        assert row is not None
        await db.refresh(row)
        assert (row.status, row.run_id, row.unseen_sources) == ("ready", run.id, 1)
        assert [(item["key"], item["verdict"]) for item in row.items] == [
            ("Invoice number", "covered"),
            ("Due date", "not_covered"),
            ("Total", "unsure"),
            ("Customer", "unsure"),
        ]
        assert [source["name"] for source in row.items[0]["sources"]] == ["invoices"]
        assert row.items[1]["sources"] == []
        stored = json.dumps(row.items)
        assert '"value"' not in stored
        assert not [value for value in VALUES if value in stored]

    async def test_a_search_reads_only_the_bound_base_under_a_shared_collection_name(
        self, db, monkeypatch, searched
    ) -> None:
        owner = await _owner(db)
        dataset = await _dataset(db, owner, INVOICE)
        stranger = await _member(db, owner.organization_id)
        bound = KnowledgeBase(
            organization_id=owner.organization_id,
            owner_user_id=owner.user_id,
            name="invoices",
            scope="org",
            collection_name=f"kb_shared_{uuid.uuid4().hex[:8]}",
            embedding_model="text-embedding-3-small",
            embedding_dim=1536,
            embedding_provider="openrouter",
            visibility="org",
        )
        hidden = KnowledgeBase(
            organization_id=owner.organization_id,
            owner_user_id=stranger.user_id,
            name="salaries",
            scope="org",
            collection_name=bound.collection_name,
            embedding_model="text-embedding-3-small",
            embedding_dim=1536,
            embedding_provider="openrouter",
            visibility="private",
        )
        db.add_all([hidden, bound])
        await db.flush()
        agent = await _agent(db, owner, collection_ids=[str(bound.id)])
        report = await KeyCoverageService(db).start(owner, dataset.id, agent.id)
        _answer(monkeypatch, JudgedCoverage(keys=[]), await _run(db, owner, agent))

        await KeyCoverageService(db).judge(report.id, owner.organization_id)

        scopes = [call.kwargs["kb_vector_scopes"] for call in searched.await_args_list]
        assert scopes and all(
            set(scope) == {bound.collection_name}
            and scope[bound.collection_name].knowledge_base_id == bound.id
            for scope in scopes
        )

    async def test_a_server_reached_through_each_persons_account_is_left_unread(
        self, db, monkeypatch
    ) -> None:
        owner = await _owner(db)
        _, agent, report = await _complete(
            db, owner, mcp_servers=[{"account": "personal", "catalog_key": "notion"}]
        )
        _answer(monkeypatch, JudgedCoverage(keys=[]), await _run(db, owner, agent))

        await KeyCoverageService(db).judge(report.id, owner.organization_id)

        row = await db.get(KeyCoverageReport, report.id, populate_existing=True)
        assert row is not None
        assert (row.status, row.unseen_sources) == ("ready", 1)

    async def test_a_disabled_server_is_no_source(self, db, monkeypatch) -> None:
        owner = await _owner(db)
        off = McpConnection(
            organization_id=owner.organization_id,
            scope="org",
            purpose="mcp",
            name="retired",
            url="https://retired.example/mcp",
            is_enabled=False,
            last_tools=[{"name": "find_customer", "description": "Look a customer up"}],
        )
        db.add(off)
        await db.flush()
        _, agent, report = await _complete(
            db, owner, mcp_servers=[{"account": "organization", "connection_id": str(off.id)}]
        )
        calls = _answer(monkeypatch, JudgedCoverage(keys=[]), await _run(db, owner, agent))

        await KeyCoverageService(db).judge(report.id, owner.organization_id)

        assert "retired" not in calls.await_args.kwargs["prompt"]
        row = await db.get(KeyCoverageReport, report.id, populate_existing=True)
        assert row is not None
        assert (row.unseen_sources, row.judged_sources) == (0, [])

    async def test_a_skill_is_read_at_the_version_its_binding_names(self, db, monkeypatch) -> None:
        owner = await _owner(db)
        skills = SkillService(db)
        skill = await skills.create(
            owner,
            name="billing",
            description="How to bill",
            content="Put the due date under the total.",
            visibility=Visibility.ORG,
        )
        await skills.update(owner, skill.id, SkillUpdate(content="Bill monthly."))
        _, agent, report = await _complete(
            db,
            owner,
            skill_ids=[str(skill.id)],
            skill_bindings=[{"skill_id": str(skill.id), "version": 1}],
        )
        calls = _answer(monkeypatch, JudgedCoverage(keys=[]), await _run(db, owner, agent))

        await KeyCoverageService(db).judge(report.id, owner.organization_id)

        prompt = calls.await_args.kwargs["prompt"]
        assert "Mentions 'Due date': Put the due date under the total." in prompt
        assert "Bill monthly" not in prompt

    async def test_a_refused_model_call_keeps_its_run(self, db, monkeypatch, searched) -> None:
        owner = await _owner(db)
        _, agent, report = await _started(db, owner)
        run = await _run(db, owner, agent)
        _answer(
            monkeypatch,
            SystemAgentRunError(message="Over budget", run_id=run.id, status="budget_exceeded"),
        )

        await KeyCoverageService(db).judge(report.id, owner.organization_id)

        row = await db.get(KeyCoverageReport, report.id)
        assert row is not None
        assert (row.status, row.error, row.run_id) == ("failed", "Over budget", run.id)

    async def test_an_unexpected_failure_fails_the_report(self, db, monkeypatch, searched) -> None:
        owner = await _owner(db)
        _, _, report = await _started(db, owner)
        # The request committed the report; the job's rollback must not take it with it.
        await db.commit()
        _answer(monkeypatch, RuntimeError("provider exploded"))

        await KeyCoverageService(db).judge(report.id, owner.organization_id)

        row = await db.get(KeyCoverageReport, report.id)
        assert row is not None
        assert (row.status, row.error) == ("failed", FAILED)

    async def test_a_requester_who_left_fails_the_report(self, db, monkeypatch) -> None:
        owner = await _owner(db)
        _, _, report = await _started(db, owner)
        await db.execute(
            OrganizationMember.__table__.delete().where(OrganizationMember.user_id == owner.user_id)
        )
        calls = _answer(monkeypatch, RuntimeError("must not run"))

        await KeyCoverageService(db).judge(report.id, owner.organization_id)

        row = await db.get(KeyCoverageReport, report.id)
        assert row is not None
        assert (row.status, row.error) == ("failed", REQUESTER_GONE)
        calls.assert_not_awaited()

    async def test_a_revoked_key_fails_the_report(self, db, monkeypatch) -> None:
        owner = await _owner(db)
        _, _, report = await _started(db, owner)
        row = await db.get(KeyCoverageReport, report.id)
        assert row is not None
        row.created_by_api_key_id = uuid.uuid4()
        await db.flush()
        _answer(monkeypatch, RuntimeError("must not run"))

        await KeyCoverageService(db).judge(report.id, owner.organization_id)

        await db.refresh(row)
        assert (row.status, row.error) == ("failed", KEY_GONE)

    async def test_keys_removed_since_the_request_fail_the_report(self, db, monkeypatch) -> None:
        owner = await _owner(db)
        dataset, _, report = await _started(db, owner)
        row = await db.get(KeyCoverageReport, report.id)
        assert row is not None
        row.dataset_version = 99
        await db.flush()
        _answer(monkeypatch, RuntimeError("must not run"))

        await KeyCoverageService(db).judge(report.id, owner.organization_id)

        await db.refresh(row)
        assert (row.status, row.error) == ("failed", NO_KEYS)

    async def test_a_report_already_ended_is_left_alone(self, db, monkeypatch) -> None:
        owner = await _owner(db)
        _, _, report = await _started(db, owner)
        calls = _answer(monkeypatch, RuntimeError("must not run"))
        service = KeyCoverageService(db)
        row = await db.get(KeyCoverageReport, report.id)
        assert row is not None
        await service._fail(row.id, row.organization_id, "done")

        await service.judge(report.id, owner.organization_id)
        await coverage_module.report_key_coverage(uuid.uuid4(), owner.organization_id)

        calls.assert_not_awaited()

    async def test_a_report_replaced_while_its_job_ran_ends_the_job_quietly(
        self, db, monkeypatch, searched
    ) -> None:
        owner = await _owner(db)
        dataset, agent, report = await _started(db, owner)
        run = await _run(db, owner, agent)
        fresh = {}

        async def answered(*_: object, **__: object) -> SystemAgentResult:
            fresh["report"] = await KeyCoverageService(db).start(owner, dataset.id, agent.id)
            return SystemAgentResult(output=JudgedCoverage(keys=[]), run=run)

        monkeypatch.setattr(SystemAgentRunner, "run", AsyncMock(side_effect=answered))

        await KeyCoverageService(db).judge(report.id, owner.organization_id)

        row = (await db.execute(select(KeyCoverageReport))).scalar_one()
        assert (row.id, row.status, row.run_id) == (fresh["report"].id, "running", None)

    async def test_a_lost_job_fails_its_running_report(self, db) -> None:
        owner = await _owner(db)
        _, _, report = await _started(db, owner)
        await db.commit()

        await coverage_module.settle_lost(report.id, owner.organization_id)
        await coverage_module.settle_lost(report.id, owner.organization_id)

        row = await db.get(KeyCoverageReport, report.id)
        assert row is not None
        await db.refresh(row)
        assert (row.status, row.error) == ("failed", STOPPED)


def _kb(ctx: AuthContext, name: str) -> KnowledgeBase:
    return KnowledgeBase(
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        name=name,
        scope="org",
        collection_name=f"kb_{name}_{uuid.uuid4().hex[:8]}",
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        embedding_provider="openrouter",
        visibility="org",
    )


def _document(ctx: AuthContext, kb: KnowledgeBase) -> RAGDocument:
    return RAGDocument(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        collection_name=kb.collection_name,
        filename=f"{uuid.uuid4().hex[:6]}.md",
        filesize=4,
        filetype="md",
        storage_path="",
        status="done",
        chunk_count=1,
        ingestion_config={},
        knowledge_base_id=kb.id,
    )


class TestSourcesChanging:
    async def _judged(self, db, monkeypatch, owner, **spec):
        dataset, agent, report = await _complete(db, owner, **spec)
        _answer(
            monkeypatch,
            JudgedCoverage(keys=[JudgedKey(key="Due date", verdict="not_covered")]),
            await _run(db, owner, agent),
        )
        service = KeyCoverageService(db)
        await service.judge(report.id, owner.organization_id)
        return service, dataset, agent

    async def test_a_document_added_since_puts_the_report_out_of_date(
        self, db, monkeypatch, searched
    ) -> None:
        owner = await _owner(db)
        bound, other = _kb(owner, "invoices"), _kb(owner, "archive")
        db.add_all([bound, other])
        await db.flush()
        db.add_all([_document(owner, bound), _document(owner, other)])
        await db.flush()
        service, dataset, agent = await self._judged(
            db, monkeypatch, owner, collection_ids=[str(bound.id)]
        )

        db.add(_document(owner, other))
        await db.flush()
        read = await service.get(owner, dataset.id, agent.id)
        assert (read.current, read.sources_changed) == (True, False)
        assert await service.uncovered_labels(owner, agent.id, [dataset.id]) == {
            dataset.id: frozenset({"due date"})
        }

        db.add(_document(owner, bound))
        await db.flush()
        read = await service.get(owner, dataset.id, agent.id)
        assert (read.current, read.sources_changed) == (False, True)
        assert await service.uncovered_labels(owner, agent.id, [dataset.id]) == {}

    async def test_a_probe_that_lists_the_same_tools_leaves_the_report_current(
        self, db, monkeypatch
    ) -> None:
        owner = await _owner(db)
        crm = McpConnection(
            organization_id=owner.organization_id,
            scope="org",
            purpose="mcp",
            name="crm",
            url="https://crm.example/mcp",
            last_tools=[{"name": "find_customer", "description": "Look a customer up"}],
        )
        db.add(crm)
        await db.flush()
        service, dataset, agent = await self._judged(
            db,
            monkeypatch,
            owner,
            mcp_servers=[{"account": "organization", "connection_id": str(crm.id)}],
        )

        crm.last_checked_at = datetime.now(UTC)
        await db.flush()
        assert (await service.get(owner, dataset.id, agent.id)).current

        crm.last_tools = [*crm.last_tools, {"name": "find_invoice", "description": "By number"}]
        await db.flush()
        assert (await service.get(owner, dataset.id, agent.id)).sources_changed


class TestActivity:
    async def test_a_coverage_run_reads_as_key_coverage_of_its_dataset(
        self, db, monkeypatch, searched
    ) -> None:
        owner = await _owner(db)
        dataset, _, report = await _started(db, owner)
        judge = Agent(
            organization_id=owner.organization_id,
            slug=f"source-coverage-{uuid.uuid4().hex[:8]}",
            name="Source coverage",
            kind=AgentKind.COVERAGE.value,
        )
        db.add(judge)
        await db.flush()
        run = await _run(db, owner, judge)
        _answer(monkeypatch, JudgedCoverage(keys=[]), run)
        await KeyCoverageService(db).judge(report.id, owner.organization_id)

        origins = await AgentRunnerService(db).origins(owner, [run.id])

        assert origins[run.id].model_dump(exclude_none=True) == {
            "kind": "key_coverage",
            "agent_name": "Source coverage",
            "dataset_id": dataset.id,
        }


class TestReading:
    async def test_a_reader_who_may_not_see_a_source_gets_it_unnamed(
        self, db, monkeypatch, searched
    ) -> None:
        owner = await _owner(db)
        dataset, agent, report = await _started(db, owner)
        _answer(
            monkeypatch,
            lambda prompt: JudgedCoverage(
                keys=[
                    JudgedKey(
                        key="Customer",
                        verdict="covered",
                        source_ids=[
                            _ref(prompt, "context file 'notes'"),
                            _ref(prompt, "MCP server 'crm'"),
                        ],
                        why="W",
                    ),
                    JudgedKey(
                        key="Total",
                        verdict="covered",
                        source_ids=[_ref(prompt, "MCP server 'crm'")],
                        why="Tool",
                    ),
                    JudgedKey(key="Due date", verdict="not_covered", why="Only notes mention it"),
                ]
            ),
            await _run(db, owner, agent),
        )
        service = KeyCoverageService(db)
        await service.judge(report.id, owner.organization_id)
        member = await _member(db, owner.organization_id)

        mine = await service.get(owner, dataset.id, agent.id)
        theirs = await service.get(member, dataset.id, agent.id)

        customer = {item.key: item for item in mine.items}["Customer"]
        assert [source.name for source in customer.sources] == ["notes", "crm"]
        assert customer.why == "W"
        hidden = {item.key: item for item in theirs.items}
        assert [(s.kind, s.id, s.name) for s in hidden["Customer"].sources] == [
            ("context", None, None),
            ("mcp", hidden["Total"].sources[0].id, "crm"),
        ]
        assert hidden["Customer"].why is None
        # The judge read the notes as well; any reason may repeat them.
        assert [item.why for item in theirs.items] == [None, None, None, None]
        assert {item.key: item.why for item in mine.items}["Due date"] == "Only notes mention it"
        assert hidden["Due date"].verdict == "not_covered" and hidden["Due date"].sources == []
        assert theirs.model_dump_json().count("Fernhill") == 0

    async def test_a_pair_without_a_report_is_not_found(self, db) -> None:
        owner = await _owner(db)
        dataset = await _dataset(db, owner, INVOICE)
        agent = await _agent(db, owner)

        with pytest.raises(NotFoundError):
            await KeyCoverageService(db).get(owner, dataset.id, agent.id)

    async def test_a_report_with_no_sources_named_reads_without_its_version(self, db) -> None:
        owner = await _owner(db)
        dataset, agent, report = await _started(db, owner)

        read = await KeyCoverageService(db).get(owner, dataset.id, agent.id)

        assert (read.id, read.items) == (report.id, [])

    async def test_only_labels_no_source_holds_are_uncovered(
        self, db, monkeypatch, searched
    ) -> None:
        owner = await _owner(db)
        dataset, agent, report = await _complete(db, owner)
        _answer(
            monkeypatch,
            JudgedCoverage(keys=[JudgedKey(key="Due date", verdict="not_covered")]),
            await _run(db, owner, agent),
        )
        service = KeyCoverageService(db)
        await service.judge(report.id, owner.organization_id)

        assert await service.uncovered_labels(owner, agent.id, [dataset.id]) == {
            dataset.id: frozenset({"due date"})
        }
        assert await service.uncovered_labels(owner, agent.id, []) == {}
        assert (await service.get(owner, dataset.id, agent.id)).current

    async def test_an_incomplete_report_gives_improve_nothing(
        self, db, monkeypatch, searched
    ) -> None:
        owner = await _owner(db)
        dataset, agent, report = await _started(db, owner)
        _answer(
            monkeypatch,
            JudgedCoverage(keys=[JudgedKey(key="Due date", verdict="not_covered")]),
            await _run(db, owner, agent),
        )
        service = KeyCoverageService(db)
        await service.judge(report.id, owner.organization_id)

        read = await service.get(owner, dataset.id, agent.id)
        assert read.unseen_sources == 1
        assert {item.key: item.verdict for item in read.items}["Due date"] == "not_covered"
        assert await service.uncovered_labels(owner, agent.id, [dataset.id]) == {}

    async def test_a_report_on_an_earlier_version_or_dataset_is_out_of_date(
        self, db, monkeypatch, searched
    ) -> None:
        owner = await _owner(db)
        dataset, agent, report = await _complete(db, owner)
        _answer(
            monkeypatch,
            JudgedCoverage(keys=[JudgedKey(key="Due date", verdict="not_covered")]),
            await _run(db, owner, agent),
        )
        service = KeyCoverageService(db)
        await service.judge(report.id, owner.organization_id)
        await DatasetService(db).add_case(
            owner,
            dataset.id,
            DatasetCaseCreate(input="Another", checks=[{"type": "keys", "keys": INVOICE}]),
        )

        assert not (await service.get(owner, dataset.id, agent.id)).current
        assert await service.uncovered_labels(owner, agent.id, [dataset.id]) == {}

        report = await service.start(owner, dataset.id, agent.id)
        await service.judge(report.id, owner.organization_id)
        assert await service.uncovered_labels(owner, agent.id, [dataset.id]) == {
            dataset.id: frozenset({"due date"})
        }

        republished = AgentVersion(
            id=uuid.uuid4(),
            agent_id=agent.id,
            organization_id=owner.organization_id,
            version=2,
            spec={"name": "Writer"},
        )
        db.add(republished)
        await db.flush()
        agent.current_version_id = republished.id
        await db.flush()

        assert not (await service.get(owner, dataset.id, agent.id)).current
        assert await service.uncovered_labels(owner, agent.id, [dataset.id]) == {}
