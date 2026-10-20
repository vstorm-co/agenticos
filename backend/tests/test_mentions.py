"""`@`-mentions (#2189): what is offered, what a frame may name, what the model reads.

The refusals are the point. Only what the chat's agent already reaches is offered -
a knowledge base it binds but whose capability is off is not - and an agent only
where the chat's agent delegates to it and the person may run it. A frame naming
anything else has it dropped, so a mention can never widen what a run reaches, and
none ever changes which agent answers.
"""

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.schemas.mention import MentionRef
from app.services import agent_chat
from app.services import mentions as module
from app.services.agent_chat import MAX_MENTIONS, ChatAgentRunner, requested_mentions
from app.services.mentions import MentionService

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()
CHAT_AGENT = uuid.uuid4()


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=ORG, role=OrgRoleName.MEMBER)


def _agent(name: str, *, published: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        description=f"{name} does things",
        slug=name.lower(),
        has_avatar=False,
        avatar_color=None,
        current_version_id=uuid.uuid4() if published else None,
    )


class _World:
    """One organization's rows, patched in at the repositories."""

    def __init__(self) -> None:
        self.connection = SimpleNamespace(
            id=uuid.uuid4(),
            name="github-work",
            label=None,
            catalog_key="github",
            is_enabled=True,
            url="https://api.githubcopilot.com/mcp/?token=secret",
        )
        self.collection = SimpleNamespace(id=uuid.uuid4(), name="Contracts", organization_id=ORG)
        self.stranger_collection = SimpleNamespace(
            id=uuid.uuid4(), name="Elsewhere", organization_id=uuid.uuid4()
        )
        self.skill = SimpleNamespace(id=uuid.uuid4(), name="refund-policy")
        self.context = SimpleNamespace(id=uuid.uuid4(), name="glossary")
        self.reviewer = _agent("Reviewer")
        self.writer = _agent("Writer")
        self.locked = _agent("Locked")
        self.draft = _agent("Draft", published=False)
        self.chat = SimpleNamespace(**{**vars(_agent("Chat")), "id": CHAT_AGENT})
        self.specs: dict[uuid.UUID, AgentSpec] = {
            CHAT_AGENT: AgentSpec(
                name="Chat",
                capabilities=[
                    {"id": "knowledge"},
                    {"id": "skills"},
                    {"id": "context", "enabled": False},
                    {
                        "id": "subagents",
                        "config": {
                            "inline": [
                                {
                                    "name": "summariser",
                                    "description": "Writes the short version",
                                    "instructions": "Summarise.",
                                }
                            ]
                        },
                    },
                ],
                collection_ids=[self.collection.id, self.stranger_collection.id, uuid.uuid4()],
                skill_ids=[self.skill.id, uuid.uuid4()],
                context_ids=[self.context.id],
                mcp_servers=[
                    {"account": "organization", "connection_id": self.connection.id},
                    {"account": "organization", "connection_id": uuid.uuid4()},
                    {"account": "personal", "catalog_key": "notion"},
                    {"account": "personal", "catalog_key": "not-in-catalog"},
                    {"account": "platform"},
                ],
                subagents=[
                    {"agent_id": self.reviewer.id, "agent_version_id": uuid.uuid4()},
                    {"agent_id": self.locked.id, "agent_version_id": uuid.uuid4()},
                    {"agent_id": uuid.uuid4(), "agent_version_id": uuid.uuid4()},
                ],
            ),
            self.writer.id: AgentSpec(
                name="Writer", capabilities=[{"id": "context"}], context_ids=[self.context.id]
            ),
        }

        # What the Builder holds for the chat's agent: one skill, nothing published.
        self.drafts: dict[uuid.UUID, AgentSpec] = {
            CHAT_AGENT: AgentSpec(
                name="Chat", capabilities=[{"id": "skills"}], skill_ids=[self.skill.id]
            )
        }

    def patches(self) -> list[Any]:
        async def runnable_spec(
            _self: object, _ctx: AuthContext, agent_id: uuid.UUID
        ) -> tuple[Any, AgentSpec, Any]:
            return MagicMock(), self.specs[agent_id], uuid.uuid4()

        async def draft_spec(
            _self: object, _ctx: AuthContext, agent_id: uuid.UUID
        ) -> tuple[Any, AgentSpec]:
            return MagicMock(), self.drafts[agent_id]

        everyone = [self.chat, self.reviewer, self.writer, self.locked, self.draft]
        return [
            patch.object(module.AgentRegistryService, "get_runnable_spec", new=runnable_spec),
            patch.object(module.AgentRegistryService, "get_draft_spec", new=draft_spec),
            patch.object(
                module.mcp_connection_repo,
                "get_org_scoped_by_ids",
                AsyncMock(return_value={self.connection.id: self.connection}),
            ),
            patch.object(
                module.knowledge_base_repo,
                "get_by_ids",
                AsyncMock(
                    return_value={
                        self.collection.id: self.collection,
                        self.stranger_collection.id: self.stranger_collection,
                    }
                ),
            ),
            patch.object(
                module.skill_repo, "get_many", AsyncMock(return_value={self.skill.id: self.skill})
            ),
            patch.object(
                module.context_repo,
                "get_many",
                AsyncMock(return_value={self.context.id: self.context}),
            ),
            patch.object(
                module.agent_repo,
                "get_many",
                AsyncMock(return_value={agent.id: agent for agent in everyone}),
            ),
        ]


@pytest.fixture
def world() -> Any:
    state = _World()
    for patcher in state.patches():
        patcher.start()
    yield state
    patch.stopall()


class TestWhatIsOffered:
    async def test_only_what_the_agent_reaches_and_the_person_may_run(self, world: Any) -> None:
        offered = await MentionService(MagicMock()).available(_ctx(), CHAT_AGENT)
        by_kind: dict[str, list[str]] = {}
        for item in offered:
            by_kind.setdefault(item.kind, []).append(item.name)

        assert by_kind["mcp"] == ["GitHub", "Notion", "not-in-catalog", "agenticos"]
        # What is switched on, never a capability that is off.
        offered_capabilities = [item.id for item in offered if item.kind == "capability"]
        assert "knowledge" in offered_capabilities
        assert "context" not in offered_capabilities
        # Who it delegates to, and only them: every pinned delegate - one the person
        # could not run directly too, as the run hands it work all the same - then
        # its inline specialist; never one that is gone, or an agent it does not
        # delegate to.
        assert by_kind["agent"] == ["Reviewer", "Locked", "summariser"]
        # Another tenant's collection is not offered, nor files whose capability is off.
        assert by_kind["collection"] == ["Contracts"]
        assert by_kind["skill"] == ["refund-policy"]
        assert "context" not in by_kind
        github = offered[0]
        assert (github.detail, github.icon) == ("github_work_*", "github")
        # The host its logo is drawn from, and nothing more of an address that can
        # carry a credential.
        assert github.host == "api.githubcopilot.com"
        assert offered[3].host is None
        assert [item.id for item in offered if item.kind == "agent"][2] == "inline:summariser"

    async def test_capabilities_are_offered_whole_and_named_as_people_know_them(
        self, world: Any
    ) -> None:
        """`@Web research`, not `@web_search`: the note names its tools, and a rename
        in the binding is the name given - pointing the model at the default name
        would point it at a tool it was not given."""
        world.specs[CHAT_AGENT] = AgentSpec(
            name="Chat",
            capabilities=[
                {"id": "knowledge"},
                {"id": "context", "enabled": False},
                {"id": "clock"},
                {
                    "id": "web_research",
                    "tool_overrides": {"web_search": {"name": "search_the_web"}},
                },
            ],
        )
        offered = await MentionService(MagicMock()).available(_ctx(), CHAT_AGENT)
        capabilities = [item for item in offered if item.kind == "capability"]

        # `clock` only adds the date to the instructions: no tool, nothing to point at.
        assert [item.id for item in capabilities] == ["knowledge", "web_research"]
        research = capabilities[-1]
        assert research.name != research.id
        assert research.icon == "web_search"
        resolved = await MentionService(MagicMock()).resolve(
            _ctx(), CHAT_AGENT, [MentionRef(kind="capability", id="web_research")]
        )
        assert resolved.note is not None
        assert f'Capability "{research.name}" - use its tools (search_the_web)' in resolved.note

    async def test_an_agent_that_does_not_delegate_offers_no_agents(self, world: Any) -> None:
        offered = await MentionService(MagicMock()).available(_ctx(), world.writer.id)
        assert {item.kind for item in offered} == {"capability", "context"}


class TestWhatTheRunWouldNotHave:
    async def test_a_server_disabled_since_publish_is_not_offered(self, world: Any) -> None:
        """The run leaves its tools out; a chip would send the model after them."""
        world.connection.is_enabled = False
        offered = await MentionService(MagicMock()).available(_ctx(), CHAT_AGENT)
        assert "GitHub" not in [item.name for item in offered if item.kind == "mcp"]

    async def test_the_note_names_tools_as_the_binding_renamed_them(self, world: Any) -> None:
        spec = world.specs[CHAT_AGENT]
        renamed = {
            "subagents": {"task": {"name": "hand_off"}},
            "knowledge": {"search_documents": {"name": "look_up"}},
        }
        dumped = spec.model_dump()
        for binding in dumped["capabilities"]:
            binding["tool_overrides"] = renamed.get(binding["id"], {})
        world.specs[CHAT_AGENT] = AgentSpec.model_validate(dumped)
        resolved = await MentionService(MagicMock()).resolve(
            _ctx(),
            CHAT_AGENT,
            [
                MentionRef(kind="agent", id=str(world.reviewer.id)),
                MentionRef(kind="collection", id=str(world.collection.id)),
            ],
        )
        assert resolved.note is not None
        assert "with the `hand_off` tool" in resolved.note
        assert "search it with `look_up`" in resolved.note
        assert "`task`" not in resolved.note and "`search_documents`" not in resolved.note


class TestResolvingAFrame:
    async def test_nothing_mentioned_changes_nothing(self, world: Any) -> None:
        resolved = await MentionService(MagicMock()).resolve(_ctx(), CHAT_AGENT, [])
        assert (resolved.mentions, resolved.note) == ([], None)

    @pytest.mark.security
    async def test_only_what_could_not_have_been_picked_tells_the_model_nothing(
        self, world: Any
    ) -> None:
        """Another tenant's collection and an agent this one does not delegate to:
        no note, so nothing about them reaches the model."""
        refs = [
            MentionRef(kind="collection", id=str(world.stranger_collection.id)),
            MentionRef(kind="agent", id=str(world.writer.id)),
        ]
        resolved = await MentionService(MagicMock()).resolve(_ctx(), CHAT_AGENT, refs)
        assert (resolved.mentions, resolved.note) == ([], None)

    async def test_what_could_not_have_been_picked_is_dropped(self, world: Any) -> None:
        refs = [
            MentionRef(kind="collection", id=str(world.collection.id)),
            MentionRef(kind="collection", id=str(world.collection.id)),
            MentionRef(kind="collection", id=str(world.stranger_collection.id)),
            MentionRef(kind="agent", id=str(world.locked.id)),
            MentionRef(kind="agent", id=str(world.writer.id)),
            MentionRef(kind="mcp", id="platform"),
            MentionRef(kind="skill", id=str(world.skill.id)),
            MentionRef(kind="agent", id=str(world.reviewer.id)),
            MentionRef(kind="agent", id="inline:summariser"),
        ]
        resolved = await MentionService(MagicMock()).resolve(_ctx(), CHAT_AGENT, refs)

        assert [item.name for item in resolved.mentions] == [
            "Contracts",
            "Locked",
            "agenticos",
            "refund-policy",
            "Reviewer",
            "summariser",
        ]
        assert resolved.note is not None
        assert 'Knowledge base "Contracts" - search it with `search_documents`.' in resolved.note
        assert 'MCP server "agenticos" - use its tools (agenticos_*).' in resolved.note
        assert 'Skill "refund-policy"' in resolved.note
        assert 'Agent "Reviewer" - hand the work to this specialist' in resolved.note
        assert 'Agent "summariser" - hand the work to this specialist' in resolved.note


class TestTheDraft:
    """The Builder's test panel runs the draft, so it is the draft that is offered."""

    async def test_the_draft_is_read_instead_of_the_published_version(self, world: Any) -> None:
        offered = await MentionService(MagicMock()).available(_ctx(), CHAT_AGENT, draft=True)
        assert [(item.kind, item.name) for item in offered][-1] == ("skill", "refund-policy")
        assert not any(item.kind == "mcp" for item in offered)

        resolved = await MentionService(MagicMock()).resolve(
            _ctx(),
            CHAT_AGENT,
            [
                MentionRef(kind="skill", id=str(world.skill.id)),
                MentionRef(kind="collection", id=str(world.collection.id)),
            ],
            draft=True,
        )
        assert [item.name for item in resolved.mentions] == ["refund-policy"]


class TestTheFrame:
    def test_no_mentions_is_an_empty_list(self) -> None:
        assert requested_mentions({}) == []

    def test_mentions_are_read_by_shape(self) -> None:
        [ref] = requested_mentions({"mentions": [{"kind": "skill", "id": "s-1"}]})
        assert (ref.kind, ref.id) == ("skill", "s-1")

    @pytest.mark.parametrize(
        "raw", ["gdrive", [{"kind": "spaceship", "id": "x"}], [{"kind": "mcp"}]]
    )
    def test_a_frame_whose_mentions_are_not_mentions_is_refused(self, raw: object) -> None:
        with pytest.raises(BadRequestError, match="could not be read"):
            requested_mentions({"mentions": raw})

    def test_more_than_anyone_points_at_is_refused(self) -> None:
        raw = [{"kind": "skill", "id": str(index)} for index in range(MAX_MENTIONS + 1)]
        with pytest.raises(BadRequestError, match="at most"):
            requested_mentions({"mentions": raw})

    async def test_the_chat_runner_resolves_as_the_person_typing(self) -> None:
        runner = ChatAgentRunner(MagicMock())
        ctx = _ctx()
        with (
            patch.object(ChatAgentRunner, "_context", AsyncMock(return_value=ctx)),
            patch.object(agent_chat.MentionService, "resolve", AsyncMock()) as resolve,
        ):
            await runner.mentions(
                user=MagicMock(), organization_id=ORG, agent_id=CHAT_AGENT, refs=[]
            )
        assert resolve.await_args.args == (ctx, CHAT_AGENT, [])


class TestTheRoute:
    async def test_it_lists_what_the_composer_offers(self) -> None:
        from app.api.routes.v1.agents import list_mentionables
        from app.schemas.mention import Mentionable

        service = MagicMock(
            available=AsyncMock(return_value=[Mentionable(kind="skill", id="s", name="refunds")])
        )
        listed = await list_mentionables(CHAT_AGENT, service, _ctx())
        assert (listed.total, listed.items[0].name) == (1, "refunds")
