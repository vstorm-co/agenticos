"""A workflow's log alert rules against Postgres: who may write them, what they are checked
against, and when the per-minute evaluation fires one.

What is proved is what an owner relies on: a rule fires when its count reaches the
threshold and not before, once per window, never for a test run, only for the lines that
match its step, outcomes and text, and to the audience it names - the owner and the chosen
members only while they still belong. The people who may write rules are the people who may
edit the workflow, grants included, and no organization reaches another's.
"""

import asyncio
import uuid
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.notification import Notification, NotificationChannel, NotificationEventType
from app.db.models.notification_delivery import NotificationDelivery
from app.db.models.organization import OrganizationMember
from app.db.models.resource_grant import ResourceGrant
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowVersion
from app.db.models.workflow_log_alert import WorkflowLogAlertFiring, WorkflowLogAlertRule
from app.db.models.workflow_log_entry import WorkflowLogEntry
from app.repositories import workflow_log_alert as alert_repo
from app.schemas.workflow_log_alert import (
    MAX_RULES_PER_WORKFLOW,
    WorkflowLogAlertCreate,
    WorkflowLogAlertUpdate,
)
from app.services.notification_center import NotificationCenterService
from app.services.workflow_log_alerts import WorkflowLogAlertService
from app.workflows._registry import REGISTRY, register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, QuickLog, WorkflowGraph
from tests.integration.workflow_run_support import SeededRun, seed_run

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


class _Out(BaseModel):
    to: str = "ada@example.com"


@pytest.fixture
def kinds() -> Iterator[dict[str, str]]:
    """`out` leaves by one port, `branch` by `true` or `false`."""

    async def handler(config: object, node_input: object) -> NodeResult:
        return Completed[_Out](output=_Out())

    ids: dict[str, str] = {}
    for name, ports in (
        ("out", ("out",)),
        ("branch", ("true", "false")),
    ):
        kind = f"test.logalert-{name}-{uuid.uuid4().hex[:6]}"
        register(
            NodeDefinition(
                id=kind,
                version=1,
                name=f"Kind {name}",
                category="test",
                description="Registered only for log alert tests.",
                kind="action",
                config_schema=None,
                input_schema=None,
                output_schema=_Out,
                ports=(
                    Port(id="in", label="In", kind="input", schema=None),
                    *(Port(id=port, label=port, kind="output", schema=_Out) for port in ports),
                ),
                effect_kind="write",
                retry_guarantee="none",
                handler=handler,
            )
        )
        ids[name] = kind
    yield ids
    for kind in ids.values():
        REGISTRY.pop(kind, None)


def _step(
    kind: str, label: str, *, quick_log: bool = True, outputs: tuple[str, ...] | None = None
) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=kind,
        definition_version=1,
        label=label,
        layout=NodePosition(x=0, y=0),
        quick_log=QuickLog(message="line", outputs=outputs) if quick_log else None,
    )


def _graph(*steps: NodeInstance) -> WorkflowGraph:
    return WorkflowGraph(
        entry_node_id=steps[0].id,
        nodes=steps,
        edges=[
            Edge(
                id=uuid.uuid4(),
                source_node_id=first.id,
                source_port="out",
                target_node_id=second.id,
                target_port="in",
            )
            for first, second in pairwise(steps)
        ],
    )


class Setup:
    """A workflow with two logging steps and one that does not, in an organization of its own."""

    def __init__(
        self, engine: AsyncEngine, seeded: SeededRun, mail: NodeInstance, branch: NodeInstance
    ) -> None:
        self.engine = engine
        self.seeded = seeded
        self.mail = mail
        self.branch = branch
        self.workflow_id = seeded.run.workflow_id
        self.org_id = seeded.org.id
        self.ctx = seeded.ctx

    def session(self):
        return self.seeded.factory()

    async def service_call(self, name: str, *args: Any, ctx: AuthContext | None = None) -> Any:
        async with self.session() as db:
            result = await getattr(WorkflowLogAlertService(db), name)(ctx or self.ctx, *args)
            await db.commit()
        return result

    async def create(self, ctx: AuthContext | None = None, **changes: Any) -> Any:
        body: dict[str, Any] = {
            "name": "Mail failures",
            "outcomes": ["error"],
            "threshold": 3,
            "window_minutes": 15,
            "audience": ["admins"],
            **changes,
        }
        return await self.service_call(
            "create_rule", self.workflow_id, WorkflowLogAlertCreate(**body), ctx=ctx
        )

    async def lines(
        self,
        count: int,
        *,
        outcome: str = "error",
        step: NodeInstance | None = None,
        at: datetime = NOW,
        message: str = "line",
        is_test: bool = False,
    ) -> None:
        step = step or self.mail
        async with self.session() as db:
            for _ in range(count):
                db.add(
                    WorkflowLogEntry(
                        organization_id=self.org_id,
                        workflow_id=self.workflow_id,
                        run_id=self.seeded.run.id,
                        node_instance_id=step.id,
                        step_label=step.label or "step",
                        outcome=outcome,
                        status="failed" if outcome == "error" else "succeeded",
                        message=message,
                        is_test=is_test,
                        is_pinned=False,
                        created_at=at,
                    )
                )
            await db.commit()

    async def evaluate(self, rule_id: uuid.UUID, now: datetime = NOW) -> bool:
        async with self.session() as db:
            fired = await WorkflowLogAlertService(db).evaluate(rule_id, now=now)
            await db.commit()
        return fired

    async def member(self, role: str = "member", *, org_id: uuid.UUID | None = None) -> AuthContext:
        async with self.session() as db:
            user = User(
                id=uuid.uuid4(),
                email=f"{uuid.uuid4().hex}@example.com",
                hashed_password="x",
                is_active=True,
            )
            db.add(user)
            await db.flush()
            db.add(
                OrganizationMember(
                    id=uuid.uuid4(),
                    organization_id=org_id or self.org_id,
                    user_id=user.id,
                    role=role,
                )
            )
            await db.commit()
        return AuthContext(user_id=user.id, organization_id=org_id or self.org_id, role=role)

    async def grant(self, ctx: AuthContext, level: str, workflow_id: uuid.UUID | None = None):
        async with self.session() as db:
            db.add(
                ResourceGrant(
                    organization_id=self.org_id,
                    subject_user_id=ctx.user_id,
                    resource_type="workflow",
                    resource_id=workflow_id or self.workflow_id,
                    level=level,
                )
            )
            await db.commit()

    async def rows(self, model: Any, *where: Any) -> list[Any]:
        async with self.session() as db:
            return list((await db.execute(select(model).where(*where))).scalars())

    async def told(self) -> set[uuid.UUID]:
        rows = await self.rows(Notification, Notification.event_type == "workflow_log_alert")
        return {row.recipient_user_id for row in rows}


@pytest.fixture
async def setup(engine: AsyncEngine, kinds: dict[str, str]) -> Setup:
    mail = _step(kinds["out"], "Mail")
    branch = _step(kinds["branch"], "Decide")
    quiet = _step(kinds["out"], "Quiet", quick_log=False)
    seeded = await seed_run(engine, _graph(mail, branch, quiet))
    return Setup(engine, seeded, mail, branch)


class TestWriting:
    async def test_a_rule_is_stored_and_listed_with_what_it_was_given(self, setup: Setup):
        created = await setup.create(
            node_instance_id=setup.mail.id, message_contains="smtp", enabled=False
        )

        listed = await setup.service_call("list_rules", setup.workflow_id)

        assert [item.id for item in listed.items] == [created.id]
        stored = listed.items[0]
        assert (stored.name, stored.outcomes, stored.threshold, stored.window_minutes) == (
            "Mail failures",
            ["error"],
            3,
            15,
        )
        assert stored.node_instance_id == setup.mail.id and stored.message_contains == "smtp"
        assert stored.enabled is False and stored.last_firing is None

    async def test_the_steps_of_the_draft_that_log_are_what_a_rule_is_checked_against(
        self, setup: Setup
    ):
        # `true` is the Decide step's, `out` the Mail step's: with no step named, either is known.
        await setup.create(outcomes=["true", "out", "error"])
        with pytest.raises(BadRequestError) as unknown:
            await setup.create(outcomes=["nonsense"])
        with pytest.raises(BadRequestError) as other_steps_port:
            await setup.create(node_instance_id=setup.mail.id, outcomes=["true"])

        for refused in (unknown, other_steps_port):
            fields = refused.value.details["fields"]
            assert [field["field"] for field in fields] == ["outcomes"]

    async def test_a_quick_log_that_names_some_ports_limits_the_outcomes_to_those(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        decide = _step(kinds["branch"], "Decide", outputs=("false",))
        seeded = await seed_run(engine, _graph(decide))
        narrow = Setup(engine, seeded, decide, decide)

        await narrow.create(node_instance_id=decide.id, outcomes=["false"])
        await narrow.create(node_instance_id=decide.id, outcomes=["error"])
        for step in (decide.id, None):
            with pytest.raises(BadRequestError) as refused:
                await narrow.create(node_instance_id=step, outcomes=["true"])
            assert refused.value.details["fields"][0]["field"] == "outcomes"

    async def test_a_graph_that_cannot_be_read_is_refused_not_a_server_error(self, setup: Setup):
        rule = await setup.create()
        async with setup.session() as db:
            await db.execute(
                update(Workflow)
                .where(Workflow.id == setup.workflow_id)
                .values(draft_graph={"nodes": "not a list"})
            )
            await db.commit()

        with pytest.raises(BadRequestError) as on_create:
            await setup.create()
        with pytest.raises(BadRequestError) as on_update:
            await setup.service_call(
                "update_rule",
                setup.workflow_id,
                rule.id,
                WorkflowLogAlertUpdate(outcomes=["error"]),
            )

        for refused in (on_create, on_update):
            assert "cannot be read" in refused.value.message
            assert refused.value.details == {"workflow_id": str(setup.workflow_id)}

    async def test_a_step_that_does_not_log_or_does_not_exist_is_refused(self, setup: Setup):
        quiet = next(
            node
            for node in WorkflowGraph.model_validate(
                (await setup.rows(Workflow, Workflow.id == setup.workflow_id))[0].draft_graph
            ).nodes
            if node.label == "Quiet"
        )
        for step in (quiet.id, uuid.uuid4()):
            with pytest.raises(BadRequestError) as refused:
                await setup.create(node_instance_id=step)
            assert refused.value.details["fields"][0]["field"] == "node_instance_id"

    async def test_the_live_version_counts_when_the_draft_is_empty(
        self, setup: Setup, kinds: dict[str, str]
    ):
        live = _step(kinds["branch"], "Live only")
        async with setup.session() as db:
            version = WorkflowVersion(
                workflow_id=setup.workflow_id,
                organization_id=setup.org_id,
                version=1,
                graph=_graph(live).model_dump(mode="json"),
            )
            db.add(version)
            await db.flush()
            await db.execute(
                update(Workflow)
                .where(Workflow.id == setup.workflow_id)
                .values(current_version_id=version.id, draft_graph={})
            )
            await db.commit()

        await setup.create(node_instance_id=live.id, outcomes=["false"])
        with pytest.raises(BadRequestError):
            await setup.create(node_instance_id=setup.mail.id, outcomes=["out"])

    async def test_a_step_with_no_definition_any_more_still_logs_its_errors(
        self, setup: Setup, kinds: dict[str, str]
    ):
        REGISTRY.pop(kinds["out"])

        await setup.create(node_instance_id=setup.mail.id, outcomes=["error"])
        with pytest.raises(BadRequestError):
            await setup.create(node_instance_id=setup.mail.id, outcomes=["out"])

    @pytest.mark.parametrize(
        "audience, user_ids",
        [(["chosen"], []), (["admins"], [uuid.uuid4()])],
    )
    async def test_chosen_needs_members_and_members_need_chosen(
        self, setup: Setup, audience: list[str], user_ids: list[uuid.UUID]
    ):
        with pytest.raises(BadRequestError) as refused:
            await setup.create(audience=audience, user_ids=user_ids)

        assert refused.value.details["fields"][0]["field"] == "user_ids"

    async def test_a_workflow_holds_a_bounded_number_of_rules(self, setup: Setup):
        for _ in range(MAX_RULES_PER_WORKFLOW):
            await setup.create()

        with pytest.raises(BadRequestError) as refused:
            await setup.create()

        assert str(MAX_RULES_PER_WORKFLOW) in refused.value.message

    async def test_a_change_touches_only_the_fields_sent_and_can_clear_the_step_and_the_text(
        self, setup: Setup
    ):
        rule = await setup.create(node_instance_id=setup.mail.id, message_contains="smtp")

        renamed = await setup.service_call(
            "update_rule",
            setup.workflow_id,
            rule.id,
            WorkflowLogAlertUpdate(name="Renamed", threshold=9),
        )
        cleared = await setup.service_call(
            "update_rule",
            setup.workflow_id,
            rule.id,
            WorkflowLogAlertUpdate(node_instance_id=None, message_contains=None),
        )

        assert (renamed.name, renamed.threshold, renamed.node_instance_id) == (
            "Renamed",
            9,
            setup.mail.id,
        )
        assert renamed.message_contains == "smtp" and renamed.outcomes == ["error"]
        assert cleared.node_instance_id is None and cleared.message_contains is None
        assert cleared.name == "Renamed"

    async def test_a_changed_outcome_or_step_is_checked_but_switching_off_is_not(
        self, setup: Setup
    ):
        rule = await setup.create(node_instance_id=setup.mail.id, outcomes=["out"])

        with pytest.raises(BadRequestError):
            await setup.service_call(
                "update_rule", setup.workflow_id, rule.id, WorkflowLogAlertUpdate(outcomes=["true"])
            )
        # The step is gone from the draft; the rule can still be switched off.
        async with setup.session() as db:
            await db.execute(
                update(Workflow).where(Workflow.id == setup.workflow_id).values(draft_graph={})
            )
            await db.commit()
        off = await setup.service_call(
            "update_rule", setup.workflow_id, rule.id, WorkflowLogAlertUpdate(enabled=False)
        )

        assert off.enabled is False

    async def test_a_change_to_the_audience_is_checked_against_the_stored_members(
        self, setup: Setup
    ):
        chosen = await setup.create(audience=["chosen"], user_ids=[uuid.uuid4()])
        plain = await setup.create()

        with pytest.raises(BadRequestError):
            await setup.service_call(
                "update_rule",
                setup.workflow_id,
                chosen.id,
                WorkflowLogAlertUpdate(audience=["admins"]),
            )
        with pytest.raises(BadRequestError):
            await setup.service_call(
                "update_rule",
                setup.workflow_id,
                plain.id,
                WorkflowLogAlertUpdate(user_ids=[uuid.uuid4()]),
            )
        again = await setup.service_call(
            "update_rule",
            setup.workflow_id,
            chosen.id,
            WorkflowLogAlertUpdate(audience=["owner", "chosen"]),
        )
        assert [a.value for a in again.audience] == ["owner", "chosen"]

    async def test_a_rule_is_deleted_with_its_history(self, setup: Setup):
        rule = await setup.create(threshold=1)
        await setup.lines(1)
        assert await setup.evaluate(rule.id)

        await setup.service_call("delete_rule", setup.workflow_id, rule.id)

        assert await setup.rows(WorkflowLogAlertRule) == []
        assert await setup.rows(WorkflowLogAlertFiring) == []
        with pytest.raises(NotFoundError):
            await setup.service_call("delete_rule", setup.workflow_id, rule.id)

    @pytest.mark.security
    async def test_the_audit_trail_names_the_fields_changed_and_never_what_they_say(
        self, setup: Setup
    ):
        rule = await setup.create(name="Secret rule name", message_contains="needle-in-haystack")
        await setup.service_call(
            "update_rule",
            setup.workflow_id,
            rule.id,
            WorkflowLogAlertUpdate(message_contains="another needle", threshold=7),
        )
        await setup.service_call("delete_rule", setup.workflow_id, rule.id)

        entries = {
            entry.action: entry
            for entry in await setup.rows(
                AppAdminAuditLog, AppAdminAuditLog.action.like("workflow.log_alert_%")
            )
        }

        assert set(entries) == {
            "workflow.log_alert_created",
            "workflow.log_alert_updated",
            "workflow.log_alert_deleted",
        }
        assert entries["workflow.log_alert_updated"].details == {
            "rule_id": str(rule.id),
            "fields": ["message_contains", "threshold"],
        }
        dump = str([entry.details for entry in entries.values()])
        assert "needle" not in dump and "Secret" not in dump
        assert all(entry.target_id == str(setup.workflow_id) for entry in entries.values())


class TestWhoMay:
    async def test_a_viewer_of_the_workflow_reads_the_rules_but_cannot_write_them(
        self, setup: Setup
    ):
        rule = await setup.create()
        viewer = await setup.member("viewer")
        await setup.grant(viewer, "read")

        listed = await setup.service_call("list_rules", setup.workflow_id, ctx=viewer)

        assert [item.id for item in listed.items] == [rule.id]
        with pytest.raises(NotFoundError):
            await setup.create(ctx=viewer)
        with pytest.raises(NotFoundError):
            await setup.service_call(
                "update_rule",
                setup.workflow_id,
                rule.id,
                WorkflowLogAlertUpdate(enabled=False),
                ctx=viewer,
            )
        with pytest.raises(NotFoundError):
            await setup.service_call("delete_rule", setup.workflow_id, rule.id, ctx=viewer)
        assert len(await setup.rows(WorkflowLogAlertRule)) == 1

    async def test_a_viewer_with_an_edit_grant_writes_on_that_workflow_and_nowhere_else(
        self, setup: Setup, kinds: dict[str, str]
    ):
        viewer = await setup.member("viewer")
        other = await seed_run(
            setup.engine,
            _graph(_step(kinds["out"], "Elsewhere")),
            member=(setup.seeded.principal, setup.seeded.org),
        )
        await setup.grant(viewer, "edit")

        created = await setup.create(ctx=viewer)
        changed = await setup.service_call(
            "update_rule",
            setup.workflow_id,
            created.id,
            WorkflowLogAlertUpdate(threshold=4),
            ctx=viewer,
        )
        await setup.service_call("delete_rule", setup.workflow_id, created.id, ctx=viewer)

        assert changed.threshold == 4
        with pytest.raises(NotFoundError):
            await setup.service_call(
                "create_rule",
                other.run.workflow_id,
                WorkflowLogAlertCreate(
                    name="x", outcomes=["error"], threshold=1, window_minutes=5, audience=["admins"]
                ),
                ctx=viewer,
            )

    async def test_a_member_who_cannot_see_the_workflow_is_told_it_does_not_exist(
        self, setup: Setup
    ):
        # A `member` reaches the workflows they own or are granted; this one is the owner's.
        member = await setup.member("member")

        with pytest.raises(NotFoundError):
            await setup.service_call("list_rules", setup.workflow_id, ctx=member)

    @pytest.mark.security
    async def test_another_organization_reaches_nothing_even_with_the_ids(
        self, setup: Setup, engine: AsyncEngine
    ):
        rule = await setup.create()
        outsider_seed = await seed_run(engine, _graph(_step("test.none", "x")))
        outsider = outsider_seed.ctx

        with pytest.raises(NotFoundError):
            await setup.service_call("list_rules", setup.workflow_id, ctx=outsider)
        with pytest.raises(NotFoundError):
            await setup.create(ctx=outsider)
        with pytest.raises(NotFoundError):
            await setup.service_call(
                "update_rule",
                setup.workflow_id,
                rule.id,
                WorkflowLogAlertUpdate(enabled=False),
                ctx=outsider,
            )
        with pytest.raises(NotFoundError):
            await setup.service_call("delete_rule", setup.workflow_id, rule.id, ctx=outsider)
        # Their own workflow's route with this organization's rule id finds no such rule.
        with pytest.raises(NotFoundError):
            await setup.service_call(
                "delete_rule", outsider_seed.run.workflow_id, rule.id, ctx=outsider
            )
        assert len(await setup.rows(WorkflowLogAlertRule)) == 1


class TestEvaluating:
    async def test_it_fires_at_the_threshold_and_not_one_line_before(self, setup: Setup):
        rule = await setup.create(threshold=3)
        await setup.lines(2)
        assert await setup.evaluate(rule.id) is False
        assert await setup.rows(WorkflowLogAlertFiring) == []

        await setup.lines(1)

        assert await setup.evaluate(rule.id) is True
        [firing] = await setup.rows(WorkflowLogAlertFiring)
        assert (firing.rule_id, firing.count, firing.fired_at) == (rule.id, 3, NOW)
        assert firing.window_start == NOW - timedelta(minutes=15)
        [stored] = await setup.rows(WorkflowLogAlertRule)
        assert stored.last_fired_at == NOW

    async def test_the_count_covers_the_window_and_nothing_before_it(self, setup: Setup):
        rule = await setup.create(threshold=3, window_minutes=15)
        # Exactly at the start of the window counts, a second older does not, and a line
        # written after the evaluation instant is not counted yet.
        await setup.lines(1, at=NOW - timedelta(minutes=15))
        await setup.lines(1, at=NOW - timedelta(minutes=15, seconds=1))
        await setup.lines(1, at=NOW + timedelta(seconds=1))
        await setup.lines(1, at=NOW)
        assert await setup.evaluate(rule.id) is False

        await setup.lines(1, at=NOW - timedelta(minutes=1))

        assert await setup.evaluate(rule.id) is True
        assert (await setup.rows(WorkflowLogAlertFiring))[0].count == 3

    async def test_it_fires_once_per_window_and_again_in_the_next(self, setup: Setup):
        rule = await setup.create(threshold=2, window_minutes=15)
        await setup.lines(2, at=NOW - timedelta(minutes=1))
        assert await setup.evaluate(rule.id) is True

        await setup.lines(5, at=NOW + timedelta(minutes=14))
        assert await setup.evaluate(rule.id, NOW + timedelta(minutes=1)) is False
        assert await setup.evaluate(rule.id, NOW + timedelta(minutes=14, seconds=59)) is False
        assert len(await setup.rows(WorkflowLogAlertFiring)) == 1

        # A window later the five lines written in the meantime still count: the next window.
        assert await setup.evaluate(rule.id, NOW + timedelta(minutes=15)) is True
        counts = sorted(firing.count for firing in await setup.rows(WorkflowLogAlertFiring))
        assert counts == [2, 5]

    async def test_a_quiet_next_window_does_not_fire(self, setup: Setup):
        rule = await setup.create(threshold=2)
        await setup.lines(2)
        assert await setup.evaluate(rule.id) is True

        assert await setup.evaluate(rule.id, NOW + timedelta(hours=1)) is False

    async def test_overlapping_evaluations_fire_a_rule_once(self, setup: Setup):
        rule = await setup.create(threshold=1)
        await setup.lines(1)

        results = await asyncio.gather(*(setup.evaluate(rule.id) for _ in range(4)))

        assert Counter(results) == {True: 1, False: 3}
        assert len(await setup.rows(WorkflowLogAlertFiring)) == 1
        assert (
            len(await setup.rows(Notification, Notification.event_type == "workflow_log_alert"))
            == 1
        )

    async def test_test_runs_are_never_counted(self, setup: Setup):
        rule = await setup.create(threshold=2)
        await setup.lines(5, is_test=True)
        await setup.lines(1)

        assert await setup.evaluate(rule.id) is False

    async def test_only_the_lines_that_match_the_rule_count(self, setup: Setup):
        by_outcome = await setup.create(name="outcome", threshold=2, outcomes=["true"])
        by_step = await setup.create(
            name="step", threshold=2, outcomes=["error"], node_instance_id=setup.branch.id
        )
        by_text = await setup.create(name="text", threshold=2, message_contains="TIMEOUT")
        await setup.lines(1, outcome="true", step=setup.branch)
        await setup.lines(1, outcome="false", step=setup.branch)
        await setup.lines(1, outcome="error", step=setup.mail, message="SMTP down")
        await setup.lines(1, outcome="error", step=setup.branch, message="no timeout here")
        assert [await setup.evaluate(rule.id) for rule in (by_outcome, by_step, by_text)] == [
            False,
            False,
            False,
        ]

        await setup.lines(1, outcome="true", step=setup.mail)
        await setup.lines(1, outcome="error", step=setup.branch, message="Timeout again")
        await setup.lines(1, outcome="error", step=setup.mail, message="a timeout")

        assert [await setup.evaluate(rule.id) for rule in (by_outcome, by_step, by_text)] == [
            True,
            True,
            True,
        ]

    async def test_a_line_that_left_by_several_ports_counts_for_each(self, setup: Setup):
        rule = await setup.create(threshold=2, outcomes=["false"])
        await setup.lines(1, outcome="true, false", step=setup.branch)
        await setup.lines(1, outcome="false", step=setup.branch)
        await setup.lines(1, outcome="falsehood", step=setup.branch)

        assert await setup.evaluate(rule.id) is True

    async def test_a_rule_switched_off_or_deleted_is_not_judged(self, setup: Setup):
        rule = await setup.create(threshold=1, enabled=False)
        live = await setup.create(threshold=1)
        await setup.lines(1)

        async with setup.session() as db:
            enabled = await WorkflowLogAlertService(db).due_rule_ids(now=NOW)

        assert enabled == [live.id]
        assert await setup.evaluate(rule.id) is False
        assert await setup.evaluate(uuid.uuid4()) is False
        assert await setup.rows(WorkflowLogAlertFiring) == []

    async def test_a_rule_holding_off_from_its_last_alert_is_not_even_looked_at(self, setup: Setup):
        rule = await setup.create(threshold=1, window_minutes=15)
        await setup.lines(1)
        async with setup.session() as db:
            service = WorkflowLogAlertService(db)
            assert await service.due_rule_ids(now=NOW) == [rule.id]
        await setup.evaluate(rule.id)

        async with setup.session() as db:
            service = WorkflowLogAlertService(db)
            assert await service.due_rule_ids(now=NOW + timedelta(minutes=14)) == []
            assert await service.due_rule_ids(now=NOW + timedelta(minutes=15)) == [rule.id]

    async def test_a_line_at_the_instant_of_an_alert_is_not_counted_again_by_the_next(
        self, setup: Setup
    ):
        rule = await setup.create(threshold=1, window_minutes=15)
        await setup.lines(1, at=NOW)
        assert await setup.evaluate(rule.id) is True
        later = NOW + timedelta(minutes=15)

        assert await setup.evaluate(rule.id, later) is False

        await setup.lines(1, at=NOW + timedelta(seconds=1))
        assert await setup.evaluate(rule.id, later) is True

    async def test_a_failed_notification_leaves_no_firing_so_the_next_tick_tries_again(
        self, setup: Setup
    ):
        rule = await setup.create(threshold=1)
        await setup.lines(1)

        with (
            patch(
                "app.services.workflow_log_alerts.NotificationService.workflow_log_alert",
                side_effect=RuntimeError("mail relay down"),
            ),
            pytest.raises(RuntimeError),
        ):
            await setup.evaluate(rule.id)
        assert await setup.rows(WorkflowLogAlertFiring) == []
        assert (await setup.rows(WorkflowLogAlertRule))[0].last_fired_at is None

        assert await setup.evaluate(rule.id, NOW + timedelta(minutes=1)) is True

    async def test_the_last_firing_is_listed_with_its_rule(self, setup: Setup):
        rule = await setup.create(threshold=1)
        quiet = await setup.create(name="quiet", threshold=500)
        await setup.lines(1)
        await setup.evaluate(rule.id)

        listed = await setup.service_call("list_rules", setup.workflow_id)

        by_id = {item.id: item for item in listed.items}
        assert by_id[rule.id].last_firing is not None and by_id[rule.id].last_firing.count == 1
        assert by_id[quiet.id].last_firing is None

    async def test_the_newest_of_several_firings_is_the_last_one(self, setup: Setup):
        rule = await setup.create(threshold=1, window_minutes=5)
        await setup.lines(1, at=NOW)
        await setup.evaluate(rule.id)
        await setup.lines(2, at=NOW + timedelta(minutes=6))
        await setup.evaluate(rule.id, NOW + timedelta(minutes=6))

        listed = await setup.service_call("list_rules", setup.workflow_id)

        assert listed.items[0].last_firing is not None and listed.items[0].last_firing.count == 2
        async with setup.session() as db:
            assert await alert_repo.latest_firings(db, []) == {}

    async def test_the_tables_refuse_a_threshold_or_window_outside_the_promise(self, setup: Setup):
        async with setup.session() as db:
            for threshold, window in ((0, 15), (1001, 15), (3, 7)):
                with pytest.raises(IntegrityError):
                    async with db.begin_nested():
                        db.add(
                            WorkflowLogAlertRule(
                                organization_id=setup.org_id,
                                workflow_id=setup.workflow_id,
                                name="x",
                                outcomes=["error"],
                                threshold=threshold,
                                window_minutes=window,
                                audience=["admins"],
                            )
                        )
                        await db.flush()

    async def test_a_rule_goes_with_its_workflow(self, setup: Setup):
        rule = await setup.create(threshold=1)
        await setup.lines(1)
        await setup.evaluate(rule.id)

        async with setup.session() as db:
            await db.execute(
                text("DELETE FROM workflows WHERE id = :id"), {"id": setup.workflow_id}
            )
            await db.commit()

        assert await setup.rows(WorkflowLogAlertRule) == []
        assert await setup.rows(WorkflowLogAlertFiring) == []


class TestDelivery:
    async def _fire(self, setup: Setup, **rule: Any) -> uuid.UUID:
        created = await setup.create(threshold=1, **rule)
        await setup.lines(1)
        assert await setup.evaluate(created.id) is True
        return created.id

    async def _own(self, setup: Setup, owner: AuthContext) -> None:
        async with setup.session() as db:
            await db.execute(
                update(Workflow)
                .where(Workflow.id == setup.workflow_id)
                .values(owner_user_id=owner.user_id)
            )
            await db.commit()

    async def test_admins_are_the_owners_and_admins_and_the_deployments_app_admins(
        self, setup: Setup
    ):
        admin = await setup.member("admin")
        await setup.member("member")
        await setup.member("viewer")
        async with setup.session() as db:
            app_admin = User(
                id=uuid.uuid4(),
                email=f"{uuid.uuid4().hex}@example.com",
                hashed_password="x",
                is_active=True,
                is_app_admin=True,
            )
            db.add(app_admin)
            await db.commit()

        await self._fire(setup, audience=["admins"])

        assert await setup.told() == {setup.ctx.user_id, admin.user_id, app_admin.id}

    async def test_owner_is_the_workflows_owner_alone(self, setup: Setup):
        owner = await setup.member("member")
        await self._own(setup, owner)

        await self._fire(setup, audience=["owner"])

        assert await setup.told() == {owner.user_id}

    async def test_chosen_are_the_members_named_who_still_belong(self, setup: Setup):
        stays = await setup.member("member")
        leaves = await setup.member("member")
        elsewhere = await seed_run(setup.engine, _graph(_step("test.none", "x")))
        async with setup.session() as db:
            await db.execute(
                text("DELETE FROM organization_members WHERE user_id = :id"),
                {"id": leaves.user_id},
            )
            await db.commit()

        await self._fire(
            setup,
            audience=["chosen"],
            user_ids=[stays.user_id, leaves.user_id, elsewhere.principal.id],
        )

        assert await setup.told() == {stays.user_id}

    async def test_audiences_are_merged_and_a_person_named_twice_hears_once(self, setup: Setup):
        await self._own(setup, setup.ctx)

        await self._fire(
            setup, audience=["admins", "owner", "chosen"], user_ids=[setup.ctx.user_id]
        )

        rows = await setup.rows(Notification, Notification.event_type == "workflow_log_alert")
        assert [row.recipient_user_id for row in rows] == [setup.ctx.user_id]

    async def test_a_chosen_audience_that_has_all_left_alerts_nobody_but_still_counts_as_fired(
        self, setup: Setup
    ):
        await self._fire(setup, audience=["chosen"], user_ids=[uuid.uuid4()])

        assert await setup.told() == set()
        assert len(await setup.rows(WorkflowLogAlertFiring)) == 1

    async def test_the_alert_names_the_rule_the_count_and_links_to_the_filtered_log(
        self, setup: Setup
    ):
        await self._fire(
            setup,
            name="Mail failures",
            outcomes=["error", "out"],
            node_instance_id=setup.mail.id,
            window_minutes=240,
        )

        [row] = await setup.rows(Notification, Notification.event_type == "workflow_log_alert")

        assert row.organization_id == setup.org_id
        assert row.summary == (
            "Mail failures: 1 occurrence in the log of Graph in the last 4 hours."
        )
        assert row.context_url == (
            f"/workflows/{setup.workflow_id}/logs?step={setup.mail.id}"
            f"&outcome=error&outcome=out&org={setup.org_id}"
        )
        assert row.render_context["workflow_id"] == str(setup.workflow_id)
        assert row.render_context["page_url"].endswith(row.context_url)

    async def test_a_window_under_two_hours_is_named_in_minutes(self, setup: Setup):
        await self._fire(setup, window_minutes=60)

        [row] = await setup.rows(Notification, Notification.event_type == "workflow_log_alert")

        assert row.summary.endswith("in the last 60 minutes.")

    async def test_an_email_is_queued_for_each_person_by_default(self, setup: Setup):
        admin = await setup.member("admin")

        await self._fire(setup, audience=["admins"])

        rows = await setup.rows(NotificationDelivery, NotificationDelivery.channel == "email")
        assert len(rows) == 2 and {row.status for row in rows} == {"pending"}
        notifications = await setup.rows(
            Notification, Notification.event_type == "workflow_log_alert"
        )
        assert {row.notification_id for row in rows} == {row.id for row in notifications}
        assert {row.recipient_user_id for row in notifications} == {
            setup.ctx.user_id,
            admin.user_id,
        }

    async def test_a_member_turns_the_alert_off_in_their_own_preferences(self, setup: Setup):
        admin = await setup.member("admin")
        async with setup.session() as db:
            await NotificationCenterService(db).update_preference(
                admin,
                event_type=NotificationEventType.WORKFLOW_LOG_ALERT,
                channel=NotificationChannel.IN_APP,
                enabled=False,
            )
            await db.commit()

        await self._fire(setup, audience=["admins"])

        rows = await setup.rows(Notification, Notification.event_type == "workflow_log_alert")
        in_app = {row.recipient_user_id for row in rows if row.in_app_visible}
        assert setup.ctx.user_id in in_app and admin.user_id not in in_app


class TestContentGate:
    async def _alert(self, setup: Setup) -> Notification:
        rule = await setup.create(threshold=1)
        await setup.lines(1)
        await setup.evaluate(rule.id)
        [row] = await setup.rows(Notification, Notification.event_type == "workflow_log_alert")
        return row

    async def _visible(self, setup: Setup, ctx: AuthContext, row: Notification) -> bool:
        async with setup.session() as db:
            return (await NotificationCenterService(db).gate_for(ctx, row)).visible

    async def test_a_reader_who_may_view_the_workflow_sees_the_row(self, setup: Setup):
        row = await self._alert(setup)
        viewer = await setup.member("viewer")
        await setup.grant(viewer, "read")

        assert await self._visible(setup, setup.ctx, row)
        assert await self._visible(setup, viewer, row)

    @pytest.mark.security
    async def test_a_reader_who_can_no_longer_view_the_workflow_does_not(self, setup: Setup):
        row = await self._alert(setup)
        member = await setup.member("member")
        await setup.grant(member, "read")
        assert await self._visible(setup, member, row)

        async with setup.session() as db:
            await db.execute(text("DELETE FROM resource_grants"))
            await db.commit()

        assert not await self._visible(setup, member, row)

    @pytest.mark.security
    async def test_a_workflow_that_is_gone_or_another_organizations_hides_the_row(
        self, setup: Setup, engine: AsyncEngine
    ):
        row = await self._alert(setup)
        outsider = (await seed_run(engine, _graph(_step("test.none", "x")))).ctx

        assert not await self._visible(setup, outsider, row)
        row.render_context = {"workflow_id": str(uuid.uuid4())}
        assert not await self._visible(setup, setup.ctx, row)
        row.render_context = {"workflow_id": "not-a-uuid"}
        assert not await self._visible(setup, setup.ctx, row)

    async def test_an_app_admin_sent_the_alert_as_an_admin_still_sees_it(self, setup: Setup):
        row = await self._alert(setup)
        app_admin = AuthContext(
            user_id=uuid.uuid4(), organization_id=setup.org_id, role="member", is_app_admin=True
        )

        assert await self._visible(setup, app_admin, row)


def test_a_rule_and_a_firing_say_what_they_are():
    rule = WorkflowLogAlertRule(name="Mail failures", workflow_id=uuid.uuid4())
    firing = WorkflowLogAlertFiring(rule_id=uuid.uuid4(), count=4)

    assert "Mail failures" in repr(rule) and str(rule.workflow_id) in repr(rule)
    assert "4 lines" in repr(firing) and str(firing.rule_id) in repr(firing)


def test_a_rule_with_a_window_outside_the_promise_is_refused_at_the_edge():
    with pytest.raises(ValidationError):
        WorkflowLogAlertCreate(
            name="x", outcomes=["error"], threshold=1, window_minutes=7, audience=["admins"]
        )
