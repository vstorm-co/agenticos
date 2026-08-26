"""A sync source's credential is a vault secret, and whose it is gets checked.

#937. `sync_sources.config` held the credential - a Google service account JSON
or an AWS key pair - encrypted by `app/core/crypto.py`: one deployment-wide
Fernet key over every tenant's secret, which is the weakness the vault exists to
remove and the one place `CLAUDE.md`'s "there is no second mechanism" was untrue.

Three refusals carry the change, and each one is a thing the foreign key cannot
say:

* **Whose credential it is.** `organization_secrets.id` is unique across the
  deployment, so a caller who supplies another organization's id satisfies the
  database. That is the shape of #918, where an embedding key was bound by id
  without asking whether the chooser could see it.
* **What kind it is.** An S3 source given a service account fails at sync time,
  in a worker, with the reason in a log rather than on the form that chose it.
* **That it is not in the config at all.** A caller posting the retired field
  names has not been updated, and dropping them silently would store a source
  that cannot authenticate and say nothing about why.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.repositories import organization_secret_repo
from app.schemas.sync_source import (
    ConnectorConfigField,
    ConnectorFieldType,
    SyncSourceCreate,
    SyncSourceUpdate,
)
from app.services import sync_source as sync_source_module
from app.services.rag.connectors.s3 import S3Connector
from app.services.sync_source import SyncSourceService

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_OTHER_ORG = uuid.uuid4()
_CALLER = uuid.uuid4()


def _ctx(organization_id: uuid.UUID) -> AuthContext:
    """An owner, so a refusal here is about the credential rather than the role."""
    return AuthContext(
        user_id=_CALLER,
        organization_id=organization_id,
        role=OrgRoleName.OWNER.value,
    )


def _service(
    monkeypatch: pytest.MonkeyPatch, *, secret=None, visible: bool = True
) -> SyncSourceService:
    """The real service, with the repositories it reaches mocked at the boundary.

    `visible` stands in for `resolve_access`, which is tested on its own and
    needs a real row and a real grant table. What matters here is that this
    service *asks* it, and refuses when the answer is no.
    """
    monkeypatch.setattr(sync_source_module, "resolve_access", AsyncMock(return_value=visible))
    monkeypatch.setattr(
        organization_secret_repo, "get", AsyncMock(return_value=secret), raising=False
    )
    monkeypatch.setattr(
        sync_source_module.organization_secret_repo, "get", AsyncMock(return_value=secret)
    )
    monkeypatch.setattr(
        sync_source_module.sync_source_repo,
        "create",
        AsyncMock(
            # `SimpleNamespace`, not `MagicMock`: `name` is MagicMock's own
            # keyword and a row built with it comes back as a mock's repr.
            side_effect=lambda db, **kwargs: SimpleNamespace(
                id=uuid.uuid4(),
                organization_id=kwargs["organization_id"],
                name=kwargs["name"],
                connector_type=kwargs["connector_type"],
                collection_name=kwargs["collection_name"],
                config=kwargs["config"],
                secret_id=kwargs["secret_id"],
                sync_mode=kwargs["sync_mode"],
                schedule_minutes=kwargs["schedule_minutes"],
                is_active=True,
                last_sync_at=None,
                last_sync_status=None,
                last_error=None,
                created_at=None,
            )
        ),
    )
    db = MagicMock()
    db.flush = AsyncMock()
    return SyncSourceService(db)


def _vault_row(*, kind: str, hint: str = "a1b2") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), kind=kind, hint=hint)


def _drive(**overrides) -> SyncSourceCreate:
    return SyncSourceCreate(
        name="Legal docs",
        connector_type="gdrive",
        collection_name="legal",
        config={"folder_id": "1AbC_-def"},
        **overrides,
    )


class TestTheCredentialIsReferencedNotCarried:
    async def test_a_source_naming_a_credential_of_the_right_kind_is_created(self, monkeypatch):
        row = _vault_row(kind="gcp_service_account", hint="9f3c")
        service = _service(monkeypatch, secret=row)
        secret_id = uuid.uuid4()

        read = await service.create_source(_drive(secret_id=secret_id), ctx=_ctx(_ORG))

        assert read.secret_id == str(secret_id)
        # The hint travels so a reader can tell which credential without seeing it.
        assert read.secret_hint == "9f3c"

    async def test_a_credential_this_organization_does_not_hold_is_refused(self, monkeypatch):
        """`organization_secrets.id` is unique deployment-wide, so the foreign key
        is satisfied by another tenant's id. The lookup is scoped, and the refusal
        does not confirm that the id exists."""
        service = _service(monkeypatch, secret=None)

        with pytest.raises(BadRequestError) as exc:
            await service.create_source(_drive(secret_id=uuid.uuid4()), ctx=_ctx(_OTHER_ORG))

        assert exc.value.details is not None
        assert exc.value.details["fields"][0]["field"] == "secret_id"
        assert "no such credential" in exc.value.details["fields"][0]["message"].lower()

    async def test_a_credential_the_caller_cannot_see_is_refused(self, monkeypatch):
        """A secret can be private to a member, and a sync runs for everyone who
        can reach the collection - so binding one is lending it. A Builder holding
        `connections:manage` but only shared-secret visibility could otherwise
        post the id of another member's private credential and have the worker
        unseal it (#918, in this table).

        Refused as a miss, in the same words as an id that does not exist: a
        refusal that differs is a way to enumerate the vault.
        """
        service = _service(
            monkeypatch, secret=_vault_row(kind="gcp_service_account"), visible=False
        )

        with pytest.raises(BadRequestError) as exc:
            await service.create_source(_drive(secret_id=uuid.uuid4()), ctx=_ctx(_ORG))

        assert "no such credential" in exc.value.details["fields"][0]["message"].lower()

    async def test_a_credential_of_the_wrong_kind_is_refused(self, monkeypatch):
        """An AWS key pair cannot sign a Drive request. Refusing here says which
        field; failing at sync time says it in a worker log."""
        service = _service(monkeypatch, secret=_vault_row(kind="aws_credentials"))

        with pytest.raises(BadRequestError) as exc:
            await service.create_source(_drive(secret_id=uuid.uuid4()), ctx=_ctx(_ORG))

        problem = exc.value.details["fields"][0]
        assert problem["field"] == "secret_id"
        assert "gcp_service_account" in problem["message"]

    async def test_a_source_with_no_credential_is_allowed_and_syncs_nowhere(self, monkeypatch):
        """`secret_id` is optional on the way in, deliberately: a source can be
        created before its credential exists, and the sync refuses rather than the
        creation. What is *not* allowed is inventing a fallback for it."""
        service = _service(monkeypatch)

        read = await service.create_source(_drive(), ctx=_ctx(_ORG))

        assert read.secret_id is None
        assert read.secret_hint is None


class TestACredentialInTheConfigIsRefused:
    @pytest.mark.parametrize(
        ("connector_type", "field", "value"),
        [
            ("gdrive", "service_account_json", '{"type": "service_account"}'),
            ("s3", "access_key_id", "AKIAEXAMPLE"),
            ("s3", "secret_access_key", "very-secret"),
        ],
    )
    async def test_the_retired_field_names_are_refused_by_name(
        self, monkeypatch, connector_type: str, field: str, value: str
    ):
        """Not dropped: a caller posting the old shape has not been updated, and a
        silently stripped credential is a source that stores and then cannot
        authenticate."""
        service = _service(monkeypatch)
        config: dict[str, object] = {field: value}
        if connector_type == "gdrive":
            config["folder_id"] = "1AbC"
        else:
            config["bucket"] = "docs"

        with pytest.raises(BadRequestError) as exc:
            await service.create_source(
                SyncSourceCreate(name="Legacy", connector_type=connector_type, config=config),
                ctx=_ctx(_ORG),
            )

        assert field in exc.value.details["fields"]
        assert "does not go in a source's configuration" in exc.value.message

    async def test_a_config_of_only_real_fields_passes(self, monkeypatch):
        service = _service(monkeypatch)

        read = await service.create_source(
            SyncSourceCreate(
                name="Marketing",
                connector_type="s3",
                config={"bucket": "docs", "prefix": "marketing/"},
            ),
            ctx=_ctx(_ORG),
        )

        assert read.config == {"bucket": "docs", "prefix": "marketing/"}

    async def test_patching_a_credential_into_the_config_is_refused_too(self, monkeypatch):
        """`create_source` was once the only path that checked its config, so a
        value refused at creation could be patched in afterwards (#897). The same
        applies to a credential."""
        service = _service(monkeypatch)
        existing = SimpleNamespace(
            connector_type="gdrive",
            ctx=_ctx(_ORG),
            config={"folder_id": "1AbC"},
            secret_id=None,
        )
        monkeypatch.setattr(service, "get_source", AsyncMock(return_value=existing))

        with pytest.raises(BadRequestError) as exc:
            await service.update_source(
                str(uuid.uuid4()),
                SyncSourceUpdate(config={"service_account_json": "{}"}),
                ctx=_ctx(_ORG),
            )

        assert "service_account_json" in exc.value.details["fields"]


class TestWhatTheReadCarries:
    async def test_the_config_comes_back_unmasked(self, monkeypatch):
        """There is nothing in it to mask any more. The `••••••` round-trip existed
        so a patch could skip a value it could not see, and both halves are gone."""
        service = _service(monkeypatch)

        read = await service.create_source(
            SyncSourceCreate(
                name="Marketing",
                connector_type="s3",
                config={"bucket": "docs", "prefix": "marketing/"},
            ),
            ctx=_ctx(_ORG),
        )

        assert "••••••" not in str(read.config)
        assert read.config["bucket"] == "docs"


class TestWhatTheConnectorsDeclare:
    def test_each_connector_names_the_kind_it_authenticates_with(self):
        """The wizard offers the organization's matching credentials and nothing
        else, so a connector that declared none would offer everything."""
        from app.services.rag.connectors import CONNECTOR_REGISTRY

        kinds = {name: cls.SECRET_KIND.value for name, cls in CONNECTOR_REGISTRY.items()}

        assert kinds == {"gdrive": "gcp_service_account", "s3": "aws_credentials"}

    def test_a_connector_cannot_ask_for_a_secret_in_its_config_schema(self):
        """The `secret: true` marker is gone, and with it `_mask_config`,
        `_secret_fields` and the encryption they existed for.

        A declaration is a `ConnectorConfigField` now rather than a bare mapping,
        so this is no longer a sweep over what the two shipped connectors happen
        to say: the field does not exist to be set, in any connector written
        later, and `ty` refuses one that tries (#562)."""
        assert "secret" not in ConnectorConfigField.model_fields

    def test_every_declared_field_is_something_the_wizard_can_draw(self):
        """`type` is what `SyncSourceConfigureStep` branches on, and its fall-through
        is a text input - so a connector inventing a type got a field the form
        collects wrongly, with nothing reporting it."""
        from app.services.rag.connectors import CONNECTOR_REGISTRY

        drawable = set(get_args(ConnectorFieldType))
        for name, cls in CONNECTOR_REGISTRY.items():
            for field, spec in cls.CONFIG_SCHEMA.items():
                assert spec.type in drawable, f"{name}.{field} declares {spec.type!r}"

    async def test_a_required_field_is_refused_by_the_label_the_form_shows(self):
        """The wizard marks the input this names, so it has to be the name the
        wizard drew - not the key underneath it."""
        refusal = await S3Connector().validate_config({})

        assert refusal is not None
        assert refusal.field == "bucket"
        assert refusal.message == "Missing required field: Bucket Name"

    def test_a_field_cannot_be_declared_without_the_label_the_form_draws(self):
        """`SyncSourceConfigureStep` renders `label` above the input, and only
        `validate_config` ever fell back to the key - so a connector omitting it
        got an unlabelled box on the form and a refusal that read fine."""
        with pytest.raises(ValidationError):
            ConnectorConfigField(type="string", required=True)

    def test_the_connector_listing_publishes_the_kind(self):
        listed = SyncSourceService.list_connectors()

        kinds = {item.type: item.secret_kind for item in listed.items}
        assert kinds["gdrive"] == "gcp_service_account"
        assert kinds["s3"] == "aws_credentials"


def test_there_is_no_second_encryption_mechanism():
    """`app/core/crypto.py` is gone, and this is the assertion that says so.

    It survived migration `0038` - which removed the other two deployment-wide
    Fernet keys - for one caller and one reason: an envelope needs an owner, and
    `sync_sources.organization_id` was nullable. Both halves are fixed, so the
    module has no reason to come back.
    """
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.core.crypto")
