"""Which part of a provider's error body is logged: a code, and only a code."""

import pytest

from app.services.provider_error_code import error_code, safe_code

KEY = "sk-provider-secret"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ('{"error":{"code":"invalid_api_key","message":"bad"}}', "invalid_api_key"),
        ('{"error":{"code":400,"status":"INVALID_ARGUMENT"}}', "INVALID_ARGUMENT"),
        ('{"error":{"type":"invalid_request_error"}}', "invalid_request_error"),
        ('{"detail":{"status":"voice_not_found","message":"Say: hello"}}', "voice_not_found"),
        ('{"code":"InvalidParameter","message":"no"}', "InvalidParameter"),
    ],
    ids=["openai code", "gemini status", "openai type", "elevenlabs", "top-level code"],
)
def test_each_providers_code_is_read_from_its_own_place(body, code):
    assert error_code(body) == code


@pytest.mark.parametrize(
    "body",
    [
        f'{{"error":{{"code":"key {KEY} refused"}}}}',
        f"invalid key {KEY}",
        "[1, 2]",
        '{"error":"just a string"}',
        "{}",
    ],
    ids=["a sentence for a code", "not json", "not an object", "no container", "nothing"],
)
def test_anything_not_shaped_like_a_code_is_left_out(body):
    assert error_code(body) is None


def test_a_value_is_a_code_only_when_it_is_a_short_token():
    assert safe_code("InputTextSensitiveContentDetected") == "InputTextSensitiveContentDetected"
    assert safe_code(f"refused {KEY}") is None
    assert safe_code(None) is None
    assert safe_code("x" * 65) is None
