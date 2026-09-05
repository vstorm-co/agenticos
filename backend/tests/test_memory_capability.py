"""Tests for the memory capability - the agent's own two-tier store and its tools.

The things worth guarding: reads union the shared store with the current person's
and never reach another person's; writes let the model pick the *tier* but the
personal key is server-derived, so a poisoned tier choice can only ever land in
the current person's own store; a personal write with no identified person is
refused rather than silently written to shared (the N1 graceful degradation);
shared always works; an agent cannot edit or delete operator-authored files; and
the per-end-user key derivation - the isolation surface - is tested in full.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.capabilities import build
from app.agents.capabilities._registry import CapabilityBinding, CapabilityBuildContext
from app.agents.capabilities.memory import (
    Memory,
    MemoryConfig,
    _build,
    derive_end_user_scope_key,
    memory_requested,
)
from app.agents.capabilities.memory._capability import _preamble
from app.agents.capabilities.memory._toolset import (
    _MAX_DESCRIPTION,
    _MAX_KIND,
    _MAX_NAME,
    _MAX_RECALL_LIMIT,
    _NO_PERSONAL_WRITE,
    _NO_SCOPE,
    _NO_SHARED_WRITE,
    MemoryToolset,
)
from app.agents.deps import AgentDeps
from app.core.exceptions import BadRequestError
from app.core.secret_kinds import ApiKeySecret
from app.services import memory as memory_store
from app.services.memory import FactHit, MemoryFileIndexEntry

pytestmark = pytest.mark.anyio

ORG = uuid4()
AGENT = uuid4()


def _deps(*, org=ORG, agent=AGENT, scope_key=None) -> AgentDeps:
    return AgentDeps(organization_id=org, agent_id=agent, end_user_scope_key=scope_key)


def _ctx(deps: AgentDeps, *, retry: int = 0, max_retries: int = 1) -> RunContext[AgentDeps]:
    return RunContext(
        deps=deps, model=TestModel(), usage=RunUsage(), retry=retry, max_retries=max_retries
    )


def _toolset() -> MemoryToolset:
    """A toolset with both stores on, so any tool under test is present."""
    return MemoryToolset(enable_files=True, enable_facts=True)


def _entry(
    name: str, *, description: str | None = None, kind: str = "note", personal: bool
) -> MemoryFileIndexEntry:
    return MemoryFileIndexEntry(name=name, description=description, kind=kind, personal=personal)


class TestPerUserKeyDerivation:
    """N1: a personal key attributes a memory to the person asking, never the
    publisher standing in for an unidentified visitor."""

    def test_a_channel_identity_keys_per_account(self):
        chan = uuid4()
        assert (
            derive_end_user_scope_key(
                channel_identity_id=chan, user_id="anyone", subject_is_publisher_fallback=True
            )
            == f"chan:{chan}"
        )

    def test_a_real_subject_keys_on_the_user(self):
        assert (
            derive_end_user_scope_key(
                channel_identity_id=None, user_id="u-1", subject_is_publisher_fallback=False
            )
            == "user:u-1"
        )

    def test_a_publisher_fallback_refuses(self):
        """The hosted/widget case: `user_id` is the owner, not the visitor."""
        assert (
            derive_end_user_scope_key(
                channel_identity_id=None, user_id="owner", subject_is_publisher_fallback=True
            )
            is None
        )

    def test_no_subject_at_all_refuses(self):
        assert (
            derive_end_user_scope_key(
                channel_identity_id=None, user_id=None, subject_is_publisher_fallback=False
            )
            is None
        )


class TestMemoryRequested:
    def test_true_for_any_enabled_memory_binding(self):
        assert memory_requested([CapabilityBinding(capability_id="memory", config={})])

    def test_a_disabled_binding_does_not_count(self):
        assert not memory_requested(
            [CapabilityBinding(capability_id="memory", config={}, enabled=False)]
        )

    def test_another_capability_does_not_count(self):
        assert not memory_requested([CapabilityBinding(capability_id="knowledge", config={})])


class TestReadScope:
    """A read always resolves - shared alone when there is no person - and never
    refuses for want of one."""

    def test_a_run_with_a_person_reads_that_persons_and_shared(self):
        assert _toolset()._read_scope(_ctx(_deps(scope_key="user:42"))) == (ORG, AGENT, "user:42")

    def test_a_run_without_a_person_reads_shared_alone(self):
        assert _toolset()._read_scope(_ctx(_deps(scope_key=None))) == (ORG, AGENT, None)

    def test_a_run_without_org_or_agent_refuses(self):
        assert _toolset()._read_scope(_ctx(AgentDeps())) == _NO_SCOPE

    def test_a_delegate_does_not_inherit_the_end_user_key(self):
        """`clone_for_subagent` drops the personal key, so a delegate that shares the
        parent's `agent_id` cannot read the parent's personal store as the visitor's -
        memory is a root-agent concern in v1."""
        root = AgentDeps(organization_id=ORG, agent_id=AGENT, end_user_scope_key="user:1")
        assert root.clone_for_subagent().end_user_scope_key is None


class TestWriteScope:
    """The model picks the tier; the server picks the key. A personal write can only
    ever reach the current person's own store, and is refused - never redirected to
    shared - when there is no person."""

    def test_shared_resolves_to_the_shared_partition(self):
        assert _toolset()._write_scope(_ctx(_deps(scope_key="user:1")), "shared") == (
            ORG,
            AGENT,
            None,
        )

    def test_personal_resolves_to_the_runs_own_key(self):
        assert _toolset()._write_scope(_ctx(_deps(scope_key="user:42")), "personal") == (
            ORG,
            AGENT,
            "user:42",
        )

    def test_personal_without_a_person_is_refused_never_shared(self):
        assert (
            _toolset()._write_scope(_ctx(_deps(scope_key=None)), "personal") == _NO_PERSONAL_WRITE
        )

    def test_a_run_without_org_or_agent_refuses(self):
        assert _toolset()._write_scope(_ctx(AgentDeps()), "shared") == _NO_SCOPE


class TestTierLevers:
    """The two operator levers over the tiers, resolved on the toolset."""

    def _levers(self, *, allow_personal=True, allow_agent_shared_writes=True) -> MemoryToolset:
        return MemoryToolset(
            enable_files=True,
            enable_facts=True,
            allow_personal=allow_personal,
            allow_agent_shared_writes=allow_agent_shared_writes,
        )

    def test_allow_personal_off_makes_reads_shared_only(self):
        # Even with an identified person, a shared-only agent reads shared alone.
        toolset = self._levers(allow_personal=False)
        assert toolset._read_scope(_ctx(_deps(scope_key="user:1"))) == (ORG, AGENT, None)

    def test_allow_personal_off_refuses_a_personal_write_even_with_a_person(self):
        toolset = self._levers(allow_personal=False)
        result = toolset._write_scope(_ctx(_deps(scope_key="user:1")), "personal")
        assert result == _NO_PERSONAL_WRITE

    def test_allow_personal_off_still_writes_shared(self):
        toolset = self._levers(allow_personal=False)
        assert toolset._write_scope(_ctx(_deps(scope_key="user:1")), "shared") == (ORG, AGENT, None)

    def test_barred_shared_writes_refuse_shared(self):
        toolset = self._levers(allow_agent_shared_writes=False)
        assert toolset._write_scope(_ctx(_deps(scope_key="user:1")), "shared") == _NO_SHARED_WRITE

    def test_barred_shared_writes_still_allow_personal(self):
        toolset = self._levers(allow_agent_shared_writes=False)
        assert toolset._write_scope(_ctx(_deps(scope_key="user:9")), "personal") == (
            ORG,
            AGENT,
            "user:9",
        )

    def test_barred_shared_writes_do_not_touch_reads(self):
        # Reads are unaffected - the agent still reads shared and the person's own.
        toolset = self._levers(allow_agent_shared_writes=False)
        assert toolset._read_scope(_ctx(_deps(scope_key="user:1"))) == (ORG, AGENT, "user:1")


class TestPreamble:
    def test_both_on_names_both_tiers_and_the_choice(self):
        text = _preamble(allow_personal=True, allow_agent_shared_writes=True)
        assert "two tiers" in text and "'personal'" in text and "'shared'" in text

    def test_personal_off_is_shared_only(self):
        text = _preamble(allow_personal=False, allow_agent_shared_writes=True)
        assert "two tiers" not in text
        assert "scope='shared'" in text

    def test_shared_writes_barred_saves_only_personal(self):
        text = _preamble(allow_personal=True, allow_agent_shared_writes=False)
        assert "scope='personal'" in text and "curated by operators" in text

    def test_both_off_is_read_only(self):
        text = _preamble(allow_personal=False, allow_agent_shared_writes=False)
        assert "read-only" in text

    def test_every_configuration_leads_with_the_read_before_answering_habit(self):
        # A model holding the recall tool but no standing instruction to use it answers
        # "I have nothing saved" with the fact one search away.
        for allow_personal in (True, False):
            for allow_shared in (True, False):
                text = _preamble(
                    allow_personal=allow_personal, allow_agent_shared_writes=allow_shared
                )
                assert text.startswith("Search your memory before answering")


class TestMemoryBrief:
    """A native-facts agent's instructions carry what it already remembers, so it
    recalls without having to call the tool - the store felt inert without this on a
    lighter model that never chose to `recall` (#788)."""

    def test_a_native_facts_agent_gets_a_dynamic_instruction(self):
        assert callable(Memory(enable_facts=True, backend="native").get_instructions())

    def test_a_files_only_agent_keeps_the_plain_preamble(self):
        assert isinstance(Memory(enable_files=True, enable_facts=False).get_instructions(), str)

    def test_a_mem0_agent_keeps_the_plain_preamble(self):
        # mem0 holds facts elsewhere; the recall tool still applies, but there is no
        # native list to brief from.
        assert isinstance(Memory(enable_facts=True, backend="mem0").get_instructions(), str)

    async def test_the_brief_appends_what_is_remembered(self, monkeypatch):
        monkeypatch.setattr(
            memory_store, "memory_brief", AsyncMock(return_value=["likes nuts", "based in Warsaw"])
        )
        instructions = Memory(enable_facts=True, backend="native").get_instructions()
        text = await instructions(_ctx(_deps(scope_key="user:1")))
        assert text.startswith("Search your memory before answering")
        assert "- likes nuts" in text and "- based in Warsaw" in text

    async def test_the_brief_reads_the_runs_own_personal_tier(self, monkeypatch):
        brief = AsyncMock(return_value=["x"])
        monkeypatch.setattr(memory_store, "memory_brief", brief)
        await Memory(enable_facts=True, backend="native").get_instructions()(
            _ctx(_deps(scope_key="user:9"))
        )
        assert brief.await_args.kwargs["personal_key"] == "user:9"

    async def test_personal_off_briefs_only_the_shared_tier(self, monkeypatch):
        brief = AsyncMock(return_value=["x"])
        monkeypatch.setattr(memory_store, "memory_brief", brief)
        cap = Memory(enable_facts=True, backend="native", allow_personal=False)
        await cap.get_instructions()(_ctx(_deps(scope_key="user:9")))
        assert brief.await_args.kwargs["personal_key"] is None

    async def test_no_facts_leaves_the_preamble_alone(self, monkeypatch):
        monkeypatch.setattr(memory_store, "memory_brief", AsyncMock(return_value=[]))
        text = await Memory(enable_facts=True, backend="native").get_instructions()(
            _ctx(_deps(scope_key="user:1"))
        )
        assert text == _preamble(allow_personal=True, allow_agent_shared_writes=True)

    async def test_a_run_with_no_identity_is_not_briefed(self, monkeypatch):
        # No org/agent on the deps: nothing to query, and the store is never touched.
        brief = AsyncMock(return_value=["x"])
        monkeypatch.setattr(memory_store, "memory_brief", brief)
        text = await Memory(enable_facts=True, backend="native").get_instructions()(
            _ctx(AgentDeps())
        )
        assert text == _preamble(allow_personal=True, allow_agent_shared_writes=True)
        brief.assert_not_awaited()

    async def test_the_brief_is_bounded_by_size_not_only_by_count(self, monkeypatch):
        # A fact's content is unbounded Text, so a row cap alone would not stop the
        # preamble from blowing the window; the newest facts are kept until the budget is spent.
        big = "x" * 1500
        monkeypatch.setattr(memory_store, "memory_brief", AsyncMock(return_value=[big] * 5))
        text = await Memory(enable_facts=True, backend="native").get_instructions()(
            _ctx(_deps(scope_key="user:1"))
        )
        assert 1 <= text.count(big) < 5

    async def test_a_single_oversized_fact_is_dropped_not_injected(self, monkeypatch):
        # A fact past the whole budget is not spliced in unbounded; with nothing left
        # that fits, the brief falls back to the plain preamble.
        huge = "y" * 6000
        monkeypatch.setattr(memory_store, "memory_brief", AsyncMock(return_value=[huge]))
        text = await Memory(enable_facts=True, backend="native").get_instructions()(
            _ctx(_deps(scope_key="user:1"))
        )
        assert huge not in text
        assert text == _preamble(allow_personal=True, allow_agent_shared_writes=True)

    async def test_the_newest_fact_survives_when_an_older_one_is_too_big(self, monkeypatch):
        # Newest-first, the small newest fact is kept and the oversized older one is
        # skipped.
        monkeypatch.setattr(
            memory_store, "memory_brief", AsyncMock(return_value=["fresh", "z" * 6000])
        )
        text = await Memory(enable_facts=True, backend="native").get_instructions()(
            _ctx(_deps(scope_key="user:1"))
        )
        assert "- fresh" in text and "z" * 6000 not in text

    async def test_an_oversized_fact_does_not_take_the_smaller_ones_with_it(self, monkeypatch):
        """One huge note must not empty the brief.

        The budget skips the line it cannot afford and carries on; ending the loop
        instead would let a single oversized `remember` - whose content is unbounded
        Text - silently drop every other fact out of the preamble, on every request
        after it was written.
        """
        monkeypatch.setattr(
            memory_store,
            "memory_brief",
            AsyncMock(return_value=["z" * 6000, "likes tea", "works in Kraków"]),
        )
        text = await Memory(enable_facts=True, backend="native").get_instructions()(
            _ctx(_deps(scope_key="user:1"))
        )
        assert "- likes tea" in text
        assert "- works in Kraków" in text
        assert "z" * 6000 not in text


class TestListMemory:
    async def test_it_lists_both_tiers_with_labels(self, monkeypatch):
        monkeypatch.setattr(
            memory_store,
            "list_files",
            AsyncMock(
                return_value=[
                    _entry("policy", description="the rules", kind="profile", personal=False),
                    _entry("prefs", description="what they like", kind="profile", personal=True),
                    _entry("scratch", description=None, kind="note", personal=True),
                ]
            ),
        )
        out = await _toolset().list_memory(_ctx(_deps(scope_key="user:1")))
        assert "- [shared] policy [profile]: the rules" in out
        assert "- [personal] prefs [profile]: what they like" in out
        assert "- [personal] scratch [note]" in out

    async def test_it_reads_with_the_runs_personal_key(self, monkeypatch):
        list_files = AsyncMock(return_value=[])
        monkeypatch.setattr(memory_store, "list_files", list_files)
        await _toolset().list_memory(_ctx(_deps(scope_key="user:9")))
        assert list_files.await_args.kwargs["personal_key"] == "user:9"

    async def test_an_empty_store_says_so(self, monkeypatch):
        monkeypatch.setattr(memory_store, "list_files", AsyncMock(return_value=[]))
        out = await _toolset().list_memory(_ctx(_deps()))
        assert "No memories saved yet." in out

    async def test_a_run_without_org_or_agent_refuses(self, monkeypatch):
        called = AsyncMock()
        monkeypatch.setattr(memory_store, "list_files", called)
        out = await _toolset().list_memory(_ctx(AgentDeps()))
        assert out == _NO_SCOPE
        called.assert_not_awaited()


class TestReadMemory:
    async def test_it_returns_the_body_reading_with_the_personal_key(self, monkeypatch):
        read = AsyncMock(return_value="the body")
        monkeypatch.setattr(memory_store, "read_file", read)
        out = await _toolset().read_memory(_ctx(_deps(scope_key="user:1")), "prefs")
        assert out == "the body"
        assert read.await_args.kwargs["personal_key"] == "user:1"

    async def test_an_unknown_name_is_a_retry_naming_what_exists(self, monkeypatch):
        monkeypatch.setattr(memory_store, "read_file", AsyncMock(return_value=None))
        monkeypatch.setattr(
            memory_store,
            "list_files",
            AsyncMock(return_value=[_entry("prefs", personal=True)]),
        )
        with pytest.raises(ModelRetry, match="prefs"):
            await _toolset().read_memory(_ctx(_deps(scope_key="user:1")), "missing")

    async def test_the_last_attempt_answers_rather_than_ending_the_run(self, monkeypatch):
        monkeypatch.setattr(memory_store, "read_file", AsyncMock(return_value=None))
        monkeypatch.setattr(memory_store, "list_files", AsyncMock(return_value=[]))
        answered = await _toolset().read_memory(_ctx(_deps(), retry=1), "missing")
        assert "missing" in answered and "none" in answered

    async def test_a_run_without_org_or_agent_refuses(self, monkeypatch):
        monkeypatch.setattr(memory_store, "read_file", AsyncMock())
        out = await _toolset().read_memory(_ctx(AgentDeps()), "prefs")
        assert out == _NO_SCOPE


class TestWriteMemory:
    async def test_personal_saves_to_the_runs_own_partition(self, monkeypatch):
        write = AsyncMock(return_value=True)
        monkeypatch.setattr(memory_store, "write_file", write)
        out = await _toolset().write_memory(
            _ctx(_deps(scope_key="user:9")), "prefs", "likes tea", scope="personal", kind="profile"
        )
        assert out == "Saved memory 'prefs'."
        assert write.await_args.kwargs["scope_key"] == "user:9"

    async def test_shared_saves_to_the_shared_partition(self, monkeypatch):
        write = AsyncMock(return_value=True)
        monkeypatch.setattr(memory_store, "write_file", write)
        out = await _toolset().write_memory(
            _ctx(_deps(scope_key="user:9")), "policy", "org-wide", scope="shared"
        )
        assert out == "Saved memory 'policy'."
        assert write.await_args.kwargs["scope_key"] is None

    async def test_it_defaults_to_personal(self, monkeypatch):
        write = AsyncMock(return_value=True)
        monkeypatch.setattr(memory_store, "write_file", write)
        await _toolset().write_memory(_ctx(_deps(scope_key="user:9")), "prefs", "x")
        assert write.await_args.kwargs["scope_key"] == "user:9"

    async def test_a_personal_write_with_no_person_is_refused_never_shared(self, monkeypatch):
        write = AsyncMock()
        monkeypatch.setattr(memory_store, "write_file", write)
        out = await _toolset().write_memory(
            _ctx(_deps(scope_key=None)), "prefs", "x", scope="personal"
        )
        assert out == _NO_PERSONAL_WRITE
        write.assert_not_awaited()

    async def test_a_shared_write_works_with_no_person(self, monkeypatch):
        write = AsyncMock(return_value=True)
        monkeypatch.setattr(memory_store, "write_file", write)
        out = await _toolset().write_memory(
            _ctx(_deps(scope_key=None)), "policy", "x", scope="shared"
        )
        assert out == "Saved memory 'policy'."
        assert write.await_args.kwargs["scope_key"] is None

    async def test_a_taken_name_is_reported_not_overwritten(self, monkeypatch):
        monkeypatch.setattr(memory_store, "write_file", AsyncMock(return_value=False))
        out = await _toolset().write_memory(_ctx(_deps(scope_key="user:1")), "prefs", "x")
        assert "already exists" in out and "edit_memory" in out

    async def test_metadata_past_a_column_width_is_refused_before_the_database(self, monkeypatch):
        # Past its column width the write would be an asyncpg `DataError` that fails the
        # run; the tool refuses it with a note the model can act on.
        write = AsyncMock()
        monkeypatch.setattr(memory_store, "write_file", write)
        toolset = _toolset()
        deps = _deps(scope_key="user:1")

        long_name = await toolset.write_memory(_ctx(deps), "n" * (_MAX_NAME + 1), "body")
        long_kind = await toolset.write_memory(
            _ctx(deps), "prefs", "body", kind="k" * (_MAX_KIND + 1)
        )
        long_desc = await toolset.write_memory(
            _ctx(deps), "prefs", "body", description="d" * (_MAX_DESCRIPTION + 1)
        )

        assert "too long" in long_name and f"under {_MAX_NAME}" in long_name
        assert "too long" in long_kind and f"under {_MAX_KIND}" in long_kind
        assert "too long" in long_desc and f"under {_MAX_DESCRIPTION}" in long_desc
        write.assert_not_awaited()


class TestEditMemory:
    async def test_it_updates_an_existing_file_in_the_default_personal_tier(self, monkeypatch):
        edit = AsyncMock(return_value="ok")
        monkeypatch.setattr(memory_store, "edit_file", edit)
        out = await _toolset().edit_memory(_ctx(_deps(scope_key="user:1")), "prefs", "new")
        assert out == "Updated memory 'prefs'."
        assert edit.await_args.kwargs["scope_key"] == "user:1"

    async def test_shared_edits_the_shared_partition(self, monkeypatch):
        edit = AsyncMock(return_value="ok")
        monkeypatch.setattr(memory_store, "edit_file", edit)
        await _toolset().edit_memory(
            _ctx(_deps(scope_key="user:1")), "policy", "new", scope="shared"
        )
        assert edit.await_args.kwargs["scope_key"] is None

    async def test_a_missing_file_says_to_write_one(self, monkeypatch):
        monkeypatch.setattr(memory_store, "edit_file", AsyncMock(return_value="missing"))
        out = await _toolset().edit_memory(_ctx(_deps(scope_key="user:1")), "gone", "x")
        assert "No memory named 'gone'" in out and "write_memory" in out

    async def test_an_operator_file_is_protected(self, monkeypatch):
        monkeypatch.setattr(memory_store, "edit_file", AsyncMock(return_value="protected"))
        out = await _toolset().edit_memory(
            _ctx(_deps(scope_key="user:1")), "policy", "x", scope="shared"
        )
        assert "operator" in out and "cannot be changed" in out

    async def test_a_personal_edit_with_no_person_is_refused(self, monkeypatch):
        monkeypatch.setattr(memory_store, "edit_file", AsyncMock())
        out = await _toolset().edit_memory(_ctx(_deps(scope_key=None)), "p", "x", scope="personal")
        assert out == _NO_PERSONAL_WRITE


class TestDeleteMemory:
    async def test_it_forgets_a_file(self, monkeypatch):
        monkeypatch.setattr(memory_store, "delete_file", AsyncMock(return_value="ok"))
        out = await _toolset().delete_memory(_ctx(_deps(scope_key="user:1")), "prefs")
        assert out == "Forgot memory 'prefs'."

    async def test_a_missing_file_says_so(self, monkeypatch):
        monkeypatch.setattr(memory_store, "delete_file", AsyncMock(return_value="missing"))
        out = await _toolset().delete_memory(_ctx(_deps(scope_key="user:1")), "gone")
        assert out == "No memory named 'gone' to forget."

    async def test_an_operator_file_is_protected(self, monkeypatch):
        monkeypatch.setattr(memory_store, "delete_file", AsyncMock(return_value="protected"))
        out = await _toolset().delete_memory(
            _ctx(_deps(scope_key="user:1")), "policy", scope="shared"
        )
        assert "operator" in out and "cannot be removed" in out

    async def test_a_personal_delete_with_no_person_is_refused(self, monkeypatch):
        monkeypatch.setattr(memory_store, "delete_file", AsyncMock())
        out = await _toolset().delete_memory(_ctx(_deps(scope_key=None)), "p", scope="personal")
        assert out == _NO_PERSONAL_WRITE


class TestRemember:
    async def test_personal_stores_a_fact_in_the_runs_partition(self, monkeypatch):
        remember = AsyncMock()
        monkeypatch.setattr(memory_store, "remember", remember)
        out = await _toolset().remember(_ctx(_deps(scope_key="user:9")), "likes tea")
        assert out == "Remembered."
        assert remember.await_args.kwargs["scope_key"] == "user:9"
        assert remember.await_args.kwargs["content"] == "likes tea"

    async def test_shared_stores_a_fact_org_wide(self, monkeypatch):
        remember = AsyncMock()
        monkeypatch.setattr(memory_store, "remember", remember)
        await _toolset().remember(
            _ctx(_deps(scope_key="user:9")), "the fiscal year starts in April", scope="shared"
        )
        assert remember.await_args.kwargs["scope_key"] is None

    async def test_a_personal_fact_with_no_person_is_refused(self, monkeypatch):
        remember = AsyncMock()
        monkeypatch.setattr(memory_store, "remember", remember)
        out = await _toolset().remember(_ctx(_deps(scope_key=None)), "x", scope="personal")
        assert out == _NO_PERSONAL_WRITE
        remember.assert_not_awaited()


class TestRecall:
    async def test_it_returns_hits_most_relevant_first(self, monkeypatch):
        monkeypatch.setattr(
            memory_store,
            "recall",
            AsyncMock(
                return_value=[
                    FactHit(content="likes tea", score=0.9),
                    FactHit(content="lives in Berlin", score=0.7),
                ]
            ),
        )
        out = await _toolset().recall(_ctx(_deps(scope_key="user:1")), "what do they like")
        assert out == "- likes tea\n- lives in Berlin"

    async def test_it_recalls_across_both_tiers(self, monkeypatch):
        recall = AsyncMock(return_value=[])
        monkeypatch.setattr(memory_store, "recall", recall)
        await _toolset().recall(_ctx(_deps(scope_key="user:9")), "q")
        assert recall.await_args.kwargs["personal_key"] == "user:9"

    async def test_it_caps_an_oversized_limit(self, monkeypatch):
        recall = AsyncMock(return_value=[])
        monkeypatch.setattr(memory_store, "recall", recall)
        await _toolset().recall(_ctx(_deps()), "q", limit=1000)
        assert recall.await_args.kwargs["limit"] == _MAX_RECALL_LIMIT

    async def test_it_floors_a_nonpositive_limit(self, monkeypatch):
        recall = AsyncMock(return_value=[])
        monkeypatch.setattr(memory_store, "recall", recall)
        await _toolset().recall(_ctx(_deps()), "q", limit=0)
        assert recall.await_args.kwargs["limit"] == 1

    async def test_nothing_relevant_says_so(self, monkeypatch):
        monkeypatch.setattr(memory_store, "recall", AsyncMock(return_value=[]))
        out = await _toolset().recall(_ctx(_deps()), "anything")
        assert out == "No relevant memories."

    async def test_a_run_without_org_or_agent_refuses(self, monkeypatch):
        recall = AsyncMock()
        monkeypatch.setattr(memory_store, "recall", recall)
        out = await _toolset().recall(_ctx(AgentDeps()), "x")
        assert out == _NO_SCOPE
        recall.assert_not_awaited()


class TestCapability:
    def test_the_toolset_is_built_once(self):
        cap = Memory()
        assert cap.get_toolset() is cap.get_toolset()

    def test_the_toolset_carries_the_tools_its_config_enables(self):
        files = {"list_memory", "read_memory", "write_memory", "edit_memory", "delete_memory"}
        facts = {"remember", "recall"}
        files_only = Memory(enable_files=True, enable_facts=False).get_toolset()
        assert set(files_only.tools) == files
        facts_only = Memory(enable_files=False, enable_facts=True).get_toolset()
        assert set(facts_only.tools) == facts
        both = Memory(enable_files=True, enable_facts=True).get_toolset()
        assert set(both.tools) == files | facts

    def test_it_carries_a_two_tier_preamble_by_default(self):
        instructions = Memory(enable_files=True).get_instructions()
        assert instructions == _preamble(allow_personal=True, allow_agent_shared_writes=True)
        assert "shared" in instructions and "personal" in instructions


class TestConfig:
    def test_defaults(self):
        config = MemoryConfig()
        assert config.enable_files is True
        assert config.enable_facts is True
        assert config.backend == "native"
        assert config.allow_personal is True
        assert config.allow_agent_shared_writes is True

    def test_backend_rejects_an_unknown_value(self):
        with pytest.raises(ValueError):
            MemoryConfig(backend="pinecone")  # ty: ignore[invalid-argument-type]

    def test_mem0_without_facts_normalizes_to_native(self):
        """mem0 stores facts only, so a facts-off config cannot require its key (H1)."""
        assert MemoryConfig(backend="mem0", enable_facts=False).backend == "native"
        assert MemoryConfig(backend="mem0", enable_facts=True).backend == "mem0"

    def test_the_partition_toggle_is_gone(self):
        """The two tiers coexist now, so there is no partition to choose."""
        assert "partition" not in MemoryConfig.model_fields

    def test_a_valid_self_hosted_mem0_url_is_accepted(self):
        assert (
            MemoryConfig(mem0_base_url="https://mem0.example.com").mem0_base_url
            == "https://mem0.example.com"
        )

    def test_no_mem0_base_url_is_the_managed_cloud(self):
        assert MemoryConfig(mem0_base_url=None).mem0_base_url is None

    def test_a_malformed_mem0_base_url_is_refused_at_publish(self):
        # `https://[` would otherwise reach urlsplit on the run path and end the run with a ValueError.
        with pytest.raises(ValueError, match="valid URL"):
            MemoryConfig(mem0_base_url="https://[")

    def test_a_non_https_mem0_base_url_is_refused(self):
        with pytest.raises(ValueError, match="https URL with a host"):
            MemoryConfig(mem0_base_url="http://mem0.example.com")

    def test_a_mem0_base_url_without_a_host_is_refused(self):
        with pytest.raises(ValueError, match="https URL with a host"):
            MemoryConfig(mem0_base_url="https://")


class TestBuilder:
    def test_both_stores_off_contributes_nothing(self):
        ctx = CapabilityBuildContext(
            binding=CapabilityBinding(capability_id="memory"),
            config=MemoryConfig(enable_files=False, enable_facts=False),
        )
        assert _build(ctx) is None

    def test_one_store_on_builds_the_capability(self):
        ctx = CapabilityBuildContext(
            binding=CapabilityBinding(capability_id="memory"),
            config=MemoryConfig(enable_files=False, enable_facts=True),
        )
        cap = _build(ctx)
        assert isinstance(cap, Memory)
        assert cap.enable_files is False
        assert cap.enable_facts is True

    def test_it_falls_back_to_default_config(self):
        ctx = CapabilityBuildContext(binding=CapabilityBinding(capability_id="memory"), config=None)
        assert isinstance(_build(ctx), Memory)

    def test_it_passes_the_tier_levers_to_the_capability(self):
        ctx = CapabilityBuildContext(
            binding=CapabilityBinding(capability_id="memory"),
            config=MemoryConfig(allow_personal=False, allow_agent_shared_writes=False),
        )
        cap = _build(ctx)
        assert isinstance(cap, Memory)
        assert cap.allow_personal is False
        assert cap.allow_agent_shared_writes is False

    def test_it_is_registered_and_builds_through_the_registry(self):
        (capability,) = build([CapabilityBinding(capability_id="memory", config={})])
        assert capability.id == "memory"

    def test_mem0_backend_reads_the_secret(self):
        sid = uuid4()
        (capability,) = build(
            [CapabilityBinding(capability_id="memory", config={"backend": "mem0"}, secret_id=sid)],
            secrets={sid: ApiKeySecret(api_key="k-9")},
        )
        assert capability.get_toolset()._mem0_key == "k-9"

    def test_mem0_backend_without_a_secret_is_refused(self):
        with pytest.raises(BadRequestError):
            build([CapabilityBinding(capability_id="memory", config={"backend": "mem0"})])


class TestMem0Backend:
    def _mem0_toolset(self) -> MemoryToolset:
        return MemoryToolset(
            enable_files=False,
            enable_facts=True,
            backend="mem0",
            mem0_api_key="k",
            mem0_base_url="https://m",
        )

    async def test_remember_routes_to_mem0(self, monkeypatch):
        mem0, native = AsyncMock(), AsyncMock()
        monkeypatch.setattr(memory_store, "mem0_remember", mem0)
        monkeypatch.setattr(memory_store, "remember", native)
        out = await self._mem0_toolset().remember(_ctx(_deps(scope_key="user:1")), "likes tea")
        assert out == "Remembered."
        native.assert_not_awaited()
        assert mem0.await_args.kwargs["api_key"] == "k"
        assert mem0.await_args.kwargs["base_url"] == "https://m"
        assert mem0.await_args.kwargs["scope_key"] == "user:1"

    async def test_recall_routes_to_mem0_across_tiers(self, monkeypatch):
        monkeypatch.setattr(
            memory_store,
            "mem0_recall",
            AsyncMock(return_value=[FactHit(content="likes tea", score=0.9)]),
        )
        native = AsyncMock()
        monkeypatch.setattr(memory_store, "recall", native)
        out = await self._mem0_toolset().recall(_ctx(_deps(scope_key="user:1")), "q")
        assert out == "- likes tea"
        native.assert_not_awaited()

    async def test_recall_passes_the_personal_key_to_mem0(self, monkeypatch):
        recall = AsyncMock(return_value=[])
        monkeypatch.setattr(memory_store, "mem0_recall", recall)
        await self._mem0_toolset().recall(_ctx(_deps(scope_key="user:9")), "q")
        assert recall.await_args.kwargs["personal_key"] == "user:9"

    def test_the_native_backend_ignores_a_stray_key(self):
        toolset = MemoryToolset(
            enable_files=False,
            enable_facts=True,
            backend="native",
            mem0_api_key="k",
        )
        assert toolset._mem0_key is None
