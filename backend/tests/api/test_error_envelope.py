"""Everything a client can be refused with leaves the API in one shape.

There used to be two. Domain refusals came back as
`{"error": {"code", "message", "details"}}`; schema validation came back as
FastAPI's own `{"detail": [...]}`. A client written against one shape does not
fail loudly on the other - it silently reads nothing, which is how a duplicate
name reached the browser as "Request failed" and a 422 reached it as the string
form of a list of dicts.

The tests here pin the envelope itself rather than any one endpoint, because the
value of a single shape is entirely in it being the only one. The last class pins
the other half of that claim: a shape the caller never receives is not a shape.
Its vehicle is `GET /users/avatar/{user_id}`, the one route that reaches a
service without authenticating first - the handler it exercises is global.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.exceptions import RequestValidationError
from httpx import AsyncClient

from app.agents.capabilities.budget import BudgetExceeded, BudgetScope
from app.api import deps
from app.api.exception_handlers import (
    _field_path,
    _summarize,
    budget_exceeded_handler,
    validation_exception_handler,
)
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.main import app
from app.repositories import user_repo
from app.schemas.message_rating import RatingValue


class TestFieldPath:
    """The path a form has to be able to match against its own inputs."""

    @pytest.mark.parametrize(
        ("location", "expected"),
        [
            (("body", "name"), "name"),
            # The Builder posts the whole spec under one key; the field a person
            # is looking at is the leaf, and the path has to reach it.
            (("body", "spec", "name"), "spec.name"),
            (("query", "limit"), "limit"),
            # An index is the most useful part of the path when a list is
            # rejected - "the third capability", not "a capability".
            (("body", "spec", "capabilities", 2, "id"), "spec.capabilities.2.id"),
            # A body that is not an object at all belongs to no field.
            (("body",), "request"),
        ],
    )
    def test_the_origin_is_dropped_and_the_rest_is_a_dotted_path(self, location, expected):
        assert _field_path(location) == expected

    def test_an_unrecognised_origin_is_kept(self):
        """Dropping a leading segment we do not recognise would lose the field."""
        assert _field_path(("name",)) == "name"


class TestSummary:
    """The one line a client with nowhere better to put it can still show."""

    def test_a_single_problem_reads_as_a_sentence(self):
        assert (
            _summarize([{"field": "name", "message": "String should have at most 128 characters"}])
            == "name: String should have at most 128 characters"
        )

    def test_several_problems_name_the_fields(self):
        """Not "the request was invalid" - the reader needs to know where to look."""
        summary = _summarize(
            [
                {"field": "email", "message": "not a valid email address"},
                {"field": "password", "message": "String should have at least 8 characters"},
            ]
        )
        assert summary == "Some fields need fixing: email, password"


class TestValidationEnvelope:
    @pytest.mark.anyio
    async def test_a_rejected_body_reports_every_field_at_once(self, client: AsyncClient):
        """One round trip per mistake is the difference between a form and a fight.

        Registration is used because it is the one route that validates a body
        without authentication; the handler under test is global.
        """
        response = await client.post(
            f"{settings.API_V1_STR}/auth/register",
            json={"email": "nope", "password": "x"},
        )

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert [field["field"] for field in error["details"]["fields"]] == ["email", "password"]
        assert "at least 8 characters" in error["details"]["fields"][1]["message"]

    @pytest.mark.anyio
    async def test_a_validation_failure_is_not_shaped_like_a_break(self, client: AsyncClient):
        """`detail` is what an unhandled 500 and a bad password used to share.

        Anything still reading `detail` off a 422 is reading the old shape, and
        the point of this change is that there is no longer one to read.
        """
        response = await client.post(
            f"{settings.API_V1_STR}/auth/register",
            json={"email": "nope", "password": "x"},
        )
        assert "detail" not in response.json()

    @pytest.mark.anyio
    async def test_the_summary_survives_to_the_wire(self, client: AsyncClient):
        response = await client.post(
            f"{settings.API_V1_STR}/auth/register",
            json={"email": "nope", "password": "x"},
        )
        assert response.json()["error"]["message"] == "Some fields need fixing: email, password"

    @pytest.mark.anyio
    async def test_a_budget_refusal_is_a_4xx_in_the_same_envelope(self):
        """`BudgetExceeded` reaching HTTP is the platform working - a document
        upload against a spent cap - and a 500 would tell the operator
        something crashed when the correct reading is "raise the limit or wait
        for the first of the month"."""

        class _Connection:
            scope = {"type": "http"}
            method = "POST"

            class url:
                path = "/api/v1/rag/documents"

        response = await budget_exceeded_handler(
            _Connection(),  # ty: ignore[invalid-argument-type]
            BudgetExceeded(
                limit_usd=Decimal("40"), spent_usd=Decimal("41.5"), scope=BudgetScope.ORGANIZATION
            ),
        )

        assert response is not None
        assert response.status_code == 402
        body = response.body.decode()
        assert '"BUDGET_EXCEEDED"' in body
        assert "Organization monthly budget exhausted" in body

    @pytest.mark.anyio
    async def test_a_budget_refusal_on_a_websocket_scope_writes_no_body(self):
        class _Connection:
            scope = {"type": "websocket"}

            class url:
                path = "/ws"

        refused = await budget_exceeded_handler(
            _Connection(),  # ty: ignore[invalid-argument-type]
            BudgetExceeded(limit_usd=Decimal("1"), spent_usd=Decimal("1"), scope=BudgetScope.AGENT),
        )

        assert refused is None

    @pytest.mark.anyio
    async def test_the_handler_answers_a_websocket_scope_with_nothing(self):
        """Shared with the domain handler, and it cannot write an HTTP body.

        Reached only because both handlers are registered on the same app; a
        `RequestValidationError` on a socket is not a thing Starlette raises,
        but the delegation means the branch exists and has to be right.
        """

        class _Connection:
            scope = {"type": "websocket"}

            class url:
                path = "/ws"

        exc = RequestValidationError([{"type": "missing", "loc": ("body", "x"), "msg": "Required"}])
        assert await validation_exception_handler(_Connection(), exc) is None  # ty: ignore[invalid-argument-type]


class TestDetailsSurviveSerialization:
    """A refusal that cannot be serialized is a refusal nobody is told about.

    `details` is where a service puts the thing it is refusing over - the id it
    could not find, the moment a token expired, the cap that was spent. The
    handler used to hand that dictionary to `json.dumps`, which raises on a
    `UUID`, so the handler died on the way out and the caller got a bodiless 500
    for what the log had already recorded as a clean 404 (#307).
    """

    @pytest.mark.anyio
    async def test_a_missing_user_is_a_404_carrying_the_id_it_could_not_find(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        """The everyday reproduction: a session kept across a database reset.

        Whole-stack on purpose - route, service and handler - because the defect
        was not in what the service raised but in what happened to it afterwards.
        """
        monkeypatch.setattr(user_repo, "get_by_id", AsyncMock(return_value=None))
        user_id = uuid4()

        response = await client.get(f"{settings.API_V1_STR}/users/avatar/{user_id}")

        assert response.status_code == 404
        assert response.json() == {
            "error": {
                "code": "NOT_FOUND",
                "message": "User not found",
                "details": {"user_id": str(user_id)},
            }
        }

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param(
                UUID("0e2e0f04-2a99-4c5b-8b3f-96f1a2a1b0d1"),
                "0e2e0f04-2a99-4c5b-8b3f-96f1a2a1b0d1",
                id="uuid",
            ),
            pytest.param(
                datetime(2026, 8, 6, 12, 30, tzinfo=UTC), "2026-08-06T12:30:00+00:00", id="datetime"
            ),
            # Lossy, and the reason the budget handler stringifies money itself
            # before it ever reaches here.
            pytest.param(Decimal("41.50"), 41.5, id="decimal"),
            pytest.param(RatingValue.DISLIKE, -1, id="enum"),
            pytest.param(Path("/workspace/report.pdf"), "/workspace/report.pdf", id="path"),
            pytest.param(
                {"rows": [{"id": UUID("11111111-1111-1111-1111-111111111111")}]},
                {"rows": [{"id": "11111111-1111-1111-1111-111111111111"}]},
                id="nested",
            ),
        ],
    )
    @pytest.mark.anyio
    async def test_details_carry_what_a_service_naturally_holds(
        self, client: AsyncClient, value: Any, expected: Any
    ):
        """Not only `UUID`: the encoder's reach is the whole point of fixing it once."""
        service = MagicMock()
        service.get_by_id = AsyncMock(
            side_effect=NotFoundError(message="User not found", details={"value": value})
        )
        app.dependency_overrides[deps.get_user_service] = lambda: service

        response = await client.get(f"{settings.API_V1_STR}/users/avatar/{uuid4()}")

        assert response.status_code == 404
        assert response.json()["error"]["details"] == {"value": expected}

    @pytest.mark.anyio
    async def test_a_set_of_scopes_arrives_as_a_list(self, client: AsyncClient):
        """`json.dumps` refuses a set as flatly as it refuses a `UUID`."""
        service = MagicMock()
        service.get_by_id = AsyncMock(
            side_effect=NotFoundError(
                message="User not found", details={"scopes": {"agents:edit", "agents:read"}}
            )
        )
        app.dependency_overrides[deps.get_user_service] = lambda: service

        response = await client.get(f"{settings.API_V1_STR}/users/avatar/{uuid4()}")

        assert response.status_code == 404
        assert sorted(response.json()["error"]["details"]["scopes"]) == [
            "agents:edit",
            "agents:read",
        ]

    @pytest.mark.anyio
    async def test_an_unencodable_value_fails_here_rather_than_on_the_wire(
        self, client: AsyncClient
    ):
        """No silent fallback: a payload nothing can encode is a bug in the raiser.

        Answering with the field quietly dropped would hide it in exactly the
        place a person goes looking for the reason something was refused.
        """
        service = MagicMock()
        service.get_by_id = AsyncMock(
            side_effect=NotFoundError(message="User not found", details={"open": object()})
        )
        app.dependency_overrides[deps.get_user_service] = lambda: service

        with pytest.raises(ValueError):
            await client.get(f"{settings.API_V1_STR}/users/avatar/{uuid4()}")

    @pytest.mark.anyio
    async def test_a_budget_refusal_keeps_its_money_exact(self):
        """`jsonable_encoder` answers a `Decimal` with a float; a cap is not a
        thing to round on the way out, so the handler stringifies it first."""

        class _Connection:
            scope = {"type": "http"}
            method = "POST"

            class url:
                path = "/api/v1/rag/documents"

        response = await budget_exceeded_handler(
            _Connection(),  # ty: ignore[invalid-argument-type]
            BudgetExceeded(
                limit_usd=Decimal("40.10"),
                spent_usd=Decimal("40.15"),
                scope=BudgetScope.ORGANIZATION,
            ),
        )

        assert response is not None
        details = json.loads(response.body)["error"]["details"]
        assert details == {
            "scope": "organization",
            "limit_usd": "40.10",
            "spent_usd": "40.15",
        }
