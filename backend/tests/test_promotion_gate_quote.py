"""A quoted gate run starts exactly the guards it priced, from one reading of the gate."""

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import ConcurrentChangeError
from app.core.permissions import AuthContext
from app.schemas.promotion_gate import PromotionGateRun
from app.services.promotion_gate import PromotionGateService

pytestmark = pytest.mark.anyio

SUITE, SETTLED_MEANWHILE, VERSION = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
CTX = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")


def _reading(*due: uuid.UUID, checking: uuid.UUID | None = None) -> SimpleNamespace:
    guards = [SimpleNamespace(suite_id=suite, state="failed") for suite in due]
    if checking is not None:
        guards.append(SimpleNamespace(suite_id=checking, state="checking"))
    return SimpleNamespace(guards=guards)


@pytest.fixture
def suites(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    price = AsyncMock(return_value=Decimal("0.50"))
    start = AsyncMock()
    monkeypatch.setattr("app.services.eval_suite.EvalSuiteService.price_on_version", price)
    monkeypatch.setattr("app.services.eval_suite.EvalSuiteService.run_on_version", start)
    monkeypatch.setattr("app.services.promotion_gate.PromotionGateRunRead", lambda **kwargs: kwargs)
    return SimpleNamespace(price=price, start=start)


def _gate(monkeypatch: pytest.MonkeyPatch, *readings: Any) -> PromotionGateService:
    service = PromotionGateService(MagicMock())
    agent = SimpleNamespace(id=uuid.uuid4(), organization_id=CTX.organization_id)
    monkeypatch.setattr(
        service, "_target", AsyncMock(return_value=(agent, MagicMock(), MagicMock()))
    )
    monkeypatch.setattr(service, "_serving_version", AsyncMock(return_value=6))
    monkeypatch.setattr(service, "check", AsyncMock(side_effect=list(readings)))
    return service


@pytest.mark.security
async def test_a_run_dearer_than_its_quote_starts_nothing(
    monkeypatch: pytest.MonkeyPatch, suites: SimpleNamespace
) -> None:
    gate = _gate(monkeypatch, _reading(SUITE))

    with pytest.raises(ConcurrentChangeError):
        await gate.run(CTX, uuid.uuid4(), uuid.uuid4(), _run(Decimal("0.40")))

    suites.start.assert_not_awaited()


@pytest.mark.security
async def test_the_guards_priced_are_the_guards_started_whatever_settles_meanwhile(
    monkeypatch: pytest.MonkeyPatch, suites: SimpleNamespace
) -> None:
    """A guard still checking when the gate was read is neither priced nor started,
    even if it has failed by the time the response reads the gate again."""
    gate = _gate(
        monkeypatch,
        _reading(SUITE, checking=SETTLED_MEANWHILE),
        _reading(SUITE, SETTLED_MEANWHILE),
    )

    ran = await gate.run(CTX, uuid.uuid4(), uuid.uuid4(), _run(Decimal("0.50")))

    assert ran["started"] == [SUITE]
    assert [call.args[2] for call in suites.price.await_args_list] == [SUITE]
    assert [call.args[2] for call in suites.start.await_args_list] == [SUITE]


async def test_an_unquoted_run_prices_nothing(
    monkeypatch: pytest.MonkeyPatch, suites: SimpleNamespace
) -> None:
    gate = _gate(monkeypatch, _reading(SUITE), _reading())

    ran = await gate.run(CTX, uuid.uuid4(), uuid.uuid4(), _run(None))

    assert ran["started"] == [SUITE]
    suites.price.assert_not_awaited()


def _run(quoted: Decimal | None) -> PromotionGateRun:
    return PromotionGateRun(version_id=VERSION, quoted_usd=quoted)
