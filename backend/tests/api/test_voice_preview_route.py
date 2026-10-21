"""`POST /agents/{agent_id}/voice/preview`: a draft's voice, heard over the wire (#54)."""

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.main import app

pytestmark = pytest.mark.anyio

_V1 = settings.API_V1_STR
_BODY = {
    "voice": {"provider": "openai", "model": "gpt-realtime", "secret_id": str(uuid.uuid4())},
    "locale": "pl",
}


@pytest.fixture
def wired() -> Iterator[SimpleNamespace]:
    registry = MagicMock(get=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())))
    preview = MagicMock(preview=AsyncMock(return_value=b"RIFF....WAVE"))
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=OrgRoleName.MEMBER.value,
        is_app_admin=False,
    )
    app.dependency_overrides[deps.get_agent_registry_service] = lambda: registry
    app.dependency_overrides[deps.get_voice_preview_service] = lambda: preview
    app.dependency_overrides[deps.limit_voice_preview] = lambda: None
    yield SimpleNamespace(registry=registry, preview=preview)
    app.dependency_overrides.clear()


async def test_an_agent_the_caller_may_not_edit_answers_404_and_speaks_nothing(
    client: AsyncClient, wired
):
    wired.registry.get.side_effect = NotFoundError(message="Agent not found")

    resp = await client.post(f"{_V1}/agents/{uuid.uuid4()}/voice/preview", json=_BODY)

    assert resp.status_code == 404
    assert wired.registry.get.call_args.kwargs["perm"] is Perm.AGENTS_EDIT
    wired.preview.preview.assert_not_awaited()


async def test_the_voice_comes_back_as_wav_in_the_requested_language(client: AsyncClient, wired):
    resp = await client.post(f"{_V1}/agents/{uuid.uuid4()}/voice/preview", json=_BODY)

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.content == b"RIFF....WAVE"
    assert wired.preview.preview.await_args.kwargs["locale"] == "pl"
    assert wired.preview.preview.await_args.args[1].provider == "openai"


async def test_a_locale_the_console_does_not_speak_is_refused(client: AsyncClient, wired):
    resp = await client.post(
        f"{_V1}/agents/{uuid.uuid4()}/voice/preview", json={**_BODY, "locale": "fr"}
    )

    assert resp.status_code == 422
    wired.preview.preview.assert_not_awaited()
