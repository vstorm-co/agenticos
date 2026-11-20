"""Reload a personal Copilot token without changing accounts inside an active run."""

import hashlib
import secrets
from dataclasses import dataclass
from uuid import UUID

from app.clients.github_copilot import bearer_token
from app.core.exceptions import AuthorizationError
from app.core.secret_kinds import ApiKeySecret, SecretKind, unseal_secret
from app.core.vault import VaultScope
from app.db.session import get_db_context
from app.repositories import personal_model_key as key_repo


def sealed_fingerprint(ciphertext: str) -> str:
    """Identify an encrypted credential revision without retaining the credential."""
    return hashlib.sha256(ciphertext.encode()).hexdigest()


@dataclass(frozen=True)
class PersonalCopilotToken:
    organization_id: UUID
    user_id: UUID
    key_id: UUID
    fingerprint: str

    async def __call__(self) -> str:
        async with get_db_context() as db:
            row = await key_repo.get(
                db,
                organization_id=self.organization_id,
                user_id=self.user_id,
                provider="github_copilot",
                endpoint="",
            )
            if (
                row is None
                or row.id != self.key_id
                or not secrets.compare_digest(
                    sealed_fingerprint(row.sealed_secret), self.fingerprint
                )
            ):
                raise AuthorizationError(
                    message="Your personal Copilot connection changed or was disconnected. Review the connection in chat settings, then send another message."
                )
            secret = unseal_secret(
                row.sealed_secret,
                kind=SecretKind.API_KEY,
                scope=VaultScope.user(self.user_id),
                key_version=row.key_version,
            )
            if not isinstance(secret, ApiKeySecret):
                raise TypeError("A personal Copilot token has the wrong stored secret kind")
            return bearer_token(secret.api_key.get_secret_value())
