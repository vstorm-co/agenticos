"""The idempotency race in `ApiRunService.queue`, with the queue mocked (#2219).

`tests/integration/test_api_run_requests.py` loses the race for real against the
unique index; the lines after the lost insert are pinned here as well, because
the coverage tracer does not always record lines after an `await` in an
`except` reached through a real database error.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.permissions import AuthContext
from app.schemas.agent import AgentRunRequest
from app.services.api_runs import ApiRunService, digest
from app.worker.jobs import RUN_AGENT, RunAgent

pytestmark = pytest.mark.anyio


async def test_an_insert_that_lost_the_race_answers_the_winners_request() -> None:
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="member")
    agent_id = uuid.uuid4()
    request = AgentRunRequest(prompt="summarise the week")
    conversation_id = uuid.uuid4()
    winner = MagicMock(
        id=uuid.uuid4(),
        kind=RUN_AGENT.kind,
        status="queued",
        created_at=datetime.now(UTC),
        finished_at=None,
        result=None,
        last_error=None,
        payload=RUN_AGENT.dump(
            RunAgent(
                agent_id=agent_id,
                organization_id=ctx.organization_id,
                user_id=ctx.subject_id,
                api_key_id=None,
                prompt=request.prompt,
                conversation_id=conversation_id,
                environment_id=None,
                file_ids=[],
                digest=digest(agent_id, request),
            )
        ),
    )

    @asynccontextmanager
    async def savepoint():
        yield

    db = MagicMock(begin_nested=savepoint)
    with (
        patch(
            "app.services.api_runs.ConversationService.for_api_run",
            new=AsyncMock(return_value=(conversation_id, None)),
        ),
        patch("app.services.api_runs.load_attached_files", new=AsyncMock(return_value=[])),
        patch(
            "app.services.api_runs.AgentRegistryService.get_runnable_spec",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.api_runs.enqueue",
            new=AsyncMock(side_effect=IntegrityError("INSERT", {}, Exception("duplicate key"))),
        ),
        patch(
            "app.services.api_runs.background_job_repo.get_by_idempotency_key",
            new=AsyncMock(side_effect=[None, winner]),
        ),
    ):
        answer = await ApiRunService(db).queue(ctx, agent_id, request, idempotency_key="order-7")

    assert (answer.id, answer.status, answer.conversation_id) == (
        winner.id,
        "queued",
        conversation_id,
    )
