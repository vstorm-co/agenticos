"""Authenticated comparison reads have shared work budgets, including the console."""

from contextlib import aclosing
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.api.deps import limit_eval_comparison
from app.core.exceptions import AuthorizationError, RateLimitError
from app.core.permissions import AuthContext
from app.services import rate_limit

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")


async def test_comparison_counts_the_person_and_organization(monkeypatch):
    ctx = _ctx()
    consume = AsyncMock(return_value=rate_limit.Decision(True, 60))
    monkeypatch.setattr(rate_limit, "consume_with_local_floor", consume)
    monkeypatch.setattr(rate_limit, "_redis", None)
    async with aclosing(limit_eval_comparison(ctx)) as guard:
        await anext(guard)
    assert [call.kwargs for call in consume.await_args_list] == [
        {
            "surface": "eval_comparison",
            "caller": f"org:{ctx.organization_id}:user:{ctx.subject_id}",
            "limit": rate_limit.Limit(30),
        },
        {
            "surface": "eval_comparison",
            "caller": f"org:{ctx.organization_id}",
            "limit": rate_limit.Limit(60),
        },
    ]


@pytest.mark.parametrize("refused_at", [0, 1])
async def test_comparison_refuses_either_exhausted_budget(monkeypatch, refused_at):
    decisions = [rate_limit.Decision(True, 60)] * refused_at + [rate_limit.Decision(False, 17)]
    consume = AsyncMock(side_effect=decisions)
    monkeypatch.setattr(rate_limit, "consume_with_local_floor", consume)
    ctx = _ctx()
    monkeypatch.setattr(rate_limit, "_redis", None)
    with pytest.raises(RateLimitError) as caught:
        await anext(limit_eval_comparison(ctx))
    assert caught.value.details == {"retry_after_seconds": 17}
    assert consume.await_count == refused_at + 1
    consume.side_effect = None
    consume.return_value = rate_limit.Decision(True, 60)
    async with aclosing(limit_eval_comparison(ctx)) as next_read:
        await anext(next_read)


async def test_only_one_org_comparison_runs_and_closing_releases_it(monkeypatch):
    ctx = _ctx()
    second = AuthContext(user_id=uuid4(), organization_id=ctx.organization_id, role="owner")
    consume = AsyncMock(return_value=rate_limit.Decision(True, 60))
    monkeypatch.setattr(rate_limit, "consume_with_local_floor", consume)
    monkeypatch.setattr(rate_limit, "_redis", None)
    async with aclosing(limit_eval_comparison(ctx)) as first:
        await anext(first)
        for _ in range(35):
            with pytest.raises(RateLimitError):
                await anext(limit_eval_comparison(second))
        assert consume.await_count == 2
        async with aclosing(limit_eval_comparison(_ctx())) as other_org:
            await anext(other_org)
    async with aclosing(limit_eval_comparison(second)) as next_read:
        await anext(next_read)


@pytest.mark.parametrize("role", ["member", "viewer"])
async def test_nonreaders_cannot_consume_quota_or_claim_concurrency(monkeypatch, role):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=role)
    consume, claim = AsyncMock(), MagicMock()
    monkeypatch.setattr(rate_limit, "consume_with_local_floor", consume)
    monkeypatch.setattr(rate_limit, "one_in_flight", claim)
    with pytest.raises(AuthorizationError):
        await anext(limit_eval_comparison(ctx))
    consume.assert_not_awaited()
    claim.assert_not_called()


async def test_verdict_computation_and_reads_share_the_claim_and_person_budget(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(rate_limit, "_redis", None)
    async with aclosing(limit_eval_comparison(ctx)) as read:
        await anext(read)
        with pytest.raises(RateLimitError):
            async with rate_limit.eval_computation(ctx):
                pytest.fail("a verdict write must not overlap the comparison")
    for _ in range(29):
        async with rate_limit.eval_computation(ctx):
            pass
    with pytest.raises(RateLimitError) as refused:
        await anext(limit_eval_comparison(ctx))
    assert 1 <= refused.value.details["retry_after_seconds"] <= 60
    assert "inflight:eval_comparison:org:" + str(ctx.organization_id) not in rate_limit._held_here
