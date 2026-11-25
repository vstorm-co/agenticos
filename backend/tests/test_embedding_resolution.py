"""Tests for per-collection embedding resolution.

Three properties carry the weight. The recorded model and width win - a
collection keeps embedding with what its table was created for, whatever the
deployment default became. A credential failure degrades rather than raising:
whose key *pays* must never decide whether the collection's row can be *read*.
And what it degrades *to* is no key at all - there is no deployment-wide
embedding credential, so a collection that names no usable vault key resolves
to an empty key and a reason, and the embedding client refuses with both.
"""

import uuid
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret
from app.core.vault import VaultScope
from app.db.vector_tables import VectorScope
from app.services.embedding_resolution import (
    EmbeddingKeySource,
    EmbeddingSettings,
    ResolvedEmbeddings,
    TargetIdentity,
    embeddings_for_collection,
    identify_target,
    open_target,
)

pytestmark = pytest.mark.anyio

_MODULE = "app.services.embedding_resolution"
_ORG = uuid.uuid4()
_KB = uuid.uuid4()
_GENERATION = uuid.uuid4()


def _kb(
    *,
    secret_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = _ORG,
    provider: str = "openrouter",
    endpoint_id: uuid.UUID | None = None,
    base_url: str | None = None,
):
    return MagicMock(
        collection_name="handbook",
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        embedding_secret_id=secret_id,
        organization_id=organization_id,
        embedding_provider=provider,
        embedding_endpoint_id=endpoint_id,
        embedding_base_url=base_url,
        vector_scope=VectorScope(tenant=organization_id, knowledge_base_id=_KB),
    )


def _service_connection(
    *,
    base_url: str = "http://ollama:11434/v1",
    active: bool = True,
    provider: str = "ollama",
    requires_key: bool = False,
    secret_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = _ORG,
):
    """A `service_connections` row of kind `embedding`, as the resolver reads it."""
    return MagicMock(
        id=uuid.uuid4(),
        base_url=base_url,
        is_active=active,
        kind="embedding",
        provider=provider,
        requires_key=requires_key,
        secret_id=secret_id,
        organization_id=organization_id,
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


async def _resolve(kb, secret_row=None, endpoint_row=None):
    """Run the resolver against one KB row, an optional vault row and an
    optional service-connection row.

    Returns the resolution and the secret-repo mock, so a test can assert the
    vault was - or was not - consulted.
    """
    with (
        patch(f"{_MODULE}.get_db_context") as db_ctx,
        patch(f"{_MODULE}.knowledge_base_repo") as kbs,
        patch(f"{_MODULE}.organization_secret_repo") as secrets,
        patch(f"{_MODULE}.service_connection_repo") as services,
    ):
        db_ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        kbs.get_for_collection = AsyncMock(return_value=kb)
        secrets.get = AsyncMock(return_value=secret_row)
        secrets.authorization_generation = AsyncMock(
            return_value=None if secret_row is None else _GENERATION
        )
        services.get_visible = AsyncMock(return_value=endpoint_row)
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
            # The base's own vector scope: its tenant (#1684) and the base
            # itself (#2537).
            vector_scope=VectorScope(tenant=_ORG, knowledge_base_id=_KB),
        )

    @pytest.mark.security
    async def test_the_resolved_base_scopes_its_runtime_rows(self):
        """The scope the runtime vector table is read under rides home with the
        key, and it is the resolved base's own - so a search by name reads that
        base's chunks and no same-named base's of the same tenant (#2537). What
        the scope holds for each kind of base is `KnowledgeBase.vector_scope`'s,
        pinned in `tests/test_rag_ingest_tenant_scope.py`."""
        kb = _kb(secret_id=uuid.uuid4())
        resolved, _ = await _resolve(kb, _sealed_key_row("sk-valid-key"))

        assert resolved is not None
        assert resolved.vector_scope is kb.vector_scope

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
            vector_scope=VectorScope(tenant=None),
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
        row = _sealed_key_row("sk-org-key")
        with patch(f"{_MODULE}.unseal_secret", return_value=MagicMock(spec=[])):
            resolved, _ = await _resolve(_kb(secret_id=uuid.uuid4()), row)

        assert resolved is not None
        assert resolved.api_key == ""
        assert resolved.key_source is EmbeddingKeySource.SECRET_WRONG_KIND

    async def test_a_collection_with_no_organization_never_looks_in_a_vault(self):
        """No organization, no vault scope to open an envelope with - and no
        deployment key to hand it instead. Said as its own reason: telling an
        app-scoped collection to choose a key from its organization's vault is
        advice it cannot follow (#1631)."""
        resolved, secrets = await _resolve(_kb(secret_id=uuid.uuid4(), organization_id=None))

        assert resolved is not None
        assert resolved.api_key == ""
        assert resolved.key_source is EmbeddingKeySource.NO_VAULT
        assert "#1631" in resolved.key_source.explanation
        assert "organization's vault" not in resolved.key_source.explanation
        secrets.get.assert_not_called()


class TestAKeylessProvider:
    """A server on the deployment's own network wants no credential (#1632); the
    collection names the service connection that carries its address."""

    async def test_resolves_to_no_key_and_the_services_address_without_opening_the_vault(self):
        resolved, secrets = await _resolve(
            _kb(provider="ollama", endpoint_id=uuid.uuid4()),
            _sealed_key_row("sk-left-behind"),
            _service_connection(base_url="http://gpu-box:11434/v1"),
        )

        assert resolved is not None
        assert resolved.api_key == ""
        assert resolved.base_url == "http://gpu-box:11434/v1"
        assert resolved.key_source is EmbeddingKeySource.KEYLESS
        assert not resolved.key_source.is_degraded
        secrets.get.assert_not_called()

    async def test_a_key_left_over_from_a_keyed_provider_stays_sealed(self):
        """Moving to a keyless provider leaves the row's key where it is; the
        resolver must not unseal a credential nothing will send."""
        resolved, secrets = await _resolve(
            _kb(secret_id=uuid.uuid4(), provider="ollama", endpoint_id=uuid.uuid4()),
            _sealed_key_row("sk-left-behind"),
            _service_connection(),
        )

        assert resolved is not None
        assert resolved.api_key == ""
        assert resolved.key_source is EmbeddingKeySource.KEYLESS
        secrets.get.assert_not_called()

    async def test_an_app_scoped_collection_embeds_through_the_deployments_service(self):
        """The one way a collection with no vault can embed (#1631)."""
        resolved, _ = await _resolve(
            _kb(provider="ollama", organization_id=None, endpoint_id=uuid.uuid4()),
            None,
            _service_connection(),
        )

        assert resolved is not None
        assert resolved.key_source is EmbeddingKeySource.KEYLESS

    async def test_a_collection_naming_no_service_says_so(self):
        resolved, _ = await _resolve(_kb(provider="ollama"))

        assert resolved is not None
        assert resolved.base_url == ""
        assert resolved.key_source is EmbeddingKeySource.ENDPOINT_MISSING
        assert resolved.key_source.is_degraded

    async def test_a_service_that_was_deleted_or_is_anothers_reads_as_gone(self):
        """`SET NULL` on delete makes the first the same as naming none; a service
        id from another tenant is invisible and so the same again."""
        resolved, _ = await _resolve(_kb(provider="ollama", endpoint_id=uuid.uuid4()), None, None)

        assert resolved is not None
        assert resolved.key_source is EmbeddingKeySource.ENDPOINT_MISSING

    async def test_a_service_turned_off_is_told_apart_from_one_that_is_gone(self):
        """The remedies differ: turn it on, or choose another."""
        resolved, _ = await _resolve(
            _kb(provider="ollama", endpoint_id=uuid.uuid4()),
            None,
            _service_connection(active=False),
        )

        assert resolved is not None
        assert resolved.key_source is EmbeddingKeySource.ENDPOINT_PAUSED
        assert "turned off" in resolved.key_source.explanation


def _custom_kb(**overrides):
    return _kb(provider="openai_compatible", endpoint_id=uuid.uuid4(), **overrides)


class TestACustomConnection:
    """`openai_compatible` is reached at its connection's address, on the key the
    connection carries - never the collection's."""

    async def test_a_custom_collection_embeds_with_its_connections_url_and_key(self):
        key = uuid.uuid4()
        resolved, secrets = await _resolve(
            _custom_kb(),
            _sealed_key_row("sk-gateway"),
            _service_connection(
                provider="openai_compatible",
                base_url="https://gateway.example.com/v1",
                requires_key=True,
                secret_id=key,
            ),
        )

        assert resolved is not None
        assert resolved.key_source is EmbeddingKeySource.CONNECTION
        assert resolved.base_url == "https://gateway.example.com/v1"
        assert resolved.api_key == "sk-gateway"
        assert not resolved.key_source.is_degraded
        assert secrets.get.await_args.args[1] == key

    async def test_a_custom_collection_on_a_keyless_connection_is_keyless(self):
        resolved, secrets = await _resolve(
            _custom_kb(),
            None,
            _service_connection(
                provider="openai_compatible", base_url="https://gateway.example.com/v1"
            ),
        )

        assert resolved is not None
        assert resolved.key_source is EmbeddingKeySource.KEYLESS
        assert resolved.api_key == ""
        assert resolved.base_url == "https://gateway.example.com/v1"
        secrets.get.assert_not_called()

    @pytest.mark.security
    async def test_a_keyed_connection_whose_key_was_deleted_is_refused_by_name(self):
        """`secret_id` is `SET NULL` on delete and `requires_key` stays, so the
        endpoint is not called bare."""
        resolved, _ = await _resolve(
            _custom_kb(),
            None,
            _service_connection(provider="openai_compatible", requires_key=True),
        )

        assert resolved is not None
        assert resolved.key_source is EmbeddingKeySource.CONNECTION_KEY_MISSING
        assert resolved.base_url == ""
        assert resolved.api_key == ""

    @pytest.mark.security
    async def test_a_keyed_connection_whose_secret_row_is_gone_is_refused_by_name(self):
        resolved, _ = await _resolve(
            _custom_kb(),
            None,
            _service_connection(
                provider="openai_compatible", requires_key=True, secret_id=uuid.uuid4()
            ),
        )

        assert resolved is not None
        assert resolved.key_source is EmbeddingKeySource.CONNECTION_KEY_MISSING
        assert resolved.base_url == ""

    @pytest.mark.security
    async def test_a_connection_key_that_cannot_be_unsealed_is_unusable(self):
        broken = MagicMock(
            sealed_secret="not-a-ciphertext", kind=SecretKind.API_KEY.value, key_version=1
        )
        resolved, _ = await _resolve(
            _custom_kb(),
            broken,
            _service_connection(
                provider="openai_compatible", requires_key=True, secret_id=uuid.uuid4()
            ),
        )

        assert resolved is not None
        assert resolved.key_source is EmbeddingKeySource.CONNECTION_KEY_UNUSABLE
        assert resolved.api_key == ""
        assert resolved.base_url == ""

    @pytest.mark.security
    async def test_a_connection_key_that_is_not_an_api_key_is_unusable(self):
        with patch(f"{_MODULE}.unseal_secret", return_value=MagicMock(spec=[])):
            resolved, _ = await _resolve(
                _custom_kb(),
                _sealed_key_row("sk-xxxxxxxxxx"),
                _service_connection(
                    provider="openai_compatible", requires_key=True, secret_id=uuid.uuid4()
                ),
            )

        assert resolved is not None
        assert resolved.key_source is EmbeddingKeySource.CONNECTION_KEY_UNUSABLE
        assert resolved.base_url == ""

    @pytest.mark.parametrize(
        ("row", "expected"),
        [
            (None, EmbeddingKeySource.ENDPOINT_MISSING),
            (
                _service_connection(provider="openai_compatible", active=False),
                EmbeddingKeySource.ENDPOINT_PAUSED,
            ),
        ],
        ids=["missing", "paused"],
    )
    async def test_a_paused_or_missing_connection_is_named(self, row, expected):
        resolved, _ = await _resolve(_custom_kb(), None, row)

        assert resolved is not None
        assert resolved.key_source is expected
        assert resolved.base_url == ""

    @pytest.mark.parametrize(
        "case",
        ["organization", "keyless", "connection"],
    )
    async def test_no_path_that_can_embed_has_an_empty_url(self, case):
        key = uuid.uuid4()
        if case == "organization":
            resolved, _ = await _resolve(_kb(secret_id=key), _sealed_key_row("sk-aaaaaaaaaa"))
        elif case == "keyless":
            resolved, _ = await _resolve(
                _kb(provider="ollama", endpoint_id=uuid.uuid4()), None, _service_connection()
            )
        else:
            resolved, _ = await _resolve(
                _custom_kb(),
                _sealed_key_row("sk-aaaaaaaaaa"),
                _service_connection(provider="openai_compatible", requires_key=True, secret_id=key),
            )

        assert resolved is not None
        assert not resolved.key_source.is_degraded
        assert resolved.base_url != ""

    async def test_the_identity_never_carries_the_key(self):
        db = MagicMock()
        key = uuid.uuid4()
        with (
            patch(f"{_MODULE}.organization_secret_repo") as secrets,
            patch(f"{_MODULE}.service_connection_repo") as services,
        ):
            secrets.authorization_generation = AsyncMock(return_value=_GENERATION)
            secrets.get = AsyncMock(return_value=_sealed_key_row("sk-never-in-identity"))
            services.get_visible = AsyncMock(
                return_value=_service_connection(
                    provider="openai_compatible", requires_key=True, secret_id=key
                )
            )
            identity = await identify_target(
                db, EmbeddingSettings.of(_custom_kb()), organization_id=_ORG
            )
            target = await open_target(db, identity)

        assert target.api_key == "sk-never-in-identity"
        assert "sk-never-in-identity" not in repr(identity)
        assert "sk-never-in-identity" not in str(asdict(identity))
        assert "sk-never-in-identity" not in repr(target)
        secrets.get.assert_awaited_once()

    async def test_the_identity_names_the_keys_generation(self):
        key = uuid.uuid4()
        with (
            patch(f"{_MODULE}.organization_secret_repo") as secrets,
            patch(f"{_MODULE}.service_connection_repo") as services,
        ):
            secrets.authorization_generation = AsyncMock(return_value=_GENERATION)
            secrets.get = AsyncMock()
            services.get_visible = AsyncMock(
                return_value=_service_connection(
                    provider="openai_compatible", requires_key=True, secret_id=key
                )
            )
            identity = await identify_target(
                MagicMock(), EmbeddingSettings.of(_custom_kb()), organization_id=_ORG
            )

        assert identity.key_generation == _GENERATION
        assert identity.secret_id == key
        assert identity.key_organization_id == _ORG
        assert identity.key_source is EmbeddingKeySource.CONNECTION
        secrets.get.assert_not_called()  # identifying unseals nothing

    async def test_a_key_that_vanishes_between_identifying_and_opening_degrades(self):
        """The two steps are separate reads, so the row can be deleted between them."""
        identity = TargetIdentity(
            provider="openai_compatible",
            connection_id=uuid.uuid4(),
            base_url="https://gateway.example.com/v1",
            secret_id=uuid.uuid4(),
            key_generation=_GENERATION,
            key_organization_id=_ORG,
            key_source=EmbeddingKeySource.CONNECTION,
        )
        with patch(f"{_MODULE}.organization_secret_repo") as secrets:
            secrets.get = AsyncMock(return_value=None)
            target = await open_target(MagicMock(), identity)

        assert target.identity.key_source is EmbeddingKeySource.CONNECTION_KEY_MISSING
        assert target.identity.base_url == ""
        assert target.api_key == ""
        assert not target.keyless

    async def test_an_identity_naming_no_key_is_never_opened(self):
        identity = TargetIdentity(
            provider="openai_compatible",
            connection_id=uuid.uuid4(),
            base_url="https://gateway.example.com/v1",
            secret_id=None,
            key_generation=None,
            key_organization_id=None,
            key_source=EmbeddingKeySource.CONNECTION,
        )
        with patch(f"{_MODULE}.organization_secret_repo") as secrets:
            target = await open_target(MagicMock(), identity)

        assert target.identity.key_source is EmbeddingKeySource.CONNECTION_KEY_MISSING
        secrets.get.assert_not_called()

    async def test_a_keyless_identity_opens_to_a_keyless_target(self):
        identity = TargetIdentity(
            provider="ollama",
            connection_id=uuid.uuid4(),
            base_url="http://ollama:11434/v1",
            secret_id=None,
            key_generation=None,
            key_organization_id=None,
            key_source=EmbeddingKeySource.KEYLESS,
        )

        target = await open_target(MagicMock(), identity)

        assert target.keyless
        assert target.api_key == ""
        assert "api_key='***'" in repr(target)

    async def test_a_catalog_keys_degradation_keeps_the_vendors_address(self):
        broken = MagicMock(sealed_secret="nope", kind=SecretKind.API_KEY.value, key_version=1)
        resolved, _ = await _resolve(_kb(secret_id=uuid.uuid4()), broken)

        assert resolved is not None
        assert resolved.key_source is EmbeddingKeySource.SECRET_UNUSABLE
        assert resolved.base_url == "https://openrouter.ai/api/v1"

    async def test_a_degradation_names_the_collection_in_the_log(self, caplog):
        with caplog.at_level("WARNING"):
            await _resolve(_kb(secret_id=uuid.uuid4()), None)

        assert any(getattr(r, "collection", None) == "handbook" for r in caplog.records)

    @pytest.mark.parametrize("wrong_kind", [False, True])
    async def test_an_unopenable_key_names_the_collection_in_the_log(self, caplog, wrong_kind):
        row = _sealed_key_row("sk-aaaaaaaaaa")
        if not wrong_kind:
            row = MagicMock(sealed_secret="nope", kind=SecretKind.API_KEY.value, key_version=1)
        with (
            caplog.at_level("WARNING"),
            patch(
                f"{_MODULE}.unseal_secret",
                **(
                    {"return_value": MagicMock(spec=[])}
                    if wrong_kind
                    else {"side_effect": ValueError}
                ),
            ),
        ):
            await _resolve(_kb(secret_id=uuid.uuid4()), row)

        assert any(getattr(r, "collection", None) == "handbook" for r in caplog.records)

    async def test_an_unknown_provider_names_provider_and_collection_in_the_log(self, caplog):
        with caplog.at_level("WARNING"):
            await _resolve(_kb(provider="a-provider-that-left"))

        record = next(r for r in caplog.records if r.getMessage() == "embedding_provider_unknown")
        assert (record.collection, record.provider) == ("handbook", "a-provider-that-left")

    async def test_an_unknown_provider_resolves_to_no_address_and_no_key(self):
        resolved, secrets = await _resolve(_kb(provider="a-provider-that-left"))

        assert resolved is not None
        assert resolved.key_source is EmbeddingKeySource.PROVIDER_UNKNOWN
        assert resolved.base_url == ""
        secrets.get.assert_not_called()


class TestSayingWhichKeyPaid:
    """A degradation nobody can see is a degradation nobody can fix.

    Until #306 the three degradations were a `logger.warning` in this module
    and nothing else: not in the worker's log, not in the error on the
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

        assert EmbeddingKeySource.KEYLESS not in degraded
        assert EmbeddingKeySource.CONNECTION not in degraded
        assert degraded == {
            EmbeddingKeySource.NONE_CHOSEN,
            EmbeddingKeySource.NO_VAULT,
            EmbeddingKeySource.SECRET_MISSING,
            EmbeddingKeySource.SECRET_UNUSABLE,
            EmbeddingKeySource.SECRET_WRONG_KIND,
            EmbeddingKeySource.PROVIDER_UNKNOWN,
            EmbeddingKeySource.ENDPOINT_MISSING,
            EmbeddingKeySource.ENDPOINT_PAUSED,
            EmbeddingKeySource.CONNECTION_KEY_MISSING,
            EmbeddingKeySource.CONNECTION_KEY_UNUSABLE,
        }

    def test_every_source_has_a_sentence_of_its_own(self):
        """A source without an explanation is a KeyError on the first document
        that lands on it, in the flow log's own error path."""
        sentences = {source.explanation for source in EmbeddingKeySource}

        assert len(sentences) == len(EmbeddingKeySource)

    def test_the_description_names_the_collection_the_provider_and_the_key(self):
        resolved = ResolvedEmbeddings(
            model="text-embedding-3-small",
            dim=1536,
            api_key="",
            key_source=EmbeddingKeySource.SECRET_MISSING,
            base_url="https://openrouter.ai/api/v1",
            provider="openrouter",
            vector_scope=VectorScope(tenant=None),
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
        """An entry removed from the file under a collection using it. The row
        can still be read - its model and width are its own - but it resolves
        to no address and no key: the key was stored for the provider that is
        gone, and sending it anywhere else would hand one vendor's credential to
        another. The reason travels with the resolution, naming the provider
        the row recorded, so the flow log says "move the collection" rather
        than "choose a key" - the collection has one."""
        resolved, secrets = await _resolve(
            _kb(secret_id=uuid.uuid4(), provider="a-provider-that-left"),
            _sealed_key_row("sk-for-the-old-provider"),
        )

        assert resolved is not None
        assert resolved.provider == "a-provider-that-left"
        assert resolved.base_url == ""
        assert resolved.api_key == ""
        assert resolved.key_source is EmbeddingKeySource.PROVIDER_UNKNOWN
        assert "no longer in this build's catalog" in resolved.describe("handbook")
        assert "a-provider-that-left" in resolved.describe("handbook")
        secrets.get.assert_not_called()


async def test_regional_openrouter_embeddings_keep_the_selected_endpoint():
    resolved, _ = await _resolve(
        _kb(secret_id=uuid.uuid4(), base_url="https://eu.openrouter.ai/api/v1"),
        _sealed_key_row("sk-regional-test"),
    )
    assert resolved is not None
    assert resolved.base_url == "https://eu.openrouter.ai/api/v1"
    assert resolved.api_key == "sk-regional-test"
