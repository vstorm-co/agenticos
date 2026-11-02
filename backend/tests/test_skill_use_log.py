"""Which skills a run used - counted from the tool calls the model really made.

Guarded here: a skill counts when its model opened it or read its files, by id and
never by a name the run was not served; a path in the workspace counts apart and
a listing not at all; a delegate's uses land under the delegate; and the count
survives a run that fails after the skill was opened.
"""

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents.capabilities._registry import CapabilityBuildContext
from app.agents.capabilities._registry import get as get_capability
from app.agents.capabilities.skills import (
    SKILL_USE_LOG_RESOURCE,
    ServedSkill,
    SkillBody,
    Skills,
    SkillUseLog,
    served_skills,
)
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.skill import Skill, SkillResource
from app.services.agent_runner import AgentRunnerService, PreparedRun

pytestmark = pytest.mark.anyio

RUNNER = "app.services.agent_runner"
AGENT = uuid.uuid4()
REFUNDS = uuid.uuid4()
SHIPPING = uuid.uuid4()


def _log(**served: ServedSkill) -> SkillUseLog:
    return SkillUseLog(
        agent_id=AGENT,
        served=served or {"refunds": ServedSkill(REFUNDS), "shipping": ServedSkill(SHIPPING)},
    )


def _skill(name: str, skill_id: uuid.UUID, *, files: tuple[str, ...] = ()) -> Skill:
    skill = Skill(id=skill_id, name=name, description=f"About {name}", content=f"# {name}")
    skill.resources = [SkillResource(name=file, description=file, content="text") for file in files]
    return skill


class TestObserve:
    def test_a_load_counts_the_skill_it_opened(self) -> None:
        log = _log()
        log.observe("load_capability", {"id": "refunds"})
        [record] = log.records()
        assert (record.agent_id, record.skill_id, record.loaded) == (AGENT, REFUNDS, True)
        assert (record.resource_reads, record.workspace_reads) == (0, 0)

    def test_reading_a_file_through_the_skill_tool_counts(self) -> None:
        log = _log()
        log.observe("read_skill_resource", {"skill_name": "refunds", "resource_name": "faq.md"})
        log.observe("read_skill_resource", {"skill_name": "refunds", "resource_name": "faq.md"})
        [record] = log.records()
        assert (record.loaded, record.resource_reads) == (False, 2)

    @pytest.mark.parametrize(
        ("tool", "args"),
        [
            ("load_capability", {"id": "invented"}),
            ("load_capability", {"id": 3}),
            ("read_skill_resource", {"skill_name": "invented"}),
            ("search_documents", {"query": "refunds policy"}),
        ],
    )
    def test_a_skill_the_run_was_not_served_is_never_counted(self, tool, args) -> None:
        log = _log()
        log.observe(tool, args)
        assert log.records() == []

    @pytest.mark.parametrize(
        "command",
        [
            "cat /workspace/skills/refunds/SKILL.md",
            "python skills/refunds/reconcile.py",
            "grep -n fee '/skills/refunds/faq.md'",
            "python ./skills/refunds/reconcile.py",
            "ls /workspace && cat /workspace/skills/refunds/SKILL.md",
        ],
    )
    def test_a_path_in_the_skill_folder_counts_apart(self, command: str) -> None:
        log = _log()
        log.observe("execute", {"command": command})
        [record] = log.records()
        assert (record.skill_id, record.loaded, record.workspace_reads) == (REFUNDS, False, 1)

    def test_a_nested_argument_is_read_too(self) -> None:
        log = _log()
        log.observe(
            "edit_file",
            {"edits": [{"path": "/workspace/skills/shipping/SKILL.md", "line": 3}], "dry": False},
        )
        [record] = log.records()
        assert record.skill_id == SHIPPING

    @pytest.mark.parametrize(
        ("tool", "args"),
        [
            ("ls", {"path": "/workspace/skills/refunds"}),
            ("execute", {"command": "ls -la /workspace/skills/refunds"}),
            ("execute", {"command": "cat /workspace/notes/skills/refunds.md"}),
            ("execute", {"command": "cat /workspace/skills/refunds-old/SKILL.md"}),
            ("execute", {"command": "cat /tmp/skills/refunds/x"}),
            ("read_file", {"path": "/home/u/.claude/skills/refunds/SKILL.md"}),
            ("read_file", {"path": "/workspace/other/skills/refunds/a"}),
            ("execute", {"command": "cat notes.md; ls /workspace/skills/refunds"}),
        ],
    )
    def test_a_listing_or_another_path_does_not_count(self, tool, args) -> None:
        log = _log()
        log.observe(tool, args)
        assert log.records() == []

    def test_records_are_drained_once(self) -> None:
        log = _log()
        log.observe("load_capability", {"id": "refunds"})
        assert len(log.records()) == 1
        assert log.records() == []

    def test_no_skills_served_means_nothing_scanned(self) -> None:
        log = SkillUseLog(agent_id=AGENT, served={})
        log.observe("execute", {"command": "cat /workspace/skills/refunds/SKILL.md"})
        assert log.records() == []


class TestDelegates:
    def test_a_delegate_records_under_its_own_agent_on_the_shared_log(self) -> None:
        parent = _log()
        delegate_agent = uuid.uuid4()
        delegate = parent.for_agent(delegate_agent, {"refunds": ServedSkill(REFUNDS)})
        parent.observe("load_capability", {"id": "refunds"})
        delegate.observe("load_capability", {"id": "refunds"})
        records = {record.agent_id: record for record in parent.records()}
        assert set(records) == {AGENT, delegate_agent}
        assert delegate.records() == []

    def test_an_inline_specialist_uses_skills_as_the_delegating_agent(self) -> None:
        parent = _log()
        inline = parent.for_agent(None, {"shipping": ServedSkill(SHIPPING)})
        inline.observe("load_capability", {"id": "shipping"})
        [record] = parent.records()
        assert (record.agent_id, record.skill_id) == (AGENT, SHIPPING)


class TestServedSkills:
    def test_a_candidate_body_is_marked_and_a_proposed_new_skill_is_left_out(self) -> None:
        new = uuid.uuid4()
        served = served_skills(
            [_skill("refunds", REFUNDS), _skill("shipping", SHIPPING), _skill("brand-new", new)],
            {
                REFUNDS: SkillBody(description="d", content="c"),
                new: SkillBody(description="d", content="c", name="brand-new"),
            },
        )
        assert served == {
            "refunds": ServedSkill(REFUNDS, projected=True),
            "shipping": ServedSkill(SHIPPING),
        }


class TestAgentRun:
    """A real agent run, as the runner builds it, with a model that opens a skill."""

    @staticmethod
    def _agent(log: SkillUseLog, model: FunctionModel) -> Agent[None, str]:
        skill = _skill("refunds", REFUNDS, files=("faq.md",))
        return Agent(model, capabilities=[Skills([skill], log=log)])

    async def test_the_load_and_the_file_read_are_counted(self) -> None:
        log = _log(refunds=ServedSkill(REFUNDS))

        def model(messages, _info: AgentInfo) -> ModelResponse:
            returns = sum(isinstance(p, ToolReturnPart) for m in messages for p in m.parts)
            if returns == 0:
                return ModelResponse(parts=[ToolCallPart("load_capability", {"id": "refunds"})])
            if returns == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            "read_skill_resource",
                            {"skill_name": "refunds", "resource_name": "faq.md"},
                        )
                    ]
                )
            return ModelResponse(parts=[TextPart("done")])

        await self._agent(log, FunctionModel(model)).run("refund please")
        [record] = log.records()
        assert (record.loaded, record.resource_reads) == (True, 1)

    async def test_a_run_that_fails_after_the_load_keeps_it(self) -> None:
        log = _log(refunds=ServedSkill(REFUNDS))

        def model(messages, _info: AgentInfo) -> ModelResponse:
            if not any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
                return ModelResponse(parts=[ToolCallPart("load_capability", {"id": "refunds"})])
            raise RuntimeError("provider went away")

        with pytest.raises(RuntimeError):
            await self._agent(log, FunctionModel(model)).run("refund please")
        [record] = log.records()
        assert record.loaded is True

    async def test_without_a_log_the_skill_still_loads(self) -> None:
        def model(messages, _info: AgentInfo) -> ModelResponse:
            if not any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
                return ModelResponse(parts=[ToolCallPart("load_capability", {"id": "refunds"})])
            return ModelResponse(parts=[TextPart("done")])

        skill = _skill("refunds", REFUNDS)
        result = await Agent(FunctionModel(model), capabilities=[Skills([skill])]).run("go")
        assert result.output == "done"


def _prepared(log: SkillUseLog | None) -> PreparedRun:
    run = MagicMock(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        started_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    return PreparedRun(
        run=run,
        agent=MagicMock(),
        spec=AgentSpec(name="Support"),
        built=MagicMock(),
        approvals=MagicMock(),
        skill_uses=log,
    )


def _savepoint_db() -> MagicMock:
    db = MagicMock()
    savepoint = MagicMock()
    savepoint.__aenter__ = AsyncMock(return_value=None)
    savepoint.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=savepoint)
    return db


class TestTheRunnerWritesTheLog:
    async def test_the_uses_are_written_once_under_the_run_and_it_is_marked_recorded(
        self,
    ) -> None:
        log = _log()
        log.observe("load_capability", {"id": "refunds"})
        prepared = _prepared(log)
        service = AgentRunnerService(_savepoint_db())

        with (
            patch(f"{RUNNER}.skill_usage_repo.record_uses", new=AsyncMock()) as write,
            patch(f"{RUNNER}.skill_usage_repo.mark_recorded", new=AsyncMock()) as recorded,
        ):
            await service._write_skill_uses(prepared)

        write.assert_awaited_once()
        assert write.await_args.kwargs["run_id"] == prepared.run.id
        assert write.await_args.kwargs["organization_id"] == prepared.run.organization_id
        assert write.await_args.kwargs["started_at"] == prepared.run.started_at
        assert [r.skill_id for r in write.await_args.args[1]] == [REFUNDS]
        assert recorded.await_args.kwargs == {
            "organization_id": prepared.run.organization_id,
            "run_id": prepared.run.id,
        }
        assert log.records() == []

    async def test_a_run_without_skills_is_recorded_as_using_none(self) -> None:
        service = AgentRunnerService(_savepoint_db())

        with (
            patch(f"{RUNNER}.skill_usage_repo.record_uses", new=AsyncMock()) as write,
            patch(f"{RUNNER}.skill_usage_repo.mark_recorded", new=AsyncMock()) as recorded,
        ):
            await service._write_skill_uses(_prepared(None))

        assert write.await_args.args[1] == []
        recorded.assert_awaited_once()

    async def test_a_lost_write_leaves_the_run_unrecorded_and_does_not_fail_it(
        self, caplog
    ) -> None:
        log = _log()
        log.observe("load_capability", {"id": "refunds"})
        service = AgentRunnerService(_savepoint_db())

        with (
            patch(
                f"{RUNNER}.skill_usage_repo.record_uses",
                new=AsyncMock(side_effect=RuntimeError("insert failed")),
            ),
            patch(f"{RUNNER}.skill_usage_repo.mark_recorded", new=AsyncMock()) as recorded,
        ):
            await service._write_skill_uses(_prepared(log))

        assert "skill_uses_not_written" in caplog.text
        recorded.assert_not_awaited()


class TestADelegateUsesSkillsUnderItsOwnName:
    async def _resources(self, parent: dict[str, Any], agent_id: uuid.UUID | None) -> Any:
        ctx = AuthContext(
            user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
        )
        service = AgentRunnerService(MagicMock())
        service.skills = MagicMock(
            resolve_for_agent=AsyncMock(return_value=[_skill("shipping", SHIPPING)])
        )
        service.context = MagicMock(resolve_for_agent=AsyncMock(return_value=[]))
        return await service._delegate_resources(
            ctx,
            AgentSpec(name="Delegate", skill_ids=[SHIPPING]),
            agent_id=agent_id,
            shared=[],
            parent_resources=parent,
        )

    async def test_a_delegate_records_into_the_parents_log(self) -> None:
        log = _log()
        delegate = uuid.uuid4()

        resources = await self._resources({SKILL_USE_LOG_RESOURCE: log}, agent_id=delegate)
        resources[SKILL_USE_LOG_RESOURCE].observe("load_capability", {"id": "shipping"})

        assert [(r.agent_id, r.skill_id) for r in log.records()] == [(delegate, SHIPPING)]

    async def test_a_parent_with_no_log_gives_its_delegate_none(self) -> None:
        resources = await self._resources({}, agent_id=uuid.uuid4())

        assert SKILL_USE_LOG_RESOURCE not in resources


class TestTheCapabilityTakesTheRunnersLog:
    def test_the_built_capability_counts_into_the_injected_log(self) -> None:
        log = _log()
        built = get_capability("skills").builder(
            CapabilityBuildContext(
                binding=CapabilityBindingSpec(id="skills"),
                config=None,
                resources={"skills": [_skill("refunds", REFUNDS)], SKILL_USE_LOG_RESOURCE: log},
            )
        )

        assert isinstance(built, Skills)
        assert built._log is log
