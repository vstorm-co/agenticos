"""Derived state is bounded, cryptographically scoped and permanently classified."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.browser_continuation import BrowserContinuationReason, BrowserContinuationRefused
from app.core.browser_session import (
    CredentialGeneration,
    CredentialSessionProvenance,
    ProtectedCookie,
    ProtectedSignIn,
    bounded_cookies,
    credential_generations,
    protected_cookie_params,
    request_at_origin,
)
from app.core.secret_scopes import browser_sign_in_scope
from app.core.vault import VaultScope, rewrap, seal, unseal

pytestmark = pytest.mark.security
ORIGIN = "https://portal.example.com"
PRIVATE = "synthetic-private-cookie-which-must-stay-hidden"


def raw_cookie(**overrides):
    return {
        "name": "sid",
        "value": PRIVATE,
        "domain": "portal.example.com",
        "path": "/",
        "secure": True,
        "httpOnly": True,
        "sameSite": "Lax",
        "session": False,
        "expires": 3000.0,
        **overrides,
    }


def provenance(**overrides):
    now = datetime.now(UTC)
    secret, generation = uuid4(), uuid4()
    return CredentialSessionProvenance(
        **{
            "organization_id": uuid4(),
            "user_id": uuid4(),
            "agent_id": uuid4(),
            "continuation_id": uuid4(),
            "source_submission_id": uuid4(),
            "source_fill_id": uuid4(),
            "secret_id": secret,
            "authorization_generation": generation,
            "origin": ORIGIN,
            "created_at": now,
            "expires_at": now + timedelta(days=7),
            "credential_generations": (
                CredentialGeneration(secret_id=secret, authorization_generation=generation),
            ),
            **overrides,
        }
    )


def test_only_exact_secure_host_cookies_are_eligible_and_names_paths_values_are_masked():
    state = bounded_cookies(
        ORIGIN,
        [
            raw_cookie(),
            raw_cookie(domain=".portal.example.com"),
            raw_cookie(domain="example.com"),
            raw_cookie(domain="child.portal.example.com"),
            raw_cookie(secure=False),
            raw_cookie(partitionKey={"topLevelSite": ORIGIN}),
            raw_cookie(partitionKeyOpaque=True),
            raw_cookie(expires=10),
        ],
        now=20,
    )
    assert len(state) == 1 and state[0].value.get_secret_value() == PRIVATE
    assert PRIVATE not in repr(state)
    private_name = ProtectedCookie(
        name=PRIVATE, value=PRIVATE, path="/" + PRIVATE, http_only=True, same_site=None
    )
    assert PRIVATE not in repr(private_name)


@pytest.mark.parametrize("cookies", [None, {}, (), [None], [raw_cookie()] * 301])
def test_malformed_or_unbounded_native_stores_are_refused_without_reflecting_content(cookies):
    with pytest.raises(BrowserContinuationRefused) as caught:
        bounded_cookies(ORIGIN, cookies, now=20)
    assert caught.value.reason == BrowserContinuationReason.STATE_REFUSED
    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize(
    "change",
    [
        {"name": ""},
        {"name": "x" * 257},
        {"value": "x" * 4097},
        {"path": "relative"},
        {"name": "bad\nname"},
        {"value": "bad\x7fvalue"},
        {"path": "/bad\rpath"},
        {"httpOnly": "true"},
        {"sameSite": "unexpected"},
        {"session": None},
        {"session": "true"},
        {"expires": None},
        {"expires": float("inf")},
        {"expires": -1},
        {"value": {}},
    ],
)
def test_cookie_attribute_validation_is_closed_and_value_free(change):
    with pytest.raises(BrowserContinuationRefused) as caught:
        bounded_cookies(ORIGIN, [raw_cookie(**change)], now=20)
    assert caught.value.reason == BrowserContinuationReason.STATE_REFUSED


@pytest.mark.parametrize(
    "cookies",
    [
        [raw_cookie(name=f"n{i}") for i in range(101)],
        [raw_cookie(name=f"n{i}", value="x" * 4096) for i in range(20)],
    ],
)
def test_total_cookie_count_and_encoded_bytes_are_capped(cookies):
    with pytest.raises(BrowserContinuationRefused, match="continuation refused"):
        bounded_cookies(ORIGIN, cookies, now=20)


def test_missing_eligible_cookie_does_not_claim_authentication():
    with pytest.raises(BrowserContinuationRefused) as caught:
        bounded_cookies(ORIGIN, [], now=20)
    assert caught.value.reason == BrowserContinuationReason.COOKIE_MISSING


@pytest.mark.parametrize(
    "change", [{"value": "x" * 4097}, {"path": "relative"}, {"http_only": "true"}]
)
def test_native_builder_revalidates_in_process_state_before_emitting_cookie_parameters(change):
    from pydantic import SecretStr

    cookie = bounded_cookies(ORIGIN, [raw_cookie()], now=20)[0]
    changed = {
        key: SecretStr(value) if key in ("value", "path") else value
        for key, value in change.items()
    }
    malformed = ProtectedSignIn.model_construct(
        provenance=provenance(), cookies=(cookie.model_copy(update=changed),)
    )
    with pytest.raises(BrowserContinuationRefused) as refused:
        protected_cookie_params(malformed)
    assert refused.value.reason == BrowserContinuationReason.STATE_REFUSED


def test_native_builder_refuses_an_oversized_restored_wire_projection():
    cookie = ProtectedCookie(name="sid", value="x" * 4096, path="/", http_only=True, same_site=None)
    restored = ProtectedSignIn(provenance=provenance(), cookies=(cookie,) * 20)
    with pytest.raises(BrowserContinuationRefused):
        protected_cookie_params(restored)


def test_restore_projects_url_host_only_scope_and_does_not_extend_cookie_expiry():
    p = provenance()
    cookies = bounded_cookies(
        ORIGIN,
        [raw_cookie(expires=p.expires_at.timestamp() + 100), raw_cookie(session=True)],
        now=20,
    )
    state = ProtectedSignIn(provenance=p, cookies=cookies)
    params = protected_cookie_params(state)
    assert all(
        item["url"] == ORIGIN + "/" and "domain" not in item and item["secure"] is True
        for item in params
    )
    assert params[0]["expires"] == p.expires_at.timestamp() and "expires" not in params[1]
    assert params[0]["value"] == PRIVATE
    assert ProtectedSignIn.model_validate_json(state.model_dump_json()) == state
    no_site = cookies[0].model_copy(update={"same_site": None})
    assert (
        "sameSite"
        not in protected_cookie_params(state.model_copy(update={"cookies": (no_site,)}))[0]
    )


def test_sealed_payload_binds_org_and_person_and_rewrapping_keeps_provenance(monkeypatch):
    from app.core.config import settings
    from app.core.exceptions import BadRequestError

    monkeypatch.setattr(
        settings, "VAULT_MASTER_KEYS", {1: "old-synthetic-master", 2: "new-synthetic-master"}
    )
    p = provenance()
    state = ProtectedSignIn(provenance=p, cookies=bounded_cookies(ORIGIN, [raw_cookie()], now=20))
    scope = browser_sign_in_scope(
        organization_id=p.organization_id, user_id=p.user_id, protection_kind="credential"
    )
    encrypted = seal(state.model_dump_json(), scope=scope, key_version=1)
    assert PRIVATE not in encrypted.ciphertext
    rotated = rewrap(encrypted.ciphertext, scope=scope, from_version=1, to_version=2)
    assert PRIVATE not in rotated and rotated != encrypted.ciphertext
    assert ProtectedSignIn.model_validate_json(unseal(rotated, scope=scope, key_version=2)) == state
    assert (
        ProtectedSignIn.model_validate_json(
            unseal(encrypted.ciphertext, scope=scope, key_version=encrypted.key_version)
        )
        == state
    )
    for other in (
        VaultScope.user(p.user_id),
        VaultScope.browser_member(uuid4(), p.user_id),
        VaultScope.browser_member(p.organization_id, uuid4()),
    ):
        with pytest.raises(BadRequestError):
            unseal(encrypted.ciphertext, scope=other, key_version=encrypted.key_version)
    assert browser_sign_in_scope(
        organization_id=p.organization_id, user_id=p.user_id, protection_kind="manual"
    ) == VaultScope.user(p.user_id)
    with pytest.raises(BadRequestError):
        browser_sign_in_scope(
            organization_id=p.organization_id, user_id=p.user_id, protection_kind="unknown"
        )


@pytest.mark.parametrize(
    "url,expected",
    [
        (ORIGIN + "/account?untrusted=private", True),
        (ORIGIN + ":443/path", True),
        ("https://portal.example.com:8443/path", False),
        ("http://portal.example.com", False),
        ("https://child.portal.example.com", False),
        ("https://user:password@portal.example.com", False),
        ("https://portal.example.com:bad/path", False),
        ("https://[invalid", False),
        ("data:text/html,private", False),
    ],
)
def test_derived_context_requests_keep_exact_origin_even_on_redirects(url, expected):
    assert request_at_origin(url, ORIGIN) is expected


def test_all_contributors_are_retained_and_a_rotated_duplicate_cannot_be_silently_overwritten():
    first = CredentialGeneration(secret_id=uuid4(), authorization_generation=uuid4())
    second = CredentialGeneration(secret_id=uuid4(), authorization_generation=uuid4())
    assert set(credential_generations([first, second, first])) == {first, second}
    for invalid in (
        [],
        [first, first.model_copy(update={"authorization_generation": uuid4()})],
        [
            CredentialGeneration(secret_id=uuid4(), authorization_generation=uuid4())
            for _ in range(51)
        ],
    ):
        with pytest.raises(BrowserContinuationRefused):
            credential_generations(invalid)


@pytest.mark.parametrize(
    "change",
    [
        {"expires_at": datetime.now(UTC) + timedelta(days=8)},
        {"expires_at": datetime.now(UTC) - timedelta(days=1)},
        {"created_at": datetime.now(UTC).replace(tzinfo=None)},
        {"origin": "https://portal.example.com/path"},
        {"output_protected": False},
        {
            "credential_generations": (
                CredentialGeneration(secret_id=uuid4(), authorization_generation=uuid4()),
            )
        },
    ],
)
def test_provenance_lifetime_origin_and_protection_cannot_be_broadened(change):
    with pytest.raises((ValidationError, BrowserContinuationRefused)):
        provenance(**change)
