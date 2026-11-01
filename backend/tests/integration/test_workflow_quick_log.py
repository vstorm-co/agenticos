"""A step's Quick Log, end to end: what the dispatcher writes when a step settles, and who reads it.

The graphs are driven through the real dispatcher against Postgres. What is proved is what an
author relies on: one line per settled run of the step - on success with the port it left by, on a
failure its error routes and on one that ends the run - none for a step that was skipped,
switched off, reused by a retry or left by a port the log does not name, a line that reads
nothing still settling the step and the run as ever, and the lines going with their run.
"""

import uuid
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from itertools import pairwise
from typing import Any
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.organization import OrganizationMember
from app.db.models.resource_grant import ResourceGrant, Visibility
from app.db.models.user import User
from app.db.models.workflow import Workflow
from app.db.models.workflow_log_entry import WorkflowLogEntry
from app.db.models.workflow_run import WorkflowRun, WorkflowRunMode, WorkflowRunStatus
from app.repositories import workflow_log_entry as workflow_log_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow_log_entry import LogFilters
from app.services.workflow_execution import WorkflowExecutionService
from app.services.workflow_execution.exceptions import WorkflowRunNotFoundError
from app.workflows._registry import REGISTRY, register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.contracts.policy import NodePolicy
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, QuickLog, WorkflowGraph
from tests.integration.test_workflow_error_foreach import ITEMS, _Loop
from tests.integration.workflow_run_support import SeededRun, drive, seed_member, seed_run

pytestmark = pytest.mark.anyio


class _Out(BaseModel):
    to: str
    choice: str = "true"


calls: Counter[str] = Counter()


@pytest.fixture
def kinds() -> Iterator[dict[str, str]]:
    """`ok` completes, `branch` leaves by `true` or `false`, `boom` always fails, `flaky` fails once."""
    calls.clear()

    async def ok(config: object, node_input: object) -> NodeResult:
        return Completed[_Out](output=_Out(to="ada@example.com"))

    async def boom(config: object, node_input: object) -> NodeResult:
        return Failed(
            error=WorkflowError(
                code="SMTP_DOWN", message="Cannot reach the server", details={"secret": "tok"}
            )
        )

    async def flaky(config: object, node_input: object) -> NodeResult:
        calls["flaky"] += 1
        if calls["flaky"] == 1:
            return await boom(config, node_input)
        return await ok(config, node_input)

    def routes(output: dict[str, Any] | None) -> frozenset[str]:
        return frozenset({(output or {}).get("choice", "true")})

    ids: dict[str, str] = {}
    two = (
        Port(id="true", label="T", kind="output", schema=_Out),
        Port(id="false", label="F", kind="output", schema=_Out),
    )
    one = (Port(id="out", label="Out", kind="output", schema=_Out),)
    for name, handler, ports, route in (
        ("ok", ok, one, None),
        ("boom", boom, one, None),
        ("flaky", flaky, one, None),
        ("branch", ok, two, routes),
    ):
        kind = f"test.qlog-{name}-{uuid.uuid4().hex[:6]}"
        register(
            NodeDefinition(
                id=kind,
                version=1,
                name=f"Kind {name}",
                category="test",
                description="Registered only for Quick Log tests.",
                kind="action",
                config_schema=None,
                input_schema=None,
                output_schema=_Out,
                ports=(Port(id="in", label="In", kind="input", schema=None), *ports),
                effect_kind="write",
                retry_guarantee="none",
                handler=handler,
                routes=route,
                exclusive_branches=route is not None,
            )
        )
        ids[name] = kind
    yield ids
    for kind in ids.values():
        REGISTRY.pop(kind, None)


def _step(kind: str, **extra: Any) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=kind,
        definition_version=1,
        layout=NodePosition(x=0, y=0),
        **extra,
    )


def _edge(source: NodeInstance, target: NodeInstance, port: str = "out") -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port=port,
        target_node_id=target.id,
        target_port="in",
    )


def _chain(*steps: NodeInstance) -> WorkflowGraph:
    return WorkflowGraph(
        entry_node_id=steps[0].id,
        nodes=steps,
        edges=tuple(_edge(a, b) for a, b in pairwise(steps)),
    )


async def _real(seeded: SeededRun) -> None:
    """Make the seeded run a real one; the harness seeds test runs."""
    async with seeded.factory() as db:
        await db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == seeded.run.id)
            .values(mode=WorkflowRunMode.REAL.value)
        )
        await db.commit()


async def _entries(seeded: SeededRun, run_id: uuid.UUID | None = None) -> list[WorkflowLogEntry]:
    async with seeded.factory() as db:
        rows = await db.execute(
            select(WorkflowLogEntry)
            .where(WorkflowLogEntry.run_id == (run_id or seeded.run.id))
            .order_by(WorkflowLogEntry.created_at, WorkflowLogEntry.id)
        )
        return list(rows.scalars())


class TestWhatIsWritten:
    async def test_a_step_that_completes_logs_the_port_it_left_by_and_what_it_made(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        step = _step(
            kinds["ok"],
            label="Send the mail",
            quick_log=QuickLog(message="{{step}} sent to {{to}} via {{outcome}}"),
        )
        seeded = await seed_run(engine, _chain(step, _step(kinds["ok"])))
        await _real(seeded)

        run = await drive(seeded)

        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        (entry,) = await _entries(seeded)
        assert entry.message == "Send the mail sent to ada@example.com via out"
        assert (entry.outcome, entry.status) == ("out", "succeeded")
        assert entry.step_label == "Send the mail" and entry.node_instance_id == step.id
        assert (entry.workflow_id, entry.organization_id) == (seeded.run.workflow_id, seeded.org.id)
        assert (entry.is_test, entry.is_pinned) == (False, False)

    async def test_an_unnamed_step_is_logged_under_its_name_from_the_catalog(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await seed_run(engine, _chain(_step(kinds["ok"], quick_log=QuickLog())))
        await drive(seeded)
        (entry,) = await _entries(seeded)
        assert entry.message == "Kind ok → out"

    async def test_a_test_run_flags_its_lines(self, engine: AsyncEngine, kinds: dict[str, str]):
        seeded = await seed_run(engine, _chain(_step(kinds["ok"], quick_log=QuickLog())))
        await drive(seeded)
        (entry,) = await _entries(seeded)
        assert entry.is_test is True

    async def test_a_pinned_output_is_logged_like_a_result_and_flagged(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        step = _step(
            kinds["ok"],
            quick_log=QuickLog(message="{{to}}"),
            pinned_output={"to": "pinned@example.com"},
        )
        seeded = await seed_run(engine, _chain(step, _step(kinds["ok"])))
        await drive(seeded)
        (entry,) = await _entries(seeded)
        assert (entry.message, entry.is_pinned, entry.is_test) == ("pinned@example.com", True, True)

    async def test_a_deciding_step_logs_once_with_the_port_it_chose(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        branch = _step(kinds["branch"], quick_log=QuickLog(outputs=("true", "false")))
        after = _step(kinds["ok"])
        graph = WorkflowGraph(
            entry_node_id=branch.id, nodes=(branch, after), edges=(_edge(branch, after, "true"),)
        )
        seeded = await seed_run(engine, graph)
        await drive(seeded)
        (entry,) = await _entries(seeded)
        assert entry.outcome == "true"

    async def test_a_message_that_reads_nothing_still_settles_the_step_and_the_run(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        step = _step(
            kinds["ok"], quick_log=QuickLog(message="[{{nope}}][{{a.b}}][{{error.code}}][{{to.x}}]")
        )
        seeded = await seed_run(engine, _chain(step, _step(kinds["ok"])))
        run = await drive(seeded)
        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        (entry,) = await _entries(seeded)
        assert entry.message == "[][][][]"

    async def test_a_step_without_a_quick_log_writes_nothing(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await seed_run(engine, _chain(_step(kinds["ok"]), _step(kinds["ok"])))
        await drive(seeded)
        assert await _entries(seeded) == []

    async def test_an_old_stored_graph_without_the_field_loads_and_runs(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        graph = _chain(_step(kinds["ok"]), _step(kinds["ok"]))
        stored = graph.model_dump(mode="json")
        for node in stored["nodes"]:
            del node["quick_log"]
        seeded = await seed_run(engine, WorkflowGraph.model_validate(stored))
        assert (await drive(seeded)).status == WorkflowRunStatus.SUCCEEDED.value


class TestFailures:
    async def test_a_failure_the_step_routes_is_logged_as_an_error_and_the_run_goes_on(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        boom = _step(
            kinds["boom"],
            policy=NodePolicy(on_error="route"),
            quick_log=QuickLog(message="{{outcome}} {{error.code}}: {{error.message}}"),
        )
        handler = _step(kinds["ok"])
        graph = WorkflowGraph(
            entry_node_id=boom.id, nodes=(boom, handler), edges=(_edge(boom, handler, "error"),)
        )
        seeded = await seed_run(engine, graph)

        run = await drive(seeded)

        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        (entry,) = await _entries(seeded)
        assert (entry.outcome, entry.status) == ("error", "failed")
        assert entry.message == "error SMTP_DOWN: Cannot reach the server"

    async def test_a_failure_that_ends_the_run_is_logged_and_never_shows_its_details(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        boom = _step(
            kinds["boom"],
            quick_log=QuickLog(message="{{error.code}} {{error.details}} {{error.details.secret}}"),
        )
        seeded = await seed_run(engine, _chain(boom, _step(kinds["ok"])))

        run = await drive(seeded)

        assert run.status == WorkflowRunStatus.FAILED.value
        (entry,) = await _entries(seeded)
        assert (entry.outcome, entry.status) == ("error", "failed")
        assert entry.message == "SMTP_DOWN  "
        assert "tok" not in entry.message

    async def test_a_failure_is_not_logged_when_the_log_does_not_name_error(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        boom = _step(
            kinds["boom"],
            policy=NodePolicy(on_error="route"),
            quick_log=QuickLog(outputs=("out",)),
        )
        handler = _step(kinds["ok"])
        graph = WorkflowGraph(
            entry_node_id=boom.id, nodes=(boom, handler), edges=(_edge(boom, handler, "error"),)
        )
        seeded = await seed_run(engine, graph)
        await drive(seeded)
        assert await _entries(seeded) == []


class TestAFailureThatEndsTheRun:
    async def test_is_logged_whatever_outputs_says(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        boom = _step(kinds["boom"], quick_log=QuickLog(outputs=("out",)))
        seeded = await seed_run(engine, WorkflowGraph(entry_node_id=boom.id, nodes=(boom,)))
        run = await drive(seeded)
        assert run.status == WorkflowRunStatus.FAILED.value
        (entry,) = await _entries(seeded)
        assert (entry.outcome, entry.status) == ("error", "failed")


class TestWhatIsNotWritten:
    async def test_a_port_the_log_does_not_name_writes_nothing(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        branch = _step(kinds["branch"], quick_log=QuickLog(outputs=("false",)))
        after = _step(kinds["ok"])
        graph = WorkflowGraph(
            entry_node_id=branch.id, nodes=(branch, after), edges=(_edge(branch, after, "true"),)
        )
        seeded = await seed_run(engine, graph)
        await drive(seeded)
        assert await _entries(seeded) == []

    async def test_a_step_on_the_branch_not_taken_is_skipped_and_writes_nothing(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        branch = _step(kinds["branch"])
        taken = _step(kinds["ok"])
        skipped = _step(kinds["ok"], quick_log=QuickLog())
        graph = WorkflowGraph(
            entry_node_id=branch.id,
            nodes=(branch, taken, skipped),
            edges=(_edge(branch, taken, "true"), _edge(branch, skipped, "false")),
        )
        seeded = await seed_run(engine, graph)
        assert (await drive(seeded)).status == WorkflowRunStatus.SUCCEEDED.value
        assert await _entries(seeded) == []

    async def test_a_step_switched_off_writes_nothing(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        off = _step(kinds["ok"], disabled=True, quick_log=QuickLog())
        seeded = await seed_run(engine, _chain(_step(kinds["ok"]), off, _step(kinds["ok"])))
        assert (await drive(seeded)).status == WorkflowRunStatus.SUCCEEDED.value
        assert await _entries(seeded) == []

    async def test_a_step_never_reached_writes_nothing(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        late = _step(kinds["ok"], quick_log=QuickLog())
        seeded = await seed_run(engine, _chain(_step(kinds["boom"]), late))
        assert (await drive(seeded)).status == WorkflowRunStatus.FAILED.value
        assert await _entries(seeded) == []

    async def test_a_retry_reuses_a_finished_step_without_logging_it_again_and_logs_one_that_reruns(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        first = _step(kinds["ok"], label="First", quick_log=QuickLog(message="first"))
        second = _step(kinds["flaky"], label="Second", quick_log=QuickLog(message="second"))
        seeded = await seed_run(engine, _chain(first, second))
        assert (await drive(seeded)).status == WorkflowRunStatus.FAILED.value
        assert [(e.step_label, e.outcome) for e in await _entries(seeded)] == [
            ("First", "out"),
            ("Second", "error"),
        ]

        async with seeded.factory() as db:
            retried = await WorkflowExecutionService(db).retry(seeded.ctx, seeded.run.id)
            await db.commit()
            run = await workflow_run_repo.get_run(db, retried.id, organization_id=seeded.org.id)
        again = SeededRun(
            run=run,
            graph=seeded.graph,
            principal=seeded.principal,
            org=seeded.org,
            factory=seeded.factory,
        )
        assert (await drive(again)).status == WorkflowRunStatus.SUCCEEDED.value

        assert [(e.step_label, e.outcome) for e in await _entries(again, run.id)] == [
            ("Second", "out")
        ]


class TestRetention:
    async def test_the_lines_go_with_their_run_when_retention_removes_it(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await seed_run(engine, _chain(_step(kinds["ok"], quick_log=QuickLog())))
        await drive(seeded)
        assert len(await _entries(seeded)) == 1
        now = datetime.now(UTC)
        async with seeded.factory() as db:
            workflow = await db.get(Workflow, seeded.run.workflow_id)
            assert workflow is not None
            workflow.settings = {"run_retention_days": 1}
            await db.commit()
        async with seeded.factory() as db:
            await db.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == seeded.run.id)
                .values(ended_at=now - timedelta(days=2))
            )
            await db.commit()
        async with seeded.factory() as db:
            taken = await workflow_run_repo.take_expired_runs(db, now=now, limit=10)
            await db.commit()

        assert [run_id for run_id, _paths in taken] == [seeded.run.id]
        assert await _entries(seeded) == []


class TestReading:
    async def _logged(self, engine: AsyncEngine, kinds: dict[str, str]) -> SeededRun:
        first = _step(kinds["ok"], label="Mail", quick_log=QuickLog(message="mailed {{to}}"))
        second = _step(kinds["ok"], label="Chat", quick_log=QuickLog(message="chatted"))
        seeded = await seed_run(engine, _chain(first, second))
        await drive(seeded)
        return seeded

    async def test_a_workflows_log_is_listed_newest_first_and_test_runs_only_when_asked(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        async with seeded.factory() as db:
            service = WorkflowExecutionService(db)
            hidden = await service.workflow_logs(
                seeded.ctx, seeded.run.workflow_id, filters=LogFilters()
            )
            shown = await service.workflow_logs(
                seeded.ctx,
                seeded.run.workflow_id,
                filters=LogFilters(include_test=True),
            )
        assert hidden.total == 0 and hidden.items == []
        assert [item.step_label for item in shown.items] == ["Chat", "Mail"]
        assert shown.total == 2

    async def test_the_log_is_narrowed_by_step_outcome_window_and_text_and_paged(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        mail = next(n for n in seeded.graph.nodes if n.label == "Mail")
        now = datetime.now(UTC)
        base = {"include_test": True}

        async def listed(skip: int = 0, limit: int = 50, **filters: Any) -> list[str]:
            async with seeded.factory() as db:
                page = await WorkflowExecutionService(db).workflow_logs(
                    seeded.ctx,
                    seeded.run.workflow_id,
                    filters=LogFilters(**base, **filters),
                    skip=skip,
                    limit=limit,
                )
            return [item.step_label for item in page.items]

        assert await listed(node_instance_id=mail.id) == ["Mail"]
        assert await listed(outcome=["out"]) == ["Chat", "Mail"]
        assert await listed(outcome=["error"]) == []
        assert await listed(outcome=["error", "out"]) == ["Chat", "Mail"]
        assert await listed(query="MAILED") == ["Mail"]
        assert await listed(query="100%") == []
        assert await listed(created_from=now + timedelta(days=1)) == []
        assert await listed(created_to=now + timedelta(days=1)) == ["Chat", "Mail"]
        assert await listed(created_to=now - timedelta(days=1)) == []
        assert await listed(skip=1, limit=1) == ["Mail"]

    async def test_the_log_is_narrowed_to_a_run_by_its_id_or_the_start_of_it(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        mail = next(n for n in seeded.graph.nodes if n.label == "Mail")
        run_id = str(seeded.run.id)

        async def listed(run: str, **filters: Any) -> list[str]:
            async with seeded.factory() as db:
                page = await WorkflowExecutionService(db).workflow_logs(
                    seeded.ctx,
                    seeded.run.workflow_id,
                    filters=LogFilters(include_test=True, run=run, **filters),
                )
            return [item.step_label for item in page.items]

        other = "ffffffff-ffff" if not run_id.startswith("ffff") else "00000000-0000"
        assert await listed(run_id) == ["Chat", "Mail"]
        assert await listed(run_id.upper()) == ["Chat", "Mail"]
        assert await listed(run_id[:4]) == ["Chat", "Mail"]
        assert await listed(run_id[:13].upper()) == ["Chat", "Mail"]
        assert await listed(run_id.replace("-", "")) == ["Chat", "Mail"]
        assert await listed(other) == []
        assert await listed("%%%%") == []
        assert await listed("____") == []
        assert await listed(run_id[:8], node_instance_id=mail.id) == ["Mail"]
        assert await listed(run_id[:8], outcome=["error"]) == []
        assert await listed(run_id[:8], query="chatted") == ["Chat"]

    @pytest.mark.security
    async def test_a_run_of_another_workflow_never_returns_that_workflows_lines(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        for run in (str(seeded.run.id), str(seeded.run.id)[:6]):
            async with seeded.factory() as db:
                rows, total = await workflow_log_repo.list_for_workflow(
                    db,
                    organization_id=seeded.org.id,
                    workflow_id=uuid.uuid4(),
                    filters=LogFilters(include_test=True, run=run),
                )
            assert (rows, total) == ([], 0)

    async def test_a_runs_lines_are_listed_in_the_order_they_were_written(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        async with seeded.factory() as db:
            page = await WorkflowExecutionService(db).run_logs(seeded.ctx, seeded.run.id)
            second = await WorkflowExecutionService(db).run_logs(
                seeded.ctx, seeded.run.id, skip=1, limit=1
            )
        assert [item.step_label for item in page.items] == ["Mail", "Chat"]
        assert page.total == 2 and [item.step_label for item in second.items] == ["Chat"]

    @pytest.mark.security
    async def test_another_organizations_member_gets_the_answer_for_a_run_that_is_not_there(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        async with seeded.factory() as db:
            outsider, other_org = await seed_member(db)
            await db.commit()
        outside = SeededRun(
            run=seeded.run,
            graph=seeded.graph,
            principal=outsider,
            org=other_org,
            factory=seeded.factory,
        )
        async with seeded.factory() as db:
            service = WorkflowExecutionService(db)
            with pytest.raises(NotFoundError):
                await service.workflow_logs(
                    outside.ctx,
                    seeded.run.workflow_id,
                    filters=LogFilters(include_test=True),
                )
            with pytest.raises(WorkflowRunNotFoundError):
                await service.run_logs(outside.ctx, seeded.run.id)
        async with seeded.factory() as db:
            rows, total = await workflow_log_repo.list_for_workflow(
                db,
                organization_id=other_org.id,
                workflow_id=seeded.run.workflow_id,
                filters=LogFilters(include_test=True),
            )
        assert (rows, total) == ([], 0)

    @pytest.mark.security
    async def test_a_member_who_may_not_view_the_workflow_is_refused_like_for_its_runs(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        no_access = patch(
            "app.services.workflow_execution.facade.resolve_access",
            new=AsyncMock(return_value=False),
        )
        async with seeded.factory() as db:
            service = WorkflowExecutionService(db)
            with no_access, pytest.raises(NotFoundError) as logs:
                await service.workflow_logs(
                    seeded.ctx, seeded.run.workflow_id, filters=LogFilters()
                )
            with no_access, pytest.raises(NotFoundError) as runs:
                await service.list(seeded.ctx, workflow_id=seeded.run.workflow_id)
            with no_access, pytest.raises(WorkflowRunNotFoundError):
                await service.run_logs(seeded.ctx, seeded.run.id)
        assert logs.value.message == runs.value.message


class TestWriteOrder:
    async def _write(self, seeded: SeededRun, clock: list[datetime], messages: list[str]) -> None:
        """Write one line per message in one transaction, the clock reading `clock` in turn."""
        step = seeded.graph.nodes[0]
        ticks = iter(clock)

        class _Clock:
            @staticmethod
            def now(_tz: object) -> datetime:
                return next(ticks)

        async with seeded.factory() as db:
            with patch("app.repositories.workflow_log_entry.datetime", _Clock):
                for message in messages:
                    await workflow_log_repo.create(
                        db,
                        organization_id=seeded.org.id,
                        workflow_id=seeded.run.workflow_id,
                        run_id=seeded.run.id,
                        node_instance_id=step.id,
                        step_label="Mail",
                        outcome="out",
                        status="succeeded",
                        message=message,
                        is_test=False,
                        is_pinned=False,
                    )
            await db.commit()

    async def test_a_line_that_left_by_several_ports_matches_each_and_its_own_listing(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await seed_run(engine, _chain(_step(kinds["ok"], label="Mail")))
        async with seeded.factory() as db:
            await workflow_log_repo.create(
                db,
                organization_id=seeded.org.id,
                workflow_id=seeded.run.workflow_id,
                run_id=seeded.run.id,
                node_instance_id=seeded.graph.nodes[0].id,
                step_label="Mail",
                outcome="a, b",
                status="succeeded",
                message="two ways out",
                is_test=False,
                is_pinned=False,
            )
            await db.commit()

        async def total(*outcomes: str) -> int:
            async with seeded.factory() as db:
                _, count = await workflow_log_repo.list_for_workflow(
                    db,
                    organization_id=seeded.org.id,
                    workflow_id=seeded.run.workflow_id,
                    filters=LogFilters(outcome=list(outcomes)),
                )
            return count

        assert [await total("a"), await total("b"), await total("c", "b")] == [1, 1, 1]
        # A client echoing the line's own outcome finds it, as does a part of one.
        assert [await total("a, b"), await total("c, a"), await total("c")] == [1, 1, 0]

    async def test_a_runs_lines_list_in_write_order_when_the_clock_steps_back(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await seed_run(engine, _chain(_step(kinds["ok"], label="Mail")))
        now = datetime.now(UTC)
        await self._write(
            seeded, [now, now - timedelta(seconds=5), now], ["first", "second", "third"]
        )
        async with seeded.factory() as db:
            run_lines, _ = await workflow_log_repo.list_for_run(
                db, organization_id=seeded.org.id, run_id=seeded.run.id
            )
        assert [row.message for row in run_lines] == ["first", "second", "third"]

    async def test_lines_written_in_one_instant_list_newest_first_by_write_order(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await seed_run(engine, _chain(_step(kinds["ok"], label="Mail")))
        instant = datetime.now(UTC)
        await self._write(seeded, [instant] * 3, ["first", "second", "third"])
        async with seeded.factory() as db:
            rows, _ = await workflow_log_repo.list_for_workflow(
                db,
                organization_id=seeded.org.id,
                workflow_id=seeded.run.workflow_id,
                filters=LogFilters(include_test=True),
            )
        assert [row.message for row in rows] == ["third", "second", "first"]


class TestSummary:
    async def _logged(self, engine: AsyncEngine, kinds: dict[str, str]) -> SeededRun:
        mail = _step(kinds["ok"], label="Mail", quick_log=QuickLog(message="mailed"))
        bad = _step(kinds["boom"], label="Bad", quick_log=QuickLog(message="broke"))
        seeded = await seed_run(engine, _chain(mail, bad))
        await drive(seeded)
        return seeded

    async def _summary(self, seeded: SeededRun, days: int = 7, tz: str = "UTC", **filters: Any):
        async with seeded.factory() as db:
            return await WorkflowExecutionService(db).workflow_log_summary(
                seeded.ctx,
                seeded.run.workflow_id,
                filters=LogFilters(**filters),
                days=days,
                tz=tz,
            )

    async def test_a_line_belongs_to_the_day_of_the_zone_asked_for(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        warsaw = ZoneInfo("Europe/Warsaw")
        yesterday = datetime.now(warsaw).date() - timedelta(days=1)
        # Half past midnight in Warsaw is still the day before in UTC, winter or summer.
        written = datetime.combine(yesterday, time(0, 30), tzinfo=warsaw)
        assert written.astimezone(UTC).date() != yesterday
        async with seeded.factory() as db:
            await db.execute(update(WorkflowLogEntry).values(created_at=written))
            await db.commit()
        local = await self._summary(seeded, tz="Europe/Warsaw", include_test=True)
        utc = await self._summary(seeded, include_test=True)
        assert {d.day: d.counts for d in local.by_day if d.counts} == {
            yesterday: {"out": 1, "error": 1}
        }
        assert {d.day for d in utc.by_day if d.counts} == {written.astimezone(UTC).date()}

    async def test_a_line_dated_ahead_of_the_clock_is_left_out(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        async with seeded.factory() as db:
            await db.execute(
                update(WorkflowLogEntry).values(created_at=datetime.now(UTC) + timedelta(days=3))
            )
            await db.commit()
        summary = await self._summary(seeded, include_test=True)
        assert summary.total == 0 and len(summary.by_day) == 7

    async def test_lines_are_counted_per_day_and_outcome_in_the_window(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        old = datetime.now(UTC) - timedelta(days=3, hours=1)
        async with seeded.factory() as db:
            await db.execute(
                update(WorkflowLogEntry)
                .where(WorkflowLogEntry.outcome == "error")
                .values(created_at=old)
            )
            await db.commit()
        today = datetime.now(UTC).date()
        summary = await self._summary(seeded, include_test=True)
        by_day = {day.day: day.counts for day in summary.by_day}
        assert len(summary.by_day) == 7 and summary.total == 2
        assert by_day[today] == {"out": 1}
        assert by_day[old.date()] == {"error": 1}
        assert sum(len(counts) for counts in by_day.values()) == 2
        # A narrower window leaves out what is older than it.
        async with seeded.factory() as db:
            await db.execute(
                update(WorkflowLogEntry).values(created_at=datetime.now(UTC) - timedelta(days=40))
            )
            await db.commit()
        assert (await self._summary(seeded, include_test=True)).total == 0
        assert (await self._summary(seeded, days=90, include_test=True)).total == 2

    async def test_the_filters_narrow_the_counts_and_test_runs_only_when_asked(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        mail = next(n for n in seeded.graph.nodes if n.label == "Mail")
        run_id = str(seeded.run.id)

        async def total(**filters: Any) -> int:
            return (await self._summary(seeded, **filters)).total

        assert await total() == 0
        assert await total(include_test=True) == 2
        assert await total(include_test=True, node_instance_id=mail.id) == 1
        assert await total(include_test=True, outcome=["error"]) == 1
        assert await total(include_test=True, query="BROKE") == 1
        assert await total(include_test=True, run=run_id[:8]) == 2
        assert await total(include_test=True, run="ffffffff-ffff") == 0

    @pytest.mark.security
    async def test_another_organization_cannot_count_the_log_or_see_its_lines(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        async with seeded.factory() as db:
            outsider, other_org = await seed_member(db)
            await db.commit()
        outside = SeededRun(
            run=seeded.run,
            graph=seeded.graph,
            principal=outsider,
            org=other_org,
            factory=seeded.factory,
        )
        async with seeded.factory() as db:
            with pytest.raises(NotFoundError):
                await WorkflowExecutionService(db).workflow_log_summary(
                    outside.ctx,
                    seeded.run.workflow_id,
                    filters=LogFilters(include_test=True),
                    days=7,
                )
            rows = await workflow_log_repo.count_by_day(
                db,
                organization_id=other_org.id,
                workflow_id=seeded.run.workflow_id,
                filters=LogFilters(include_test=True),
                since=datetime.now(UTC) - timedelta(days=7),
                until=datetime.now(UTC) + timedelta(days=1),
                tz="UTC",
            )
        assert rows == []


class TestRecentAcrossWorkflows:
    async def _logged(self, engine: AsyncEngine, kinds: dict[str, str]) -> SeededRun:
        mail = _step(kinds["ok"], label="Mail", quick_log=QuickLog(message="mailed"))
        bad = _step(kinds["boom"], label="Bad", quick_log=QuickLog(message="broke"))
        seeded = await seed_run(engine, _chain(mail, bad))
        await drive(seeded)
        return seeded

    async def _recent(self, seeded: SeededRun, ctx=None, **page: int):
        async with seeded.factory() as db:
            return await WorkflowExecutionService(db).recent_logs(ctx or seeded.ctx, **page)

    async def _as_real(self, seeded: SeededRun) -> None:
        """The harness seeds test runs; make their lines a real run's."""
        async with seeded.factory() as db:
            await db.execute(
                update(WorkflowLogEntry)
                .where(WorkflowLogEntry.run_id == seeded.run.id)
                .values(is_test=False)
            )
            await db.commit()

    async def _colleague(self, seeded: SeededRun) -> AuthContext:
        """A second `member` of the same organization, who owns none of its workflows."""
        async with seeded.factory() as db:
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
                    id=uuid.uuid4(), organization_id=seeded.org.id, user_id=user.id, role="member"
                )
            )
            await db.commit()
        return AuthContext(user_id=user.id, organization_id=seeded.org.id, role="member")

    async def test_the_newest_real_lines_come_with_the_workflow_name_and_counts_by_outcome(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        assert (await self._recent(seeded)).items == []  # test runs are left out
        await self._as_real(seeded)
        recent = await self._recent(seeded)
        assert [item.step_label for item in recent.items] == ["Bad", "Mail"]
        assert {item.workflow_name for item in recent.items} == {"Graph"}
        assert recent.counts == {"out": 1, "error": 1}

    async def test_it_is_paged_and_the_counts_cover_only_the_last_24_hours(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        await self._as_real(seeded)
        async with seeded.factory() as db:
            await db.execute(
                update(WorkflowLogEntry)
                .where(WorkflowLogEntry.step_label == "Mail")
                .values(created_at=datetime.now(UTC) - timedelta(hours=25))
            )
            await db.commit()
        page = await self._recent(seeded, skip=1, limit=1)
        assert [item.step_label for item in page.items] == ["Mail"]
        assert page.counts == {"error": 1}

    @pytest.mark.security
    async def test_a_member_sees_only_the_workflows_they_may_view(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        await self._as_real(seeded)
        colleague = await self._colleague(seeded)
        hidden = await self._recent(seeded, colleague)
        assert hidden.items == [] and hidden.counts == {}
        async with seeded.factory() as db:
            await db.execute(
                update(Workflow)
                .where(Workflow.id == seeded.run.workflow_id)
                .values(visibility=Visibility.ORG.value)
            )
            await db.commit()
        shown = await self._recent(seeded, colleague)
        assert len(shown.items) == 2 and shown.counts == {"out": 1, "error": 1}

    @pytest.mark.security
    async def test_a_workflow_shared_by_a_grant_shows_its_lines_and_counts(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        await self._as_real(seeded)
        colleague = await self._colleague(seeded)
        assert (await self._recent(seeded, colleague)).items == []
        async with seeded.factory() as db:
            db.add(
                ResourceGrant(
                    organization_id=seeded.org.id,
                    subject_user_id=colleague.user_id,
                    resource_type="workflow",
                    resource_id=seeded.run.workflow_id,
                    level="read",
                )
            )
            await db.commit()
        shared = await self._recent(seeded, colleague)
        assert [item.step_label for item in shared.items] == ["Bad", "Mail"]
        assert shared.counts == {"out": 1, "error": 1}

    @pytest.mark.security
    async def test_another_organization_sees_none_of_it(
        self, engine: AsyncEngine, kinds: dict[str, str]
    ):
        seeded = await self._logged(engine, kinds)
        await self._as_real(seeded)
        async with seeded.factory() as db:
            await db.execute(
                update(Workflow)
                .where(Workflow.id == seeded.run.workflow_id)
                .values(visibility=Visibility.ORG.value)
            )
            outsider, other_org = await seed_member(db)
            await db.commit()
        ctx = AuthContext(user_id=outsider.id, organization_id=other_org.id, role="owner")
        recent = await self._recent(seeded, ctx)
        assert recent.items == [] and recent.counts == {}


def _logged_loop(built: _Loop, **steps: QuickLog) -> WorkflowGraph:
    """The built loop's graph with a Quick Log on the named steps (`loop`, `refuse`)."""
    ids = {getattr(built, name).id: quick_log for name, quick_log in steps.items()}
    nodes = tuple(
        node.model_copy(update={"quick_log": ids[node.id]}) if node.id in ids else node
        for node in built.graph.nodes
    )
    return built.graph.model_copy(update={"nodes": nodes})


class TestLoops:
    async def test_a_loop_that_completes_logs_done_once_with_what_it_collected(
        self, engine: AsyncEngine
    ):
        loop = _Loop()
        graph = _logged_loop(loop, loop=QuickLog(message="{{outcome}} {{count}} {{results}}"))
        seeded = await seed_run(engine, graph, run_input={"items": ITEMS})

        run = await drive(seeded)

        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        (entry,) = await _entries(seeded)
        assert (entry.outcome, entry.status) == ("done", "succeeded")
        assert entry.message.startswith("done 3 [")
        assert '"name":"grace"' in entry.message

    async def test_a_loop_whose_log_does_not_name_done_writes_nothing_on_success(
        self, engine: AsyncEngine
    ):
        graph = _logged_loop(_Loop(), loop=QuickLog(outputs=("body",)))
        seeded = await seed_run(engine, graph, run_input={"items": ITEMS})
        await drive(seeded)
        assert await _entries(seeded) == []

    async def test_a_collected_item_failure_is_logged_whatever_outputs_says(
        self, engine: AsyncEngine
    ):
        loop = _Loop(policy="collect", fail_on="grace")
        graph = _logged_loop(
            loop, refuse=QuickLog(message="{{outcome}} {{error.code}}", outputs=("out",))
        )
        seeded = await seed_run(engine, graph, run_input={"items": ITEMS})

        run = await drive(seeded)

        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        failed = [e for e in await _entries(seeded) if e.status == "failed"]
        assert [(e.outcome, e.message) for e in failed] == [("error", "error BAD_ITEM")]

    async def test_a_loop_that_stops_on_a_failed_item_logs_the_error_once_after_the_item(
        self, engine: AsyncEngine
    ):
        loop = _Loop(policy="stop", fail_on="grace")
        graph = _logged_loop(
            loop,
            loop=QuickLog(message="loop {{outcome}} {{error.code}}"),
            refuse=QuickLog(message="item {{outcome}} {{error.code}}"),
        )
        seeded = await seed_run(engine, graph, run_input={"items": ITEMS})

        run = await drive(seeded)

        assert run.status == WorkflowRunStatus.FAILED.value
        entries = await _entries(seeded)
        # In the order they were written, though both share one transaction.
        assert [(e.message, e.outcome) for e in entries] == [
            ("item error BAD_ITEM", "error"),
            ("loop error BAD_ITEM", "error"),
        ]
        assert "done" not in {e.outcome for e in entries}
