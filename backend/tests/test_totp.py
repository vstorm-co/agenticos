"""Tests for the TOTP core: the code, its window, the URI, the recovery codes.

The RFC 6238 vectors pin the algorithm itself (SHA1, eight digits, the
`12345678901234567890` secret); the rest pins the behaviour around it - the
six-digit code the authenticator shows, the one-step window, and the
recovery codes that are the way back in when the authenticator is lost.
"""

import base64

import pytest

from app.core.totp import (
    _code,
    code_now,
    generate_recovery_codes,
    generate_secret,
    hash_recovery_code,
    provisioning_uri,
    verify_code,
)

# RFC 6238, Appendix B: the SHA1 secret, as base32, and the codes for two
# counters. The vectors use eight digits; the production code is six, so
# these go through the counter function directly.
_RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
_RFC_VECTORS = (
    (59, "94287082"),
    (1_111_111_109, "07081804"),
    (1_234_567_890, "89005924"),
    (2_000_000_000, "69279037"),
)


@pytest.mark.parametrize("moment,expected", _RFC_VECTORS)
def test_the_code_matches_the_rfc_vectors(moment: int, expected: str) -> None:
    assert _code(_RFC_SECRET, moment // 30, digits=8) == expected


@pytest.mark.security
def test_a_fresh_secret_is_160_bits_in_base32() -> None:
    secret = generate_secret()
    assert len(secret) == 32
    assert "=" not in secret
    assert len(base64.b32decode(secret + "=" * (-len(secret) % 8))) == 20


def test_the_code_shown_now_verifies() -> None:
    secret = generate_secret()
    moment = 1_000_000
    assert verify_code(secret, code_now(secret, at=moment), at=moment) == moment // 30


def test_the_previous_step_still_lands_but_two_back_does_not() -> None:
    secret = generate_secret()
    assert verify_code(secret, code_now(secret, at=1_000_000), at=1_000_030) == 1_000_000 // 30
    assert verify_code(secret, code_now(secret, at=1_000_000), at=1_000_060) is None


def test_the_next_step_lands_but_two_ahead_does_not() -> None:
    secret = generate_secret()
    assert verify_code(secret, code_now(secret, at=1_000_060), at=1_000_030) == 1_000_060 // 30
    assert verify_code(secret, code_now(secret, at=1_000_090), at=1_000_030) is None


def test_a_code_that_is_not_six_digits_cannot_match() -> None:
    secret = generate_secret()
    assert verify_code(secret, "12345") is None
    assert verify_code(secret, "1234567") is None
    assert verify_code(secret, "abcdef") is None
    assert verify_code(secret, "") is None


def test_whitespace_around_a_code_is_ignored() -> None:
    secret = generate_secret()
    moment = 1_000_000
    assert verify_code(secret, f"  {code_now(secret, at=moment)}  ", at=moment) == moment // 30


def test_the_provisioning_uri_names_the_defaults_explicitly() -> None:
    uri = provisioning_uri("JBSWY3DPEHPK3PXP", account_name="ada@example.com", issuer="AgenticOS")
    assert uri.startswith("otpauth://totp/AgenticOS:ada%40example.com?")
    assert "secret=JBSWY3DPEHPK3PXP" in uri
    assert "issuer=AgenticOS" in uri
    assert "algorithm=SHA1" in uri
    assert "digits=6" in uri
    assert "period=30" in uri


def test_recovery_codes_are_ten_unique_typed_groups() -> None:
    codes = generate_recovery_codes()
    assert len(codes) == 10
    assert len(set(codes)) == 10
    for code in codes:
        left, right = code.split("-")
        assert len(left) == 4 and len(right) == 4
        assert all(char not in "01IOl" for char in code.replace("-", ""))


def test_a_recovery_code_hash_is_deterministic_but_not_the_code() -> None:
    code = "ABCD-EFGH"
    assert hash_recovery_code(code) == hash_recovery_code(code)
    assert hash_recovery_code(code) != code
    assert hash_recovery_code("abcd-efgh") == hash_recovery_code(code)
    assert hash_recovery_code("ABCDEFGH") == hash_recovery_code(code)
    assert hash_recovery_code("ABCD EFGH") == hash_recovery_code(code)
    assert hash_recovery_code("WXYZ-EFGH") != hash_recovery_code(code)
