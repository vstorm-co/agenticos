"""The credentials the platform recognises in text, and the text it leaves alone."""

import pytest

from app.core.redaction import redact_secrets


def _redacted(text: str) -> str:
    verdict = redact_secrets(text)
    return verdict.replacement if verdict.action == "replace" else text  # type: ignore[return-value]


@pytest.mark.parametrize(
    ("text", "secret", "kept"),
    [
        (
            "postgres://app:s3cr3t-Pa55@db.internal:5432/app",
            "s3cr3t-Pa55",
            "[redacted:url_credentials]@db.internal:5432/app",
        ),
        ("https://ann:hunter2@example.com/feed", "hunter2", "https://[redacted:url_credentials]@"),
        (
            "https://api.example.com/v1/items?api_key=K3yV4lue9x&page=2",
            "K3yV4lue9x",
            "?[redacted:query_secret]&page=2",
        ),
        ("callback?access_token=ya29.a0AfH6SM&state=1", "ya29.a0AfH6SM", "&state=1"),
        ("user=ann&password=hunter2&remember=1", "hunter2", "user=ann&"),
        ("POST client_secret=Zq8rT0pX2vW", "Zq8rT0pX2vW", "POST "),
        ("Authorization: Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA", "[redacted:"),
        ("-H 'Authorization: Bearer 0a1b2c3d4e5f6a7b8c9d'", "0a1b2c3d4e5f6a7b8c9d", "-H '"),
        ("hf_" + "aB3dE5gH7jK9mN1pQ3sT5vX7zA9cE1gI3", "aB3dE5gH7jK9", "[redacted:"),
        ("gsk_" + "a1B2" * 13, "a1B2a1B2", "[redacted:"),
        ("xai-" + "Z9y8" * 20, "Z9y8Z9y8", "[redacted:"),
        ("glpat-" + "x1Y2z3W4v5U6t7S8r9Q0", "x1Y2z3W4v5U6", "[redacted:"),
        ("SG." + "a" * 22 + "." + "b" * 43, "aaaaaaaaaaaa", "[redacted:"),
        ("npm_" + "a1B2c3D4e5F6" * 3, "a1B2c3D4e5F6", "[redacted:"),
        ("bot 123456789:" + "AAH" + "x1" * 16, "AAHx1x1x1", "bot [redacted:"),
    ],
)
def test_a_credential_is_replaced_and_the_text_around_it_kept(
    text: str, secret: str, kept: str
) -> None:
    redacted = _redacted(text)

    assert secret not in redacted
    assert kept in redacted


@pytest.mark.parametrize(
    "text",
    [
        "https://example.com/search?page=2&sort=name",
        "mailto:ann@example.com?subject=Refund",
        "ssh://git@github.com/acme/app.git",
        "https://ann@example.com/feed",
        "Write to ann@example.com about the token.",
        "She was the bearer of bad news.",
        "Bearer responsibilities include the refund.",
        "Basic information about authorization and tokens.",
        "Set token= in the form, then press save.",
        "Order 123456789:shipped today",
    ],
)
def test_ordinary_text_is_left_alone(text: str) -> None:
    assert redact_secrets(text).action != "replace"


def test_a_vendor_key_in_a_query_keeps_its_own_label() -> None:
    redacted = _redacted("https://x.test/?api_key=sk-proj-" + "A1b2" * 10)

    assert redacted == "https://x.test/?api_key=[redacted:openai_key]"
