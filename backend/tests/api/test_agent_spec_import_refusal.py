"""A hand-edited spec YAML, through the app.

What the spec's own field rules say is covered by `tests/test_agent_spec_and_factory.py`;
what is asserted here is how a mistake in a spec *arrives*. A pydantic
`ValidationError` is a `ValueError` but not a `RequestValidationError`, and
`app/api/exception_handlers.py` maps neither `ValueError` nor `yaml.YAMLError` - so
every kind of mistake in an imported file used to answer 500 "An unexpected error
occurred" with `details: null` and a traceback in the log, for the endpoint whose
ordinary case is somebody editing YAML by hand and iterating (#873).

The service is the real one; only the session and Redis are mocked. The parse
refuses before the agent is read, so nothing here reaches the database.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio

_AGENT_ID = uuid.uuid4()

# A spec carrying the two things a spec carries that must never come back in a
# refusal: a block of instructions and a reference somebody named.
_SECRETIVE_YAML = """
name: Support
instructions: |
  Escalate to legal@example.com and quote contract ACME-9981.
capabilities:
  - id: clock
    secret_id: 3f7c2c58-0000-4000-8000-000000000001
  bad indent here
"""


@pytest.fixture
def client(mock_db_session: Any, mock_redis: MagicMock) -> Iterator[Any]:
    user = MagicMock()
    user.id = uuid.uuid4()
    context = AuthContext(user_id=user.id, organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)
    app.dependency_overrides[deps.get_db_session] = lambda: mock_db_session
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_auth_context] = lambda: context

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


async def _import(client: Any, text: str) -> Any:
    async with client() as opened:
        return await opened.post(
            f"{settings.API_V1_STR}/agents/{_AGENT_ID}/spec.yaml", json={"yaml": text}
        )


class TestTheRefusalNamesTheField:
    async def test_a_field_that_breaks_a_rule_is_refused_with_a_400_naming_it(
        self, client: Any
    ) -> None:
        """The example from #873, which answered 500 on `main`."""
        response = await _import(client, "capabilities: [not_a_capability]\n")

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == "BAD_REQUEST"
        assert [problem["field"] for problem in error["details"]["fields"]] == [
            "name",
            "capabilities.0",
        ]

    async def test_a_typo_in_a_field_name_names_the_key_it_could_not_place(
        self, client: Any
    ) -> None:
        """`extra="forbid"` is what makes a spec strict; the caller has to be
        told *which* key it refused, or strictness is just a rejection."""
        response = await _import(client, "name: Support\ninstrucitons: be helpful\n")

        assert response.status_code == 400
        problems = response.json()["error"]["details"]["fields"]
        assert problems == [{"field": "instrucitons", "message": "Extra inputs are not permitted"}]

    async def test_a_document_that_is_a_list_is_refused_with_the_reason(self, client: Any) -> None:
        """Pydantic reports a list as an unhelpful type error, which is why
        `from_yaml` refuses it itself - and that message is ours to surface."""
        response = await _import(client, "- a\n- b\n")

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == "BAD_REQUEST"
        assert error["message"] == "An agent spec must be a YAML mapping"
        assert error["details"] == {"field": "yaml"}

    async def test_yaml_that_does_not_parse_is_refused_with_the_position(self, client: Any) -> None:
        response = await _import(client, "name: Support\n  description: adrift\n")

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == "BAD_REQUEST"
        assert error["details"] == {"field": "yaml", "line": 2, "column": 14}

    async def test_a_character_yaml_cannot_read_has_no_position_to_report(
        self, client: Any
    ) -> None:
        """A `ReaderError` carries a byte offset and no mark, so the field is
        named and nothing is invented for the line."""
        response = await _import(client, "name: Sup\x00port\n")

        assert response.status_code == 400
        assert response.json()["error"]["details"] == {"field": "yaml"}


class TestTheRefusalQuotesNothingSubmitted:
    async def test_neither_the_instructions_nor_a_secret_reference_come_back(
        self, client: Any
    ) -> None:
        """A spec is a file somebody is editing: it carries instructions and
        `secret_id` references, and a YAML error's own text quotes the line it
        failed on (`.claude/rules/exceptions-security.md`)."""
        response = await _import(client, _SECRETIVE_YAML)

        assert response.status_code == 400
        assert "legal@example.com" not in response.text
        assert "ACME-9981" not in response.text
        assert "3f7c2c58" not in response.text
        assert "bad indent here" not in response.text

    async def test_a_rejected_value_is_not_echoed_beside_the_field_it_broke(
        self, client: Any
    ) -> None:
        """`include_input=False`: a form needs to know which field is wrong, not
        to be sent a copy of what it posted."""
        response = await _import(client, "name: Support\ninstructions: 12\ndescription: 34\n")

        assert response.status_code == 400
        problems = response.json()["error"]["details"]["fields"]
        assert sorted(problem["field"] for problem in problems) == ["description", "instructions"]
        assert all(set(problem) == {"field", "message"} for problem in problems)


class TestTheRefusalStopsBeforeTheRow:
    async def test_nothing_is_read_or_written_when_the_spec_does_not_parse(
        self, client: Any, mock_db_session: Any
    ) -> None:
        """The parse is the first thing `import_spec` does, so a spec nobody
        could have saved never opens a transaction against an agent."""
        response = await _import(client, "- a\n- b\n")

        assert response.status_code == 400
        mock_db_session.execute.assert_not_called()
        mock_db_session.flush.assert_not_called()
