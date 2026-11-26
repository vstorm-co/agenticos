"""A retained container must not be reported as continued native history after a reset."""

from pathlib import Path

import pytest

from app.agents.capabilities.coding_agent._harness import CodingReport
from app.agents.capabilities.coding_agent._task import WORK_DIR, session_path
from tests.test_coding_agent import _CLAUDE_DONE, THREAD, _call, _claude_stream, _lines, _Shell

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("remembered", "fresh", "pruned", "resumed"),
    [
        (True, False, False, True),
        (True, True, False, False),
        (True, False, True, False),
        (False, False, False, False),
    ],
)
async def test_personal_native_continuation_reports_a_pruned_history_as_new(
    remembered: bool,
    fresh: bool,
    pruned: bool,
    resumed: bool,
) -> None:
    shell = _Shell(events=_lines(_claude_stream(result=_CLAUDE_DONE)), fails_resumed=pruned)
    await shell.make_dir(WORK_DIR)
    if remembered:
        await shell.write_bytes(session_path("claude_code", THREAD), b"old-history")
    report = CodingReport.model_validate_json(
        await _call(shell, personal_isolated=True, fresh_session=fresh)
    )
    assert report.outcome == "completed"
    assert report.session_resumed is resumed


@pytest.mark.parametrize("native_state", [True, False, None])
async def test_personal_result_uses_native_history_state_instead_of_container_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_state: bool | None,
) -> None:
    from uuid import uuid4

    from pydantic_ai.models.test import TestModel
    from pydantic_ai.tools import RunContext
    from pydantic_ai.toolsets import FunctionToolset
    from pydantic_ai.usage import RunUsage
    from pydantic_ai.workspaces import Workspace
    from pydantic_ai.workspaces.local import LocalWorkspaceBackend

    from app.agents.capabilities.coding_agent import _toolset
    from app.agents.deps import AgentDeps
    from tests.test_personal_coding import PersonalExecutor

    workspace = Workspace(LocalWorkspaceBackend(tmp_path))
    outer = _toolset.build_coding_toolset(
        harness="claude_code",
        access="read_only",
        model=None,
        base_url=None,
        api_key=None,
        timeout_seconds=60,
        runs_on="personal_sandbox",
        personal_executor=PersonalExecutor(workspace),
    )
    inner = FunctionToolset[AgentDeps]()

    async def tool(
        ctx: RunContext[AgentDeps], task: str, session: str = "main", fresh_session: bool = False
    ) -> str:
        assert ctx.workspace is workspace and task == "Inspect"
        assert session == "main" and not fresh_session
        return CodingReport(
            harness="claude_code",
            access="read_only",
            outcome="completed",
            answer="Inspected",
            session_resumed=native_state,
        ).model_dump_json()

    inner.add_function(tool, name="run_coding_agent")
    monkeypatch.setattr(_toolset, "build_coding_toolset", lambda **_options: inner)
    ctx = RunContext(
        deps=AgentDeps(organization_id=uuid4(), user_id=str(uuid4())),
        model=TestModel(),
        usage=RunUsage(),
        prompt="Task",
        workspace=workspace,
    )
    report = CodingReport.model_validate_json(
        await outer.tools["run_coding_agent"].function(ctx, "Inspect")
    )
    assert report.session_resumed is (native_state if native_state is not None else False)
