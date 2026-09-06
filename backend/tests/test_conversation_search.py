"""Tests for the conversation-search capability.

Two things are worth guarding here and neither is "does the query run" - that is
`tests/integration/test_conversation_search_repo.py`, against a real PostgreSQL,
because a full-text search asserted against a mock proves nothing about whether
words actually match.

What this file holds is the **refusal** and the **rendering**. The refusal,
because the corpus is one person's and the whole capability turns on it never
being read out where somebody else is listening; the rendering, because what
comes back is prompt, and a transcript that loses who spoke is a transcript a
model attributes to the wrong person.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.audience import RunAudience
from app.agents.capabilities import build
from app.agents.capabilities._registry import CapabilityBinding, CapabilityBuildContext
from app.agents.capabilities.conversation_search import (
    ConversationSearch,
    ConversationSearchConfig,
    _build,
)
from app.agents.capabilities.conversation_search._capability import _HABIT
from app.agents.capabilities.conversation_search._toolset import (
    _IN_A_ROOM,
    _MAX_TRANSCRIPT_CHARS,
    _MAX_TURN_CHARS,
    _NO_CORPUS,
    ConversationSearchToolset,
    _render,
    _speaker_label,
)
from app.agents.deps import AgentDeps
from app.services.conversation_search import (
    FoundConversation,
    Transcript,
    TranscriptTurn,
)

pytestmark = pytest.mark.anyio

ORG = uuid4()
PERSON = uuid4()
THREAD = uuid4()
AT = datetime(2026, 8, 14, 10, 4, tzinfo=UTC)


def _deps(*, org: UUID | None = ORG, user: UUID | None = PERSON, room: str | None = None):
    return AgentDeps(
        organization_id=org,
        agent_id=uuid4(),
        audience=None if (user is None and room is None) else RunAudience(user, room),
    )


def _ctx(deps: AgentDeps, *, retry: int = 0) -> RunContext[AgentDeps]:
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), retry=retry, max_retries=1)


def _hit(**overrides) -> FoundConversation:
    return FoundConversation(
        **{
            "conversation_id": THREAD,
            "title": "Q3 pricing",
            "updated_at": AT,
            "hits": 3,
            "snippet": "the **pricing** floor stays",
            "speaker_role": "assistant",
            "speaker_name": None,
            **overrides,
        }
    )


def _transcript(turns: list[TranscriptTurn], *, total: int | None = None, skip: int = 0):
    return Transcript(
        conversation_id=THREAD,
        title="Q3 pricing",
        turns=turns,
        total=len(turns) if total is None else total,
        skip=skip,
    )


def _turn(role="user", speaker="Anna", content="what did we decide") -> TranscriptTurn:
    return TranscriptTurn(role=role, speaker=speaker, content=content, at=AT)


class TestWhoMayHearTheAnswer:
    """The corpus is one person's, so it may only be read where they are alone."""

    async def test_a_group_chat_is_refused_rather_than_narrowed(self):
        """The threads reachable from a channel run are the *sender's* own, so
        answering from them would read one person's private conversations out to
        everybody in the room. Both tools refuse, and the refusal says why rather
        than reporting an empty search - which would read as "nothing was said"."""
        toolset = ConversationSearchToolset(max_results=10)
        ctx = _ctx(_deps(room="room:slack:C1"))

        assert await toolset.search_conversations(ctx, "pricing") == _IN_A_ROOM
        assert await toolset.read_conversation(ctx, str(THREAD)) == _IN_A_ROOM

    async def test_an_anonymous_visitor_has_nothing_to_search(self):
        """A widget or an embed runs as the publisher standing in for whoever is
        typing, so there is no person whose conversations these are. Keying on the
        publisher would hand every visitor the owner's history."""
        toolset = ConversationSearchToolset(max_results=10)
        ctx = _ctx(_deps(user=None))

        assert await toolset.search_conversations(ctx, "pricing") == _NO_CORPUS

    async def test_a_run_with_no_organization_searches_nothing(self):
        toolset = ConversationSearchToolset(max_results=10)

        assert await toolset.search_conversations(_ctx(_deps(org=None)), "x") == _NO_CORPUS

    async def test_the_person_is_never_taken_from_the_model(self):
        """The tool signature has no user and no organization in it. Both come off
        the deps the runner resolved, which is what makes "an agent can only search
        the asker's conversations" a property of the code."""
        toolset = ConversationSearchToolset(max_results=10)
        schema = toolset.tools["search_conversations"].tool_def.parameters_json_schema

        assert set(schema["properties"]) == {"query", "limit"}


class TestSearching:
    async def test_it_asks_for_the_person_on_the_deps_and_nobody_else(self):
        toolset = ConversationSearchToolset(max_results=10)
        with patch(
            "app.services.conversation_search.search", new=AsyncMock(return_value=[_hit()])
        ) as search:
            await toolset.search_conversations(_ctx(_deps()), "pricing")

        assert search.await_args.kwargs["user_id"] == PERSON
        assert search.await_args.kwargs["organization_id"] == ORG

    async def test_a_result_carries_the_id_the_read_tool_needs(self):
        """A snippet the model cannot open is a dead end, so the id is in the
        block rather than left to a second search."""
        toolset = ConversationSearchToolset(max_results=10)
        with patch("app.services.conversation_search.search", new=AsyncMock(return_value=[_hit()])):
            answer = await toolset.search_conversations(_ctx(_deps()), "pricing")

        assert str(THREAD) in answer
        assert "Q3 pricing" in answer
        assert "3 matching turns" in answer
        assert "the **pricing** floor stays" in answer

    async def test_one_match_is_not_reported_as_plural(self):
        toolset = ConversationSearchToolset(max_results=10)
        with patch(
            "app.services.conversation_search.search",
            new=AsyncMock(return_value=[_hit(hits=1, title=None)]),
        ):
            answer = await toolset.search_conversations(_ctx(_deps()), "pricing")

        assert "1 conversation matched" in answer
        assert "1 matching turn\n" in answer
        assert "Untitled conversation" in answer

    async def test_a_channel_hit_says_which_person_said_it(self):
        """A room has several people in it; a snippet that called all of them
        `USER` would be attributed to whoever the model assumed."""
        toolset = ConversationSearchToolset(max_results=10)
        with patch(
            "app.services.conversation_search.search",
            new=AsyncMock(return_value=[_hit(speaker_role="user", speaker_name="Anna Kowalska")]),
        ):
            answer = await toolset.search_conversations(_ctx(_deps()), "pricing")

        assert "USER (Anna Kowalska):" in answer

    async def test_nothing_found_is_a_result_and_says_what_to_try(self):
        """Not a retry: an empty search is the answer, and inviting the model to
        call again with the same words is how a tool budget is spent. The words
        matter because the index does not stem - the next call should try another
        form rather than the same one."""
        toolset = ConversationSearchToolset(max_results=10)
        with patch("app.services.conversation_search.search", new=AsyncMock(return_value=[])):
            answer = await toolset.search_conversations(_ctx(_deps()), "pricing")

        assert "No conversation you can read mentions" in answer
        assert "form" in answer

    async def test_an_empty_query_is_the_models_mistake(self):
        toolset = ConversationSearchToolset(max_results=10)
        with patch("app.services.conversation_search.search", new=AsyncMock()) as search:
            answer = await toolset.search_conversations(_ctx(_deps(), retry=1), "   ")

        assert "was empty" in answer
        assert not search.await_count

    @pytest.mark.parametrize(("asked", "expected"), [(None, 10), (3, 3), (99, 10), (0, 1), (-4, 1)])
    async def test_the_agents_ceiling_is_the_ceiling(self, asked, expected):
        """`limit` is model-controlled, so it is clamped rather than trusted: each
        result costs context, and the operator's number is the budget."""
        toolset = ConversationSearchToolset(max_results=10)
        with patch(
            "app.services.conversation_search.search", new=AsyncMock(return_value=[])
        ) as search:
            await toolset.search_conversations(_ctx(_deps()), "pricing", asked)

        assert search.await_args.kwargs["limit"] == expected


class TestReading:
    async def test_a_transcript_splits_into_user_and_ai(self):
        toolset = ConversationSearchToolset(max_results=10)
        transcript = _transcript(
            [
                _turn(role="user", speaker="Anna", content="what did we decide"),
                _turn(role="assistant", speaker="Support", content="the floor stays"),
            ]
        )
        with patch("app.services.conversation_search.read", new=AsyncMock(return_value=transcript)):
            answer = await toolset.read_conversation(_ctx(_deps()), str(THREAD))

        assert "**USER (Anna)**" in answer
        assert "**AI (Support)**" in answer
        assert answer.index("what did we decide") < answer.index("the floor stays")
        assert "Turns 1 to 2 of 2." in answer

    async def test_a_turn_nothing_can_name_keeps_its_role(self):
        toolset = ConversationSearchToolset(max_results=10)
        transcript = _transcript([_turn(role="system", speaker=None, content="be brief")])
        with patch("app.services.conversation_search.read", new=AsyncMock(return_value=transcript)):
            answer = await toolset.read_conversation(_ctx(_deps()), str(THREAD))

        assert "**SYSTEM**" in answer

    async def test_a_long_thread_says_where_to_carry_on(self):
        """Without it a model handed sixty of two hundred turns reasons about the
        slice as though it were the conversation."""
        toolset = ConversationSearchToolset(max_results=10)
        transcript = _transcript([_turn()], total=200, skip=60)
        with patch("app.services.conversation_search.read", new=AsyncMock(return_value=transcript)):
            answer = await toolset.read_conversation(_ctx(_deps()), str(THREAD))

        assert "Turns 61 to 61 of 200." in answer
        assert "skip=61" in answer

    async def test_a_window_past_the_end_says_so_rather_than_claiming_a_range(self):
        toolset = ConversationSearchToolset(max_results=10)
        with patch(
            "app.services.conversation_search.read",
            new=AsyncMock(return_value=_transcript([], total=4, skip=90)),
        ):
            answer = await toolset.read_conversation(_ctx(_deps()), str(THREAD))

        assert "Nothing to read from turn 91" in answer
        assert "4 turns" in answer

    async def test_an_id_that_is_not_an_id_is_the_models_mistake(self):
        toolset = ConversationSearchToolset(max_results=10)
        with patch("app.services.conversation_search.read", new=AsyncMock()) as read:
            answer = await toolset.read_conversation(_ctx(_deps(), retry=1), "the pricing one")

        assert "not a conversation id" in answer
        assert not read.await_count

    async def test_somebody_elses_conversation_is_indistinguishable_from_a_wrong_id(self):
        """The service answers `None` to both, deliberately: telling them apart
        would confirm that a thread exists in somebody else's history."""
        toolset = ConversationSearchToolset(max_results=10)
        with patch("app.services.conversation_search.read", new=AsyncMock(return_value=None)):
            answer = await toolset.read_conversation(_ctx(_deps(), retry=1), str(uuid4()))

        assert "No conversation you can read has that id" in answer

    async def test_the_skip_the_model_sends_cannot_go_backwards(self):
        toolset = ConversationSearchToolset(max_results=10)
        with patch(
            "app.services.conversation_search.read",
            new=AsyncMock(return_value=_transcript([_turn()])),
        ) as read:
            await toolset.read_conversation(_ctx(_deps()), str(THREAD), -20)

        assert read.await_args.kwargs["skip"] == 0


class TestWhatARenderedTranscriptCosts:
    def test_one_enormous_turn_is_cut_rather_than_left_whole(self):
        rendered = _render(_transcript([_turn(content="x" * (_MAX_TURN_CHARS * 3))]))

        assert "(turn cut short)" in rendered
        assert len(rendered) < _MAX_TURN_CHARS * 2

    def test_the_window_stops_at_the_budget_and_reports_where(self):
        """Sixty turns is not a bounded amount of text, so the character budget is
        the second ceiling - and the footer has to report what was actually
        written rather than what was fetched."""
        turns = [_turn(content="y" * 1000) for _ in range(40)]
        rendered = _render(_transcript(turns, total=40))

        assert len(rendered) < _MAX_TRANSCRIPT_CHARS + _MAX_TURN_CHARS
        assert "of 40." in rendered
        assert "Turns 1 to 40" not in rendered

    def test_the_first_turn_is_written_even_when_it_alone_blows_the_budget(self):
        """Otherwise a thread opening with a pasted document renders as nothing at
        all, and the model is told turns 1 to 0 exist."""
        rendered = _render(_transcript([_turn(content="z" * _MAX_TURN_CHARS)], total=2))

        assert "Turns 1 to 1 of 2." in rendered

    def test_a_turn_with_no_text_is_marked_rather_than_dropped(self):
        assert "(no text)" in _render(_transcript([_turn(content="   ")]))

    def test_an_untitled_thread_is_still_headed(self):
        rendered = _render(
            Transcript(conversation_id=THREAD, title=None, turns=[_turn()], total=1, skip=0)
        )

        assert rendered.startswith("# Untitled conversation")


class TestSpeakerLabels:
    @pytest.mark.parametrize(
        ("role", "name", "expected"),
        [
            ("user", None, "USER"),
            ("user", "Anna", "USER (Anna)"),
            ("assistant", "Support", "AI (Support)"),
            ("tool", None, "TOOL"),
        ],
    )
    def test_the_label_is_the_role_and_who_it_was(self, role, name, expected):
        assert _speaker_label(role, name) == expected


class TestTheStandingNote:
    async def test_a_private_run_is_told_the_tools_exist(self):
        """A model holding a search tool and no instruction to use it answers from
        what is in front of it, confidently - which is the whole reason a store
        like this feels inert."""
        capability = ConversationSearch()
        instructions = capability.get_instructions()

        assert await instructions(_ctx(_deps())) == _HABIT

    @pytest.mark.parametrize("deps", [_deps(room="room:slack:C1"), _deps(user=None)])
    async def test_a_run_that_cannot_search_is_promised_nothing(self, deps):
        """An instruction promising a search that will be refused costs a tool
        call to find out."""
        assert await ConversationSearch().get_instructions()(_ctx(deps)) == ""

    def test_the_toolset_is_built_once(self):
        capability = ConversationSearch()

        assert capability.get_toolset() is capability.get_toolset()


class TestTheBinding:
    def test_the_registry_offers_both_tools_under_the_scope(self):
        built = build([CapabilityBinding(capability_id="conversation_search", config={})])
        toolset = built[0].get_toolset()

        assert set(toolset.tools) == {"search_conversations", "read_conversation"}

    def test_a_binding_with_no_config_takes_the_default_ceiling(self):
        capability = _build(
            CapabilityBuildContext(
                binding=CapabilityBinding(capability_id="conversation_search", config={}),
                config=None,
            )
        )

        assert capability.max_results == ConversationSearchConfig().max_results

    def test_the_ceiling_is_bounded_both_ways(self):
        """Each result costs context on every search, and one result is not a
        search - so neither end is left to a number somebody typed."""
        assert ConversationSearchConfig(max_results=25).max_results == 25
        with pytest.raises(ValidationError):
            ConversationSearchConfig(max_results=26)
        with pytest.raises(ValidationError):
            ConversationSearchConfig(max_results=0)

    def test_a_configured_ceiling_reaches_the_toolset(self):
        capability = _build(
            CapabilityBuildContext(
                binding=CapabilityBinding(capability_id="conversation_search", config={}),
                config=ConversationSearchConfig(max_results=4),
            )
        )

        assert capability.max_results == 4
