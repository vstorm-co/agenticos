"""What `GET /runs/{run_id}/manifest` puts on the wire.

The authorization logic is proven against the service in
`tests/test_run_transcript.py`, beside the transcript's, because the two are
reached the same way and refuse in the same order. What belongs here is the
wiring: that the stored document is served under a shape a client can branch on,
that a record written by an older build still serializes rather than 500ing the
whole response, and that each refusal arrives as the status it should.

The route carries no `require()` gate on purpose - reading a run is authorized,
not owned - which is why the gate sweep in `tests/api/test_platform_routes.py`
reaches it through the runner service.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid4()


@asynccontextmanager
async def _client(service: MagicMock) -> AsyncIterator[AsyncClient]:
    context = AuthContext(
        user_id=uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.OPERATOR.value
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_agent_runner_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _manifest(payload: dict, *, truncated: bool = False) -> MagicMock:
    return MagicMock(
        run_id=uuid4(),
        created_at=datetime(2026, 8, 19, 9, 0, tzinfo=UTC),
        truncated=truncated,
        payload=payload,
    )


async def test_the_record_is_served_as_it_was_stored() -> None:
    record = _manifest(
        {
            "instructions": "You are a clerk.",
            "system_prompts": ["Answer in English."],
            "tools": [
                {
                    "name": "check_stock",
                    "description": "Look one up.",
                    "parameters_json_schema": {"type": "object"},
                    "kind": "function",
                }
            ],
            "settings": {"temperature": 0.2},
            "requests": [{"index": 0, "duration_ms": 812, "input_tokens": 1200}],
            "messages": [{"kind": "request", "parts": []}],
        }
    )
    service = MagicMock(get_run_manifest=AsyncMock(return_value=record))

    async with _client(service) as client:
        response = await client.get(f"/api/v1/runs/{record.run_id}/manifest")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["instructions"] == "You are a clerk."
    # The sentence the model reads, which is the half no other surface shows.
    assert body["tools"][0]["description"] == "Look one up."
    assert body["settings"] == {"temperature": 0.2}
    assert body["requests"][0]["duration_ms"] == 812
    assert body["truncated"] is False


async def test_a_record_from_an_older_build_still_serializes() -> None:
    """The payload is stored as it was recorded, so a row written before a field
    existed carries whatever that build knew. A required field would refuse to
    validate exactly the old runs somebody is looking back at - and in FastAPI
    that is a 500 on the whole response, not a gap in one panel."""
    service = MagicMock(get_run_manifest=AsyncMock(return_value=_manifest({"tools": []})))

    async with _client(service) as client:
        response = await client.get(f"/api/v1/runs/{uuid4()}/manifest")

    assert response.status_code == 200, response.text
    assert response.json()["instructions"] is None


async def test_a_trimmed_record_says_so() -> None:
    """A trimmed document that reads as a complete one is worse than none: it
    says the agent was given no tool schemas, which is a claim about the agent."""
    service = MagicMock(
        get_run_manifest=AsyncMock(return_value=_manifest({"messages": []}, truncated=True))
    )

    async with _client(service) as client:
        response = await client.get(f"/api/v1/runs/{uuid4()}/manifest")

    assert response.json()["truncated"] is True


async def test_a_run_with_nothing_recorded_is_a_404() -> None:
    service = MagicMock(
        get_run_manifest=AsyncMock(side_effect=NotFoundError(message="Nothing was recorded"))
    )

    async with _client(service) as client:
        response = await client.get(f"/api/v1/runs/{uuid4()}/manifest")

    assert response.status_code == 404


async def test_a_caller_without_runs_view_is_refused() -> None:
    service = MagicMock(
        get_run_manifest=AsyncMock(side_effect=AuthorizationError(message="Insufficient"))
    )

    async with _client(service) as client:
        response = await client.get(f"/api/v1/runs/{uuid4()}/manifest")

    assert response.status_code == 403
