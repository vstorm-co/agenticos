"""Tests for the context-file service - storage and access for standing context.

The things worth guarding: a file that disappears after publish degrades the
agent rather than breaking the run, a file the runner could not reach themselves
is still read for a subject-less surface, a duplicate name is refused, and a
private file the caller cannot reach is a 404 rather than a 403.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.resource_grant import Visibility
from app.schemas.context import ContextFileUpdate
from app.services.context import ContextService, _summary

pytestmark = pytest.mark.anyio

CONTEXT_PATH = "app.services.context"


def _ctx(role: str = OrgRoleName.OWNER, *, org_id=None, user_id=None) -> AuthContext:
    return AuthContext(
        user_id=user_id or uuid.uuid4(),
        organization_id=org_id or uuid.uuid4(),
        role=role,
    )


def _file(name="glossary", *, mode="inject", enabled=True, ctx=None, owner_user_id=None):
    """A context-file row; given a `ctx` it is one the caller owns."""
    file = MagicMock()
    file.id = uuid.uuid4()
    file.organization_id = ctx.organization_id if ctx else uuid.uuid4()
    file.owner_user_id = owner_user_id or (ctx.user_id if ctx else uuid.uuid4())
    file.visibility = Visibility.PRIVATE.value
    file.name = name
    file.description = "What the words mean."
    file.content = "# Glossary\n\nSLA: service level agreement."
    file.format = "md"
    file.mode = mode
    file.enabled = enabled
    return file


def _service() -> ContextService:
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return ContextService(db)


class TestSummary:
    def test_the_summary_reports_the_body_as_a_byte_count(self):
        file = _file()
        file.content = "abcd€"  # € is three UTF-8 bytes
        summary = _summary(file)
        assert summary.size_bytes == 7
        assert summary.mode == "inject"
        assert summary.name == "glossary"


class TestGet:
    async def test_a_missing_file_is_not_found(self):
        service = _service()
        with (
            patch(f"{CONTEXT_PATH}.context_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await service.get(_ctx(), uuid.uuid4())

    async def test_a_file_the_caller_cannot_reach_is_not_found(self):
        """A private file is a 404, never a 403 - existence is not leaked."""
        service = _service()
        with (
            patch(f"{CONTEXT_PATH}.context_repo.get", new=AsyncMock(return_value=_file())),
            patch(f"{CONTEXT_PATH}.resolve_access", new=AsyncMock(return_value=False)),
            pytest.raises(NotFoundError),
        ):
            await service.get(_ctx(role=OrgRoleName.VIEWER), uuid.uuid4())

    async def test_a_reachable_file_is_returned(self):
        service = _service()
        ctx = _ctx()
        file = _file(ctx=ctx)
        with (
            patch(f"{CONTEXT_PATH}.context_repo.get", new=AsyncMock(return_value=file)),
            patch(f"{CONTEXT_PATH}.resolve_access", new=AsyncMock(return_value=True)),
        ):
            assert await service.get(ctx, file.id) is file


class TestResolveForAgent:
    async def test_an_agent_bound_to_no_files_asks_the_database_nothing(self):
        service = _service()
        with patch(f"{CONTEXT_PATH}.context_repo.get_many", new=AsyncMock()) as get_many:
            assert await service.resolve_for_agent(_ctx(), []) == []
            get_many.assert_not_called()

    async def test_a_deleted_file_degrades_the_agent_not_the_run(self):
        service = _service()
        present = _file("present")
        missing_id = uuid.uuid4()
        with patch(
            f"{CONTEXT_PATH}.context_repo.get_many",
            new=AsyncMock(return_value={present.id: present}),
        ):
            resolved = await service.resolve_for_agent(_ctx(), [present.id, missing_id])
        assert resolved == [present]

    async def test_disabled_files_are_skipped(self):
        service = _service()
        disabled = _file("disabled", enabled=False)
        with patch(
            f"{CONTEXT_PATH}.context_repo.get_many",
            new=AsyncMock(return_value={disabled.id: disabled}),
        ):
            assert await service.resolve_for_agent(_ctx(), [disabled.id]) == []

    async def test_a_run_with_no_subject_still_reads_the_agents_files(self):
        """A widget, an API key and a channel message run without a subject; the
        binding was checked at publish, so resolution here does not re-check."""
        service = _service()
        ctx = AuthContext.anonymous(uuid.uuid4())
        file = _file("glossary")
        with patch(
            f"{CONTEXT_PATH}.context_repo.get_many",
            new=AsyncMock(return_value={file.id: file}),
        ):
            assert await service.resolve_for_agent(ctx, [file.id]) == [file]

    async def test_binding_order_is_preserved(self):
        service = _service()
        first, second = _file("first"), _file("second")
        with patch(
            f"{CONTEXT_PATH}.context_repo.get_many",
            new=AsyncMock(return_value={first.id: first, second.id: second}),
        ):
            resolved = await service.resolve_for_agent(_ctx(), [second.id, first.id])
        assert resolved == [second, first]


class TestListing:
    async def test_a_role_that_reaches_everything_lists_without_a_grant_lookup(self):
        service = _service()
        mine = _file("mine")
        with (
            patch(f"{CONTEXT_PATH}.visible_resource_ids", new=AsyncMock(return_value=None)),
            patch(
                f"{CONTEXT_PATH}.context_repo.list_visible",
                new=AsyncMock(return_value=([mine], 1)),
            ) as list_visible,
            patch(f"{CONTEXT_PATH}.resource_grant_repo.list_shared_ids", new=AsyncMock()) as grants,
        ):
            result = await service.list_readable(_ctx())
        assert result.total == 1
        assert [item.name for item in result.items] == ["mine"]
        assert list_visible.call_args.kwargs["see_all"] is True
        grants.assert_not_called()

    async def test_a_scoped_role_lists_its_own_and_what_was_shared(self):
        service = _service()
        shared_id = uuid.uuid4()
        with (
            patch(
                f"{CONTEXT_PATH}.visible_resource_ids",
                new=AsyncMock(return_value=[shared_id]),
            ),
            patch(
                f"{CONTEXT_PATH}.context_repo.list_visible",
                new=AsyncMock(return_value=([], 0)),
            ) as list_visible,
        ):
            await service.list_readable(_ctx(role=OrgRoleName.MEMBER))
        assert list_visible.call_args.kwargs["see_all"] is False
        assert list_visible.call_args.kwargs["shared_ids"] == [shared_id]

    async def test_shared_with_me_asks_for_grants_even_when_the_role_reaches_all(self):
        """ "Shared with me" is a question about grants and visibility, not reach,
        so a role that sees everything still has to look its grants up."""
        service = _service()
        granted = uuid.uuid4()
        with (
            patch(f"{CONTEXT_PATH}.visible_resource_ids", new=AsyncMock(return_value=None)),
            patch(
                f"{CONTEXT_PATH}.resource_grant_repo.list_shared_ids",
                new=AsyncMock(return_value=[granted]),
            ) as grants,
            patch(
                f"{CONTEXT_PATH}.context_repo.list_visible",
                new=AsyncMock(return_value=([], 0)),
            ) as list_visible,
        ):
            await service.list_readable(_ctx(), shared_with_me=True)
        grants.assert_awaited_once()
        assert list_visible.call_args.kwargs["shared_ids"] == [granted]
        assert list_visible.call_args.kwargs["shared_with_me"] is True


class TestCreate:
    async def test_a_duplicate_name_is_refused(self):
        service = _service()
        with (
            patch(f"{CONTEXT_PATH}.context_repo.get_by_name", new=AsyncMock(return_value=_file())),
            pytest.raises(AlreadyExistsError),
        ):
            await service.create(_ctx(), name="glossary", description=None, content="x")

    async def test_creation_is_audited(self):
        service = _service()
        created = _file("glossary", mode="link")
        with (
            patch(f"{CONTEXT_PATH}.context_repo.get_by_name", new=AsyncMock(return_value=None)),
            patch(f"{CONTEXT_PATH}.context_repo.create", new=AsyncMock(return_value=created)),
            patch(f"{CONTEXT_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            result = await service.create(
                _ctx(),
                name="glossary",
                description="terms",
                content="body",
                content_format="txt",
                mode="link",
            )
        assert result is created
        assert audit.call_args.kwargs["action"] == "context.created"
        assert audit.call_args.kwargs["details"] == {"name": "glossary", "mode": "link"}


class TestUpdate:
    async def test_an_edit_records_the_fields_but_not_the_body(self):
        service = _service()
        ctx = _ctx()
        file = _file(ctx=ctx)
        with (
            patch(f"{CONTEXT_PATH}.context_repo.get", new=AsyncMock(return_value=file)),
            patch(f"{CONTEXT_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{CONTEXT_PATH}.context_repo.update", new=AsyncMock(return_value=file)),
            patch(f"{CONTEXT_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            await service.update(ctx, file.id, ContextFileUpdate(content="new", mode="link"))
        details = audit.call_args.kwargs["details"]
        assert details["fields"] == ["content", "mode"]
        # The submitted body is never audit data.
        assert "new" not in str(details)


class TestDelete:
    async def test_delete_clears_grants_then_removes_the_row(self):
        service = _service()
        ctx = _ctx()
        file = _file(ctx=ctx)
        with (
            patch(f"{CONTEXT_PATH}.context_repo.get", new=AsyncMock(return_value=file)),
            patch(f"{CONTEXT_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{CONTEXT_PATH}.resource_grant_repo.delete_for_resource", new=AsyncMock()
            ) as clear,
            patch(f"{CONTEXT_PATH}.context_repo.delete", new=AsyncMock()) as remove,
            patch(f"{CONTEXT_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            await service.delete(ctx, file.id)
        clear.assert_awaited_once()
        remove.assert_awaited_once()
        assert audit.call_args.kwargs["action"] == "context.deleted"
