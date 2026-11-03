"""A sync source records the knowledge base its caller resolved, and only that (#2551).

`SyncSourceService._target` is the one place a source's `knowledge_base_id` is
decided on every write path - create, clone, and a PATCH that moves it - so the
refusals live there: a name with no base, a base of another name, a base of
another organization (a personal base travels with its owner into every
organization they belong to), and a base deleted while the request waited for
its name. `_repoint` keeps a source where it is when the name it already has is
sent back.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.knowledge_base import KBScope
from app.schemas.sync_source import SyncSourceCreate, SyncSourceUpdate
from app.services import sync_source as sync_source_module
from app.services.sync_source import SyncSourceService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_ORG = uuid.uuid4()
_OTHER_ORG = uuid.uuid4()


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=_ORG, role=OrgRoleName.OWNER.value)


def _base(
    *,
    name: str = "handbook",
    organization_id: uuid.UUID | None = _ORG,
    scope: KBScope = KBScope.ORG,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), collection_name=name, organization_id=organization_id, scope=scope.value
    )


def _row(**fields: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": _ORG,
        "name": "Drive",
        "connector_type": "gdrive",
        "collection_name": "handbook",
        "knowledge_base_id": None,
        "config": {"folder_id": "abc"},
        "secret_id": None,
        "organizational_unit": None,
        "sync_mode": "new_only",
        "schedule_minutes": None,
        "is_active": True,
        "last_sync_at": None,
        "last_sync_status": None,
        "last_error": None,
        "created_at": None,
    }
    values.update(fields)
    return SimpleNamespace(**values)


@pytest.fixture
def repos(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The repositories the service writes through, and the lock it takes."""
    held = AsyncMock()
    still_there = AsyncMock(return_value=True)
    create = AsyncMock(side_effect=lambda _db, **kwargs: _row(**kwargs))
    update = AsyncMock(side_effect=lambda _db, source_id, **kwargs: _row(id=source_id, **kwargs))
    monkeypatch.setattr(sync_source_module, "hold_name", held)
    monkeypatch.setattr(sync_source_module.knowledge_base_repo, "hold_key_share", still_there)
    monkeypatch.setattr(sync_source_module.sync_source_repo, "create", create)
    monkeypatch.setattr(sync_source_module.sync_source_repo, "update", update)
    monkeypatch.setattr(sync_source_module, "record_audit", AsyncMock())
    return SimpleNamespace(held=held, still_there=still_there, create=create, update=update)


def _create(name: str | None = "handbook") -> SyncSourceCreate:
    return SyncSourceCreate(
        name="Drive", connector_type="gdrive", collection_name=name, config={"folder_id": "abc"}
    )


class TestCreatingASourceOnABase:
    async def test_it_records_the_base_under_the_names_lock(self, repos) -> None:
        base = _base()

        read = await SyncSourceService(MagicMock()).create_source(
            _create(), ctx=_ctx(), knowledge_base=base
        )

        assert read.knowledge_base_id == str(base.id)
        assert repos.create.await_args.kwargs["knowledge_base_id"] == base.id
        assert repos.held.await_args.args[2] == "handbook"

    async def test_an_unassigned_integration_records_no_base(self, repos) -> None:
        await SyncSourceService(MagicMock()).create_source(_create(None), ctx=_ctx())

        assert repos.create.await_args.kwargs["knowledge_base_id"] is None
        repos.held.assert_not_awaited()

    @pytest.mark.parametrize(
        "base",
        [None, _base(name="manuals"), _base(organization_id=_OTHER_ORG, scope=KBScope.PERSONAL)],
        ids=["no base", "a base of another name", "another organization's personal base"],
    )
    async def test_a_name_without_its_own_organizations_base_is_refused(
        self, repos, base: SimpleNamespace | None
    ) -> None:
        """The last is the owner of a personal base created in org A adding a source
        to it while acting in org B: B's credential would write into A's tenant."""
        with pytest.raises(BadRequestError):
            await SyncSourceService(MagicMock()).create_source(
                _create(), ctx=_ctx(), knowledge_base=base
            )

        repos.create.assert_not_awaited()

    async def test_an_app_base_belongs_to_every_organization(self, repos) -> None:
        base = _base(organization_id=None, scope=KBScope.APP)

        await SyncSourceService(MagicMock()).create_source(
            _create(), ctx=_ctx(), knowledge_base=base
        )

        assert repos.create.await_args.kwargs["knowledge_base_id"] == base.id

    async def test_a_base_deleted_while_waiting_for_its_name_is_not_found(self, repos) -> None:
        repos.still_there.return_value = False

        with pytest.raises(NotFoundError):
            await SyncSourceService(MagicMock()).create_source(
                _create(), ctx=_ctx(), knowledge_base=_base()
            )

        repos.create.assert_not_awaited()


class TestPatchingASourcesCollection:
    async def _patch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        existing: SimpleNamespace,
        name: str | None,
        base: SimpleNamespace | None,
    ) -> None:
        service = SyncSourceService(MagicMock())
        monkeypatch.setattr(service, "get_source", AsyncMock(return_value=existing))
        await service.update_source(
            str(existing.id),
            SyncSourceUpdate(collection_name=name, schedule_minutes=60),
            ctx=_ctx(),
            knowledge_base=base,
        )

    async def test_the_name_it_has_is_no_move(self, monkeypatch, repos) -> None:
        recorded = uuid.uuid4()
        existing = _row(knowledge_base_id=recorded, sync_state={"version": "v"})

        await self._patch(monkeypatch, existing, "handbook", None)

        written = repos.update.await_args.kwargs
        assert "collection_name" not in written and "knowledge_base_id" not in written
        assert "sync_state" not in written
        assert written["schedule_minutes"] == 60

    async def test_a_move_records_the_new_base_and_forgets_the_last_run(
        self, monkeypatch, repos
    ) -> None:
        """The last clean run filled the other base; stopping early on it would
        leave this one empty."""
        existing = _row(knowledge_base_id=uuid.uuid4())
        manuals = _base(name="manuals")

        await self._patch(monkeypatch, existing, "manuals", manuals)

        written = repos.update.await_args.kwargs
        assert written["collection_name"] == "manuals"
        assert written["knowledge_base_id"] == manuals.id
        assert written["sync_state"] is None

    async def test_a_detach_records_no_base(self, monkeypatch, repos) -> None:
        existing = _row(knowledge_base_id=uuid.uuid4())

        await self._patch(monkeypatch, existing, None, None)

        written = repos.update.await_args.kwargs
        assert written["collection_name"] is None and written["knowledge_base_id"] is None

    async def test_a_source_with_no_base_is_pointed_at_one_again(self, monkeypatch, repos) -> None:
        existing = _row(knowledge_base_id=None)
        base = _base()

        await self._patch(monkeypatch, existing, "handbook", base)

        assert repos.update.await_args.kwargs["knowledge_base_id"] == base.id
