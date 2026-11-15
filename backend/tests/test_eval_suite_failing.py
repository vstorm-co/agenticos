"""The cases a suite result names, each as its attempts settled rather than as it first came out."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.eval_suite import EvalSuiteService

pytestmark = pytest.mark.anyio

ARM = uuid.uuid4()


def _try(attempt: int, outcome: bool | None, state: str = "passed") -> SimpleNamespace:
    return SimpleNamespace(arm_id=ARM, attempt=attempt, outcome=outcome, state=state, score=None)


def _case(text: str, *attempts: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(case_id=uuid.uuid4(), input=text, attempts=list(attempts))


async def test_a_case_whose_tries_tied_is_named_undecided_whichever_way_it_first_went() -> None:
    service = EvalSuiteService(MagicMock())
    listed = [
        _case("Passed, then failed", _try(0, True), _try(1, False)),
        _case("Failed, then passed", _try(0, False, "failed"), _try(1, True)),
        _case("Failed twice", _try(0, False, "failed"), _try(1, False)),
        _case("Nothing grades it", _try(0, None, "ungraded")),
        _case("Passed", _try(0, True)),
    ]
    service.evals = SimpleNamespace(cases=AsyncMock(return_value=SimpleNamespace(items=listed)))
    comparison = SimpleNamespace(cases=[], candidate=SimpleNamespace(arm_id=ARM))

    named = await service._failing(
        MagicMock(), SimpleNamespace(id=uuid.uuid4(), cases=5), comparison
    )

    assert [(case.input, case.kind) for case in named] == [
        ("Passed, then failed", "incomplete"),
        ("Failed, then passed", "incomplete"),
        ("Nothing grades it", "ungraded"),
        ("Failed twice", "failed"),
    ]
