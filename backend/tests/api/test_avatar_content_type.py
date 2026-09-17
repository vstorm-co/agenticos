"""An avatar is served as an image or not at all.

All three avatar routes serve a file the uploader named, from the app's own
origin, under a CSP that allows inline script. The upload kept whatever suffix
the caller chose, so a file stored as `x.html` was served as `text/html` - a
stored script rather than a picture (#702 for the user and org avatars, #1035 for
the agent's). The routes now pin the served type to the file's own bytes and
refuse anything that is not one of the four image types.

Since #1423 the routes are handed a *storage path* rather than a path on this
host, because an object store has no second kind - so these write the file where
the local backend would have put it and let the route resolve it, which is also
what makes the refusal test exercise the real resolution rather than a mock's
return value.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.api.routes.v1.agents import get_agent_avatar
from app.api.routes.v1.organizations import get_organization_avatar
from app.api.routes.v1.users import get_avatar
from app.core.config import settings
from app.core.exceptions import NotFoundError

pytestmark = pytest.mark.anyio


def _store(monkeypatch: pytest.MonkeyPatch, root: Path, storage_path: str, data: bytes) -> str:
    """Write `data` where the local backend would have, and return its storage path."""
    monkeypatch.setattr(settings, "MEDIA_DIR", root)
    target = root / storage_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return storage_path


async def test_a_user_avatar_stored_as_html_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = _store(
        monkeypatch, tmp_path, "avatars/u/x.html", b"<script>fetch('/api/v1/users/me')</script>"
    )
    service = MagicMock(get_by_id=AsyncMock(return_value=MagicMock(avatar_url=stored)))

    with pytest.raises(NotFoundError):
        await get_avatar(uuid4(), service)


async def test_a_user_avatar_that_is_an_image_is_pinned_and_nosniffed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = _store(monkeypatch, tmp_path, "avatars/u/x.png", b"\x89PNG\r\n\x1a\n")
    service = MagicMock(get_by_id=AsyncMock(return_value=MagicMock(avatar_url=stored)))

    response = await get_avatar(uuid4(), service)

    assert response.media_type == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_an_org_avatar_stored_as_html_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = _store(
        monkeypatch, tmp_path, "avatars/orgs/o/x.html", b"<script>fetch('/api/v1/orgs')</script>"
    )
    service = MagicMock(get_for_user=AsyncMock(return_value=(MagicMock(avatar_url=stored), None)))

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as refusal:
        await get_organization_avatar(uuid4(), service, MagicMock(id=uuid4()))
    assert refusal.value.status_code == 404


async def test_an_org_avatar_that_is_an_image_is_pinned_and_nosniffed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = _store(monkeypatch, tmp_path, "avatars/orgs/o/x.webp", b"RIFF....WEBP")
    service = MagicMock(get_for_user=AsyncMock(return_value=(MagicMock(avatar_url=stored), None)))

    response = await get_organization_avatar(uuid4(), service, MagicMock(id=uuid4()))

    assert response.media_type == "image/webp"
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_an_agent_avatar_stored_as_html_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = _store(
        monkeypatch,
        tmp_path,
        "avatars/agents/a/x.html",
        b"<script>fetch('/api/v1/agents')</script>",
    )
    service = MagicMock(avatar_path=AsyncMock(return_value=stored))

    with pytest.raises(NotFoundError):
        await get_agent_avatar(uuid4(), service, MagicMock())


async def test_an_agent_avatar_that_is_an_image_is_pinned_and_nosniffed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = _store(monkeypatch, tmp_path, "avatars/agents/a/x.gif", b"GIF89a")
    service = MagicMock(avatar_path=AsyncMock(return_value=stored))

    response = await get_agent_avatar(uuid4(), service, MagicMock())

    assert response.media_type == "image/gif"
    assert response.headers["x-content-type-options"] == "nosniff"
