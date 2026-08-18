"""Tests for per-collection reranker resolution.

The mirror image of embedding resolution, and its one deliberate difference
carries the weight here: where a missing embedding key falls back to the
deployment's, a missing rerank key turns reranking *off*. So every path but a
usable organization secret resolves to `None`, and the three that mean a real
misconfiguration say so in a log line while the normal off state stays silent.
"""

from __future__ import annotations

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret
from app.core.vault import VaultScope
from app.services.rerank_resolution import (
    RerankKeySource,
    ResolvedReranker,
    reranker_for_collection,
)

pytestmark = pytest.mark.anyio

_MODULE = "app.services.rerank_resolution"
_ORG = uuid.uuid4()


def _kb(
    *,
    model: str | None = "rerank-v3.5",
    secret_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = _ORG,
):
    return MagicMock(
        collection_name="handbook",
        rerank_model=model,
        rerank_secret_id=secret_id,
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
        purpose="cohere",
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
        return await reranker_for_collection("handbook"), secrets


class TestResolution:
    async def test_a_collection_nobody_claims_has_no_reranker(self):
        resolved, secrets = await _resolve(None)
        assert resolved is None
        secrets.get.assert_not_called()

    async def test_a_collection_that_named_no_reranker_has_none(self):
        """The normal off state - the vault is never consulted."""
        resolved, secrets = await _resolve(_kb(model=None, secret_id=None))
        assert resolved is None
        secrets.get.assert_not_called()

    async def test_a_model_with_no_key_is_off(self):
        resolved, secrets = await _resolve(_kb(model="rerank-v3.5", secret_id=None))
        assert resolved is None
        secrets.get.assert_not_called()

    async def test_a_configured_collection_unseals_and_returns_its_reranker(self):
        resolved, _ = await _resolve(_kb(secret_id=uuid.uuid4()), _sealed_key_row("co-org-own-key"))
        assert resolved == ResolvedReranker(model="rerank-v3.5", api_key="co-org-own-key")

    async def test_a_personal_collection_never_looks_in_a_vault(self):
        """No organization, no vault scope to open an envelope with."""
        resolved, secrets = await _resolve(_kb(secret_id=uuid.uuid4(), organization_id=None))
        assert resolved is None
        secrets.get.assert_not_called()

    async def test_a_repr_never_carries_the_key(self):
        resolved = ResolvedReranker(model="rerank-v3.5", api_key="co-secret")
        assert "co-secret" not in repr(resolved)
        assert "rerank-v3.5" in repr(resolved)


class TestDegradationTurnsRerankingOff:
    """A chosen key that is gone drops reranking to off, with a line saying why.

    Never a 500: whose key pays for reranking must not decide whether a search
    answers at all.
    """

    async def test_a_deleted_secret_turns_reranking_off_with_a_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger=_MODULE):
            resolved, _ = await _resolve(_kb(secret_id=uuid.uuid4()), None)
        assert resolved is None
        assert "rerank_secret_missing" in caplog.text

    async def test_an_unopenable_ciphertext_turns_reranking_off(self, caplog):
        broken = MagicMock(
            sealed_secret="not-a-ciphertext", kind=SecretKind.API_KEY.value, key_version=1
        )
        with caplog.at_level(logging.WARNING, logger=_MODULE):
            resolved, _ = await _resolve(_kb(secret_id=uuid.uuid4()), broken)
        assert resolved is None
        assert "rerank_secret_unusable" in caplog.text

    async def test_a_secret_of_the_wrong_kind_turns_reranking_off(self, caplog):
        row = _sealed_key_row("co-org")
        with (
            patch(f"{_MODULE}.unseal_secret", return_value=MagicMock(spec=[])),
            caplog.at_level(logging.WARNING, logger=_MODULE),
        ):
            resolved, _ = await _resolve(_kb(secret_id=uuid.uuid4()), row)
        assert resolved is None
        assert "rerank_secret_wrong_kind" in caplog.text

    async def test_the_normal_off_state_logs_nothing(self, caplog):
        with caplog.at_level(logging.WARNING, logger=_MODULE):
            await _resolve(_kb(model=None, secret_id=None))
        assert caplog.text == ""


class TestWhichReasonsAreDegraded:
    def test_only_a_key_asked_for_and_not_given_is_degraded(self):
        degraded = {source for source in RerankKeySource if source.is_degraded}
        assert degraded == {
            RerankKeySource.SECRET_MISSING,
            RerankKeySource.SECRET_UNUSABLE,
            RerankKeySource.SECRET_WRONG_KIND,
        }
