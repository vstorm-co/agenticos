"""Service connections: who may register one, what one may be, and who may name it.

The rows decide where an organization's documents are sent for embedding or
OCR, so the questions worth a test are the refusals: a deployment-wide row from
somebody who is not the deployment's administrator, a provider that does not
fit the kind, a duplicate name, an edit to a row the caller may only see, and
a lookup that lands on another tenant's host.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.service_connection import ServiceConnection
from app.repositories import service_connection_repo
from app.schemas.service_connection import ServiceConnectionCreate, ServiceConnectionUpdate
from app.services.service_connection import ServiceConnectionService

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_REPO = "app.services.service_connection.service_connection_repo"


def _ctx(*, app_admin: bool = False, organization_id: uuid.UUID = _ORG) -> AuthContext:
    return AuthContext(
        user_id=uuid.uuid4(),
        organization_id=organization_id,
        role=OrgRoleName.OWNER.value,
        is_app_admin=app_admin,
    )


def _row(**overrides: object) -> MagicMock:
    row = MagicMock(
        id=uuid.uuid4(),
        organization_id=_ORG,
        kind="embedding",
        provider="ollama",
        base_url="http://ollama:11434/v1",
        is_active=True,
        secret_id=None,
        requires_key=False,
    )
    row.name = "GPU box"
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _service() -> ServiceConnectionService:
    return ServiceConnectionService(MagicMock(execute=AsyncMock()))


def _embedding(**overrides: object) -> ServiceConnectionCreate:
    return ServiceConnectionCreate(
        **{
            "name": "GPU box",
            "kind": "embedding",
            "provider": "ollama",
            "base_url": "http://ollama:11434/v1",
            **overrides,
        }
    )


class TestRegistering:
    async def test_an_organization_registers_its_own_embedding_server(self):
        with (
            patch(f"{_REPO}.get_by_name", new=AsyncMock(return_value=None)),
            patch(f"{_REPO}.create", new=AsyncMock(return_value=_row())) as create,
            patch("app.services.service_connection.record_audit", new=AsyncMock()) as audit,
        ):
            row = await _service().create(_ctx(), _embedding())

        assert row.provider == "ollama"
        assert create.call_args.kwargs["organization_id"] == _ORG
        assert audit.call_args.kwargs["details"] == {
            "name": "GPU box",
            "kind": "embedding",
            "provider": "ollama",
            "has_key": row.requires_key,
        }

    async def test_a_deployment_wide_row_is_the_administrators_alone(self):
        """Every organization may name it, so only the person running the
        deployment may say where the deployment's Ollama is."""
        with pytest.raises(AuthorizationError):
            await _service().create(_ctx(), _embedding(deployment_wide=True))

    async def test_the_administrator_registers_a_deployment_wide_row_with_no_owner(self):
        with (
            patch(f"{_REPO}.get_by_name", new=AsyncMock(return_value=None)),
            patch(
                f"{_REPO}.create", new=AsyncMock(return_value=_row(organization_id=None))
            ) as create,
            patch("app.services.service_connection.record_audit", new=AsyncMock()),
        ):
            await _service().create(_ctx(app_admin=True), _embedding(deployment_wide=True))

        assert create.call_args.kwargs["organization_id"] is None

    async def test_an_embedding_connection_must_name_a_provider_reached_through_a_connection(self):
        """The catalog is what says which models the server serves and at what
        width; a vendor with its own address is chosen on the collection instead."""
        with pytest.raises(BadRequestError) as refusal:
            await _service().create(_ctx(), _embedding(provider="openai"))

        assert refusal.value.details["fields"][0]["field"] == "provider"
        assert "ollama" in refusal.value.message
        assert "openai_compatible" in refusal.value.message

    async def test_an_ocr_server_is_reached_by_liteparse_and_nothing_else(self):
        with pytest.raises(BadRequestError) as refusal:
            await _service().create(_ctx(), _embedding(kind="ocr", provider="ollama"))

        assert refusal.value.details["fields"][0]["field"] == "provider"

    async def test_an_ocr_server_reached_by_liteparse_is_accepted(self):
        with (
            patch(f"{_REPO}.get_by_name", new=AsyncMock(return_value=None)),
            patch(
                f"{_REPO}.create",
                new=AsyncMock(return_value=_row(kind="ocr", provider="liteparse")),
            ) as create,
            patch("app.services.service_connection.record_audit", new=AsyncMock()),
        ):
            row = await _service().create(
                _ctx(), _embedding(kind="ocr", provider="liteparse", base_url="http://ocr:8000")
            )

        assert row.kind == "ocr"
        assert create.call_args.kwargs["provider"] == "liteparse"

    async def test_a_second_row_of_one_kind_by_the_same_name_is_refused(self):
        with (
            patch(f"{_REPO}.get_by_name", new=AsyncMock(return_value=_row())),
            pytest.raises(AlreadyExistsError),
        ):
            await _service().create(_ctx(), _embedding())

    @pytest.mark.parametrize(
        "address",
        [
            "ftp://ollama:11434",
            "not a url",
            "http://user:pw@ollama:11434/v1",
            "http://169.254.169.254",
        ],
    )
    def test_an_address_the_worker_must_not_fetch_is_refused_at_the_schema(self, address):
        """`ServiceAddress`, the same rule a sandbox host takes: the worker POSTs
        document pages to whatever is stored here."""
        with pytest.raises(ValidationError):
            _embedding(base_url=address)


_SECRET_ID = uuid.uuid4()
_KEY = "app.services.service_connection.organization_secret_repo.get"
_ACCESS = "app.services.service_connection.resolve_access"
_AUDIT = "app.services.service_connection.record_audit"


def _custom(**overrides: object) -> ServiceConnectionCreate:
    return _embedding(
        **{
            "provider": "openai_compatible",
            "base_url": "https://gateway.example.com/v1",
            "secret_id": _SECRET_ID,
            **overrides,
        }
    )


def _secret(**overrides: object) -> MagicMock:
    return MagicMock(**{"purpose": "openai_compatible", **overrides})


class TestTheKeyAConnectionCarries:
    @pytest.mark.security
    async def test_a_deployment_wide_connection_with_a_key_is_refused_on_secret_id(self):
        with (
            patch(f"{_REPO}.create", new=AsyncMock()) as create,
            pytest.raises(BadRequestError) as refusal,
        ):
            await _service().create(_ctx(app_admin=True), _custom(deployment_wide=True))

        assert refusal.value.details["fields"][0]["field"] == "secret_id"
        create.assert_not_called()

    @pytest.mark.security
    @pytest.mark.parametrize(("kind", "provider"), [("embedding", "ollama"), ("ocr", "liteparse")])
    async def test_a_key_on_an_ollama_or_ocr_connection_is_refused(self, kind, provider):
        with (
            patch(f"{_REPO}.create", new=AsyncMock()) as create,
            pytest.raises(BadRequestError) as refusal,
        ):
            await _service().create(
                _ctx(),
                _embedding(
                    kind=kind, provider=provider, base_url="http://ocr:8000", secret_id=_SECRET_ID
                ),
            )

        assert refusal.value.details["fields"][0]["field"] == "secret_id"
        create.assert_not_called()

    @pytest.mark.security
    async def test_a_key_for_another_purpose_is_refused(self):
        with (
            patch(_KEY, new=AsyncMock(return_value=_secret(purpose="openai"))),
            patch(_ACCESS, new=AsyncMock(return_value=True)),
            patch(f"{_REPO}.create", new=AsyncMock()) as create,
            pytest.raises(BadRequestError) as refusal,
        ):
            await _service().create(_ctx(), _custom())

        assert refusal.value.details["fields"][0]["field"] == "secret_id"
        assert refusal.value.details["purpose"] == "openai"
        create.assert_not_called()

    @pytest.mark.security
    @pytest.mark.parametrize("found", [None, "row"])
    async def test_a_key_the_caller_cannot_view_reads_as_not_in_the_vault(self, found):
        """A missing row and a row out of reach answer alike, so a refusal cannot
        enumerate another member's private secrets."""
        with (
            patch(_KEY, new=AsyncMock(return_value=None if found is None else _secret())),
            patch(_ACCESS, new=AsyncMock(return_value=False)),
            patch(f"{_REPO}.create", new=AsyncMock()) as create,
            pytest.raises(BadRequestError) as refusal,
        ):
            await _service().create(_ctx(), _custom())

        assert refusal.value.message == "That key is not in this organization's vault"
        assert refusal.value.details == {"secret_id": str(_SECRET_ID)}
        create.assert_not_called()

    async def test_an_openai_compatible_connection_with_its_orgs_key_is_created_keyed(self):
        keyed = _row(provider="openai_compatible", secret_id=_SECRET_ID, requires_key=True)
        with (
            patch(_KEY, new=AsyncMock(return_value=_secret())),
            patch(_ACCESS, new=AsyncMock(return_value=True)) as access,
            patch(f"{_REPO}.get_by_name", new=AsyncMock(return_value=None)),
            patch(f"{_REPO}.create", new=AsyncMock(return_value=keyed)) as create,
            patch(_AUDIT, new=AsyncMock()) as audit,
        ):
            await _service().create(_ctx(), _custom())

        assert create.call_args.kwargs["requires_key"] is True
        assert create.call_args.kwargs["secret_id"] == _SECRET_ID
        assert access.call_args.args[3] == "secrets:view"
        details = audit.call_args.kwargs["details"]
        assert details["has_key"] is True
        assert "base_url" not in details
        assert str(_SECRET_ID) not in str(details)

    async def test_an_openai_compatible_connection_without_a_key_is_keyless(self):
        with (
            patch(f"{_REPO}.get_by_name", new=AsyncMock(return_value=None)),
            patch(
                f"{_REPO}.create", new=AsyncMock(return_value=_row(provider="openai_compatible"))
            ) as create,
            patch(_AUDIT, new=AsyncMock()),
        ):
            await _service().create(_ctx(), _custom(secret_id=None))

        assert create.call_args.kwargs["requires_key"] is False
        assert create.call_args.kwargs["secret_id"] is None

    async def test_changing_the_key_checks_the_new_one_and_marks_the_row_keyed(self):
        row = _row(provider="openai_compatible")
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
            patch(_KEY, new=AsyncMock(return_value=_secret())) as lookup,
            patch(_ACCESS, new=AsyncMock(return_value=True)),
            patch(f"{_REPO}.update", new=AsyncMock(return_value=row)) as update,
            patch(_AUDIT, new=AsyncMock()),
        ):
            await _service().update(_ctx(), row.id, ServiceConnectionUpdate(secret_id=_SECRET_ID))

        assert lookup.call_args.args[1] == _SECRET_ID
        assert update.call_args.kwargs["update_data"] == {
            "secret_id": _SECRET_ID,
            "requires_key": True,
        }

    @pytest.mark.security
    async def test_a_new_key_of_the_wrong_purpose_is_refused_on_update(self):
        row = _row(provider="openai_compatible")
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
            patch(_KEY, new=AsyncMock(return_value=_secret(purpose="openrouter"))),
            patch(_ACCESS, new=AsyncMock(return_value=True)),
            patch(f"{_REPO}.update", new=AsyncMock()) as update,
            pytest.raises(BadRequestError),
        ):
            await _service().update(_ctx(), row.id, ServiceConnectionUpdate(secret_id=_SECRET_ID))

        update.assert_not_called()

    @pytest.mark.security
    async def test_clearing_the_key_of_a_keyed_connection_is_refused(self):
        row = _row(provider="openai_compatible", secret_id=_SECRET_ID, requires_key=True)
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
            patch(f"{_REPO}.update", new=AsyncMock()) as update,
            pytest.raises(BadRequestError) as refusal,
        ):
            await _service().update(_ctx(), row.id, ServiceConnectionUpdate(secret_id=None))

        assert refusal.value.details["fields"][0]["field"] == "secret_id"
        update.assert_not_called()

    async def test_clearing_nothing_from_a_keyless_connection_changes_nothing(self):
        row = _row()
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
            patch(f"{_REPO}.update", new=AsyncMock(return_value=row)) as update,
            patch(_AUDIT, new=AsyncMock()),
        ):
            await _service().update(_ctx(), row.id, ServiceConnectionUpdate(secret_id=None))

        update.assert_not_called()

    async def test_an_empty_edit_writes_no_audit_entry(self):
        row = _row()
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
            patch(f"{_REPO}.update", new=AsyncMock(return_value=row)),
            patch(_AUDIT, new=AsyncMock()) as audit,
        ):
            assert await _service().update(_ctx(), row.id, ServiceConnectionUpdate()) is row

        audit.assert_not_called()

    async def test_resending_the_same_key_is_a_no_op_that_needs_no_access_to_it(self):
        row = _row(provider="openai_compatible", secret_id=_SECRET_ID, requires_key=True)
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
            patch(f"{_REPO}.get_by_name", new=AsyncMock(return_value=None)),
            patch(_KEY, new=AsyncMock(return_value=_secret())) as lookup,
            patch(_ACCESS, new=AsyncMock(return_value=False)),
            patch(f"{_REPO}.update", new=AsyncMock(return_value=row)) as update,
            patch(_AUDIT, new=AsyncMock()) as audit,
        ):
            await _service().update(
                _ctx(), row.id, ServiceConnectionUpdate(name="Renamed", secret_id=_SECRET_ID)
            )

        lookup.assert_not_called()
        assert update.call_args.kwargs["update_data"] == {"name": "Renamed"}
        assert audit.call_args.kwargs["details"] == {"fields": ["name"]}

    @pytest.mark.security
    async def test_moving_a_keyed_connection_needs_access_to_its_key(self):
        """The key would be sent to the new host, so the editor must be able to view it."""
        row = _row(provider="openai_compatible", secret_id=_SECRET_ID, requires_key=True)
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
            patch(_KEY, new=AsyncMock(return_value=_secret())),
            patch(_ACCESS, new=AsyncMock(return_value=False)),
            patch(f"{_REPO}.update", new=AsyncMock()) as update,
            pytest.raises(BadRequestError) as refusal,
        ):
            await _service().update(
                _ctx(), row.id, ServiceConnectionUpdate(base_url="https://elsewhere.example.com/v1")
            )

        assert refusal.value.details == {"secret_id": str(_SECRET_ID)}
        update.assert_not_called()

    async def test_moving_a_keyed_connection_is_allowed_to_whoever_may_view_its_key(self):
        row = _row(provider="openai_compatible", secret_id=_SECRET_ID, requires_key=True)
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
            patch(_KEY, new=AsyncMock(return_value=_secret())),
            patch(_ACCESS, new=AsyncMock(return_value=True)),
            patch(f"{_REPO}.update", new=AsyncMock(return_value=row)) as update,
            patch(_AUDIT, new=AsyncMock()),
        ):
            await _service().update(
                _ctx(), row.id, ServiceConnectionUpdate(base_url="https://elsewhere.example.com/v1")
            )

        update.assert_awaited_once()

    @pytest.mark.security
    @pytest.mark.parametrize(
        "address",
        ["https://gw.example.com/v1?api-key=sk-123", "https://gw.example.com/v1?x=1#f"],
    )
    def test_a_query_string_is_refused_on_base_url(self, address):
        """A key pasted as `?api-key=` would be stored in the clear and echoed back."""
        with pytest.raises(ValidationError) as refusal:
            _embedding(base_url=address)
        assert refusal.value.errors()[0]["loc"] == ("base_url",)
        with pytest.raises(ValidationError):
            ServiceConnectionUpdate(base_url=address)

    @pytest.mark.security
    @pytest.mark.parametrize("field", ["provider", "kind"])
    def test_an_api_style_cannot_be_changed_after_creation(self, field):
        with pytest.raises(ValidationError):
            ServiceConnectionUpdate.model_validate({field: "openai_compatible"})

    async def test_editing_records_the_changed_field_names_only(self):
        row = _row()
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
            patch(f"{_REPO}.get_by_name", new=AsyncMock(return_value=None)),
            patch(f"{_REPO}.update", new=AsyncMock(return_value=row)),
            patch(_AUDIT, new=AsyncMock()) as audit,
        ):
            await _service().update(
                _ctx(),
                row.id,
                ServiceConnectionUpdate(name="Bigger box", base_url="http://other:11434/v1"),
            )

        assert audit.call_args.kwargs["action"] == "service_connection.updated"
        assert audit.call_args.kwargs["details"] == {"fields": ["base_url", "name"]}


class TestEditingAndRemoving:
    async def test_a_row_out_of_reach_is_not_found(self):
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await _service().update(_ctx(), uuid.uuid4(), ServiceConnectionUpdate(name="Renamed"))

    async def test_an_organization_edits_its_own_row(self):
        row = _row()
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
            patch(f"{_REPO}.get_by_name", new=AsyncMock(return_value=None)),
            patch(f"{_REPO}.update", new=AsyncMock(return_value=row)) as update,
            patch(_AUDIT, new=AsyncMock()),
        ):
            await _service().update(
                _ctx(), row.id, ServiceConnectionUpdate(name="Bigger box", is_active=False)
            )

        assert update.call_args.kwargs["update_data"] == {"name": "Bigger box", "is_active": False}

    async def test_a_visible_deployment_wide_row_is_not_an_editable_one(self):
        """Every organization sees the deployment's rows; none of them may move
        the deployment's Ollama."""
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=_row(organization_id=None))),
            pytest.raises(AuthorizationError),
        ):
            await _service().delete(_ctx(), uuid.uuid4())

    async def test_the_administrator_removes_a_deployment_wide_row(self):
        row = _row(organization_id=None)
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
            patch(f"{_REPO}.delete", new=AsyncMock()) as delete,
            patch("app.services.service_connection.record_audit", new=AsyncMock()) as audit,
        ):
            await _service().delete(_ctx(app_admin=True), row.id)

        delete.assert_awaited_once()
        assert audit.call_args.kwargs["organization_id"] is None

    async def test_saving_the_same_name_back_is_not_a_rename(self):
        """The duplicate check is for a name that moved, not for a form that
        posted every field it showed."""
        row = _row()
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
            patch(f"{_REPO}.get_by_name", new=AsyncMock()) as by_name,
            patch(f"{_REPO}.update", new=AsyncMock(return_value=row)),
            patch(_AUDIT, new=AsyncMock()),
        ):
            await _service().update(_ctx(), row.id, ServiceConnectionUpdate(name="GPU box"))

        by_name.assert_not_called()

    async def test_renaming_onto_a_taken_name_is_refused(self):
        row = _row()
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
            patch(f"{_REPO}.get_by_name", new=AsyncMock(return_value=_row())),
            pytest.raises(AlreadyExistsError),
        ):
            await _service().update(_ctx(), row.id, ServiceConnectionUpdate(name="Taken"))

    async def test_the_listing_is_what_the_organization_may_name(self):
        rows = [_row(), _row(organization_id=None)]
        with patch(f"{_REPO}.list_visible", new=AsyncMock(return_value=rows)) as listing:
            assert await _service().list_visible(_ctx()) == rows

        assert listing.call_args.kwargs["organization_id"] == _ORG


class _RecordingSession:
    """An `AsyncSession` stand-in that keeps the statements it was given."""

    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.statements: list[object] = []
        self.added: list[ServiceConnection] = []
        self.deleted: list[ServiceConnection] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self._results.pop(0) if self._results else MagicMock()

    def add(self, instance: ServiceConnection) -> None:
        self.added.append(instance)

    async def delete(self, instance: ServiceConnection) -> None:
        self.deleted.append(instance)

    async def flush(self) -> None:
        pass

    async def refresh(self, instance: ServiceConnection) -> None:
        pass


def _sql(session: _RecordingSession) -> str:
    return str(session.statements[-1].compile(dialect=postgresql.dialect()))


def _scalar(value: object):
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


class TestTheRepositoryScopesEveryLookup:
    """A repository's behaviour is the statement it builds, so these read it back.

    The predicate that matters is the owner: a service is a host documents are
    sent to, so a lookup without it would let one organization point its
    collections at another's server by guessing an id.
    """

    async def test_an_organization_sees_its_own_rows_and_the_deployments(self):
        session = _RecordingSession(_scalar(None))
        await service_connection_repo.get_visible(session, uuid.uuid4(), organization_id=_ORG)

        sql = _sql(session)
        assert "service_connections.organization_id = " in sql
        assert "service_connections.organization_id IS NULL" in sql

    async def test_a_caller_with_no_organization_sees_the_deployments_rows_alone(self):
        """An app-scoped collection: the deployment's Ollama, nobody else's."""
        session = _RecordingSession(_scalar(None))
        await service_connection_repo.get_visible(session, uuid.uuid4(), organization_id=None)

        sql = _sql(session)
        assert "service_connections.organization_id IS NULL" in sql
        assert "service_connections.organization_id = " not in sql

    async def test_the_listing_orders_by_kind_then_the_organizations_own_first(self):
        session = _RecordingSession(MagicMock(scalars=MagicMock(return_value=MagicMock(all=list))))
        await service_connection_repo.list_visible(session, organization_id=_ORG)

        assert "ORDER BY service_connections.kind" in _sql(session)

    async def test_a_name_is_looked_up_within_one_owner_and_one_kind(self):
        session = _RecordingSession(_scalar(None), _scalar(None))
        await service_connection_repo.get_by_name(
            session, organization_id=_ORG, kind="embedding", name="GPU box"
        )
        assert "service_connections.organization_id = " in _sql(session)

        await service_connection_repo.get_by_name(
            session, organization_id=None, kind="ocr", name="Scanner"
        )
        assert "service_connections.organization_id IS NULL" in _sql(session)

    async def test_create_update_and_delete_touch_the_session_as_repositories_do(self):
        session = _RecordingSession()
        row = await service_connection_repo.create(
            session,
            organization_id=_ORG,
            kind="embedding",
            provider="ollama",
            name="GPU box",
            base_url="http://ollama:11434/v1",
            created_by_user_id=None,
            secret_id=None,
            requires_key=False,
        )
        assert session.added == [row]
        assert row.is_active is None or row.is_active is True

        await service_connection_repo.update(session, row=row, update_data={"name": "Bigger box"})
        assert row.name == "Bigger box"

        await service_connection_repo.delete(session, row=row)
        assert session.deleted == [row]
