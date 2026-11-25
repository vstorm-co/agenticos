"""Testing an embedding change against what is stored, and the call that does it.

The probe decides whether a save may skip re-indexing, so the cases worth a test
are the ways it could pass wrongly - a threshold off by one, a base compared in
another's scope, a token minted for a failure - and the ways it could spend
before it was allowed to: every refusal asserts that no request went out.
"""

import math
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.budget import BudgetExceeded
from app.agents.capabilities.budget._capability import BudgetScope
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.schemas.embedding_probe import (
    ConnectionProbeRequest,
    KbEmbeddingProbeRequest,
    NewEmbeddingProbeRequest,
)
from app.services import embedding_probe as probe
from app.services.embedding_probe import (
    PROBE_MIN_COSINE,
    EmbeddingProbeService,
    ProbeOutcome,
    min_cosine,
)
from app.services.embedding_probe_token import ProbeBinding, ProbePurpose, read_probe_token
from app.services.embedding_resolution import (
    EmbeddingKeySource,
    EmbeddingSettings,
    EmbeddingTarget,
    TargetIdentity,
)
from app.services.rag.embeddings import EmbeddingProbeError
from app.services.rag.models import StoredChunk

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_EMBED = "app.services.embedding_probe.embed_for_probe"


def _ctx(*, app_admin: bool = False) -> AuthContext:
    return AuthContext(
        user_id=uuid.uuid4(),
        organization_id=_ORG,
        role=OrgRoleName.OWNER.value,
        is_app_admin=app_admin,
    )


def _kb(organization_id: uuid.UUID | None = _ORG, name: str = "Docs") -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=name,
        scope=KBScope.ORG.value,
        collection_name=f"c_{uuid.uuid4().hex[:8]}",
        embedding_provider="openai_compatible",
        embedding_model="m",
        embedding_dim=2,
        organization_id=organization_id,
    )


def _identity(source: EmbeddingKeySource = EmbeddingKeySource.CONNECTION) -> TargetIdentity:
    keyed = source is EmbeddingKeySource.CONNECTION
    return TargetIdentity(
        provider="openai_compatible",
        connection_id=uuid.uuid4(),
        base_url="https://gateway.example/v1",
        secret_id=uuid.uuid4() if keyed else None,
        key_generation=uuid.uuid4() if keyed else None,
        key_organization_id=_ORG if keyed else None,
        key_source=source,
    )


def _chunks(*vectors: list[float]) -> list[StoredChunk]:
    return [StoredChunk(content=f"chunk {i}", embedding=v) for i, v in enumerate(vectors)]


def _store(**by_collection: list[StoredChunk]) -> MagicMock:
    store = MagicMock()

    async def probe_chunks(name: str, scope: object, **_: object) -> list[StoredChunk]:
        return by_collection.get(name, [])

    store.probe_chunks = AsyncMock(side_effect=probe_chunks)
    return store


@pytest.fixture
def identity(monkeypatch: pytest.MonkeyPatch) -> TargetIdentity:
    """Rows resolve to a keyed connection whose key opens; nothing else is read."""
    found = _identity()
    monkeypatch.setattr(probe, "identify_target", AsyncMock(return_value=found))
    monkeypatch.setattr(probe, "identify_connection", AsyncMock(return_value=found))
    monkeypatch.setattr(
        probe, "open_target", AsyncMock(return_value=EmbeddingTarget(found, api_key="sk-secret"))
    )
    monkeypatch.setattr(probe, "assert_organization_within_budget", AsyncMock())
    return found


def _service(store: MagicMock, kb: KnowledgeBase | None = None) -> EmbeddingProbeService:
    service = EmbeddingProbeService(MagicMock(), store)
    if kb is not None:
        service.bases.get_for_write = AsyncMock(return_value=kb)  # type: ignore[method-assign]
        service.bases.plan_embedding = AsyncMock(  # type: ignore[method-assign]
            return_value=EmbeddingSettings(
                provider="openai_compatible",
                endpoint_id=uuid.uuid4(),
                secret_id=None,
                base_url=None,
                model="new-model",
            )
        )
    return service


def _same(vectors: list[StoredChunk]) -> AsyncMock:
    """An endpoint that answers every text with the vector it was stored at."""
    by_text = {chunk.content: chunk.embedding for chunk in vectors}
    return AsyncMock(side_effect=lambda **kwargs: list(by_text[kwargs["text"]]))


def _at_angle(cosine: float) -> list[float]:
    return [cosine, math.sqrt(1 - cosine**2)]


class TestTheComparison:
    def test_identical_vectors_score_one_and_orthogonal_zero(self) -> None:
        assert min_cosine([[1.0, 2.0]], [[1.0, 2.0]]) == pytest.approx(1.0)
        assert min_cosine([[1.0, 0.0]], [[0.0, 1.0]]) == pytest.approx(0.0)

    def test_min_cosine_is_the_minimum_not_the_mean(self) -> None:
        assert min_cosine([[1.0, 0.0], [1.0, 0.0]], [[1.0, 0.0], [0.0, 1.0]]) == pytest.approx(0.0)

    def test_vectors_are_normalised_before_comparison(self) -> None:
        assert min_cosine([[1.0, 2.0]], [[10.0, 20.0]]) == pytest.approx(1.0)

    def test_a_zero_vector_is_similar_to_nothing(self) -> None:
        assert min_cosine([[0.0, 0.0]], [[1.0, 0.0]]) == 0.0


class TestRefusalsSpendNothing:
    @pytest.mark.security
    async def test_a_probe_on_a_base_the_caller_cannot_write_is_refused_before_any_call(
        self, identity: TargetIdentity
    ) -> None:
        service = _service(_store())
        service.bases.get_for_write = AsyncMock(side_effect=AuthorizationError(message="no"))  # type: ignore[method-assign]

        with patch(_EMBED, new=AsyncMock()) as embed, pytest.raises(AuthorizationError):
            await service.probe_kb_change(_ctx(), uuid.uuid4(), KbEmbeddingProbeRequest())

        embed.assert_not_awaited()

    @pytest.mark.security
    async def test_probing_with_a_key_the_caller_cannot_view_is_refused_before_any_call(
        self, identity: TargetIdentity
    ) -> None:
        service = _service(_store(), _kb())
        service.bases.plan_embedding = AsyncMock(  # type: ignore[method-assign]
            side_effect=BadRequestError(message="That key is not in this organization's vault")
        )

        with patch(_EMBED, new=AsyncMock()) as embed, pytest.raises(BadRequestError):
            await service.probe_kb_change(_ctx(), uuid.uuid4(), KbEmbeddingProbeRequest())

        embed.assert_not_awaited()

    @pytest.mark.security
    async def test_a_deployment_connection_probe_by_an_org_operator_is_refused(
        self, identity: TargetIdentity
    ) -> None:
        row = MagicMock(organization_id=None, kind="embedding")
        service = _service(_store())

        with (
            patch(
                "app.services.service_connection.service_connection_repo.get_visible",
                new=AsyncMock(return_value=row),
            ),
            patch(_EMBED, new=AsyncMock()) as embed,
            pytest.raises(AuthorizationError),
        ):
            await service.probe_connection_change(_ctx(), uuid.uuid4(), ConnectionProbeRequest())

        embed.assert_not_awaited()

    @pytest.mark.security
    async def test_an_org_over_budget_is_refused_before_any_billed_call(
        self, identity: TargetIdentity, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kb = _kb()
        order: list[str] = []
        monkeypatch.setattr(
            probe,
            "assert_organization_within_budget",
            AsyncMock(side_effect=lambda *_: order.append("budget") or _raise()),
        )
        service = _service(_store(**{kb.collection_name: _chunks([1.0, 0.0])}), kb)

        with patch(_EMBED, new=AsyncMock()) as embed, pytest.raises(BudgetExceeded):
            await service.probe_kb_change(_ctx(), kb.id, KbEmbeddingProbeRequest())

        embed.assert_not_awaited()
        assert order == ["budget"]

    @pytest.mark.security
    async def test_a_keyless_endpoint_bills_nobody_so_no_budget_is_checked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        keyless = _identity(EmbeddingKeySource.KEYLESS)
        monkeypatch.setattr(probe, "identify_target", AsyncMock(return_value=keyless))
        monkeypatch.setattr(
            probe, "open_target", AsyncMock(return_value=EmbeddingTarget(keyless, api_key=""))
        )
        budget = AsyncMock()
        monkeypatch.setattr(probe, "assert_organization_within_budget", budget)
        kb = _kb()

        result = await _service(_store(), kb).probe_kb_change(
            _ctx(), kb.id, KbEmbeddingProbeRequest()
        )

        assert result.passed
        budget.assert_not_awaited()

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("source", "field"),
        [
            (EmbeddingKeySource.ENDPOINT_PAUSED, "embedding_endpoint_id"),
            (EmbeddingKeySource.CONNECTION_KEY_MISSING, "embedding_endpoint_id"),
            (EmbeddingKeySource.NONE_CHOSEN, "embedding_secret_id"),
            (EmbeddingKeySource.NO_VAULT, "embedding_provider"),
        ],
    )
    async def test_a_paused_connection_is_refused_on_its_field_before_any_call(
        self, monkeypatch: pytest.MonkeyPatch, source: EmbeddingKeySource, field: str
    ) -> None:
        degraded = TargetIdentity("openai_compatible", None, "", None, None, None, source)
        monkeypatch.setattr(probe, "identify_target", AsyncMock(return_value=degraded))
        kb = _kb()

        with patch(_EMBED, new=AsyncMock()) as embed, pytest.raises(BadRequestError) as refused:
            await _service(_store(), kb).probe_kb_change(_ctx(), kb.id, KbEmbeddingProbeRequest())

        embed.assert_not_awaited()
        assert refused.value.details["fields"][0]["field"] == field

    @pytest.mark.security
    async def test_a_key_that_cannot_be_opened_is_refused_before_any_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        found = _identity()
        unusable = TargetIdentity(
            "openai_compatible",
            found.connection_id,
            "",
            None,
            None,
            None,
            EmbeddingKeySource.CONNECTION_KEY_UNUSABLE,
        )
        monkeypatch.setattr(probe, "identify_target", AsyncMock(return_value=found))
        monkeypatch.setattr(
            probe, "open_target", AsyncMock(return_value=EmbeddingTarget(unusable, api_key=""))
        )
        kb = _kb()

        with patch(_EMBED, new=AsyncMock()) as embed, pytest.raises(BadRequestError):
            await _service(_store(), kb).probe_kb_change(_ctx(), kb.id, KbEmbeddingProbeRequest())

        embed.assert_not_awaited()

    @pytest.mark.security
    async def test_the_connection_probe_names_secret_id_for_a_key_that_is_gone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        missing = TargetIdentity(
            "openai_compatible",
            None,
            "",
            None,
            None,
            None,
            EmbeddingKeySource.CONNECTION_KEY_MISSING,
        )
        monkeypatch.setattr(probe, "identify_connection", AsyncMock(return_value=missing))
        service = _service(_store())
        service.connections._editable = AsyncMock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(
                kind="embedding",
                provider="openai_compatible",
                base_url="https://a.example/v1",
                secret_id=None,
                requires_key=True,
                organization_id=_ORG,
                id=uuid.uuid4(),
            )
        )

        with pytest.raises(BadRequestError) as refused:
            await service.probe_connection_change(_ctx(), uuid.uuid4(), ConnectionProbeRequest())

        assert refused.value.details["fields"][0]["field"] == "secret_id"


class TestAProbeOfAKnowledgeBase:
    async def test_a_base_with_no_chunks_passes_with_no_call_and_a_token(
        self, identity: TargetIdentity
    ) -> None:
        kb = _kb()

        with patch(_EMBED, new=AsyncMock()) as embed:
            result = await _service(_store(), kb).probe_kb_change(
                _ctx(), kb.id, KbEmbeddingProbeRequest()
            )

        embed.assert_not_awaited()
        assert (result.passed, result.calls, result.outcome) == (True, 0, "no_chunks")
        assert result.probe_token is not None

    async def test_same_vectors_pass_and_mint_a_token_bound_to_the_tested_values(
        self, identity: TargetIdentity
    ) -> None:
        kb = _kb()
        stored = _chunks([1.0, 0.0], [0.0, 1.0], [1.0, 1.0])
        ctx = _ctx()

        with patch(_EMBED, new=_same(stored)) as embed:
            result = await _service(_store(**{kb.collection_name: stored}), kb).probe_kb_change(
                ctx, kb.id, KbEmbeddingProbeRequest()
            )

        assert (result.passed, result.outcome, result.calls) == (True, "passed", 3)
        assert result.knowledge_bases[0].min_cosine == pytest.approx(1.0)
        assert embed.await_args.kwargs["api_key"] == "sk-secret"
        assert embed.await_args.kwargs["model"] == "new-model"
        assert result.expires_at is not None
        claims = read_probe_token(result.probe_token, ctx=ctx, purpose=ProbePurpose.KB_CHANGE)
        expected = ProbeBinding.of(
            ProbePurpose.KB_CHANGE, identity, model="new-model", dim=2, knowledge_bases=[kb]
        )
        assert claims.fingerprint == expected.fingerprint()

    @pytest.mark.parametrize(
        ("cosine", "passes"),
        [(PROBE_MIN_COSINE + 0.0001, True), (PROBE_MIN_COSINE - 0.0001, False)],
    )
    async def test_the_threshold_is_the_edge_between_pass_and_fail(
        self, identity: TargetIdentity, cosine: float, passes: bool
    ) -> None:
        kb = _kb()
        stored = _chunks([1.0, 0.0])

        with patch(_EMBED, new=AsyncMock(return_value=_at_angle(cosine))):
            result = await _service(_store(**{kb.collection_name: stored}), kb).probe_kb_change(
                _ctx(), kb.id, KbEmbeddingProbeRequest()
            )

        assert result.passed is passes

    async def test_a_cosine_of_exactly_the_threshold_passes_and_one_below_it_fails(
        self, identity: TargetIdentity, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kb = _kb()
        service = _service(_store(**{kb.collection_name: _chunks([1.0, 0.0])}), kb)
        outcomes = []

        for score in (PROBE_MIN_COSINE, 0.9949):
            monkeypatch.setattr(probe, "min_cosine", lambda *_, score=score: score)
            with patch(_EMBED, new=AsyncMock(return_value=[1.0, 0.0])):
                outcomes.append(
                    (await service.probe_kb_change(_ctx(), kb.id, KbEmbeddingProbeRequest())).passed
                )

        assert outcomes == [True, False]

    async def test_a_first_failure_is_retried_once_then_reported(
        self, identity: TargetIdentity
    ) -> None:
        kb = _kb()
        stored = _chunks([1.0, 0.0], [0.0, 1.0], [1.0, 1.0])
        service = _service(_store(**{kb.collection_name: stored}), kb)
        good = {chunk.content: chunk.embedding for chunk in stored}
        wrong = [[0.0, 1.0], [1.0, 0.0], [1.0, -1.0]]
        answers = iter([*wrong, *good.values()])

        with patch(_EMBED, new=AsyncMock(side_effect=lambda **_: next(answers))) as embed:
            recovered = await service.probe_kb_change(_ctx(), kb.id, KbEmbeddingProbeRequest())

        assert (recovered.passed, recovered.calls) == (True, 6)
        assert embed.await_count == 6

        with patch(_EMBED, new=AsyncMock(return_value=[0.0, 1.0])) as always:
            failed = await service.probe_kb_change(_ctx(), kb.id, KbEmbeddingProbeRequest())

        assert (failed.passed, failed.outcome, failed.calls) == (False, "vectors_differ", 6)
        assert always.await_count == 6

    async def test_a_failure_names_the_base_and_the_cause_and_mints_no_token(
        self, identity: TargetIdentity
    ) -> None:
        kb = _kb(name="Handbook")
        stored = _chunks([1.0, 0.0])

        with patch(_EMBED, new=AsyncMock(return_value=[0.0, 1.0])):
            result = await _service(_store(**{kb.collection_name: stored}), kb).probe_kb_change(
                _ctx(), kb.id, KbEmbeddingProbeRequest()
            )

        assert result.probe_token is None
        assert result.expires_at is None
        (read,) = result.knowledge_bases
        assert (read.name, read.outcome) == ("Handbook", "vectors_differ")
        assert read.min_cosine == pytest.approx(0.0)

    async def test_a_width_change_is_wrong_width_not_an_error(
        self, identity: TargetIdentity
    ) -> None:
        kb = _kb()
        stored = _chunks([1.0, 0.0])

        with patch(_EMBED, new=AsyncMock(return_value=[1.0, 0.0, 0.0])):
            result = await _service(_store(**{kb.collection_name: stored}), kb).probe_kb_change(
                _ctx(), kb.id, KbEmbeddingProbeRequest()
            )

        assert (result.passed, result.outcome) == (False, "wrong_width")
        assert result.knowledge_bases[0].min_cosine is None

    @pytest.mark.parametrize("outcome", ["unreachable", "key_refused", "model_unknown"])
    async def test_an_endpoint_failure_is_its_outcome_and_is_retried_once(
        self, identity: TargetIdentity, outcome: str
    ) -> None:
        kb = _kb()
        stored = _chunks([1.0, 0.0], [0.0, 1.0])

        with patch(_EMBED, new=AsyncMock(side_effect=EmbeddingProbeError(outcome))) as embed:
            result = await _service(_store(**{kb.collection_name: stored}), kb).probe_kb_change(
                _ctx(), kb.id, KbEmbeddingProbeRequest()
            )

        assert (result.passed, result.outcome) == (False, outcome)
        assert embed.await_count == 2, "one request per attempt: the first failure stops the pass"

    async def test_the_estimate_counts_exactly_the_requests_the_probe_makes(
        self, identity: TargetIdentity
    ) -> None:
        kb = _kb()
        stored = _chunks([1.0, 0.0], [0.0, 1.0], [1.0, 1.0])
        service = _service(_store(**{kb.collection_name: stored}), kb)

        estimate = await service.estimate_kb_change(_ctx(), kb.id)
        with patch(_EMBED, new=_same(stored)) as embed:
            await service.probe_kb_change(_ctx(), kb.id, KbEmbeddingProbeRequest())

        assert (estimate.calls, estimate.max_calls, estimate.knowledge_bases) == (3, 6, 1)
        assert embed.await_count == estimate.calls

    async def test_a_base_with_only_short_chunks_is_estimated_on_what_is_sampled(
        self, identity: TargetIdentity
    ) -> None:
        kb = _kb()
        only_longest = _chunks([1.0, 0.0])
        service = _service(_store(**{kb.collection_name: only_longest}), kb)

        assert (await service.estimate_kb_change(_ctx(), kb.id)).calls == 1

    async def test_only_what_the_request_names_is_proposed(self, identity: TargetIdentity) -> None:
        kb = _kb()
        service = _service(_store(), kb)

        await service.probe_kb_change(
            _ctx(), kb.id, KbEmbeddingProbeRequest(embedding_model="other", embedding_base_url=None)
        )

        update = service.bases.plan_embedding.await_args.args[1]  # type: ignore[attr-defined]
        assert update.model_fields_set == {"embedding_model", "embedding_base_url"}


class TestAProbeOfAConnection:
    def _connection(self, **overrides: object) -> SimpleNamespace:
        fields: dict[str, object] = {
            "id": uuid.uuid4(),
            "kind": "embedding",
            "provider": "openai_compatible",
            "base_url": "https://old.example/v1",
            "secret_id": None,
            "requires_key": False,
            "organization_id": _ORG,
        }
        return SimpleNamespace(**(fields | overrides))

    async def test_a_deployment_connection_probes_every_base_across_organizations_in_its_own_scope(
        self, identity: TargetIdentity, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mine, theirs = _kb(_ORG, "Mine"), _kb(uuid.uuid4(), "Theirs")
        chunks = _chunks([1.0, 0.0])
        store = _store(**{mine.collection_name: chunks, theirs.collection_name: chunks})
        monkeypatch.setattr(
            probe.knowledge_base_repo, "list_by_endpoint", AsyncMock(return_value=[mine, theirs])
        )
        service = _service(store)
        service.connections._editable = AsyncMock(  # type: ignore[method-assign]
            return_value=self._connection(organization_id=None)
        )

        with patch(_EMBED, new=_same(chunks)):
            result = await service.probe_connection_change(
                _ctx(app_admin=True), uuid.uuid4(), ConnectionProbeRequest()
            )

        scopes = {call.args[0]: call.args[1] for call in store.probe_chunks.await_args_list}
        assert scopes == {
            mine.collection_name: mine.vector_scope,
            theirs.collection_name: theirs.vector_scope,
        }
        assert [read.name for read in result.knowledge_bases] == ["Mine", "Theirs"]
        assert result.passed

    async def test_the_new_address_and_the_bases_own_model_are_what_is_called(
        self, identity: TargetIdentity, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kb = _kb()
        chunks = _chunks([1.0, 0.0])
        monkeypatch.setattr(
            probe.knowledge_base_repo, "list_by_endpoint", AsyncMock(return_value=[kb])
        )
        service = _service(_store(**{kb.collection_name: chunks}))
        service.connections._editable = AsyncMock(return_value=self._connection())  # type: ignore[method-assign]

        with patch(_EMBED, new=_same(chunks)) as embed:
            await service.probe_connection_change(
                _ctx(), uuid.uuid4(), ConnectionProbeRequest(base_url="https://new.example/v1")
            )

        assert embed.await_args.kwargs["model"] == kb.embedding_model
        assert (
            probe.identify_connection.await_args.kwargs["base_url"]  # type: ignore[attr-defined]
            == "https://new.example/v1"
        )

    @pytest.mark.security
    async def test_probing_a_new_address_with_the_kept_key_needs_to_view_it(
        self, identity: TargetIdentity, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kept = uuid.uuid4()
        service = _service(_store())
        service.connections._editable = AsyncMock(  # type: ignore[method-assign]
            return_value=self._connection(secret_id=kept, requires_key=True)
        )
        monkeypatch.setattr(
            "app.services.service_connection.organization_secret_repo.get",
            AsyncMock(return_value=MagicMock()),
        )
        monkeypatch.setattr(
            "app.services.service_connection.resolve_access", AsyncMock(return_value=False)
        )

        with patch(_EMBED, new=AsyncMock()) as embed, pytest.raises(BadRequestError) as refused:
            await service.probe_connection_change(
                _ctx(),
                uuid.uuid4(),
                ConnectionProbeRequest(base_url="https://their-host.example/v1"),
            )

        assert "not in this organization's vault" in refused.value.message
        embed.assert_not_awaited()

    async def test_a_new_key_is_checked_like_a_save_would_check_it(
        self, identity: TargetIdentity
    ) -> None:
        service = _service(_store())
        service.connections._editable = AsyncMock(return_value=self._connection())  # type: ignore[method-assign]
        service.connections._check_key = AsyncMock(  # type: ignore[method-assign]
            side_effect=BadRequestError(message="That key is not in this organization's vault")
        )

        with patch(_EMBED, new=AsyncMock()) as embed, pytest.raises(BadRequestError):
            await service.probe_connection_change(
                _ctx(), uuid.uuid4(), ConnectionProbeRequest(secret_id=uuid.uuid4())
            )

        embed.assert_not_awaited()

    async def test_a_connection_nothing_uses_passes_with_a_token_and_no_call(
        self, identity: TargetIdentity, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            probe.knowledge_base_repo, "list_by_endpoint", AsyncMock(return_value=[])
        )
        service = _service(_store())
        service.connections._editable = AsyncMock(return_value=self._connection())  # type: ignore[method-assign]

        result = await service.probe_connection_change(
            _ctx(), uuid.uuid4(), ConnectionProbeRequest()
        )

        assert (result.passed, result.calls, result.outcome) == (True, 0, "passed")
        assert result.probe_token is not None

    async def test_an_ocr_connection_has_nothing_to_prove(self, identity: TargetIdentity) -> None:
        service = _service(_store())
        ocr = self._connection(kind="ocr", provider="liteparse")
        service.connections._editable = AsyncMock(return_value=ocr)  # type: ignore[method-assign]

        probed = await service.probe_connection_change(
            _ctx(), uuid.uuid4(), ConnectionProbeRequest()
        )
        estimate = await service.estimate_connection_change(_ctx(), uuid.uuid4())

        assert (probed.passed, probed.calls, probed.probe_token) == (True, 0, None)
        assert (estimate.calls, estimate.max_calls, estimate.knowledge_bases) == (0, 0, 0)

    async def test_the_estimate_sums_every_base_on_the_connection(
        self, identity: TargetIdentity, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        one, two = _kb(), _kb()
        store = _store(
            **{
                one.collection_name: _chunks([1.0, 0.0], [0.0, 1.0]),
                two.collection_name: _chunks([1.0, 0.0]),
            }
        )
        monkeypatch.setattr(
            probe.knowledge_base_repo, "list_by_endpoint", AsyncMock(return_value=[one, two])
        )
        service = _service(store)
        service.connections._editable = AsyncMock(return_value=self._connection())  # type: ignore[method-assign]

        estimate = await service.estimate_connection_change(_ctx(), uuid.uuid4())

        assert (estimate.calls, estimate.max_calls, estimate.knowledge_bases) == (3, 6, 2)


class TestMeasuringANewModel:
    def _request(self, scope: str = "org") -> NewEmbeddingProbeRequest:
        return NewEmbeddingProbeRequest.model_validate(
            {"embedding_endpoint_id": str(uuid.uuid4()), "embedding_model": "corp", "scope": scope}
        )

    async def test_measuring_a_new_custom_model_makes_one_call_and_reports_its_width(
        self, identity: TargetIdentity
    ) -> None:
        service = _service(_store())
        service.bases._check_embedding_endpoint = AsyncMock()  # type: ignore[method-assign]
        ctx = _ctx()

        with patch(_EMBED, new=AsyncMock(return_value=[0.1] * 768)) as embed:
            result = await service.measure_new(ctx, self._request())

        assert embed.await_count == 1
        assert embed.await_args.kwargs["text"] == probe.PROBE_WIDTH_TEXT
        assert (result.passed, result.dim, result.calls) == (True, 768, 1)
        claims = read_probe_token(result.probe_token, ctx=ctx, purpose=ProbePurpose.KB_CREATE)
        assert claims.dim == 768

    @pytest.mark.parametrize("width", [0, 4001])
    async def test_a_measured_width_past_4000_is_wrong_width(
        self, identity: TargetIdentity, width: int
    ) -> None:
        service = _service(_store())
        service.bases._check_embedding_endpoint = AsyncMock()  # type: ignore[method-assign]

        with patch(_EMBED, new=AsyncMock(return_value=[0.1] * width)):
            result = await service.measure_new(_ctx(), self._request())

        assert (result.passed, result.outcome, result.dim) == (False, "wrong_width", width)
        assert result.probe_token is None

    async def test_the_widest_the_store_can_index_is_accepted(
        self, identity: TargetIdentity
    ) -> None:
        service = _service(_store())
        service.bases._check_embedding_endpoint = AsyncMock()  # type: ignore[method-assign]

        with patch(_EMBED, new=AsyncMock(return_value=[0.1] * 4000)):
            result = await service.measure_new(_ctx(), self._request())

        assert result.passed

    async def test_an_endpoint_that_will_not_answer_is_a_failed_test_not_an_error(
        self, identity: TargetIdentity
    ) -> None:
        service = _service(_store())
        service.bases._check_embedding_endpoint = AsyncMock()  # type: ignore[method-assign]

        with patch(_EMBED, new=AsyncMock(side_effect=EmbeddingProbeError("key_refused"))):
            result = await service.measure_new(_ctx(), self._request())

        assert (result.passed, result.outcome, result.calls) == (False, "key_refused", 1)

    @pytest.mark.security
    async def test_an_app_scoped_test_needs_the_deployments_administrator(
        self, identity: TargetIdentity
    ) -> None:
        with patch(_EMBED, new=AsyncMock()) as embed, pytest.raises(AuthorizationError):
            await _service(_store()).measure_new(_ctx(), self._request("app"))

        embed.assert_not_awaited()

    @pytest.mark.security
    async def test_a_connection_the_base_may_not_name_is_refused_before_any_call(
        self, identity: TargetIdentity
    ) -> None:
        service = _service(_store())
        service.bases._check_embedding_endpoint = AsyncMock(  # type: ignore[method-assign]
            side_effect=BadRequestError(message="That service connection is not one this may name")
        )

        with patch(_EMBED, new=AsyncMock()) as embed, pytest.raises(BadRequestError):
            await service.measure_new(_ctx(app_admin=True), self._request("app"))

        embed.assert_not_awaited()


def test_the_outcomes_match_the_schema_literal() -> None:
    from typing import get_args

    from app.schemas.embedding_probe import EmbeddingProbeOutcome

    assert {o.value for o in ProbeOutcome} == set(get_args(EmbeddingProbeOutcome))


def _raise() -> None:
    raise BudgetExceeded(limit_usd=Decimal(1), spent_usd=Decimal(2), scope=next(iter(BudgetScope)))
