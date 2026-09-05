"""Tests for the memory service - operator management of an agent's memory.

The things worth guarding: access rides on the parent agent and a denial is a
404 (existence is not leaked), an operator file is created trusted, editing an
agent-authored file does NOT make it trusted (promotion is separate), and
injectable content is only the shared operator rows.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.agents.capabilities.budget import BudgetExceeded, BudgetScope, SpendEntry, SpendLedger
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.memory import MemoryOrigin
from app.schemas.memory import (
    AgentMemoryFactCreate,
    AgentMemoryFileCreate,
    AgentMemoryFileUpdate,
)
from app.services.memory.facade import (
    MemoryService,
    _record_operator_embedding_spend,
    _summary,
)

pytestmark = pytest.mark.anyio

MEMORY_PATH = "app.services.memory.facade"


def _ctx(role: str = OrgRoleName.OWNER, *, org_id=None, user_id=None) -> AuthContext:
    return AuthContext(
        user_id=user_id or uuid.uuid4(), organization_id=org_id or uuid.uuid4(), role=role
    )


def _file(name="prefs", *, origin=MemoryOrigin.AGENT.value, agent_id=None, owner_key=None):
    file = MagicMock()
    file.id = uuid.uuid4()
    file.agent_id = agent_id or uuid.uuid4()
    file.name = name
    file.description = "what they like"
    file.content = "likes tea"
    file.format = "md"
    file.kind = "note"
    file.origin = origin
    file.owner_key = owner_key
    return file


def _fact():
    fact = MagicMock()
    fact.id = uuid.uuid4()
    fact.agent_id = uuid.uuid4()
    fact.content = "likes tea"
    fact.origin = MemoryOrigin.AGENT.value
    fact.owner_key = None
    fact.created_at = None
    return fact


def _service() -> MemoryService:
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return MemoryService(db)


def _agent(*, draft_spec=None, current_version_id=None):
    """An agent row as the mem0 guard reads it: a draft spec, and what is published.

    `current_version_id=None` is "nothing published", which is what keeps the guard
    from reaching for a version on a mocked session; a test about the published spec
    sets it and patches `agent_repo.get_version`.
    """
    return MagicMock(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        draft_spec=draft_spec if draft_spec is not None else {},
        current_version_id=current_version_id,
    )


def _memory_spec(backend: str) -> dict:
    return {"capabilities": [{"id": "memory", "enabled": True, "config": {"backend": backend}}]}


def _version(spec: dict):
    """A published version row. `spec` is set after construction: `MagicMock(spec=...)`
    is the mock's own spec argument, not an attribute."""
    version = MagicMock()
    version.spec = spec
    return version


def _reachable_agent():
    """`agent_repo.get` returns a row; `resolve_access` says yes."""
    return (
        patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
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
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
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

    async def test_list_files_resolves_person_stores_to_member_emails(self):
        service = _service()
        get_agent, allow = _reachable_agent()
        known, emailless = uuid.uuid4(), uuid.uuid4()
        files = [
            _file("company", owner_key=None),
            _file("prefs", owner_key=f"person:{known}"),
            _file("ghost", owner_key=f"person:{emailless}"),
        ]
        with (
            get_agent,
            allow,
            patch(
                f"{MEMORY_PATH}.memory_repo.list_for_agent",
                new=AsyncMock(return_value=(files, 3)),
            ),
            patch(
                f"{MEMORY_PATH}.member_repo.get_emails_for_users",
                new=AsyncMock(return_value={known: "dana@acme.example", emailless: None}),
            ) as emails,
        ):
            result = await service.list_files(_ctx(), agent_id=uuid.uuid4())
        # The shared store and a member with no email carry no label; a resolvable
        # member shows their email.
        labels = {item.name: item.owner_label for item in result.items}
        assert labels == {"company": None, "prefs": "dana@acme.example", "ghost": None}
        # Only the per-user ids are looked up, and the lookup is org-scoped.
        assert set(emails.await_args.kwargs["user_ids"]) == {known, emailless}

    async def test_list_files_leaves_an_unresolvable_owner_key_unlabelled(self):
        service = _service()
        get_agent, allow = _reachable_agent()
        # A channel account and a malformed user key both parse to no member id, so
        # the lookup is skipped and the console falls back to the raw key.
        files = [_file("c", owner_key="person:chan:abc"), _file("b", owner_key="person:not-a-uuid")]
        with (
            get_agent,
            allow,
            patch(
                f"{MEMORY_PATH}.memory_repo.list_for_agent",
                new=AsyncMock(return_value=(files, 2)),
            ),
            patch(f"{MEMORY_PATH}.member_repo.get_emails_for_users", new=AsyncMock()) as emails,
        ):
            result = await service.list_files(_ctx(), agent_id=uuid.uuid4())
        assert all(item.owner_label is None for item in result.items)
        emails.assert_not_awaited()

    async def test_list_facts_resolves_the_owner_label(self):
        service = _service()
        get_agent, allow = _reachable_agent()
        uid = uuid.uuid4()
        fact = _fact()
        fact.owner_key = f"person:{uid}"
        fact.created_at = None
        with (
            get_agent,
            allow,
            patch(
                f"{MEMORY_PATH}.memory_repo.list_facts",
                new=AsyncMock(return_value=([fact], 1)),
            ),
            patch(
                f"{MEMORY_PATH}.member_repo.get_emails_for_users",
                new=AsyncMock(return_value={uid: "dana@acme.example"}),
            ),
        ):
            result = await service.list_facts(_ctx(), agent_id=uuid.uuid4())
        assert result.items[0].owner_label == "dana@acme.example"


class TestCreate:
    async def test_a_duplicate_name_in_the_store_is_refused(self):
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
        # A concurrent create that wins the race raises IntegrityError at the unique
        # index, which becomes the same AlreadyExistsError a sequential duplicate gets.
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


class TestCreateAuthorizesByOwner:
    """The store decides the permission: the organization's, a room's and another
    person's are operator acts (`AGENTS_EDIT`); one's own needs only `AGENTS_VIEW`,
    so a member keeps their own notes without touching anything else. The own-key
    is `person_owner_key(caller)`, matching the runtime derivation exactly."""

    def _perm(self, resolve_mock) -> Perm:
        # resolve_access(db, ctx, agent, perm, resource_type=AGENT) - perm is 4th positional.
        return resolve_mock.call_args.args[3]

    def _create_patches(self, resolve: AsyncMock):
        return (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=resolve),
            patch(f"{MEMORY_PATH}.memory_repo.get_by_name", new=AsyncMock(return_value=None)),
            patch(f"{MEMORY_PATH}.memory_repo.create", new=AsyncMock(return_value=_file())),
            patch(f"{MEMORY_PATH}.record_audit", new=AsyncMock()),
        )

    async def test_the_organization_store_needs_edit(self):
        service = _service()
        resolve = AsyncMock(return_value=True)
        get_agent, allow, by_name, create, audit = self._create_patches(resolve)
        with get_agent, allow, by_name, create, audit:
            await service.create(_ctx(), AgentMemoryFileCreate(agent_id=uuid.uuid4(), name="p"))
        assert self._perm(resolve) == Perm.AGENTS_EDIT

    async def test_ones_own_store_needs_only_view(self):
        service = _service()
        me = uuid.uuid4()
        resolve = AsyncMock(return_value=True)
        get_agent, allow, by_name, create, audit = self._create_patches(resolve)
        with get_agent, allow, by_name, create, audit:
            await service.create(
                _ctx(user_id=me),
                AgentMemoryFileCreate(agent_id=uuid.uuid4(), name="p", owner_key=f"person:{me}"),
            )
        assert self._perm(resolve) == Perm.AGENTS_VIEW

    async def test_another_persons_personal_needs_edit(self):
        service = _service()
        resolve = AsyncMock(return_value=True)
        get_agent, allow, by_name, create, audit = self._create_patches(resolve)
        with get_agent, allow, by_name, create, audit:
            await service.create(
                _ctx(user_id=uuid.uuid4()),
                AgentMemoryFileCreate(
                    agent_id=uuid.uuid4(), name="p", owner_key=f"person:{uuid.uuid4()}"
                ),
            )
        assert self._perm(resolve) == Perm.AGENTS_EDIT

    async def test_a_member_creates_only_their_own_store(self):
        """The refusal that makes the relaxation safe: a caller who has view but
        not edit may create their own personal file, and nothing else."""
        service = _service()
        me = uuid.uuid4()

        async def _view_only(_db, _ctx, _agent, perm, **_kw) -> bool:
            return perm == Perm.AGENTS_VIEW

        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=AsyncMock(side_effect=_view_only)),
            patch(f"{MEMORY_PATH}.memory_repo.get_by_name", new=AsyncMock(return_value=None)),
            patch(f"{MEMORY_PATH}.memory_repo.create", new=AsyncMock(return_value=_file())),
            patch(f"{MEMORY_PATH}.record_audit", new=AsyncMock()),
        ):
            await service.create(
                _ctx(user_id=me),
                AgentMemoryFileCreate(agent_id=uuid.uuid4(), name="mine", owner_key=f"person:{me}"),
            )
            with pytest.raises(NotFoundError):
                await service.create(
                    _ctx(user_id=me), AgentMemoryFileCreate(agent_id=uuid.uuid4(), name="company")
                )
            with pytest.raises(NotFoundError):
                await service.create(
                    _ctx(user_id=me),
                    AgentMemoryFileCreate(
                        agent_id=uuid.uuid4(),
                        name="theirs",
                        owner_key=f"person:{uuid.uuid4()}",
                    ),
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


class TestOwnerFilteredListing:
    async def test_a_person_files_listing_asks_the_repo_for_that_kind(self):
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
            await service.list_files(_ctx(), agent_id=uuid.uuid4(), owners="person")
        assert listing.await_args.kwargs["owners"] == "person"

    async def test_a_room_facts_listing_asks_the_repo_for_that_kind(self):
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
            await service.list_facts(_ctx(), agent_id=uuid.uuid4(), owners="room")
        assert listing.await_args.kwargs["owners"] == "room"


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


class TestCrossUserRead:
    """A viewer sees the organization store and their own; listing a whole kind of
    store, another person's, or any room is an editor act."""

    @staticmethod
    def _view_only():
        async def _f(_db, _ctx, _agent, perm, **_kw) -> bool:
            return perm == Perm.AGENTS_VIEW

        return AsyncMock(side_effect=_f)

    async def test_a_viewer_may_list_the_organization_store(self):
        service = _service()
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=self._view_only()),
            patch(f"{MEMORY_PATH}.memory_repo.list_for_agent", new=AsyncMock(return_value=([], 0))),
        ):
            result = await service.list_files(_ctx(), agent_id=uuid.uuid4(), owner_key=None)
        assert result.total == 0

    async def test_a_viewer_may_list_their_own_store(self):
        service = _service()
        me = uuid.uuid4()
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=self._view_only()),
            patch(f"{MEMORY_PATH}.memory_repo.list_facts", new=AsyncMock(return_value=([], 0))),
        ):
            result = await service.list_facts(
                _ctx(user_id=me), agent_id=uuid.uuid4(), owner_key=f"person:{me}"
            )
        assert result.total == 0

    async def test_a_viewer_cannot_list_every_store(self):
        service = _service()
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=self._view_only()),
            pytest.raises(NotFoundError),
        ):
            await service.list_files(_ctx(), agent_id=uuid.uuid4(), owners="all")

    async def test_a_viewer_cannot_list_another_persons_facts(self):
        service = _service()
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=self._view_only()),
            pytest.raises(NotFoundError),
        ):
            await service.list_facts(
                _ctx(user_id=uuid.uuid4()), agent_id=uuid.uuid4(), owner_key="person:someone-else"
            )

    async def test_a_viewer_reads_their_own_personal_file_by_id(self):
        service = _service()
        me = uuid.uuid4()
        file = _file(owner_key=f"person:{me}")
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=self._view_only()),
            patch(f"{MEMORY_PATH}.memory_repo.get", new=AsyncMock(return_value=file)),
        ):
            assert await service.get(_ctx(user_id=me), file.id) is file

    async def test_a_viewer_cannot_read_another_persons_file_by_id(self):
        # A known id must not let a viewer GET a personal row it may not list.
        service = _service()
        file = _file(owner_key="person:someone-else")
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=self._view_only()),
            patch(f"{MEMORY_PATH}.memory_repo.get", new=AsyncMock(return_value=file)),
            pytest.raises(NotFoundError),
        ):
            await service.get(_ctx(user_id=uuid.uuid4()), file.id)

    async def test_a_viewer_reads_their_own_personal_fact_by_id(self):
        service = _service()
        me = uuid.uuid4()
        fact = _fact()
        fact.owner_key = f"person:{me}"
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=self._view_only()),
            patch(f"{MEMORY_PATH}.memory_repo.get_fact", new=AsyncMock(return_value=fact)),
        ):
            assert await service.get_fact(_ctx(user_id=me), fact.id) is fact

    async def test_a_viewer_cannot_read_another_persons_fact_by_id(self):
        service = _service()
        fact = _fact()
        fact.owner_key = "person:someone-else"
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=self._view_only()),
            patch(f"{MEMORY_PATH}.memory_repo.get_fact", new=AsyncMock(return_value=fact)),
            pytest.raises(NotFoundError),
        ):
            await service.get_fact(_ctx(user_id=uuid.uuid4()), fact.id)


class TestOwnPersonalWrites:
    """A viewer may amend and forget their *own* personal memory, but nothing else -
    the delete/update side of the create relaxation."""

    @staticmethod
    def _view_only():
        async def _f(_db, _ctx, _agent, perm, **_kw) -> bool:
            return perm == Perm.AGENTS_VIEW

        return AsyncMock(side_effect=_f)

    async def test_a_viewer_forgets_their_own_personal_fact(self):
        service = _service()
        me = uuid.uuid4()
        fact = _fact()
        fact.owner_key = f"person:{me}"
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=self._view_only()),
            patch(f"{MEMORY_PATH}.memory_repo.get_fact", new=AsyncMock(return_value=fact)),
            patch(f"{MEMORY_PATH}.memory_repo.delete_fact", new=AsyncMock()) as delete,
            patch(f"{MEMORY_PATH}.record_audit", new=AsyncMock()),
        ):
            await service.delete_fact(_ctx(user_id=me), fact.id)
        delete.assert_awaited_once()

    async def test_a_viewer_cannot_forget_a_shared_fact(self):
        service = _service()
        fact = _fact()  # shared (scope None)
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=self._view_only()),
            patch(f"{MEMORY_PATH}.memory_repo.get_fact", new=AsyncMock(return_value=fact)),
            pytest.raises(NotFoundError),
        ):
            await service.delete_fact(_ctx(user_id=uuid.uuid4()), fact.id)

    async def test_a_viewer_forgets_their_own_personal_file(self):
        service = _service()
        me = uuid.uuid4()
        file = _file(owner_key=f"person:{me}")
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=self._view_only()),
            patch(f"{MEMORY_PATH}.memory_repo.get", new=AsyncMock(return_value=file)),
            patch(f"{MEMORY_PATH}.memory_repo.delete", new=AsyncMock()) as delete,
            patch(f"{MEMORY_PATH}.record_audit", new=AsyncMock()),
        ):
            await service.delete(_ctx(user_id=me), file.id)
        delete.assert_awaited_once()

    async def test_a_viewer_cannot_forget_a_shared_file(self):
        service = _service()
        file = _file(owner_key=None)  # shared
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=self._view_only()),
            patch(f"{MEMORY_PATH}.memory_repo.get", new=AsyncMock(return_value=file)),
            pytest.raises(NotFoundError),
        ):
            await service.delete(_ctx(user_id=uuid.uuid4()), file.id)


def _mem0_agent():
    return _agent(draft_spec=_memory_spec("mem0"))


class TestMem0FactManagement:
    """Native fact management refuses a mem0-backed agent rather than misleading: a
    seed would report a success the agent can never recall."""

    def _reachable_mem0(self):
        return (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_mem0_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=AsyncMock(return_value=True)),
        )

    async def test_seeding_a_fact_is_refused(self):
        service = _service()
        get_agent, allow = self._reachable_mem0()
        with (
            get_agent,
            allow,
            patch(f"{MEMORY_PATH}.embed_operator_fact", new=AsyncMock()) as embed,
            pytest.raises(BadRequestError),
        ):
            await service.create_fact(
                _ctx(), AgentMemoryFactCreate(agent_id=uuid.uuid4(), content="x")
            )
        embed.assert_not_awaited()

    async def test_listing_facts_is_refused(self):
        service = _service()
        get_agent, allow = self._reachable_mem0()
        with get_agent, allow, pytest.raises(BadRequestError):
            await service.list_facts(_ctx(), agent_id=uuid.uuid4())

    async def test_clearing_facts_is_refused(self):
        service = _service()
        get_agent, allow = self._reachable_mem0()
        with get_agent, allow, pytest.raises(BadRequestError):
            await service.clear_facts(_ctx(), agent_id=uuid.uuid4())

    async def test_clearing_all_memory_is_refused_and_deletes_nothing(self):
        # The combined clear refuses before any partial delete: dropping the native files
        # while the mem0 facts stay recallable would be a wipe reporting success.
        service = _service()
        get_agent, allow = self._reachable_mem0()
        with (
            get_agent,
            allow,
            patch(f"{MEMORY_PATH}.memory_repo.delete_all_files", new=AsyncMock()) as files,
            patch(f"{MEMORY_PATH}.memory_repo.delete_all_facts", new=AsyncMock()) as facts,
            pytest.raises(BadRequestError),
        ):
            await service.clear(_ctx(), agent_id=uuid.uuid4())
        files.assert_not_awaited()
        facts.assert_not_awaited()

    async def test_a_native_backed_agent_is_not_refused(self):
        # The binding is present but native, so the guard's loop runs and finds
        # nothing to refuse - the management path proceeds as normal.
        service = _service()
        agent = _agent(draft_spec=_memory_spec("native"))
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{MEMORY_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{MEMORY_PATH}.memory_repo.list_facts", new=AsyncMock(return_value=([], 0))),
        ):
            result = await service.list_facts(_ctx(), agent_id=uuid.uuid4())
        assert result.total == 0

    async def test_a_published_mem0_spec_is_refused_though_the_draft_says_native(self):
        """The version that runs decides, not the one being edited.

        Published on mem0, then edited back to `native` and not published: the agent's
        facts are still in mem0, so a native seed would report a success nothing can
        recall. Reading the draft alone missed exactly this.
        """
        service = _service()
        agent = _agent(draft_spec=_memory_spec("native"), current_version_id=uuid.uuid4())
        version = _version(_memory_spec("mem0"))
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(
                f"{MEMORY_PATH}.agent_repo.get_version", new=AsyncMock(return_value=version)
            ) as get_version,
            patch(f"{MEMORY_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            pytest.raises(BadRequestError),
        ):
            await service.list_facts(_ctx(), agent_id=uuid.uuid4())
        get_version.assert_awaited_once()

    async def test_a_native_agent_with_a_published_version_is_not_refused(self):
        service = _service()
        agent = _agent(draft_spec=_memory_spec("native"), current_version_id=uuid.uuid4())
        version = _version(_memory_spec("native"))
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{MEMORY_PATH}.agent_repo.get_version", new=AsyncMock(return_value=version)),
            patch(f"{MEMORY_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{MEMORY_PATH}.memory_repo.list_facts", new=AsyncMock(return_value=([], 0))),
        ):
            result = await service.list_facts(_ctx(), agent_id=uuid.uuid4())
        assert result.total == 0

    async def test_a_version_row_that_has_gone_missing_refuses_nothing(self):
        # `current_version_id` names a row this organization cannot read; there is no
        # published spec to consult, so the draft's answer stands.
        service = _service()
        agent = _agent(draft_spec=_memory_spec("native"), current_version_id=uuid.uuid4())
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{MEMORY_PATH}.agent_repo.get_version", new=AsyncMock(return_value=None)),
            patch(f"{MEMORY_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{MEMORY_PATH}.memory_repo.list_facts", new=AsyncMock(return_value=([], 0))),
        ):
            result = await service.list_facts(_ctx(), agent_id=uuid.uuid4())
        assert result.total == 0

    async def test_a_mem0_draft_is_refused_without_reading_the_published_version(self):
        # The draft is checked first, so an agent being switched *to* mem0 refuses
        # before a version lookup it does not need.
        service = _service()
        agent = _agent(draft_spec=_memory_spec("mem0"), current_version_id=uuid.uuid4())
        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{MEMORY_PATH}.agent_repo.get_version", new=AsyncMock()) as get_version,
            patch(f"{MEMORY_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            pytest.raises(BadRequestError),
        ):
            await service.list_facts(_ctx(), agent_id=uuid.uuid4())
        get_version.assert_not_awaited()


class TestCreateFact:
    """The operator seeds a fact directly: it is embedded server-side and metered,
    stored, and audited, and the tier decides the permission the same way a file
    create does."""

    async def test_it_embeds_the_fact_stores_it_and_audits(self):
        service = _service()
        fact_id = uuid.uuid4()
        embed = AsyncMock(return_value=[0.1, 0.2])
        create = AsyncMock(return_value=(fact_id, None))
        audit = AsyncMock()
        get_agent, allow = _reachable_agent()
        with (
            get_agent,
            allow,
            patch(f"{MEMORY_PATH}.assert_organization_within_budget", new=AsyncMock()),
            patch(f"{MEMORY_PATH}.embed_operator_fact", new=embed),
            patch(f"{MEMORY_PATH}.memory_repo.create_fact", new=create),
            patch(f"{MEMORY_PATH}.record_audit", new=audit),
        ):
            result = await service.create_fact(
                _ctx(),
                AgentMemoryFactCreate(agent_id=uuid.uuid4(), content="Acme FY starts in April"),
            )
        assert result.id == fact_id
        assert result.content == "Acme FY starts in April"
        embed.assert_awaited_once_with("Acme FY starts in April")
        assert create.await_args.kwargs["embedding"] == [0.1, 0.2]
        # An operator seed is the trusted tier, so it may enter the shared brief.
        assert create.await_args.kwargs["origin"] == MemoryOrigin.OPERATOR.value
        assert result.origin == "operator"
        assert audit.await_args.kwargs["action"] == "memory.fact.created"

    def _fact_authz_patches(self, resolve: AsyncMock):
        return (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=resolve),
            patch(f"{MEMORY_PATH}.assert_organization_within_budget", new=AsyncMock()),
            patch(f"{MEMORY_PATH}.embed_operator_fact", new=AsyncMock(return_value=[0.1])),
            patch(
                f"{MEMORY_PATH}.memory_repo.create_fact",
                new=AsyncMock(return_value=(uuid.uuid4(), None)),
            ),
            patch(f"{MEMORY_PATH}.record_audit", new=AsyncMock()),
        )

    async def test_it_refuses_when_the_org_is_over_budget(self):
        # The cap is checked before the embed spends, the pre-check RAG makes.
        service = _service()
        get_agent, allow = _reachable_agent()
        embed = AsyncMock()
        with (
            get_agent,
            allow,
            patch(
                f"{MEMORY_PATH}.assert_organization_within_budget",
                new=AsyncMock(
                    side_effect=BudgetExceeded(
                        limit_usd=Decimal(1), spent_usd=Decimal(2), scope=BudgetScope.ORGANIZATION
                    )
                ),
            ),
            patch(f"{MEMORY_PATH}.embed_operator_fact", new=embed),
            pytest.raises(BudgetExceeded),
        ):
            await service.create_fact(
                _ctx(), AgentMemoryFactCreate(agent_id=uuid.uuid4(), content="x")
            )
        embed.assert_not_awaited()

    async def test_a_shared_fact_needs_edit(self):
        service = _service()
        resolve = AsyncMock(return_value=True)
        get_agent, allow, budget, embed, create, audit = self._fact_authz_patches(resolve)
        with get_agent, allow, budget, embed, create, audit:
            await service.create_fact(
                _ctx(), AgentMemoryFactCreate(agent_id=uuid.uuid4(), content="org-wide")
            )
        assert resolve.call_args.args[3] == Perm.AGENTS_EDIT

    async def test_ones_own_fact_needs_only_view(self):
        service = _service()
        me = uuid.uuid4()
        resolve = AsyncMock(return_value=True)
        get_agent, allow, budget, embed, create, audit = self._fact_authz_patches(resolve)
        with get_agent, allow, budget, embed, create, audit:
            await service.create_fact(
                _ctx(user_id=me),
                AgentMemoryFactCreate(
                    agent_id=uuid.uuid4(), content="about me", owner_key=f"person:{me}"
                ),
            )
        assert resolve.call_args.args[3] == Perm.AGENTS_VIEW

    async def test_a_member_cannot_seed_a_shared_fact(self):
        # The refusal that makes the relaxation safe: view-only may seed its own
        # personal fact, but a shared one needs edit and is a 404.
        service = _service()

        async def _view_only(_db, _ctx, _agent, perm, **_kw) -> bool:
            return perm == Perm.AGENTS_VIEW

        with (
            patch(f"{MEMORY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{MEMORY_PATH}.resolve_access", new=AsyncMock(side_effect=_view_only)),
            patch(f"{MEMORY_PATH}.embed_operator_fact", new=AsyncMock()) as embed,
            pytest.raises(NotFoundError),
        ):
            await service.create_fact(
                _ctx(), AgentMemoryFactCreate(agent_id=uuid.uuid4(), content="org-wide")
            )
        embed.assert_not_awaited()

    async def test_it_meters_the_embedding_to_the_org(self):
        # The seed's embedding books to the org, not the deployment: create_fact
        # wraps the embed in an org ledger and hands it to the spend recorder.
        service = _service()
        org = uuid.uuid4()
        record = AsyncMock()
        get_agent, allow = _reachable_agent()
        with (
            get_agent,
            allow,
            patch(f"{MEMORY_PATH}.assert_organization_within_budget", new=AsyncMock()),
            patch(f"{MEMORY_PATH}.embed_operator_fact", new=AsyncMock(return_value=[0.1])),
            patch(
                f"{MEMORY_PATH}.memory_repo.create_fact",
                new=AsyncMock(return_value=(uuid.uuid4(), None)),
            ),
            patch(f"{MEMORY_PATH}._record_operator_embedding_spend", new=record),
            patch(f"{MEMORY_PATH}.record_audit", new=AsyncMock()),
        ):
            await service.create_fact(
                _ctx(org_id=org),
                AgentMemoryFactCreate(agent_id=uuid.uuid4(), content="x"),
            )
        assert record.await_count == 1
        assert isinstance(record.await_args.args[1], SpendLedger)
        assert record.await_args.kwargs["organization_id"] == org


class TestOperatorEmbeddingSpend:
    """The seed's embedding is booked to org ingestion spend, like a RAG document's -
    one row per model, none when the embedding reported no usage."""

    async def test_it_books_the_embedding_per_model_to_ingestion_spend(self):
        ledger = SpendLedger(organization_id=uuid.uuid4())
        ledger.entries.append(
            SpendEntry(
                model_name="emb",
                input_tokens=5,
                output_tokens=0,
                cost_usd=Decimal("0.001"),
                priced=True,
            )
        )
        ledger.entries.append(
            SpendEntry(
                model_name="emb",
                input_tokens=3,
                output_tokens=0,
                cost_usd=Decimal("0.002"),
                priced=True,
            )
        )
        org = uuid.uuid4()
        record = AsyncMock()
        with patch(f"{MEMORY_PATH}.ingestion_spend_repo.record", new=record):
            await _record_operator_embedding_spend(MagicMock(), ledger, organization_id=org)
        kwargs = record.await_args.kwargs
        assert record.await_count == 1
        assert kwargs["organization_id"] == org
        assert kwargs["rag_document_id"] is None
        assert kwargs["input_tokens"] == 8
        assert kwargs["cost_usd"] == Decimal("0.003")
        assert kwargs["cost_is_partial"] is False

    async def test_it_writes_nothing_when_no_usage_was_recorded(self):
        record = AsyncMock()
        with patch(f"{MEMORY_PATH}.ingestion_spend_repo.record", new=record):
            await _record_operator_embedding_spend(
                MagicMock(), SpendLedger(organization_id=uuid.uuid4()), organization_id=uuid.uuid4()
            )
        record.assert_not_awaited()
