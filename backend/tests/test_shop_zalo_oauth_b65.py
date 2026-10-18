"""B65 — Shop Zalo OAuth state + PKCE."""

from __future__ import annotations

import pytest

from app.core.exceptions import BadRequestError
from app.services.shop_zalo_oauth_crypto import (
    sign_shop_zalo_oauth_state,
    verify_shop_zalo_oauth_state,
)
from app.services.shop_zalo_oauth_pkce import generate_pkce_pair


def test_pkce_pair_length() -> None:
    verifier, challenge = generate_pkce_pair()
    assert len(verifier) >= 40
    assert len(challenge) >= 40
    assert verifier != challenge


def test_oauth_state_roundtrip() -> None:
    payload = {"minerp_tenant_id": "00000000-0000-0000-0000-000000000001", "nonce": "x"}
    token = sign_shop_zalo_oauth_state(payload)
    out = verify_shop_zalo_oauth_state(token)
    assert out["minerp_tenant_id"] == payload["minerp_tenant_id"]


def test_oauth_state_rejects_garbage() -> None:
    with pytest.raises(BadRequestError, match="Invalid OAuth state"):
        verify_shop_zalo_oauth_state("not-a-valid-state")
