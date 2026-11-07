"""File codecs and authentication never accept provider-selected credential destinations."""

import base64
import io
import json
from unittest.mock import AsyncMock
from uuid import uuid4
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

pytestmark = [pytest.mark.anyio, pytest.mark.security]
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
    token = SecretStr(
        jwt.encode(
            {"aud": "00000003-0000-0000-c000-000000000000", "roles": ["Files.Read.All"]},
            "test-configuration-metadata-key-only",
            algorithm="HS256",
        )
    )
    exchange = AsyncMock(return_value=token)
    monkeypatch.setattr(app_auth, "_exchange", exchange)
    app = EntraAppSecret(
        tenant_id="00000000-0000-0000-0000-000000000001",
        client_id="00000000-0000-0000-0000-000000000002",
        client_secret="secret-value",
    )
    grant = await app_auth.microsoft_token(app)
    assert grant.access_token == token and grant.granted_scopes == frozenset({"Files.Read.All"})
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


@pytest.mark.parametrize(
    "shape", ["nested", "flat_user", "bot", "revoked", "refused", "unreadable", "status"]
)
async def test_slack_rotation_preserves_user_authority_and_the_new_refresh_token(transport, shape):
    from app.agents.mcp_oauth import OAuthError, OAuthGrantRevoked

    data = {
        "access_token": "user-access",
        "refresh_token": "next-refresh",
        "expires_in": 43200,
        "scope": "search:read",
    }
    body = {"ok": True, "authed_user": data, "access_token": "bot-token"}
    if shape == "flat_user":
        body = {"ok": True, "token_type": "user", **data}
    if shape == "bot":
        body = {"ok": True, "token_type": "bot", **data}
    if shape == "revoked":
        body = {"ok": False, "error": "invalid_refresh_token"}
    if shape == "refused":
        body = {"ok": False}

    def respond(request):
        assert request.url == slack_oauth.TOKEN_ENDPOINT
        assert b"grant_type=refresh_token" in request.content
        return httpx.Response(
            503 if shape == "status" else 200,
            content=b"bad" if shape == "unreadable" else None,
            json=None if shape == "unreadable" else body,
        )

    transport(respond)
    if shape in {"nested", "flat_user"}:
        result = await slack_oauth.refresh_user_token(
            client_id="client", client_secret="secret", refresh_token=SecretStr("old-refresh")
        )
        assert result.access_token.get_secret_value() == "user-access"
        assert result.refresh_token.get_secret_value() == "next-refresh"
    else:
        with pytest.raises(OAuthGrantRevoked if shape == "revoked" else OAuthError):
            await slack_oauth.refresh_user_token(
                client_id="client", client_secret="secret", refresh_token=SecretStr("old-refresh")
            )


async def test_slack_rotation_network_failure_does_not_echo_the_key(transport):
    from app.agents.mcp_oauth import OAuthError

    def fail(request):
        raise httpx.ReadTimeout("secret")

    transport(fail)
    with pytest.raises(OAuthError, match="could not refresh"):
        await slack_oauth.refresh_user_token(
            client_id="client", client_secret="secret", refresh_token=SecretStr("old-refresh")
        )


def test_slack_client_hint_contains_only_the_public_client_id_suffix():
    from app.core.secret_kinds import SlackOAuthAppSecret

    value = SlackOAuthAppSecret(client_id="client-1234", client_secret="private-secret")
    assert value.hint == "1234"
    assert "private-secret" not in repr(value)


def test_word_reading_keeps_formatted_runs_inside_their_original_paragraph():
    from docx import Document

    document = Document()
    paragraph = document.add_paragraph("Hello ")
    paragraph.add_run("bold").bold = True
    paragraph.add_run(" world.")
    document.add_paragraph("Next paragraph.")
    output = io.BytesIO()
    document.save(output)
    result = files.file_text(
        output.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        word=True,
    )
    assert result["text"] == "Hello bold world.\nNext paragraph."


async def test_sharepoint_connected_account_never_uses_an_application_secret(transport):
    from app.services.integrations import AccountToken
    from app.services.rag.connectors.sharepoint import _Graph

    token = AccountToken(connection_id=uuid4(), provider="microsoft", api_key="delegated-token")
    async with httpx.AsyncClient() as http:
        graph = _Graph(token, http, 0)
        assert await graph._bearer() == "delegated-token"


async def test_application_file_feed_baselines_without_reading_me(transport):
    from app.services.portals.microsoft_files import MicrosoftFilesPortalAdapter

    transport(lambda request: pytest.fail("an application identity has no /me endpoint"))
    read = await MicrosoftFilesPortalAdapter(subject="mailbox@example.com").poll(
        access_token="application-token", cursor=None
    )
    assert read.events == () and read.cursor["account"] == "mailbox@example.com"


@pytest.mark.parametrize("roles", [None, []])
async def test_entra_roleless_tokens_cannot_claim_requested_permissions(monkeypatch, roles):
    from app.core.exceptions import AuthorizationError

    claims = {"aud": "https://graph.microsoft.com"}
    if roles is not None:
        claims["roles"] = roles
    token = jwt.encode(claims, "test-configuration-metadata-key-only", algorithm="HS256")
    monkeypatch.setattr(app_auth, "_exchange", AsyncMock(return_value=SecretStr(token)))
    with pytest.raises(AuthorizationError, match="granted no application roles"):
        await app_auth.microsoft_token(
            EntraAppSecret(
                tenant_id=str(uuid4()),
                client_id=str(uuid4()),
                client_secret="private-secret",
            )
        )


@pytest.mark.parametrize(
    "token",
    [
        "opaque-provider-token",
        "encrypted.provider.token.has.parts",
        "header.%%%.signature",
        "header.ą.signature",
        "header." + base64.urlsafe_b64encode(b"not json").decode() + ".signature",
        *[
            jwt.encode(claims, "test-configuration-metadata-key-only", algorithm="HS256")
            for claims in [
                {"aud": "other-api", "roles": ["Mail.Read"]},
                {"aud": "https://graph.microsoft.com", "roles": "Mail.Read"},
                {"aud": "https://graph.microsoft.com", "roles": [123]},
            ]
        ],
    ],
)
async def test_entra_unreadable_permission_metadata_has_an_explicit_safe_failure(
    monkeypatch, token
):
    monkeypatch.setattr(app_auth, "_exchange", AsyncMock(return_value=SecretStr(token)))
    with pytest.raises(ExternalServiceError, match="readable Graph application roles") as exc:
        await app_auth.microsoft_token(
            EntraAppSecret(
                tenant_id=str(uuid4()), client_id=str(uuid4()), client_secret="private-secret"
            )
        )
    assert token not in str(exc.value) and "private" not in str(exc.value)


@pytest.mark.parametrize(
    "channels", [("C-public",), ("C-private",), ("D-direct",), ("G-group-dm",)]
)
@pytest.mark.parametrize("permitted", [False, True])
async def test_slack_checks_history_access_for_each_selected_conversation_type(
    transport, channels, permitted
):
    from app.core.exceptions import BadRequestError

    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={"ok": permitted, "error": "missing_scope"}
            if not permitted
            else {"ok": True, "messages": []},
        )

    transport(respond)
    if permitted:
        await slack_oauth.validate_conversations(TOKEN, channels * 2)
    else:
        with pytest.raises(BadRequestError, match="selected conversation"):
            await slack_oauth.validate_conversations(TOKEN, channels)
    assert len(seen) == 1
    assert seen[0].url.path == "/api/conversations.history"
    assert dict(seen[0].url.params) == {"channel": channels[0], "limit": "1"}
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN.get_secret_value()}"


@pytest.mark.parametrize("failure", ["unreachable", "http", "malformed", "too-many"])
async def test_slack_conversation_validation_keeps_outages_explicit(transport, failure):
    from app.core.exceptions import BadRequestError

    def respond(request):
        if failure == "unreachable":
            raise httpx.ConnectError("provider offline", request=request)
        return (
            httpx.Response(503) if failure == "http" else httpx.Response(200, content=b"not JSON")
        )

    transport(respond)
    if failure == "too-many":
        with pytest.raises(BadRequestError, match="twenty"):
            await slack_oauth.validate_conversations(TOKEN, tuple(f"C{i}" for i in range(21)))
    else:
        with pytest.raises(ExternalServiceError, match="try again"):
            await slack_oauth.validate_conversations(TOKEN, ("C1",))
