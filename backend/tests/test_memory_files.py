"""Tests for the memory-files capability.

The security property is one sentence and everything here serves it: **a run
touches exactly one store, the conversation's own.** A note taken alone with
somebody is not read back where a channel sees it, and a note the channel keeps
is not written into somebody's private store. That is decided server-side from
who is listening, so there is no scope argument for a model to get wrong - and
the tests that would have caught the old shape's mistakes are the ones asserting
that no tool takes one.

The second property is narrower and easy to lose: what reaches the *instructions*
is narrower than what the tools read. A tool result is something a model weighs;
instructions are what it obeys, so an index is injected only where its content
could have steered nobody but its reader.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.audience import RunAudience
from app.agents.capabilities import build
from app.agents.capabilities._registry import CapabilityBinding, CapabilityBuildContext
from app.agents.capabilities.memory_files import (
    INDEX_NAME,
    MemoryFiles,
    MemoryFilesConfig,
    _build,
)
from app.agents.capabilities.memory_files._capability import _MAX_INDEX_CHARS, _preamble
from app.agents.capabilities.memory_files._toolset import _NO_STORE, MemoryToolset
from app.agents.deps import AgentDeps
from app.agents.memory_scope import may_inject_memory, memory_owner_key
from app.core.memory_keys import is_person_key, person_owner_key, room_owner_key
from app.services import memory as memory_store

pytestmark = pytest.mark.anyio

ORG = uuid4()
AGENT = uuid4()
PERSON = uuid4()
PERSON_KEY = person_owner_key(PERSON)
ROOM_KEY = room_owner_key("slack", "C1")


def _deps(*, person: object = PERSON, room: str | None = None) -> AgentDeps:
    return AgentDeps(
        organization_id=ORG,
        agent_id=AGENT,
        audience=RunAudience(user_id=person, room_key=room),  # ty: ignore[invalid-argument-type]
    )


def _ctx(deps: AgentDeps, *, retry: int = 0) -> RunContext[AgentDeps]:
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), retry=retry, max_retries=1)


def _toolset(*, allow_personal: bool = True) -> MemoryToolset:
    return MemoryToolset(allow_personal=allow_personal)


def _entry(name: str, *, description: str | None = "d", kind: str = "note"):
    return memory_store.MemoryFileIndexEntry(name=name, description=description, kind=kind)


class TestWhichStoreARunTouches:
    """One store, resolved from the audience - never a union and never a choice."""

    def test_alone_with_somebody_it_is_theirs(self):
        assert memory_owner_key(RunAudience(user_id=PERSON), allow_personal=True) == PERSON_KEY

    def test_in_a_group_chat_it_is_the_chats(self):
        """And explicitly not the speaker's, even though the run knows who spoke:
        writing a private note in a channel, or reading one out there, is the
        defect the whole audience model exists to prevent (#788)."""
        audience = RunAudience(user_id=PERSON, room_key=ROOM_KEY)

        assert memory_owner_key(audience, allow_personal=True) == ROOM_KEY

    def test_an_anonymous_run_has_none(self):
        assert memory_owner_key(RunAudience(), allow_personal=True) is None

    def test_reading_and_writing_are_the_same_key(self):
        """A run that could write somewhere it cannot read would be saving into a
        void; one that could read somewhere it cannot write is the union this
        design removed."""
        audience = RunAudience(user_id=PERSON, room_key=ROOM_KEY)

        assert memory_owner_key(audience, allow_personal=True) == memory_owner_key(
            audience, allow_personal=True
        )

    def test_the_personal_lever_off_drops_the_person_store_entirely(self):
        assert memory_owner_key(RunAudience(user_id=PERSON), allow_personal=False) is None

    def test_the_personal_lever_off_leaves_group_chats_alone(self):
        """A compliance switch about private notes is not a switch about a channel
        everybody in it already reads."""
        audience = RunAudience(user_id=PERSON, room_key=ROOM_KEY)

        assert memory_owner_key(audience, allow_personal=False) == ROOM_KEY


class TestWhatMayBecomeInstructions:
    def test_a_private_run_may_be_shown_its_index(self):
        assert may_inject_memory(RunAudience(user_id=PERSON), allow_personal=True)

    def test_a_room_may_not_be_even_though_it_reads_the_store(self):
        """The speaker is known but is not the only listener, so a sentence one
        colleague left in the room would arrive as another colleague's
        instructions. It stays reachable with `read_memory`, which is a result
        rather than an order."""
        audience = RunAudience(user_id=PERSON, room_key=ROOM_KEY)

        assert not may_inject_memory(audience, allow_personal=True)
        assert memory_owner_key(audience, allow_personal=True) is not None

    def test_a_run_with_no_store_is_shown_nothing(self):
        assert not may_inject_memory(RunAudience(), allow_personal=True)

    def test_the_personal_lever_off_injects_nothing_privately(self):
        assert not may_inject_memory(RunAudience(user_id=PERSON), allow_personal=False)


class TestOwnerKeys:
    def test_a_person_key_names_the_account_not_the_surface(self):
        """Which is what makes web chat, the API and a linked chat account one
        store, and "forget everything about me" one key to delete."""
        assert person_owner_key(PERSON) == f"person:{PERSON}"
        assert is_person_key(person_owner_key(PERSON))

    def test_a_room_key_carries_its_platform(self):
        """Chat ids are only unique within a platform, and one agent can be reached
        from several."""
        assert room_owner_key("slack", "C1") != room_owner_key("telegram", "C1")
        assert not is_person_key(room_owner_key("slack", "C1"))


class TestThePreamble:
    def test_it_names_the_index_the_capability_injects(self):
        assert INDEX_NAME in _preamble(allow_personal=True)

    def test_it_leads_with_reading_rather_than_writing(self):
        """A model holding the tools and no standing instruction to look answers "I
        have nothing saved" with the note one call away."""
        preamble = _preamble(allow_personal=True)

        assert preamble.index("read") < preamble.index("save")

    def test_it_never_asks_the_model_to_reason_about_who_is_listening(self):
        """There is one store per conversation, resolved server-side, so there is
        no scope to choose - and a preamble that discussed one would invite the
        model to try."""
        assert "scope" not in _preamble(allow_personal=True).lower()

    def test_it_says_where_a_note_goes(self):
        preamble = _preamble(allow_personal=True)

        assert "group chat" in preamble
        assert "one to one" in preamble

    def test_the_personal_lever_off_says_there_is_nothing_to_save_one_to_one(self):
        assert "only in group chats" in _preamble(allow_personal=False)


class TestTheTools:
    async def test_no_tool_takes_a_store(self):
        """The old shape had a `scope` argument, and a model that chose `personal`
        in a room wrote a private note from a public conversation. There is nothing
        to choose now, which is why this is asserted on the schema rather than on
        behaviour."""
        toolset = _toolset()

        for name, tool in toolset.tools.items():
            properties = tool.tool_def.parameters_json_schema.get("properties", {})
            assert "scope" not in properties, name

    async def test_every_tool_refuses_the_same_way_when_there_is_no_store(self, monkeypatch):
        """One sentence for the whole capability rather than five variants, and a
        returned string rather than a retry: a store the run does not have is not
        something the model can fix by calling again."""
        toolset = _toolset()
        ctx = _ctx(AgentDeps())

        assert await toolset.list_memory(ctx) == _NO_STORE
        assert await toolset.read_memory(ctx, "prefs") == _NO_STORE
        assert await toolset.write_memory(ctx, "prefs", "x") == _NO_STORE
        assert await toolset.edit_memory(ctx, "prefs", "x") == _NO_STORE
        assert await toolset.delete_memory(ctx, "prefs") == _NO_STORE

    async def test_an_anonymous_run_reaches_nothing(self, monkeypatch):
        called = AsyncMock()
        monkeypatch.setattr(memory_store, "list_files", called)

        assert await _toolset().list_memory(_ctx(_deps(person=None))) == _NO_STORE
        assert not called.await_count


class TestListMemory:
    async def test_it_lists_the_stores_own_notes(self, monkeypatch):
        monkeypatch.setattr(
            memory_store,
            "list_files",
            AsyncMock(return_value=[_entry("prefs", description="what they like", kind="profile")]),
        )

        out = await _toolset().list_memory(_ctx(_deps()))

        assert out == "- prefs [profile]: what they like"

    async def test_a_note_with_no_description_still_lists(self, monkeypatch):
        monkeypatch.setattr(
            memory_store,
            "list_files",
            AsyncMock(return_value=[_entry("scratch", description=None)]),
        )

        assert await _toolset().list_memory(_ctx(_deps())) == "- scratch [note]"

    async def test_it_asks_for_the_runs_one_store(self, monkeypatch):
        listed = AsyncMock(return_value=[])
        monkeypatch.setattr(memory_store, "list_files", listed)

        await _toolset().list_memory(_ctx(_deps(room=ROOM_KEY)))

        assert listed.await_args.kwargs["owner_key"] == ROOM_KEY

    async def test_an_empty_store_says_so(self, monkeypatch):
        monkeypatch.setattr(memory_store, "list_files", AsyncMock(return_value=[]))

        assert await _toolset().list_memory(_ctx(_deps())) == "No notes saved yet."


class TestReadMemory:
    async def test_it_returns_the_body(self, monkeypatch):
        read = AsyncMock(return_value="the body")
        monkeypatch.setattr(memory_store, "read_file", read)

        assert await _toolset().read_memory(_ctx(_deps()), "prefs") == "the body"
        assert read.await_args.kwargs["owner_key"] == PERSON_KEY

    async def test_an_unknown_name_is_a_retry_naming_what_exists(self, monkeypatch):
        monkeypatch.setattr(memory_store, "read_file", AsyncMock(return_value=None))
        monkeypatch.setattr(memory_store, "list_files", AsyncMock(return_value=[_entry("prefs")]))

        with pytest.raises(ModelRetry, match="prefs"):
            await _toolset().read_memory(_ctx(_deps()), "missing")

    async def test_the_last_attempt_answers_rather_than_ending_the_run(self, monkeypatch):
        """A `ModelRetry` past the budget does not fail the call - it ends the whole
        run with `UnexpectedModelBehavior`, so the same wrong name asked twice would
        take the conversation with it."""
        monkeypatch.setattr(memory_store, "read_file", AsyncMock(return_value=None))
        monkeypatch.setattr(memory_store, "list_files", AsyncMock(return_value=[]))

        answered = await _toolset().read_memory(_ctx(_deps(), retry=1), "missing")

        assert "missing" in answered
        assert "none" in answered


class TestWriteMemory:
    async def test_it_saves_into_the_runs_own_store(self, monkeypatch):
        write = AsyncMock(return_value=True)
        monkeypatch.setattr(memory_store, "write_file", write)

        out = await _toolset().write_memory(_ctx(_deps()), "prefs", "likes tea", kind="profile")

        assert out == "Saved note 'prefs'."
        assert write.await_args.kwargs["owner_key"] == PERSON_KEY
        assert write.await_args.kwargs["kind"] == "profile"

    async def test_a_room_run_writes_the_room_and_never_the_speaker(self, monkeypatch):
        write = AsyncMock(return_value=True)
        monkeypatch.setattr(memory_store, "write_file", write)

        await _toolset().write_memory(_ctx(_deps(room=ROOM_KEY)), "prefs", "x")

        assert write.await_args.kwargs["owner_key"] == ROOM_KEY

    async def test_a_taken_name_is_reported_not_overwritten(self, monkeypatch):
        monkeypatch.setattr(memory_store, "write_file", AsyncMock(return_value=False))

        out = await _toolset().write_memory(_ctx(_deps()), "prefs", "x")

        assert "already exists" in out
        assert "edit_memory" in out

    @pytest.mark.parametrize(
        ("field", "kwargs"),
        [
            ("name", {"name": "n" * 65}),
            ("kind", {"kind": "k" * 33}),
            ("description", {"description": "d" * 501}),
        ],
    )
    async def test_metadata_past_a_column_width_is_refused_before_the_database(
        self, monkeypatch, field, kwargs
    ):
        """A write past the column width is an asyncpg `DataError`, which fails the
        whole run rather than the call - so the tool refuses first and says which
        argument was too long."""
        write = AsyncMock()
        monkeypatch.setattr(memory_store, "write_file", write)
        arguments = {"name": "prefs", "content": "x", **kwargs}

        out = await _toolset().write_memory(_ctx(_deps()), **arguments)

        assert "too long" in out
        assert field in out
        assert not write.await_count


class TestEditMemory:
    async def test_it_replaces_the_body(self, monkeypatch):
        edit = AsyncMock(return_value=True)
        monkeypatch.setattr(memory_store, "edit_file", edit)

        assert await _toolset().edit_memory(_ctx(_deps()), "prefs", "new") == (
            "Updated note 'prefs'."
        )
        assert edit.await_args.kwargs["owner_key"] == PERSON_KEY

    async def test_a_name_this_store_does_not_hold_says_to_write_one(self, monkeypatch):
        monkeypatch.setattr(memory_store, "edit_file", AsyncMock(return_value=False))

        out = await _toolset().edit_memory(_ctx(_deps()), "prefs", "new")

        assert "write_memory" in out


class TestDeleteMemory:
    async def test_it_forgets_a_note(self, monkeypatch):
        delete = AsyncMock(return_value=True)
        monkeypatch.setattr(memory_store, "delete_file", delete)

        assert await _toolset().delete_memory(_ctx(_deps()), "prefs") == "Forgot note 'prefs'."
        assert delete.await_args.kwargs["owner_key"] == PERSON_KEY

    async def test_a_name_this_store_does_not_hold_says_so(self, monkeypatch):
        monkeypatch.setattr(memory_store, "delete_file", AsyncMock(return_value=False))

        assert "No note named" in await _toolset().delete_memory(_ctx(_deps()), "prefs")


class TestIndexInjection:
    def _capability(self, *, allow_personal: bool = True) -> MemoryFiles:
        return MemoryFiles(allow_personal=allow_personal)

    async def test_a_private_run_is_shown_its_own_index(self, monkeypatch):
        monkeypatch.setattr(memory_store, "read_file", AsyncMock(return_value="- prefs: tea"))

        instructions = await self._capability().get_instructions()(_ctx(_deps()))

        assert "Here is what you already have written down:" in instructions
        assert "- prefs: tea" in instructions

    async def test_it_asks_for_this_runs_index_and_nobody_elses(self, monkeypatch):
        read = AsyncMock(return_value="x")
        monkeypatch.setattr(memory_store, "read_file", read)

        await self._capability().get_instructions()(_ctx(_deps()))

        assert read.await_args.kwargs["owner_key"] == PERSON_KEY
        assert read.await_args.kwargs["name"] == INDEX_NAME

    async def test_a_room_run_is_shown_nothing_though_it_can_still_read(self, monkeypatch):
        read = AsyncMock(return_value="- something a colleague wrote")
        monkeypatch.setattr(memory_store, "read_file", read)

        instructions = await self._capability().get_instructions()(_ctx(_deps(room=ROOM_KEY)))

        assert "already have written down" not in instructions
        assert not read.await_count

    async def test_a_run_with_no_person_is_shown_nothing(self, monkeypatch):
        monkeypatch.setattr(memory_store, "read_file", AsyncMock(return_value="x"))

        instructions = await self._capability().get_instructions()(_ctx(_deps(person=None)))

        assert "already have written down" not in instructions

    async def test_a_run_with_no_organisation_or_agent_is_shown_nothing(self, monkeypatch):
        read = AsyncMock(return_value="x")
        monkeypatch.setattr(memory_store, "read_file", read)

        await self._capability().get_instructions()(_ctx(AgentDeps(audience=RunAudience(PERSON))))

        assert not read.await_count

    async def test_the_personal_lever_off_shows_nothing_privately(self, monkeypatch):
        read = AsyncMock(return_value="x")
        monkeypatch.setattr(memory_store, "read_file", read)

        await self._capability(allow_personal=False).get_instructions()(_ctx(_deps()))

        assert not read.await_count

    @pytest.mark.parametrize("body", [None, "", "   \n  "])
    async def test_an_empty_index_gets_no_heading(self, monkeypatch, body):
        """A heading over nothing reads as an instruction that there is nothing to
        remember, which is the opposite of what an empty store means."""
        monkeypatch.setattr(memory_store, "read_file", AsyncMock(return_value=body))

        instructions = await self._capability().get_instructions()(_ctx(_deps()))

        assert instructions == _preamble(allow_personal=True)

    async def test_an_oversized_index_is_dropped_rather_than_cut(self, monkeypatch):
        """An index is a note like any other, so one `write_memory` could push the
        preamble out of the window - and half an index, ending mid-filename, is
        worse than none."""
        monkeypatch.setattr(
            memory_store, "read_file", AsyncMock(return_value="x" * (_MAX_INDEX_CHARS + 1))
        )

        instructions = await self._capability().get_instructions()(_ctx(_deps()))

        assert instructions == _preamble(allow_personal=True)


class TestTheCapability:
    def test_the_toolset_is_built_once(self):
        capability = MemoryFiles()

        assert capability.get_toolset() is capability.get_toolset()

    def test_it_carries_the_five_note_tools_and_nothing_else(self):
        toolset = MemoryFiles().get_toolset()

        assert set(toolset.tools) == {
            "list_memory",
            "read_memory",
            "write_memory",
            "edit_memory",
            "delete_memory",
        }

    async def test_the_instructions_are_a_per_request_callable(self):
        """They have to be: the second half is a database read scoped to the run's
        audience, which a static string could not do."""
        assert callable(MemoryFiles().get_instructions())


class TestTheBinding:
    def test_a_bound_capability_always_contributes_its_tools(self):
        """There is no configuration that switches every store off, so an agent that
        wants no notes does not bind it rather than binding it hollow."""
        built = build([CapabilityBinding(capability_id="memory_files", config={})])

        assert built[0].get_toolset() is not None

    def test_the_only_field_is_the_person_store(self):
        """Six fields became one: the backend is a separate capability now, and the
        organisation-wide store is gone because `context` already did that job."""
        assert set(MemoryFilesConfig.model_fields) == {"allow_personal"}

    def test_personal_memory_is_on_by_default(self):
        assert MemoryFilesConfig().allow_personal is True

    def test_it_falls_back_to_the_default_config(self):
        capability = _build(
            CapabilityBuildContext(
                binding=CapabilityBinding(capability_id="memory_files", config={}), config=None
            )
        )

        assert capability.allow_personal is True

    def test_it_carries_the_configured_lever(self):
        capability = _build(
            CapabilityBuildContext(
                binding=CapabilityBinding(capability_id="memory_files", config={}),
                config=MemoryFilesConfig(allow_personal=False),
            )
        )

        assert capability.allow_personal is False
