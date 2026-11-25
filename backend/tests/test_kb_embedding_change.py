"""Changing where or how a knowledge base embeds needs proof, or an audited override.

The vectors already stored are only comparable with vectors from the space they were
made in, so a save that could move that space is accepted with the token a passing
test left for exactly these settings, or with `unverified`. The refusals matter most:
a missing proof, a proof for other settings or another person, and an override that
would leave a sibling on settings nothing vouches for.
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.repositories import collection_teardown_repo, knowledge_base_repo, rag_document_repo
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.services.embedding_probe_token import ProbeBinding, ProbePurpose, mint_probe_token
from app.services.embedding_resolution import EmbeddingKeySource, TargetIdentity
from app.services.knowledge_base import KnowledgeBaseService
from app.services.rag import embedding_providers

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()
ENDPOINT = uuid.uuid4()
OTHER_ENDPOINT = uuid.uuid4()
SECRET = uuid.uuid4()
OTHER_SECRET = uuid.uuid4()
GENERATION = uuid.uuid4()
_AT = "app.services.knowledge_base"


def _ctx() -> AuthContext:
    return AuthContext(
        user_id=uuid.uuid4(), organization_id=ORG, role=OrgRoleName.OWNER.value, is_app_admin=False
    )


def _custom(**overrides: Any) -> KnowledgeBase:
    """A base on a custom endpoint at width 4."""
    return KnowledgeBase(
        **{
            "id": uuid.uuid4(),
            "name": "Custom",
            "scope": KBScope.ORG.value,
            "collection_name": "shared",
            "embedding_model": "m",
            "embedding_dim": 4,
            "embedding_provider": "openai_compatible",
            "embedding_endpoint_id": ENDPOINT,
            "organization_id": ORG,
        }
        | overrides
    )


def _keyed(**overrides: Any) -> KnowledgeBase:
    """A base on OpenRouter, paying with a vault key."""
    return KnowledgeBase(
        **{
            "id": uuid.uuid4(),
            "name": "Keyed",
            "scope": KBScope.ORG.value,
            "collection_name": "shared",
            "embedding_model": "text-embedding-3-small",
            "embedding_dim": 1536,
            "embedding_provider": "openrouter",
            "embedding_secret_id": SECRET,
            "organization_id": ORG,
        }
        | overrides
    )


def _identity(*, generation: uuid.UUID = GENERATION, **overrides: Any) -> TargetIdentity:
    return TargetIdentity(
        **{
            "provider": "openai_compatible",
            "connection_id": ENDPOINT,
            "base_url": "https://gateway.example/v1",
            "secret_id": SECRET,
            "key_generation": generation,
            "key_organization_id": ORG,
            "key_source": EmbeddingKeySource.CONNECTION,
        }
        | overrides
    )


def _token(
    ctx: AuthContext,
    kb: KnowledgeBase,
    *,
    model: str,
    identity: TargetIdentity | None = None,
    purpose: ProbePurpose = ProbePurpose.KB_CHANGE,
) -> str:
    binding = ProbeBinding.of(
        purpose,
        identity or _identity(),
        model=model,
        dim=kb.embedding_dim,
        knowledge_bases=[kb],
    )
    return mint_probe_token(ctx, binding)[0]


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    recorded = AsyncMock()
    monkeypatch.setattr(f"{_AT}.record_audit", recorded)
    return recorded


@pytest.fixture
def updated(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    writes = AsyncMock(side_effect=lambda _db, db_kb, **_: db_kb)
    monkeypatch.setattr(knowledge_base_repo, "update", writes)
    return writes


@pytest.fixture
def identified(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    found = AsyncMock(return_value=_identity())
    monkeypatch.setattr(f"{_AT}.identify_target", found)
    return found


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch, audit: AsyncMock) -> KnowledgeBaseService:
    monkeypatch.setattr(collection_teardown_repo, "is_reserved", AsyncMock(return_value=False))
    monkeypatch.setattr(rag_document_repo, "holds_unfiled_outside", AsyncMock(return_value=False))
    monkeypatch.setattr(
        rag_document_repo, "table_holds_chunks_outside", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(knowledge_base_repo, "create", AsyncMock(side_effect=lambda _db, **kw: kw))
    monkeypatch.setattr(
        "app.services.collection_access.hold_name_within", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(embedding_providers, "require_served_at", AsyncMock())
    monkeypatch.setattr(f"{_AT}.validate_endpoint_url", AsyncMock(side_effect=lambda url: url))
    monkeypatch.setattr(KnowledgeBaseService, "_check_embedding_endpoint", AsyncMock())
    monkeypatch.setattr(KnowledgeBaseService, "_check_embedding_secret", AsyncMock())
    monkeypatch.setattr(KnowledgeBaseService, "_check_kept_secret", AsyncMock())
    return KnowledgeBaseService(MagicMock())


def _hold(monkeypatch: pytest.MonkeyPatch, service: KnowledgeBaseService, *rows: KnowledgeBase):
    monkeypatch.setattr(service, "get_for_write", AsyncMock(return_value=rows[0]))
    monkeypatch.setattr(
        knowledge_base_repo, "list_by_collection_name", AsyncMock(return_value=list(rows))
    )


def _field(refused: pytest.ExceptionInfo[BadRequestError]) -> str:
    return refused.value.details["fields"][0]["field"]


MOVES: list[tuple[str, Any, dict[str, Any]]] = [
    ("model", _custom, {"embedding_model": "m2"}),
    ("endpoint", _custom, {"embedding_endpoint_id": OTHER_ENDPOINT}),
    ("key", _keyed, {"embedding_secret_id": OTHER_SECRET}),
    ("base_url", _keyed, {"embedding_base_url": "https://eu.openrouter.ai/api/v1"}),
    ("provider", _keyed, {"embedding_provider": "openai", "embedding_secret_id": OTHER_SECRET}),
]


class TestAMoveNeedsProof:
    @pytest.mark.security
    @pytest.mark.parametrize(("kind", "make", "change"), MOVES, ids=[m[0] for m in MOVES])
    async def test_moving_a_base_without_a_test_or_override_is_refused_on_probe_token(
        self, service, monkeypatch, updated, identified, kind, make, change
    ) -> None:
        kb = make()
        _hold(monkeypatch, service, kb)

        with pytest.raises(BadRequestError) as refused:
            await service.update(kb.id, KnowledgeBaseUpdate(**change), ctx=_ctx())

        assert _field(refused) == "probe_token"
        updated.assert_not_awaited()

    async def test_a_rename_or_ingestion_change_needs_no_test(
        self, service, monkeypatch, updated, identified
    ) -> None:
        kb = _custom()
        _hold(monkeypatch, service, kb)

        await service.update(kb.id, KnowledgeBaseUpdate(name="Renamed"), ctx=_ctx())

        assert updated.await_args.kwargs["name"] == "Renamed"
        identified.assert_not_awaited()

    async def test_restating_what_the_base_already_has_is_not_a_move(
        self, service, monkeypatch, updated, identified, audit
    ) -> None:
        kb = _custom()
        _hold(monkeypatch, service, kb)

        await service.update(
            kb.id,
            KnowledgeBaseUpdate(embedding_model="m", embedding_endpoint_id=ENDPOINT),
            ctx=_ctx(),
        )

        identified.assert_not_awaited()
        audit.assert_not_awaited()

    @pytest.mark.security
    async def test_a_token_for_other_settings_is_refused(
        self, service, monkeypatch, updated, identified
    ) -> None:
        kb, ctx = _custom(), _ctx()
        _hold(monkeypatch, service, kb)
        token = _token(ctx, kb, model="tested-model")

        with pytest.raises(BadRequestError, match="changed since"):
            await service.update(
                kb.id,
                KnowledgeBaseUpdate(embedding_model="other-model", probe_token=token),
                ctx=ctx,
            )

        updated.assert_not_awaited()

    @pytest.mark.security
    async def test_a_key_rotated_after_the_test_voids_the_token(
        self, service, monkeypatch, updated, identified
    ) -> None:
        kb, ctx = _custom(), _ctx()
        _hold(monkeypatch, service, kb)
        token = _token(ctx, kb, model="m2")
        identified.return_value = _identity(generation=uuid.uuid4())

        with pytest.raises(BadRequestError) as refused:
            await service.update(
                kb.id, KnowledgeBaseUpdate(embedding_model="m2", probe_token=token), ctx=ctx
            )

        assert _field(refused) == "probe_token"
        updated.assert_not_awaited()

    @pytest.mark.security
    async def test_the_fingerprint_is_built_from_the_base_as_it_was_tested(
        self, service, monkeypatch, updated, identified
    ) -> None:
        """A token for a base at another model is not this base's."""
        kb, ctx = _custom(), _ctx()
        _hold(monkeypatch, service, kb)
        token = _token(ctx, _custom(id=kb.id, embedding_model="old"), model="m2")

        with pytest.raises(BadRequestError, match="changed since"):
            await service.update(
                kb.id, KnowledgeBaseUpdate(embedding_model="m2", probe_token=token), ctx=ctx
            )

    @pytest.mark.security
    async def test_another_members_token_is_refused(
        self, service, monkeypatch, updated, identified
    ) -> None:
        kb = _custom()
        _hold(monkeypatch, service, kb)
        token = _token(_ctx(), kb, model="m2")

        with pytest.raises(BadRequestError, match="someone else"):
            await service.update(
                kb.id, KnowledgeBaseUpdate(embedding_model="m2", probe_token=token), ctx=_ctx()
            )

    @pytest.mark.security
    async def test_a_token_for_a_creation_is_not_a_token_for_a_change(
        self, service, monkeypatch, updated, identified
    ) -> None:
        kb, ctx = _custom(), _ctx()
        _hold(monkeypatch, service, kb)
        token = _token(ctx, kb, model="m2", purpose=ProbePurpose.KB_CREATE)

        with pytest.raises(BadRequestError, match="expired or belongs"):
            await service.update(
                kb.id, KnowledgeBaseUpdate(embedding_model="m2", probe_token=token), ctx=ctx
            )


class TestAVerifiedMove:
    async def test_a_verified_move_saves_and_audits_the_changed_fields(
        self, service, monkeypatch, updated, identified, audit
    ) -> None:
        kb, ctx = _custom(), _ctx()
        _hold(monkeypatch, service, kb)
        token = _token(ctx, kb, model="m2")

        await service.update(
            kb.id, KnowledgeBaseUpdate(embedding_model="m2", probe_token=token), ctx=ctx
        )

        assert updated.await_args.kwargs["embedding_model"] == "m2"
        assert audit.await_args.kwargs["action"] == "knowledge_base.embedding_changed"
        assert audit.await_args.kwargs["details"] == {
            "fields": ["embedding_model"],
            "verified": True,
        }
        assert audit.await_args.kwargs["target_id"] == str(kb.id)

    async def test_a_verified_key_change_on_a_shared_collection_is_allowed(
        self, service, monkeypatch, updated, identified
    ) -> None:
        kb, sibling, ctx = _keyed(), _keyed(), _ctx()
        _hold(monkeypatch, service, kb, sibling)
        identity = _identity(provider="openrouter", connection_id=None, secret_id=OTHER_SECRET)
        identified.return_value = identity
        token = _token(ctx, kb, model=kb.embedding_model, identity=identity)

        await service.update(
            kb.id,
            KnowledgeBaseUpdate(embedding_secret_id=OTHER_SECRET, probe_token=token),
            ctx=ctx,
        )

        assert updated.await_args.kwargs["embedding_secret_id"] == OTHER_SECRET


class TestAnUnverifiedMove:
    @pytest.mark.security
    async def test_an_unverified_move_saves_and_audits_previous_and_new_settings_without_secrets(
        self, service, monkeypatch, updated, identified, audit
    ) -> None:
        kb = _keyed(embedding_base_url="https://or.example/v1?api-key=sk-leak")
        _hold(monkeypatch, service, kb)

        await service.update(
            kb.id,
            KnowledgeBaseUpdate(embedding_secret_id=OTHER_SECRET, unverified=True),
            ctx=_ctx(),
        )

        assert audit.await_args.kwargs["action"] == "knowledge_base.embedding_changed_unverified"
        details = audit.await_args.kwargs["details"]
        assert details["previous"]["secret_id"] == str(SECRET)
        assert details["new"]["secret_id"] == str(OTHER_SECRET)
        assert details["previous"]["base_url"] == "https://or.example/v1"
        assert "api-key" not in str(details)
        assert "sk-leak" not in str(details)
        identified.assert_not_awaited()

    @pytest.mark.security
    async def test_an_unverified_move_still_needs_the_key_to_be_viewable(
        self, service, monkeypatch, updated, identified
    ) -> None:
        kb = _keyed()
        _hold(monkeypatch, service, kb)
        monkeypatch.undo()  # the key check is the real one in this test
        monkeypatch.setattr(
            f"{_AT}.organization_secret_repo.get",
            AsyncMock(return_value=MagicMock(purpose="openrouter")),
        )
        monkeypatch.setattr(f"{_AT}.resolve_access", AsyncMock(return_value=False))
        monkeypatch.setattr(service, "get_for_write", AsyncMock(return_value=kb))
        monkeypatch.setattr(
            knowledge_base_repo, "list_by_collection_name", AsyncMock(return_value=[kb])
        )
        monkeypatch.setattr(embedding_providers, "require_served_at", AsyncMock())
        monkeypatch.setattr(knowledge_base_repo, "update", updated)

        with pytest.raises(BadRequestError, match="not in this organization's vault"):
            await service.update(
                kb.id,
                KnowledgeBaseUpdate(embedding_secret_id=OTHER_SECRET, unverified=True),
                ctx=_ctx(),
            )

        updated.assert_not_awaited()

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("field", "make", "sibling_overrides", "change"),
        [
            (
                "embedding_provider",
                _keyed,
                {},
                {"embedding_provider": "openai", "embedding_secret_id": OTHER_SECRET},
            ),
            (
                "embedding_endpoint_id",
                _custom,
                {},
                {"embedding_endpoint_id": OTHER_ENDPOINT},
            ),
            ("embedding_secret_id", _keyed, {}, {"embedding_secret_id": OTHER_SECRET}),
            ("embedding_model", _custom, {}, {"embedding_model": "m2"}),
            (
                "embedding_base_url",
                _keyed,
                {},
                {"embedding_base_url": "https://eu.openrouter.ai/api/v1"},
            ),
        ],
    )
    async def test_an_unverified_move_that_leaves_a_sibling_on_other_settings_is_refused(
        self, service, monkeypatch, updated, identified, field, make, sibling_overrides, change
    ) -> None:
        kb = make()
        sibling = make(**sibling_overrides)
        _hold(monkeypatch, service, kb, sibling)

        with pytest.raises(BadRequestError) as refused:
            await service.update(kb.id, KnowledgeBaseUpdate(unverified=True, **change), ctx=_ctx())

        assert _field(refused) == field
        assert "shares its embedding configuration" in refused.value.message
        updated.assert_not_awaited()

    async def test_an_unverified_move_of_an_unshared_collection_is_saved(
        self, service, monkeypatch, updated, identified
    ) -> None:
        kb = _custom()
        _hold(monkeypatch, service, kb)

        await service.update(
            kb.id, KnowledgeBaseUpdate(embedding_model="m2", unverified=True), ctx=_ctx()
        )

        assert updated.await_args.kwargs["embedding_model"] == "m2"


class TestAStaleKeyIsNotKept:
    """A base reached through a connection carries neither a key nor an address of its own."""

    async def test_a_move_to_openai_compatible_clears_both_fields(
        self, service, monkeypatch, updated, identified, audit
    ) -> None:
        kb = _keyed(embedding_base_url="https://or.example/v1")
        kb.embedding_model, kb.embedding_dim = "m", 1536
        _hold(monkeypatch, service, kb)

        await service.update(
            kb.id,
            KnowledgeBaseUpdate(
                embedding_provider="openai_compatible",
                embedding_endpoint_id=ENDPOINT,
                unverified=True,
            ),
            ctx=_ctx(),
        )

        kwargs = updated.await_args.kwargs
        assert kwargs["clear_embedding_secret"] is True
        assert (kwargs["embedding_base_url"], kwargs["set_embedding_base_url"]) == (None, True)
        new = audit.await_args.kwargs["details"]["new"]
        assert (new["secret_id"], new["base_url"]) == (None, None)

    async def test_a_stale_key_on_a_connection_base_is_not_a_difference_between_siblings(
        self, service, monkeypatch, updated, identified
    ) -> None:
        kb = _custom(embedding_model="old")
        sibling = _custom(embedding_model="m2", embedding_secret_id=SECRET)
        _hold(monkeypatch, service, kb, sibling)

        await service.update(
            kb.id, KnowledgeBaseUpdate(embedding_model="m2", unverified=True), ctx=_ctx()
        )

        updated.assert_awaited_once()

    @pytest.mark.security
    async def test_a_later_move_back_without_a_key_is_refused_on_embedding_secret_id(
        self, service, monkeypatch, updated, identified
    ) -> None:
        kb = _custom(embedding_model="text-embedding-3-small", embedding_dim=1536)
        _hold(monkeypatch, service, kb)
        monkeypatch.undo()
        monkeypatch.setattr(service, "get_for_write", AsyncMock(return_value=kb))
        monkeypatch.setattr(
            knowledge_base_repo, "list_by_collection_name", AsyncMock(return_value=[kb])
        )
        monkeypatch.setattr(knowledge_base_repo, "update", updated)

        with pytest.raises(BadRequestError) as refused:
            await service.update(
                kb.id,
                KnowledgeBaseUpdate(embedding_provider="openrouter", unverified=True),
                ctx=_ctx(),
            )

        assert _field(refused) == "embedding_secret_id"
        updated.assert_not_awaited()

    @pytest.mark.security
    async def test_a_stale_key_left_by_an_earlier_move_is_never_reused(
        self, service, monkeypatch, updated, identified
    ) -> None:
        """Rows moved before the key was cleared still hold it; a move back must name one."""
        kb = _custom(
            embedding_model="text-embedding-3-small", embedding_dim=1536, embedding_secret_id=SECRET
        )
        _hold(monkeypatch, service, kb)
        monkeypatch.undo()
        monkeypatch.setattr(service, "get_for_write", AsyncMock(return_value=kb))
        monkeypatch.setattr(
            knowledge_base_repo, "list_by_collection_name", AsyncMock(return_value=[kb])
        )
        monkeypatch.setattr(
            f"{_AT}.organization_secret_repo.get",
            AsyncMock(return_value=MagicMock(purpose="openrouter")),
        )
        monkeypatch.setattr(knowledge_base_repo, "update", updated)

        with pytest.raises(BadRequestError) as refused:
            await service.update(
                kb.id,
                KnowledgeBaseUpdate(embedding_provider="openrouter", unverified=True),
                ctx=_ctx(),
            )

        assert _field(refused) == "embedding_secret_id"
        updated.assert_not_awaited()

    async def test_a_stale_key_is_not_lent_to_a_new_address_either(
        self, service, monkeypatch, updated, identified
    ) -> None:
        """Naming an endpoint as well must end in the same refusal, not a check of the old key."""
        kb = _custom(
            embedding_model="text-embedding-3-small", embedding_dim=1536, embedding_secret_id=SECRET
        )
        _hold(monkeypatch, service, kb)
        monkeypatch.undo()
        monkeypatch.setattr(service, "get_for_write", AsyncMock(return_value=kb))
        monkeypatch.setattr(
            knowledge_base_repo, "list_by_collection_name", AsyncMock(return_value=[kb])
        )
        monkeypatch.setattr(embedding_providers, "require_served_at", AsyncMock())
        monkeypatch.setattr(f"{_AT}.validate_endpoint_url", AsyncMock(side_effect=lambda url: url))
        lent = AsyncMock()
        monkeypatch.setattr(service, "_check_embedding_secret", lent)
        monkeypatch.setattr(knowledge_base_repo, "update", updated)

        with pytest.raises(BadRequestError) as refused:
            await service.update(
                kb.id,
                KnowledgeBaseUpdate(
                    embedding_provider="openrouter",
                    embedding_base_url="https://eu.openrouter.ai/api/v1",
                    unverified=True,
                ),
                ctx=_ctx(),
            )

        assert _field(refused) == "embedding_secret_id"
        lent.assert_not_awaited()
        updated.assert_not_awaited()

    async def test_a_keyed_base_with_no_key_is_not_told_it_is_moving(
        self, service, monkeypatch, updated, identified
    ) -> None:
        kb = _keyed(embedding_secret_id=None)
        _hold(monkeypatch, service, kb)
        monkeypatch.undo()
        monkeypatch.setattr(service, "get_for_write", AsyncMock(return_value=kb))
        monkeypatch.setattr(
            knowledge_base_repo, "list_by_collection_name", AsyncMock(return_value=[kb])
        )
        monkeypatch.setattr(knowledge_base_repo, "update", updated)

        with pytest.raises(BadRequestError) as refused:
            await service.update(
                kb.id,
                KnowledgeBaseUpdate(embedding_provider="openrouter", unverified=True),
                ctx=_ctx(),
            )

        assert _field(refused) == "embedding_secret_id"
        assert "Moving to" not in refused.value.message


class TestCreatingOnACustomEndpoint:
    def _create(self, **overrides: Any) -> KnowledgeBaseCreate:
        return KnowledgeBaseCreate(
            **{
                "name": "Custom",
                "scope": "org",
                "collection_name": "fresh",
                "embedding_model": "corp-embed",
                "embedding_provider": "openai_compatible",
                "embedding_endpoint_id": ENDPOINT,
            }
            | overrides
        )

    def _holders(self, monkeypatch: pytest.MonkeyPatch, *rows: KnowledgeBase) -> None:
        monkeypatch.setattr(
            knowledge_base_repo, "list_by_collection_name", AsyncMock(return_value=list(rows))
        )

    def _creation_token(
        self, ctx: AuthContext, *, dim: int = 768, model: str = "corp-embed"
    ) -> str:
        binding = ProbeBinding.of(
            ProbePurpose.KB_CREATE,
            _identity(secret_id=None, key_generation=None),
            model=model,
            dim=dim,
            knowledge_bases=(),
        )
        return mint_probe_token(ctx, binding)[0]

    async def test_creating_a_custom_base_takes_its_width_from_the_token(
        self, service, monkeypatch, identified
    ) -> None:
        self._holders(monkeypatch)
        identified.return_value = _identity(secret_id=None, key_generation=None)
        ctx = _ctx()

        written = await service.create(self._create(probe_token=self._creation_token(ctx)), ctx=ctx)

        assert (written["embedding_model"], written["embedding_dim"]) == ("corp-embed", 768)
        assert written["embedding_provider"] == "openai_compatible"

    @pytest.mark.security
    async def test_creating_a_custom_base_without_a_token_is_refused_on_probe_token(
        self, service, monkeypatch, identified
    ) -> None:
        self._holders(monkeypatch)

        with pytest.raises(BadRequestError) as refused:
            await service.create(self._create(), ctx=_ctx())

        assert _field(refused) == "probe_token"
        knowledge_base_repo.create.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.security
    async def test_a_token_for_another_model_or_connection_does_not_create(
        self, service, monkeypatch, identified
    ) -> None:
        self._holders(monkeypatch)
        identified.return_value = _identity(secret_id=None, key_generation=None)
        ctx = _ctx()

        with pytest.raises(BadRequestError, match="changed since"):
            await service.create(
                self._create(probe_token=self._creation_token(ctx, model="tested")), ctx=ctx
            )

        knowledge_base_repo.create.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_a_model_is_still_required_before_any_token_is_read(
        self, service, monkeypatch, identified
    ) -> None:
        self._holders(monkeypatch)

        with pytest.raises(BadRequestError) as refused:
            await service.create(self._create(embedding_model=None), ctx=_ctx())

        assert _field(refused) == "embedding_model"

    async def test_joining_a_custom_collection_adopts_it_without_a_test(
        self, service, monkeypatch, identified
    ) -> None:
        self._holders(monkeypatch, _custom())

        written = await service.create(
            KnowledgeBaseCreate(name="Second", scope="org", collection_name="shared"), ctx=_ctx()
        )

        assert (written["embedding_dim"], written["embedding_endpoint_id"]) == (4, ENDPOINT)
        identified.assert_not_awaited()

    async def test_a_catalog_provider_needs_no_token(
        self, service, monkeypatch, identified
    ) -> None:
        self._holders(monkeypatch)

        written = await service.create(
            KnowledgeBaseCreate(
                name="Keyed",
                scope="org",
                collection_name="fresh",
                embedding_model="text-embedding-3-small",
                embedding_provider="openrouter",
                embedding_secret_id=SECRET,
            ),
            ctx=_ctx(),
        )

        assert written["embedding_dim"] == 1536
        identified.assert_not_awaited()
