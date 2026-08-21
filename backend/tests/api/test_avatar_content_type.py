"""An avatar is served as an image or not at all.

Both avatar routes serve a file the uploader named, from the app's own origin,
under a CSP that allows inline script. The upload kept whatever suffix the caller
chose, so a file stored as `x.html` was served as `text/html` - a stored script
rather than a picture (#702). The routes now pin the served type to an image and
refuse anything else; the type is guessed from the name on disk, so a stored
`.html` is refused rather than served.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.api.routes.v1.organizations import get_organization_avatar
from app.api.routes.v1.users import get_avatar
from app.core.exceptions import NotFoundError

pytestmark = pytest.mark.anyio


async def test_a_user_avatar_stored_as_html_is_refused(tmp_path: Path) -> None:
    stored = tmp_path / "x.html"
    stored.write_bytes(b"<script>fetch('/api/v1/users/me')</script>")
    service = MagicMock(
        get_by_id=AsyncMock(return_value=MagicMock(avatar_url="avatars/u/x.html")),
        get_avatar_path=MagicMock(return_value=str(stored)),
    )

    with pytest.raises(NotFoundError):
        await get_avatar(uuid4(), service)


async def test_a_user_avatar_that_is_an_image_is_pinned_and_nosniffed(tmp_path: Path) -> None:
    stored = tmp_path / "x.png"
    stored.write_bytes(b"\x89PNG\r\n\x1a\n")
    service = MagicMock(
        get_by_id=AsyncMock(return_value=MagicMock(avatar_url="avatars/u/x.png")),
        get_avatar_path=MagicMock(return_value=str(stored)),
    )

    response = await get_avatar(uuid4(), service)

    assert response.media_type == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_an_org_avatar_stored_as_html_is_refused(tmp_path: Path) -> None:
    stored = tmp_path / "x.html"
    stored.write_bytes(b"<script>fetch('/api/v1/orgs')</script>")
    service = MagicMock(
        get_for_user=AsyncMock(return_value=(MagicMock(avatar_url="avatars/orgs/o/x.html"), None)),
        get_avatar_path=MagicMock(return_value=str(stored)),
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as refusal:
        await get_organization_avatar(uuid4(), service, MagicMock(id=uuid4()))
    assert refusal.value.status_code == 404


async def test_an_org_avatar_that_is_an_image_is_pinned_and_nosniffed(tmp_path: Path) -> None:
    stored = tmp_path / "x.webp"
    stored.write_bytes(b"RIFF....WEBP")
    service = MagicMock(
        get_for_user=AsyncMock(return_value=(MagicMock(avatar_url="avatars/orgs/o/x.webp"), None)),
        get_avatar_path=MagicMock(return_value=str(stored)),
    )

    response = await get_organization_avatar(uuid4(), service, MagicMock(id=uuid4()))

    assert response.media_type == "image/webp"
    assert response.headers["x-content-type-options"] == "nosniff"
