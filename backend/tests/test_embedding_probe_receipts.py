"""Per-call admission and settlement, including cancellation after paid responses."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai.usage import RequestUsage

from app.agents.capabilities.budget import (
    BudgetExceeded,
    BudgetScope,
    record_ambient_cost,
    record_ambient_usage,
)
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.services import embedding_probe_call as calls
from app.services.embedding_resolution import EmbeddingKeySource, TargetIdentity
from app.services.rag.embeddings import EmbeddingProbeError

pytestmark = pytest.mark.anyio
MODEL = "text-embedding-3-small"


@pytest.fixture
def actor() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)


@pytest.fixture
def identity(actor: AuthContext) -> TargetIdentity:
    return TargetIdentity(
        provider="openai_compatible",
        connection_id=uuid4(),
        base_url="https://example.test/v1",
        secret_id=uuid4(),
        key_generation=uuid4(),
        key_organization_id=actor.organization_id,
        key_source=EmbeddingKeySource.CONNECTION,
    )


@pytest.fixture
def boundary(monkeypatch: pytest.MonkeyPatch, actor: AuthContext) -> MagicMock:
    state = MagicMock()
    state.context = AsyncMock(return_value=actor)
    state.budget = AsyncMock()
    state.record = AsyncMock()
    state.organization = MagicMock(monthly_budget_usd=Decimal("1"))

    @asynccontextmanager
    async def db_context():
        yield MagicMock()
        state.committed()

    monkeypatch.setattr(calls, "get_independent_db_context", db_context)
    monkeypatch.setattr(calls, "current_probe_context", state.context)
    monkeypatch.setattr(calls, "assert_organization_within_budget", state.budget)
    monkeypatch.setattr(
        calls.organization_repo, "get_by_id", AsyncMock(return_value=state.organization)
    )
    monkeypatch.setattr(calls.ingestion_spend_repo, "record", state.record)
    return state


async def _paid() -> list[float]:
    record_ambient_usage(MODEL, RequestUsage(input_tokens=8), "openai")
    return [1.0]


async def _run(actor, identity, request=_paid, authorize=None, model=MODEL):
    return await calls.run_probe_call(
        actor=actor,
        identity=identity,
        model=model,
        authorize=authorize or AsyncMock(),
        request=request,
    )


async def test_fractional_receipt_is_committed_before_return(actor, identity, boundary):
    assert await _run(actor, identity) == [1.0]
    row = boundary.record.call_args.kwargs
    assert row["organization_id"] == identity.key_organization_id
    assert row["rag_document_id"] is None
    assert row["cost_usd"] == Decimal("0.00000016")
    assert row["input_tokens"] == 8
    assert row["cost_is_partial"] is False
    assert boundary.committed.call_count == 2


async def test_refused_vector_retains_reported_usage(actor, identity, boundary):
    async def invalid():
        await _paid()
        raise EmbeddingProbeError("model_unknown")

    with pytest.raises(EmbeddingProbeError):
        await _run(actor, identity, invalid)
    boundary.record.assert_awaited_once()


async def test_fresh_authority_before_every_call_and_no_spend_after_refusal(
    actor, identity, boundary
):
    authorize = AsyncMock(side_effect=[None, AuthorizationError(message="grant removed")])
    request = AsyncMock(side_effect=_paid)
    await _run(actor, identity, request, authorize)
    with pytest.raises(AuthorizationError):
        await _run(actor, identity, request, authorize)
    assert request.await_count == 1
    assert boundary.context.await_count == 2
    boundary.record.assert_awaited_once()


async def test_cap_rechecked_after_each_receipt(actor, identity, boundary):
    cost = Decimal(0)

    async def budget(*_):
        if cost >= Decimal("0.0000003"):
            raise BudgetExceeded(
                scope=BudgetScope.ORGANIZATION, limit_usd=Decimal("0.0000003"), spent_usd=cost
            )

    async def receipt(*_, **row):
        nonlocal cost
        cost += row["cost_usd"]

    boundary.budget.side_effect = budget
    boundary.record.side_effect = receipt
    request = AsyncMock(side_effect=_paid)
    await _run(actor, identity, request)
    await _run(actor, identity, request)
    with pytest.raises(BudgetExceeded):
        await _run(actor, identity, request)
    assert request.await_count == 2
    assert cost == Decimal("0.00000032")


async def test_unknown_price_refused_before_paid_request(actor, identity, boundary):
    request = AsyncMock()
    with pytest.raises(BadRequestError, match="price is unknown"):
        await _run(actor, identity, request, model="not-a-priced-model")
    request.assert_not_awaited()
    boundary.record.assert_not_awaited()


@pytest.mark.parametrize("capped", [True, False])
async def test_unknown_usage_is_partial_never_fake_free(actor, identity, boundary, capped):
    boundary.organization.monthly_budget_usd = Decimal(1) if capped else None

    async def unknown():
        record_ambient_cost(MODEL, None)
        return [1.0]

    if capped:
        with pytest.raises(BadRequestError, match="priceable usage"):
            await _run(actor, identity, unknown)
    else:
        assert await _run(actor, identity, unknown) == [1.0]
    assert boundary.record.call_args.kwargs["cost_is_partial"] is True


async def test_keyless_endpoint_never_charges_caller(actor, identity, boundary):
    await _run(actor, replace(identity, key_organization_id=None), _paid)
    boundary.budget.assert_not_awaited()
    boundary.record.assert_not_awaited()


@pytest.mark.parametrize("phase", ["http", "close", "receipt"])
async def test_repeated_cancellation_keeps_owned_settlement(actor, identity, boundary, phase):
    entered, release = asyncio.Event(), asyncio.Event()

    async def request():
        if phase == "http":
            entered.set()
            await release.wait()
        result = await _paid()
        if phase == "close":
            entered.set()
            await release.wait()
        return result

    async def receipt(*_, **__):
        if phase == "receipt":
            entered.set()
            await release.wait()

    boundary.record.side_effect = receipt
    task = asyncio.create_task(_run(actor, identity, request))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    boundary.record.assert_awaited_once()
    assert boundary.committed.call_count == 2


async def test_receipt_failure_is_visible_no_automatic_http_replay(actor, identity, boundary):
    boundary.record.side_effect = RuntimeError("receipt unavailable")
    request = AsyncMock(side_effect=_paid)
    with pytest.raises(RuntimeError, match="receipt unavailable"):
        await _run(actor, identity, request)
    request.assert_awaited_once()


async def test_refreshed_context_does_not_expand_api_key_ceiling(monkeypatch, actor):
    admitted = replace(
        actor, api_key_id=uuid4(), key_scopes=frozenset({Perm.COLLECTIONS_EDIT}), key_internal=False
    )
    fresh = replace(
        admitted,
        key_scopes=frozenset({Perm.COLLECTIONS_EDIT, Perm.CONNECTIONS_VIEW}),
        key_internal=True,
    )
    monkeypatch.setattr(calls.ApiKeyService, "context_for_key", AsyncMock(return_value=fresh))
    result = await calls.current_probe_context(MagicMock(), admitted)
    assert result.key_scopes == admitted.key_scopes
    assert result.key_internal is True


async def test_revoked_key_refused(monkeypatch, actor):
    admitted = replace(actor, api_key_id=uuid4())
    monkeypatch.setattr(
        calls.ApiKeyService,
        "context_for_key",
        AsyncMock(side_effect=AuthorizationError(message="revoked")),
    )
    with pytest.raises(AuthorizationError):
        await calls.current_probe_context(MagicMock(), admitted)


@pytest.mark.parametrize("fallback", [True, False])
async def test_actor_without_member_identity_refused(actor, fallback):
    admitted = (
        replace(actor, user_id=None)
        if not fallback
        else replace(actor, subject_is_publisher_fallback=True)
    )
    with pytest.raises(AuthorizationError):
        await calls.current_probe_context(MagicMock(), admitted)


async def test_changed_key_issuer_refused(monkeypatch, actor):
    admitted = replace(actor, api_key_id=uuid4())
    monkeypatch.setattr(
        calls.ApiKeyService,
        "context_for_key",
        AsyncMock(return_value=replace(admitted, user_id=uuid4())),
    )
    with pytest.raises(AuthorizationError):
        await calls.current_probe_context(MagicMock(), admitted)


@pytest.mark.parametrize("app_admin", [True, False])
@pytest.mark.parametrize("removed", [True, False])
async def test_current_membership_rechecked(monkeypatch, actor, app_admin, removed):
    admitted = replace(actor, is_app_admin=app_admin)
    current = replace(actor, role=OrgRoleName.MEMBER.value, is_app_admin=False)
    refreshed = AsyncMock(return_value=None if removed else current)
    monkeypatch.setattr(calls, "decider_context" if app_admin else "member_context", refreshed)
    if removed:
        with pytest.raises(AuthorizationError):
            await calls.current_probe_context(MagicMock(), admitted)
    else:
        result = await calls.current_probe_context(MagicMock(), admitted)
        assert result.role == OrgRoleName.MEMBER.value
        assert result.is_app_admin is False


@pytest.mark.parametrize(
    "initial,current", [(None, None), (None, frozenset()), (frozenset(), None)]
)
async def test_unbounded_scope_intersection(monkeypatch, actor, initial, current):
    admitted = replace(actor, api_key_id=uuid4(), key_scopes=initial)
    monkeypatch.setattr(
        calls.ApiKeyService,
        "context_for_key",
        AsyncMock(return_value=replace(admitted, key_scopes=current)),
    )
    result = await calls.current_probe_context(MagicMock(), admitted)
    assert result.key_scopes == (current if initial is None else initial)


async def test_cancelled_receipt_failure_retained_with_cancellation(actor, identity, boundary):
    entered, release = asyncio.Event(), asyncio.Event()

    async def receipt(*_, **__):
        entered.set()
        await release.wait()
        raise RuntimeError("receipt failed")

    boundary.record.side_effect = receipt
    task = asyncio.create_task(_run(actor, identity))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(BaseExceptionGroup) as failure:
        await task
    assert [type(error) for error in failure.value.exceptions] == [
        asyncio.CancelledError,
        RuntimeError,
    ]


@pytest.mark.parametrize(
    "initial,current", [(True, False), (False, True), (True, True), (False, False)]
)
async def test_internal_credential_restriction_is_never_dropped(
    monkeypatch, actor, initial, current
):
    admitted = replace(actor, api_key_id=uuid4(), key_internal=initial)
    monkeypatch.setattr(
        calls.ApiKeyService,
        "context_for_key",
        AsyncMock(return_value=replace(admitted, key_internal=current)),
    )
    refreshed = await calls.current_probe_context(MagicMock(), admitted)
    assert refreshed.key_internal is (initial or current)


async def test_call_deadline_is_controlled_and_unknown_usage_retained(
    actor, identity, boundary, monkeypatch
):
    monkeypatch.setattr(calls, "CALL_SETTLEMENT_SECONDS", 0)
    boundary.organization.monthly_budget_usd = None

    async def waiting():
        await asyncio.Event().wait()
        return [1.0]

    with pytest.raises(EmbeddingProbeError) as failure:
        await _run(actor, identity, waiting)
    assert failure.value.outcome == "unreachable"
    assert boundary.record.call_args.kwargs["cost_is_partial"] is True


async def test_programming_timeout_is_not_misclassified(actor, identity, boundary):
    async def broken():
        raise TimeoutError("internal bug")

    with pytest.raises(TimeoutError, match="internal bug"):
        await _run(actor, identity, broken)


async def test_deadline_after_known_response_retains_known_usage(
    actor, identity, boundary, monkeypatch
):
    monkeypatch.setattr(calls, "CALL_SETTLEMENT_SECONDS", 0)

    async def closing():
        await _paid()
        await asyncio.Event().wait()
        return [1.0]

    with pytest.raises(EmbeddingProbeError):
        await _run(actor, identity, closing)
    assert boundary.record.call_args.kwargs["cost_usd"] == Decimal("0.00000016")


async def test_concurrent_probes_do_not_share_receipts(actor, identity, boundary):
    ready = asyncio.Event()
    count = 0

    async def request(tokens):
        nonlocal count
        record_ambient_usage(MODEL, RequestUsage(input_tokens=tokens), "openai")
        count += 1
        if count == 2:
            ready.set()
        await ready.wait()
        return [1.0]

    await asyncio.gather(
        _run(actor, identity, lambda: request(8)), _run(actor, identity, lambda: request(16))
    )
    assert sorted(row.kwargs["input_tokens"] for row in boundary.record.call_args_list) == [8, 16]
