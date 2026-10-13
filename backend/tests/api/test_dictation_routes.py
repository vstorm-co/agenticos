"""`POST /agents/{agent_id}/dictation`, over the wire.

What the route adds to `MLService.dictate`: run access on the agent through its
grants, the per-person rate limit, and a bounded read of the upload. The grants
themselves are exercised against a real database in
`tests/integration/test_platform_flows.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import ExternalServiceError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.main import app
from app.services import transcription
from app.services.ml.facade import MLService

pytestmark = pytest.mark.anyio

_V1 = settings.API_V1_STR
_REGISTRY = "app.services.agent_registry.AgentRegistryService.get"
_DICTATE = "app.services.ml.facade.MLService.dictate"


async def _no_limit() -> None:
    return None


@pytest.fixture(autouse=True)
def caller() -> Iterator[AuthContext]:
    context = AuthContext(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=OrgRoleName.VIEWER.value,
        is_app_admin=False,
    )
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_ml_service] = lambda: MLService(session)
    app.dependency_overrides[deps.limit_dictation] = _no_limit
    yield context
    app.dependency_overrides.clear()


async def test_a_caller_who_may_run_the_agent_gets_the_text(client: AsyncClient) -> None:
    """Checked as run access on this agent, which is what lets a Viewer holding
    a run grant dictate - a role gate would refuse them first."""
    agent_id = uuid.uuid4()
    with (
        patch(_REGISTRY, new=AsyncMock(return_value=MagicMock())) as get,
        patch(_DICTATE, new=AsyncMock(return_value="hello")) as dictate,
    ):
        response = await client.post(
            f"{_V1}/agents/{agent_id}/dictation",
            files={"file": ("blob", b"audio", "audio/webm;codecs=opus")},
        )

    assert response.status_code == 200
    assert response.json() == {"text": "hello"}
    assert get.await_args.args[1] == agent_id
    assert get.await_args.kwargs["perm"] == Perm.AGENTS_RUN
    assert dictate.await_args.kwargs["content"] == b"audio"
    assert dictate.await_args.kwargs["mime_type"] == "audio/webm;codecs=opus"


@pytest.mark.security
async def test_an_agent_the_caller_cannot_run_is_not_found_and_nothing_is_transcribed(
    client: AsyncClient,
) -> None:
    """Covers a Viewer without a grant and another organization's agent: both
    read as absent, and neither reaches a paid engine."""
    with (
        patch(
            _REGISTRY,
            new=AsyncMock(side_effect=NotFoundError(message="Agent not found", details={})),
        ),
        patch(_DICTATE, new=AsyncMock()) as dictate,
    ):
        response = await client.post(
            f"{_V1}/agents/{uuid.uuid4()}/dictation",
            files={"file": ("blob", b"audio", "audio/webm")},
        )

    assert response.status_code == 404
    dictate.assert_not_awaited()


async def test_a_refusal_reaches_the_client_with_its_reason(client: AsyncClient) -> None:
    error = ExternalServiceError(
        message="The transcription provider did not answer in time.",
        details={"reason": "timeout"},
    )
    with (
        patch(_REGISTRY, new=AsyncMock(return_value=MagicMock())),
        patch(_DICTATE, new=AsyncMock(side_effect=error)),
    ):
        response = await client.post(
            f"{_V1}/agents/{uuid.uuid4()}/dictation",
            files={"file": ("blob", b"audio", "audio/webm")},
        )

    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "timeout"


async def test_the_upload_is_read_no_further_than_transcription_accepts(
    client: AsyncClient,
) -> None:
    """A bounded read, so a body far over the cap is never copied whole into
    memory; one byte over is what lets the service name the limit."""
    with (
        patch(_REGISTRY, new=AsyncMock(return_value=MagicMock())),
        patch(_DICTATE, new=AsyncMock(return_value="x")) as dictate,
        patch.object(transcription, "MAX_BYTES", 4),
    ):
        await client.post(
            f"{_V1}/agents/{uuid.uuid4()}/dictation",
            files={"file": ("blob", b"0123456789", "audio/webm")},
        )

    assert dictate.await_args.kwargs["content"] == b"01234"
