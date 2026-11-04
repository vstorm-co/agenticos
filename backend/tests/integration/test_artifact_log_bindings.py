"""A published page bound to a workflow's log, against a real database.

The second kind of page query, beside a table's: it resolves at publish with the access of
the person behind the run (and, for a change, of the page's owner), is frozen as ids, is
read with the owner's access on every load and only after the owner's consent, and reads
nothing - with a reason - once the owner may no longer view the workflow or the step is
gone. It is never on a public link.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent, AgentVersion
from app.db.models.artifact import Artifact, ArtifactMediaType, ArtifactVersion
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_log_entry import WorkflowLogEntry
from app.db.models.workflow_run import WorkflowRun, WorkflowRunMode
from app.repositories import artifact_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.artifact import (
    ArtifactBinding,
    BindingRequest,
    LogDay,
    WorkflowLogBinding,
    WorkflowLogData,
    WorkflowLogDisclosure,
    WorkflowLogParts,
    WorkflowLogRequest,
    stored_binding,
)
from app.services import artifact as artifacts
from app.services.artifact import ArtifactService
from app.services.artifact_bindings import (
    Refused,
    check_bindings,
    fingerprint,
    reresolve,
)
from app.services.artifact_log_bindings import parts_of
from app.services.file_storage import LocalFileStorage
from tests.integration.virtual_table_support import ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[LocalFileStorage]:
    local = LocalFileStorage(tmp_path)
    with (
        patch("app.services.artifact.get_file_storage", return_value=local),
        patch("app.services.file_storage.get_file_storage", return_value=local),
    ):
        yield local


@dataclass
class _World:
    """An organization with a boss and Olga, a workflow of Olga's with two steps and a page."""

    db: AsyncSession
    org: Organization
    boss: AuthContext
    olga: AuthContext
    agent: Agent
    workflow: Workflow
    run: WorkflowRun
    mail: uuid.UUID
    sms: uuid.UUID
    numbers: int = 0
    page_id: uuid.UUID | None = None
    bound: list[uuid.UUID] = field(default_factory=list)
    """The workflows the agent's Workflows capability binds."""

    async def bind_agent(self, *workflows: Workflow) -> None:
        """The agent's current spec binds exactly these in its Workflows capability."""
        spec = AgentSpec(
            name="Reporter",
            capabilities=[
                {"id": "workflows", "config": {"workflow_ids": [str(w.id) for w in workflows]}}
            ],
        )
        number = len((await self.db.execute(select(AgentVersion))).all()) + 1
        version = AgentVersion(
            id=uuid.uuid4(),
            agent_id=self.agent.id,
            organization_id=self.org.id,
            version=number,
            spec=spec.model_dump(mode="json"),
        )
        self.db.add(version)
        await self.db.flush()
        self.agent.current_version_id = version.id
        await self.db.flush()
        self.bound = [w.id for w in workflows]

    async def viewer(self, level: Any = None) -> AuthContext:
        """A member holding `level` on the page (read by default) - and nothing else."""
        from app.db.models.resource_grant import GrantLevel
        from app.repositories import resource_grant_repo
        from app.services.access import ARTIFACT

        person = await self.member()
        if self.page_id is None:
            self.page_id = (
                await artifact_repo.create(
                    self.db,
                    organization_id=self.org.id,
                    owner_user_id=self.olga.user_id,
                    agent_id=self.agent.id,
                    environment_id=None,
                    name="live-log",
                    title="Live log",
                )
            ).id
        await resource_grant_repo.upsert(
            self.db,
            organization_id=self.org.id,
            subject_user_id=person.user_id,
            resource_type=ARTIFACT.key,
            resource_id=self.page_id,
            level=level or GrantLevel.READ,
        )
        return person

    async def member(self, role: str = "member") -> AuthContext:
        user = await make_user(self.db)
        self.db.add(OrganizationMember(organization_id=self.org.id, user_id=user.id, role=role))
        await self.db.flush()
        return AuthContext(user_id=user.id, organization_id=self.org.id, role=role)

    async def line(
        self,
        *,
        outcome: str = "out",
        step: uuid.UUID | None = None,
        label: str = "Mail",
        message: str = "hello",
        is_test: bool = False,
        at: datetime | None = None,
        workflow: Workflow | None = None,
        run: WorkflowRun | None = None,
    ) -> WorkflowLogEntry:
        target = workflow or self.workflow
        entry = WorkflowLogEntry(
            organization_id=target.organization_id,
            workflow_id=target.id,
            run_id=(run or self.run).id,
            node_instance_id=step or self.mail,
            step_label=label,
            outcome=outcome,
            status="failed" if outcome == "error" else "succeeded",
            message=message,
            is_test=is_test,
            is_pinned=False,
            created_at=at or datetime.now(UTC),
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    def ask(self, **fields: Any) -> WorkflowLogRequest:
        return WorkflowLogRequest(
            kind="workflow_log", workflow=fields.pop("workflow", self.workflow.id), **fields
        )

    async def check(
        self,
        request: WorkflowLogRequest | BindingRequest,
        *,
        name: str = "log",
        person: AuthContext | None = None,
        owner: AuthContext | str | None = "person",
        previous: list[Any] | None = None,
    ) -> Any:
        who = person or self.olga
        [checked] = await check_bindings(
            self.db,
            requested={name: request},
            previous=previous or [],
            person=who,
            owner=who if owner == "person" else owner,
            grants={},
            workflow_ids=self.bound,
        )
        return checked

    async def bind(self, **fields: Any) -> WorkflowLogBinding:
        checked = await self.check(self.ask(**fields))
        assert checked.problem is None, checked.problem
        assert isinstance(checked.binding, WorkflowLogBinding)
        return checked.binding

    async def consent(self, version: ArtifactVersion) -> None:
        """The owner's consent to `version`, under the membership they hold now."""
        membership = await self.db.scalar(
            select(OrganizationMember.id).where(
                OrganizationMember.organization_id == self.org.id,
                OrganizationMember.user_id == self.olga.user_id,
            )
        )
        version.consent_state = "consented"
        version.consented_at = datetime.now(UTC)
        version.consented_by_membership_id = membership
        await self.db.flush()

    async def publish(
        self,
        *bindings: WorkflowLogBinding,
        body: str = "<p>v1</p>",
        consented: bool = False,
    ) -> ArtifactVersion:
        """A version reading `bindings`, as a publish leaves it - consented when asked."""
        if self.page_id is None:
            self.page_id = (
                await artifact_repo.create(
                    self.db,
                    organization_id=self.org.id,
                    owner_user_id=self.olga.user_id,
                    agent_id=self.agent.id,
                    environment_id=None,
                    name="live-log",
                    title="Live log",
                )
            ).id
        self.numbers += 1
        version = await artifact_repo.create_version(
            self.db,
            artifact_id=self.page_id,
            number=self.numbers,
            media_type=ArtifactMediaType.HTML.value,
            size_bytes=1,
            sha256=f"{self.numbers:064d}",
            storage_path=f"artifacts/{self.page_id}/{self.numbers}.html",
            run_id=None,
            bindings=[binding.model_dump(mode="json") for binding in bindings],
            consent={
                "query_fingerprint": fingerprint(bindings),
                "consent_state": "pending" if bindings else "not_needed",
            },
        )
        if consented:
            await self.consent(version)
        return version

    async def data(
        self, version: ArtifactVersion, viewer: AuthContext | None = None
    ) -> dict[str, Any]:
        assert self.page_id is not None
        read = await ArtifactService(self.db).data(viewer or self.olga, self.page_id, version.id)
        return dict(read.bindings)

    async def publish_with(
        self,
        bindings: dict[str, Any] | None,
        *,
        by: AuthContext | None = None,
        body: str = "<p>v1</p>",
    ) -> artifacts.PublishedArtifact:
        person = by or self.olga
        published = await artifacts.publish_with(
            self.db,
            organization_id=self.org.id,
            agent_id=self.agent.id,
            owner_user_id=self.olga.user_id,
            run_id=None,
            name="tool",
            title="Tool",
            media_type=ArtifactMediaType.HTML,
            data=body.encode(),
            run_person=person.user_id,
            bindings=bindings,
            workflow_ids=frozenset(self.bound),
        )
        self.page_id = published.artifact_id
        return published


async def _world(db: AsyncSession) -> _World:
    boss_user = await make_user(db)
    org = await make_org(db, owner=boss_user)
    boss = ctx_for(boss_user, org)
    olga_user = await make_user(db)
    db.add(OrganizationMember(organization_id=org.id, user_id=olga_user.id, role="member"))
    await db.flush()
    olga = ctx_for(olga_user, org, role="member")
    agent = Agent(
        organization_id=org.id,
        name="Reporter",
        created_by_user_id=olga_user.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
    )
    db.add(agent)
    await db.flush()
    mail, sms = uuid.uuid4(), uuid.uuid4()
    workflow, run = await _workflow(db, org, olga_user.id, "Order intake", mail, sms)
    world = _World(db, org, boss, olga, agent, workflow, run, mail, sms)
    await world.bind_agent(workflow)
    return world


async def _workflow(
    db: AsyncSession,
    org: Organization,
    owner_id: uuid.UUID,
    name: str,
    mail: uuid.UUID,
    sms: uuid.UUID,
) -> tuple[Workflow, WorkflowRun]:
    graph = {
        "nodes": [{"id": str(mail), "label": "Mail"}, {"id": str(sms), "label": "Text"}],
    }
    workflow = Workflow(
        id=uuid.uuid4(),
        organization_id=org.id,
        owner_user_id=owner_id,
        slug=f"wf-{uuid.uuid4().hex[:8]}",
        name=name,
        status=WorkflowStatus.PUBLISHED.value,
        visibility=Visibility.PRIVATE.value,
        draft_graph=graph,
    )
    db.add(workflow)
    await db.flush()
    run = await workflow_run_repo.create_run(
        db,
        organization_id=org.id,
        workflow_id=workflow.id,
        workflow_version_id=None,
        draft_graph_snapshot=graph,
        mode=WorkflowRunMode.TEST.value,
        triggered_by="api",
        public_origin=False,
        execution_principal_user_id=owner_id,
        budget_limit=None,
        node_count=2,
        deadline_at=None,
        root_run_id=None,
        causation_run_id=None,
        visited_trigger_ids=[],
        depth=0,
        started_at=datetime.now(UTC),
        run_input=None,
    )
    return workflow, run


class TestResolvingAtPublish:
    async def test_a_workflow_by_name_and_a_step_by_label_resolve_to_ids(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)

        checked = await world.check(
            WorkflowLogRequest(kind="workflow_log", workflow="Order intake", step="Mail", lines=20)
        )

        assert checked.problem is None
        assert checked.changed is True
        assert checked.binding == WorkflowLogBinding(
            name="log",
            workflow_id=world.workflow.id,
            node_instance_id=world.mail,
            lines=20,
        )
        assert checked.disclosure == WorkflowLogDisclosure(
            workflow="Order intake",
            filters=["test runs left out", "only the step Mail"],
            reads="the newest 20 lines, newest first",
        )

    async def test_a_step_by_id_and_per_day_with_its_filters_are_worded(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)

        checked = await world.check(
            world.ask(
                step=str(world.sms),
                outcomes=["error", "error", "a"],
                run="abcd",
                include_test=True,
                per_day=True,
                days=30,
                tz="Europe/Warsaw",
            )
        )

        assert checked.binding is not None
        assert checked.binding.outcomes == ["error", "a"]
        assert checked.disclosure == WorkflowLogDisclosure(
            workflow="Order intake",
            filters=[
                "test runs included",
                "only the step Text",
                "left by error or a",
                "only the run abcd",
            ],
            reads="the number of lines per day over 30 days, in Europe/Warsaw",
        )

    async def test_per_day_counts_days_in_utc_unless_a_zone_is_asked_for(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)

        binding = await world.bind(per_day=True, days=7)

        assert (binding.days, binding.tz, binding.lines) == (7, "UTC", None)

    async def test_a_workflow_by_id_given_as_text_and_a_step_known_only_to_the_draft(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        added = uuid.uuid4()
        world.workflow.draft_graph = {
            "nodes": [{"id": str(added), "label": "Added"}, {"id": "not-an-id"}]
        }
        await db.flush()

        checked = await world.check(
            world.ask(workflow=str(world.workflow.id), step="Added", lines=1)
        )

        assert checked.problem is None
        assert checked.binding.node_instance_id == added

    async def test_a_step_of_the_live_version_still_resolves_after_the_draft_moved_on(
        self, db: AsyncSession
    ) -> None:
        from app.db.models.workflow import WorkflowVersion

        world = await _world(db)
        version = WorkflowVersion(
            id=uuid.uuid4(),
            workflow_id=world.workflow.id,
            organization_id=world.org.id,
            version=1,
            graph={"nodes": [{"id": str(world.mail), "label": "Mail"}]},
        )
        db.add(version)
        await db.flush()
        world.workflow.current_version_id = version.id
        world.workflow.draft_graph = {}
        await db.flush()

        checked = await world.check(world.ask(step="Mail", lines=1))

        assert checked.problem is None

    @pytest.mark.parametrize(
        ("fields", "message"),
        [
            ({}, "Binding log: ask for either `lines` (the newest N) or `per_day`, not both."),
            (
                {"lines": 5, "per_day": True, "days": 7},
                "Binding log: ask for either `lines` (the newest N) or `per_day`, not both.",
            ),
            ({"lines": 501}, "Binding log: `lines` is at most 500; this one asks for 501."),
            ({"per_day": True}, "Binding log: `per_day` needs `days`: 7, 30 or 90."),
            ({"lines": 5, "days": 7}, "Binding log: `days` and `tz` belong to `per_day`."),
            ({"lines": 5, "tz": "UTC"}, "Binding log: `days` and `tz` belong to `per_day`."),
            (
                {"per_day": True, "days": 7, "tz": "Mars/Base"},
                "Binding log: `tz` is not an IANA time zone name, such as Europe/Warsaw.",
            ),
            (
                {"lines": 5, "run": "xyz"},
                "Binding log: `run` is a run id, or its first 4 or more characters.",
            ),
        ],
    )
    async def test_bad_filters_and_limits_are_refused_in_words(
        self, db: AsyncSession, fields: dict[str, Any], message: str
    ) -> None:
        world = await _world(db)

        checked = await world.check(world.ask(**fields))

        assert checked.binding is None
        assert checked.problem == message

    async def test_an_unknown_workflow_and_one_the_person_may_not_view_read_the_same(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        private, _ = await _workflow(
            db, world.org, world.boss.user_id, "Payroll", uuid.uuid4(), uuid.uuid4()
        )

        unknown = await world.check(world.ask(workflow=uuid.uuid4(), lines=5))
        hidden = await world.check(world.ask(workflow=private.id, lines=5))
        hidden_by_name = await world.check(world.ask(workflow="Payroll", lines=5))

        assert unknown.problem is not None and "not found" in unknown.problem
        assert hidden.problem == (
            f"Binding log: Workflow {str(private.id)!r} not found. "
            "Take its id from `list_workflows`."
        )
        assert hidden_by_name.problem == (
            "Binding log: Workflow 'Payroll' not found. Take its id from `list_workflows`."
        )
        assert "Payroll" not in (unknown.problem + hidden.problem)

    async def test_two_workflows_with_one_name_are_told_to_use_the_id(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        twin, _ = await _workflow(
            db, world.org, world.olga.user_id, "Order intake", uuid.uuid4(), uuid.uuid4()
        )
        world.bound.append(twin.id)

        checked = await world.check(world.ask(workflow="Order intake", lines=5))

        assert (
            checked.problem
            == "Binding log: Several workflows are named 'Order intake'; give the id."
        )

    async def test_another_organizations_workflow_is_not_found(self, db: AsyncSession) -> None:
        world = await _world(db)
        other_user = await make_user(db)
        other_org = await make_org(db, owner=other_user)
        foreign, _ = await _workflow(
            db, other_org, other_user.id, "Order intake", uuid.uuid4(), uuid.uuid4()
        )

        by_id = await world.check(world.ask(workflow=foreign.id, lines=5))
        by_name = await world.check(world.ask(workflow="Order intake", lines=5))

        assert by_id.problem is not None and "not found" in by_id.problem
        assert by_name.problem is None  # this organization's own, never the other's
        assert by_name.binding.workflow_id == world.workflow.id

    async def test_an_unknown_and_an_ambiguous_step_are_refused(self, db: AsyncSession) -> None:
        world = await _world(db)
        world.workflow.draft_graph = {
            "nodes": [
                {"id": str(uuid.uuid4()), "label": "Twin"},
                {"id": str(uuid.uuid4()), "label": "Twin"},
            ]
        }
        await db.flush()

        unknown = await world.check(world.ask(step="Nope", lines=5))
        twin = await world.check(world.ask(step="Twin", lines=5))

        assert unknown.problem == (
            "Binding log: 'Order intake' has no step 'Nope', by id, label or name."
        )
        assert twin.problem == (
            "Binding log: Several steps of 'Order intake' are called 'Twin'; give the id."
        )

    async def test_a_bad_binding_name_is_refused_before_anything_is_looked_up(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)

        checked = await world.check(world.ask(lines=5), name="Bad Name")
        reserved = await world.check(world.ask(lines=5), name="constructor")

        assert checked.problem == "Binding name 'Bad Name' must match `^[a-z_][a-z0-9_]{0,63}$`."
        assert reserved.problem == "Binding name constructor is reserved; choose another."

    async def test_a_changed_binding_must_be_viewable_by_the_pages_owner_too(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        mine, _ = await _workflow(
            db, world.org, world.boss.user_id, "Boss only", uuid.uuid4(), uuid.uuid4()
        )
        world.bound.append(mine.id)
        # The person behind the run is the boss, who sees everything; the page is Olga's.
        gone = await world.check(
            world.ask(workflow=mine.id, lines=5), person=world.boss, owner=world.olga
        )
        nobody = await world.check(
            world.ask(workflow=mine.id, lines=5), person=world.boss, owner=None
        )
        same = await world.check(world.ask(lines=5), person=world.boss, owner=world.olga)

        assert gone.problem == (
            "Binding log: the page's owner can't view 'Boss only', and a page's data is "
            "read with its owner's access."
        )
        assert nobody.problem == (
            "Binding log: the page's owner is no longer an active member, and a page's "
            "data is read with its owner's access."
        )
        assert same.problem is None  # Olga's own workflow


class TestWhatAChangeIs:
    async def test_the_same_request_is_unchanged_and_another_filter_is_a_change(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        stored = await world.bind(lines=10)

        same = await world.check(world.ask(lines=10), previous=[stored])
        more = await world.check(world.ask(lines=11), previous=[stored])
        other_kind = await world.check(
            BindingRequest(table=uuid.uuid4(), fields={}), previous=[stored]
        )

        assert same.changed is False
        assert more.changed is True
        assert other_kind.problem is not None

    async def test_the_fingerprint_changes_with_every_part_of_the_binding(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        base = await world.bind(lines=10)
        variants = [
            await world.bind(lines=11),
            await world.bind(lines=10, step="Mail"),
            await world.bind(lines=10, outcomes=["error"]),
            await world.bind(lines=10, run="abcd"),
            await world.bind(lines=10, include_test=True),
            await world.bind(per_day=True, days=7),
            await world.bind(per_day=True, days=30),
            await world.bind(per_day=True, days=7, tz="Europe/Warsaw"),
        ]

        prints = {fingerprint([base])} | {fingerprint([v]) for v in variants}

        assert len(prints) == len(variants) + 1
        assert fingerprint([base]) == fingerprint([base.model_copy()])


class TestStoredShape:
    async def test_a_table_binding_stored_before_there_were_kinds_loads_and_dumps_unchanged(
        self,
    ) -> None:
        table_id, column_id = uuid.uuid4(), uuid.uuid4()
        old = {
            "name": "orders",
            "table_id": str(table_id),
            "filters": [],
            "sort": {"by": "created_at", "direction": "asc"},
            "limit": 100,
            "fields": {"status": str(column_id)},
            "reach": {"tables": {str(table_id): {str(column_id): 1}}, "named_by": {}},
        }

        loaded = stored_binding(old)

        assert isinstance(loaded, ArtifactBinding)
        assert loaded.kind == "table"
        assert "kind" not in loaded.model_dump(mode="json")
        assert fingerprint([loaded]) == fingerprint([stored_binding(old)])

    async def test_a_log_binding_round_trips_with_its_kind(self) -> None:
        binding = WorkflowLogBinding(name="log", workflow_id=uuid.uuid4(), lines=5)

        dumped = binding.model_dump(mode="json")

        assert dumped["kind"] == "workflow_log"
        assert stored_binding(dumped) == binding

    async def test_a_request_without_a_kind_is_a_table_query_and_one_with_it_is_a_log(
        self,
    ) -> None:
        from pydantic import TypeAdapter

        from app.schemas.artifact import AnyBindingRequest

        adapter = TypeAdapter(AnyBindingRequest)

        table = adapter.validate_python({"table": str(uuid.uuid4()), "fields": {"a": "A"}})
        log = adapter.validate_python({"kind": "workflow_log", "workflow": "W", "lines": 3})

        assert isinstance(table, BindingRequest)
        assert isinstance(log, WorkflowLogRequest)
        assert adapter.validate_python(table) is table


class TestPublishing:
    async def test_a_publish_stores_the_resolved_binding_and_echoes_it_in_words(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)

        published = await world.publish_with(
            {"log": world.ask(workflow="Order intake", per_day=True, days=7)}
        )

        version = await artifact_repo.latest_version(db, published.artifact_id)
        assert version is not None
        assert version.bindings == [
            {
                "kind": "workflow_log",
                "name": "log",
                "workflow_id": str(world.workflow.id),
                "node_instance_id": None,
                "outcomes": [],
                "run": None,
                "include_test": False,
                "lines": None,
                "days": 7,
                "tz": "UTC",
            }
        ]
        assert published.bindings["log"] == WorkflowLogDisclosure(
            workflow="Order intake",
            filters=["test runs left out"],
            reads="the number of lines per day over 7 days, in UTC",
        )

    async def test_a_publish_naming_a_workflow_the_person_cannot_view_is_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        private, _ = await _workflow(
            db, world.org, world.boss.user_id, "Payroll", uuid.uuid4(), uuid.uuid4()
        )

        with pytest.raises(BadRequestError, match="not found"):
            await world.publish_with({"log": world.ask(workflow=private.id, lines=5)})

    async def test_a_page_with_a_public_link_refuses_a_log_binding(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish_with(None)
        artifact = await db.get(Artifact, world.page_id)
        assert artifact is not None
        artifact.public_key = "k" * 32
        await db.flush()

        with pytest.raises(BadRequestError) as refused:
            await world.publish_with({"orders": world.ask(lines=5)})

        assert refused.value.message.startswith(
            "Binding orders: A page that reads a workflow's log"
        )
        assert "public link" in refused.value.message

    async def test_a_page_that_reads_a_log_refuses_a_public_link(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish_with(
            {"orders": world.ask(lines=5), "a_week": world.ask(per_day=True, days=7)}
        )

        with pytest.raises(BadRequestError) as refused:
            await ArtifactService(db).set_public_link(world.olga, world.page_id)

        assert refused.value.message.startswith("Binding a_week, orders: A page that reads")
        artifact = await db.get(Artifact, world.page_id)
        assert artifact is not None and artifact.public_key is None

    async def test_a_public_link_cannot_pin_a_version_that_reads_a_log(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        from app.schemas.artifact import ArtifactPublicLinkUpdate

        world = await _world(db)
        await world.publish_with({"orders": world.ask(lines=5)})
        [version] = (
            await db.execute(
                select(ArtifactVersion).where(ArtifactVersion.artifact_id == world.page_id)
            )
        ).scalars()
        await world.consent(version)

        with pytest.raises(BadRequestError) as refused:
            await ArtifactService(db).update_public_link(
                world.olga,
                world.page_id,
                ArtifactPublicLinkUpdate(pinned_version_id=version.id),
            )

        assert "public link" in refused.value.message

    async def test_a_page_without_logs_still_takes_a_public_link(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish_with(None)

        detail = await ArtifactService(db).set_public_link(world.olga, world.page_id)

        assert detail.public_link is not None

    async def test_a_run_with_nobody_behind_it_cannot_bind_a_log(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)

        with pytest.raises(BadRequestError, match="Only a run acting for a member"):
            await artifacts.publish_with(
                db,
                organization_id=world.org.id,
                agent_id=world.agent.id,
                owner_user_id=world.olga.user_id,
                run_id=None,
                name="tool",
                title="Tool",
                media_type=ArtifactMediaType.HTML,
                data=b"<p>x</p>",
                run_person=None,
                bindings={"log": world.ask(lines=5)},
            )


class TestReading:
    async def test_lines_arrive_newest_first_after_consent_and_not_before(
        self, db: AsyncSession
    ) -> None:
        from app.db.models.resource_grant import GrantLevel

        world = await _world(db)
        viewer = await world.viewer(GrantLevel.EDIT)
        now = datetime.now(UTC)
        for index in range(3):
            await world.line(message=f"line {index}", at=now - timedelta(minutes=3 - index))
        version = await world.publish(await world.bind(lines=2))

        before = (await world.data(version, viewer))["log"]
        assert (before.status, before.reason, before.records) == (
            "unavailable",
            "awaiting_consent",
            [],
        )

        await world.consent(version)
        served = (await world.data(version, viewer))["log"]

        assert isinstance(served, WorkflowLogData)
        assert served.status == "ok"
        assert [r["message"] for r in served.records or []] == ["line 2", "line 1"]
        assert set(served.records[0]) == {
            "id",
            "created_at",
            "step",
            "outcome",
            "status",
            "message",
            "run_id",
        }
        assert served.records[0]["step"] == "Mail"
        assert served.records[0]["run_id"] == str(world.run.id)
        assert (served.count, served.truncated, served.limit) == (2, True, "records")
        assert served.days is None

    async def test_every_viewer_reads_what_the_owner_may_whatever_their_own_access(
        self, db: AsyncSession
    ) -> None:
        from app.db.models.resource_grant import GrantLevel
        from app.repositories import resource_grant_repo
        from app.services.access import ARTIFACT

        world = await _world(db)
        viewer = await world.member()
        await world.line(message="private to the workflow")
        version = await world.publish(await world.bind(lines=5), consented=True)
        await resource_grant_repo.upsert(
            db,
            organization_id=world.org.id,
            subject_user_id=viewer.user_id,
            resource_type=ARTIFACT.key,
            resource_id=world.page_id,
            level=GrantLevel.READ,
        )

        served = (await world.data(version, viewer))["log"]

        assert served.status == "ok"
        assert [r["message"] for r in served.records] == ["private to the workflow"]

    async def test_test_runs_are_left_out_unless_the_binding_asks_for_them(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        await world.line(message="real")
        await world.line(message="rehearsal", is_test=True)

        plain = await world.publish(await world.bind(lines=5), consented=True)
        assert [r["message"] for r in (await world.data(plain))["log"].records] == ["real"]

        both = await world.publish(await world.bind(lines=5, include_test=True), consented=True)
        assert sorted(r["message"] for r in (await world.data(both))["log"].records) == [
            "real",
            "rehearsal",
        ]

    async def test_a_step_an_outcome_and_a_run_narrow_the_lines_and_a_several_port_line_matches_each(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        _, other_run = await _workflow(
            db, world.org, world.olga.user_id, "Scratch", world.mail, world.sms
        )
        await world.line(outcome="out", message="mail out")
        await world.line(outcome="error", message="mail error")
        await world.line(outcome="a, b", message="two ways", step=world.sms, label="Text")
        await world.line(outcome="b", message="b of the other", step=world.sms, label="Text")
        await world.line(outcome="out", message="in a run of its own", run=other_run)

        async def messages(**fields: Any) -> list[str]:
            version = await world.publish(await world.bind(lines=9, **fields), consented=True)
            return sorted(r["message"] for r in (await world.data(version))["log"].records)

        assert await messages(step="Text") == ["b of the other", "two ways"]
        assert await messages(outcomes=["a", "error"]) == ["mail error", "two ways"]
        assert await messages(run=str(other_run.id)[:8]) == ["in a run of its own"]

    async def test_per_day_counts_every_day_of_the_window_by_outcome(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        noon = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
        await world.line(outcome="out", at=noon)
        await world.line(outcome="out", at=noon)
        await world.line(outcome="error", at=noon - timedelta(days=2))
        await world.line(outcome="out", at=noon - timedelta(days=40))  # outside 7 days
        version = await world.publish(await world.bind(per_day=True, days=7), consented=True)

        served = (await world.data(version))["log"]

        assert isinstance(served, WorkflowLogData)
        assert served.status == "ok"
        assert served.records is None
        assert (served.window_days, served.tz, served.total, served.count) == (7, "UTC", 3, 7)
        assert served.days is not None and len(served.days) == 7
        by_day = {day.day: day.counts for day in served.days}
        today = datetime.now(UTC).date()
        assert by_day[today.isoformat()] in ({"out": 2}, {})  # `noon` is today or just past
        assert by_day[(noon - timedelta(days=2)).date().isoformat()] == {"error": 1}
        assert served.days == sorted(served.days, key=lambda d: d.day)
        assert isinstance(served.days[0], LogDay)

    async def test_the_lines_are_cut_to_the_pages_byte_budget(self, db: AsyncSession) -> None:
        world = await _world(db)
        for index in range(4):
            await world.line(message=f"{index}" * 300)
        version = await world.publish(await world.bind(lines=4), consented=True)

        with patch("app.services.artifact.settings.ARTIFACT_DATA_MAX_BYTES", 1500):
            served = (await world.data(version))["log"]

        assert served.status == "ok"
        assert 0 < served.count < 4
        assert (served.truncated, served.limit) == (True, "bytes")

    async def test_the_record_limit_of_the_deployment_cuts_the_lines(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        for index in range(3):
            await world.line(message=str(index))
        version = await world.publish(await world.bind(lines=3), consented=True)

        with patch("app.services.artifact_log_bindings.settings.ARTIFACT_DATA_MAX_RECORDS", 1):
            served = (await world.data(version))["log"]

        assert (served.count, served.truncated, served.limit) == (1, True, "records")

    async def test_a_log_with_no_lines_is_an_empty_ok(self, db: AsyncSession) -> None:
        world = await _world(db)
        version = await world.publish(await world.bind(lines=3), consented=True)

        served = (await world.data(version))["log"]

        assert (served.status, served.records, served.count, served.truncated) == (
            "ok",
            [],
            0,
            False,
        )

    async def test_another_organizations_lines_are_never_read(self, db: AsyncSession) -> None:
        world = await _world(db)
        other_user = await make_user(db)
        other_org = await make_org(db, owner=other_user)
        foreign, foreign_run = await _workflow(
            db, other_org, other_user.id, "Order intake", uuid.uuid4(), uuid.uuid4()
        )
        await world.line(message="ours")
        await world.line(message="theirs", workflow=foreign, run=foreign_run)
        version = await world.publish(await world.bind(lines=9), consented=True)

        served = (await world.data(version))["log"]

        assert [r["message"] for r in served.records] == ["ours"]

    async def test_mixed_with_a_table_the_page_serves_both_kinds(self, db: AsyncSession) -> None:
        world = await _world(db)
        await world.line()
        version = await world.publish(await world.bind(lines=3), consented=True)

        data = await world.data(version)

        assert set(data) == {"log"}
        assert data["log"].kind == "workflow_log"


class TestWhenTheLogCannotBeRead:
    async def test_an_owner_who_loses_the_workflow_makes_it_unavailable_with_a_reason(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        viewer = await world.member(role="viewer")
        version = await world.publish(await world.bind(lines=3), consented=True)
        world.workflow.owner_user_id = world.boss.user_id  # private to the boss now
        await db.flush()

        as_owner = (await world.data(version, world.olga))["log"]

        assert as_owner.status == "unavailable"
        assert as_owner.reason == "creator_lost_access"
        assert as_owner.records == []
        assert viewer is not None

    async def test_a_viewer_who_may_not_edit_is_told_no_reason(self, db: AsyncSession) -> None:
        from app.db.models.resource_grant import GrantLevel
        from app.repositories import resource_grant_repo
        from app.services.access import ARTIFACT

        world = await _world(db)
        viewer = await world.member()
        version = await world.publish(await world.bind(per_day=True, days=7), consented=True)
        await resource_grant_repo.upsert(
            db,
            organization_id=world.org.id,
            subject_user_id=viewer.user_id,
            resource_type=ARTIFACT.key,
            resource_id=world.page_id,
            level=GrantLevel.READ,
        )
        world.workflow.owner_user_id = world.boss.user_id
        await db.flush()

        told_nothing = (await world.data(version, viewer))["log"]
        editor_told = (await world.data(version, world.olga))["log"]

        assert (told_nothing.status, told_nothing.reason) == ("unavailable", None)
        assert told_nothing.records is None and told_nothing.days == []
        assert editor_told.reason == "creator_lost_access"

    async def test_a_step_gone_from_the_workflow_makes_it_source_changed(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        version = await world.publish(await world.bind(lines=3, step="Mail"), consented=True)
        world.workflow.draft_graph = {"nodes": [{"id": str(world.sms), "label": "Text"}]}
        await db.flush()

        served = (await world.data(version))["log"]

        assert (served.status, served.reason, served.changed) == (
            "unavailable",
            "source_changed",
            "step",
        )

    async def test_a_workflow_that_is_gone_makes_it_unavailable(self, db: AsyncSession) -> None:
        world = await _world(db)
        version = await world.publish(await world.bind(lines=3), consented=True)
        await db.delete(world.workflow)
        await db.flush()

        served = (await world.data(version))["log"]

        assert (served.status, served.reason) == ("unavailable", "creator_lost_access")

    async def test_a_page_whose_owner_left_serves_nothing(self, db: AsyncSession) -> None:
        world = await _world(db)
        version = await world.publish(await world.bind(lines=3), consented=True)
        olga = await db.get(User, world.olga.user_id)
        assert olga is not None
        olga.is_active = False
        await db.flush()

        served = (await world.data(version, world.boss))["log"]

        assert (served.status, served.reason) == ("unavailable", "creator_gone")

    async def test_a_version_that_is_not_current_serves_nothing(self, db: AsyncSession) -> None:
        world = await _world(db)
        first = await world.publish(await world.bind(lines=3), consented=True)
        await world.publish(await world.bind(lines=4), consented=True)

        served = (await world.data(first))["log"]

        assert (served.status, served.reason) == ("unavailable", "not_current")

    async def test_the_public_page_never_reads_a_log(self, db: AsyncSession) -> None:
        from app.services.artifact_public_data import PublicReads

        world = await _world(db)
        await world.line()
        version = await world.publish(await world.bind(lines=3), consented=True)
        artifact = await db.get(Artifact, world.page_id)
        assert artifact is not None
        from app.services.artifact_consent import Served

        served = await ArtifactService(db)._read_page(
            artifact,
            version,
            Served(version=version, data=True, latest=True),
            can_edit=True,
            current=True,
            shared=PublicReads(artifact.id, version, uuid.uuid4()),
        )

        assert (served["log"].status, served["log"].reason) == ("unavailable", "public_link")

    async def test_reading_only_the_reasons_loads_no_lines(self, db: AsyncSession) -> None:
        world = await _world(db)
        await world.line()
        lines = await world.publish(await world.bind(lines=3), consented=True)
        days = await world.publish(await world.bind(per_day=True, days=7), consented=True)

        first = await ArtifactService(db).data(world.olga, world.page_id, lines.id, rows=False)
        second = await ArtifactService(db).data(world.olga, world.page_id, days.id, rows=False)

        assert first.bindings["log"].status == "unavailable"  # `lines` is no longer current
        assert second.bindings["log"].status == "ok"
        assert second.bindings["log"].total == 0

    async def test_reading_only_the_reasons_of_a_current_lines_binding_loads_none(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        await world.line()
        version = await world.publish(await world.bind(lines=3), consented=True)

        read = await ArtifactService(db).data(world.olga, world.page_id, version.id, rows=False)

        assert (read.bindings["log"].status, read.bindings["log"].records) == ("ok", [])


class TestRestoring:
    async def test_a_log_binding_is_kept_when_the_restorer_and_owner_may_view_the_workflow(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        binding = await world.bind(lines=5, step="Mail")

        kept = await reresolve(
            db, binding, person=world.olga, owner=world.olga, workflow_ids=world.bound
        )

        assert kept == binding

    async def test_it_is_refused_for_a_restorer_who_cannot_view_the_workflow(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        binding = await world.bind(lines=5)
        stranger = await world.member()

        refused = await reresolve(
            db, binding, person=stranger, owner=world.olga, workflow_ids=world.bound
        )

        assert refused == Refused(
            "Binding log reads a workflow you can't view, or that the agent no longer has "
            "bound in its Workflows capability.",
            forbidden=True,
        )

    async def test_it_is_refused_when_the_workflow_is_gone(self, db: AsyncSession) -> None:
        world = await _world(db)
        binding = await world.bind(lines=5)
        await db.delete(world.workflow)
        await db.flush()

        refused = await reresolve(
            db, binding, person=world.olga, owner=world.olga, workflow_ids=world.bound
        )

        assert isinstance(refused, Refused) and refused.forbidden

    async def test_it_is_refused_when_the_step_is_gone(self, db: AsyncSession) -> None:
        world = await _world(db)
        binding = await world.bind(lines=5, step="Mail")
        world.workflow.draft_graph = {"nodes": []}
        await db.flush()

        refused = await reresolve(
            db, binding, person=world.olga, owner=world.olga, workflow_ids=world.bound
        )

        assert refused == Refused(
            "Binding log reads a step 'Order intake' no longer has.", forbidden=True
        )

    async def test_it_is_refused_when_the_owner_cannot_view_the_workflow(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        binding = await world.bind(lines=5)
        other_owner = await world.member()

        refused = await reresolve(
            db, binding, person=world.olga, owner=other_owner, workflow_ids=world.bound
        )

        assert isinstance(refused, Refused)
        assert "the page's owner can't view 'Order intake'" in refused.message

    async def test_a_page_with_a_public_link_cannot_restore_a_version_that_reads_a_log(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish_with({"orders": world.ask(lines=5)})
        await world.publish_with(None, body="<p>v2</p>")
        artifact = await db.get(Artifact, world.page_id)
        assert artifact is not None
        artifact.public_key = "k" * 32
        await db.flush()
        first = await artifact_repo.get_version_by_number(db, world.page_id, 1)
        assert first is not None

        with pytest.raises(BadRequestError) as refused:
            await ArtifactService(db).restore_version(world.olga, world.page_id, first.id)

        assert refused.value.message.endswith("So this version can't be restored.")

    async def test_a_version_that_reads_a_log_restores_on_a_private_page(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish_with({"orders": world.ask(lines=5)})
        await world.publish_with(None, body="<p>v2</p>")
        first = await artifact_repo.get_version_by_number(db, world.page_id, 1)
        assert first is not None

        restored = await ArtifactService(db).restore_version(world.olga, world.page_id, first.id)

        assert restored is not None
        latest = await artifact_repo.latest_version(db, world.page_id)
        assert latest is not None and latest.bindings[0]["kind"] == "workflow_log"


class TestWordsForTheOwner:
    async def test_the_disclosure_words_each_log_binding_and_the_workflow_it_reads(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        version = await world.publish(
            await world.bind(lines=20, step="Mail", outcomes=["error"]),
        )

        shown = await ArtifactService(db).disclosure(world.olga, world.page_id, version.id)

        assert shown.problem is None
        assert shown.bindings["log"] == WorkflowLogDisclosure(
            workflow="Order intake",
            filters=["test runs left out", "only the step Mail", "left by error"],
            reads="the newest 20 lines, newest first",
        )
        parts = shown.parts["log"]
        assert isinstance(parts, WorkflowLogParts)
        assert (parts.workflow, parts.step, parts.outcomes, parts.mode, parts.lines) == (
            "Order intake",
            "Mail",
            ["error"],
            "lines",
            20,
        )
        assert shown.tables == []

    async def test_a_step_no_longer_in_the_workflow_is_worded_by_its_id(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        version = await world.publish(await world.bind(lines=5, step="Mail"))
        world.workflow.draft_graph = {}
        await db.flush()

        shown = await ArtifactService(db).disclosure(world.olga, world.page_id, version.id)

        parts = shown.parts["log"]
        assert isinstance(parts, WorkflowLogParts) and parts.step == str(world.mail)

    async def test_an_owner_who_cannot_view_the_workflow_blocks_confirming_it(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        version = await world.publish(await world.bind(per_day=True, days=30))
        world.workflow.owner_user_id = world.boss.user_id
        await db.flush()

        by_boss = await ArtifactService(db).disclosure(world.boss, world.page_id, version.id)
        by_olga = await ArtifactService(db).disclosure(world.olga, world.page_id, version.id)

        assert by_boss.problem is not None
        assert "can't view 1 of the workflows whose log it reads" in by_boss.problem
        # An administrator may still read the words the owner can no longer see.
        assert by_boss.bindings["log"].workflow == "Order intake"
        assert by_olga.problem is not None and by_olga.bindings == {}

    async def test_a_workflow_nobody_may_view_is_left_out_of_the_words(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        version = await world.publish(await world.bind(lines=5))
        await db.delete(world.workflow)
        await db.flush()

        shown = await ArtifactService(db).disclosure(world.boss, world.page_id, version.id)

        assert shown.bindings == {} and shown.parts == {}
        assert shown.problem is not None

    async def test_the_review_of_a_changed_log_binding_widens(self, db: AsyncSession) -> None:
        from app.services.artifact_request_service import ArtifactRequestService

        world = await _world(db)
        await world.publish(await world.bind(lines=10), consented=True)
        changed = await world.publish(await world.bind(lines=10, include_test=True))

        review = await ArtifactRequestService(db).review(world.olga, world.page_id, changed.id)

        [binding] = review.bindings
        assert (binding.name, binding.change, binding.effect) == ("log", "changed", "widens")
        [change] = binding.changes
        assert (change.aspect, change.effect) == ("log", "widens")
        assert isinstance(change.before, WorkflowLogParts) and not change.before.include_test
        assert isinstance(change.after, WorkflowLogParts) and change.after.include_test
        assert review.widens is True

    async def test_the_review_of_an_unchanged_log_binding_lists_it_as_unchanged(
        self, db: AsyncSession
    ) -> None:
        from app.services.artifact_request_service import ArtifactRequestService

        world = await _world(db)
        await world.publish(await world.bind(lines=10), consented=True)
        same = await world.publish(await world.bind(lines=10))

        review = await ArtifactRequestService(db).review(world.olga, world.page_id, same.id)

        assert (review.bindings, review.unchanged, review.widens) == ([], ["log"], False)

    async def test_a_log_binding_whose_workflow_nobody_may_view_is_left_out_of_the_review(
        self, db: AsyncSession
    ) -> None:
        from app.services.artifact_request_service import ArtifactRequestService

        world = await _world(db)
        await world.publish(await world.bind(lines=10), consented=True)
        later = await world.publish(await world.bind(lines=10))
        await db.delete(world.workflow)
        await db.flush()

        review = await ArtifactRequestService(db).review(world.boss, world.page_id, later.id)

        assert review.bindings == [] and review.problem is not None


class TestTheAgentsWorkflows:
    """A log binding names a workflow the agent's spec binds, as an action does."""

    async def test_an_unbound_workflow_is_told_as_one_that_does_not_exist(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        other, _ = await _workflow(
            db, world.org, world.olga.user_id, "Unbound", uuid.uuid4(), uuid.uuid4()
        )

        unbound = await world.check(world.ask(workflow=other.id, lines=5))
        missing = await world.check(world.ask(workflow=uuid.uuid4(), lines=5))
        by_name = await world.check(world.ask(workflow="Unbound", lines=5))

        assert unbound.problem == (
            f"Binding log: Workflow {str(other.id)!r} not found. Take its id from `list_workflows`."
        )
        assert missing.problem is not None and "not found. Take its id" in missing.problem
        assert by_name.problem == (
            "Binding log: Workflow 'Unbound' not found. Take its id from `list_workflows`."
        )

    async def test_a_bound_workflow_is_accepted_once_the_agent_binds_it(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        other, _ = await _workflow(
            db, world.org, world.olga.user_id, "Later", uuid.uuid4(), uuid.uuid4()
        )
        await world.bind_agent(world.workflow, other)

        checked = await world.check(world.ask(workflow=other.id, lines=5))

        assert checked.problem is None

    async def test_a_publish_refuses_an_unbound_workflow(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        other, _ = await _workflow(
            db, world.org, world.olga.user_id, "Unbound", uuid.uuid4(), uuid.uuid4()
        )

        with pytest.raises(BadRequestError, match="not found"):
            await world.publish_with({"log": world.ask(workflow=other.id, lines=5)})

    async def test_a_restore_refuses_a_workflow_the_agent_no_longer_binds(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish_with({"orders": world.ask(lines=5)})
        await world.publish_with(None, body="<p>v2</p>")
        first = await artifact_repo.get_version_by_number(db, world.page_id, 1)
        assert first is not None
        await world.bind_agent()

        with pytest.raises(AuthorizationError) as refused:
            await ArtifactService(db).restore_version(world.olga, world.page_id, first.id)

        assert "no longer has bound" in refused.value.message
        assert refused.value.message.endswith("So this version can't be restored.")

    async def test_a_restore_refuses_when_the_pages_agent_is_gone(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish_with({"orders": world.ask(lines=5)})
        await world.publish_with(None, body="<p>v2</p>")
        first = await artifact_repo.get_version_by_number(db, world.page_id, 1)
        artifact = await db.get(Artifact, world.page_id)
        assert first is not None and artifact is not None
        artifact.agent_id = None
        await db.flush()

        with pytest.raises(AuthorizationError, match="the page's agent is gone"):
            await ArtifactService(db).restore_version(world.olga, world.page_id, first.id)


class TestSteps:
    async def test_a_step_without_a_quick_log_publishes_with_a_note(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        world.workflow.draft_graph = {
            "nodes": [
                {"id": str(world.mail), "label": "Mail", "quick_log": {"message": "x"}},
                {"id": str(world.sms), "label": "Text"},
            ]
        }
        await db.flush()

        quiet = await world.publish_with({"log": world.ask(step="Text", lines=5)})
        loud = await world.publish_with({"log": world.ask(step="Mail", lines=5)})

        assert quiet.notes == [
            "Binding log: the step 'Text' of 'Order intake' has no Quick Log, so it will "
            "read no lines until the step has one."
        ]
        assert loud.notes == []

    async def test_a_step_with_a_quick_log_only_in_the_draft_counts(self, db: AsyncSession) -> None:
        from app.db.models.workflow import WorkflowVersion

        world = await _world(db)
        version = WorkflowVersion(
            id=uuid.uuid4(),
            workflow_id=world.workflow.id,
            organization_id=world.org.id,
            version=1,
            graph={"nodes": [{"id": str(world.mail), "label": "Mail"}]},
        )
        db.add(version)
        await db.flush()
        world.workflow.current_version_id = version.id
        world.workflow.draft_graph = {
            "nodes": [{"id": str(world.mail), "quick_log": {"message": "x"}}]
        }
        await db.flush()

        checked = await world.check(world.ask(step="Mail", lines=5))

        assert checked.problem is None and checked.note is None

    async def test_a_step_with_no_label_is_found_by_its_kinds_name_when_that_is_unambiguous(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        loop, other, twin_a, twin_b = (uuid.uuid4() for _ in range(4))
        world.workflow.draft_graph = {
            "nodes": [
                {"id": str(loop), "definition_id": "control.foreach", "definition_version": 1},
                {"id": str(other), "definition_id": "loop.item", "definition_version": 1},
                {"id": str(twin_a), "definition_id": "removed.kind", "definition_version": 1},
                {"id": str(twin_b), "definition_id": "removed.kind", "definition_version": "x"},
            ]
        }
        await db.flush()

        by_kind = await world.check(world.ask(step="For each", lines=5))
        unknown = await world.check(world.ask(step="removed.kind", lines=5))
        bound = await world.bind(step=str(loop), lines=5)
        parts = await parts_of(db, bound, world.workflow)

        assert by_kind.binding is not None and by_kind.binding.node_instance_id == loop
        assert unknown.problem is not None and "has no step" in unknown.problem
        assert parts.step == "For each"

    async def test_two_unlabelled_steps_of_one_kind_are_ambiguous(self, db: AsyncSession) -> None:
        world = await _world(db)
        world.workflow.draft_graph = {
            "nodes": [
                {"id": str(uuid.uuid4()), "definition_id": "loop.item", "definition_version": 1},
                {"id": str(uuid.uuid4()), "definition_id": "loop.item", "definition_version": 1},
            ]
        }
        await db.flush()

        checked = await world.check(world.ask(step="Loop item", lines=5))

        assert checked.problem == (
            "Binding log: Several steps of 'Order intake' are called 'Loop item'; give the id."
        )


class _Mixed:
    """A table of Olga's beside her workflow's log, both on one page."""

    def __init__(self, world: _World, table: Any) -> None:
        self.world = world
        self.table = table

    @classmethod
    async def make(cls, world: _World) -> _Mixed:
        from app.db.models.resource_grant import GrantLevel
        from app.repositories import resource_grant_repo
        from app.services.access import TABLE
        from app.services.virtual_tables import VirtualTableService
        from tests.integration.virtual_table_support import orders_table

        table = await orders_table(VirtualTableService(world.db), world.boss)
        await resource_grant_repo.upsert(
            world.db,
            organization_id=world.org.id,
            subject_user_id=world.olga.user_id,
            resource_type=TABLE.key,
            resource_id=table.id,
            level=GrantLevel.READ,
        )
        return cls(world, table)

    async def bindings(self, **log: Any) -> list[Any]:
        [orders, lines] = await check_bindings(
            self.world.db,
            requested={
                "orders": BindingRequest(table=self.table.id, fields={"who": "Customer"}),
                "log": self.world.ask(**log),
            },
            previous=[],
            person=self.world.olga,
            owner=self.world.olga,
            grants={self.table.id: frozenset({"read"})},
            workflow_ids=self.world.bound,
        )
        assert orders.problem is None and lines.problem is None, (orders.problem, lines.problem)
        return [orders.binding, lines.binding]

    async def rows(self, count: int, text: str) -> None:
        from tests.integration.virtual_table_support import cid, insert_rows

        await insert_rows(
            self.world.db,
            self.table,
            [{cid(self.table, "Customer"): f"{text}{index}"} for index in range(count)],
        )


class TestBesideATable:
    async def test_a_page_serves_a_table_and_a_log_each_as_its_own_kind(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        mixed = await _Mixed.make(world)
        await mixed.rows(2, "Ann")
        await world.line(message="hello")
        version = await world.publish(*await mixed.bindings(lines=5), consented=True)

        served = await world.data(version)

        assert set(served) == {"orders", "log"}
        assert served["orders"].kind == "table"
        assert sorted(r["who"] for r in served["orders"].records) == ["Ann0", "Ann1"]
        assert served["log"].kind == "workflow_log"
        assert [r["message"] for r in served["log"].records] == ["hello"]

    async def test_the_byte_budget_is_shared_fairly_between_a_table_and_a_log(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        mixed = await _Mixed.make(world)
        await mixed.rows(6, "x" * 200)
        for index in range(6):
            await world.line(message=f"{index}" * 200)
        version = await world.publish(*await mixed.bindings(lines=6), consented=True)

        with patch("app.services.artifact.settings.ARTIFACT_DATA_MAX_BYTES", 1500):
            served = await world.data(version)

        assert (served["orders"].truncated, served["orders"].limit) == (True, "bytes")
        assert (served["log"].truncated, served["log"].limit) == (True, "bytes")
        assert 0 < served["orders"].count < 6 and 0 < served["log"].count < 6

    async def test_an_unavailable_table_leaves_the_log_working(self, db: AsyncSession) -> None:
        from app.schemas.virtual_table import ColumnInput, OptionInput, SchemaUpdate
        from app.services.virtual_tables import VirtualTableService

        world = await _world(db)
        mixed = await _Mixed.make(world)
        await world.line(message="still here")
        version = await world.publish(*await mixed.bindings(lines=5), consented=True)
        tables = VirtualTableService(db)
        current = await tables.describe_table(world.boss, mixed.table.id)
        await tables.update_schema(
            world.boss,
            current.id,
            SchemaUpdate(
                expected_version=current.schema_version,
                columns=[
                    ColumnInput(
                        id=c.id,
                        label=c.label,
                        type=c.type,
                        options=[OptionInput(id=o.id, label=o.label) for o in c.options],
                    )
                    for c in current.columns
                    if c.label != "Customer" and not c.archived
                ],
            ),
        )

        served = await world.data(version)

        assert (served["orders"].status, served["orders"].reason) == (
            "unavailable",
            "source_changed",
        )
        assert [r["message"] for r in served["log"].records] == ["still here"]

    async def test_an_owner_who_lost_tables_and_workflows_is_told_of_both(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        mixed = await _Mixed.make(world)
        version = await world.publish(*await mixed.bindings(lines=5))
        from app.repositories import resource_grant_repo
        from app.services.access import TABLE

        await resource_grant_repo.delete_for_resource(
            db,
            organization_id=world.org.id,
            resource_type=TABLE.key,
            resource_id=mixed.table.id,
        )
        world.workflow.owner_user_id = world.boss.user_id
        await db.flush()

        shown = await ArtifactService(db).disclosure(world.boss, world.page_id, version.id)

        assert shown.problem is not None
        assert "can't access 1 of the tables it uses" in shown.problem
        assert "can't view 1 of the workflows whose log it reads" in shown.problem


class TestWhoReadsWithoutConsent:
    async def test_a_role_that_does_not_view_every_workflow_awaits_consent_for_a_log(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        await world.line()
        version = await world.publish(await world.bind(lines=5))

        with_workflows = (await world.data(version, world.boss))["log"]
        with patch("app.services.artifact_consent.reads_every_workflow", return_value=False):
            without = (await world.data(version, world.boss))["log"]

        assert with_workflows.status == "ok"
        # The role is served the version and its data waits on the owner's consent.
        assert (without.status, without.reason) == ("unavailable", "awaiting_consent")

    async def test_a_page_without_a_log_is_unaffected(self, db: AsyncSession) -> None:
        world = await _world(db)
        version = await world.publish()

        with patch("app.services.artifact_consent.reads_every_workflow", return_value=False):
            read = await ArtifactService(db).data(world.boss, world.page_id, version.id)

        assert read.bindings == {}


class TestThePublicLinkAndEveryServedVersion:
    async def test_a_log_in_any_version_the_link_could_serve_refuses_it(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        await world.publish(consented=True)
        # Waiting for consent: not what the audience is served yet, but what it will be.
        await world.publish(await world.bind(lines=5))

        with pytest.raises(BadRequestError) as refused:
            await ArtifactService(db).set_public_link(world.olga, world.page_id)

        assert refused.value.message.startswith("Binding log: A page that reads")

    async def test_a_log_in_a_version_older_than_the_served_one_is_not_in_the_way(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        await world.publish(await world.bind(lines=5), consented=True)
        await world.publish(consented=True)
        await world.publish(consented=True)  # the audience's version now: no log from here

        detail = await ArtifactService(db).set_public_link(world.olga, world.page_id)
        assert detail.public_link is not None


class TestTheDaysOfAWindow:
    async def test_only_the_windows_the_log_counts_over_are_taken(self) -> None:
        from pydantic import ValidationError

        for days in (7, 30, 90):
            assert (
                WorkflowLogRequest(kind="workflow_log", workflow="W", per_day=True, days=days).days
                == days
            )
        with pytest.raises(ValidationError, match="One of 7, 30, 90"):
            WorkflowLogRequest(kind="workflow_log", workflow="W", per_day=True, days=14)
        with pytest.raises(ValidationError, match="One of 7, 30, 90"):
            WorkflowLogBinding(name="log", workflow_id=uuid.uuid4(), days=1)
