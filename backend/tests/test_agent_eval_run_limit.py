"""The eval-run rate limit: an eval try's starts share one allowance.

An eval try starts a test run of the agent per case, per side, per sample,
so it gets a surface of its own - `agent_eval_run` - on the same allowance
as the run limits, following `limit_workflow_run`.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.api.deps import limit_agent_eval_run
from app.core.exceptions import RateLimitError
from app.core.permissions import AuthContext
from app.services.rate_limit import Decision

pytestmark = pytest.mark.anyio


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")


async def test_an_eval_try_inside_the_allowance_is_let_through():
    ctx = _ctx()
    consume = AsyncMock(return_value=Decision(allowed=True, retry_after_seconds=0))

    with patch("app.api.deps.rate_limit.consume", consume):
        await limit_agent_eval_run(ctx)

    consume.assert_awaited_once()
    call = consume.await_args
    assert call.kwargs["surface"] == "agent_eval_run"
    assert call.kwargs["caller"] == f"user:{ctx.subject_id}"


async def test_an_eval_try_over_the_allowance_is_refused_as_a_429():
    consume = AsyncMock(return_value=Decision(allowed=False, retry_after_seconds=60))

    with (
        patch("app.api.deps.rate_limit.consume", consume),
        pytest.raises(RateLimitError) as caught,
    ):
        await limit_agent_eval_run(_ctx())

    assert caught.value.status_code == 429
    assert caught.value.details["retry_after_seconds"] == 60
