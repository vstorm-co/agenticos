"""Direct-share fanout stays bounded across fresh conversation IDs."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import RateLimitError
from app.services import rate_limit

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("refused", range(4))
async def test_each_aggregate_share_quota_refuses_with_a_retry_interval(
    monkeypatch: pytest.MonkeyPatch, refused: int
) -> None:
    consume = AsyncMock(
        side_effect=[
            rate_limit.Decision(allowed=index != refused, retry_after_seconds=17)
            for index in range(4)
        ]
    )
    monkeypatch.setattr(rate_limit, "consume_with_local_floor", consume)
    with pytest.raises(RateLimitError) as failure:
        await rate_limit.enforce_conversation_share(
            organization_id=uuid4(), actor_id=uuid4(), recipient_id=uuid4()
        )
    assert failure.value.details == {"retry_after_seconds": 17}
    assert consume.await_count == refused + 1


async def test_share_quotas_bind_the_org_actor_and_recipient_without_a_conversation_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, actor, recipient = uuid4(), uuid4(), uuid4()
    consume = AsyncMock(return_value=rate_limit.Decision(allowed=True, retry_after_seconds=0))
    monkeypatch.setattr(rate_limit, "consume_with_local_floor", consume)
    for _ in range(2):
        await rate_limit.enforce_conversation_share(
            organization_id=org, actor_id=actor, recipient_id=recipient
        )
    first = [call.kwargs for call in consume.await_args_list[:4]]
    assert first == [call.kwargs for call in consume.await_args_list[4:]]
    assert [item["limit"].attempts for item in first] == [5, 20, 20, 100]
    assert first[3]["caller"] == f"org:{org}"
    assert first[1]["caller"] == f"org:{org}:actor:{actor}"
    assert first[2]["caller"] == f"org:{org}:recipient:{recipient}"
    assert first[0]["caller"] == f"org:{org}:actor:{actor}:recipient:{recipient}"


async def test_direct_shares_keep_the_pair_ceiling_when_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rate_limit, "_redis", None)
    monkeypatch.setattr(rate_limit, "_floor", rate_limit.LocalWindows())
    org, actor, recipient = uuid4(), uuid4(), uuid4()
    for _ in range(5):
        await rate_limit.enforce_conversation_share(
            organization_id=org, actor_id=actor, recipient_id=recipient
        )
    with pytest.raises(RateLimitError):
        await rate_limit.enforce_conversation_share(
            organization_id=org, actor_id=actor, recipient_id=recipient
        )
    await rate_limit.enforce_conversation_share(
        organization_id=org, actor_id=actor, recipient_id=uuid4()
    )
    await rate_limit.enforce_conversation_share(
        organization_id=uuid4(), actor_id=actor, recipient_id=recipient
    )


async def test_a_blocked_pair_cannot_spend_the_organizations_delivery_allowance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rate_limit, "_redis", None)
    monkeypatch.setattr(rate_limit, "_floor", rate_limit.LocalWindows())
    org, actor, recipient = uuid4(), uuid4(), uuid4()
    for _ in range(5):
        await rate_limit.enforce_conversation_share(
            organization_id=org, actor_id=actor, recipient_id=recipient
        )
    for _ in range(100):
        with pytest.raises(RateLimitError):
            await rate_limit.enforce_conversation_share(
                organization_id=org, actor_id=actor, recipient_id=recipient
            )
    await rate_limit.enforce_conversation_share(
        organization_id=org, actor_id=uuid4(), recipient_id=uuid4()
    )
