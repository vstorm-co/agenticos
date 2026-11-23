"""A personal Copilot connection is revalidated for each request, without account fallback."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.secret_kinds import ApiKeySecret, GithubOAuthAppSecret, seal_secret
from app.core.vault import VaultScope
from app.db.models.personal_model_key import PersonalModelKey
from app.services import personal_copilot as module
from app.services.personal_copilot import PersonalCopilotToken

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@asynccontextmanager
async def database() -> AsyncGenerator[AsyncSession]:
    yield AsyncMock()


def connection() -> tuple[PersonalCopilotToken, PersonalModelKey]:
    owner, organization = uuid4(), uuid4()
    sealed = seal_secret(ApiKeySecret(api_key="private-owner-token"), scope=VaultScope.user(owner))
    row = PersonalModelKey(
        id=uuid4(),
        user_id=owner,
        organization_id=organization,
        provider="github_copilot",
        endpoint="",
        sealed_secret=sealed.ciphertext,
        key_version=sealed.key_version,
        updated_at=None,
    )
    return PersonalCopilotToken(
        organization, owner, row.id, module.sealed_fingerprint(row.sealed_secret)
    ), row


async def test_live_token_is_owner_sealed_and_queries_both_tenant_and_person() -> None:
    source, row = connection()
    with (
        patch.object(module, "get_db_context", database),
        patch.object(module.key_repo, "get", AsyncMock(return_value=row)) as get,
    ):
        assert await source() == "private-owner-token"
    assert get.call_args.kwargs == {
        "organization_id": source.organization_id,
        "user_id": source.user_id,
        "provider": "github_copilot",
        "endpoint": "",
    }
    assert "private-owner-token" not in repr(source)


@pytest.mark.parametrize("change", ["deleted", "recreated", "reconnected"])
async def test_a_running_chat_does_not_adopt_a_replaced_or_deleted_credential(change: str) -> None:
    source, row = connection()
    if change == "recreated":
        row.id = uuid4()
    elif change == "reconnected":
        row.sealed_secret = seal_secret(
            ApiKeySecret(api_key="another-account-token"), scope=VaultScope.user(source.user_id)
        ).ciphertext
    with (
        patch.object(module, "get_db_context", database),
        patch.object(
            module.key_repo, "get", AsyncMock(return_value=None if change == "deleted" else row)
        ),
        pytest.raises(AuthorizationError, match="changed or was disconnected"),
    ):
        await source()


async def test_another_person_cannot_decrypt_a_copilot_token_even_if_a_repository_is_miswired() -> (
    None
):
    source, row = connection()
    wrong_owner = PersonalCopilotToken(
        source.organization_id, uuid4(), source.key_id, source.fingerprint
    )
    with (
        patch.object(module, "get_db_context", database),
        patch.object(module.key_repo, "get", AsyncMock(return_value=row)),
        pytest.raises(BadRequestError),
    ):
        await wrong_owner()


async def test_a_wrong_secret_contract_is_refused_instead_of_coerced_to_a_bearer() -> None:
    source, row = connection()
    secret = GithubOAuthAppSecret(client_id="our-app", client_secret="not-a-model-token")
    with (
        patch.object(module, "get_db_context", database),
        patch.object(module.key_repo, "get", AsyncMock(return_value=row)),
        patch.object(module, "unseal_secret", return_value=secret),
        pytest.raises(TypeError, match="wrong stored secret kind"),
    ):
        await source()
