"""Raw-byte authentication accepts the supported wire formats and refuses tampering."""

import base64
import hashlib
import hmac
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr, ValidationError

from app.core.exceptions import BadRequestError
from app.schemas.event_source import EventSourceCreate, SourceAuth, SourceCredentials
from app.services.event_source_auth import standard_key, verify_source
from app.services.event_sources import prepare_credentials

pytestmark = pytest.mark.security
_KEY = "example-signing-key"
_BODY = b'{"webhookTimestamp":1700000000000,"issue":{"title":"Hello"}}'
_NOW = 1700000000
_URL = "https://example.com/api/v1/webhooks/sources/source-id"


def _hmac(value: bytes, key: bytes = _KEY.encode()) -> bytes:
    return hmac.new(key, value, hashlib.sha256).digest()


@pytest.mark.parametrize("encoding", ["hex", "base64", "base64url"])
def test_custom_hmac_checks_raw_bytes_with_configured_header_prefix_and_encoding(encoding):
    digest = _hmac(_BODY)
    encoded = (
        digest.hex()
        if encoding == "hex"
        else (
            base64.b64encode(digest).decode()
            if encoding == "base64"
            else base64.urlsafe_b64encode(digest).decode().rstrip("=")
        )
    )
    auth = SourceAuth(
        header_name="X-Provider-Signature", signature_prefix="sig=", encoding=encoding
    )
    credentials = SourceCredentials(secret=SecretStr(_KEY))
    headers = {"x-provider-signature": "sig=" + encoded}
    assert verify_source("webhook", auth, credentials, body=_BODY, headers=headers, url=_URL)
    assert not verify_source(
        "webhook", auth, credentials, body=_BODY + b" ", headers=headers, url=_URL
    )
    assert not verify_source("webhook", auth, credentials, body=_BODY, headers={}, url=_URL)


@pytest.mark.parametrize(
    "stamp", [str(_NOW), str(_NOW - 300), str(_NOW + 300), str(_NOW - 301), "no-time", "1" * 20]
)
def test_legacy_hmac_timestamp_is_signed_and_bounded(stamp):
    auth = SourceAuth(legacy=True)
    headers = {
        "x-signature-timestamp": stamp,
        "x-signature-256": "sha256=" + _hmac(stamp.encode() + b"." + _BODY).hex(),
    }
    accepted = stamp in {str(_NOW), str(_NOW - 300), str(_NOW + 300)}
    assert (
        verify_source(
            "webhook",
            auth,
            SourceCredentials(secret=SecretStr(_KEY)),
            body=_BODY,
            headers=headers,
            url=_URL,
            now=_NOW,
        )
        is accepted
    )


def test_legacy_hmac_still_accepts_body_only_when_no_timestamp_was_supplied():
    assert verify_source(
        "webhook",
        SourceAuth(legacy=True),
        SourceCredentials(secret=SecretStr(_KEY)),
        body=_BODY,
        headers={"x-signature-256": "sha256=" + _hmac(_BODY).hex()},
        url=_URL,
        now=_NOW,
    )


@pytest.mark.parametrize("method", ["basic", "api_key"])
def test_static_auth_credentials_are_compared_and_credential_replacement_invalidates_old_requests(
    method,
):
    if method == "basic":
        auth = SourceAuth(method="basic")
        credentials = SourceCredentials(
            username=SecretStr("sender"), password=SecretStr("password")
        )
        replaced = SourceCredentials(username=SecretStr("sender"), password=SecretStr("changed"))
        headers = {"authorization": "Basic " + base64.b64encode(b"sender:password").decode()}
    else:
        auth = SourceAuth(method="api_key", header_name="X-API-Key", signature_prefix="Bearer ")
        credentials = SourceCredentials(secret=SecretStr(_KEY))
        replaced = SourceCredentials(secret=SecretStr("changed"))
        headers = {"x-api-key": "Bearer " + _KEY}
    assert verify_source("webhook", auth, credentials, body=_BODY, headers=headers, url=_URL)
    assert not verify_source("webhook", auth, replaced, body=_BODY, headers=headers, url=_URL)
    assert not verify_source("webhook", auth, credentials, body=_BODY, headers={}, url=_URL)


@pytest.mark.parametrize(
    ("prefix", "accepted"),
    [("basic ", True), ("BaSiC   ", True), ("Bearer ", False), ("Basic", False)],
)
def test_basic_scheme_is_case_insensitive_but_requires_a_separate_token(prefix, accepted):
    credentials = SourceCredentials(username=SecretStr("sender"), password=SecretStr("password"))
    token = base64.b64encode(b"sender:password").decode()
    assert (
        verify_source(
            "webhook",
            SourceAuth(method="basic"),
            credentials,
            body=_BODY,
            headers={"authorization": prefix + token},
            url=_URL,
        )
        is accepted
    )


@pytest.mark.parametrize("offset", [-301, -300, 0, 300, 301])
def test_standard_webhooks_accepts_v1_signature_lists_and_enforces_five_minutes(offset):
    key = bytes(range(32))
    stamp = str(_NOW + offset)
    signed = b"event-1." + stamp.encode() + b"." + _BODY
    signature = base64.b64encode(_hmac(signed, key)).decode()
    credentials = SourceCredentials(secret=SecretStr("whsec_" + base64.b64encode(key).decode()))
    headers = {
        "webhook-id": "event-1",
        "webhook-timestamp": stamp,
        "webhook-signature": "v1,wrong v2,ignored v1," + signature,
    }
    auth = SourceAuth(method="standard_webhooks")
    assert verify_source(
        "webhook", auth, credentials, body=_BODY, headers=headers, url=_URL, now=_NOW
    ) is (abs(offset) <= 300)
    headers["webhook-id"] = "event-2"
    assert not verify_source(
        "webhook", auth, credentials, body=_BODY, headers=headers, url=_URL, now=_NOW
    )


@pytest.mark.parametrize("stamp", ["", "yesterday", "1" * 17, "\u0661\u0667" + "\u0660" * 8])
def test_standard_webhooks_refuses_malformed_timestamps(stamp):
    credentials = SourceCredentials(secret=SecretStr(base64.b64encode(bytes(range(32))).decode()))
    assert not verify_source(
        "webhook",
        SourceAuth(method="standard_webhooks"),
        credentials,
        body=_BODY,
        headers={"webhook-id": "event-1", "webhook-timestamp": stamp},
        url=_URL,
        now=_NOW,
    )


@pytest.mark.parametrize("provider", ["github", "linear", "hubspot", "zendesk"])
def test_provider_presets_reuse_each_native_signature_format(provider):
    if provider == "github":
        headers = {"x-hub-signature-256": "sha256=" + _hmac(_BODY).hex()}
    elif provider == "linear":
        headers = {"linear-signature": _hmac(_BODY).hex()}
    elif provider == "hubspot":
        stamp = str(_NOW * 1000)
        headers = {
            "x-hubspot-request-timestamp": stamp,
            "x-hubspot-signature-v3": base64.b64encode(
                _hmac(b"POST" + _URL.encode() + _BODY + stamp.encode())
            ).decode(),
        }
    else:
        stamp = datetime.fromtimestamp(_NOW, UTC).isoformat()
        headers = {
            "x-zendesk-webhook-signature-timestamp": stamp,
            "x-zendesk-webhook-signature": base64.b64encode(_hmac(stamp.encode() + _BODY)).decode(),
        }
    auth = SourceAuth(method="provider")
    credentials = SourceCredentials(secret=SecretStr(_KEY))
    assert verify_source(
        provider, auth, credentials, body=_BODY, headers=headers, url=_URL, now=_NOW
    )
    assert not verify_source(
        provider, auth, credentials, body=_BODY + b" ", headers=headers, url=_URL, now=_NOW
    )


@pytest.mark.parametrize("header", ["authorization", "x-api-key", "webhook-signature"])
def test_a_delivery_id_cannot_be_a_static_credential_or_signature(header):
    with pytest.raises(ValidationError, match="credential or signature"):
        EventSourceCreate(
            name="Source",
            auth=SourceAuth(method="api_key", header_name="x-api-key"),
            delivery_id_header=header,
        )


@pytest.mark.parametrize(
    "provider,header",
    [
        ("github", "X-Hub-Signature-256"),
        ("linear", "Linear-Signature"),
        ("hubspot", "X-HubSpot-Signature-V3"),
        ("hubspot", "X-HubSpot-Signature"),
        ("zendesk", "X-Zendesk-Webhook-Signature"),
    ],
)
def test_preset_delivery_ids_cannot_use_native_signatures(provider, header):
    with pytest.raises(ValidationError, match="credential or signature"):
        EventSourceCreate(
            name="Provider",
            provider=provider,
            auth=SourceAuth(method="provider"),
            delivery_id_header=header,
        )


@pytest.mark.parametrize(
    "key", ["invalid@@", *(base64.b64encode(b"x" * size).decode() for size in (23, 65))]
)
def test_standard_keys_are_validated_before_storage(key):
    with pytest.raises(BadRequestError):
        standard_key(key)


@pytest.mark.parametrize("size", [24, 31, 64])
def test_standard_webhooks_accepts_compliant_imported_key_lengths(size: int) -> None:
    key = bytes(range(size))
    assert standard_key("whsec_" + base64.b64encode(key).decode()) == key


def test_basic_credentials_are_required_and_masked():
    with pytest.raises(BadRequestError):
        prepare_credentials(SourceAuth(method="basic"), SourceCredentials(), generate=True)
    credentials = SourceCredentials(username=SecretStr("sender"), password=SecretStr("password"))
    normalized, reveal = prepare_credentials(SourceAuth(method="basic"), credentials, generate=True)
    assert "password" not in normalized.model_dump_json().replace('"password"', "")
    assert reveal is None


def test_missing_basic_credentials_are_refused():
    assert not verify_source(
        "webhook", SourceAuth(method="basic"), SourceCredentials(), body=b"{}", headers={}, url=_URL
    )


def test_generated_standard_credentials_have_a_valid_symmetric_key():
    credentials, reveal = prepare_credentials(
        SourceAuth(method="standard_webhooks"), SourceCredentials(), generate=True
    )
    assert reveal == credentials.secret.get_secret_value()
    assert len(standard_key(reveal)) == 32


def test_an_existing_standard_key_is_validated_without_revealing_it():
    secret = "whsec_" + base64.b64encode(b"a" * 32).decode()
    credentials, reveal = prepare_credentials(
        SourceAuth(method="standard_webhooks"),
        SourceCredentials(secret=SecretStr(secret)),
        generate=False,
    )
    assert credentials.secret.get_secret_value() == secret and reveal is None
