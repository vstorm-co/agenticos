"""Local services: who may register one, what one may be, and who may name it.

The rows decide where an organization's documents are sent for embedding or
OCR, so the questions worth a test are the refusals: a deployment-wide row from
somebody who is not the deployment's administrator, a provider that does not
fit the kind, a duplicate name, an edit to a row the caller may only see, and
a lookup that lands on another tenant's host.
"""

from __future__ import annotations

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
from app.db.models.local_service import LocalService
from app.repositories import local_service_repo
from app.schemas.local_service import LocalServiceCreate, LocalServiceUpdate
from app.services.local_service import LocalServiceService

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_REPO = "app.services.local_service.local_service_repo"


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
    )
    row.name = "GPU box"
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _service() -> LocalServiceService:
    return LocalServiceService(MagicMock(execute=AsyncMock()))


def _embedding(**overrides: object) -> LocalServiceCreate:
    return LocalServiceCreate(
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
            patch("app.services.local_service.record_audit", new=AsyncMock()) as audit,
        ):
            row = await _service().create(_ctx(), _embedding())

        assert row.provider == "ollama"
        assert create.call_args.kwargs["organization_id"] == _ORG
        assert audit.call_args.kwargs["details"] == {
            "name": "GPU box",
            "kind": "embedding",
            "provider": "ollama",
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
            patch("app.services.local_service.record_audit", new=AsyncMock()),
        ):
            await _service().create(_ctx(app_admin=True), _embedding(deployment_wide=True))

        assert create.call_args.kwargs["organization_id"] is None

    async def test_an_embedding_service_must_name_a_keyless_catalog_provider(self):
        """The catalog is what says which models the server serves and at what
        width; a vendor that takes a key is chosen on the collection instead."""
        with pytest.raises(BadRequestError) as refusal:
            await _service().create(_ctx(), _embedding(provider="openai"))

        assert refusal.value.details["fields"][0]["field"] == "provider"
        assert "ollama" in refusal.value.message

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
            patch("app.services.local_service.record_audit", new=AsyncMock()),
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


class TestEditingAndRemoving:
    async def test_a_row_out_of_reach_is_not_found(self):
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await _service().update(_ctx(), uuid.uuid4(), LocalServiceUpdate(name="Renamed"))

    async def test_an_organization_edits_its_own_row(self):
        row = _row()
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
            patch(f"{_REPO}.get_by_name", new=AsyncMock(return_value=None)),
            patch(f"{_REPO}.update", new=AsyncMock(return_value=row)) as update,
        ):
            await _service().update(
                _ctx(), row.id, LocalServiceUpdate(name="Bigger box", is_active=False)
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
            patch("app.services.local_service.record_audit", new=AsyncMock()) as audit,
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
        ):
            await _service().update(_ctx(), row.id, LocalServiceUpdate(name="GPU box"))

        by_name.assert_not_called()

    async def test_renaming_onto_a_taken_name_is_refused(self):
        row = _row()
        with (
            patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
            patch(f"{_REPO}.get_by_name", new=AsyncMock(return_value=_row())),
            pytest.raises(AlreadyExistsError),
        ):
            await _service().update(_ctx(), row.id, LocalServiceUpdate(name="Taken"))

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
        self.added: list[LocalService] = []
        self.deleted: list[LocalService] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self._results.pop(0) if self._results else MagicMock()

    def add(self, instance: LocalService) -> None:
        self.added.append(instance)

    async def delete(self, instance: LocalService) -> None:
        self.deleted.append(instance)

    async def flush(self) -> None:
        pass

    async def refresh(self, instance: LocalService) -> None:
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
        await local_service_repo.get_visible(session, uuid.uuid4(), organization_id=_ORG)

        sql = _sql(session)
        assert "local_services.organization_id = " in sql
        assert "local_services.organization_id IS NULL" in sql

    async def test_a_caller_with_no_organization_sees_the_deployments_rows_alone(self):
        """An app-scoped collection: the deployment's Ollama, nobody else's."""
        session = _RecordingSession(_scalar(None))
        await local_service_repo.get_visible(session, uuid.uuid4(), organization_id=None)

        sql = _sql(session)
        assert "local_services.organization_id IS NULL" in sql
        assert "local_services.organization_id = " not in sql

    async def test_the_listing_orders_by_kind_then_the_organizations_own_first(self):
        session = _RecordingSession(MagicMock(scalars=MagicMock(return_value=MagicMock(all=list))))
        await local_service_repo.list_visible(session, organization_id=_ORG)

        assert "ORDER BY local_services.kind" in _sql(session)

    async def test_a_name_is_looked_up_within_one_owner_and_one_kind(self):
        session = _RecordingSession(_scalar(None), _scalar(None))
        await local_service_repo.get_by_name(
            session, organization_id=_ORG, kind="embedding", name="GPU box"
        )
        assert "local_services.organization_id = " in _sql(session)

        await local_service_repo.get_by_name(
            session, organization_id=None, kind="ocr", name="Scanner"
        )
        assert "local_services.organization_id IS NULL" in _sql(session)

    async def test_create_update_and_delete_touch_the_session_as_repositories_do(self):
        session = _RecordingSession()
        row = await local_service_repo.create(
            session,
            organization_id=_ORG,
            kind="embedding",
            provider="ollama",
            name="GPU box",
            base_url="http://ollama:11434/v1",
            created_by_user_id=None,
        )
        assert session.added == [row]
        assert row.is_active is None or row.is_active is True

        await local_service_repo.update(session, row=row, update_data={"name": "Bigger box"})
        assert row.name == "Bigger box"

        await local_service_repo.delete(session, row=row)
        assert session.deleted == [row]
