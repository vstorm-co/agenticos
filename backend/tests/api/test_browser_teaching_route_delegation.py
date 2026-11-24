"""Each browser-teaching route hands the caller, the session and the revision to the service.

The service's own refusals are covered against a real database; here the service
is replaced by one that records what it was asked, so the test shows what a route
passes on and what request bodies are refused before reaching it.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.api import deps
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.browser_teaching import (
    TeachingChange,
    TeachingPropose,
    TeachingReview,
    TeachingStart,
)

pytestmark = pytest.mark.anyio

SESSION = uuid.uuid4()
ORIGIN = "https://portal.example.com"


def _read() -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": SESSION,
        "agent_id": uuid.uuid4(),
        "run_id": uuid.uuid4(),
        "call_id": "call-1",
        "tab_id": "main",
        "title": "Download invoice",
        "allowed_origins": (ORIGIN,),
        "status": "review",
        "revision": 4,
        "reason_code": None,
        "events": (),
        "review": (),
        "parameters": (),
        "proposal_name": None,
        "proposal_id": None,
        "created_at": now,
        "capture_ends_at": now,
        "expires_at": now,
    }


class _Service:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def _answer(self, name: str, *args: Any) -> dict[str, Any]:
        self.calls.append((name, args))
        return _read()

    async def get(self, *args: Any) -> dict[str, Any]:
        return self._answer("get", *args)

    async def start(self, *args: Any) -> dict[str, Any]:
        return self._answer("start", *args)

    async def review(self, *args: Any) -> dict[str, Any]:
        return self._answer("review", *args)

    async def change(self, *args: Any) -> dict[str, Any]:
        return self._answer("change", *args)

    async def propose(self, *args: Any) -> dict[str, Any]:
        return self._answer("propose", *args)

    async def stop(self, *args: Any) -> dict[str, Any]:
        return self._answer("stop", *args)

    async def discard(self, *args: Any) -> None:
        self._answer("discard", *args)


@pytest.fixture
def service() -> Iterator[_Service]:
    fake = _Service()
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.BUILDER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_browser_teaching_service] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


async def _call(method: str, path: str = "", **kwargs: Any) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        return await http.request(method, f"/api/v1/browser-teachings{path}", **kwargs)


async def test_reading_a_session_asks_for_that_session(service: _Service) -> None:
    response = await _call("GET", f"/{SESSION}")
    assert response.status_code == 200
    assert response.json()["id"] == str(SESSION)
    assert service.calls[0][0] == "get" and service.calls[0][1][1] == SESSION


@pytest.mark.parametrize(
    ("body", "name"),
    [
        ({"action": "pause"}, "change"),
        ({"action": "review", "steps": [{"sequence": 1, "parameter": "invoice"}]}, "review"),
    ],
)
async def test_a_patch_goes_to_review_or_change_with_the_revision_from_if_match(
    service: _Service, body: dict[str, Any], name: str
) -> None:
    response = await _call("PATCH", f"/{SESSION}", json=body, headers={"If-Match": '"4"'})
    assert response.status_code == 200
    called, args = service.calls[0]
    assert called == name and args[1] == SESSION and args[3] == 4


async def test_a_patch_without_if_match_names_no_revision(service: _Service) -> None:
    await _call("PATCH", f"/{SESSION}", json={"action": "resume"})
    assert service.calls[0][1][3] is None


async def test_proposing_passes_the_name_and_the_revision(service: _Service) -> None:
    response = await _call(
        "POST", f"/{SESSION}/propose", json={"name": "download-invoice"}, headers={"If-Match": "7"}
    )
    assert response.status_code == 202
    _, args = service.calls[0]
    assert args[2].name == "download-invoice" and args[3] == 7


async def test_stopping_returns_the_review_state(service: _Service) -> None:
    response = await _call("POST", f"/{SESSION}/stop")
    assert response.status_code == 200 and response.json()["status"] == "review"
    assert service.calls[0][0] == "stop"


async def test_discarding_answers_no_content(service: _Service) -> None:
    response = await _call("DELETE", f"/{SESSION}")
    assert response.status_code == 204 and response.content == b""
    assert service.calls[0][0] == "discard"


async def test_starting_hands_over_the_idempotency_key(service: _Service) -> None:
    body = {
        "run_id": str(uuid.uuid4()),
        "call_id": "call-1",
        "title": "Download invoice",
        "allowed_origins": [ORIGIN],
    }
    response = await _call("POST", json=body, headers={"Idempotency-Key": "retry-1"})
    assert response.status_code == 201
    assert service.calls[0][1][2] == "retry-1"


@pytest.mark.parametrize("title", ["   ", "two\nlines", "bell\x07", "del\x7f"])
def test_a_title_must_be_short_plain_text(title: str) -> None:
    with pytest.raises(ValidationError):
        TeachingStart(run_id=uuid.uuid4(), call_id="c", title=title, allowed_origins=(ORIGIN,))


def test_an_origin_listed_twice_in_two_spellings_is_refused() -> None:
    with pytest.raises(ValidationError):
        TeachingStart(
            run_id=uuid.uuid4(),
            call_id="c",
            title="Download",
            allowed_origins=(ORIGIN, "https://PORTAL.example.com:443"),
        )


def test_a_title_is_stored_without_its_surrounding_spaces() -> None:
    start = TeachingStart(
        run_id=uuid.uuid4(), call_id="c", title="  Download  ", allowed_origins=(ORIGIN,)
    )
    assert start.title == "Download"
    assert TeachingChange(action="pause").action == "pause"
    assert TeachingReview(action="review", steps=()).steps == ()


@pytest.mark.parametrize("name", ["Download Invoice", "-lead", "x" * 65])
def test_a_proposal_name_the_skill_catalog_refuses_is_refused(name: str) -> None:
    with pytest.raises(ValidationError):
        TeachingPropose(name=name)


def test_a_review_names_each_step_once_and_keeps_them_in_sequence() -> None:
    with pytest.raises(ValidationError):
        TeachingReview(action="review", steps=({"sequence": 1}, {"sequence": 1}))  # type: ignore[arg-type]
    review = TeachingReview(
        action="review",
        steps=({"sequence": 3}, {"sequence": 1}),  # type: ignore[arg-type]
    )
    assert [step.sequence for step in review.steps] == [1, 3]


def test_a_review_with_more_than_twenty_parameters_is_refused() -> None:
    steps = tuple({"sequence": number, "parameter": f"field_{number}"} for number in range(1, 22))
    with pytest.raises(ValidationError):
        TeachingReview(action="review", steps=steps)  # type: ignore[arg-type]
    assert len(TeachingReview(action="review", steps=steps[:20]).steps) == 20  # type: ignore[arg-type]
