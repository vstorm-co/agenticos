"""Admin recovery links use the account's normal one-use password reset."""

from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, ConfigurationError
from app.db.models.user import User
from app.services.user import UserService

pytestmark = pytest.mark.anyio


async def test_admin_link_is_bound_to_the_accounts_credential_version(db: AsyncSession) -> None:
    user = User(email=f"{uuid4().hex}@example.com", hashed_password="old", is_active=True)
    admin = User(email=f"{uuid4().hex}@example.com", is_active=True, is_app_admin=True)
    db.add_all([user, admin])
    await db.flush()

    service = UserService(db)
    with patch("app.services.user.record_audit", new_callable=AsyncMock) as audit:
        url = await service.admin_password_reset(
            user.id, actor_id=admin.id, delivery="link", ip_address=None
        )
    assert url is not None
    token = parse_qs(urlsplit(url).query)["token"][0]
    assert audit.await_args is not None
    assert audit.await_args.kwargs["details"] == {"delivery": "link"}

    await service.confirm_password_reset(token, "new-password")
    with pytest.raises(AuthenticationError, match="invalid or has expired"):
        await service.confirm_password_reset(token, "another-password")


async def test_an_unconfigured_mail_provider_cannot_report_success(db: AsyncSession) -> None:
    user = User(email=f"{uuid4().hex}@example.com", is_active=True)
    db.add(user)
    await db.flush()

    with (
        patch("app.services.user.get_email_service") as email,
        pytest.raises(ConfigurationError, match="Email delivery is unavailable"),
    ):
        email.return_value.delivers = False
        await UserService(db).admin_password_reset(
            user.id, actor_id=user.id, delivery="email", ip_address=None
        )
    email.return_value.send_password_reset.assert_not_called()
