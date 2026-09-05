"""Tests for the memory capability - the agent's three stores and its tools.

The things worth guarding: a read reaches exactly the stores the run's audience
admits and never another person's or another room's; a write defaults to the
audience's own store, which can leak nothing, and the model may pick a store but
never a *key*; a write to a store the run has none of is refused rather than
silently redirected; writing narrower than the audience is allowed and widening
is the one thing behind a lever; an agent cannot edit or delete operator-authored
files; and the audience derivation - the isolation surface - is tested in full.
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
    memory_audience_for,
    memory_requested,
)
from app.agents.capabilities.memory._capability import _preamble
from app.agents.capabilities.memory._toolset import (
    _MAX_DESCRIPTION,
    _MAX_KIND,
    _MAX_NAME,
    _MAX_RECALL_LIMIT,
    _NO_PERSONAL_WRITE,
    _NO_ROOM_WRITE,
    _NO_SCOPE,
    _NO_SHARED_WRITE,
    MemoryToolset,
)
from app.agents.deps import AgentDeps
from app.agents.memory_scope import MemoryAudience
from app.core.exceptions import BadRequestError
from app.core.memory_keys import (
    MemoryOwnerKind,
    channel_person_owner_key,
    owner_kind,
    parse_owner_selector,
    person_owner_key,
    room_owner_key,
)
from app.core.secret_kinds import ApiKeySecret
from app.services import memory as memory_store
from app.services.memory import FactHit, MemoryFileIndexEntry

pytestmark = pytest.mark.anyio

ORG = uuid4()
AGENT = uuid4()
PERSON = "person:42"
ROOM = "room:slack:C1"


def _deps(*, org=ORG, agent=AGENT, person=None, room=None) -> AgentDeps:
    """Deps for a run with the given audience. No person and no room is the
    anonymous audience - a widget visitor - which reads the org store alone."""
    return AgentDeps(
        organization_id=org,
        agent_id=agent,
        memory_audience=MemoryAudience(person_key=person, room_key=room),
    )


def _ctx(deps: AgentDeps, *, retry: int = 0, max_retries: int = 1) -> RunContext[AgentDeps]:
    return RunContext(
        deps=deps, model=TestModel(), usage=RunUsage(), retry=retry, max_retries=max_retries
    )


def _toolset() -> MemoryToolset:
    """A toolset with both stores on, so any tool under test is present."""
    return MemoryToolset(enable_files=True, enable_facts=True)


def _entry(
    name: str,
    *,
    description: str | None = None,
    kind: str = "note",
    owner: MemoryOwnerKind = MemoryOwnerKind.ORG,
) -> MemoryFileIndexEntry:
    return MemoryFileIndexEntry(name=name, description=description, kind=kind, owner=owner)


class TestAudienceDerivation:
    """The isolation surface: who a run is attributed to, and where it is heard."""

    def test_a_real_subject_keys_on_their_account(self):
        assert memory_audience_for(
            channel_identity_id=None,
            user_id="u-1",
            subject_is_publisher_fallback=False,
            room_key=None,
        ) == MemoryAudience(person_key="person:u-1", room_key=None)

    def test_a_linked_chat_account_reaches_the_same_store_as_web_chat(self):
        """The join the whole redesign turns on: a member writing from a linked
        Slack account already runs as themselves, so their direct messages and
        their browser reach one store rather than two (#788)."""
        web = memory_audience_for(
            channel_identity_id=None,
            user_id="u-1",
            subject_is_publisher_fallback=False,
            room_key=None,
        )
        dm = memory_audience_for(
            channel_identity_id=uuid4(),
            user_id="u-1",
            subject_is_publisher_fallback=False,
            room_key=None,
        )
        assert web == dm

    def test_an_unlinked_chat_account_keys_on_the_identity(self):
        """No app user to key on, so the account is the person - still isolated,
        just named by the account they wrote from."""
        chan = uuid4()
        assert memory_audience_for(
            channel_identity_id=chan,
            user_id="the-publisher",
            subject_is_publisher_fallback=True,
            room_key=None,
        ) == MemoryAudience(person_key=f"person:chan:{chan}", room_key=None)

    def test_a_publisher_fallback_with_no_chat_account_has_no_person(self):
        """The hosted/widget case: `user_id` is the owner, not the visitor, so
        keying on it would collapse every visitor onto the owner's store."""
        assert memory_audience_for(
            channel_identity_id=None,
            user_id="owner",
            subject_is_publisher_fallback=True,
            room_key=None,
        ) == MemoryAudience(person_key=None, room_key=None)

    def test_no_subject_at_all_has_no_person(self):
        assert memory_audience_for(
            channel_identity_id=None,
            user_id=None,
            subject_is_publisher_fallback=False,
            room_key=None,
        ) == MemoryAudience(person_key=None, room_key=None)

    def test_a_room_is_carried_and_leaves_the_speaker_known(self):
        audience = memory_audience_for(
            channel_identity_id=None,
            user_id="u-1",
            subject_is_publisher_fallback=False,
            room_key=ROOM,
        )
        assert audience == MemoryAudience(person_key="person:u-1", room_key=ROOM)
        assert not audience.private


class TestReadKeys:
    """Which stores an audience admits, and in what precedence."""

    def test_a_private_run_reads_the_person_then_the_organization(self):
        audience = MemoryAudience(person_key=PERSON)
        assert audience.read_keys(allow_personal=True) == (PERSON, None)

    def test_a_room_run_does_not_read_the_speakers_private_store(self):
        """The defect the redesign exists to fix: a note taken alone with somebody
        must not be readable where the whole channel sees the answer (#788)."""
        audience = MemoryAudience(person_key=PERSON, room_key=ROOM)
        assert audience.read_keys(allow_personal=True) == (ROOM, None)

    def test_an_anonymous_run_reads_the_organization_alone(self):
        assert MemoryAudience().read_keys(allow_personal=True) == (None,)

    def test_allow_personal_off_drops_the_person_arm(self):
        audience = MemoryAudience(person_key=PERSON)
        assert audience.read_keys(allow_personal=False) == (None,)

    def test_the_organization_store_is_always_readable(self):
        for audience in (
            MemoryAudience(),
            MemoryAudience(person_key=PERSON),
            MemoryAudience(person_key=PERSON, room_key=ROOM),
        ):
            assert None in audience.read_keys(allow_personal=True)


class TestDefaultScope:
    """The default is the audience's own store, which can leak nothing: whoever
    reads it back has already heard the conversation it came from."""

    def test_a_room_run_defaults_to_the_room(self):
        assert MemoryAudience(person_key=PERSON, room_key=ROOM).default_scope() == "room"

    def test_a_private_run_defaults_to_the_person(self):
        assert MemoryAudience(person_key=PERSON).default_scope() == "personal"

    def test_an_anonymous_run_defaults_to_the_organization(self):
        assert MemoryAudience().default_scope() == "shared"


class TestOwnerKeys:
    """The three key shapes and the two questions asked of them."""

    def test_a_person_key_reads_back_as_a_person(self):
        uid = uuid4()
        assert owner_kind(person_owner_key(uid)) is MemoryOwnerKind.PERSON

    def test_an_unlinked_chat_account_is_still_a_person(self):
        assert owner_kind(channel_person_owner_key(uuid4())) is MemoryOwnerKind.PERSON

    def test_a_room_key_reads_back_as_a_room(self):
        assert owner_kind(room_owner_key("slack", "C1")) is MemoryOwnerKind.ROOM

    def test_no_key_is_the_organization(self):
        assert owner_kind(None) is MemoryOwnerKind.ORG

    def test_a_room_key_keeps_the_platform_so_two_platforms_cannot_collide(self):
        """Chat ids are only unique within a platform, and one agent can be reached
        from several."""
        assert room_owner_key("slack", "C1") != room_owner_key("telegram", "C1")

    @pytest.mark.parametrize("value", ["all", "org", "person", "room"])
    def test_a_filter_word_selects_a_kind_and_no_key(self, value):
        assert parse_owner_selector(value) == (None, value)

    @pytest.mark.parametrize("value", ["person:42", "room:slack:C1", "person:chan:9"])
    def test_a_key_selects_a_key_and_no_kind(self, value):
        """Never inferred into a kind: listing every person's store to somebody
        auditing one is the direction that leaks (#788)."""
        assert parse_owner_selector(value) == (value, None)


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
    """A read always resolves - the organization store alone at worst - and never
    refuses for want of a person or a room."""

    def test_a_private_run_reads_the_person_and_the_organization(self):
        assert _toolset()._read_scope(_ctx(_deps(person=PERSON))) == (
            ORG,
            AGENT,
            (PERSON, None),
        )

    def test_a_room_run_reads_the_room_and_the_organization_not_the_person(self):
        assert _toolset()._read_scope(_ctx(_deps(person=PERSON, room=ROOM))) == (
            ORG,
            AGENT,
            (ROOM, None),
        )

    def test_a_run_with_no_audience_reads_the_organization_alone(self):
        assert _toolset()._read_scope(_ctx(_deps())) == (ORG, AGENT, (None,))

    def test_a_surface_that_supplied_no_audience_at_all_still_reads(self):
        """`memory_audience=None` is a surface that gave no signal, not a refusal."""
        deps = AgentDeps(organization_id=ORG, agent_id=AGENT)
        assert _toolset()._read_scope(_ctx(deps)) == (ORG, AGENT, (None,))

    def test_a_run_without_org_or_agent_refuses(self):
        assert _toolset()._read_scope(_ctx(AgentDeps())) == _NO_SCOPE

    def test_a_delegate_does_not_inherit_the_audience(self):
        """`clone_for_subagent` drops the audience, so a delegate that shares the
        parent's `agent_id` cannot read the parent's person store as the visitor's -
        memory is a root-agent concern in v1."""
        root = _deps(person=PERSON, room=ROOM)
        assert root.clone_for_subagent().memory_audience is None


class TestWriteScope:
    """The model picks the store; the server picks the key. A write can only ever
    reach a store this run's audience admits, and is refused - never redirected -
    when it asks for one the run has none of."""

    def test_omitting_the_scope_writes_to_the_room_in_a_room(self):
        assert _toolset()._write_scope(_ctx(_deps(person=PERSON, room=ROOM)), None) == (
            ORG,
            AGENT,
            ROOM,
        )

    def test_omitting_the_scope_writes_to_the_person_in_private(self):
        assert _toolset()._write_scope(_ctx(_deps(person=PERSON)), None) == (ORG, AGENT, PERSON)

    def test_shared_resolves_to_the_organization_store(self):
        assert _toolset()._write_scope(_ctx(_deps(person=PERSON)), "shared") == (ORG, AGENT, None)

    def test_personal_resolves_to_the_runs_own_person_key(self):
        assert _toolset()._write_scope(_ctx(_deps(person=PERSON)), "personal") == (
            ORG,
            AGENT,
            PERSON,
        )

    def test_a_room_run_may_still_write_narrower_to_the_speakers_own_store(self):
        """Narrowing is always safe: the room already heard it, and the person's
        store is read by fewer people than that."""
        assert _toolset()._write_scope(_ctx(_deps(person=PERSON, room=ROOM)), "personal") == (
            ORG,
            AGENT,
            PERSON,
        )

    def test_personal_without_a_person_is_refused_never_redirected(self):
        assert _toolset()._write_scope(_ctx(_deps()), "personal") == _NO_PERSONAL_WRITE

    def test_room_outside_a_room_is_refused_never_redirected(self):
        assert _toolset()._write_scope(_ctx(_deps(person=PERSON)), "room") == _NO_ROOM_WRITE

    def test_a_run_without_org_or_agent_refuses(self):
        assert _toolset()._write_scope(_ctx(AgentDeps()), "shared") == _NO_SCOPE


class TestStoreLevers:
    """The two operator levers, resolved on the toolset."""

    def _levers(self, *, allow_personal=True, allow_agent_shared_writes=True) -> MemoryToolset:
        return MemoryToolset(
            enable_files=True,
            enable_facts=True,
            allow_personal=allow_personal,
            allow_agent_shared_writes=allow_agent_shared_writes,
        )

    def test_allow_personal_off_drops_the_person_from_reads(self):
        toolset = self._levers(allow_personal=False)
        assert toolset._read_scope(_ctx(_deps(person=PERSON))) == (ORG, AGENT, (None,))

    def test_allow_personal_off_keeps_the_room_readable(self):
        """The lever is about per-person memory, not about group memory."""
        toolset = self._levers(allow_personal=False)
        assert toolset._read_scope(_ctx(_deps(person=PERSON, room=ROOM))) == (
            ORG,
            AGENT,
            (ROOM, None),
        )

    def test_allow_personal_off_refuses_a_personal_write_even_with_a_person(self):
        toolset = self._levers(allow_personal=False)
        assert toolset._write_scope(_ctx(_deps(person=PERSON)), "personal") == _NO_PERSONAL_WRITE

    def test_allow_personal_off_still_writes_shared(self):
        toolset = self._levers(allow_personal=False)
        assert toolset._write_scope(_ctx(_deps(person=PERSON)), "shared") == (ORG, AGENT, None)

    def test_barred_shared_writes_refuse_the_one_widening_direction(self):
        toolset = self._levers(allow_agent_shared_writes=False)
        assert toolset._write_scope(_ctx(_deps(person=PERSON)), "shared") == _NO_SHARED_WRITE

    def test_barred_shared_writes_refuse_an_anonymous_runs_default(self):
        """An anonymous run's own store *is* the organization's, so the lever bites
        the default too - otherwise it would be a lever the default walks past."""
        toolset = self._levers(allow_agent_shared_writes=False)
        assert toolset._write_scope(_ctx(_deps()), None) == _NO_SHARED_WRITE

    def test_barred_shared_writes_still_allow_personal(self):
        toolset = self._levers(allow_agent_shared_writes=False)
        assert toolset._write_scope(_ctx(_deps(person=PERSON)), "personal") == (
            ORG,
            AGENT,
            PERSON,
        )

    def test_barred_shared_writes_still_allow_the_room(self):
        toolset = self._levers(allow_agent_shared_writes=False)
        assert toolset._write_scope(_ctx(_deps(person=PERSON, room=ROOM)), "room") == (
            ORG,
            AGENT,
            ROOM,
        )

    def test_barred_shared_writes_do_not_touch_reads(self):
        toolset = self._levers(allow_agent_shared_writes=False)
        assert toolset._read_scope(_ctx(_deps(person=PERSON))) == (ORG, AGENT, (PERSON, None))


class TestPreamble:
    def test_it_names_all_three_stores(self):
        text = _preamble(allow_personal=True, allow_agent_shared_writes=True)
        assert "three stores" in text
        assert "group chat" in text and "organisation" in text

    def test_it_steers_the_model_away_from_choosing_a_scope(self):
        """The safe write is the one the model makes by saying nothing, so the
        preamble asks for the default rather than for a judgement about who is
        listening (#788)."""
        text = _preamble(allow_personal=True, allow_agent_shared_writes=True)
        assert "omit `scope`" in text

    def test_barred_shared_writes_say_the_organisation_store_is_read_only(self):
        text = _preamble(allow_personal=True, allow_agent_shared_writes=False)
        assert "curated by operators" in text and "read-only" in text
        assert "scope='shared'" not in text

    def test_personal_off_says_nothing_is_per_person(self):
        text = _preamble(allow_personal=False, allow_agent_shared_writes=True)
        assert "no private per-person memory" in text

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
        text = await instructions(_ctx(_deps(person=PERSON)))
        assert text.startswith("Search your memory before answering")
        assert "- likes nuts" in text and "- based in Warsaw" in text

    async def test_the_brief_reads_the_runs_own_stores(self, monkeypatch):
        brief = AsyncMock(return_value=["x"])
        monkeypatch.setattr(memory_store, "memory_brief", brief)
        await Memory(enable_facts=True, backend="native").get_instructions()(
            _ctx(_deps(person=PERSON))
        )
        assert brief.await_args.kwargs["read_keys"] == (PERSON, None)
        assert brief.await_args.kwargs["self_key"] == PERSON

    async def test_a_room_run_briefs_the_room_but_trusts_nobody_as_self(self, monkeypatch):
        """In a room the reader is not the only listener, so nothing is
        self-scoped: the brief falls back to operator-authored content alone, and
        a colleague's agent-written note cannot become another colleague's
        instructions (#788)."""
        brief = AsyncMock(return_value=["x"])
        monkeypatch.setattr(memory_store, "memory_brief", brief)
        await Memory(enable_facts=True, backend="native").get_instructions()(
            _ctx(_deps(person=PERSON, room=ROOM))
        )
        assert brief.await_args.kwargs["read_keys"] == (ROOM, None)
        assert brief.await_args.kwargs["self_key"] is None

    async def test_personal_off_briefs_the_organization_alone(self, monkeypatch):
        brief = AsyncMock(return_value=["x"])
        monkeypatch.setattr(memory_store, "memory_brief", brief)
        cap = Memory(enable_facts=True, backend="native", allow_personal=False)
        await cap.get_instructions()(_ctx(_deps(person=PERSON)))
        assert brief.await_args.kwargs["read_keys"] == (None,)
        assert brief.await_args.kwargs["self_key"] is None

    async def test_no_facts_leaves_the_preamble_alone(self, monkeypatch):
        monkeypatch.setattr(memory_store, "memory_brief", AsyncMock(return_value=[]))
        text = await Memory(enable_facts=True, backend="native").get_instructions()(
            _ctx(_deps(person=PERSON))
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
            _ctx(_deps(person=PERSON))
        )
        assert 1 <= text.count(big) < 5

    async def test_a_single_oversized_fact_is_dropped_not_injected(self, monkeypatch):
        # A fact past the whole budget is not spliced in unbounded; with nothing left
        # that fits, the brief falls back to the plain preamble.
        huge = "y" * 6000
        monkeypatch.setattr(memory_store, "memory_brief", AsyncMock(return_value=[huge]))
        text = await Memory(enable_facts=True, backend="native").get_instructions()(
            _ctx(_deps(person=PERSON))
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
            _ctx(_deps(person=PERSON))
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
            _ctx(_deps(person=PERSON))
        )
        assert "- likes tea" in text
        assert "- works in Kraków" in text
        assert "z" * 6000 not in text


class TestListMemory:
    async def test_it_labels_each_row_with_the_store_it_lives_in(self, monkeypatch):
        monkeypatch.setattr(
            memory_store,
            "list_files",
            AsyncMock(
                return_value=[
                    _entry("policy", description="the rules", kind="profile"),
                    _entry(
                        "prefs",
                        description="what they like",
                        kind="profile",
                        owner=MemoryOwnerKind.PERSON,
                    ),
                    _entry("scratch", description=None, kind="note", owner=MemoryOwnerKind.ROOM),
                ]
            ),
        )
        out = await _toolset().list_memory(_ctx(_deps(person=PERSON)))
        # The tag is the word `edit_memory` takes back as `scope`, so the index and
        # the write vocabulary cannot drift.
        assert "- [shared] policy [profile]: the rules" in out
        assert "- [personal] prefs [profile]: what they like" in out
        assert "- [room] scratch [note]" in out

    async def test_it_reads_with_the_runs_own_stores(self, monkeypatch):
        list_files = AsyncMock(return_value=[])
        monkeypatch.setattr(memory_store, "list_files", list_files)
        await _toolset().list_memory(_ctx(_deps(person=PERSON)))
        assert list_files.await_args.kwargs["read_keys"] == (PERSON, None)

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
    async def test_it_returns_the_body_reading_every_store_the_run_admits(self, monkeypatch):
        read = AsyncMock(return_value="the body")
        monkeypatch.setattr(memory_store, "read_file", read)
        out = await _toolset().read_memory(_ctx(_deps(person=PERSON)), "prefs")
        assert out == "the body"
        assert read.await_args.kwargs["read_keys"] == (PERSON, None)

    async def test_an_unknown_name_is_a_retry_naming_what_exists(self, monkeypatch):
        monkeypatch.setattr(memory_store, "read_file", AsyncMock(return_value=None))
        monkeypatch.setattr(
            memory_store,
            "list_files",
            AsyncMock(return_value=[_entry("prefs", owner=MemoryOwnerKind.PERSON)]),
        )
        with pytest.raises(ModelRetry, match="prefs"):
            await _toolset().read_memory(_ctx(_deps(person=PERSON)), "missing")

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
    async def test_personal_saves_to_the_runs_own_person_store(self, monkeypatch):
        write = AsyncMock(return_value=True)
        monkeypatch.setattr(memory_store, "write_file", write)
        out = await _toolset().write_memory(
            _ctx(_deps(person=PERSON)), "prefs", "likes tea", scope="personal", kind="profile"
        )
        assert out == "Saved memory 'prefs'."
        assert write.await_args.kwargs["owner_key"] == PERSON

    async def test_shared_saves_to_the_organization_store(self, monkeypatch):
        write = AsyncMock(return_value=True)
        monkeypatch.setattr(memory_store, "write_file", write)
        out = await _toolset().write_memory(
            _ctx(_deps(person=PERSON)), "policy", "org-wide", scope="shared"
        )
        assert out == "Saved memory 'policy'."
        assert write.await_args.kwargs["owner_key"] is None

    async def test_it_defaults_to_personal(self, monkeypatch):
        write = AsyncMock(return_value=True)
        monkeypatch.setattr(memory_store, "write_file", write)
        await _toolset().write_memory(_ctx(_deps(person=PERSON)), "prefs", "x")
        assert write.await_args.kwargs["owner_key"] == PERSON

    async def test_a_personal_write_with_no_person_is_refused_never_shared(self, monkeypatch):
        write = AsyncMock()
        monkeypatch.setattr(memory_store, "write_file", write)
        out = await _toolset().write_memory(_ctx(_deps()), "prefs", "x", scope="personal")
        assert out == _NO_PERSONAL_WRITE
        write.assert_not_awaited()

    async def test_a_shared_write_works_with_no_person(self, monkeypatch):
        write = AsyncMock(return_value=True)
        monkeypatch.setattr(memory_store, "write_file", write)
        out = await _toolset().write_memory(_ctx(_deps()), "policy", "x", scope="shared")
        assert out == "Saved memory 'policy'."
        assert write.await_args.kwargs["owner_key"] is None

    async def test_a_taken_name_is_reported_not_overwritten(self, monkeypatch):
        monkeypatch.setattr(memory_store, "write_file", AsyncMock(return_value=False))
        out = await _toolset().write_memory(_ctx(_deps(person=PERSON)), "prefs", "x")
        assert "already exists" in out and "edit_memory" in out

    async def test_metadata_past_a_column_width_is_refused_before_the_database(self, monkeypatch):
        # Past its column width the write would be an asyncpg `DataError` that fails the
        # run; the tool refuses it with a note the model can act on.
        write = AsyncMock()
        monkeypatch.setattr(memory_store, "write_file", write)
        toolset = _toolset()
        deps = _deps(person=PERSON)

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
        out = await _toolset().edit_memory(_ctx(_deps(person=PERSON)), "prefs", "new")
        assert out == "Updated memory 'prefs'."
        assert edit.await_args.kwargs["owner_key"] == PERSON

    async def test_shared_edits_the_organization_store(self, monkeypatch):
        edit = AsyncMock(return_value="ok")
        monkeypatch.setattr(memory_store, "edit_file", edit)
        await _toolset().edit_memory(_ctx(_deps(person=PERSON)), "policy", "new", scope="shared")
        assert edit.await_args.kwargs["owner_key"] is None

    async def test_a_missing_file_says_to_write_one(self, monkeypatch):
        monkeypatch.setattr(memory_store, "edit_file", AsyncMock(return_value="missing"))
        out = await _toolset().edit_memory(_ctx(_deps(person=PERSON)), "gone", "x")
        assert "No memory named 'gone'" in out and "write_memory" in out

    async def test_an_operator_file_is_protected(self, monkeypatch):
        monkeypatch.setattr(memory_store, "edit_file", AsyncMock(return_value="protected"))
        out = await _toolset().edit_memory(
            _ctx(_deps(person=PERSON)), "policy", "x", scope="shared"
        )
        assert "operator" in out and "cannot be changed" in out

    async def test_a_personal_edit_with_no_person_is_refused(self, monkeypatch):
        monkeypatch.setattr(memory_store, "edit_file", AsyncMock())
        out = await _toolset().edit_memory(_ctx(_deps()), "p", "x", scope="personal")
        assert out == _NO_PERSONAL_WRITE


class TestDeleteMemory:
    async def test_it_forgets_a_file(self, monkeypatch):
        monkeypatch.setattr(memory_store, "delete_file", AsyncMock(return_value="ok"))
        out = await _toolset().delete_memory(_ctx(_deps(person=PERSON)), "prefs")
        assert out == "Forgot memory 'prefs'."

    async def test_a_missing_file_says_so(self, monkeypatch):
        monkeypatch.setattr(memory_store, "delete_file", AsyncMock(return_value="missing"))
        out = await _toolset().delete_memory(_ctx(_deps(person=PERSON)), "gone")
        assert out == "No memory named 'gone' to forget."

    async def test_an_operator_file_is_protected(self, monkeypatch):
        monkeypatch.setattr(memory_store, "delete_file", AsyncMock(return_value="protected"))
        out = await _toolset().delete_memory(_ctx(_deps(person=PERSON)), "policy", scope="shared")
        assert "operator" in out and "cannot be removed" in out

    async def test_a_personal_delete_with_no_person_is_refused(self, monkeypatch):
        monkeypatch.setattr(memory_store, "delete_file", AsyncMock())
        out = await _toolset().delete_memory(_ctx(_deps()), "p", scope="personal")
        assert out == _NO_PERSONAL_WRITE


class TestRemember:
    async def test_personal_stores_a_fact_in_the_runs_person_store(self, monkeypatch):
        remember = AsyncMock()
        monkeypatch.setattr(memory_store, "remember", remember)
        out = await _toolset().remember(_ctx(_deps(person=PERSON)), "likes tea")
        assert out == "Remembered."
        assert remember.await_args.kwargs["owner_key"] == PERSON
        assert remember.await_args.kwargs["content"] == "likes tea"

    async def test_shared_stores_a_fact_org_wide(self, monkeypatch):
        remember = AsyncMock()
        monkeypatch.setattr(memory_store, "remember", remember)
        await _toolset().remember(
            _ctx(_deps(person=PERSON)), "the fiscal year starts in April", scope="shared"
        )
        assert remember.await_args.kwargs["owner_key"] is None

    async def test_a_personal_fact_with_no_person_is_refused(self, monkeypatch):
        remember = AsyncMock()
        monkeypatch.setattr(memory_store, "remember", remember)
        out = await _toolset().remember(_ctx(_deps()), "x", scope="personal")
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
        out = await _toolset().recall(_ctx(_deps(person=PERSON)), "what do they like")
        assert out == "- likes tea\n- lives in Berlin"

    async def test_it_recalls_across_both_tiers(self, monkeypatch):
        recall = AsyncMock(return_value=[])
        monkeypatch.setattr(memory_store, "recall", recall)
        await _toolset().recall(_ctx(_deps(person=PERSON)), "q")
        assert recall.await_args.kwargs["read_keys"] == (PERSON, None)

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

    def test_it_carries_the_three_store_preamble_by_default(self):
        instructions = Memory(enable_files=True).get_instructions()
        assert instructions == _preamble(allow_personal=True, allow_agent_shared_writes=True)
        assert "three stores" in instructions


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

    def test_there_is_no_owner_field_to_configure(self):
        """Whose memory a run reaches is decided by its audience, per run, so there
        is nothing on the spec to choose."""
        assert "partition" not in MemoryConfig.model_fields
        assert "owner" not in MemoryConfig.model_fields

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
        out = await self._mem0_toolset().remember(_ctx(_deps(person=PERSON)), "likes tea")
        assert out == "Remembered."
        native.assert_not_awaited()
        assert mem0.await_args.kwargs["api_key"] == "k"
        assert mem0.await_args.kwargs["base_url"] == "https://m"
        assert mem0.await_args.kwargs["owner_key"] == PERSON

    async def test_recall_routes_to_mem0_across_tiers(self, monkeypatch):
        monkeypatch.setattr(
            memory_store,
            "mem0_recall",
            AsyncMock(return_value=[FactHit(content="likes tea", score=0.9)]),
        )
        native = AsyncMock()
        monkeypatch.setattr(memory_store, "recall", native)
        out = await self._mem0_toolset().recall(_ctx(_deps(person=PERSON)), "q")
        assert out == "- likes tea"
        native.assert_not_awaited()

    async def test_recall_passes_the_personal_key_to_mem0(self, monkeypatch):
        recall = AsyncMock(return_value=[])
        monkeypatch.setattr(memory_store, "mem0_recall", recall)
        await self._mem0_toolset().recall(_ctx(_deps(person=PERSON)), "q")
        assert recall.await_args.kwargs["read_keys"] == (PERSON, None)

    def test_the_native_backend_ignores_a_stray_key(self):
        toolset = MemoryToolset(
            enable_files=False,
            enable_facts=True,
            backend="native",
            mem0_api_key="k",
        )
        assert toolset._mem0_key is None
