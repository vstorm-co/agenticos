"""`@`-mentions (#2189): what is offered, what a frame may name, what the model reads.

The refusals are the point. Only what the chat's agent already reaches is offered -
a knowledge base it binds but whose capability is off is not - and only agents the
person may run. A frame naming anything else has it dropped, so a mention can
never widen what a run reaches.
"""

from __future__ import annotations

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
            id=uuid.uuid4(), name="github-work", label=None, catalog_key="github"
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
                    {"id": "subagents"},
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
                subagents=[{"agent_id": self.reviewer.id, "agent_version_id": uuid.uuid4()}],
            ),
            self.writer.id: AgentSpec(
                name="Writer", capabilities=[{"id": "context"}], context_ids=[self.context.id]
            ),
        }

    def patches(self) -> list[Any]:
        async def runnable_spec(
            _self: object, _ctx: AuthContext, agent_id: uuid.UUID
        ) -> tuple[Any, AgentSpec, Any]:
            return MagicMock(), self.specs[agent_id], uuid.uuid4()

        everyone = [self.chat, self.reviewer, self.writer, self.locked, self.draft]
        return [
            patch.object(module.AgentRegistryService, "get_runnable_spec", new=runnable_spec),
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
            patch.object(module, "visible_resource_ids", AsyncMock(return_value=[])),
            patch.object(
                module.agent_repo, "list_visible", AsyncMock(return_value=(everyone, len(everyone)))
            ),
            patch.object(
                module,
                "accessible_ids",
                AsyncMock(
                    side_effect=lambda _db, _ctx, rows, *_a, **_k: {
                        row.id for row in rows if row is not self.locked
                    }
                ),
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
        # A delegate first; never the chat's own agent, a draft, or one the person cannot run.
        assert by_kind["agent"] == ["Reviewer", "Writer"]
        # Another tenant's collection is not offered, nor files whose capability is off.
        assert by_kind["collection"] == ["Contracts"]
        assert by_kind["skill"] == ["refund-policy"]
        assert "context" not in by_kind
        github = offered[0]
        assert (github.detail, github.icon) == ("github_work_*", "github")
        assert [item.delegate for item in offered if item.kind == "agent"] == [True, False]


class TestResolvingAFrame:
    async def test_nothing_mentioned_changes_nothing(self, world: Any) -> None:
        resolved = await MentionService(MagicMock()).resolve(_ctx(), CHAT_AGENT, [])
        assert (resolved.agent_id, resolved.mentions, resolved.note) == (CHAT_AGENT, [], None)

    async def test_what_could_not_have_been_picked_is_dropped(self, world: Any) -> None:
        refs = [
            MentionRef(kind="collection", id=str(world.collection.id)),
            MentionRef(kind="collection", id=str(world.collection.id)),
            MentionRef(kind="collection", id=str(world.stranger_collection.id)),
            MentionRef(kind="agent", id=str(world.locked.id)),
            MentionRef(kind="mcp", id="platform"),
            MentionRef(kind="skill", id=str(world.skill.id)),
            MentionRef(kind="agent", id=str(world.reviewer.id)),
        ]
        resolved = await MentionService(MagicMock()).resolve(_ctx(), CHAT_AGENT, refs)

        assert resolved.agent_id == CHAT_AGENT
        assert [item.name for item in resolved.mentions] == [
            "Contracts",
            "agenticos",
            "refund-policy",
            "Reviewer",
        ]
        assert resolved.note is not None
        assert 'Knowledge base "Contracts" - search it with `search_documents`.' in resolved.note
        assert 'MCP server "agenticos" - use its tools (agenticos_*).' in resolved.note
        assert 'Skill "refund-policy"' in resolved.note
        assert 'Agent "Reviewer" - hand the work to this specialist' in resolved.note

    async def test_an_agent_that_is_not_a_delegate_answers_the_turn_itself(
        self, world: Any
    ) -> None:
        refs = [
            MentionRef(kind="agent", id=str(world.writer.id)),
            MentionRef(kind="context", id=str(world.context.id)),
            MentionRef(kind="skill", id=str(world.skill.id)),
        ]
        resolved = await MentionService(MagicMock()).resolve(_ctx(), CHAT_AGENT, refs)

        assert resolved.agent_id == world.writer.id
        # The rest is resolved against the agent that answers: the writer reads
        # context files and has no skills.
        assert [item.name for item in resolved.mentions] == ["Writer", "glossary"]
        assert resolved.note == (
            "The person pointed at these for this request; use them:\n"
            '- Context file "glossary" - use what it says.'
        )

    async def test_an_agent_alone_is_who_answers_with_nothing_to_note(self, world: Any) -> None:
        resolved = await MentionService(MagicMock()).resolve(
            _ctx(), CHAT_AGENT, [MentionRef(kind="agent", id=str(world.writer.id))]
        )
        assert (resolved.agent_id, resolved.note) == (world.writer.id, None)


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
