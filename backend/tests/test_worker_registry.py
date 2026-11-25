"""How handlers are bound and how a failure is written down (#2219)."""

from collections.abc import Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import BaseModel
from pydantic_ai.exceptions import ModelHTTPError

from app.core.exceptions import BadRequestError
from app.worker.errors import _MESSAGE_LIMIT, describe
from app.worker.handlers import _each_tick
from app.worker.jobs import Tick
from app.worker.registry import Handler, by_kind
from tests import worker_handlers

pytestmark = pytest.mark.anyio


def test_two_handlers_for_one_kind_are_refused_rather_than_the_second_winning() -> None:
    ok = worker_handlers.tasks()["ok"]
    with pytest.raises(ValueError, match="two handlers for the job kind 'test-ok'"):
        by_kind([Handler(ok, worker_handlers.succeed), Handler(ok, worker_handlers.fail)])


def _raise_long() -> None:
    raise BadRequestError(message="x" * (_MESSAGE_LIMIT + 50))


def test_a_long_message_is_cut_and_says_so() -> None:
    with pytest.raises(BadRequestError) as caught:
        _raise_long()

    described = describe(caught.value)

    assert described.splitlines()[0] == f"BadRequestError: {'x' * _MESSAGE_LIMIT}..."
    assert "in _raise_long" in described


def _caught(raise_it: Callable[[], None]) -> BaseException:
    try:
        raise_it()
    except Exception as exc:
        return exc
    raise AssertionError("nothing was raised")


def _status_error() -> None:
    request = httpx.Request("GET", "https://api.example.com/v1/x?api_key=Kanar3kJobKey")
    response = httpx.Response(502, request=request)
    raise httpx.HTTPStatusError("Bad gateway", request=request, response=response)


def _provider_error() -> None:
    raise ModelHTTPError(500, "gpt-test", body={"error": "Kanar3kBody in the prompt"})


class _Payload(BaseModel):
    days: int


def _invalid_payload() -> None:
    _Payload.model_validate({"days": "Kanar3kValue"})


@pytest.mark.security
@pytest.mark.parametrize(
    ("raise_it", "kind"),
    [
        (_status_error, "HTTPStatusError"),
        (_provider_error, "ModelHTTPError"),
        (_invalid_payload, "ValidationError"),
    ],
)
def test_a_vendor_message_stays_in_the_log_and_off_the_row(
    raise_it: Callable[[], None], kind: str
) -> None:
    described = describe(_caught(raise_it))

    assert described.startswith(f"{kind}: ")
    assert "Kanar3k" not in described and "api.example.com" not in described
    assert f"in {raise_it.__name__}" in described


def test_a_validation_error_names_the_fields_that_failed() -> None:
    described = describe(_caught(_invalid_payload))

    assert described.splitlines()[0] == "ValidationError: 1 invalid field(s): days"


async def test_a_sweep_runs_on_each_tick_whatever_occurrence_it_is() -> None:
    sweep = AsyncMock(return_value=3)

    assert await _each_tick(sweep)(Tick(scheduled_for=datetime.now(UTC))) == 3
    sweep.assert_awaited_once_with()
