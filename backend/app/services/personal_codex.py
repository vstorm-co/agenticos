"""A Codex task's access to its initiator's user-sealed grant."""

from dataclasses import dataclass
from uuid import UUID

from pydantic_ai.providers.openai_codex import OpenAICodexCredentials

from app.core.exceptions import AuthorizationError
from app.core.secret_kinds import OpenAICodexSecret, SecretKind, seal_secret, unseal_secret
from app.core.vault import VaultScope
from app.db.session import get_db_context
from app.repositories import coding_account as account_repo


@dataclass(frozen=True)
class PersonalCodexCredentials:
    organization_id: UUID
    user_id: UUID
    account_id: UUID
    generation: UUID

    async def visible_to(self, user_id: UUID) -> bool:
        return user_id == self.user_id

    async def load(self) -> OpenAICodexCredentials:
        async with get_db_context() as db:
            row = await account_repo.get(
                db,
                organization_id=self.organization_id,
                user_id=self.user_id,
                account_id=self.account_id,
            )
            if row is None or not row.enabled or row.generation != self.generation:
                raise AuthorizationError(
                    message="The personal coding account was disconnected or changed"
                )
            if row.secret_kind != SecretKind.OPENAI_CODEX.value:
                raise TypeError("A Codex grant has the wrong stored secret kind")
            value = unseal_secret(
                row.sealed_secret,
                kind=SecretKind.OPENAI_CODEX,
                scope=VaultScope.user(self.user_id),
                key_version=row.key_version,
            )
            if not isinstance(value, OpenAICodexSecret):
                raise TypeError("A Codex grant has the wrong stored secret kind")
            return OpenAICodexCredentials(
                access_token=value.access_token.get_secret_value(),
                refresh_token=value.refresh_token.get_secret_value(),
                account_id=value.account_id,
            )

    async def swap(self, previous: OpenAICodexCredentials, rotated: OpenAICodexCredentials) -> bool:
        if previous.account_id != rotated.account_id:
            return False
        async with get_db_context() as db:
            row = await account_repo.get(
                db,
                organization_id=self.organization_id,
                user_id=self.user_id,
                account_id=self.account_id,
                locked=True,
            )
            if row is None or not row.enabled or row.generation != self.generation:
                return False
            if row.secret_kind != SecretKind.OPENAI_CODEX.value:
                raise TypeError("A Codex grant has the wrong stored secret kind")
            held = unseal_secret(
                row.sealed_secret,
                kind=SecretKind.OPENAI_CODEX,
                scope=VaultScope.user(self.user_id),
                key_version=row.key_version,
            )
            if not isinstance(held, OpenAICodexSecret):
                raise TypeError("A Codex grant has the wrong stored secret kind")
            if (
                held.account_id != previous.account_id
                or held.refresh_token.get_secret_value() != previous.refresh_token
                or held.access_token.get_secret_value() != previous.access_token
            ):
                return False
            sealed = seal_secret(
                OpenAICodexSecret(
                    access_token=rotated.access_token,
                    refresh_token=rotated.refresh_token,
                    account_id=rotated.account_id,
                ),
                scope=VaultScope.user(self.user_id),
            )
            row.sealed_secret = sealed.ciphertext
            row.key_version = sealed.key_version
            await db.flush()
            return True
