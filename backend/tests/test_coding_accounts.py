"""Account persistence refuses unsupported credentials and preserves database failures."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, NoSecret
from app.db.models.coding_account import CodingAccount
from app.services import coding_accounts as module
from app.services.coding_accounts import CodingAccountService

pytestmark = pytest.mark.anyio


class DatabaseFailure(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("Synthetic database refusal")
        self.sqlstate = sqlstate


@pytest.mark.parametrize("sqlstate", ["23505", "23514"])
async def test_only_unique_database_failures_become_duplicate_accounts(
    monkeypatch: pytest.MonkeyPatch, mock_db_session: AsyncSession, sqlstate: str
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    monkeypatch.setattr(module.member_repo, "get", AsyncMock(return_value=object()))
    monkeypatch.setattr(module.account_repo, "list_for", AsyncMock(return_value=[]))
    error = IntegrityError("synthetic insert", {}, DatabaseFailure(sqlstate))
    monkeypatch.setattr(module.account_repo, "create", AsyncMock(side_effect=error))
    monkeypatch.setattr(mock_db_session, "begin_nested", MagicMock(return_value=AsyncMock()))
    expected = AlreadyExistsError if sqlstate == "23505" else IntegrityError
    with pytest.raises(expected) as caught:
        await CodingAccountService(mock_db_session).save(
            ctx,
            harness="codex",
            label="Private account",
            secret=ApiKeySecret(api_key=SecretStr("synthetic-test-key")),
            enabled=False,
        )
    if sqlstate != "23505":
        assert caught.value is error


async def test_unsupported_stored_credentials_fail_before_new_account_persistence(
    monkeypatch: pytest.MonkeyPatch, mock_db_session: AsyncSession
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    stored = CodingAccount(
        id=uuid4(),
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        harness="codex",
        label="Existing",
        secret_kind="api_key",
        sealed_secret="synthetic-ciphertext",
        key_version=1,
        enabled=False,
        generation=uuid4(),
        is_default=True,
        pool_member=False,
        provider_identity_fingerprint=None,
    )
    monkeypatch.setattr(module.member_repo, "get", AsyncMock(return_value=object()))
    monkeypatch.setattr(module.account_repo, "list_for", AsyncMock(return_value=[stored]))
    monkeypatch.setattr(module, "unseal_secret", MagicMock(return_value=NoSecret()))
    create = AsyncMock()
    monkeypatch.setattr(module.account_repo, "create", create)
    with pytest.raises(TypeError, match="unsupported stored credential"):
        await CodingAccountService(mock_db_session).save(
            ctx,
            harness="codex",
            label="New account",
            secret=ApiKeySecret(api_key=SecretStr("synthetic-test-key")),
            enabled=False,
        )
    create.assert_not_awaited()
