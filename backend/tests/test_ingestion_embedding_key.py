"""The worker embeds with the collection's key, not the deployment's (#306).

`app/worker/tasks/rag_tasks.py` built its vector store with no `resolver=`,
which is the one construction of five that did. `PgVectorStore._for_collection`
short-circuits to the deployment embedder when it has no resolver, so a
collection's `embedding_secret_id` and `embedding_model` were read by every
path except the one every uploaded document actually takes.

Two failures, and the quiet one is the worse:

- with no `OPENROUTER_API_KEY` set - the normal case when an organization pays
  for its own embeddings - every upload died in the worker advising the
  operator to set a variable, about a collection they had already given a key;
- with both set, embeddings were billed to the deployment's account while the
  product said the organization's key paid, and nothing said otherwise.

So these tests run the real resolver against a knowledge-base row and assert
what the outgoing client was actually built with, rather than that a resolver
was passed.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from app.core.exceptions import ConfigurationError
from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret
from app.core.vault import VaultScope
from app.services.embedding_resolution import EmbeddingKeySource, ResolvedEmbeddings
from app.services.ingestion_config import IngestionConfig
from app.services.rag.config import RAGSettings
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.vectorstore import PgVectorStore
from app.worker.tasks.rag_tasks import (
    _ingestion_service_for,
    _resolve_embeddings_in_flow,
    _say_in_flow_log,
)

pytestmark = pytest.mark.anyio

_RESOLUTION = "app.services.embedding_resolution"
_EMBEDDINGS = "app.services.rag.embeddings"
_ORG = uuid.uuid4()
_MODEL = "text-embedding-3-small"
_DIM = 1536


def _knowledge_base(*, secret_id: uuid.UUID | None):
    return MagicMock(
        collection_name="handbook",
        embedding_model=_MODEL,
        embedding_dim=_DIM,
        embedding_secret_id=secret_id,
        organization_id=_ORG,
    )


def _vault_row(plaintext: str, *, organization_id: uuid.UUID = _ORG):
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


async def _store() -> PgVectorStore:
    """The store the ingestion flow actually builds.

    Built through `_ingestion_service_for` rather than constructed here: what
    #306 was is that function passing no `resolver=`, so a test that wires one
    itself would pass against the bug it exists to catch. Only the processor -
    parsers, chunker, image model, all of which need a session - is stubbed.
    """
    with patch("app.worker.tasks.rag_tasks.IngestionConfigService") as config_service:
        config_service.return_value.build_processor = AsyncMock(return_value=MagicMock())
        service = await _ingestion_service_for(
            MagicMock(), config=IngestionConfig(), organization_id=_ORG
        )
    store = service.store
    assert isinstance(store, PgVectorStore)
    return store


class _CapturedOpenAI:
    """Stands in for the OpenAI SDK, recording what key it was built with."""

    def __init__(self) -> None:
        self.api_keys: list[str] = []
        self.embedded: list[list[str]] = []

    def __call__(self, *, api_key: str, base_url: str | None = None) -> MagicMock:
        self.api_keys.append(api_key)

        def create(*, model: str, input: list[str]) -> MagicMock:
            self.embedded.append(input)
            return MagicMock(
                data=[MagicMock(embedding=[0.0] * _DIM) for _ in input],
                usage=None,
            )

        return MagicMock(embeddings=MagicMock(create=create))


async def _embed_through_the_flows_store(*, secret_id: uuid.UUID | None, vault_row, deployment_key):
    """Embed one query through the flow's store, capturing the client.

    Patches the two repositories the resolver reads and the SDK it ends up
    calling; everything between is the production path.
    """
    openai = _CapturedOpenAI()
    with (
        patch(f"{_RESOLUTION}.get_db_context") as db_ctx,
        patch(f"{_RESOLUTION}.knowledge_base_repo") as bases,
        patch(f"{_RESOLUTION}.organization_secret_repo") as secrets,
        patch(f"{_RESOLUTION}.settings") as resolution_env,
        patch(f"{_EMBEDDINGS}.app_settings") as embedding_env,
        patch(f"{_EMBEDDINGS}.OpenAI", openai),
    ):
        db_ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        bases.get_by_collection_name = AsyncMock(return_value=_knowledge_base(secret_id=secret_id))
        secrets.get = AsyncMock(return_value=vault_row)
        resolution_env.OPENROUTER_API_KEY = deployment_key
        embedding_env.OPENROUTER_API_KEY = deployment_key

        embedder, dim = await (await _store())._for_collection("handbook")
        vector = embedder.embed_query("what is the refund policy")

    return openai, dim, vector


class TestTheCollectionsKeyPays:
    async def test_a_collection_with_a_vault_key_indexes_with_no_deployment_key(self):
        """The reported crash, and the assertion that fixes it.

        `OPENROUTER_API_KEY` empty is the deployment the issue was filed from:
        the organization pays for its own embeddings. Before the resolver was
        wired here, this raised `ConfigurationError` telling the operator to
        set the variable.
        """
        openai, dim, vector = await _embed_through_the_flows_store(
            secret_id=uuid.uuid4(),
            vault_row=_vault_row("sk-org-own-key"),
            deployment_key="",
        )

        assert openai.api_keys == ["sk-org-own-key"]
        assert openai.embedded == [["what is the refund policy"]]
        assert (dim, len(vector)) == (_DIM, _DIM)

    async def test_the_deployment_is_not_billed_when_the_collection_chose_a_key(self):
        """The quiet half. With both keys set nothing failed - the deployment's
        account simply paid for work the product attributed to the
        organization's key."""
        openai, _, _ = await _embed_through_the_flows_store(
            secret_id=uuid.uuid4(),
            vault_row=_vault_row("sk-org-own-key"),
            deployment_key="sk-deployment",
        )

        assert openai.api_keys == ["sk-org-own-key"]

    async def test_a_collection_that_chose_no_key_still_embeds_on_the_deployments(self):
        """The fallback is deliberate, and wiring the resolver must not end it."""
        openai, _, _ = await _embed_through_the_flows_store(
            secret_id=None,
            vault_row=None,
            deployment_key="sk-deployment",
        )

        assert openai.api_keys == ["sk-deployment"]

    def test_a_store_cannot_be_built_without_a_resolver(self):
        """The default is what made forgetting silent for five call sites.

        Five constructions passed a resolver and one did not, and nothing -
        not a type error, not a test, not a log line - distinguished the sixth
        from a deliberate deployment-wide store.
        """
        with pytest.raises(TypeError):
            PgVectorStore(  # ty: ignore[missing-argument]  - that is the assertion
                settings=RAGSettings(), embedding_service=EmbeddingService(settings=RAGSettings())
            )

    async def test_two_collections_on_one_key_do_not_share_each_others_name(self):
        """The embedder cache is keyed by collection as well as by credential.

        It was keyed by (model, key) alone, which is fine while a service is
        only an HTTP client - but it now carries the sentence a refusal prints,
        so the second collection to embed on a shared key would have been
        refused in the first one's name.
        """
        store = await _store()
        resolutions = {
            "handbook": ResolvedEmbeddings(
                model=_MODEL, dim=_DIM, api_key="", key_source=EmbeddingKeySource.SECRET_MISSING
            ),
            "policies": ResolvedEmbeddings(
                model=_MODEL, dim=_DIM, api_key="", key_source=EmbeddingKeySource.DEPLOYMENT
            ),
        }
        store._resolver = AsyncMock(side_effect=lambda name: resolutions[name])

        origins = []
        for collection in resolutions:
            embedder, _ = await store._for_collection(collection)
            with pytest.raises(ConfigurationError) as refusal:
                embedder.embed_query("anything")
            origins.append(refusal.value.details["key_origin"])

        assert "'handbook'" in origins[0] and "no longer in this organization's vault" in origins[0]
        assert "'policies'" in origins[1] and "chose no key of its own" in origins[1]


class TestWhenTheChosenKeyCannotBeUsed:
    """Three refusals that must degrade, and say that they did.

    The resolver deliberately falls back rather than raising - whose key pays
    must not decide whether documents can be found - so the only thing that
    can carry the failure to an operator is the message.
    """

    async def test_a_secret_from_another_organization_is_not_readable(self):
        """The repository scopes every read by `organization_id`, so a secret
        id belonging to another tenant simply is not found - the same answer as
        a deleted one, and never that tenant's key."""
        openai, _, _ = await _embed_through_the_flows_store(
            secret_id=uuid.uuid4(),
            vault_row=None,
            deployment_key="sk-deployment",
        )

        assert openai.api_keys == ["sk-deployment"]

    async def test_an_unsealable_key_says_so_instead_of_naming_a_variable(self):
        openai = _CapturedOpenAI()
        broken = MagicMock(
            sealed_secret="not-a-ciphertext", kind=SecretKind.API_KEY.value, key_version=1
        )

        with (
            patch(f"{_RESOLUTION}.get_db_context") as db_ctx,
            patch(f"{_RESOLUTION}.knowledge_base_repo") as bases,
            patch(f"{_RESOLUTION}.organization_secret_repo") as secrets,
            patch(f"{_RESOLUTION}.settings") as resolution_env,
            patch(f"{_EMBEDDINGS}.OpenAI", openai),
        ):
            db_ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            bases.get_by_collection_name = AsyncMock(
                return_value=_knowledge_base(secret_id=uuid.uuid4())
            )
            secrets.get = AsyncMock(return_value=broken)
            resolution_env.OPENROUTER_API_KEY = ""

            embedder, _ = await (await _store())._for_collection("handbook")
            with pytest.raises(ConfigurationError) as refusal:
                embedder.embed_query("anything")

        assert "'handbook'" in refusal.value.message
        assert "could not be unsealed" in refusal.value.message
        assert refusal.value.details["key_origin"]
        assert openai.api_keys == []

    async def test_a_secret_of_the_wrong_kind_says_which_collection_chose_it(self):
        openai = _CapturedOpenAI()

        with (
            patch(f"{_RESOLUTION}.get_db_context") as db_ctx,
            patch(f"{_RESOLUTION}.knowledge_base_repo") as bases,
            patch(f"{_RESOLUTION}.organization_secret_repo") as secrets,
            patch(f"{_RESOLUTION}.settings") as resolution_env,
            patch(f"{_RESOLUTION}.unseal_secret", return_value=MagicMock(spec=[])),
            patch(f"{_EMBEDDINGS}.OpenAI", openai),
        ):
            db_ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            bases.get_by_collection_name = AsyncMock(
                return_value=_knowledge_base(secret_id=uuid.uuid4())
            )
            secrets.get = AsyncMock(return_value=_vault_row("sk-org"))
            resolution_env.OPENROUTER_API_KEY = ""

            embedder, _ = await (await _store())._for_collection("handbook")
            with pytest.raises(ConfigurationError) as refusal:
                embedder.embed_query("anything")

        assert "'handbook'" in refusal.value.message
        assert "does not hold an API key" in refusal.value.message


class TestWhatTheFlowLogSays:
    """The `logger.warning` in the resolver reaches the worker's stdout and
    stops there, so a degraded credential was invisible to the run an operator
    opens. These pin that a fallback is announced and a normal one is not."""

    async def _resolution(self, key_source: EmbeddingKeySource):
        resolved = ResolvedEmbeddings(
            model=_MODEL, dim=_DIM, api_key="sk-deployment", key_source=key_source
        )
        with (
            patch(
                "app.worker.tasks.rag_tasks.embeddings_for_collection",
                new=AsyncMock(return_value=resolved),
            ),
            patch("app.worker.tasks.rag_tasks._say_in_flow_log") as said,
        ):
            answer = await _resolve_embeddings_in_flow("handbook")
        return answer, said

    async def test_a_degraded_credential_is_announced_with_the_reason(self):
        answer, said = await self._resolution(EmbeddingKeySource.SECRET_MISSING)

        assert answer is not None
        said.assert_called_once()
        assert "no longer in this organization's vault" in said.call_args.args[0]
        assert "'handbook'" in said.call_args.args[0]

    async def test_a_collection_embedding_on_the_key_it_chose_says_nothing(self):
        _, said = await self._resolution(EmbeddingKeySource.ORGANIZATION)

        said.assert_not_called()

    async def test_a_collection_that_chose_no_key_says_nothing_either(self):
        _, said = await self._resolution(EmbeddingKeySource.DEPLOYMENT)

        said.assert_not_called()

    async def test_a_collection_no_knowledge_base_claims_says_nothing(self):
        with (
            patch(
                "app.worker.tasks.rag_tasks.embeddings_for_collection",
                new=AsyncMock(return_value=None),
            ),
            patch("app.worker.tasks.rag_tasks._say_in_flow_log") as said,
        ):
            assert await _resolve_embeddings_in_flow("unclaimed") is None

        said.assert_not_called()

    def test_the_line_goes_to_the_prefect_run_when_there_is_one(self):
        with patch("app.worker.tasks.rag_tasks.get_run_logger") as run_logger:
            _say_in_flow_log("the collection's key is gone")

        run_logger.return_value.warning.assert_called_once_with("the collection's key is gone")

    def test_outside_a_run_it_still_logs_rather_than_raising(self, caplog):
        """`_resolve_embeddings_in_flow` is a plain function: a CLI ingest and
        a test both reach it with no Prefect context, and a log line must never
        be what takes an ingestion down."""
        with caplog.at_level("WARNING"):
            _say_in_flow_log("the collection's key is gone")

        assert "the collection's key is gone" in caplog.text
