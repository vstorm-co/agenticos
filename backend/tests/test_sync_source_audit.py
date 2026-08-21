"""A sync source's life is recorded, because the row *is* an access decision.

#983. A source binds a credential to a collection, and access to what it
ingests is decided at the collection - so the row decides who ends up able to
read whatever that credential can reach
(`docs/file-processing.md#who-ends-up-able-to-read-what-a-source-ingested`).
Nothing wrote an audit entry for creating, repointing or deleting one, so a
broad credential pointed at an `org` collection weeks ago had no answer to who
did it, when, or whether it had originally been pointed somewhere narrower.

Two things every test here holds shut, and the second is why the first is not
enough:

* **The entry exists**, on all four paths that write such a row - create,
  clone, update, delete.
* **`details` carries the decision and not the payload.** The connector, the
  collection and the secret's *id*; never the config document, which is a place
  a credential has been posted before (#937), and never the row.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.permissions import AuthContext, OrgRoleName
from app.schemas.sync_source import SyncSourceClone, SyncSourceCreate, SyncSourceUpdate
from app.services import sync_source as sync_source_module
from app.services.sync_source import SyncSourceService

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_CALLER = uuid.uuid4()
_SECRET = uuid.uuid4()

# The value a reader of the trail must never be handed back: `config` is what a
# connector needs to *find* the documents, and the field names in it have held a
# credential within this repository's memory.
_CONFIG = {"folder_id": "1AbC_-secret-looking-folder"}


def _ctx(*, anonymous: bool = False) -> AuthContext:
    if anonymous:
        return AuthContext.anonymous(_ORG)
    return AuthContext(user_id=_CALLER, organization_id=_ORG, role=OrgRoleName.OWNER.value)


def _row(**overrides) -> SimpleNamespace:
    """A stored source. `SimpleNamespace` because `name` is MagicMock's own kwarg."""
    fields = {
        "id": uuid.uuid4(),
        "organization_id": _ORG,
        "name": "Legal docs",
        "connector_type": "gdrive",
        "collection_name": "legal",
        "config": dict(_CONFIG),
        "secret_id": _SECRET,
        "sync_mode": "new_only",
        "schedule_minutes": None,
        "is_active": True,
        "last_sync_at": None,
        "last_sync_status": None,
        "last_error": None,
        "created_at": None,
    }
    return SimpleNamespace(**{**fields, **overrides})


def _service(monkeypatch: pytest.MonkeyPatch, *, stored=None, updated=None) -> AsyncMock:
    """The real service with its repositories and its checks mocked at the edge.

    Returns the `record_audit` mock, because that is what every test here reads.
    The credential check is `resolve_access`, which has its own tests and needs a
    real grant table; what matters here is only that a source reaches the trail.
    """
    monkeypatch.setattr(sync_source_module, "resolve_access", AsyncMock(return_value=True))
    monkeypatch.setattr(
        sync_source_module.organization_secret_repo,
        "get",
        AsyncMock(
            return_value=SimpleNamespace(id=_SECRET, kind="gcp_service_account", hint="9f3c")
        ),
    )
    monkeypatch.setattr(
        sync_source_module.sync_source_repo,
        "create",
        AsyncMock(
            side_effect=lambda db, **kwargs: _row(
                organization_id=kwargs["organization_id"],
                name=kwargs["name"],
                collection_name=kwargs["collection_name"],
                config=kwargs["config"],
                secret_id=kwargs["secret_id"],
            )
        ),
    )
    monkeypatch.setattr(
        sync_source_module.sync_source_repo, "get_by_id", AsyncMock(return_value=stored)
    )
    monkeypatch.setattr(
        sync_source_module.sync_source_repo, "update", AsyncMock(return_value=updated)
    )
    monkeypatch.setattr(sync_source_module.sync_source_repo, "delete", AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr(sync_source_module, "record_audit", audit)
    return audit


def _create(**overrides) -> SyncSourceCreate:
    return SyncSourceCreate(
        name="Legal docs",
        connector_type="gdrive",
        collection_name="legal",
        config=dict(_CONFIG),
        secret_id=_SECRET,
        **overrides,
    )


def _entry(audit: AsyncMock) -> dict:
    assert audit.await_count == 1, f"expected one audit entry, got {audit.await_count}"
    return audit.await_args.kwargs


class TestEveryWritePathLeavesAnEntry:
    async def test_creating_a_source_names_the_actor_the_collection_and_the_secret(
        self, monkeypatch
    ):
        audit = _service(monkeypatch)

        await SyncSourceService(MagicMock()).create_source(_create(), ctx=_ctx())

        entry = _entry(audit)
        assert entry["action"] == "sync_source.created"
        assert entry["actor_user_id"] == _CALLER
        assert entry["organization_id"] == _ORG
        assert entry["target_type"] == "sync_source"
        assert entry["details"]["collection_name"] == "legal"
        assert entry["details"]["secret_id"] == str(_SECRET)
        assert entry["details"]["connector_type"] == "gdrive"

    async def test_a_clone_says_which_row_it_was_cloned_from(self, monkeypatch):
        """The decision most easily missed: the credential is unchanged and its
        audience is not. A clone references the same secret and names a different
        collection, so it widens who can read what that credential reaches
        without touching the credential at all."""
        stored = _row()
        audit = _service(monkeypatch, stored=stored)

        await SyncSourceService(MagicMock()).clone_source(
            str(stored.id), SyncSourceClone(collection_name="everyone"), ctx=_ctx()
        )

        entry = _entry(audit)
        assert entry["action"] == "sync_source.created"
        assert entry["details"]["cloned_from"] == str(stored.id)
        assert entry["details"]["collection_name"] == "everyone"
        assert entry["details"]["secret_id"] == str(_SECRET)

    async def test_an_update_names_the_fields_and_not_their_values(self, monkeypatch):
        stored = _row()
        audit = _service(
            monkeypatch, stored=stored, updated=_row(id=stored.id, sync_mode="update_only")
        )

        await SyncSourceService(MagicMock()).update_source(
            str(stored.id), SyncSourceUpdate(sync_mode="update_only"), ctx=_ctx()
        )

        entry = _entry(audit)
        assert entry["action"] == "sync_source.updated"
        assert entry["details"]["fields"] == ["sync_mode"]

    async def test_repointing_a_source_says_where_it_used_to_point(self, monkeypatch):
        """A rename and a repoint are both `updated`, and only one of them
        changes who can read what has already been ingested. The entry has to
        say which happened, or the trail answers "something changed"."""
        stored = _row(collection_name="my_notes")
        audit = _service(
            monkeypatch, stored=stored, updated=_row(id=stored.id, collection_name="everyone")
        )

        await SyncSourceService(MagicMock()).update_source(
            str(stored.id), SyncSourceUpdate(collection_name="everyone"), ctx=_ctx()
        )

        entry = _entry(audit)
        assert entry["details"]["previous_collection_name"] == "my_notes"
        assert entry["details"]["collection_name"] == "everyone"

    async def test_a_rename_records_no_previous_collection(self, monkeypatch):
        stored = _row()
        audit = _service(
            monkeypatch, stored=stored, updated=_row(id=stored.id, name="Legal docs (EU)")
        )

        await SyncSourceService(MagicMock()).update_source(
            str(stored.id), SyncSourceUpdate(name="Legal docs (EU)"), ctx=_ctx()
        )

        assert "previous_collection_name" not in _entry(audit)["details"]

    async def test_deleting_a_source_records_what_was_deleted(self, monkeypatch):
        stored = _row()
        audit = _service(monkeypatch, stored=stored)

        await SyncSourceService(MagicMock()).delete_source(str(stored.id), ctx=_ctx())

        entry = _entry(audit)
        assert entry["action"] == "sync_source.deleted"
        assert entry["target_id"] == str(stored.id)
        assert entry["details"]["collection_name"] == "legal"
        assert entry["details"]["secret_id"] == str(_SECRET)

    async def test_a_source_that_does_not_exist_leaves_no_entry(self, monkeypatch):
        audit = _service(monkeypatch, stored=None)

        with pytest.raises(sync_source_module.NotFoundError):
            await SyncSourceService(MagicMock()).delete_source(str(uuid.uuid4()), ctx=_ctx())

        assert audit.await_count == 0


class TestWhatMayNotReachTheTrail:
    @pytest.mark.parametrize(
        "act",
        [
            pytest.param("create", id="create"),
            pytest.param("clone", id="clone"),
            pytest.param("update", id="update"),
            pytest.param("delete", id="delete"),
        ],
    )
    async def test_no_config_value_reaches_details(self, monkeypatch, act: str):
        """`details` is a stored JSONB column with a longer life than a response
        body, and the rule that governs a refusal governs it too: the field that
        explains the decision, never the payload that was submitted (#412)."""
        stored = _row()
        audit = _service(monkeypatch, stored=stored, updated=_row(id=stored.id))
        service = SyncSourceService(MagicMock())

        if act == "create":
            await service.create_source(_create(), ctx=_ctx())
        elif act == "clone":
            await service.clone_source(
                str(stored.id), SyncSourceClone(collection_name="everyone"), ctx=_ctx()
            )
        elif act == "update":
            await service.update_source(
                str(stored.id), SyncSourceUpdate(config=dict(_CONFIG)), ctx=_ctx()
            )
        else:
            await service.delete_source(str(stored.id), ctx=_ctx())

        written = json.dumps(_entry(audit)["details"])
        assert _CONFIG["folder_id"] not in written
        assert "folder_id" not in written


class TestAnOperatorCommandStillLeavesOne:
    async def test_a_context_with_no_subject_records_no_actor_rather_than_refusing(
        self, monkeypatch
    ):
        """`rag-source-add` and `rag-source-remove` have nobody at a keyboard,
        and `ctx.subject_id` raises for such a context - so reading it here
        would have turned two working operator commands into an
        `AuthorizationError`. An entry naming no actor is a truer record of the
        removal than no entry at all, and the action is what tells it from the
        approval expiry sweep, the only other writer that names nobody."""
        stored = _row()
        audit = _service(monkeypatch, stored=stored)

        await SyncSourceService(MagicMock()).delete_source(str(stored.id), ctx=_ctx(anonymous=True))

        entry = _entry(audit)
        assert entry["actor_user_id"] is None
        assert entry["action"] == "sync_source.deleted"
        assert entry["organization_id"] == _ORG
