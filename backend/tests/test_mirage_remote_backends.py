"""Remote-only Box/LanceDB contracts, with the pinned SDKs and a local Box API."""

import pytest
from aiohttp import web
from mirage import Workspace
from mirage.core.box import client as box_client
from pydantic import JsonValue, SecretStr, ValidationError

from app.agents.capabilities.mirage import MirageMount
from app.agents.capabilities.mirage._backends import backend
from app.agents.capabilities.mirage._remote_configs import BoxServiceConfig, CloudLanceDBConfig
from app.agents.capabilities.mirage._resolved import ResolvedMount
from app.core.config import settings
from app.services.mirage_mounts import _check_hosts, _Unmountable

pytestmark = [pytest.mark.anyio, pytest.mark.security]

BOX = {"client_id": "test-client", "enterprise_id": "123", "client_secret": "vault-secret"}
LANCE = {
    "uri": "db://company",
    "host_override": "https://company.us-east-1.api.lancedb.com",
    "api_key": "vault-key",
}


def test_catalog_requires_only_service_credentials_and_no_ambient_storage_options() -> None:
    box = backend("box")
    lance = backend("lancedb")
    assert box is not None and box.available
    assert box.secret_fields == box.required_secrets == ("client_secret",)
    assert (
        not {"access_token", "refresh_token", "endpoint"} & box.options_schema["properties"].keys()
    )
    assert lance is not None and lance.available
    assert lance.secret_fields == lance.required_secrets == ("api_key",)
    assert lance.address_fields == ("host_override",)
    assert "storage_options" not in lance.options_schema["properties"]


@pytest.mark.parametrize("field", ["client_id", "enterprise_id", "client_secret"])
def test_box_requires_the_complete_service_account(field: str) -> None:
    with pytest.raises(ValidationError):
        BoxServiceConfig.model_validate({key: value for key, value in BOX.items() if key != field})


@pytest.mark.parametrize(
    "field", ["access_token", "refresh_token", "endpoint", "refresh_fn", "on_refresh_token_rotated"]
)
def test_box_refuses_other_auth_modes_and_endpoint_overrides(field: str) -> None:
    with pytest.raises(ValidationError):
        BoxServiceConfig.model_validate({**BOX, field: "refused"})


@pytest.mark.parametrize(
    "uri",
    [
        "/srv/private/company",
        "file:///srv/private/company",
        "s3://bucket/db",
        "gs://bucket/db",
        "az://bucket/db",
        "db://user:pass@host",
        "db://company/path",
        "db://company?option=x",
    ],
)
def test_lance_refuses_local_storage_and_non_cloud_uris(uri: str) -> None:
    with pytest.raises(ValidationError):
        CloudLanceDBConfig.model_validate({**LANCE, "uri": uri})


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://company.test",
        "https:///missing",
        "https://user@company.test",
        "https://user:pass@company.test",
        "https://company.test/path",
        "https://company.test?key=x",
        "https://company.test#x",
        "https://company.test:bad",
    ],
)
def test_lance_requires_an_unambiguous_https_endpoint(endpoint: str) -> None:
    with pytest.raises(ValidationError):
        CloudLanceDBConfig.model_validate({**LANCE, "host_override": endpoint})


@pytest.mark.parametrize("missing", ["api_key", "host_override"])
def test_lance_cannot_inherit_a_key_or_endpoint_from_the_host(missing: str) -> None:
    with pytest.raises(ValidationError):
        CloudLanceDBConfig.model_validate(
            {key: value for key, value in LANCE.items() if key != missing}
        )


def test_lance_refuses_storage_credentials_and_normalizes_the_endpoint() -> None:
    with pytest.raises(ValidationError):
        CloudLanceDBConfig.model_validate({**LANCE, "storage_options": {"aws_profile": "host"}})
    config = CloudLanceDBConfig.model_validate(
        {**LANCE, "host_override": LANCE["host_override"] + "/"}
    )
    assert config.host_override == LANCE["host_override"]


def test_lance_endpoint_is_checked_at_runtime_against_the_deployment_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = backend("lancedb")
    assert info is not None
    monkeypatch.setattr(settings, "MIRAGE_ALLOWED_HOSTS", [])
    with pytest.raises(_Unmountable, match="does not allow"):
        _check_hosts(info, LANCE)
    monkeypatch.setattr(settings, "MIRAGE_ALLOWED_HOSTS", ["company.us-east-1.api.lancedb.com"])
    _check_hosts(info, LANCE)


@pytest.mark.parametrize(
    "name,options,secret",
    [
        ("box", {"client_id": "client", "enterprise_id": "123"}, "client_secret"),
        ("lancedb", {"uri": "db://company", "host_override": LANCE["host_override"]}, "api_key"),
    ],
)
def test_mount_builds_without_connecting_and_credentials_stay_out_of_the_spec(
    name: str, options: dict[str, JsonValue], secret: str
) -> None:
    from uuid import uuid4

    mount = MirageMount.model_validate(
        {"path": "/data/", "backend": name, "options": options, "secrets": {secret: str(uuid4())}}
    )
    assert "vault-key" not in mount.model_dump_json()
    resolved = ResolvedMount(
        "/data/", name, "read", True, {**options, secret: SecretStr("vault-key")}, name
    )
    assert "vault-key" not in repr(resolved)
    assert resolved.build().vfs.name == name


async def test_lance_initializes_and_closes_the_real_cloud_client() -> None:
    from mirage.vfs.lancedb import LanceDBVFS

    vfs = LanceDBVFS(CloudLanceDBConfig.model_validate(LANCE))
    try:
        connection = await vfs.accessor.db()
        assert await vfs.accessor.db() is connection
        assert connection.is_open()
    finally:
        await vfs.close()
    assert not connection.is_open()


async def test_box_mints_a_service_token_and_lists_a_folder_over_real_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forms: list[dict[str, str]] = []
    headers: list[str | None] = []

    async def token(request: web.Request) -> web.Response:
        form = await request.post()
        forms.append({key: str(value) for key, value in form.items()})
        return web.json_response({"access_token": "test-access", "expires_in": 3600})

    async def items(request: web.Request) -> web.Response:
        headers.append(request.headers.get("Authorization"))
        return web.json_response(
            {
                "total_count": 1,
                "entries": [{"id": "42", "type": "file", "name": "report.txt", "size": 12}],
            }
        )

    app = web.Application()
    app.router.add_post("/oauth2/token", token)
    app.router.add_get("/2.0/folders/0/items", items)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        root = f"http://127.0.0.1:{port}"
        monkeypatch.setattr(box_client, "BOX_TOKEN_URL", root + "/oauth2/token")
        monkeypatch.setattr(box_client, "BOX_API_BASE", root + "/2.0")
        mount = ResolvedMount("/box/", "box", "read", True, BOX, "Box service account").build()
        workspace = Workspace({"/box/": mount})
        try:
            result = await workspace.shell("ls /box/")
            assert result.exit_code == 0
            assert isinstance(result.stdout, bytes)
            text = result.stdout.decode()
            assert "report.txt" in text
        finally:
            await workspace.close()
        assert forms == [
            {
                "grant_type": "client_credentials",
                "client_id": "test-client",
                "client_secret": "vault-secret",
                "box_subject_type": "enterprise",
                "box_subject_id": "123",
            }
        ]
        assert headers == ["Bearer test-access"]
    finally:
        await runner.cleanup()
