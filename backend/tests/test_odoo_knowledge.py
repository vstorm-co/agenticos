"""An Odoo source indexes only selected business fields under its shared account."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.exceptions import BadRequestError, ExternalServiceError
from app.core.odoo_credential import OdooCredential
from app.core.secret_kinds import ApiKeySecret
from app.services.integrations import OdooAccountToken
from app.services.rag.connectors import RemoteFile, odoo

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def setup_source():
    connection = uuid4()
    config = {
        "connection_id": str(connection),
        "product_id": "odoo_contacts",
        "fields": ["name", "email"],
    }
    secret = OdooAccountToken(
        connection_id=connection,
        api_key=SecretStr("private-key"),
        credential=OdooCredential(
            origin="https://erp.example.com", database="company", api_key="private-key"
        ),
    )
    return config, secret


async def test_fields_are_explicit_and_config_contains_no_credentials():
    config, _ = setup_source()
    connector = odoo.OdooConnector()
    assert await connector.validate_config(config) is None
    assert await connector.validate_config({}) is not None
    assert (await connector.validate_config({**config, "fields": ["bad field"]})).field == "fields"


async def test_listing_and_download_use_the_same_account_and_field_selection(monkeypatch, tmp_path):
    config, secret = setup_source()
    execute = AsyncMock(
        side_effect=[
            {"result": [{"id": 7, "display_name": "Acme", "write_date": "2026-11-07 10:00:00"}]},
            {"result": [{"id": 7, "name": "Acme", "email": "hello@example.com"}]},
        ]
    )
    monkeypatch.setattr(odoo, "execute", execute)
    connector = odoo.OdooConnector()
    listing = await connector.list_files(config, secret)
    assert listing.complete and listing.problems == []
    file = listing.files[0]
    assert file.id == "res.partner:7"
    assert file.modified_at.isoformat() == "2026-11-07T10:00:00+00:00"
    destination = tmp_path / "record.md"
    await connector._fetch(file, destination, config, secret)
    assert "hello@example.com" in destination.read_text()
    assert "private-key" not in destination.read_text()
    assert execute.await_args.kwargs["body"] == {"ids": [7], "fields": ["name", "email"]}
    assert execute.await_args.args[0] == secret.credential


@pytest.mark.parametrize("kind", ["missing", "raw", "other_account"])
async def test_raw_or_other_account_credentials_are_never_spent(kind):
    config, secret = setup_source()
    credential = (
        None
        if kind == "missing"
        else ApiKeySecret(api_key="private-key")
        if kind == "raw"
        else secret.model_copy(update={"connection_id": uuid4()})
    )
    with pytest.raises(BadRequestError):
        await odoo.OdooConnector().list_files(config, credential)


@pytest.mark.parametrize(
    "rows",
    [{}, [False], [{"id": "7"}], [{"id": 0}], [{"id": 7}], [{"id": 7, "write_date": "invalid"}]],
)
async def test_invalid_provider_listing_never_claims_completeness(monkeypatch, rows):
    config, secret = setup_source()
    monkeypatch.setattr(odoo, "execute", AsyncMock(return_value={"result": rows}))
    with pytest.raises(ExternalServiceError):
        await odoo.OdooConnector().list_files(config, secret)


async def test_page_limit_disables_removal_and_retains_the_last_record(monkeypatch):
    config, secret = setup_source()

    async def read(*args, **kwargs):
        after = kwargs["body"]["domain"][0][2]
        return {
            "result": [
                {"id": after + offset, "write_date": "2026-11-07 10:00:00"}
                for offset in range(1, 101)
            ]
        }

    monkeypatch.setattr(odoo, "execute", read)
    result = await odoo.OdooConnector().list_files(config, secret)
    assert not result.complete and result.problems
    assert len(result.files) == 5000 and result.files[-1].id == "res.partner:5000"


@pytest.mark.parametrize(
    "identifier", ["res.users:7", "res.partner:0", "res.partner:bad", "res.partner:" + "1" * 16]
)
async def test_download_cannot_retarget_models_or_record_ids(tmp_path, identifier):
    config, secret = setup_source()
    file = RemoteFile(
        id=identifier, name="record.md", mime_type="text/markdown", source_path="odoo://test"
    )
    with pytest.raises(BadRequestError):
        await odoo.OdooConnector()._fetch(file, tmp_path / "record.md", config, secret)


@pytest.mark.parametrize("rows", [None, [], [{}], [{"id": 8}], [False], [{"id": 7}, {"id": 8}]])
async def test_missing_or_different_records_are_not_successfully_indexed(
    monkeypatch, tmp_path, rows
):
    config, secret = setup_source()
    monkeypatch.setattr(odoo, "execute", AsyncMock(return_value={"result": rows}))
    file = RemoteFile(
        id="res.partner:7", name="record.md", mime_type="text/markdown", source_path="odoo://test"
    )
    with pytest.raises(ExternalServiceError):
        await odoo.OdooConnector()._fetch(file, tmp_path / "record.md", config, secret)
