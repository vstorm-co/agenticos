"""Tests for per-collection embedding resolution.

Three properties carry the weight. The recorded model and width win - a
collection keeps embedding with what its table was created for, whatever the
deployment default became. A credential failure degrades rather than raising:
whose key *pays* must never decide whether documents can be *found*. And what
it degrades *to* stops at the provider the deployment's key belongs to - a
collection embedding through OpenAI paid for with the deployment's OpenRouter
key is a request refused by the provider after the key has already reached it.
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
        return await embeddings_for_collection("handbook", organization_id=uuid.uuid4()), secrets


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
            model="text-embedding-3-small",
            dim=1536,
            api_key="sk-deployment",
            key_source=EmbeddingKeySource.DEPLOYMENT,
            base_url="https://openrouter.ai/api/v1",
            provider="openrouter",
        )

    async def test_the_organizations_own_key_is_unsealed_and_used(self):
        secret_id = uuid.uuid4()
        resolved, _ = await _resolve(_kb(secret_id=secret_id), _sealed_key_row("sk-org-own-key"))

        assert resolved is not None
        assert resolved.api_key == "sk-org-own-key"
        assert resolved.key_source is EmbeddingKeySource.ORGANIZATION

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


class TestAuthorizedKnowledgeBaseId:
    """A given `knowledge_base_id` resolves that exact row, not a name lookup, so
    a shared collection name cannot re-select and unseal another row's key (#913)."""

    async def test_a_given_kb_id_reads_that_row_and_skips_the_name_lookup(self):
        with (
            patch(f"{_MODULE}.get_db_context") as db_ctx,
            patch(f"{_MODULE}.knowledge_base_repo") as kbs,
            patch(f"{_MODULE}.organization_secret_repo") as secrets,
            patch(f"{_MODULE}.settings") as env,
        ):
            env.OPENROUTER_API_KEY = "sk-deployment"
            db_ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            kbs.get_by_id = AsyncMock(return_value=_kb())
            kbs.get_for_collection = AsyncMock(return_value=_kb(secret_id=uuid.uuid4()))
            secrets.get = AsyncMock()
            kb_id = uuid.uuid4()

            resolved = await embeddings_for_collection(
                "handbook", organization_id=_ORG, knowledge_base_id=kb_id
            )

            kbs.get_by_id.assert_awaited_once_with(kbs.get_by_id.await_args.args[0], kb_id)
            kbs.get_for_collection.assert_not_called()
            assert resolved is not None and resolved.key_source == EmbeddingKeySource.DEPLOYMENT


class TestCredentialDegradation:
    """Every failure lands on the deployment key, saying which failure it was.

    The key itself is the same on all four fallback paths, so `api_key` alone
    cannot tell an operator whether they never chose a key or chose one that is
    now gone. `key_source` is what carries that out to the flow log and the
    error left on the document row.
    """

    async def test_a_deleted_secret_falls_back_to_the_deployment_key(self):
        with patch(f"{_MODULE}.settings") as env:
            env.OPENROUTER_API_KEY = "sk-deployment"
            resolved, _ = await _resolve(_kb(secret_id=uuid.uuid4()), None)

        assert resolved is not None
        assert resolved.api_key == "sk-deployment"
        assert resolved.key_source is EmbeddingKeySource.SECRET_MISSING

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
        assert resolved.key_source is EmbeddingKeySource.SECRET_UNUSABLE

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
        assert resolved.key_source is EmbeddingKeySource.SECRET_WRONG_KIND

    async def test_a_personal_collection_never_looks_in_a_vault(self):
        """No organization, no vault scope to open an envelope with."""
        with patch(f"{_MODULE}.settings") as env:
            env.OPENROUTER_API_KEY = "sk-deployment"
            resolved, secrets = await _resolve(_kb(secret_id=uuid.uuid4(), organization_id=None))

        assert resolved is not None
        assert resolved.api_key == "sk-deployment"
        assert resolved.key_source is EmbeddingKeySource.DEPLOYMENT
        secrets.get.assert_not_called()


class TestSayingWhichKeyPaid:
    """A fallback nobody can see is a fallback nobody can fix.

    Until #306 the three degradations were a `logger.warning` in this module
    and nothing else: not in the Prefect flow log, not in the error on the
    document row, not in the product. An organization that had chosen a key
    could be billed to the deployment's account with nothing anywhere saying
    so.
    """

    @pytest.mark.parametrize("source", list(EmbeddingKeySource))
    def test_every_source_says_which_key_paid_or_that_none_did(
        self, source: EmbeddingKeySource
    ) -> None:
        explanation = source.explanation

        assert explanation
        if source is EmbeddingKeySource.DEPLOYMENT:
            assert "OPENROUTER_API_KEY" in explanation
        else:
            # Naming the deployment's variable is advice for the operator of a
            # deployment the reader may not be running, and it is wrong outright
            # where that key is for another provider's endpoint.
            assert "OPENROUTER_API_KEY" not in explanation

    def test_only_a_key_that_was_asked_for_and_not_given_counts_as_degraded(self):
        """A collection that chose no key embedding on the deployment's is the
        documented normal path, not an incident to log per document."""
        degraded = {source for source in EmbeddingKeySource if source.is_degraded}

        assert degraded == {
            EmbeddingKeySource.SECRET_MISSING,
            EmbeddingKeySource.SECRET_UNUSABLE,
            EmbeddingKeySource.SECRET_WRONG_KIND,
            EmbeddingKeySource.FOREIGN_PROVIDER,
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
    """The address is the collection's own now, and it travels with the key.

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

    async def test_another_providers_collection_gets_no_deployment_key(self):
        """The deployment has one key and it belongs to one endpoint. Sending it
        to another provider is a refusal with a credential attached."""
        with patch(f"{_MODULE}.settings") as env:
            env.OPENROUTER_API_KEY = "sk-deployment"
            resolved, _ = await _resolve(_kb(provider="openai"))

        assert resolved is not None
        assert resolved.api_key == ""
        assert resolved.key_source is EmbeddingKeySource.FOREIGN_PROVIDER

    async def test_a_broken_key_on_another_provider_says_there_is_none_to_use(self):
        """Which of the two facts leads matters: with nothing to fall back to,
        "no key for this provider" is what the operator acts on."""
        with patch(f"{_MODULE}.settings") as env:
            env.OPENROUTER_API_KEY = "sk-deployment"
            resolved, _ = await _resolve(_kb(secret_id=uuid.uuid4(), provider="openai"), None)

        assert resolved is not None
        assert resolved.api_key == ""
        assert resolved.key_source is EmbeddingKeySource.FOREIGN_PROVIDER

    async def test_a_provider_the_catalog_no_longer_names_falls_back_to_the_deployments(self):
        """An entry removed from the file under a collection using it. The
        alternative is a collection nobody can search because of a catalog edit."""
        with patch(f"{_MODULE}.settings") as env:
            env.OPENROUTER_API_KEY = "sk-deployment"
            resolved, _ = await _resolve(_kb(provider="a-provider-that-left"))

        assert resolved is not None
        assert resolved.provider == "openrouter"
        assert resolved.key_source is EmbeddingKeySource.DEPLOYMENT
