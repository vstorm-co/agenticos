"""`http_credential`: a token sealed with the only origins it may be sent to.

What is defended is the origin match itself - the one thing standing between an
editor who can type a URL and the organization's credential - so the cases are
the spellings an origin can be written in and the ones that must not match.
"""

import uuid

import pytest
from pydantic import ValidationError

from app.core.secret_kinds import (
    HttpCredentialSecret,
    SecretKind,
    describe_kinds,
    seal_secret,
    unseal_secret,
)
from app.core.vault import VaultScope

pytestmark = pytest.mark.security

_TOKEN = "tok-abcdef-123456"


def _secret(*origins: str) -> HttpCredentialSecret:
    return HttpCredentialSecret(token=_TOKEN, origins=origins)


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("https://api.example.com", "https://api.example.com"),
        ("https://API.Example.com/", "https://api.example.com"),
        ("https://api.example.com:443", "https://api.example.com"),
        ("http://api.example.com:80", "http://api.example.com"),
        ("https://api.example.com:8443", "https://api.example.com:8443"),
        ("https://[2001:db8::1]:8443", "https://[2001:db8::1]:8443"),
    ],
)
def test_an_origin_is_stored_in_one_spelling(given: str, stored: str):
    assert _secret(given).origins == (stored,)


@pytest.mark.parametrize(
    "given",
    [
        "api.example.com",
        "ftp://api.example.com",
        "https://api.example.com/v1",
        "https://api.example.com?x=1",
        "https://user:pw@api.example.com",
        "https://api.example.com:99999",
        "https://",
    ],
    ids=["no-scheme", "not-http", "path", "query", "userinfo", "bad-port", "no-host"],
)
def test_anything_but_a_bare_origin_is_refused(given: str):
    with pytest.raises(ValidationError, match="not an origin"):
        _secret(given)


def test_at_least_one_origin_is_required():
    with pytest.raises(ValidationError):
        HttpCredentialSecret(token=_TOKEN, origins=())


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://api.example.com/v1/items?page=2", True),
        ("https://api.example.com:443/v1", True),
        ("https://API.EXAMPLE.COM/v1", True),
        ("http://api.example.com/v1", False),
        ("https://api.example.com:8443/v1", False),
        ("https://evil.api.example.com/v1", False),
        ("https://api.example.com.evil.net/v1", False),
        ("https://api.example.com@evil.net/v1", False),
        ("not a url", False),
    ],
)
def test_a_request_may_carry_the_credential_only_to_an_allowed_origin(url: str, allowed: bool):
    assert _secret("https://api.example.com").allows(url) is allowed


def test_the_hint_is_the_tokens_last_four_characters():
    assert _secret("https://api.example.com").hint == "3456"


def test_it_is_offered_as_a_kind_a_person_can_store():
    kinds = {info.kind for info in describe_kinds()}
    assert SecretKind.HTTP_CREDENTIAL in kinds


def test_it_round_trips_through_the_vault():
    scope = VaultScope.organization(uuid.uuid4())
    sealed = seal_secret(_secret("https://api.example.com"), scope=scope)
    opened = unseal_secret(
        sealed.ciphertext,
        kind=SecretKind.HTTP_CREDENTIAL,
        scope=scope,
        key_version=sealed.key_version,
    )
    assert isinstance(opened, HttpCredentialSecret)
    assert opened.origins == ("https://api.example.com",)
    assert _TOKEN not in sealed.ciphertext
