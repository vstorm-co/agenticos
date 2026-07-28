"""Everything a client can be refused with leaves the API in one shape.

There used to be two. Domain refusals came back as
``{"error": {"code", "message", "details"}}``; schema validation came back as
FastAPI's own ``{"detail": [...]}``. A client written against one shape does not
fail loudly on the other - it silently reads nothing, which is how a duplicate
name reached the browser as "Request failed" and a 422 reached it as the string
form of a list of dicts.

The tests here pin the envelope itself rather than any one endpoint, because the
value of a single shape is entirely in it being the only one.
"""

from __future__ import annotations

import pytest
from fastapi.exceptions import RequestValidationError
from httpx import AsyncClient

from app.api.exception_handlers import _field_path, _summarize, validation_exception_handler
from app.core.config import settings


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
