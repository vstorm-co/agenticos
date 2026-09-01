"""Tests for the memory capability - the agent's own file store and its tools.

The things worth guarding: the tools reach only the partition the run was
admitted to (and a per-user run with no person refuses rather than falling back
to a shared store), an agent cannot edit or delete operator-authored files, an
unknown read is a retry not a crash, and a disabled store contributes nothing.
The per-end-user key derivation is the N1 refusal surface and is tested in full.
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
    per_user_partition_requested,
)
from app.agents.capabilities.memory._toolset import (
    _MAX_DESCRIPTION,
    _MAX_KIND,
    _MAX_NAME,
    _NO_PERSON,
    _NO_SCOPE,
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


def _toolset(partition: str = "shared") -> MemoryToolset:
    """A toolset with both stores on, so any tool under test is present."""
    return MemoryToolset(partition=partition, enable_files=True, enable_facts=True)


class TestPerUserKeyDerivation:
    """N1: a per-user key attributes a memory to the person asking, never the
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


class TestPerUserPartitionRequested:
    def test_true_only_for_an_enabled_per_user_memory_binding(self):
        assert per_user_partition_requested(
            [CapabilityBinding(capability_id="memory", config={"partition": "per_user"})]
        )

    def test_a_shared_binding_is_not_per_user(self):
        assert not per_user_partition_requested(
            [CapabilityBinding(capability_id="memory", config={"partition": "shared"})]
        )

    def test_an_absent_partition_defaults_to_shared(self):
        assert not per_user_partition_requested(
            [CapabilityBinding(capability_id="memory", config={})]
        )

    def test_a_disabled_binding_does_not_count(self):
        assert not per_user_partition_requested(
            [
                CapabilityBinding(
                    capability_id="memory", config={"partition": "per_user"}, enabled=False
                )
            ]
        )

    def test_another_capability_does_not_count(self):
        assert not per_user_partition_requested(
            [CapabilityBinding(capability_id="knowledge", config={"partition": "per_user"})]
        )


class TestScopeResolution:
    def test_shared_uses_the_null_partition(self):
        toolset = _toolset("shared")
        assert toolset._scope(_ctx(_deps(scope_key="user:ignored"))) == (ORG, AGENT, None)

    def test_per_user_uses_the_derived_key(self):
        toolset = _toolset("per_user")
        assert toolset._scope(_ctx(_deps(scope_key="user:42"))) == (ORG, AGENT, "user:42")

    def test_per_user_without_a_key_refuses(self):
        toolset = _toolset("per_user")
        assert toolset._scope(_ctx(_deps(scope_key=None))) == _NO_PERSON

    def test_a_run_without_org_or_agent_refuses(self):
        toolset = _toolset("shared")
        assert toolset._scope(_ctx(AgentDeps())) == _NO_SCOPE

    def test_a_delegate_does_not_inherit_the_end_user_key(self):
        """`clone_for_subagent` drops the per-user key, so per_user memory refuses
        inside a delegation - memory is a root-agent concern in v1, and a delegate
        that shares the parent's `agent_id` must not read the parent's per-user
        partition as if it were the visitor's."""
        root = AgentDeps(organization_id=ORG, agent_id=AGENT, end_user_scope_key="user:1")
        assert root.clone_for_subagent().end_user_scope_key is None


class TestListMemory:
    async def test_it_lists_names_kinds_and_descriptions(self, monkeypatch):
        monkeypatch.setattr(
            memory_store,
            "list_files",
            AsyncMock(
                return_value=[
                    MemoryFileIndexEntry(
                        name="prefs", description="what they like", kind="profile"
                    ),
                    MemoryFileIndexEntry(name="scratch", description=None, kind="note"),
                ]
            ),
        )
        out = await _toolset("shared").list_memory(_ctx(_deps()))
        assert "- prefs [profile]: what they like" in out
        assert "- scratch [note]" in out

    async def test_an_empty_store_says_so(self, monkeypatch):
        monkeypatch.setattr(memory_store, "list_files", AsyncMock(return_value=[]))
        out = await _toolset("shared").list_memory(_ctx(_deps()))
        assert "No memories saved yet." in out

    async def test_it_refuses_a_per_user_run_with_no_person(self, monkeypatch):
        called = AsyncMock()
        monkeypatch.setattr(memory_store, "list_files", called)
        out = await _toolset("per_user").list_memory(_ctx(_deps(scope_key=None)))
        assert out == _NO_PERSON
        called.assert_not_awaited()


class TestReadMemory:
    async def test_it_returns_the_body(self, monkeypatch):
        monkeypatch.setattr(memory_store, "read_file", AsyncMock(return_value="the body"))
        out = await _toolset("shared").read_memory(_ctx(_deps()), "prefs")
        assert out == "the body"

    async def test_an_unknown_name_is_a_retry_naming_what_exists(self, monkeypatch):
        monkeypatch.setattr(memory_store, "read_file", AsyncMock(return_value=None))
        monkeypatch.setattr(
            memory_store,
            "list_files",
            AsyncMock(
                return_value=[MemoryFileIndexEntry(name="prefs", description=None, kind="n")]
            ),
        )
        with pytest.raises(ModelRetry, match="prefs"):
            await _toolset("shared").read_memory(_ctx(_deps()), "missing")

    async def test_the_last_attempt_answers_rather_than_ending_the_run(self, monkeypatch):
        monkeypatch.setattr(memory_store, "read_file", AsyncMock(return_value=None))
        monkeypatch.setattr(memory_store, "list_files", AsyncMock(return_value=[]))
        answered = await _toolset("shared").read_memory(_ctx(_deps(), retry=1), "missing")
        assert "missing" in answered and "none" in answered

    async def test_it_refuses_a_per_user_run_with_no_person(self, monkeypatch):
        monkeypatch.setattr(memory_store, "read_file", AsyncMock())
        out = await _toolset("per_user").read_memory(_ctx(_deps(scope_key=None)), "prefs")
        assert out == _NO_PERSON


class TestWriteMemory:
    async def test_it_saves_a_new_file_scoped_to_the_partition(self, monkeypatch):
        write = AsyncMock(return_value=True)
        monkeypatch.setattr(memory_store, "write_file", write)
        out = await _toolset("per_user").write_memory(
            _ctx(_deps(scope_key="user:9")), "prefs", "likes tea", description="d", kind="profile"
        )
        assert out == "Saved memory 'prefs'."
        assert write.await_args.kwargs["scope_key"] == "user:9"
        assert write.await_args.kwargs["organization_id"] == ORG

    async def test_a_taken_name_is_reported_not_overwritten(self, monkeypatch):
        monkeypatch.setattr(memory_store, "write_file", AsyncMock(return_value=False))
        out = await _toolset("shared").write_memory(_ctx(_deps()), "prefs", "x")
        assert "already exists" in out and "edit_memory" in out

    async def test_it_refuses_a_per_user_run_with_no_person(self, monkeypatch):
        write = AsyncMock()
        monkeypatch.setattr(memory_store, "write_file", write)
        out = await _toolset("per_user").write_memory(_ctx(_deps(scope_key=None)), "prefs", "x")
        assert out == _NO_PERSON
        write.assert_not_awaited()

    async def test_metadata_past_a_column_width_is_refused_before_the_database(self, monkeypatch):
        # A name/kind/description past its column width would be an asyncpg
        # `DataError` that fails the run; the tool refuses it with a note the model
        # can shorten and retry, and never reaches the store.
        write = AsyncMock()
        monkeypatch.setattr(memory_store, "write_file", write)
        toolset = _toolset("shared")

        long_name = await toolset.write_memory(_ctx(_deps()), "n" * (_MAX_NAME + 1), "body")
        long_kind = await toolset.write_memory(
            _ctx(_deps()), "prefs", "body", kind="k" * (_MAX_KIND + 1)
        )
        long_desc = await toolset.write_memory(
            _ctx(_deps()), "prefs", "body", description="d" * (_MAX_DESCRIPTION + 1)
        )

        assert "too long" in long_name and f"under {_MAX_NAME}" in long_name
        assert "too long" in long_kind and f"under {_MAX_KIND}" in long_kind
        assert "too long" in long_desc and f"under {_MAX_DESCRIPTION}" in long_desc
        write.assert_not_awaited()


class TestEditMemory:
    async def test_it_updates_an_existing_file(self, monkeypatch):
        monkeypatch.setattr(memory_store, "edit_file", AsyncMock(return_value="ok"))
        out = await _toolset("shared").edit_memory(_ctx(_deps()), "prefs", "new")
        assert out == "Updated memory 'prefs'."

    async def test_a_missing_file_says_to_write_one(self, monkeypatch):
        monkeypatch.setattr(memory_store, "edit_file", AsyncMock(return_value="missing"))
        out = await _toolset("shared").edit_memory(_ctx(_deps()), "gone", "x")
        assert "No memory named 'gone'" in out and "write_memory" in out

    async def test_an_operator_file_is_protected(self, monkeypatch):
        monkeypatch.setattr(memory_store, "edit_file", AsyncMock(return_value="protected"))
        out = await _toolset("shared").edit_memory(_ctx(_deps()), "policy", "x")
        assert "operator" in out and "cannot be changed" in out

    async def test_it_refuses_a_per_user_run_with_no_person(self, monkeypatch):
        monkeypatch.setattr(memory_store, "edit_file", AsyncMock())
        out = await _toolset("per_user").edit_memory(_ctx(_deps(scope_key=None)), "p", "x")
        assert out == _NO_PERSON


class TestDeleteMemory:
    async def test_it_forgets_a_file(self, monkeypatch):
        monkeypatch.setattr(memory_store, "delete_file", AsyncMock(return_value="ok"))
        out = await _toolset("shared").delete_memory(_ctx(_deps()), "prefs")
        assert out == "Forgot memory 'prefs'."

    async def test_a_missing_file_says_so(self, monkeypatch):
        monkeypatch.setattr(memory_store, "delete_file", AsyncMock(return_value="missing"))
        out = await _toolset("shared").delete_memory(_ctx(_deps()), "gone")
        assert out == "No memory named 'gone' to forget."

    async def test_an_operator_file_is_protected(self, monkeypatch):
        monkeypatch.setattr(memory_store, "delete_file", AsyncMock(return_value="protected"))
        out = await _toolset("shared").delete_memory(_ctx(_deps()), "policy")
        assert "operator" in out and "cannot be removed" in out

    async def test_it_refuses_a_per_user_run_with_no_person(self, monkeypatch):
        monkeypatch.setattr(memory_store, "delete_file", AsyncMock())
        out = await _toolset("per_user").delete_memory(_ctx(_deps(scope_key=None)), "p")
        assert out == _NO_PERSON


class TestRemember:
    async def test_it_stores_a_fact_scoped_to_the_partition(self, monkeypatch):
        remember = AsyncMock()
        monkeypatch.setattr(memory_store, "remember", remember)
        out = await _toolset("per_user").remember(_ctx(_deps(scope_key="user:9")), "likes tea")
        assert out == "Remembered."
        assert remember.await_args.kwargs["scope_key"] == "user:9"
        assert remember.await_args.kwargs["content"] == "likes tea"

    async def test_it_refuses_a_per_user_run_with_no_person(self, monkeypatch):
        remember = AsyncMock()
        monkeypatch.setattr(memory_store, "remember", remember)
        out = await _toolset("per_user").remember(_ctx(_deps(scope_key=None)), "x")
        assert out == _NO_PERSON
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
        out = await _toolset("shared").recall(_ctx(_deps()), "what do they like")
        assert out == "- likes tea\n- lives in Berlin"

    async def test_nothing_relevant_says_so(self, monkeypatch):
        monkeypatch.setattr(memory_store, "recall", AsyncMock(return_value=[]))
        out = await _toolset("shared").recall(_ctx(_deps()), "anything")
        assert out == "No relevant memories."

    async def test_it_refuses_a_per_user_run_with_no_person(self, monkeypatch):
        recall = AsyncMock()
        monkeypatch.setattr(memory_store, "recall", recall)
        out = await _toolset("per_user").recall(_ctx(_deps(scope_key=None)), "x")
        assert out == _NO_PERSON
        recall.assert_not_awaited()


class TestCapability:
    def test_the_toolset_is_built_once(self):
        cap = Memory(partition="shared")
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


class TestConfig:
    def test_partition_rejects_an_unknown_value(self):
        with pytest.raises(ValueError):
            MemoryConfig(partition="everyone")  # ty: ignore[invalid-argument-type]

    def test_defaults(self):
        config = MemoryConfig()
        assert config.enable_files is True
        assert config.enable_facts is True
        assert config.partition == "shared"
        assert config.backend == "native"

    def test_mem0_without_facts_normalizes_to_native(self):
        """mem0 stores facts only, so a facts-off config cannot require its key (H1)."""
        assert MemoryConfig(backend="mem0", enable_facts=False).backend == "native"
        assert MemoryConfig(backend="mem0", enable_facts=True).backend == "mem0"


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
            config=MemoryConfig(enable_files=False, enable_facts=True, partition="per_user"),
        )
        cap = _build(ctx)
        assert isinstance(cap, Memory)
        assert cap.partition == "per_user"
        assert cap.enable_files is False
        assert cap.enable_facts is True

    def test_it_falls_back_to_default_config(self):
        ctx = CapabilityBuildContext(binding=CapabilityBinding(capability_id="memory"), config=None)
        assert isinstance(_build(ctx), Memory)

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
            partition="shared",
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
        out = await self._mem0_toolset().remember(_ctx(_deps()), "likes tea")
        assert out == "Remembered."
        native.assert_not_awaited()
        assert mem0.await_args.kwargs["api_key"] == "k"
        assert mem0.await_args.kwargs["base_url"] == "https://m"

    async def test_recall_routes_to_mem0(self, monkeypatch):
        monkeypatch.setattr(
            memory_store,
            "mem0_recall",
            AsyncMock(return_value=[FactHit(content="likes tea", score=0.9)]),
        )
        native = AsyncMock()
        monkeypatch.setattr(memory_store, "recall", native)
        out = await self._mem0_toolset().recall(_ctx(_deps()), "q")
        assert out == "- likes tea"
        native.assert_not_awaited()

    def test_the_native_backend_ignores_a_stray_key(self):
        toolset = MemoryToolset(
            partition="shared",
            enable_files=False,
            enable_facts=True,
            backend="native",
            mem0_api_key="k",
        )
        assert toolset._mem0_key is None
