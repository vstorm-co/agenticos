"""The proof a passing embedding test leaves: what it is bound to, and who may spend it."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import jwt
import pytest

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.security import create_embedding_probe_token, verify_special_token
from app.services.embedding_probe_token import (
    PROBE_TOKEN_TTL,
    ProbeBinding,
    ProbePurpose,
    mint_probe_token,
    read_probe_token,
)
from app.services.embedding_resolution import EmbeddingKeySource, TargetIdentity

_ORG = uuid.uuid4()
_KB = uuid.uuid4()


def _ctx(*, user_id: uuid.UUID | None = None, organization_id: uuid.UUID = _ORG) -> AuthContext:
    return AuthContext(
        user_id=user_id or uuid.uuid4(),
        organization_id=organization_id,
        role=OrgRoleName.OWNER.value,
    )


def _identity() -> TargetIdentity:
    return TargetIdentity(
        provider="openai_compatible",
        connection_id=uuid.uuid4(),
        base_url="https://gateway.example/v1",
        secret_id=uuid.uuid4(),
        key_generation=uuid.uuid4(),
        key_organization_id=_ORG,
        key_source=EmbeddingKeySource.CONNECTION,
    )


def _kb(kb_id: uuid.UUID = _KB, model: str = "m", dim: int = 8) -> MagicMock:
    return MagicMock(id=kb_id, embedding_model=model, embedding_dim=dim)


def _binding(identity: TargetIdentity | None = None) -> ProbeBinding:
    return ProbeBinding.of(
        ProbePurpose.KB_CHANGE,
        identity or _identity(),
        model="m",
        dim=8,
        knowledge_bases=[_kb()],
    )


def test_a_probe_token_cannot_be_used_as_an_access_token() -> None:
    token, _ = mint_probe_token(_ctx(), _binding())

    assert verify_special_token(token, "access") is None


def test_the_token_carries_no_url_or_key_id_in_clear() -> None:
    token, expires_at = mint_probe_token(_ctx(), _binding())

    claims = jwt.decode(token, options={"verify_signature": False})

    assert set(claims) == {"exp", "sub", "type", "aud", "org", "fp", "dim"}
    assert expires_at > datetime.now(UTC) + PROBE_TOKEN_TTL - timedelta(seconds=5)


def test_a_token_reads_back_as_its_fingerprint_and_width() -> None:
    ctx = _ctx()
    binding = _binding()
    token, _ = mint_probe_token(ctx, binding)

    claims = read_probe_token(token, ctx=ctx, purpose=ProbePurpose.KB_CHANGE)

    assert claims.fingerprint == binding.fingerprint()
    assert claims.dim == 8
    claims.require_match(binding)


@pytest.mark.security
def test_a_missing_token_is_refused_on_probe_token() -> None:
    with pytest.raises(BadRequestError) as refused:
        read_probe_token(None, ctx=_ctx(), purpose=ProbePurpose.KB_CHANGE)

    assert refused.value.details["fields"][0]["field"] == "probe_token"
    assert "Test these settings" in refused.value.message


@pytest.mark.security
def test_a_token_for_one_purpose_is_refused_for_another() -> None:
    ctx = _ctx()
    token, _ = mint_probe_token(ctx, _binding())

    with pytest.raises(BadRequestError) as refused:
        read_probe_token(token, ctx=ctx, purpose=ProbePurpose.CONNECTION_CHANGE)

    assert refused.value.details["fields"][0]["field"] == "probe_token"


@pytest.mark.security
def test_an_expired_token_is_refused() -> None:
    ctx = _ctx()
    token = create_embedding_probe_token(
        subject=ctx.subject_id,
        organization_id=ctx.organization_id,
        purpose=ProbePurpose.KB_CHANGE.value,
        fingerprint=_binding().fingerprint(),
        dim=8,
        expires_in=timedelta(seconds=-1),
    )

    with pytest.raises(BadRequestError, match="expired"):
        read_probe_token(token, ctx=ctx, purpose=ProbePurpose.KB_CHANGE)


@pytest.mark.security
def test_another_users_token_is_refused() -> None:
    token, _ = mint_probe_token(_ctx(), _binding())

    with pytest.raises(BadRequestError, match="someone else"):
        read_probe_token(token, ctx=_ctx(), purpose=ProbePurpose.KB_CHANGE)


@pytest.mark.security
def test_another_organizations_token_is_refused() -> None:
    ctx = _ctx()
    token, _ = mint_probe_token(ctx, _binding())
    elsewhere = _ctx(user_id=ctx.user_id, organization_id=uuid.uuid4())

    with pytest.raises(BadRequestError, match="someone else"):
        read_probe_token(token, ctx=elsewhere, purpose=ProbePurpose.KB_CHANGE)


@pytest.mark.security
def test_a_forged_token_is_refused() -> None:
    ctx = _ctx()
    forged = jwt.encode(
        {"sub": str(ctx.subject_id), "type": "embedding_probe", "aud": "kb_change"},
        "not-the-secret-" * 3,
        algorithm=settings.ALGORITHM,
    )

    with pytest.raises(BadRequestError, match="expired"):
        read_probe_token(forged, ctx=ctx, purpose=ProbePurpose.KB_CHANGE)


_BASE = _binding()


@pytest.mark.security
@pytest.mark.parametrize(
    "changed",
    [
        replace(_BASE, purpose=ProbePurpose.KB_CREATE),
        replace(_BASE, provider="ollama"),
        replace(_BASE, connection_id=uuid.uuid4()),
        replace(_BASE, connection_id=None),
        replace(_BASE, base_url="https://other.example/v1"),
        replace(_BASE, secret_id=uuid.uuid4()),
        replace(_BASE, secret_id=None),
        replace(_BASE, key_generation=uuid.uuid4()),
        replace(_BASE, key_generation=None),
        replace(_BASE, model="other"),
        replace(_BASE, model=None),
        replace(_BASE, dim=9),
        replace(_BASE, dim=None),
        replace(_BASE, knowledge_bases=()),
        replace(_BASE, knowledge_bases=((_KB, "other", 8),)),
        replace(_BASE, knowledge_bases=((_KB, "m", 9),)),
        replace(_BASE, knowledge_bases=((uuid.uuid4(), "m", 8),)),
    ],
)
def test_any_bound_value_changing_changes_the_fingerprint(changed: ProbeBinding) -> None:
    assert changed.fingerprint() != _BASE.fingerprint()

    ctx = _ctx()
    token, _ = mint_probe_token(ctx, _BASE)
    claims = read_probe_token(token, ctx=ctx, purpose=ProbePurpose.KB_CHANGE)
    with pytest.raises(BadRequestError, match="changed since"):
        claims.require_match(changed)


def test_the_order_of_knowledge_bases_does_not_change_the_fingerprint() -> None:
    identity = _identity()
    first, second = _kb(uuid.uuid4()), _kb(uuid.uuid4(), model="n")

    one = ProbeBinding.of(
        ProbePurpose.CONNECTION_CHANGE,
        identity,
        model=None,
        dim=None,
        knowledge_bases=[first, second],
    )
    other = ProbeBinding.of(
        ProbePurpose.CONNECTION_CHANGE,
        identity,
        model=None,
        dim=None,
        knowledge_bases=[second, first],
    )

    assert one.fingerprint() == other.fingerprint()


def test_a_caller_with_no_organization_reads_back_its_own_token() -> None:
    ctx = MagicMock(subject_id=uuid.uuid4(), organization_id=None)
    token, _ = mint_probe_token(ctx, _binding())

    claims = read_probe_token(token, ctx=ctx, purpose=ProbePurpose.KB_CHANGE)

    assert claims.dim == 8


def test_the_width_is_an_int_whatever_the_claim_was_encoded_as() -> None:
    ctx = _ctx()
    token = create_embedding_probe_token(
        subject=ctx.subject_id,
        organization_id=ctx.organization_id,
        purpose=ProbePurpose.KB_CHANGE.value,
        fingerprint="f" * 64,
        dim="768",  # type: ignore[arg-type]
        expires_in=timedelta(minutes=1),
    )

    claims = read_probe_token(token, ctx=ctx, purpose=ProbePurpose.KB_CHANGE)

    assert claims.dim == 768
    assert isinstance(claims.dim, int)
