"""Tests for per-collection embedding resolution.

Two properties carry the weight. The recorded model and width win - a
collection keeps embedding with what its table was created for, whatever the
deployment default became. And every credential failure degrades to the
deployment key rather than raising: whose key *pays* must never decide whether
documents can be *found*.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret
from app.core.vault import VaultScope
from app.services.embedding_resolution import ResolvedEmbeddings, embeddings_for_collection

pytestmark = pytest.mark.anyio

_MODULE = "app.services.embedding_resolution"
_ORG = uuid.uuid4()


def _kb(*, secret_id: uuid.UUID | None = None, organization_id: uuid.UUID | None = _ORG):
    return MagicMock(
        collection_name="handbook",
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        embedding_secret_id=secret_id,
        organization_id=organization_id,
    )


def _sealed_key_row(plaintext: str, *, organization_id: uuid.UUID = _ORG):
    sealed = seal_secret(
        ApiKeySecret(api_key=SecretStr(plaintext)),
        scope=VaultScope.organization(organization_id),
    )
    return MagicMock(
        sealed_secret=sealed.ciphertext,
        kind=SecretKind.API_KEY.value,
        key_version=sealed.key_version,
        purpose="openrouter",
    )


async def _resolve(kb, secret_row=None):
    """Run the resolver against one KB row and an optional vault row.

    Returns the resolution and the secret-repo mock, so a test can assert the
    vault was - or was not - consulted.
    """
    with (
        patch(f"{_MODULE}.get_db_context") as db_ctx,
        patch(f"{_MODULE}.knowledge_base_repo") as kbs,
        patch(f"{_MODULE}.organization_secret_repo") as secrets,
    ):
        db_ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        kbs.get_by_collection_name = AsyncMock(return_value=kb)
        secrets.get = AsyncMock(return_value=secret_row)
        return await embeddings_for_collection("handbook"), secrets


class TestResolution:
    async def test_a_collection_nobody_claims_resolves_to_none(self):
        """The store then uses its deployment defaults - what such collections
        have always gotten."""
        resolved, _ = await _resolve(None)
        assert resolved is None

    async def test_the_recorded_model_and_width_win_over_any_default(self):
        with patch(f"{_MODULE}.settings") as env:
            env.OPENROUTER_API_KEY = "sk-deployment"
            resolved, _ = await _resolve(_kb())

        assert resolved == ResolvedEmbeddings(
            model="text-embedding-3-small", dim=1536, api_key="sk-deployment"
        )

    async def test_the_organizations_own_key_is_unsealed_and_used(self):
        secret_id = uuid.uuid4()
        resolved, _ = await _resolve(_kb(secret_id=secret_id), _sealed_key_row("sk-org-own-key"))

        assert resolved is not None
        assert resolved.api_key == "sk-org-own-key"

    async def test_a_repr_never_carries_the_key(self):
        """A dataclass repr in a log line is the way a key usually escapes."""
        resolved = ResolvedEmbeddings(model="m", dim=8, api_key="sk-secret")

        assert "sk-secret" not in repr(resolved)


class TestCredentialDegradation:
    """Every failure lands on the deployment key, with a log line."""

    async def test_a_deleted_secret_falls_back_to_the_deployment_key(self):
        with patch(f"{_MODULE}.settings") as env:
            env.OPENROUTER_API_KEY = "sk-deployment"
            resolved, _ = await _resolve(_kb(secret_id=uuid.uuid4()), None)

        assert resolved is not None
        assert resolved.api_key == "sk-deployment"

    async def test_an_unopenable_ciphertext_falls_back(self):
        """A rotated master key must not take search down."""
        broken = MagicMock(
            sealed_secret="not-a-ciphertext",
            kind=SecretKind.API_KEY.value,
            key_version=1,
        )
        with patch(f"{_MODULE}.settings") as env:
            env.OPENROUTER_API_KEY = "sk-deployment"
            resolved, _ = await _resolve(_kb(secret_id=uuid.uuid4()), broken)

        assert resolved is not None
        assert resolved.api_key == "sk-deployment"

    async def test_a_secret_of_the_wrong_kind_falls_back(self):
        """The vault can hold shapes an embedding client cannot use."""
        row = _sealed_key_row("sk-org")
        with (
            patch(f"{_MODULE}.settings") as env,
            patch(f"{_MODULE}.unseal_secret", return_value=MagicMock(spec=[])),
        ):
            env.OPENROUTER_API_KEY = "sk-deployment"
            resolved, _ = await _resolve(_kb(secret_id=uuid.uuid4()), row)

        assert resolved is not None
        assert resolved.api_key == "sk-deployment"

    async def test_a_personal_collection_never_looks_in_a_vault(self):
        """No organization, no vault scope to open an envelope with."""
        with patch(f"{_MODULE}.settings") as env:
            env.OPENROUTER_API_KEY = "sk-deployment"
            resolved, secrets = await _resolve(_kb(secret_id=uuid.uuid4(), organization_id=None))

        assert resolved is not None
        assert resolved.api_key == "sk-deployment"
        secrets.get.assert_not_called()
