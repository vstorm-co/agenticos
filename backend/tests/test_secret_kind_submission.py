"""Submitted vault values fail safely without echoing the credential."""

import json

import pytest

from app.core.exceptions import BadRequestError
from app.core.secret_kinds import ApiKeySecret, SecretKind, parse_storable_secret

pytestmark = pytest.mark.security

PRIVATE_VALUE = "synthetic-vault-value-must-not-escape"


@pytest.mark.parametrize(
    ("kind", "value", "message"),
    [
        ("unknown-kind", PRIVATE_VALUE, "not valid"),
        ("none", PRIVATE_VALUE, "not valid"),
        ("google_oauth_app", '{"private": "' + PRIVATE_VALUE, "not valid"),
        (
            "google_oauth_app",
            json.dumps({"kind": "api_key", "api_key": PRIVATE_VALUE}),
            "does not match",
        ),
    ],
)
def test_invalid_submissions_report_only_the_requested_kind(kind, value, message):
    with pytest.raises(BadRequestError, match=message) as caught:
        parse_storable_secret(kind, value)

    assert caught.value.details == {"kind": kind}
    assert PRIVATE_VALUE not in str(caught.value)
    assert PRIVATE_VALUE not in repr(caught.value)
    assert PRIVATE_VALUE not in json.dumps(caught.value.details)


def test_a_plain_api_key_is_preserved_as_the_requested_typed_secret():
    result = parse_storable_secret("api_key", PRIVATE_VALUE)
    assert isinstance(result, ApiKeySecret)
    assert result.kind is SecretKind.API_KEY
    assert result.api_key.get_secret_value() == PRIVATE_VALUE
