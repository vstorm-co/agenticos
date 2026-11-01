"""What a system agent searches and remembers, through the real runner and a scripted model.

A system agent binds no knowledge base: the platform picks the ones each run is
about, and only those the caller may read are searched. Nobody's memory reaches
it, so the same answer is judged the same whoever started the eval.
"""

import json
import re
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select, update

from app.agents.capabilities.knowledge import FoundPassage
from app.agents.model_resolver import ModelRequestSpec
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.agents.system_agents import JUDGE, SEARCH_STEPS, SYSTEM_AGENTS, SystemAgentDef
from app.core.exceptions import SystemAgentRunError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun
from app.db.models.credential import ModelProfile
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.schemas.scoring import DatasetScoring, KnowledgeFinding
from app.services.agent_registry import AgentRegistryService
from app.services.rag.models import SearchResult
from app.services.scorers import CaseView, ScoredAnswer
from app.services.scoring import ScoringService
from app.services.system_agent_runner import SystemAgentRunner
from app.services.system_agents import SystemAgentService
from tests.integration.test_system_agent_isolation import _owner

pytestmark = pytest.mark.anyio

SEARCH = "search_documents"
PASSAGE = "Refunds are accepted within 30 days."


class Answer(BaseModel):
    ok: bool


def _ok(_prompt: str) -> str:
    return json.dumps({"ok": True})


def _grades(prompt: str) -> str:
    ids = re.findall(r"^- (\w+) \(", prompt, flags=re.MULTILINE)
    return json.dumps(
        {"grades": [{"id": item, "score": 5, "reason": "Matches.", "quotes": []} for item in ids]}
    )


@dataclass
class Script:
    """The model and the search: what a run was offered, told and where it searched."""

    answer: Callable[[str], str] = _ok
    forever: bool = False
    requests: int = 0
    tools: list[set[str]] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    searched: list[list[str]] = field(default_factory=list)

    def model(self) -> FunctionModel:
        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            self.requests += 1
            names = {tool.name for tool in info.function_tools}
            self.tools.append(names)
            self.instructions.append(info.instructions or "")
            searched = any(
                isinstance(part, ToolReturnPart) for message in messages for part in message.parts
            )
            if SEARCH in names and (self.forever or not searched):
                return ModelResponse(parts=[ToolCallPart(SEARCH, {"query": "refund window"})])
            prompt = str(messages[0].parts[-1].content)  # type: ignore[union-attr]
            return ModelResponse(parts=[TextPart(self.answer(prompt))])

        return FunctionModel(respond)

    async def retrieve(
        self,
        *,
        query: str,
        kb_collection_names: list[str] | None = None,
        on_results: Callable[[list[str], list[SearchResult]], None] | None = None,
        **_: Any,
    ) -> str:
        names = list(kb_collection_names or [])
        self.searched.append(names)
        if on_results is not None and names:
            found = SearchResult(
                content=PASSAGE, score=1.0, similarity=0.9, metadata={"filename": "refunds.md"}
            )
            on_results(names, [found])
        return f"refunds.md: {PASSAGE}"


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> Iterator[Script]:
    scripted = Script()
    monkeypatch.setattr(ModelRequestSpec, "build", lambda self: scripted.model())
    monkeypatch.setattr(
        "app.agents.capabilities.knowledge._toolset.search_knowledge_base", scripted.retrieve
    )
    yield scripted


async def _base(db, organization_id: uuid.UUID, **values: Any) -> KnowledgeBase:
    base = KnowledgeBase(
        organization_id=organization_id,
        name=f"handbook-{uuid.uuid4().hex[:6]}",
        collection_name=f"handbook_{uuid.uuid4().hex[:8]}",
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        scope="org",
        **values,
    )
    db.add(base)
    await db.flush()
    return base


async def _elsewhere(db) -> KnowledgeBase:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    other = Organization(
        id=uuid.uuid4(),
        name="Globex",
        slug=f"globex-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(other)
    await db.flush()
    return await _base(db, other.id, visibility=Visibility.ORG.value)


async def _member(db, ctx: AuthContext, role: OrgRoleName) -> AuthContext:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=ctx.organization_id, user_id=user.id, role=role.value
        )
    )
    await db.flush()
    return AuthContext(user_id=user.id, organization_id=ctx.organization_id, role=role)


async def _published(
    db,
    ctx: AuthContext,
    definition: SystemAgentDef,
    *,
    searches: bool,
    max_steps: int | None = None,
) -> Agent:
    agent = await SystemAgentService(db).ensure(
        organization_id=ctx.organization_id, key=definition.key
    )
    spec = AgentSpec.model_validate(agent.draft_spec)
    bindings = [binding for binding in spec.capabilities if binding.id != "knowledge"]
    if searches:
        bindings.append(CapabilityBindingSpec(id="knowledge"))
    registry = AgentRegistryService(db)
    await registry.save_draft(
        ctx, agent.id, spec.model_copy(update={"capabilities": bindings, "max_steps": max_steps})
    )
    await registry.publish(ctx, agent.id)
    return agent


@pytest.mark.parametrize("definition", SYSTEM_AGENTS, ids=lambda item: item.kind.value)
class TestEachKind:
    async def test_one_that_searches_reaches_only_the_runs_own_readable_bases(
        self, db, script: Script, definition: SystemAgentDef
    ) -> None:
        ctx = await _owner(db)
        mine = await _base(db, ctx.organization_id, visibility=Visibility.ORG.value)
        foreign = await _elsewhere(db)
        await _published(db, ctx, definition, searches=True)

        result = await SystemAgentRunner(db).run(
            ctx,
            key=definition.key,
            prompt="Read this.",
            output_type=Answer,
            knowledge_base_ids=[mine.id, foreign.id],
        )

        assert SEARCH in script.tools[0]
        assert script.searched == [[mine.collection_name]]
        assert result.found == [FoundPassage(source="refunds.md", quote=PASSAGE)]

    async def test_one_that_does_not_search_is_offered_no_search(
        self, db, script: Script, definition: SystemAgentDef
    ) -> None:
        ctx = await _owner(db)
        mine = await _base(db, ctx.organization_id, visibility=Visibility.ORG.value)
        await _published(db, ctx, definition, searches=False)

        result = await SystemAgentRunner(db).run(
            ctx,
            key=definition.key,
            prompt="Read this.",
            output_type=Answer,
            knowledge_base_ids=[mine.id],
        )

        assert all(SEARCH not in offered for offered in script.tools)
        assert (script.searched, result.found) == ([], [])


class TestItsSearch:
    async def test_a_base_the_caller_may_not_read_is_never_searched(
        self, db, script: Script
    ) -> None:
        owner = await _owner(db)
        private = await _base(
            db,
            owner.organization_id,
            visibility=Visibility.PRIVATE.value,
            owner_user_id=owner.user_id,
        )
        await _published(db, owner, JUDGE, searches=True)
        member = await _member(db, owner, OrgRoleName.MEMBER)

        await SystemAgentRunner(db).run(
            member,
            key=JUDGE.key,
            prompt="Read this.",
            output_type=Answer,
            knowledge_base_ids=[private.id],
        )

        assert private.collection_name not in [name for names in script.searched for name in names]

    @pytest.mark.parametrize(("max_steps", "requests"), [(None, SEARCH_STEPS), (2, 2)])
    async def test_a_search_that_never_ends_stops_at_its_steps(
        self, db, script: Script, max_steps: int | None, requests: int
    ) -> None:
        ctx = await _owner(db)
        mine = await _base(db, ctx.organization_id, visibility=Visibility.ORG.value)
        await _published(db, ctx, JUDGE, searches=True, max_steps=max_steps)
        script.forever = True

        with pytest.raises(SystemAgentRunError, match="ran out of steps"):
            await SystemAgentRunner(db).run(
                ctx,
                key=JUDGE.key,
                prompt="Read this.",
                output_type=Answer,
                knowledge_base_ids=[mine.id],
            )

        assert script.requests == requests


class TestNobodysMemory:
    async def test_two_people_s_runs_of_a_judge_get_the_same_instructions(
        self, db, script: Script, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even a version published with memory before memory was refused reads none."""
        owner = await _owner(db)
        judge = await _published(db, owner, JUDGE, searches=False)
        version = await db.get(AgentVersion, judge.current_version_id)
        assert version is not None
        await db.execute(
            update(AgentVersion)
            .where(AgentVersion.id == version.id)
            .values(spec={**version.spec, "capabilities": [{"id": "memory_files"}]})
        )
        recalled = AsyncMock(side_effect=lambda **kw: f"Notes of {kw['owner_key']}")
        monkeypatch.setattr(
            "app.agents.capabilities.memory_files._capability.memory_store.read_file", recalled
        )
        admin = await _member(db, owner, OrgRoleName.ADMIN)

        for ctx in (owner, admin):
            await SystemAgentRunner(db).run(
                ctx, key=JUDGE.key, prompt="Grade this.", output_type=Answer
            )

        first, second = script.instructions
        assert first == second
        assert "Notes of" not in first
        recalled.assert_not_awaited()
        assert all("read_memory" not in offered for offered in script.tools)


class TestAJudgeThatSearches:
    async def test_it_searches_the_graded_agent_s_bases_and_its_grades_say_what_it_found(
        self, db, script: Script
    ) -> None:
        ctx = await _owner(db)
        handbook = await _base(db, ctx.organization_id, visibility=Visibility.ORG.value)
        await _base(db, ctx.organization_id, visibility=Visibility.ORG.value)
        await _published(db, ctx, JUDGE, searches=True)
        support = await AgentRegistryService(db).create(
            ctx, AgentSpec(name="Support", instructions="Help.", collection_ids=[handbook.id])
        )
        script.answer = _grades
        scoring = DatasetScoring.model_validate({"reference": {"enabled": True}})
        case = CaseView(
            input="How long do I have to return it?",
            history=[],
            reference_answer="30 days.",
            counter_example=None,
            expected_tool_calls=[],
            order_mode="any",
            checks=[],
        )

        evaluation = await ScoringService(db).evaluate(
            ctx, case, ScoredAnswer(text="You have 30 days.", agent_id=support.id), scoring
        )

        assert script.searched == [[handbook.collection_name]]
        judged = [result for result in evaluation.results if result.judge_run_id is not None]
        assert judged
        assert all(
            result.knowledge == [KnowledgeFinding(source="refunds.md", quote=PASSAGE)]
            for result in judged
        )


class TestARunThatFails:
    async def test_a_failure_other_than_its_steps_reaches_the_caller_as_it_was(
        self, db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = await _owner(db)
        await _published(db, ctx, JUDGE, searches=False)

        async def broken(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            raise RuntimeError("the provider fell over")

        monkeypatch.setattr(ModelRequestSpec, "build", lambda self: FunctionModel(broken))

        with pytest.raises(RuntimeError, match="fell over"):
            await SystemAgentRunner(db).run(
                ctx, key=JUDGE.key, prompt="Grade this.", output_type=Answer
            )


class TestTheGradedAgentsBases:
    async def test_an_answer_s_bases_come_from_the_version_its_run_ran_on(
        self, db, script: Script
    ) -> None:
        ctx = await _owner(db)
        published = await _base(db, ctx.organization_id, visibility=Visibility.ORG.value)
        drafted = await _base(db, ctx.organization_id, visibility=Visibility.ORG.value)
        registry = AgentRegistryService(db)
        model = await db.scalar(
            select(ModelProfile.id).where(ModelProfile.organization_id == ctx.organization_id)
        )
        support = await registry.create(
            ctx,
            AgentSpec(
                name="Support",
                instructions="Help.",
                model_profile_id=model,
                collection_ids=[published.id],
            ),
        )
        version = await registry.publish(ctx, support.id)
        await registry.save_draft(
            ctx,
            support.id,
            AgentSpec(name="Support", instructions="Help.", collection_ids=[drafted.id]),
        )
        run = AgentRun(
            id=uuid.uuid4(),
            organization_id=ctx.organization_id,
            agent_id=support.id,
            agent_version_id=version.id,
            user_id=ctx.user_id,
            surface="eval",
        )
        db.add(run)
        await db.flush()
        scoring = ScoringService(db)

        on_version = await scoring._answering_bases(
            ctx, ScoredAnswer(text="Yes.", agent_id=support.id, run_id=run.id)
        )
        on_draft = await scoring._answering_bases(
            ctx, ScoredAnswer(text="Yes.", agent_id=support.id)
        )
        nobody = await scoring._answering_bases(ctx, ScoredAnswer(text="Yes."))

        assert (on_version, on_draft, nobody) == ([published.id], [drafted.id], [])
