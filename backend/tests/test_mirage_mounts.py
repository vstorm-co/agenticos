"""A virtual terminal's folders, resolved for one run (#2191).

What the runner decides before the model is called: which secret and which
account a folder reaches, and which folders cannot be built - each left out with a
sentence the model reads, rather than failing a run whose other folders work.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.agents.capabilities.mirage import MirageConfig
from app.core.config import settings
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, EntraAppSecret
from app.services import mirage_mounts
from app.services.mcp_connection import AccountGrant
from app.services.mirage_mounts import MirageMountService, host_of
from app.services.portals import google_oauth

pytestmark = pytest.mark.anyio

TOKEN = uuid4()
DSN = uuid4()
APP = uuid4()


@pytest.fixture
def ctx() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")


@pytest.fixture
def vault(monkeypatch) -> dict:
    stored: dict = {
        TOKEN: ApiKeySecret(api_key="ghp_token"),
        DSN: ApiKeySecret(api_key="postgresql://u:pw@db.acme.internal:5432/sales"),
        APP: EntraAppSecret(
            tenant_id="acme.onmicrosoft.com",
            client_id="00000000-0000-0000-0000-000000000001",
            client_secret="app-secret",
        ),
    }
    monkeypatch.setattr(
        mirage_mounts.OrganizationSecretService,
        "resolve_for_bindings",
        AsyncMock(side_effect=lambda ctx, ids: {i: stored[i] for i in ids if i in stored}),
    )
    return stored


@pytest.fixture
def accounts(monkeypatch) -> MagicMock:
    repo = MagicMock()
    repo.get_account = AsyncMock(return_value=None)
    repo.list_accounts = AsyncMock(return_value=[])
    monkeypatch.setattr(mirage_mounts, "mcp_connection_repo", repo)
    return repo


def _config(*mounts: dict) -> MirageConfig:
    return MirageConfig.model_validate({"mounts": list(mounts)})


def _grant(email: str, scopes=frozenset({google_oauth.DRIVE})) -> AccountGrant:
    return AccountGrant(
        email=email,
        client_id="org-client",
        client_secret=SecretStr("org-secret"),
        refresh_token=SecretStr(f"rt-{email}"),
        scopes=scopes,
    )


async def _resolve(ctx, config, *, person_id=None):
    return await MirageMountService(AsyncMock()).resolve(ctx, config, person_id=person_id)


async def test_a_secret_field_is_unsealed_into_the_folders_config(ctx, vault, accounts):
    terminal = await _resolve(
        ctx,
        _config(
            {
                "path": "/code/",
                "backend": "github",
                "secrets": {"token": str(TOKEN)},
                "options": {"owner": "o", "repo": "r"},
            },
            {"path": "/scratch/", "backend": "ram", "mode": "write"},
        ),
    )
    code, scratch = terminal.mounts
    assert code.config["token"] == SecretStr("ghp_token") and code.config["repo"] == "r"
    assert code.title == "GitHub" and scratch.backend == "ram" and terminal.notes == ()


async def test_a_secret_gone_from_the_vault_leaves_the_folder_out(ctx, vault, accounts):
    del vault[TOKEN]
    terminal = await _resolve(
        ctx,
        _config(
            {
                "path": "/code/",
                "backend": "github",
                "secrets": {"token": str(TOKEN)},
                "options": {"owner": "o", "repo": "r"},
            }
        ),
    )
    assert terminal.mounts == ()
    assert terminal.notes == ("/code/ is not mounted: its token secret is no longer in the vault.",)


async def test_a_host_inside_a_secret_is_checked_when_it_is_dialled(
    ctx, vault, accounts, monkeypatch
):
    config = _config({"path": "/db/", "backend": "postgres", "secrets": {"dsn": str(DSN)}})

    monkeypatch.setattr(settings, "MIRAGE_ALLOWED_HOSTS", [])
    refused = await _resolve(ctx, config)
    assert refused.mounts == () and "(db.acme.internal)" in refused.notes[0]
    assert "pw" not in refused.notes[0]

    monkeypatch.setattr(settings, "MIRAGE_ALLOWED_HOSTS", ["DB.acme.internal"])
    allowed = await _resolve(ctx, config)
    assert [mount.path for mount in allowed.mounts] == ["/db/"]


async def test_a_typed_host_off_the_list_is_refused_and_a_missing_one_is_fine(
    ctx, vault, accounts, monkeypatch
):
    monkeypatch.setattr(settings, "MIRAGE_ALLOWED_HOSTS", [])
    terminal = await _resolve(
        ctx,
        _config(
            {"path": "/box/", "backend": "ssh", "options": {"host": "build.acme.internal"}},
            {"path": "/traces/", "backend": "jaeger"},
        ),
    )
    assert [mount.path for mount in terminal.mounts] == ["/traces/"]
    assert "build.acme.internal" in terminal.notes[0]


def _entra(monkeypatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []
    original = httpx.AsyncClient

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        mirage_mounts.httpx,
        "AsyncClient",
        lambda *a, **k: original(*a, transport=httpx.MockTransport(answer), **k),
    )
    return seen


async def test_a_microsoft_folder_gets_a_graph_token_for_its_app(ctx, vault, accounts, monkeypatch):
    seen = _entra(
        monkeypatch, lambda request: httpx.Response(200, json={"access_token": "graph-token"})
    )
    terminal = await _resolve(
        ctx, _config({"path": "/files/", "backend": "sharepoint", "secrets": {"app": str(APP)}})
    )
    assert terminal.mounts[0].config["access_token"] == SecretStr("graph-token")
    assert "/acme.onmicrosoft.com/oauth2/v2.0/token" in str(seen[0].url)
    assert b"grant_type=client_credentials" in seen[0].content


@pytest.mark.parametrize(
    ("handler", "said"),
    [
        (
            lambda request: httpx.Response(401, json={"error": "invalid_client"}),
            "refused its app's credentials",
        ),
        (lambda request: httpx.Response(200, json={"token_type": "Bearer"}), "with no token"),
        (lambda request: httpx.Response(200, text="<html>"), "with no token"),
    ],
)
async def test_a_graph_sign_in_that_fails_leaves_the_folder_out(
    ctx, vault, accounts, monkeypatch, handler, said
):
    _entra(monkeypatch, handler)
    terminal = await _resolve(
        ctx, _config({"path": "/files/", "backend": "onedrive", "secrets": {"app": str(APP)}})
    )
    assert terminal.mounts == () and said in terminal.notes[0]


async def test_an_unreachable_entra_leaves_the_folder_out(ctx, vault, accounts, monkeypatch):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    _entra(monkeypatch, down)
    terminal = await _resolve(
        ctx, _config({"path": "/files/", "backend": "onedrive", "secrets": {"app": str(APP)}})
    )
    assert "could not be reached" in terminal.notes[0]


async def test_an_entra_app_replaced_by_another_kind_is_not_signed_in_as(ctx, vault, accounts):
    vault[APP] = ApiKeySecret(api_key="not an app")
    terminal = await _resolve(
        ctx, _config({"path": "/files/", "backend": "onedrive", "secrets": {"app": str(APP)}})
    )
    assert "Entra app is no longer in the vault" in terminal.notes[0]


# -- Google accounts ---------------------------------------------------------------


def _with_grants(monkeypatch, grants: dict) -> None:
    monkeypatch.setattr(
        mirage_mounts.McpConnectionService,
        "account_grant",
        AsyncMock(side_effect=lambda account: grants.get(account.id)),
    )


async def test_the_organizations_account_is_one_folder_with_its_refresh_token(
    ctx, vault, accounts, monkeypatch
):
    account = MagicMock(id=uuid4(), organization_id=ctx.organization_id, label="ops@acme.com")
    accounts.get_account = AsyncMock(return_value=account)
    _with_grants(monkeypatch, {account.id: _grant("ops@acme.com")})

    terminal = await _resolve(
        ctx,
        _config(
            {
                "path": "/drive/",
                "backend": "gdrive",
                "account": {"kind": "organization", "connection_id": str(account.id)},
            }
        ),
    )

    [drive] = terminal.mounts
    assert drive.path == "/drive/" and drive.title == "Google Drive of ops@acme.com"
    assert drive.config["refresh_token"] == SecretStr("rt-ops@acme.com")
    assert drive.config["client_id"] == "org-client"


async def test_another_organizations_account_is_not_mounted(ctx, vault, accounts):
    accounts.get_account = AsyncMock(return_value=MagicMock(organization_id=uuid4()))
    terminal = await _resolve(
        ctx,
        _config(
            {
                "path": "/drive/",
                "backend": "gdrive",
                "account": {"kind": "organization", "connection_id": str(uuid4())},
            }
        ),
    )
    assert terminal.mounts == () and "was disconnected" in terminal.notes[0]


async def test_each_of_a_persons_accounts_is_a_folder_of_its_own(ctx, vault, accounts, monkeypatch):
    person = uuid4()
    work = MagicMock(id=uuid4(), label="ana@acme.com")
    home = MagicMock(id=uuid4(), label="Ana.Home@Gmail.com")
    accounts.list_accounts = AsyncMock(return_value=[work, home])
    _with_grants(
        monkeypatch,
        {
            work.id: _grant("ana@acme.com", frozenset({google_oauth.GMAIL})),
            home.id: _grant("Ana.Home@Gmail.com", frozenset({google_oauth.GMAIL})),
        },
    )

    terminal = await _resolve(
        ctx,
        _config({"path": "/mail/", "backend": "gmail", "account": {"kind": "personal"}}),
        person_id=person,
    )

    assert [mount.path for mount in terminal.mounts] == [
        "/mail/ana-acme.com/",
        "/mail/ana.home-gmail.com/",
    ]
    assert accounts.list_accounts.await_args.kwargs == {"provider": "google", "user_id": person}


@pytest.mark.parametrize(
    ("person", "listed", "said"),
    [
        (None, [], "answers nobody who has one"),
        ("someone", [], "they have not connected one"),
    ],
)
async def test_a_personal_folder_without_an_account_says_where_to_connect_one(
    ctx, vault, accounts, person, listed, said
):
    accounts.list_accounts = AsyncMock(return_value=listed)
    terminal = await _resolve(
        ctx,
        _config({"path": "/drive/", "backend": "gdrive", "account": {"kind": "personal"}}),
        person_id=uuid4() if person else None,
    )
    assert terminal.mounts == () and said in terminal.notes[0]


async def test_a_grant_that_cannot_be_used_or_lacks_the_service_leaves_the_folder_out(
    ctx, vault, accounts, monkeypatch
):
    stale = MagicMock(id=uuid4(), label="old@acme.com")
    narrow = MagicMock(id=uuid4(), label=None)
    accounts.list_accounts = AsyncMock(return_value=[stale])
    _with_grants(monkeypatch, {narrow.id: _grant("ana@acme.com", frozenset({google_oauth.GMAIL}))})
    config = _config({"path": "/docs/", "backend": "gdocs", "account": {"kind": "personal"}})

    first = await _resolve(ctx, config, person_id=uuid4())
    assert "old@acme.com has to be connected again" in first.notes[0]

    accounts.list_accounts = AsyncMock(return_value=[narrow])
    second = await _resolve(ctx, config, person_id=uuid4())
    assert "did not grant access to Google Docs" in second.notes[0]

    stale.label = None
    accounts.list_accounts = AsyncMock(return_value=[stale])
    third = await _resolve(ctx, config, person_id=uuid4())
    assert "the account has to be connected again" in third.notes[0]


async def test_a_backend_that_went_away_since_publish_is_said_not_built(
    ctx, vault, accounts, monkeypatch
):
    config = _config({"path": "/scratch/", "backend": "ram"})
    monkeypatch.setattr(mirage_mounts, "backend", lambda name: None)
    terminal = await _resolve(ctx, config)
    assert terminal.mounts == () and "cannot reach that service" in terminal.notes[0]


def test_options_are_passed_as_the_library_takes_them() -> None:
    assert mirage_mounts._option(["a", 1]) == ["a", "1"]
    assert mirage_mounts._option({"x": 1}) == "{'x': 1}"
    assert mirage_mounts._option(None) is None and mirage_mounts._option(3) == 3


@pytest.mark.parametrize(
    ("value", "host"),
    [
        ("postgresql://u:pw@db.acme.internal:5432/x", "db.acme.internal"),
        ("mongodb://[::1", None),
        ("ana@build.acme.internal:22", "build.acme.internal"),
        ("IMAP.acme.com", "imap.acme.com"),
        ("", None),
    ],
)
def test_the_host_of_a_typed_address(value, host) -> None:
    assert host_of(value) == host


def test_an_address_slug_is_never_empty() -> None:
    assert mirage_mounts._slug("@@@") == "account"
