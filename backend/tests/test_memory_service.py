"""Tests for the memory service - operator management of an agent's memory.

The things worth guarding: access rides on the parent agent and a denial is a
404 (existence is not leaked), an operator file is created trusted, editing an
agent-authored file does NOT make it trusted (promotion is separate), and
injectable content is only the shared operator rows.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.memory import MemoryOrigin
from app.schemas.memory import AgentMemoryFileCreate, AgentMemoryFileUpdate
from app.services.memory.facade import MemoryService, _summary

pytestmark = pytest.mark.anyio

MEMORY_PATH = "app.services.memory.facade"


def _ctx(role: str = OrgRoleName.OWNER, *, org_id=None, user_id=None) -> AuthContext:
    return AuthContext(
        user_id=user_id or uuid.uuid4(), organization_id=org_id or uuid.uuid4(), role=role
    )


def _file(name="prefs", *, origin=MemoryOrigin.AGENT.value, agent_id=None, scope_key=None):
    file = MagicMock()
    file.id = uuid.uuid4()
    file.agent_id = agent_id or uuid.uuid4()
    file.name = name
    file.description = "what they like"
    file.content = "likes tea"
    file.format = "md"
    file.kind = "note"
    file.origin = origin
    file.end_user_scope_key = scope_key
    return file


def _fact():
    fact = MagicMock()
    fact.id = uuid.uuid4()
    fact.agent_id = uuid.uuid4()
    fact.content = "likes tea"
    fact.end_user_scope_key = None
    fact.created_at = None
    return fact


def _service() -> MemoryService:
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return MemoryService(db)


def _reachable_agent():
    """`agent_repo.get` returns a row; `resolve_access` says yes."""
    return (
        patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=MagicMock())),
        patch(f"{MEMORY_PATH}.resolve_access", new=AsyncMock(return_value=True)),
    )


class TestSummary:
    def test_the_summary_reports_the_body_as_a_byte_count(self):
        file = _file()
        file.content = "abcd€"  # € is three UTF-8 bytes
        summary = _summary(file)
        assert summary.size_bytes == 7
        assert summary.origin == "agent"
        assert summary.name == "prefs"


class TestAgentAccess:
    async def test_a_missing_agent_is_not_found(self):
        service = _service()
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await service.list_files(_ctx(), agent_id=uuid.uuid4())

    async def test_an_agent_the_caller_cannot_reach_is_not_found(self):
        """A denial is a 404, never a 403 - existence is not leaked."""
        service = _service()
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=MagicMock())),
            patch(f"{MEMORY_PATH}.resolve_access", new=AsyncMock(return_value=False)),
            pytest.raises(NotFoundError),
        ):
            await service.list_files(_ctx(role=OrgRoleName.VIEWER), agent_id=uuid.uuid4())


class TestGet:
    async def test_a_missing_file_is_not_found(self):
        service = _service()
        with (
            patch(f"{MEMORY_PATH}.memory_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await service.get(_ctx(), uuid.uuid4())

    async def test_a_reachable_file_is_returned(self):
        service = _service()
        file = _file()
        get_agent, allow = _reachable_agent()
        with (
            patch(f"{MEMORY_PATH}.memory_repo.get", new=AsyncMock(return_value=file)),
            get_agent,
            allow,
        ):
            assert await service.get(_ctx(), file.id) is file


class TestListing:
    async def test_it_summarises_the_page_and_total(self):
        service = _service()
        get_agent, allow = _reachable_agent()
        with (
            get_agent,
            allow,
            patch(
                f"{MEMORY_PATH}.memory_repo.list_for_agent",
                new=AsyncMock(return_value=([_file("a"), _file("b")], 2)),
            ),
        ):
            result = await service.list_files(_ctx(), agent_id=uuid.uuid4())
        assert result.total == 2
        assert [item.name for item in result.items] == ["a", "b"]


class TestCreate:
    async def test_a_duplicate_name_in_the_partition_is_refused(self):
        service = _service()
        get_agent, allow = _reachable_agent()
        with (
            get_agent,
            allow,
            patch(f"{MEMORY_PATH}.memory_repo.get_by_name", new=AsyncMock(return_value=_file())),
            pytest.raises(AlreadyExistsError),
        ):
            await service.create(
                _ctx(), AgentMemoryFileCreate(agent_id=uuid.uuid4(), name="prefs", content="x")
            )

    async def test_an_operator_file_is_created_trusted_and_audited(self):
        service = _service()
        created = _file("policy", origin=MemoryOrigin.OPERATOR.value)
        get_agent, allow = _reachable_agent()
        with (
            get_agent,
            allow,
            patch(f"{MEMORY_PATH}.memory_repo.get_by_name", new=AsyncMock(return_value=None)),
            patch(
                f"{MEMORY_PATH}.memory_repo.create", new=AsyncMock(return_value=created)
            ) as create,
            patch(f"{MEMORY_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            result = await service.create(
                _ctx(), AgentMemoryFileCreate(agent_id=uuid.uuid4(), name="policy", content="body")
            )
        assert result is created
        assert create.call_args.kwargs["origin"] == MemoryOrigin.OPERATOR.value
        assert audit.call_args.kwargs["action"] == "memory.file.created"

    async def test_a_racing_duplicate_becomes_a_conflict_not_a_500(self):
        # The name check and the insert are not atomic; a concurrent create that
        # wins the race raises IntegrityError at the unique index, which the
        # service turns into the same AlreadyExistsError a sequential duplicate
        # gets, not a bare 500.
        service = _service()
        get_agent, allow = _reachable_agent()
        with (
            get_agent,
            allow,
            patch(f"{MEMORY_PATH}.memory_repo.get_by_name", new=AsyncMock(return_value=None)),
            patch(
                f"{MEMORY_PATH}.memory_repo.create",
                new=AsyncMock(side_effect=IntegrityError("insert", {}, Exception("dup"))),
            ),
            pytest.raises(AlreadyExistsError),
        ):
            await service.create(
                _ctx(), AgentMemoryFileCreate(agent_id=uuid.uuid4(), name="prefs", content="x")
            )


class TestUpdate:
    async def test_an_edit_records_the_fields_but_not_the_body_and_keeps_origin(self):
        service = _service()
        file = _file()
        get_agent, allow = _reachable_agent()
        with (
            patch(f"{MEMORY_PATH}.memory_repo.get", new=AsyncMock(return_value=file)),
            get_agent,
            allow,
            patch(f"{MEMORY_PATH}.memory_repo.update", new=AsyncMock(return_value=file)) as update,
            patch(f"{MEMORY_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            await service.update(_ctx(), file.id, AgentMemoryFileUpdate(content="new"))
        # The update dict carries no origin - editing never launders trust.
        assert "origin" not in update.call_args.kwargs["update_data"]
        details = audit.call_args.kwargs["details"]
        assert details["fields"] == ["content"]
        assert "new" not in str(details)


class TestPromote:
    async def test_promotion_sets_origin_operator_and_is_audited(self):
        service = _service()
        file = _file(origin=MemoryOrigin.AGENT.value)
        get_agent, allow = _reachable_agent()
        with (
            patch(f"{MEMORY_PATH}.memory_repo.get", new=AsyncMock(return_value=file)),
            get_agent,
            allow,
            patch(f"{MEMORY_PATH}.memory_repo.update", new=AsyncMock(return_value=file)) as update,
            patch(f"{MEMORY_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            await service.promote(_ctx(), file.id)
        assert update.call_args.kwargs["update_data"] == {"origin": MemoryOrigin.OPERATOR.value}
        assert audit.call_args.kwargs["action"] == "memory.file.promoted"


class TestDelete:
    async def test_delete_removes_the_row_and_audits(self):
        service = _service()
        file = _file()
        get_agent, allow = _reachable_agent()
        with (
            patch(f"{MEMORY_PATH}.memory_repo.get", new=AsyncMock(return_value=file)),
            get_agent,
            allow,
            patch(f"{MEMORY_PATH}.memory_repo.delete", new=AsyncMock()) as remove,
            patch(f"{MEMORY_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            await service.delete(_ctx(), file.id)
        remove.assert_awaited_once()
        assert audit.call_args.kwargs["action"] == "memory.file.deleted"


class TestFacts:
    async def test_listing_summarises_the_facts(self):
        service = _service()
        get_agent, allow = _reachable_agent()
        with (
            get_agent,
            allow,
            patch(
                f"{MEMORY_PATH}.memory_repo.list_facts",
                new=AsyncMock(return_value=([_fact(), _fact()], 2)),
            ),
        ):
            result = await service.list_facts(_ctx(), agent_id=uuid.uuid4())
        assert result.total == 2
        assert len(result.items) == 2

    async def test_a_missing_fact_is_not_found(self):
        service = _service()
        with (
            patch(f"{MEMORY_PATH}.memory_repo.get_fact", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await service.get_fact(_ctx(), uuid.uuid4())

    async def test_get_fact_returns_a_reachable_fact(self):
        service = _service()
        fact = _fact()
        get_agent, allow = _reachable_agent()
        with (
            patch(f"{MEMORY_PATH}.memory_repo.get_fact", new=AsyncMock(return_value=fact)),
            get_agent,
            allow,
        ):
            assert await service.get_fact(_ctx(), fact.id) is fact

    async def test_delete_removes_the_fact_and_audits(self):
        service = _service()
        fact = _fact()
        get_agent, allow = _reachable_agent()
        with (
            patch(f"{MEMORY_PATH}.memory_repo.get_fact", new=AsyncMock(return_value=fact)),
            get_agent,
            allow,
            patch(f"{MEMORY_PATH}.memory_repo.delete_fact", new=AsyncMock()) as remove,
            patch(f"{MEMORY_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            await service.delete_fact(_ctx(), fact.id)
        remove.assert_awaited_once()
        assert audit.call_args.kwargs["action"] == "memory.fact.deleted"


class TestScopedListing:
    async def test_per_user_files_listing_asks_the_repo_for_scoped_only(self):
        service = _service()
        get_agent, allow = _reachable_agent()
        with (
            get_agent,
            allow,
            patch(
                f"{MEMORY_PATH}.memory_repo.list_for_agent",
                new=AsyncMock(return_value=([], 0)),
            ) as listing,
        ):
            await service.list_files(_ctx(), agent_id=uuid.uuid4(), scoped_only=True)
        assert listing.await_args.kwargs["scoped_only"] is True

    async def test_per_user_facts_listing_asks_the_repo_for_scoped_only(self):
        service = _service()
        get_agent, allow = _reachable_agent()
        with (
            get_agent,
            allow,
            patch(
                f"{MEMORY_PATH}.memory_repo.list_facts",
                new=AsyncMock(return_value=([], 0)),
            ) as listing,
        ):
            await service.list_facts(_ctx(), agent_id=uuid.uuid4(), scoped_only=True)
        assert listing.await_args.kwargs["scoped_only"] is True


class TestClear:
    async def test_clear_removes_files_and_facts_and_audits_the_counts(self):
        service = _service()
        get_agent, allow = _reachable_agent()
        with (
            get_agent,
            allow,
            patch(
                f"{MEMORY_PATH}.memory_repo.delete_all_files", new=AsyncMock(return_value=3)
            ) as df,
            patch(
                f"{MEMORY_PATH}.memory_repo.delete_all_facts", new=AsyncMock(return_value=2)
            ) as dfa,
            patch(f"{MEMORY_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            await service.clear(_ctx(), uuid.uuid4())
        df.assert_awaited_once()
        dfa.assert_awaited_once()
        assert audit.call_args.kwargs["action"] == "memory.cleared"
        assert audit.call_args.kwargs["details"] == {"files": 3, "facts": 2}

    async def test_clear_facts_removes_only_facts(self):
        service = _service()
        get_agent, allow = _reachable_agent()
        with (
            get_agent,
            allow,
            patch(
                f"{MEMORY_PATH}.memory_repo.delete_all_facts", new=AsyncMock(return_value=5)
            ) as dfa,
            patch(f"{MEMORY_PATH}.memory_repo.delete_all_files", new=AsyncMock()) as df,
            patch(f"{MEMORY_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            await service.clear_facts(_ctx(), uuid.uuid4())
        dfa.assert_awaited_once()
        df.assert_not_awaited()
        assert audit.call_args.kwargs["action"] == "memory.facts.cleared"

    async def test_clearing_an_unreachable_agent_is_refused(self):
        service = _service()
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=None)),
            patch(f"{MEMORY_PATH}.memory_repo.delete_all_files", new=AsyncMock()) as df,
            pytest.raises(NotFoundError),
        ):
            await service.clear(_ctx(), uuid.uuid4())
        df.assert_not_awaited()
