"""What an agent is told about its own setup (#2301)."""

import json
import uuid
from unittest.mock import MagicMock

import pytest
from pydantic_ai import ModelRetry

from app.agents.capabilities import all_capabilities
from app.agents.factory import build_agent
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.setup_briefing import PLUMBING, SetupBriefing, setup_briefing
from app.agents.spec import AgentSpec
from app.agents.voice import VoiceOptions
from app.core.secret_kinds import ApiKeySecret


def _spec(*ids: str, **overrides: object) -> AgentSpec:
    return AgentSpec(name="Helper", capabilities=[{"id": i} for i in ids], **overrides)


def _halves(text: str) -> tuple[str, str]:
    has, _, missing = text.partition("Not switched on")
    return has, missing


class TestWhatItSays:
    def test_what_is_bound_is_listed_in_the_words_the_toolbox_leads_with(self) -> None:
        has, missing = _halves(setup_briefing(_spec("web_research", "ask_user"), agent_id=None))

        assert "- **Web search**: Look up current information on the public web." in has
        # Said to the agent itself: the Toolbox's "Let the agent ask..." is "Ask...".
        assert "- **Ask the user**: Ask the person it is working for" in has
        assert "Web search" not in missing

    def test_what_is_not_bound_is_listed_as_what_it_cannot_do_here(self) -> None:
        _has, missing = _halves(setup_briefing(_spec("clock"), agent_id=None))

        # With its id, which is what the card is asked for by.
        assert "- **Web search** (`web_research`):" in missing
        assert "- **Sandbox** (`sandbox`):" in missing

    def test_a_switched_off_binding_is_something_it_cannot_do(self) -> None:
        spec = AgentSpec(name="Helper", capabilities=[{"id": "web_research", "enabled": False}])

        has, missing = _halves(setup_briefing(spec, agent_id=None))

        assert "Web search" not in has
        assert "- **Web search** (`web_research`):" in missing

    def test_plumbing_is_neither_an_ability_nor_a_gap(self) -> None:
        text = setup_briefing(_spec("thinking", "compaction"), agent_id=None)

        for capability in all_capabilities():
            if capability.id in PLUMBING:
                assert f"**{capability.name}**" not in text

    def test_a_capability_no_spec_may_bind_is_never_suggested(self) -> None:
        text = setup_briefing(_spec(), agent_id=None)

        assert "Chat channel lookup" not in text

    @pytest.mark.parametrize(
        ("bound", "other"), [("memory_files", "Memory (mem0)"), ("memory_mem0", "**Memory**")]
    )
    def test_one_way_of_remembering_is_not_short_of_the_other(self, bound: str, other: str) -> None:
        _has, missing = _halves(setup_briefing(_spec(bound), agent_id=None))

        assert other not in missing

    def test_an_agent_with_everything_is_told_of_no_gap(self) -> None:
        everything = [c.id for c in all_capabilities() if c.selectable]

        assert "Not switched on" not in setup_briefing(_spec(*everything), agent_id=None)

    def test_knowledge_and_connected_services_are_counted(self) -> None:
        spec = _spec(
            collection_ids=[uuid.uuid4(), uuid.uuid4()],
            mcp_servers=[{"account": "platform"}],
        )

        text = setup_briefing(spec, agent_id=None)

        assert "- **Knowledge**: 2 knowledge base(s) to answer from." in text
        assert "- **Connected services**:" in text
        assert "**Knowledge**" not in setup_briefing(_spec(), agent_id=None)

    def test_an_agent_that_knows_its_id_offers_the_card(self) -> None:
        linked = setup_briefing(_spec(), agent_id=uuid.uuid4())
        unlinked = setup_briefing(_spec(), agent_id=None)

        assert "call `request_capability` with its id" in linked
        assert unlinked.endswith("switch it on in the Builder.")

    def test_the_capability_hands_the_text_over_unchanged(self) -> None:
        assert SetupBriefing("# Your setup").get_instructions() == "# Your setup"


class TestTheCard:
    """`request_capability`: the card an agent shows for what it lacks."""

    @staticmethod
    def _tool(spec: AgentSpec, agent_id: uuid.UUID | None):
        return SetupBriefing.for_spec(spec, agent_id=agent_id).get_toolset()

    def test_it_names_the_agent_the_capability_and_why(self) -> None:
        agent_id = uuid.uuid4()
        toolset = self._tool(_spec("clock"), agent_id)
        assert toolset is not None

        card = json.loads(
            toolset.request_capability(MagicMock(), "web_research", "  to check   today's prices ")
        )

        assert card == {
            "agent_id": str(agent_id),
            "capability_id": "web_research",
            "name": "Web search",
            "reason": "to check today's prices",
        }

    def test_one_it_already_has_is_steered_back_to_the_list(self) -> None:
        toolset = self._tool(_spec("web_research"), uuid.uuid4())
        assert toolset is not None
        ctx = MagicMock(last_attempt=False)

        with pytest.raises(ModelRetry, match="not one you lack"):
            toolset.request_capability(ctx, "web_research", "search")

    @pytest.mark.parametrize("reason", ["   ", "x" * 301])
    def test_a_reason_the_cards_button_could_not_send_is_asked_for_again(self, reason) -> None:
        """The press posts it as `CapabilityRequest.reason`, 1-300 characters - a
        card outside them would refuse every press (Codex on #2324)."""
        toolset = self._tool(_spec("clock"), uuid.uuid4())
        assert toolset is not None

        with pytest.raises(ModelRetry, match="at most 300 characters"):
            toolset.request_capability(MagicMock(last_attempt=False), "web_research", reason)

    def test_no_card_without_an_agent_to_name_or_anything_to_ask_for(self) -> None:
        everything = [c.id for c in all_capabilities() if c.selectable]

        assert self._tool(_spec(), None) is None
        assert self._tool(_spec(*everything), uuid.uuid4()) is None


def _model() -> ModelRequestSpec:
    return ModelRequestSpec(
        profile_id=uuid.uuid4(),
        label="GPT-4.1",
        provider="openai",
        model="gpt-4.1",
        params={},
        credential=ResolvedCredential(
            provider="openai", secret=ApiKeySecret(api_key="sk-test-key")
        ),
        fallbacks=[],
    )


def _briefings(spec: AgentSpec, **kwargs: object) -> list[SetupBriefing]:
    built = build_agent(spec, _model(), organization_id=uuid.uuid4(), **kwargs)
    attached: list[object] = []
    built.agent.root_capability.apply(attached.append)
    return [c for c in attached if isinstance(c, SetupBriefing)]


class TestEveryAgentIsBriefed:
    def test_a_text_run_carries_its_setup(self) -> None:
        agent_id = uuid.uuid4()

        (briefing,) = _briefings(_spec("clock"), agent_id=agent_id)

        assert briefing.text == setup_briefing(_spec("clock"), agent_id=agent_id)
        assert briefing.agent_id == agent_id
        assert "web_research" in briefing.missing

    def test_a_voice_call_is_not(self) -> None:
        async def deny(_request: object) -> object:  # pragma: no cover - never called
            raise AssertionError

        assert _briefings(_spec(), voice=VoiceOptions(on_deferred=deny)) == []
