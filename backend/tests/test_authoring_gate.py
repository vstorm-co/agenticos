"""When a change of model may be accepted: only once a check of exactly what is
accepted - the draft with every suggestion still waiting made - shows it pays off."""

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, NotFoundError
from app.db.models.eval_run import ArmRole
from app.repositories import eval_run_repo
from app.services.authoring import AuthoringService
from app.services.eval_run import EvalRunService, spec_hash

pytestmark = pytest.mark.anyio

MODEL = str(uuid.uuid4())
COMBINATION = AgentSpec(name="Clerk", instructions="Answer refunds.", model_profile_id=MODEL)


def _run(
    *,
    status: str = "completed",
    verdict: str | None = "better",
    regressions: int = 0,
    ungraded: int = 0,
    incomplete: int = 0,
    crashed: int = 0,
    outcome: bool = True,
    checked: AgentSpec = COMBINATION,
) -> Any:
    decided = SimpleNamespace(incomplete=0, ungraded=0, crashed=0)
    return SimpleNamespace(
        status=status,
        proposal_check=None,
        arms=[
            SimpleNamespace(id=uuid.uuid4(), role=ArmRole.BASELINE, summary=decided),
            SimpleNamespace(
                id=uuid.uuid4(),
                role=ArmRole.CANDIDATE,
                summary=SimpleNamespace(incomplete=incomplete, ungraded=ungraded, crashed=crashed),
                spec_hash=spec_hash(checked),
            ),
        ],
        outcome=SimpleNamespace(verdict=verdict, regressions_confirmed=regressions)
        if outcome
        else None,
    )


async def _gate(monkeypatch, mock_db_session, runs: list[Any], *, model: str = MODEL) -> str | None:
    by_id = {uuid.uuid4(): run for run in runs}

    async def get(_self: Any, _ctx: Any, run_id: uuid.UUID) -> Any:
        found = by_id[run_id]
        if isinstance(found, Exception):
            raise found
        return found

    monkeypatch.setattr(EvalRunService, "get", get)
    monkeypatch.setattr(
        eval_run_repo,
        "get_arm",
        AsyncMock(return_value=SimpleNamespace(spec={"model_profile_id": model})),
    )
    batch = SimpleNamespace(check_eval_run_ids=list(by_id))
    ctx = SimpleNamespace(organization_id=uuid.uuid4())
    return await AuthoringService(mock_db_session)._model_gate(ctx, batch, COMBINATION)


@pytest.mark.parametrize(
    ("run", "reason"),
    [
        (_run(), None),
        (_run(verdict="no_difference"), None),
        (_run(verdict="worse"), "regression"),
        (_run(verdict="mixed"), "regression"),
        (_run(regressions=1), "regression"),
        (_run(verdict="invalid"), "inconclusive"),
        (_run(verdict=None), "inconclusive"),
        (_run(ungraded=2), "inconclusive"),
        (_run(incomplete=1), "inconclusive"),
        (_run(crashed=1), "crashed"),
        (_run(regressions=1, ungraded=2), "regression"),
        (_run(outcome=False), "inconclusive"),
    ],
)
async def test_the_latest_check_of_this_model_decides(monkeypatch, mock_db_session, run, reason):
    assert await _gate(monkeypatch, mock_db_session, [run]) == reason


async def test_a_check_still_running_or_unreadable_is_no_check_at_all(monkeypatch, mock_db_session):
    runs = [
        _run(),
        _run(status="running"),
        AuthorizationError(message="no"),
        NotFoundError(message="gone"),
    ]
    # The latest readable, finished check is the first one, which paid off.
    assert await _gate(monkeypatch, mock_db_session, runs) is None
    assert await _gate(monkeypatch, mock_db_session, runs[1:]) == "check_first"
    assert await _gate(monkeypatch, mock_db_session, []) == "check_first"


async def test_a_check_of_another_model_does_not_count(monkeypatch, mock_db_session):
    assert await _gate(monkeypatch, mock_db_session, [_run()], model=str(uuid.uuid4())) == (
        "check_first"
    )


async def test_a_check_without_its_candidate_or_its_spec_does_not_count(
    monkeypatch, mock_db_session
):
    lonely = _run()
    lonely.arms = lonely.arms[:1]
    assert await _gate(monkeypatch, mock_db_session, [lonely]) == "check_first"
    monkeypatch.setattr(EvalRunService, "get", AsyncMock(return_value=_run()))
    monkeypatch.setattr(eval_run_repo, "get_arm", AsyncMock(return_value=None))
    batch = SimpleNamespace(check_eval_run_ids=[uuid.uuid4()])
    ctx = SimpleNamespace(organization_id=uuid.uuid4())
    gate = await AuthoringService(mock_db_session)._model_gate(ctx, batch, COMBINATION)
    assert gate == "check_first"


async def test_a_check_of_another_combination_is_out_of_date(monkeypatch, mock_db_session):
    moved = COMBINATION.model_copy(update={"instructions": "Answer refunds briefly."})

    assert await _gate(monkeypatch, mock_db_session, [_run(checked=moved)]) == "check_outdated"
    # The latest check of exactly this combination decides, however many came before.
    runs = [_run(), _run(checked=moved)]
    assert await _gate(monkeypatch, mock_db_session, runs) is None
