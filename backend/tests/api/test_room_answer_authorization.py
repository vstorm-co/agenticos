"""Room admission preserves the answer route's requester authorization and HTTP status."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse, ToolCallPart

from app.api import deps
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.main import app
from app.services import conversation_turns
from app.services.agent_runner import AgentRunnerService, RunSegment
from app.services.approvals import ApprovalService
from app.services.parked_runs import ParkedRunService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("answerer_is_requester", [False, True])
async def test_only_the_original_requester_can_answer_under_room_admission(
    answerer_is_requester: bool,
) -> None:
    requester_id = uuid4()
    ctx = AuthContext(
        user_id=requester_id if answerer_is_requester else uuid4(),
        organization_id=uuid4(),
        role="member",
    )
    run = AgentRun(
        id=uuid4(),
        organization_id=ctx.organization_id,
        agent_id=uuid4(),
        user_id=requester_id,
        conversation_id=uuid4(),
        surface=RunSurface.WEB.value,
        status=RunStatus.AWAITING_ANSWER.value,
        paused_state={
            "messages": ModelMessagesTypeAdapter.dump_python(
                [
                    ModelResponse(
                        parts=[
                            ToolCallPart(
                                "ask_user_question",
                                {
                                    "questions": [
                                        {
                                            "header": "Audience",
                                            "question": "Who will use it?",
                                            "options": [
                                                {"label": "Everyone"},
                                                {"label": "My team"},
                                            ],
                                        }
                                    ]
                                },
                                tool_call_id="question-1",
                            )
                        ]
                    )
                ],
                mode="json",
            ),
            "tool_call_ids": {},
            "questions": ["question-1"],
        },
        cost_usd=Decimal("0"),
        cost_is_partial=False,
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    db = MagicMock()
    runner = AgentRunnerService(db)
    parked = ParkedRunService(db, runner=runner, approvals=ApprovalService(db))
    claim_id = uuid4()

    @asynccontextmanager
    async def database() -> AsyncGenerator[MagicMock]:
        yield db

    async def continue_run(*_args: object, **_kwargs: object) -> RunSegment:
        run.status = RunStatus.COMPLETED.value
        return RunSegment(output="Received your answer", run=run, tool_calls=[], settled={})

    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_agent_runner_service] = lambda: runner
    app.dependency_overrides[deps.get_parked_run_service] = lambda: parked
    try:
        with (
            patch("app.core.maintenance.get_db_context", new=database),
            patch("app.repositories.deployment_settings.get", new=AsyncMock(return_value=None)),
            patch("app.repositories.agent_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(
                "app.repositories.room_submission.for_run", new=AsyncMock(return_value=MagicMock())
            ),
            patch.object(conversation_turns, "get_db_context", new=database),
            patch.object(
                conversation_turns.task_repo, "claim_turn", new=AsyncMock(return_value=claim_id)
            ) as claim,
            patch.object(conversation_turns.task_repo, "release_turn", new=AsyncMock()) as release,
            patch.object(runner, "resume", new=AsyncMock(side_effect=continue_run)) as resume,
            patch.object(runner, "parked_calls", new=AsyncMock(return_value=[])),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/api/v1/runs/{run.id}/answers",
                    json={"responses": {"question-1": [{"selected": ["My team"]}]}},
                )

            assert response.status_code == (200 if answerer_is_requester else 403), response.text
            claim.assert_awaited_once_with(
                db,
                run.conversation_id,
                background=False,
                room_request_id=None,
                resume_run_id=run.id,
            )
            release.assert_awaited_once_with(db, claim_id)
            if answerer_is_requester:
                assert response.json()["output"] == "Received your answer"
                assert response.json()["status"] == RunStatus.COMPLETED.value
                assert resume.await_args is not None
                assert resume.await_args.kwargs["answers"] == {
                    "question-1": {"Audience": ["My team"]}
                }
            else:
                assert response.json() == {
                    "error": {
                        "code": "AUTHORIZATION_ERROR",
                        "message": "Only the person it asked can answer this question",
                        "details": None,
                    }
                }
                assert run.status == RunStatus.AWAITING_ANSWER.value
                resume.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()
