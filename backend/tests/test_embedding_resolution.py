"""Tests for per-collection embedding resolution.

Three properties carry the weight. The recorded model and width win - a
collection keeps embedding with what its table was created for, whatever the
deployment default became. A credential failure degrades rather than raising:
whose key *pays* must never decide whether the collection's row can be *read*.
And what it degrades *to* is no key at all - there is no deployment-wide
embedding credential, so a collection that names no usable vault key resolves
to an empty key and a reason, and the embedding client refuses with both.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret
from app.core.vault import VaultScope
from app.services.embedding_resolution import (
    EmbeddingKeySource,
    ResolvedEmbeddings,
    embeddings_for_collection,
)

pytestmark = pytest.mark.anyio

_MODULE = "app.services.embedding_resolution"
_ORG = uuid.uuid4()


def _kb(
    *,
    secret_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = _ORG,
    provider: str = "openrouter",
):
    return MagicMock(
        collection_name="handbook",
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        embedding_secret_id=secret_id,
        organization_id=organization_id,
        embedding_provider=provider,
    )


def _openai_key_row(plaintext: str, *, organization_id: uuid.UUID = _ORG):
    """A vault row holding an OpenAI key, for a collection embedding through one."""
    row = _sealed_key_row(plaintext, organization_id=organization_id)
    row.purpose = "openai"
    return row


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
        kbs.get_for_collection = AsyncMock(return_value=kb)
        secrets.get = AsyncMock(return_value=secret_row)
        return await embeddings_for_collection("handbook"), secrets


class TestResolution:
    async def test_a_collection_nobody_claims_resolves_to_none(self):
        """The store then uses its own keyless embedder, which refuses on first
        use - such a collection has nothing to pay with."""
        resolved, _ = await _resolve(None)
        assert resolved is None

    async def test_the_recorded_model_and_width_win_over_any_default(self):
        secret_id = uuid.uuid4()
        resolved, _ = await _resolve(_kb(secret_id=secret_id), _sealed_key_row("sk-org-own-key"))

        assert resolved == ResolvedEmbeddings(
            model="text-embedding-3-small",
            dim=1536,
            api_key="sk-org-own-key",
            key_source=EmbeddingKeySource.ORGANIZATION,
            base_url="https://openrouter.ai/api/v1",
            provider="openrouter",
        )

    async def test_the_organizations_own_key_is_unsealed_and_used(self):
        secret_id = uuid.uuid4()
        resolved, _ = await _resolve(_kb(secret_id=secret_id), _sealed_key_row("sk-org-own-key"))

        assert resolved is not None
        assert resolved.api_key == "sk-org-own-key"
        assert resolved.key_source is EmbeddingKeySource.ORGANIZATION

    async def test_a_collection_that_names_no_key_resolves_to_none_and_says_so(self):
        """There is no deployment-wide key to fall back to, and the resolution
        says which of the five situations this is rather than handing back an
        empty string with no story."""
        resolved, secrets = await _resolve(_kb())

        assert resolved is not None
        assert resolved.api_key == ""
        assert resolved.key_source is EmbeddingKeySource.NONE_CHOSEN
        secrets.get.assert_not_called()

    async def test_a_repr_never_carries_the_key(self):
        """A dataclass repr in a log line is the way a key usually escapes."""
        resolved = ResolvedEmbeddings(
            model="m",
            dim=8,
            api_key="sk-secret",
            key_source=EmbeddingKeySource.ORGANIZATION,
            base_url="https://api.openai.com/v1",
            provider="openai",
        )

        assert "sk-secret" not in repr(resolved)
        assert "organization" in repr(resolved)


class TestOrganizationScoping:
    """The resolution is scoped to the caller's organization (#913).

    `collection_name` is indexed but not unique, so resolving by name alone can
    land on another tenant's knowledge base and unseal *their* vault key for
    *this* embedding call. The resolver passes the organization it embeds for
    through to the org-scoped repository lookup; that the lookup then refuses a
    third tenant's row is `knowledge_base_repo.get_for_collection`'s own contract,
    proven against real rows in the integration suite.
    """

    async def test_the_caller_organization_is_threaded_to_the_lookup(self):
        org = uuid.uuid4()
        with (
            patch(f"{_MODULE}.get_db_context") as db_ctx,
            patch(f"{_MODULE}.knowledge_base_repo") as kbs,
            patch(f"{_MODULE}.organization_secret_repo"),
        ):
            db_ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            kbs.get_for_collection = AsyncMock(return_value=None)

            await embeddings_for_collection("handbook", org)

            kbs.get_for_collection.assert_awaited_once()
            assert kbs.get_for_collection.await_args.args[1:] == ("handbook", org)


class TestCredentialDegradation:
    """Every failure lands on no key, saying which failure it was.

    An empty `api_key` alone cannot tell an operator whether they never chose a
    key or chose one that is now gone. `key_source` is what carries that out to
    the flow log and the error left on the document row.
    """

    async def test_a_deleted_secret_degrades_to_no_key(self):
        resolved, _ = await _resolve(_kb(secret_id=uuid.uuid4()), None)

        assert resolved is not None
        assert resolved.api_key == ""
        assert resolved.key_source is EmbeddingKeySource.SECRET_MISSING

    async def test_an_unopenable_ciphertext_degrades_rather_than_raising(self):
        """A rotated master key must not take the collection's row down with it."""
        broken = MagicMock(
            sealed_secret="not-a-ciphertext",
            kind=SecretKind.API_KEY.value,
            key_version=1,
        )
        resolved, _ = await _resolve(_kb(secret_id=uuid.uuid4()), broken)

        assert resolved is not None
        assert resolved.api_key == ""
        assert resolved.key_source is EmbeddingKeySource.SECRET_UNUSABLE

    async def test_a_secret_of_the_wrong_kind_degrades(self):
        """The vault can hold shapes an embedding client cannot use."""
        row = _sealed_key_row("sk-org")
        with patch(f"{_MODULE}.unseal_secret", return_value=MagicMock(spec=[])):
            resolved, _ = await _resolve(_kb(secret_id=uuid.uuid4()), row)

        assert resolved is not None
        assert resolved.api_key == ""
        assert resolved.key_source is EmbeddingKeySource.SECRET_WRONG_KIND

    async def test_a_collection_with_no_organization_never_looks_in_a_vault(self):
        """No organization, no vault scope to open an envelope with - and no
        deployment key to hand it instead."""
        resolved, secrets = await _resolve(_kb(secret_id=uuid.uuid4(), organization_id=None))

        assert resolved is not None
        assert resolved.api_key == ""
        assert resolved.key_source is EmbeddingKeySource.NONE_CHOSEN
        secrets.get.assert_not_called()


class TestSayingWhichKeyPaid:
    """A degradation nobody can see is a degradation nobody can fix.

    Until #306 the three degradations were a `logger.warning` in this module
    and nothing else: not in the Prefect flow log, not in the error on the
    document row, not in the product.
    """

    @pytest.mark.parametrize("source", list(EmbeddingKeySource))
    def test_every_source_says_which_key_paid_or_that_none_did(
        self, source: EmbeddingKeySource
    ) -> None:
        """No explanation names an environment variable: there is no
        deployment-wide embedding key, so advising one would be advice about a
        setting that does not exist."""
        explanation = source.explanation

        assert explanation
        assert "OPENROUTER_API_KEY" not in explanation

    def test_every_source_but_the_organizations_own_key_counts_as_degraded(self):
        """Including a collection that chose no key: with nothing to fall back
        to, that is a collection that cannot index, and the flow log says so."""
        degraded = {source for source in EmbeddingKeySource if source.is_degraded}

        assert degraded == {
            EmbeddingKeySource.NONE_CHOSEN,
            EmbeddingKeySource.SECRET_MISSING,
            EmbeddingKeySource.SECRET_UNUSABLE,
            EmbeddingKeySource.SECRET_WRONG_KIND,
        }

    def test_the_description_names_the_collection_the_provider_and_the_key(self):
        resolved = ResolvedEmbeddings(
            model="text-embedding-3-small",
            dim=1536,
            api_key="",
            key_source=EmbeddingKeySource.SECRET_MISSING,
            base_url="https://openrouter.ai/api/v1",
            provider="openrouter",
        )

        described = resolved.describe("handbook")

        assert "'handbook'" in described
        assert "openrouter" in described
        assert "no longer in this organization's vault" in described


class TestWhereTheRequestGoes:
    """The address is the collection's own, and it travels with the key.

    Every embedding request used to go to openrouter.ai whatever key the
    collection had chosen, so an organization's OpenAI key was sent to
    OpenRouter and refused there.
    """

    async def test_the_collections_provider_decides_the_endpoint(self):
        resolved, _ = await _resolve(
            _kb(secret_id=uuid.uuid4(), provider="openai"), _openai_key_row("sk-org-openai")
        )

        assert resolved is not None
        assert resolved.base_url == "https://api.openai.com/v1"
        assert resolved.provider == "openai"
        assert resolved.api_key == "sk-org-openai"

    async def test_a_provider_the_catalog_no_longer_names_keeps_its_key_to_itself(self):
        """An entry removed from the file under a collection using it. The
        address falls back to the first the catalog still holds, so the row can
        be read; the key does not follow, because it was stored for the
        provider that is gone and sending it to another address would hand one
        vendor's credential to another."""
        resolved, secrets = await _resolve(
            _kb(secret_id=uuid.uuid4(), provider="a-provider-that-left"),
            _sealed_key_row("sk-for-the-old-provider"),
        )

        assert resolved is not None
        assert resolved.provider == "openrouter"
        assert resolved.api_key == ""
        assert resolved.key_source is EmbeddingKeySource.NONE_CHOSEN
        secrets.get.assert_not_called()
