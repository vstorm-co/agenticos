"""File codecs and authentication never accept provider-selected credential destinations."""

import base64
import io
import json
from unittest.mock import AsyncMock
from zipfile import ZipFile

import httpx
import jwt
import pytest
from pydantic import SecretStr

from app.agents.mcp_oauth import OAuthError
from app.core.exceptions import BadRequestError, ExternalServiceError
from app.core.secret_kinds import EntraAppSecret, GcpServiceAccountSecret
from app.services.integrations import app_auth, client, files, slack_oauth
from app.services.integrations.catalog import PRODUCTS, Operation

pytestmark = pytest.mark.anyio
TOKEN = SecretStr("token-must-not-leak")


@pytest.fixture
def transport(monkeypatch):
    original = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
        )

    return install


async def test_upload_decodes_only_explicit_content_and_validates_metadata():
    raw, mime, metadata = files.upload_bytes(
        {
            "content_base64": base64.b64encode(b"hello").decode(),
            "name": "note.txt",
            "parent_id": "folder",
            "content_type": "text/plain",
        }
    )
    assert raw == b"hello" and mime == "text/plain"
    assert json.loads(metadata) == {"name": "note.txt", "parents": ["folder"]}
    assert files.upload_bytes({"content_base64": ""})[2] == b"{}"


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"path": "/etc/passwd"},
        {"content_base64": "!"},
        {"content_base64": "", "content_type": "text/plain\r\nX: secret"},
    ],
)
async def test_file_arguments_cannot_read_local_paths_or_inject_mime_headers(body):
    with pytest.raises(BadRequestError):
        files.upload_bytes(body)


async def test_upload_payload_is_bounded_after_decoding():
    with pytest.raises(BadRequestError, match="20 MB"):
        files.upload_bytes({"content_base64": base64.b64encode(b"x" * 20_000_001).decode()})


async def test_word_writes_are_readable_documents_without_local_paths():
    data = files.word_bytes({"title": "Status", "paragraphs": ["One", "Two"]})
    read = files.file_text(data, "application/octet-stream", word=True)
    assert read["text"] == "Status\nOne\nTwo"
    assert (
        files.file_text(
            files.word_bytes({"paragraphs": []}),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            word=False,
        )["text"]
        == ""
    )
    with pytest.raises(BadRequestError):
        files.word_bytes({"path": "/etc/passwd"})


@pytest.mark.parametrize(
    "xml",
    [
        None,
        b"bad xml",
        b'<!DOCTYPE doc [<!ENTITY x SYSTEM "file:///etc/passwd">]><doc>&x;</doc>',
        b"x" * 2_000_001,
    ],
)
async def test_invalid_or_hostile_word_documents_are_refused(xml):
    data = io.BytesIO()
    with ZipFile(data, "w") as archive:
        if xml is not None:
            archive.writestr("word/document.xml", xml)
    with pytest.raises(ExternalServiceError):
        files.file_text(data.getvalue(), "application/octet-stream", word=True)
    with pytest.raises(ExternalServiceError):
        files.file_text(b"not zip", "application/octet-stream", word=True)


async def test_text_is_clipped_and_unsupported_binary_is_explicitly_refused():
    assert files.file_text(b"x" * 100_001, "text/plain", word=False) == {
        "text": "x" * 100_000,
        "truncated": True,
        "content_type": "text/plain",
    }
    assert files.file_text(b"{}", "application/json", word=False)["text"] == "{}"
    with pytest.raises(ExternalServiceError):
        files.file_text(b"binary", "image/png", word=False)


async def test_pdf_reading_and_parse_failure_are_explicit():
    import pymupdf

    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((30, 30), "Hello")
        data = doc.tobytes()
    assert "Hello" in files.file_text(data, "application/pdf", word=False)["text"]
    with pytest.raises(ExternalServiceError):
        files.file_text(b"invalid", "application/pdf", word=False)


async def test_multipart_upload_contains_metadata_and_content_without_json_reencoding(transport):
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "created"})

    transport(handle)
    result = await client.execute(
        PRODUCTS["google_drive"].operations[-1],
        TOKEN,
        parameters={},
        query={},
        body={
            "content_base64": base64.b64encode(b"hello").decode(),
            "name": "note",
            "content_type": "text/plain",
        },
    )
    assert result == {"id": "created"}
    assert seen[0].url.params["uploadType"] == "multipart"
    assert b'"name": "note"' in seen[0].content and b"hello" in seen[0].content
    assert seen[0].headers["content-type"].startswith("multipart/related; boundary=agenticos-")


async def test_binary_and_word_uploads_use_the_declared_provider_transport(transport):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "file"})

    transport(handle)
    op = next(op for op in PRODUCTS["microsoft_files"].operations if op.id == "upload_file")
    await client.execute(
        op,
        TOKEN,
        parameters={"drive_id": "d", "parent_id": "p", "filename": "f.txt"},
        query={},
        body={"content_base64": "aGVsbG8="},
    )
    assert requests[-1].content == b"hello"
    op = PRODUCTS["word"].operations[-1]
    with pytest.raises(BadRequestError, match="docx"):
        await client.execute(
            op,
            TOKEN,
            parameters={"drive_id": "d", "parent_id": "p", "filename": "bad.exe"},
            query={},
            body={"paragraphs": []},
        )
    await client.execute(
        op,
        TOKEN,
        parameters={"drive_id": "d", "parent_id": "p", "filename": "note.docx"},
        query={},
        body={"paragraphs": ["hello"]},
    )
    assert requests[-1].content.startswith(b"PK")


async def test_file_download_redirect_drops_the_bearer_and_uses_checked_download(
    transport, monkeypatch
):
    transport(
        lambda request: httpx.Response(
            302, headers={"location": "https://files.example.test/signed"}
        )
    )
    download = AsyncMock(
        return_value=httpx.Response(200, content=b"hello", headers={"content-type": "text/plain"})
    )
    monkeypatch.setattr(client, "safe_download", download)
    op = next(op for op in PRODUCTS["microsoft_files"].operations if op.id == "read_file")
    result = await client.execute(
        op, TOKEN, parameters={"drive_id": "d", "item_id": "f"}, query={}, body=None
    )
    assert result["text"] == "hello"
    download.assert_awaited_once_with(
        "https://files.example.test/signed", max_redirects=5, max_bytes=20_000_000
    )
    download.side_effect = ValueError("private destination")
    with pytest.raises(ExternalServiceError, match="download"):
        await client.execute(
            op, TOKEN, parameters={"drive_id": "d", "item_id": "f"}, query={}, body=None
        )


async def test_file_reads_and_empty_success_are_supported(transport):
    transport(
        lambda request: httpx.Response(
            200, content=b"hello", headers={"content-type": "text/plain"}
        )
    )
    op = Operation(
        "file", "read", "GET", "https://graph.microsoft.com/file", (), response_format="file"
    )
    assert (await client.execute(op, TOKEN, parameters={}, query={}, body=None))["text"] == "hello"
    transport(lambda request: httpx.Response(204))
    assert (
        await client.execute(
            Operation("empty", "empty", "POST", "https://graph.microsoft.com/x", ()),
            TOKEN,
            parameters={},
            query={},
            body={},
        )
        == {}
    )


@pytest.mark.parametrize(
    "status,payload", [(200, {"access_token": "secret"}), (403, {}), (200, {}), (200, [])]
)
async def test_token_exchange_validates_provider_responses_without_returning_provider_errors(
    transport, status, payload
):
    transport(lambda request: httpx.Response(status, json=payload))
    if status == 200 and isinstance(payload, dict) and "access_token" in payload:
        assert (
            await app_auth._exchange("https://oauth2.googleapis.com/token", {"assertion": "secret"})
        ).get_secret_value() == "secret"
    else:
        with pytest.raises(ExternalServiceError):
            await app_auth._exchange("https://oauth2.googleapis.com/token", {})


async def test_service_account_ignores_a_key_document_token_uri_and_signs_exact_scopes(monkeypatch):
    key = GcpServiceAccountSecret(
        service_account_json=SecretStr(
            json.dumps(
                {
                    "type": "service_account",
                    "project_id": "project",
                    "client_email": "bot@example.com",
                    "private_key": "private",
                    "private_key_id": "key",
                    "token_uri": "https://evil.example/steal",
                }
            )
        )
    )
    calls = []

    def encode(claims, private, **kwargs):
        calls.append((claims, private, kwargs))
        return "assertion"

    monkeypatch.setattr(app_auth.jwt, "encode", encode)
    exchange = AsyncMock(return_value=TOKEN)
    monkeypatch.setattr(app_auth, "_exchange", exchange)
    await app_auth.google_token(key, subject="member@example.com", scopes=["read", "write"])
    assert calls[0][0]["sub"] == "member@example.com"
    assert calls[0][0]["scope"] == "read write"
    assert calls[0][2] == {"algorithm": "RS256", "headers": {"kid": "key"}}
    assert exchange.await_args.args[0] == "https://oauth2.googleapis.com/token"
    assert "private" not in repr(key)


async def test_invalid_google_keys_do_not_leak_validation_inputs(monkeypatch):
    key = GcpServiceAccountSecret.model_construct(
        service_account_json=SecretStr('{"private_key":"do-not-print"}')
    )
    with pytest.raises(ExternalServiceError) as error:
        await app_auth.google_token(key, subject=None, scopes=["read"])
    assert "do-not-print" not in str(error.value)
    key = GcpServiceAccountSecret.model_construct(
        service_account_json=SecretStr('{"client_email":"bot","private_key":"do-not-print"}')
    )
    monkeypatch.setattr(
        app_auth.jwt,
        "encode",
        lambda *args, **kwargs: (_ for _ in ()).throw(jwt.InvalidKeyError("bad key")),
    )
    with pytest.raises(ExternalServiceError, match="sign"):
        await app_auth.google_token(key, subject=None, scopes=["read"])


async def test_entra_app_uses_its_tenant_and_default_application_roles(monkeypatch):
    exchange = AsyncMock(return_value=TOKEN)
    monkeypatch.setattr(app_auth, "_exchange", exchange)
    app = EntraAppSecret(
        tenant_id="00000000-0000-0000-0000-000000000001",
        client_id="00000000-0000-0000-0000-000000000002",
        client_secret="secret-value",
    )
    await app_auth.microsoft_token(app)
    assert (
        exchange.await_args.args[0]
        == "https://login.microsoftonline.com/00000000-0000-0000-0000-000000000001/oauth2/v2.0/token"
    )
    assert exchange.await_args.args[1]["scope"] == "https://graph.microsoft.com/.default"


@pytest.mark.parametrize(
    "status,result",
    [
        (
            200,
            {
                "ok": True,
                "authed_user": {"access_token": "user", "scope": "read"},
                "access_token": "bot",
            },
        ),
        (200, {"ok": True, "access_token": "bot"}),
        (200, {"ok": False}),
        (403, {}),
        (200, {"ok": True, "authed_user": {}}),
    ],
)
async def test_slack_oauth_uses_only_the_consenting_user_token(transport, status, result):
    transport(lambda request: httpx.Response(status, json=result))
    if isinstance(result.get("authed_user"), dict) and result["authed_user"].get("access_token"):
        grant = await slack_oauth.exchange_code(
            client_id="id",
            client_secret="secret",
            code="code",
            redirect_uri="https://console/callback",
        )
        assert grant.access_token.get_secret_value() == "user"
    else:
        with pytest.raises(OAuthError):
            await slack_oauth.exchange_code(
                client_id="id",
                client_secret="secret",
                code="code",
                redirect_uri="https://console/callback",
            )


@pytest.mark.parametrize(
    "status,result",
    [
        (200, {"ok": True, "team_id": "T", "user_id": "U"}),
        (200, {"ok": False}),
        (200, {"ok": True}),
        (403, {}),
        (200, []),
    ],
)
async def test_pasted_slack_tokens_are_validated_and_keep_actual_scopes(transport, status, result):
    transport(
        lambda request: httpx.Response(
            status, json=result, headers={"x-oauth-scopes": "channels:history, chat:write"}
        )
    )
    if status == 200 and isinstance(result, dict) and result.get("user_id"):
        label, scopes = await slack_oauth.identify(TOKEN)
        assert label == "T / U" and scopes == ["channels:history", "chat:write"]
    else:
        with pytest.raises(OAuthError):
            await slack_oauth.identify(TOKEN)


async def test_connection_loss_is_an_explicit_failure_and_does_not_retry_a_write(transport):
    calls = []

    def fail(request):
        calls.append(request)
        raise httpx.ReadTimeout("lost after write")

    transport(fail)
    with pytest.raises(ExternalServiceError, match="already have completed"):
        await client.execute(
            Operation("send", "send", "POST", "https://graph.microsoft.com/send", ()),
            TOKEN,
            parameters={},
            query={},
            body={},
        )
    assert len(calls) == 1


async def test_empty_identifiers_are_refused_before_transport():
    with pytest.raises(BadRequestError):
        await client.execute(
            PRODUCTS["gmail"].operations[1],
            TOKEN,
            parameters={"thread_id": ""},
            query={},
            body=None,
        )


async def test_slack_authorization_asks_for_user_scopes_and_exact_redirect():
    from urllib.parse import parse_qs, urlsplit

    query = parse_qs(
        urlsplit(
            slack_oauth.authorization_url(
                client_id="client",
                redirect_uri="https://deployment/callback",
                scopes=["channels:history", "search:read"],
                state="bound-state",
            )
        ).query
    )
    assert query["user_scope"] == ["channels:history,search:read"]
    assert query["redirect_uri"] == ["https://deployment/callback"] and "scope" not in query


async def test_unknown_setup_provider_is_refused():
    from app.services.integrations.setup import setup_for

    with pytest.raises(BadRequestError):
        setup_for("imap")


async def test_slack_write_manifest_matches_explicit_consent_scopes():
    from urllib.parse import parse_qs, urlsplit

    from app.services.integrations.setup import setup_for

    info = setup_for("slack", write=True)
    manifest = json.loads(parse_qs(urlsplit(info.manifest_url).query)["manifest_json"][0])
    assert set(manifest["oauth_config"]["scopes"]["user"]) == set(
        info.products[0].read_scopes + info.products[0].write_scopes
    )
