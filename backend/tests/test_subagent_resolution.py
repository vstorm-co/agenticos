"""Resolving a run's delegation tree, and recording what a delegation cost.

The runner resolves the whole tree before the run starts, because the capability
that uses it holds no session and the one the run shares is not
concurrency-safe. Almost everything worth asserting here is a refusal or an
isolation:

* an agent that does not delegate is assembled exactly as it was before
  delegation existed;
* a delegate reaches its **own** collections, never its caller's;
* a pin whose version is gone fails the run rather than quietly running whatever
  is published now;
* nesting stops at `max_depth`, and stops by *removing* the capability rather
  than by offering a tool that always says no;
* a delegate already running higher up the tree is refused, as are two delegates
  answering to one name;
* a delegation to a published agent gets a run row of its own, an inline
  specialist gets none, and the row counts towards its own agent's month but not
  towards the organization's.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents.capabilities.budget import SpendLedger
from app.agents.capabilities.sandbox import WORKSPACE_BACKEND_RESOURCE
from app.agents.capabilities.subagents import SubagentsConfig
from app.agents.spec import AgentSpec, SpecialistSpec, SubagentRef
from app.agents.subagent_runtime import (
    SUBAGENT_RUNTIME_RESOURCE,
    DelegationOutcome,
    ResolvedSubagent,
    SubagentRuntime,
)
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import AgentStatus
from app.db.models.agent_run import RunStatus
from app.services.agent_registry import DELEGATION_CAPABILITY_ID
from app.services.agent_runner import (
    AgentRunnerService,
    RecordedDelegation,
    month_start,
)

pytestmark = pytest.mark.anyio

RUNNER = "app.services.agent_runner"


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


def _db() -> MagicMock:
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    # `_run` commits its own terminal write; a cancellation never reaches the
    # session context that would otherwise do it.
    db.commit = AsyncMock()
    # How the organization row - and with it the org-wide cap - comes back.
    db.get = AsyncMock(return_value=MagicMock(monthly_budget_usd=None))
    return db


def _delegating(
    *,
    inline: list[SpecialistSpec] | None = None,
    subagents: list[SubagentRef] | None = None,
    name: str = "Orchestrator",
    max_depth: int = 1,
    allow_dynamic: bool = False,
    share: list[str] | None = None,
    capabilities: list[dict[str, Any]] | None = None,
    **spec_fields: Any,
) -> AgentSpec:
    """A spec that binds the delegation capability, configured as given."""
    config: dict[str, Any] = {"max_depth": max_depth, "allow_dynamic": allow_dynamic}
    if inline is not None:
        config["inline"] = [specialist.model_dump(mode="json") for specialist in inline]
    if share is not None:
        config["share_with_delegates"] = share
    return AgentSpec(
        name=name,
        capabilities=[
            *(capabilities or []),
            {"id": DELEGATION_CAPABILITY_ID, "config": config},
        ],
        subagents=subagents or [],
        **spec_fields,
    )


def _specialist(**fields: Any) -> SpecialistSpec:
    return SpecialistSpec(
        name=fields.pop("name", "summariser"),
        description=fields.pop("description", "Summarises a document in three bullets"),
        instructions=fields.pop("instructions", "Be brief."),
        **fields,
    )


def _version(agent_id: uuid.UUID, spec: AgentSpec) -> MagicMock:
    """A published version row holding `spec`.

    `spec` is assigned rather than passed to the constructor, where `MagicMock`
    would read it as the class to mock and refuse every other attribute.
    """
    version = MagicMock(id=uuid.uuid4(), agent_id=agent_id)
    version.spec = spec.model_dump(mode="json")
    return version


def _agent_row(
    agent_id: uuid.UUID, *, slug: str, status: str = AgentStatus.PUBLISHED.value
) -> MagicMock:
    """A delegate's `agents` row - the one place its handle and its status live.

    `name` is assigned rather than passed to the constructor, where `MagicMock`
    would take it as the mock's own name and leave the attribute unset.
    """
    row = MagicMock(id=agent_id, slug=slug, status=status)
    row.name = slug
    return row


def _slug(name: str) -> str:
    """What a name looks like as a handle, for a row a test did not spell out."""
    return name.strip().lower().replace(" ", "-")


UNUSABLE_PROFILE = "unusable"
"""The label of a model profile whose key has been deleted since it was stored."""


def _profile(label: str) -> MagicMock:
    """One row of the organization's model catalog."""
    return MagicMock(id=uuid.uuid4(), label=label)


def _collection(organization_id: uuid.UUID, name: str) -> MagicMock:
    return MagicMock(organization_id=organization_id, collection_name=name)


class _Prepared:
    """A prepared run, plus the calls the factory and the repositories saw."""

    def __init__(
        self,
        prepared: Any,
        build: MagicMock,
        get_version: AsyncMock,
        list_profiles: AsyncMock,
    ) -> None:
        self.prepared = prepared
        self.build = build
        self.get_version = get_version
        self.list_profiles = list_profiles

    @property
    def resources(self) -> dict[str, Any]:
        return self.build.call_args_list[0].kwargs["resources"]

    @staticmethod
    def _arguments(call: Any) -> dict[str, Any]:
        """One `build_agent` call, with its two positional arguments named."""
        return {"spec": call.args[0], "model": call.args[1], **call.kwargs}

    @property
    def runtime(self) -> SubagentRuntime:
        return self.resources[SUBAGENT_RUNTIME_RESOURCE]

    def built(self, *path: str) -> dict[str, Any]:
        """Build one delegate and hand back the arguments the factory got.

        Building is what the capability does when the model actually delegates,
        so this is the only way to see what a delegate was resolved with - and
        the point of it being lazy. The factory is put back in place for the
        call, because that call happens later than `prepare` did.

        More than one name walks down the tree, building each level to reach the
        runtime the next one is addressed through: `built("research-bot",
        "fact-checker")` is what the grandchild was resolved with.
        """
        runtime = self.runtime
        for name in path[:-1]:
            runtime = self._build(runtime, name)["resources"][SUBAGENT_RUNTIME_RESOURCE]
        return self._build(runtime, path[-1])

    def _build(self, runtime: SubagentRuntime, name: str) -> dict[str, Any]:
        entry = runtime.named(name)
        assert entry is not None, f"no delegate named {name!r}"
        with patch(f"{RUNNER}.build_agent", new=self.build):
            entry.build()
        return self._arguments(self.build.call_args_list[-1])

    def invented(self, *, model: str, name: str = "summariser") -> dict[str, Any]:
        """Build a specialist the run's model asked for, and say what the factory got.

        The same shape as `built`, and for the same reason: a dynamic specialist is
        built from inside a tool call, so what it was built *with* is only visible
        by making that call. What matters in the answer is `shared_budget` - a
        specialist built without it meters nothing the run's cap can see.
        """
        dynamic = self.runtime.dynamic
        assert dynamic is not None, "this agent was not resolved with dynamic specialists"
        with patch(f"{RUNNER}.build_agent", new=self.build):
            dynamic.build(name=name, instructions="Be brief.", model=model)
        return self._arguments(self.build.call_args_list[-1])


async def _prepare(
    spec: AgentSpec,
    *,
    ctx: AuthContext | None = None,
    versions: dict[uuid.UUID, MagicMock] | None = None,
    agents: dict[uuid.UUID, MagicMock] | None = None,
    collections: dict[uuid.UUID, MagicMock] | None = None,
    workspace: object | None = None,
    agent_id: uuid.UUID | None = None,
    profiles: list[MagicMock] | None = None,
) -> _Prepared:
    """Prepare a run of `spec` with every database read answered from memory.

    `agents` is the delegates' own rows, keyed by id. Passing it says these are
    the only ones that exist - which is how a test says a delegate was deleted.
    Left out, every delegate has a row whose slug follows its pinned name, so a
    test about something else does not have to spell one out.

    `profiles` is the organization's model catalog, read only by an agent that may
    invent specialists. One usable profile by default, because that is the state a
    run is always in: the delegating agent's own model resolved before any of this.
    A profile whose label is `unusable` is one whose key has gone.
    """
    ctx = ctx or _ctx()
    service = AgentRunnerService(_db())
    agent = MagicMock(id=agent_id or uuid.uuid4(), current_version_id=uuid.uuid4())
    run = MagicMock(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        exposure_id=uuid.uuid4(),
        environment_id=uuid.uuid4(),
        surface="slack",
    )
    known_versions = versions or {}
    known_collections = collections or {}

    async def get_version(_db: Any, version_id: uuid.UUID, *, organization_id: uuid.UUID) -> Any:
        return known_versions.get(version_id)

    async def get_agent(_db: Any, delegate_id: uuid.UUID, *, organization_id: uuid.UUID) -> Any:
        if agents is not None:
            return agents.get(delegate_id)
        pinned = next((row for row in known_versions.values() if row.agent_id == delegate_id), None)
        name = "delegate" if pinned is None else str(pinned.spec["name"])
        return _agent_row(delegate_id, slug=_slug(name))

    async def get_collection(_db: Any, collection_id: uuid.UUID) -> Any:
        return known_collections.get(collection_id)

    catalog = [_profile("fast")] if profiles is None else profiles
    by_id = {profile.id: profile for profile in catalog}

    async def resolve_model(_ctx: Any, *, profile_id: uuid.UUID | None) -> Any:
        profile = by_id.get(profile_id)
        if profile is not None and profile.label == UNUSABLE_PROFILE:
            raise BadRequestError(message="That model has no key configured")
        label = f"model-{profile_id}" if profile is None else profile.label
        return MagicMock(
            profile_id=profile_id,
            label=label,
            provider="openai",
            secret_id=None,
            params={},
        )

    with (
        patch.object(
            service.registry,
            "get_runnable_spec",
            new=AsyncMock(return_value=(agent, spec, agent.current_version_id)),
        ),
        patch.object(service.models, "resolve", new=AsyncMock(side_effect=resolve_model)),
        patch.object(
            service.models, "list_profiles", new=AsyncMock(return_value=catalog)
        ) as list_profiles,
        patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
        patch.object(service.secrets, "resolve_for_bindings", new=AsyncMock(return_value={})),
        patch.object(
            service.workspaces,
            "open",
            new=AsyncMock(return_value=None if workspace is None else MagicMock(backend=workspace)),
        ),
        patch(f"{RUNNER}.workspace_snapshot", new=AsyncMock(return_value=set())),
        patch(f"{RUNNER}.knowledge_base_repo.get_by_id", new=AsyncMock(side_effect=get_collection)),
        patch(
            f"{RUNNER}.agent_repo.get_version", new=AsyncMock(side_effect=get_version)
        ) as fetch_version,
        patch(f"{RUNNER}.agent_repo.get", new=AsyncMock(side_effect=get_agent)),
        patch(f"{RUNNER}.agent_run_repo.create_run", new=AsyncMock(return_value=run)),
        patch(f"{RUNNER}.build_agent") as build,
    ):
        prepared = await service.prepare(ctx, agent.id)

    return _Prepared(prepared, build, fetch_version, list_profiles)


class TestAnAgentThatDoesNotDelegate:
    async def test_nothing_new_reaches_its_resources(self):
        """Delegation is opt-in, and an agent without it must assemble as it did.

        The check is on `resources` rather than on the runtime being None,
        because that dict is what every capability reads: a key present but
        empty would make the delegation capability offer tools with nothing
        behind them to an agent whose author never asked for any.
        """
        prepared = await _prepare(AgentSpec(name="Plain"))

        assert SUBAGENT_RUNTIME_RESOURCE not in prepared.resources

    async def test_a_disabled_binding_is_not_a_delegating_agent(self):
        """`enabled: false` is how a binding is switched off without losing its
        configuration, and it has to mean the same thing here as everywhere."""
        spec = AgentSpec(
            name="Paused",
            capabilities=[{"id": DELEGATION_CAPABILITY_ID, "config": {}, "enabled": False}],
        )

        prepared = await _prepare(spec)

        assert SUBAGENT_RUNTIME_RESOURCE not in prepared.resources


class TestTheRuntimeARunIsHanded:
    async def test_the_specialists_the_config_names_are_offered_by_name(self):
        prepared = await _prepare(_delegating(inline=[_specialist(name="summariser")]))

        runtime = prepared.runtime
        assert [entry.name for entry in runtime.subagents] == ["summariser"]
        assert runtime.named("summariser") is not None
        # A name the model invented is not a delegate.
        assert runtime.named("researcher") is None

    async def test_the_runtime_is_given_the_runs_ledger(self):
        """It cannot be constructed with one: the ledger is a product of the
        build, and the runtime had to be inside the resources that build read.
        Without this assignment every delegation reports zero cost."""
        prepared = await _prepare(_delegating(inline=[_specialist()]))

        assert prepared.runtime.ledger is prepared.build.return_value.ledger

    async def test_a_specialist_is_not_built_until_it_is_addressed(self):
        """A delegate the model never calls must cost nothing - building one
        constructs every capability it has and instruments the agent."""
        prepared = await _prepare(_delegating(inline=[_specialist()]))

        assert prepared.build.call_count == 1

        prepared.built("summariser")

        assert prepared.build.call_count == 2

    async def test_a_delegate_runs_on_the_runs_own_budget_guard(self):
        """Sharing the guard is what makes a delegation's spend visible to the
        parent's cap before the next request. Without it a delegate meters
        nothing the parent can see, at exactly the moment delegation multiplies
        spend."""
        prepared = await _prepare(_delegating(inline=[_specialist()]))

        assert prepared.built("summariser")["shared_budget"] is prepared.build.return_value.budget

    async def test_a_delegate_reaches_the_approval_queue_the_parent_is_waiting_on(self):
        """A specialist that needs a person needs the person already waiting."""
        prepared = await _prepare(_delegating(inline=[_specialist()]))

        assert prepared.built("summariser")["request_approval"] is prepared.prepared.approvals


class TestWhatAnInlineSpecialistCanReach:
    async def test_a_specialist_searches_its_own_collections_and_not_the_parents(self):
        """The parent's `resources` dict is mutable and shared for the length of
        the run, and `build_agent` reads `kb_collection_names` straight out of
        whatever it is given - so handing a specialist the parent's would grant
        it every collection the parent has. A specialist is a tempting place to
        reach a collection nobody granted precisely because it does not look
        like an agent."""
        ctx = _ctx()
        parent_collection, own_collection = uuid.uuid4(), uuid.uuid4()
        spec = _delegating(
            inline=[_specialist(collection_ids=[own_collection])],
            collection_ids=[parent_collection],
        )

        prepared = await _prepare(
            spec,
            ctx=ctx,
            collections={
                parent_collection: _collection(ctx.organization_id, "kb_parent"),
                own_collection: _collection(ctx.organization_id, "kb_specialist"),
            },
        )

        assert prepared.resources["kb_collection_names"] == ["kb_parent"]
        specialist_resources = prepared.built("summariser")["resources"]
        assert specialist_resources["kb_collection_names"] == ["kb_specialist"]
        assert specialist_resources is not prepared.resources

    async def test_a_specialist_with_no_model_of_its_own_runs_on_its_callers(self):
        profile_id = uuid.uuid4()
        spec = _delegating(inline=[_specialist()], model_profile_id=profile_id)

        prepared = await _prepare(spec)

        assert prepared.built("summariser")["model"].label == f"model-{profile_id}"

    async def test_a_specialist_that_names_a_model_gets_it(self):
        own_profile = uuid.uuid4()
        spec = _delegating(
            inline=[_specialist(model_profile_id=own_profile)], model_profile_id=uuid.uuid4()
        )

        prepared = await _prepare(spec)

        assert prepared.built("summariser")["model"].label == f"model-{own_profile}"

    async def test_a_specialist_is_built_without_the_means_to_delegate(self):
        """It does not delegate further by construction, so a capability bound on
        it anyway would offer a tool with nothing behind it."""
        spec = _delegating(
            inline=[_specialist(capabilities=[{"id": DELEGATION_CAPABILITY_ID, "config": {}}])]
        )

        prepared = await _prepare(spec)

        built = prepared.built("summariser")
        assert [binding.id for binding in built["spec"].capabilities] == []
        assert SUBAGENT_RUNTIME_RESOURCE not in built["resources"]

    async def test_a_specialist_has_no_mcp_connections_of_its_own(self):
        """An MCP connection is organization-scoped configuration; reaching one
        through a specialist nobody published is the wrong door."""
        prepared = await _prepare(_delegating(inline=[_specialist()]))

        assert prepared.built("summariser")["extra_toolsets"] == []


class TestSharingACapabilityWithADelegate:
    """`share_with_delegates` exists for the workspace, and the workspace is the
    difference between a fan-out and three agents that cannot use each other's
    work."""

    async def test_a_shared_workspace_is_the_parents_own_session(self):
        backend = MagicMock(name="workspace-backend")
        spec = _delegating(
            inline=[_specialist()],
            share=["sandbox"],
            capabilities=[{"id": "sandbox", "config": {}}],
        )

        prepared = await _prepare(spec, workspace=backend)

        built = prepared.built("summariser")
        assert built["resources"][WORKSPACE_BACKEND_RESOURCE] is backend
        # The binding travels as it stands, so the delegate reads and writes with
        # the configuration the parent was published with.
        assert [binding.id for binding in built["spec"].capabilities] == ["sandbox"]

    async def test_a_capability_that_is_not_shared_does_not_travel(self):
        backend = MagicMock(name="workspace-backend")
        spec = _delegating(inline=[_specialist()], capabilities=[{"id": "sandbox", "config": {}}])

        prepared = await _prepare(spec, workspace=backend)

        built = prepared.built("summariser")
        assert WORKSPACE_BACKEND_RESOURCE not in built["resources"]
        assert built["spec"].capabilities == []

    async def test_a_delegates_own_binding_wins_over_a_shared_one(self):
        """Its own configuration is the more specific statement of intent, and a
        spec holding one id twice would build one of the two with no indication
        which."""
        spec = _delegating(
            inline=[
                _specialist(capabilities=[{"id": "sandbox", "config": {"include_execute": False}}])
            ],
            share=["sandbox"],
            capabilities=[{"id": "sandbox", "config": {"include_execute": True}}],
        )

        prepared = await _prepare(spec, workspace=MagicMock())

        [binding] = prepared.built("summariser")["spec"].capabilities
        assert binding.config == {"include_execute": False}

    async def test_a_disabled_binding_is_not_shared(self):
        spec = _delegating(
            inline=[_specialist()],
            share=["sandbox"],
            capabilities=[{"id": "sandbox", "config": {}, "enabled": False}],
        )

        prepared = await _prepare(spec, workspace=MagicMock())

        assert prepared.built("summariser")["spec"].capabilities == []

    async def test_delegation_is_not_shared_however_the_stored_spec_asks(self):
        """Publish now refuses this id, and a spec stored before it did still runs.

        Shared, the parent's delegation binding would land on a delegate that binds
        none, and `_delegation_config` would read the *parent's* specialists,
        fan-out, depth and `allow_dynamic` as the delegate's own answers - handing a
        published agent a policy no reviewer of its spec could see. The delegate
        here binds nothing, so it must be built with nothing.
        """
        delegate_id = uuid.uuid4()
        pinned = _version(delegate_id, AgentSpec(name="Research Bot"))
        spec = _delegating(
            inline=[_specialist(name="parents-own-summariser")],
            subagents=[SubagentRef(agent_id=delegate_id, agent_version_id=pinned.id)],
            share=[DELEGATION_CAPABILITY_ID],
            max_depth=2,
            allow_dynamic=True,
        )

        prepared = await _prepare(spec, versions={pinned.id: pinned})

        built = prepared.built("research-bot")
        assert built["spec"].capabilities == []
        # And with no binding there is no nested runtime, so the parent's own
        # specialist is not reachable through the delegate and the delegate may not
        # invent one of its own.
        assert SUBAGENT_RUNTIME_RESOURCE not in built["resources"]


class TestAPublishedDelegate:
    async def test_it_runs_the_version_it_is_pinned_to(self):
        """Not whatever is published now, and not what the parent's environment
        resolves: `get_runnable_spec` resolves an environment, so a delegate
        that went through it would differ between a parent published in `dev`
        and the same parent in production."""
        delegate_id = uuid.uuid4()
        pinned = _version(delegate_id, AgentSpec(name="Research Bot", instructions="Cite."))
        spec = _delegating(
            subagents=[SubagentRef(agent_id=delegate_id, agent_version_id=pinned.id)]
        )

        prepared = await _prepare(spec, versions={pinned.id: pinned})

        [entry] = prepared.runtime.subagents
        assert (entry.agent_id, entry.agent_version_id) == (delegate_id, pinned.id)
        assert prepared.built("research-bot")["spec"].instructions == "Cite."

    async def test_the_model_addresses_it_by_the_handle_the_row_owns(self):
        """`agents.slug`, not a slug of the pinned name. The row's handle is what
        a channel mention resolves and what the Builder shows beside the pin, and
        it is unique per organization by constraint - so deriving a second one
        would offer the model a name the author was never shown, and instructions
        saying "delegate to deep-researcher" would address nothing."""
        delegate_id = uuid.uuid4()
        pinned = _version(delegate_id, AgentSpec(name="Research Bot"))
        spec = _delegating(
            subagents=[SubagentRef(agent_id=delegate_id, agent_version_id=pinned.id)]
        )

        prepared = await _prepare(
            spec,
            versions={pinned.id: pinned},
            agents={delegate_id: _agent_row(delegate_id, slug="deep-researcher")},
        )

        assert [entry.name for entry in prepared.runtime.subagents] == ["deep-researcher"]
        assert prepared.runtime.named("research-bot") is None

    async def test_a_delegate_whose_agent_is_gone_fails_the_run(self):
        """The same refusal a missing pin gets, rather than an `AttributeError`
        from reading a handle off nothing."""
        delegate_id = uuid.uuid4()
        pinned = _version(delegate_id, AgentSpec(name="Research Bot"))
        spec = _delegating(
            subagents=[SubagentRef(agent_id=delegate_id, agent_version_id=pinned.id)]
        )

        with pytest.raises(BadRequestError, match="no longer exists") as refused:
            await _prepare(spec, versions={pinned.id: pinned}, agents={})

        assert refused.value.details["agent_id"] == str(delegate_id)

    async def test_a_pinned_version_that_is_gone_fails_the_run(self):
        """Never a quiet fall back to the delegate's current version: the reason
        to pin is that nothing changes without somebody deciding, and a silent
        upgrade is worse than a refusal because nobody finds out."""
        delegate_id, version_id = uuid.uuid4(), uuid.uuid4()
        spec = _delegating(
            subagents=[SubagentRef(agent_id=delegate_id, agent_version_id=version_id)]
        )

        with pytest.raises(BadRequestError, match="no longer exists") as refused:
            await _prepare(spec, versions={})

        assert refused.value.details["agent_id"] == str(delegate_id)

    async def test_an_archived_delegate_fails_the_run(self):
        """Archiving is this product's one take-out-of-service action, and it has to
        reach the caller hardest to notice.

        A pin to an already archived agent is refused at publish, and a direct run
        of one is refused by `get_runnable_spec`. Neither covers the agent archived
        *after* a parent pinned it: that delegate kept answering indefinitely, for
        an author who had been told it was retired.
        """
        delegate_id = uuid.uuid4()
        pinned = _version(delegate_id, AgentSpec(name="Research Bot"))
        spec = _delegating(
            subagents=[SubagentRef(agent_id=delegate_id, agent_version_id=pinned.id)]
        )
        retired = _agent_row(delegate_id, slug="research-bot", status=AgentStatus.ARCHIVED.value)

        with pytest.raises(BadRequestError, match="is archived") as refused:
            await _prepare(spec, versions={pinned.id: pinned}, agents={delegate_id: retired})

        assert refused.value.details == {
            "agent_id": str(delegate_id),
            "slug": "research-bot",
        }

    async def test_a_pin_naming_another_agents_version_is_refused(self):
        """A version id is only meaningful through the agent that owns it - and
        the lookup is tenant-scoped, so the same refusal covers a pin that
        reaches across organizations."""
        pinned = _version(uuid.uuid4(), AgentSpec(name="Somebody Else"))
        spec = _delegating(
            subagents=[SubagentRef(agent_id=uuid.uuid4(), agent_version_id=pinned.id)]
        )

        with pytest.raises(BadRequestError, match="no longer exists"):
            await _prepare(spec, versions={pinned.id: pinned})

    async def test_it_gets_its_own_mcp_connections_back(self):
        """A delegate is a published agent, and half its tools coming from MCP
        does not make them optional."""
        delegate_id = uuid.uuid4()
        connection_id = uuid.uuid4()
        pinned = _version(delegate_id, AgentSpec(name="Linear Bot", mcp_server_ids=[connection_id]))
        spec = _delegating(
            subagents=[SubagentRef(agent_id=delegate_id, agent_version_id=pinned.id)]
        )

        with patch(
            f"{RUNNER}.build_toolsets_for_agent", new=AsyncMock(return_value=["linear-toolset"])
        ) as toolsets:
            prepared = await _prepare(spec, versions={pinned.id: pinned})
            built = prepared.built("linear-bot")

        assert toolsets.await_args_list[-1].kwargs["connection_ids"] == [connection_id]
        assert built["extra_toolsets"] == ["linear-toolset"]

    async def test_a_delegate_with_no_description_is_still_describable(self):
        """The description is what the parent's model reads before deciding to
        delegate, and an empty string is not something it can act on."""
        delegate_id = uuid.uuid4()
        pinned = _version(delegate_id, AgentSpec(name="Research Bot"))
        spec = _delegating(
            subagents=[SubagentRef(agent_id=delegate_id, agent_version_id=pinned.id)]
        )

        prepared = await _prepare(spec, versions={pinned.id: pinned})

        assert prepared.runtime.named("research-bot").description == "Research Bot"

    async def test_the_preferred_mode_the_pin_carries_reaches_the_capability(self):
        """A slow specialist is the case: the parent can carry on while it works."""
        delegate_id = uuid.uuid4()
        pinned = _version(delegate_id, AgentSpec(name="Slow Bot"))
        spec = _delegating(
            subagents=[
                SubagentRef(
                    agent_id=delegate_id, agent_version_id=pinned.id, preferred_mode="async"
                )
            ]
        )

        prepared = await _prepare(spec, versions={pinned.id: pinned})

        assert prepared.runtime.named("slow-bot").preferred_mode == "async"


class TestHowDeepDelegationGoes:
    """`max_depth` counts levels of delegation *including the configured agent's own*.

    Which is one less than the tree has left below it, and the subtraction is the
    whole of what the setting means: the field says "1 lets this agent delegate and
    its delegates not", so at 1 there is nothing left below and every delegate is
    built without the capability. It used to pass `max_depth` straight through as
    the remaining budget, which made the documented behaviour of `1` what `0` did -
    and shipped a default that allowed one nested level nobody had asked for.
    """

    @staticmethod
    def _two_levels(max_depth: int) -> tuple[AgentSpec, dict[uuid.UUID, MagicMock]]:
        """A parent that delegates to an agent which itself delegates."""
        grandchild_id, child_id = uuid.uuid4(), uuid.uuid4()
        grandchild = _version(grandchild_id, AgentSpec(name="Fact Checker"))
        child = _version(
            child_id,
            _delegating(
                name="Research Bot",
                subagents=[SubagentRef(agent_id=grandchild_id, agent_version_id=grandchild.id)],
            ),
        )
        parent = _delegating(
            subagents=[SubagentRef(agent_id=child_id, agent_version_id=child.id)],
            max_depth=max_depth,
        )
        return parent, {child.id: child, grandchild.id: grandchild}

    async def test_two_levels_lets_a_delegate_delegate_once_more(self):
        parent, versions = self._two_levels(max_depth=2)

        prepared = await _prepare(parent, versions=versions)
        built = prepared.built("research-bot")

        nested = built["resources"][SUBAGENT_RUNTIME_RESOURCE]
        assert [entry.name for entry in nested.subagents] == ["fact-checker"]
        # Nothing further: the grandchild is at the bound.
        assert nested.depth_remaining == 0
        # And it says how deep it is rather than leaving the capability to compute
        # it from two numbers out of two different specs, which is what used to
        # nest a delegation panel under the wrong parent.
        assert (prepared.runtime.depth, nested.depth) == (0, 1)
        # Every level shares the run's one ledger, so the nested runtime measures
        # the same total the parent's cap is checked against.
        assert nested.ledger is prepared.build.return_value.ledger
        # And one stash, because a delegation two levels down parks the run
        # somebody started and is continued from that run's stored state.
        assert nested.stash is prepared.runtime.stash

    async def test_the_default_stops_a_delegate_from_delegating_at_all(self):
        """One level, which is what `max_depth=1` says and what an author reads.

        The capability is *removed* rather than left in place with nothing to
        delegate to: that tool's description is context the model pays for on every
        turn, and the first thing it does with one is try it.
        """
        parent, versions = self._two_levels(max_depth=1)

        prepared = await _prepare(parent, versions=versions)
        built = prepared.built("research-bot")

        assert [binding.id for binding in built["spec"].capabilities] == []
        assert built["spec"].subagents == []
        assert SUBAGENT_RUNTIME_RESOURCE not in built["resources"]
        # And the grandchild's version was never loaded: resolving a delegate
        # nothing can address would be a query per run for nothing.
        assert prepared.get_version.await_count == 1

    @staticmethod
    def _three_levels(*, root: int, delegate: int) -> tuple[AgentSpec, dict[uuid.UUID, MagicMock]]:
        """A chain of four, so a delegate's own ceiling can be exceeded or not.

        The middle two both delegate, and `delegate` is the *middle* agent's own
        `max_depth` - the number its author chose and its reviewers read.
        """
        proofreader_id, grandchild_id, child_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        proofreader = _version(proofreader_id, AgentSpec(name="Proof Reader"))
        grandchild = _version(
            grandchild_id,
            _delegating(
                name="Fact Checker",
                subagents=[SubagentRef(agent_id=proofreader_id, agent_version_id=proofreader.id)],
            ),
        )
        child = _version(
            child_id,
            _delegating(
                name="Research Bot",
                subagents=[SubagentRef(agent_id=grandchild_id, agent_version_id=grandchild.id)],
                max_depth=delegate,
            ),
        )
        parent = _delegating(
            subagents=[SubagentRef(agent_id=child_id, agent_version_id=child.id)],
            max_depth=root,
        )
        return parent, {
            child.id: child,
            grandchild.id: grandchild,
            proofreader.id: proofreader,
        }

    async def test_a_caller_cannot_buy_a_delegate_more_nesting_than_its_own_spec(self):
        """A delegate's `max_depth` is its own author's ceiling, not a suggestion.

        The root here is configured for three levels and the delegate's published
        spec for one, so the delegate delegates and *its* delegates do not - which is
        what its own reviewers read. The budget used to be `depth_remaining - 1`,
        taking only the root's remainder: the delegate's ceiling was then exceeded by
        a caller it has never seen, and every extra level is another agent's model
        spend on the caller's budget. The whole argument for pinning a delegate to a
        version is that its author's decisions hold when somebody else calls it.
        """
        parent, versions = self._three_levels(root=3, delegate=1)

        prepared = await _prepare(parent, versions=versions)
        nested = prepared.built("research-bot")["resources"][SUBAGENT_RUNTIME_RESOURCE]

        # The delegate itself delegates, at `max_depth=1`, with nothing left below.
        assert [entry.name for entry in nested.subagents] == ["fact-checker"]
        assert nested.depth_remaining == 0
        # And the depth it reports is still what it is, told rather than computed
        # from a ceiling and a remainder that now come from two specs.
        assert nested.depth == 1

        grandchild = prepared.built("research-bot", "fact-checker")

        assert [binding.id for binding in grandchild["spec"].capabilities] == []
        assert grandchild["spec"].subagents == []
        assert SUBAGENT_RUNTIME_RESOURCE not in grandchild["resources"]
        # Two versions, not three: the proofreader is behind a delegation the
        # grandchild was built without, so resolving it would be a query for nothing.
        assert prepared.get_version.await_count == 2

    async def test_a_generous_delegate_still_stops_where_the_tree_does(self):
        """The other direction, and the reason the bound is a `min` of two numbers.

        A delegate configured for three levels called by a root with one left gets
        one. Its own ceiling says how deep it may go, never how deep the run it is
        inside may - that budget belongs to whoever started the run and is paying
        for it.
        """
        parent, versions = self._three_levels(root=2, delegate=3)

        prepared = await _prepare(parent, versions=versions)
        nested = prepared.built("research-bot")["resources"][SUBAGENT_RUNTIME_RESOURCE]

        assert nested.depth_remaining == 0
        grandchild = prepared.built("research-bot", "fact-checker")
        assert [binding.id for binding in grandchild["spec"].capabilities] == []
        assert prepared.get_version.await_count == 2

    def test_delegation_cannot_be_switched_off_through_the_depth(self):
        """`max_depth=0` is refused by the model rather than accepted and ignored.

        It would be a *second* off switch contradicting the first. Disabling the
        binding is how delegation is turned off - publish validation already refuses
        an agent whose binding is disabled while its spec still names delegates - and
        a `max_depth` of zero beside a list of pins would be configuration that reads
        as a decision and does nothing, with nothing refusing it.
        """
        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            SubagentsConfig(max_depth=0)


class TestASpecialistTheModelInvents:
    """`allow_dynamic`, resolved. The runner's half of it is two things: whether
    the agent may, and which models it may name - and both are database questions,
    which is why the capability is handed the answer rather than the setting.
    """

    async def test_an_agent_that_did_not_ask_for_it_gets_nothing(self):
        """The default, and the reason the capability reads the runtime rather than
        the config: one reader for one setting."""
        prepared = await _prepare(_delegating(inline=[_specialist()]))

        assert prepared.runtime.dynamic is None

    async def test_the_models_it_may_name_are_the_organizations_own_profiles(self):
        """Never free text. A model naming `openai:gpt-4.1` in an organization that
        holds no OpenAI key writes a run that dies at its first request with a
        provider error, and the model that named it had no way to know."""
        prepared = await _prepare(
            _delegating(inline=[_specialist()], allow_dynamic=True),
            profiles=[_profile("fast"), _profile("careful")],
        )

        dynamic = prepared.runtime.dynamic
        assert dynamic is not None
        assert dynamic.allowed_models == ("fast", "careful")

    async def test_a_profile_whose_key_has_gone_is_left_out_rather_than_failing_the_run(self):
        """One misconfigured model in a catalog of ten must not stop an agent that
        names none of it - the same reasoning `resolve` applies to a fallback
        chain. What it must not do is stay on a list a model is told it may use."""
        prepared = await _prepare(
            _delegating(allow_dynamic=True),
            profiles=[_profile("fast"), _profile(UNUSABLE_PROFILE)],
        )

        dynamic = prepared.runtime.dynamic
        assert dynamic is not None
        assert dynamic.allowed_models == ("fast",)

    async def test_the_catalog_is_read_once_for_the_whole_tree(self):
        """It is a fact about the organization, not about a level, and reading it
        costs a query and a vault unseal per profile. Two nested levels that both
        allow dynamic specialists would otherwise pay for it twice."""
        grandchild_id = uuid.uuid4()
        grandchild = _version(grandchild_id, AgentSpec(name="Fact Checker"))
        child_id = uuid.uuid4()
        child = _version(
            child_id,
            _delegating(
                name="Research Bot",
                allow_dynamic=True,
                subagents=[SubagentRef(agent_id=grandchild_id, agent_version_id=grandchild.id)],
            ),
        )
        parent = _delegating(
            subagents=[SubagentRef(agent_id=child_id, agent_version_id=child.id)],
            allow_dynamic=True,
            max_depth=2,
        )

        prepared = await _prepare(
            parent, versions={child.id: child, grandchild.id: grandchild}, profiles=[_profile("f")]
        )
        nested = prepared.built("research-bot")["resources"][SUBAGENT_RUNTIME_RESOURCE]

        assert prepared.runtime.dynamic is not None
        assert nested.dynamic is not None
        assert prepared.list_profiles.await_count == 1

    async def test_a_delegate_inherits_nothing_and_decides_for_itself(self):
        """A published delegate is reviewed on its own spec, so whether it may
        invent specialists is a question its own author answered - not one its
        caller answers for it."""
        child_id = uuid.uuid4()
        child = _version(child_id, _delegating(name="Research Bot"))
        parent = _delegating(
            subagents=[SubagentRef(agent_id=child_id, agent_version_id=child.id)],
            allow_dynamic=True,
            max_depth=2,
        )

        prepared = await _prepare(parent, versions={child.id: child})
        nested = prepared.built("research-bot")["resources"][SUBAGENT_RUNTIME_RESOURCE]

        assert prepared.runtime.dynamic is not None
        assert nested.dynamic is None

    async def test_at_the_depth_bound_a_delegate_may_not_invent_one_either(self):
        """A specialist a model invents is a level of delegation like any other, so
        an agent at the bound gets neither a delegate nor the tools to make one -
        and it gets them by having the whole capability removed, which is what also
        removes the two dynamic entry points."""
        child_id = uuid.uuid4()
        child = _version(child_id, _delegating(name="Research Bot", allow_dynamic=True))
        parent = _delegating(
            subagents=[SubagentRef(agent_id=child_id, agent_version_id=child.id)], max_depth=1
        )

        prepared = await _prepare(parent, versions={child.id: child})
        built = prepared.built("research-bot")

        assert [binding.id for binding in built["spec"].capabilities] == []
        assert SUBAGENT_RUNTIME_RESOURCE not in built["resources"]

    async def test_one_is_built_through_the_factory_with_the_runs_budget(self):
        """The property the whole phase exists for, at the seam the runner owns.

        A specialist built without `shared_budget` meters into a ledger of its own,
        so the cap on the run somebody started never sees what it spent - and that
        is exactly what the delegation library does if it is left to build one.
        """
        prepared = await _prepare(_delegating(allow_dynamic=True), profiles=[_profile("fast")])

        built = prepared.invented(model="fast")

        assert built["shared_budget"] is prepared.prepared.built.budget
        assert built["spec"].instructions == "Be brief."
        assert built["model"].label == "fast"

    async def test_one_reaches_nothing_the_agent_that_invented_it_was_granted(self):
        """No capabilities, no collections, no skills, no MCP connections and no
        delegates. A specialist a model wrote is the tempting route to a
        credential the organization granted the *parent*, precisely because
        nobody thinks of it as an agent."""
        prepared = await _prepare(
            _delegating(allow_dynamic=True, collection_ids=[uuid.uuid4()]),
            profiles=[_profile("fast")],
        )

        built = prepared.invented(model="fast")

        spec = built["spec"]
        assert (spec.capabilities, spec.subagents, spec.skill_ids, spec.mcp_server_ids) == (
            [],
            [],
            [],
            [],
        )
        assert built["resources"] == {
            "kb_collection_names": [],
            "kb_collection_ids": [],
            "skills": [],
            "context_files": [],
        }
        assert built["secrets"] == {}
        assert built["extra_toolsets"] == []
        # Its own agent is the run's, as an inline specialist's is: nothing
        # attributes a run row to a specialist, and this id keys the workspace.
        assert built["agent_id"] == prepared.prepared.agent.id


class TestRefusals:
    async def test_a_delegate_already_running_in_this_tree_is_refused(self):
        """Pinning makes a cycle hard to reach by accident but not impossible,
        and a cycle at run time is a run that ends when the step limit does,
        having spent everything up to it."""
        parent_agent_id, child_id = uuid.uuid4(), uuid.uuid4()
        back_to_parent = _version(parent_agent_id, AgentSpec(name="Orchestrator"))
        child = _version(
            child_id,
            _delegating(
                name="Research Bot",
                subagents=[
                    SubagentRef(agent_id=parent_agent_id, agent_version_id=back_to_parent.id)
                ],
            ),
        )
        # Two levels, because a cycle needs a nested one to close: at the default
        # depth the child is built without the capability at all, so the pin back to
        # the parent is never resolved and there is nothing to refuse.
        parent = _delegating(
            subagents=[SubagentRef(agent_id=child_id, agent_version_id=child.id)], max_depth=2
        )

        with pytest.raises(BadRequestError, match="already running") as refused:
            await _prepare(
                parent,
                versions={child.id: child, back_to_parent.id: back_to_parent},
                agent_id=parent_agent_id,
            )

        assert refused.value.details["agent_id"] == str(parent_agent_id)

    async def test_an_agent_that_delegates_to_itself_is_refused(self):
        agent_id = uuid.uuid4()
        pinned = _version(agent_id, AgentSpec(name="Orchestrator"))
        parent = _delegating(subagents=[SubagentRef(agent_id=agent_id, agent_version_id=pinned.id)])

        with pytest.raises(BadRequestError, match="already running"):
            await _prepare(parent, versions={pinned.id: pinned}, agent_id=agent_id)

    async def test_two_delegates_answering_to_one_name_are_refused(self):
        """`named()` answers with the first match, so the model would address one
        and silently get the other."""
        delegate_id = uuid.uuid4()
        pinned = _version(delegate_id, AgentSpec(name="Summariser"))
        parent = _delegating(
            inline=[_specialist(name="summariser")],
            subagents=[SubagentRef(agent_id=delegate_id, agent_version_id=pinned.id)],
        )

        with pytest.raises(BadRequestError, match="same name") as refused:
            await _prepare(parent, versions={pinned.id: pinned})

        assert refused.value.details["names"] == ["summariser"]


def _outcome(**fields: Any) -> DelegationOutcome:
    return DelegationOutcome(
        subagent=fields.pop("subagent", "research-bot"),
        task_id=fields.pop("task_id", "4f2a1b8c"),
        status=fields.pop("status", "completed"),
        cost_usd=fields.pop("cost_usd", Decimal("0.42")),
        input_tokens=fields.pop("input_tokens", 1200),
        output_tokens=fields.pop("output_tokens", 300),
        **fields,
    )


def _model(**fields: Any) -> MagicMock:
    return MagicMock(
        label=fields.pop("label", "GPT-4.1 (prod)"),
        provider=fields.pop("provider", "openai"),
        secret_id=fields.pop("secret_id", None),
    )


def _parent_run() -> MagicMock:
    return MagicMock(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        exposure_id=uuid.uuid4(),
        environment_id=uuid.uuid4(),
        surface="slack",
    )


@dataclass
class _Recorded:
    """What recording one delegation did."""

    child_run_id: uuid.UUID | None
    parent: MagicMock
    queued: list[Any]

    @property
    def only(self) -> Any:
        [delegation] = self.queued
        return delegation


async def _record(
    outcome: DelegationOutcome,
    *,
    attribution: dict[uuid.UUID, Any] | None = None,
) -> _Recorded:
    """Report one delegation to a recorder, and see what it left behind."""
    run = _parent_run()
    queued: list[Any] = []
    record = AgentRunnerService(_db())._delegation_recorder(
        run=run,
        attribution=attribution or {},
        queued=queued,
    )

    with (
        patch(f"{RUNNER}.agent_run_repo.create_run", new=AsyncMock()) as create_run,
        patch(f"{RUNNER}.agent_run_repo.record_delegated_run", new=AsyncMock()) as write,
    ):
        recorded = await record(outcome)

    # The property the queue exists for: a delegation reaches no database while
    # the run is going, so two of them overlapping cannot corrupt the session
    # everything else in the request is using.
    create_run.assert_not_awaited()
    write.assert_not_awaited()
    return _Recorded(child_run_id=recorded, parent=run, queued=queued)


class TestRecordingADelegation:
    """A delegation to a published agent gets a run row; a specialist does not.

    The row is what makes the delegate's own monthly total answerable and what a
    delegation panel links to. It is deliberately not part of the organization's
    total: the parent's row already holds these tokens.

    Nothing is written while the run is going. Two `sync` delegations can overlap
    - pydantic-ai runs several tool calls from one model response concurrently -
    and two inserts at once on the request's session do not make a slow query,
    they corrupt the session and take the parent's run row with them.
    """

    async def test_a_delegation_is_described_and_its_id_answered_immediately(self):
        agent_id, version_id = uuid.uuid4(), uuid.uuid4()
        model = _model(secret_id=uuid.uuid4())
        outcome = _outcome(agent_id=agent_id, agent_version_id=version_id)

        result = await _record(outcome, attribution={version_id: model})

        assert result.only.agent_id == agent_id
        assert result.only.agent_version_id == version_id
        # The library's own task id, so this row and `check_task('4f2a1b8c')` in
        # the transcript are the same delegation rather than two things that look
        # related.
        assert result.only.task_id == "4f2a1b8c"
        # The model that actually answered, so the cost dashboard does not group
        # this under "not recorded" - and only the three fields a row records, not
        # the resolved spec, which carries a live credential.
        assert result.only.model_label == "GPT-4.1 (prod)"
        assert result.only.provider == "openai"
        assert result.only.secret_id == model.secret_id
        assert result.only.status is RunStatus.COMPLETED
        assert result.only.cost_usd == Decimal("0.42")
        assert (result.only.input_tokens, result.only.output_tokens) == (1200, 300)
        # The id is allocated here rather than by the database, because the
        # surface is handed it while the run is still going: it is how a
        # delegation panel finds the run history entry it produced.
        assert result.child_run_id == result.only.id

    async def test_a_failed_delegation_is_recorded_as_a_failed_run(self):
        version_id = uuid.uuid4()
        outcome = _outcome(
            agent_id=uuid.uuid4(),
            agent_version_id=version_id,
            status="failed",
            error="the delegate timed out",
        )

        result = await _record(outcome, attribution={version_id: _model()})

        assert result.only.status is RunStatus.FAILED
        assert result.only.error == "the delegate timed out"

    async def test_a_cancelled_delegation_is_recorded_as_cancelled(self):
        version_id = uuid.uuid4()
        outcome = _outcome(agent_id=uuid.uuid4(), agent_version_id=version_id, status="cancelled")

        result = await _record(outcome, attribution={version_id: _model()})

        assert result.only.status is RunStatus.CANCELLED

    async def test_an_unpriced_request_of_its_own_makes_a_delegations_share_a_floor(self):
        """The flag travels with the share, so it describes the delegate's requests.

        Read off the outcome rather than off the run's ledger, which is what it used
        to be: a *parent* on a model `genai-prices` does not know made every child
        row in the run partial, while a delegate that genuinely went unpriced inside
        an otherwise priced run was marked nothing at all once the parent's requests
        were all priced.
        """
        version_id = uuid.uuid4()
        outcome = _outcome(agent_id=uuid.uuid4(), agent_version_id=version_id, cost_is_partial=True)

        result = await _record(outcome, attribution={version_id: _model()})

        assert result.only.cost_is_partial is True

    async def test_a_delegation_whose_own_requests_were_priced_is_not_a_floor(self):
        """The other half: the run's other agents cannot mark this share partial."""
        version_id = uuid.uuid4()
        outcome = _outcome(agent_id=uuid.uuid4(), agent_version_id=version_id)

        result = await _record(outcome, attribution={version_id: _model()})

        assert result.only.cost_is_partial is False

    async def test_a_delegations_row_spans_its_own_start_and_end(self):
        """agenticos#191: the span is the delegate's, not the settlement's.

        Both ends used to be `now` at the moment the delegation was reported,
        which for a background one is the poll that collected it - so its row read
        as a zero-duration run at the wrong time. Off the handle instead, the row
        carries the interval the delegate actually ran for.
        """
        version_id = uuid.uuid4()
        started = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
        ended = datetime(2026, 8, 5, 9, 0, 40, tzinfo=UTC)
        outcome = _outcome(
            agent_id=uuid.uuid4(),
            agent_version_id=version_id,
            started_at=started,
            ended_at=ended,
        )

        result = await _record(outcome, attribution={version_id: _model()})

        assert result.only.started_at == started
        assert result.only.ended_at == ended

    async def test_an_outcome_carrying_no_times_falls_back_to_a_zero_span(self):
        """agenticos#191: a handle with no times must not write a null.

        A terminal handle that carried neither a start nor an end - all the outcome
        has to offer - leaves both columns, which are non-null, to fall back to
        `now`: a zero-duration run recorded where it was reported, rather than a
        `NULL` the insert rejects. (The refusal that creates no handle at all writes
        no row; that path never reaches the recorder - see
        `tests/test_subagents_capability.py::TestBackgroundDelegations`.)
        """
        version_id = uuid.uuid4()
        outcome = _outcome(agent_id=uuid.uuid4(), agent_version_id=version_id)

        result = await _record(outcome, attribution={version_id: _model()})

        assert result.only.started_at is not None
        assert result.only.ended_at == result.only.started_at

    async def test_a_handle_with_an_end_but_no_start_reads_as_an_instant(self):
        """A task that reached a terminal status without executing - cancelled or
        failed before it began - has an end stamped and no start. The row takes the
        end for both, so its span is an instant at the right time rather than one
        that ends before it began."""
        version_id = uuid.uuid4()
        ended = datetime(2026, 8, 5, 9, 0, 40, tzinfo=UTC)
        outcome = _outcome(
            agent_id=uuid.uuid4(),
            agent_version_id=version_id,
            status="cancelled",
            started_at=None,
            ended_at=ended,
        )

        result = await _record(outcome, attribution={version_id: _model()})

        assert result.only.started_at == ended
        assert result.only.ended_at == ended

    async def test_an_inline_specialist_records_nothing(self):
        """It has no agent to attribute a row to: it is not versioned, nothing
        else can reference it, and its cost is already the parent's."""
        result = await _record(_outcome())

        assert result.child_run_id is None
        assert result.queued == []

    async def test_a_delegate_this_run_never_resolved_records_nothing(self):
        """Nothing here can say what it ran on, and a row attributed by guess is
        worse than no row - it would count towards a real agent's month."""
        outcome = _outcome(agent_id=uuid.uuid4(), agent_version_id=uuid.uuid4())

        result = await _record(outcome, attribution={})

        assert result.child_run_id is None
        assert result.queued == []


class TestTwoDelegationsInOneStep:
    """The case the queue exists for, driven through a real model.

    A `sync` delegation holds its own tool call, and that is not the same as
    happening alone: pydantic-ai executes the tool calls from one model response
    concurrently, and `parallel_tool_calls` is unset by default, so how many a
    step contains is the provider's decision. Two overlapping recorders on the
    request's `AsyncSession` is a corrupted session, not a slow query.
    """

    @staticmethod
    def _two_calls_then_an_answer() -> FunctionModel:
        """A model that emits two `task` calls in one response, then answers."""

        def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            if len(messages) == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart("delegate", {"task_id": "aaaaaaaa"}, tool_call_id="a"),
                        ToolCallPart("delegate", {"task_id": "bbbbbbbb"}, tool_call_id="b"),
                    ]
                )
            return ModelResponse(parts=[TextPart("both delegations are in")])

        return FunctionModel(respond)

    async def _run_two_delegations(self) -> tuple[list[Any], list[str], AsyncMock]:
        """Run an agent whose one step delegates twice, through the real recorder."""
        version_id = uuid.uuid4()
        queued: list[Any] = []
        record = AgentRunnerService(_db())._delegation_recorder(
            run=_parent_run(),
            attribution={version_id: _model()},
            queued=queued,
        )
        overlap: list[str] = []
        agent: Agent[None, str] = Agent(self._two_calls_then_an_answer())

        @agent.tool_plain
        async def delegate(task_id: str) -> str:
            """Stand in for one `sync` delegation: it runs, then it is recorded."""
            overlap.append(f"start:{task_id}")
            # Yield, so a serialised implementation would show start/end pairs
            # rather than the interleaving below.
            await asyncio.sleep(0)
            recorded = await record(
                _outcome(task_id=task_id, agent_id=uuid.uuid4(), agent_version_id=version_id)
            )
            overlap.append(f"end:{task_id}")
            return str(recorded)

        with patch(f"{RUNNER}.agent_run_repo.record_delegated_run", new=AsyncMock()) as write:
            await agent.run("delegate twice")

        return queued, overlap, write

    async def test_they_overlap_and_neither_touches_the_database(self):
        queued, overlap, write = await self._run_two_delegations()

        # Proof the concurrency is real rather than asserted: b starts before a
        # finishes. If pydantic-ai ever serialised tool calls this would read
        # start:a, end:a, start:b, end:b - and the test would be worth deleting.
        assert overlap == ["start:aaaaaaaa", "start:bbbbbbbb", "end:aaaaaaaa", "end:bbbbbbbb"]
        write.assert_not_awaited()
        assert len(queued) == 2

    async def test_both_get_a_row_of_their_own(self):
        queued, _overlap, _write = await self._run_two_delegations()

        # Distinct ids, allocated in the recorder: two delegations that shared one
        # would be one row, and the second panel would link to the first's run.
        assert len({delegation.id for delegation in queued}) == 2
        assert {delegation.task_id for delegation in queued} == {"aaaaaaaa", "bbbbbbbb"}


class TestWritingTheQueuedRows:
    """The run's terminal write, which is the only place the session is certainly
    not shared with a tool call."""

    @staticmethod
    def _prepared(delegations: list[Any]) -> MagicMock:
        prepared = MagicMock()
        prepared.run = _parent_run()
        prepared.built.ledger = SpendLedger()
        prepared.delegations = delegations
        prepared.workspace = None
        prepared.ctx = None
        return prepared

    @staticmethod
    def _queued(**fields: Any) -> RecordedDelegation:
        moment = datetime(2026, 8, 4, 12, 30, tzinfo=UTC)
        return RecordedDelegation(
            id=fields.pop("id", uuid.uuid4()),
            agent_id=fields.pop("agent_id", uuid.uuid4()),
            agent_version_id=fields.pop("agent_version_id", uuid.uuid4()),
            task_id=fields.pop("task_id", "4f2a1b8c"),
            status=fields.pop("status", RunStatus.COMPLETED),
            model_label="GPT-4.1 (prod)",
            provider="openai",
            secret_id=fields.pop("secret_id", uuid.uuid4()),
            input_tokens=1200,
            output_tokens=300,
            cost_usd=Decimal("0.42"),
            cost_is_partial=False,
            started_at=moment,
            ended_at=moment,
            **fields,
        )

    async def test_a_queued_delegation_becomes_a_row_under_the_parent(self):
        delegation = self._queued()
        prepared = self._prepared([delegation])
        service = AgentRunnerService(_db())

        with (
            patch(f"{RUNNER}.agent_run_repo.finish_run", new=AsyncMock()),
            patch(f"{RUNNER}.agent_run_repo.record_delegated_run", new=AsyncMock()) as write,
        ):
            await service.finish(prepared, status=RunStatus.COMPLETED)

        written = write.await_args.kwargs
        # The id the surface was already given, not one the database invents.
        assert written["run_id"] == delegation.id
        assert written["parent_run_id"] == prepared.run.id
        assert written["subagent_task_id"] == "4f2a1b8c"
        assert written["status"] == RunStatus.COMPLETED.value
        assert written["cost_usd"] == Decimal("0.42")
        assert written["model_label"] == "GPT-4.1 (prod)"
        # Read off the parent's row: they describe the run, not the delegation.
        assert written["organization_id"] == prepared.run.organization_id
        assert written["user_id"] == prepared.run.user_id
        assert written["conversation_id"] == prepared.run.conversation_id
        assert written["exposure_id"] == prepared.run.exposure_id
        # A delegation from Slack is still Slack.
        assert written["surface"] == "slack"
        # And no environment: that column says which environment resolved the
        # version, and a delegate's version came from a pin.
        assert "environment_id" not in written

    async def test_the_parent_row_is_written_before_the_rows_that_reference_it(self):
        """They carry `parent_run_id`. The parent's row exists from the start of
        the run, so this is belt and braces - but a change that created it later
        would break the foreign key silently, and this is what would notice."""
        order: list[str] = []
        prepared = self._prepared([self._queued()])
        service = AgentRunnerService(_db())

        async def note(name: str):
            async def call(*_args: Any, **_kwargs: Any) -> MagicMock:
                order.append(name)
                return MagicMock()

            return call

        with (
            patch(
                f"{RUNNER}.agent_run_repo.finish_run",
                new=AsyncMock(side_effect=await note("parent")),
            ),
            patch(
                f"{RUNNER}.agent_run_repo.record_delegated_run",
                new=AsyncMock(side_effect=await note("delegation")),
            ),
        ):
            await service.finish(prepared, status=RunStatus.COMPLETED)

        assert order == ["parent", "delegation"]

    async def test_a_cancelled_run_still_writes_what_it_delegated(self):
        """A delegation that spent money and recorded nothing is the hole
        cancellation would otherwise open."""
        prepared = self._prepared([self._queued(), self._queued()])
        service = AgentRunnerService(_db())

        with (
            patch(f"{RUNNER}.agent_run_repo.finish_run", new=AsyncMock()),
            patch(f"{RUNNER}.agent_run_repo.record_delegated_run", new=AsyncMock()) as write,
        ):
            await service.finish(prepared, status=RunStatus.CANCELLED)

        assert write.await_count == 2

    async def test_a_row_that_cannot_be_written_does_not_replace_the_runs_outcome(self):
        """It shares a `finally` with the parent's cost row. A delegate deleted
        mid-run must not turn a completed run into a storage error - the money is
        on the parent's row either way."""
        prepared = self._prepared([self._queued()])
        service = AgentRunnerService(_db())

        with (
            patch(f"{RUNNER}.agent_run_repo.finish_run", new=AsyncMock()) as finish_run,
            patch(
                f"{RUNNER}.agent_run_repo.record_delegated_run",
                new=AsyncMock(side_effect=RuntimeError("the delegate is gone")),
            ),
        ):
            await service.finish(prepared, status=RunStatus.COMPLETED)

        assert finish_run.await_args.kwargs["status"] == RunStatus.COMPLETED.value

    async def test_a_row_that_cannot_be_written_does_not_take_the_others_with_it(self):
        """One savepoint and one guard per delegation, not one around the loop.

        Guarding the loop abandoned every delegation after the failure - and on a
        real database it did worse than that: the failed insert leaves the
        transaction aborted, so the commit that would have written the parent's
        finished row raises too.
        `tests/integration/test_delegation_row_failures.py` is where that half is
        proven, because a mocked session has no transaction to abort.
        """
        prepared = self._prepared([self._queued(), self._queued()])
        service = AgentRunnerService(_db())
        attempted: list[uuid.UUID] = []

        async def refuse_the_first(*_args: Any, **kwargs: Any) -> MagicMock:
            attempted.append(kwargs["run_id"])
            if len(attempted) == 1:
                raise RuntimeError("the delegate is gone")
            return MagicMock()

        with (
            patch(f"{RUNNER}.agent_run_repo.finish_run", new=AsyncMock()),
            patch(
                f"{RUNNER}.agent_run_repo.record_delegated_run",
                new=AsyncMock(side_effect=refuse_the_first),
            ),
        ):
            await service.finish(prepared, status=RunStatus.COMPLETED)

        assert attempted == [delegation.id for delegation in prepared.delegations]

    async def test_a_run_that_delegated_nothing_writes_nothing(self):
        prepared = self._prepared([])
        service = AgentRunnerService(_db())

        with (
            patch(f"{RUNNER}.agent_run_repo.finish_run", new=AsyncMock()),
            patch(f"{RUNNER}.agent_run_repo.record_delegated_run", new=AsyncMock()) as write,
        ):
            await service.finish(prepared, status=RunStatus.COMPLETED)

        write.assert_not_awaited()


class TestResumingIntoADelegation:
    """A continued run is reassembled from scratch, so the place has to be put back.

    Nothing survives from the turn that parked: `resume` resolves the whole tree
    again from the version the run was parked on, which is what makes it safe to
    continue a run in another process a day later. So the stashed place travels
    through the assembly, and every level of the fresh tree has to be able to find
    it - a delegate two levels down parks the run somebody started, and it is that
    run's stored state the continuation comes out of.
    """

    async def test_the_reassembled_tree_holds_the_place_the_parked_delegate_left(self):
        parked_at = "the-parents-task-call"
        frame = {
            "tool_call_id": parked_at,
            "task_id": "4f2a1b8c",
            "subagent": "summariser",
            "messages": [{"kind": "request", "parts": []}],
        }
        run = MagicMock(
            id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            agent_version_id=uuid.uuid4(),
            conversation_id=None,
            exposure_id=None,
            environment_id=None,
            surface="api",
            status=RunStatus.AWAITING_APPROVAL.value,
            paused_state={"messages": [], "tool_call_ids": {}, "delegations": [frame]},
            model_label="gpt-4.1",
            input_tokens=0,
            output_tokens=0,
            cost_usd=Decimal(0),
            cost_is_partial=False,
        )
        spec = _delegating(inline=[_specialist()])
        version = MagicMock(id=run.agent_version_id, agent_id=run.agent_id)
        version.spec = spec.model_dump(mode="json")
        service = AgentRunnerService(_db())

        with (
            patch(f"{RUNNER}.agent_run_repo.claim_parked_run", new=AsyncMock(return_value=run)),
            patch(
                f"{RUNNER}.agent_run_repo.list_approvals_for_run", new=AsyncMock(return_value=[])
            ),
            patch(f"{RUNNER}.agent_run_repo.mark_running", new=AsyncMock()),
            patch(f"{RUNNER}.agent_run_repo.finish_run", new=AsyncMock()),
            patch(f"{RUNNER}.agent_repo.get_version", new=AsyncMock(return_value=version)),
            patch.object(service.registry, "get", new=AsyncMock(return_value=MagicMock())),
            patch.object(service.models, "resolve", new=AsyncMock(return_value=MagicMock())),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch.object(service.secrets, "resolve_for_bindings", new=AsyncMock(return_value={})),
            patch.object(service.workspaces, "open", new=AsyncMock(return_value=None)),
            patch(f"{RUNNER}.build_agent") as build,
        ):
            build.return_value.agent.run = AsyncMock(return_value=MagicMock(output="continued"))
            segment = await service.resume(_ctx(), run.id)

        assert segment.output == "continued"
        runtime = build.call_args_list[0].kwargs["resources"][SUBAGENT_RUNTIME_RESOURCE]
        assert list(runtime.stash.resuming) == [parked_at]
        # And the replay is told to run that `task` call again, which is what puts
        # the capability in a position to continue the delegate instead of starting
        # one. Without it Pydantic AI refuses the resume as incomplete.
        deferred = build.return_value.agent.run.call_args.kwargs["deferred_tool_results"]
        assert list(deferred.approvals) == [parked_at]


class TestWhoseMonthADelegationCountsTowards:
    """The two totals behaving alike is the bug this pair exists to keep fixed.

    A run has one ledger, so a delegate's tokens are already inside the parent
    run's cost. The organization's total must therefore skip the child row, and
    the agent's total must not - those rows are the only record of what the
    delegate itself cost.
    """

    async def test_an_agents_month_counts_the_runs_it_was_delegated_into(self):
        ctx = _ctx()
        agent_id = uuid.uuid4()

        with patch(
            f"{RUNNER}.agent_run_repo.sum_cost_since", new=AsyncMock(return_value=Decimal("40"))
        ) as total:
            spent = await AgentRunnerService(_db()).monthly_spend(ctx, agent_id=agent_id)

        assert spent == Decimal("40")
        assert total.await_args.kwargs["include_delegations"] is True
        assert total.await_args.kwargs["agent_id"] == agent_id
        assert total.await_args.kwargs["since"] == month_start()

    async def test_the_organizations_month_does_not(self):
        """Counting both would bill the organization twice for one request."""
        with (
            patch(
                "app.services.spend.agent_run_repo.sum_cost_since",
                new=AsyncMock(return_value=Decimal("13")),
            ) as total,
            patch(
                "app.services.spend.ingestion_spend_repo.sum_cost_since",
                new=AsyncMock(return_value=Decimal("0")),
            ),
        ):
            spent = await AgentRunnerService(_db()).monthly_spend(_ctx())

        assert spent == Decimal("13")
        # Left to the default rather than asked for: a caller added later gets a
        # total that does not double-count.
        assert "include_delegations" not in total.await_args.kwargs


class TestTheRuntimeIsOptional:
    def test_a_runtime_with_no_recorder_is_a_run_with_nothing_to_write_to(self):
        """A preview resolves no tree and records nothing; the capability offers
        no delegates rather than raising."""
        runtime = SubagentRuntime()

        assert runtime.subagents == ()
        assert runtime.record is None
        assert runtime.named("anything") is None

    def test_a_resolved_specialist_carries_no_agent_to_attribute_a_row_to(self):
        entry = ResolvedSubagent(name="summariser", description="brief", build=MagicMock())

        assert (entry.agent_id, entry.agent_version_id) == (None, None)
