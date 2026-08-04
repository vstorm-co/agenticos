"""Publish-time validation for delegation - the checks a delegate can hide behind.

A delegating agent is the one place this platform hands an agent's reach to
something else, and there are two ways to smuggle something through it. An inline
specialist is an agent in every way except that nobody thinks of it as one, so a
collection, a key or an ungranted capability attached to it would sail past a
validator that only walked the parent's own bindings. And a pin to a published
agent is three references wearing one shape - an agent, a version, and the right
to run it - so an existence check alone would happily run another tenant's row.

What is defended here:

*A refusal looks like an absence.* A delegate the publisher may not run reports
the same "Agent not found" as one that does not exist, exactly as the collection
check does, so agent ids cannot be probed one guess at a time.

*One validator, used twice.* A specialist goes through the same binding, secret
and collection helpers the parent does. A second copy would drift, and the half
that drifted would be the half nobody reviews.

*A cycle is caught while somebody is looking at a form.* `max_depth` bounds how
deep one delegation goes, not whether the graph loops.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.agents.capabilities import REGISTRY, load_builtins, register
from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import AgentStatus
from app.db.models.resource_grant import Visibility
from app.services import agent_registry
from app.services.agent_registry import (
    DEFAULT_GRANTED_SCOPES,
    DELEGATION_CAPABILITY_ID,
    AgentRegistryService,
    slugify,
)
from tests.test_agent_registry import _agent, _ctx, _db, _spec, _version

pytestmark = pytest.mark.anyio

DELEGATE_SCOPE = "agents:delegate"


@pytest.fixture(autouse=True)
def builtins_loaded():
    """The delegation capability has to be registered for its id to resolve."""
    load_builtins()


@pytest.fixture(autouse=True)
def model_profile_exists(monkeypatch):
    """Every spec here names a model that resolves - the model is not the subject."""
    monkeypatch.setattr(
        agent_registry.credential_repo, "get_profile", AsyncMock(return_value=MagicMock())
    )


def _delegating(
    config: dict[str, Any],
    *,
    subagents: list[dict[str, Any]] | None = None,
    capabilities: list[dict[str, Any]] | None = None,
    name: str = "Support",
) -> AgentSpec:
    """A spec that delegates: the capability bound, plus whatever it points at."""
    return AgentSpec(
        name=name,
        model_profile_id=uuid4(),
        capabilities=[
            {"id": DELEGATION_CAPABILITY_ID, "config": config},
            *(capabilities or []),
        ],
        subagents=subagents or [],
    )


def _pin(agent_id: UUID, version_id: UUID) -> dict[str, Any]:
    return {"agent_id": str(agent_id), "agent_version_id": str(version_id)}


def _specialist(name: str = "summariser", **overrides: Any) -> dict[str, Any]:
    return {
        "name": name,
        "description": "Summarises a document in three bullets",
        "instructions": "Summarise what you are given.",
        **overrides,
    }


def _published(ctx: AuthContext, name: str, *, slug: str | None = None) -> Any:
    """A published agent, with the handle its row would actually carry.

    The slug matters here rather than being scenery: it is what the parent's model
    addresses this delegate by, and `uq_agent_org_slug` is what makes it unique.
    """
    return _agent(ctx, name=name, slug=slug or slugify(name), status=AgentStatus.PUBLISHED.value)


def _agents(*agents: Any) -> AsyncMock:
    """`agent_repo.get`, answering from a fixed set."""
    rows = {agent.id: agent for agent in agents}

    async def get(_db_session, agent_id, *, organization_id):
        return rows.get(agent_id)

    return AsyncMock(side_effect=get)


def _versions(*versions: Any) -> AsyncMock:
    """`agent_repo.get_version`, answering from a fixed set."""
    rows = {version.id: version for version in versions}

    async def get_version(_db_session, version_id, *, organization_id):
        return rows.get(version_id)

    return AsyncMock(side_effect=get_version)


def _repos(monkeypatch, *, agents: AsyncMock | None = None, versions: AsyncMock | None = None):
    monkeypatch.setattr(agent_registry.agent_repo, "get", agents or _agents())
    monkeypatch.setattr(agent_registry.agent_repo, "get_version", versions or _versions())


async def _problems(
    ctx: AuthContext, spec: AgentSpec, *, agent_id: UUID | None = None, db: Any = None
) -> list[str]:
    """The problems publishing this spec would report."""
    with pytest.raises(BadRequestError) as refused:
        await AgentRegistryService(db or _db()).validate_spec(ctx, spec, agent_id=agent_id)
    assert refused.value.message == "This agent cannot be published yet"
    assert refused.value.details is not None
    problems: list[str] = refused.value.details["problems"]
    return problems


class TestTheDelegationScope:
    """`agents:delegate` is granted by default, and withdrawing it turns it off.

    The scope is not the gate on *who* may be delegated to - that is `agents:run`,
    per delegate, against the row. It answers the deployment-wide question a
    permission cannot: whether agents may call agents here at all.
    """

    async def test_delegating_is_allowed_without_anybody_granting_anything(self):
        await AgentRegistryService(_db()).validate_spec(_ctx(), _delegating({}))

    async def test_a_deployment_that_withdraws_the_scope_refuses_every_delegating_agent(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            agent_registry,
            "DEFAULT_GRANTED_SCOPES",
            DEFAULT_GRANTED_SCOPES - {DELEGATE_SCOPE},
        )

        problems = await _problems(_ctx(), _delegating({}))

        assert problems == [
            f"Capability '{DELEGATION_CAPABILITY_ID}' needs scopes not granted here: "
            f"{DELEGATE_SCOPE}"
        ]


class TestInlineSpecialists:
    """A specialist gets the parent's checks, and every refusal says which one.

    It is the tempting place to attach a collection, a key or a capability the
    publisher may not have, precisely because it does not look like an agent - and
    a Builder form with one input per specialist cannot point at the right one
    unless the problem names it.
    """

    @pytest.fixture
    def ungranted_capability(self):
        capability_id = "test_specialist_email"

        @register(
            id=capability_id,
            name="Send email",
            category="test",
            description="Sends mail nobody granted us the right to send",
            scopes=("email:send",),
            tools=(),
        )
        def _build(ctx):
            return None

        yield capability_id
        REGISTRY.pop(capability_id)

    async def test_a_specialist_cannot_reach_a_collection_its_publisher_cannot(self, monkeypatch):
        """The smuggling route this check exists for.

        Same wording as the parent's own collection check, for the same reason: a
        refusal that read differently would map the organization's private
        collections one guess at a time - and it would do it from a corner of the
        spec nobody reviews.
        """
        ctx = _ctx(OrgRoleName.MEMBER)
        collection_id = uuid4()
        monkeypatch.setattr(
            agent_registry.knowledge_base_repo,
            "get_by_id",
            AsyncMock(
                return_value=MagicMock(
                    organization_id=ctx.organization_id,
                    owner_user_id=uuid4(),
                    visibility=Visibility.PRIVATE.value,
                )
            ),
        )
        monkeypatch.setattr(
            "app.services.access.resource_grant_repo.get_level", AsyncMock(return_value=None)
        )

        problems = await _problems(
            ctx,
            _delegating({"inline": [_specialist(collection_ids=[str(collection_id)])]}),
        )

        assert problems == [f"Specialist 'summariser': Collection not found: {collection_id}"]

    async def test_a_specialist_cannot_lend_a_secret_its_publisher_cannot_read(self, monkeypatch):
        """The same route, one table over.

        The secret checks are the parent's four, run through the parent's helper -
        this proves a specialist reaches them at all, with the one of the four that
        is a leak rather than a misconfiguration.
        """
        ctx = _ctx(OrgRoleName.MEMBER)
        secret_id = uuid4()
        monkeypatch.setattr(
            agent_registry.organization_secret_repo,
            "get",
            AsyncMock(
                return_value=MagicMock(
                    organization_id=ctx.organization_id,
                    owner_user_id=uuid4(),
                    visibility=Visibility.PRIVATE.value,
                )
            ),
        )
        monkeypatch.setattr(
            "app.services.access.resource_grant_repo.get_level", AsyncMock(return_value=None)
        )

        problems = await _problems(
            ctx,
            _delegating(
                {
                    "inline": [
                        _specialist(
                            capabilities=[
                                {
                                    "id": "web_research",
                                    "config": {"provider": "tavily"},
                                    "secret_id": str(secret_id),
                                }
                            ]
                        )
                    ]
                }
            ),
        )

        assert problems == [
            "Specialist 'summariser': Capability 'web_research' points at a secret this "
            f"organization does not have: {secret_id}"
        ]

    async def test_a_specialist_cannot_bind_a_capability_the_deployment_has_not_granted(
        self, ungranted_capability
    ):
        problems = await _problems(
            _ctx(),
            _delegating({"inline": [_specialist(capabilities=[{"id": ungranted_capability}])]}),
        )

        assert problems == [
            f"Specialist 'summariser': Capability '{ungranted_capability}' needs scopes "
            "not granted here: email:send"
        ]

    async def test_a_specialist_binding_a_capability_that_does_not_exist_is_refused(self):
        problems = await _problems(
            _ctx(), _delegating({"inline": [_specialist(capabilities=[{"id": "no_such_thing"}])]})
        )

        assert problems == ["Specialist 'summariser': Unknown capability: no_such_thing"]

    async def test_a_specialist_whose_capability_config_does_not_parse_is_refused(self):
        problems = await _problems(
            _ctx(),
            _delegating(
                {
                    "inline": [
                        _specialist(
                            capabilities=[
                                {"id": "knowledge", "config": {"default_top_k": "several"}}
                            ]
                        )
                    ]
                }
            ),
        )

        assert problems == [
            "Specialist 'summariser': Capability 'knowledge': Invalid configuration for "
            "capability 'knowledge'"
        ]

    async def test_a_specialist_gating_a_tool_that_does_not_exist_is_refused(self):
        """The dangerous typo, in the corner of the spec nobody reads.

        A `tool_approval` key matching nothing is silence, not an error: the tool
        the author meant to gate runs unapproved inside a delegation and nobody
        is told.
        """
        problems = await _problems(
            _ctx(),
            _delegating(
                {
                    "inline": [
                        _specialist(
                            capabilities=[
                                {"id": "skills", "tool_approval": {"load_skil": "required"}}
                            ]
                        )
                    ]
                }
            ),
        )

        assert problems == [
            "Specialist 'summariser': Capability 'skills' has no tool named load_skil "
            "to set approval for"
        ]

    async def test_a_specialist_renaming_a_tool_onto_its_sibling_is_refused(self):
        problems = await _problems(
            _ctx(),
            _delegating(
                {
                    "inline": [
                        _specialist(
                            capabilities=[
                                {
                                    "id": "skills",
                                    "tool_overrides": {"load_skill": {"name": "list_skills"}},
                                }
                            ]
                        )
                    ]
                }
            ),
        )

        assert problems == [
            "Specialist 'summariser': Capability 'skills' would offer two tools called list_skills"
        ]

    async def test_a_specialist_naming_a_model_profile_that_is_gone_is_refused(self, monkeypatch):
        """A specialist may run on a model of its own, and that is a reference too.

        Only when it names one: a specialist that names none runs on the parent's
        profile, which publish has already checked.
        """
        monkeypatch.setattr(
            agent_registry.credential_repo, "get_profile", AsyncMock(return_value=None)
        )

        problems = await _problems(
            _ctx(),
            _delegating({"inline": [_specialist(model_profile_id=str(uuid4()))]}),
        )

        assert problems == [
            "The selected model profile no longer exists",
            "Specialist 'summariser': The selected model profile no longer exists",
        ]

    async def test_a_specialist_inside_a_switched_off_capability_is_not_checked(self):
        """A disabled capability is not built, so its specialists can never run.

        Refusing a publish over one would be refusing over configuration with no
        effect - and the binding has to be re-enabled through a draft, which is
        published, which validates.
        """
        spec = AgentSpec(
            name="Support",
            model_profile_id=uuid4(),
            capabilities=[
                {
                    "id": DELEGATION_CAPABILITY_ID,
                    "enabled": False,
                    "config": {"inline": [_specialist(capabilities=[{"id": "no_such_thing"}])]},
                }
            ],
        )

        await AgentRegistryService(_db()).validate_spec(_ctx(), spec)

    async def test_a_delegation_config_that_does_not_parse_is_reported_once(self):
        """The binding check has already said so; a second guess adds nothing."""
        spec = _delegating({"max_depth": 99})

        problems = await _problems(_ctx(), spec)

        assert problems == [
            f"Capability '{DELEGATION_CAPABILITY_ID}': Invalid configuration for capability "
            f"'{DELEGATION_CAPABILITY_ID}'"
        ]


class TestSharedCapabilities:
    async def test_sharing_a_capability_this_agent_is_not_bound_to_is_refused(self):
        """The parent cannot lend what it does not hold.

        Naming one it is not bound to shares nothing - it is a line that reads as
        a decision and has no effect, which is the failure nobody notices.
        """
        problems = await _problems(
            _ctx(), _delegating({"share_with_delegates": ["knowledge", "charts"]})
        )

        assert problems == [
            "Delegation shares capabilities this agent is not bound to: charts, knowledge. "
            "Bind them here first, or drop them from the list."
        ]

    async def test_sharing_a_capability_this_agent_has_switched_off_is_refused(self):
        """A binding that is off is not built, so there is nothing to hand over."""
        problems = await _problems(
            _ctx(),
            _delegating(
                {"share_with_delegates": ["clock"]},
                capabilities=[{"id": "clock", "enabled": False}],
            ),
        )

        assert problems == [
            "Delegation shares capabilities this agent is not bound to: clock. "
            "Bind them here first, or drop them from the list."
        ]


class TestDelegatePins:
    async def test_a_delegate_the_publisher_cannot_run_is_refused_as_a_missing_one(
        self, monkeypatch
    ):
        """Two refusals that have to read identically.

        A delegate runs inside this agent's run, for everyone who can run this
        agent, so pinning one lends it out - the publisher has to be able to run
        it themselves. If the refusal for "may not run this" differed from the one
        for "no such agent", the pair would enumerate the organization's private
        agents.
        """
        ctx = _ctx(OrgRoleName.MEMBER)
        forbidden = _published(ctx, "Researcher")
        forbidden.owner_user_id = uuid4()
        version = _version(forbidden.id)
        monkeypatch.setattr(
            "app.services.access.resource_grant_repo.get_level", AsyncMock(return_value=None)
        )

        _repos(monkeypatch, agents=_agents(forbidden), versions=_versions(version))
        refused = await _problems(ctx, _delegating({}, subagents=[_pin(forbidden.id, version.id)]))

        _repos(monkeypatch, agents=_agents(), versions=_versions(version))
        absent = await _problems(ctx, _delegating({}, subagents=[_pin(forbidden.id, version.id)]))

        assert refused == absent == [f"Agent not found: {forbidden.id}"]

    async def test_a_delegate_in_another_organization_is_not_found(self, monkeypatch):
        """The id exists; the lookup is org-scoped, and the refusal says nothing else."""
        ctx = _ctx()
        elsewhere = uuid4()
        _repos(monkeypatch)

        problems = await _problems(ctx, _delegating({}, subagents=[_pin(elsewhere, uuid4())]))

        assert problems == [f"Agent not found: {elsewhere}"]

    async def test_an_archived_delegate_is_refused(self, monkeypatch):
        """An archived agent refuses to run, so a pin to one is a run that fails.

        Named rather than reported as missing: the publisher can see this agent,
        so "not found" would send them looking for something that is in front of
        them - and the fix is to unarchive it, which they can do.
        """
        ctx = _ctx()
        retired = _agent(ctx, name="Researcher", status=AgentStatus.ARCHIVED.value)
        version = _version(retired.id)
        _repos(monkeypatch, agents=_agents(retired), versions=_versions(version))

        problems = await _problems(ctx, _delegating({}, subagents=[_pin(retired.id, version.id)]))

        assert problems == ["Agent 'Researcher' is archived, so nothing can delegate to it"]

    async def test_a_version_belonging_to_another_agent_is_refused(self, monkeypatch):
        """A cross-agent version id is a cross-tenant read wearing a valid UUID.

        The version exists and is in this organization, so an existence check
        alone would pin it - and the parent would then run a spec belonging to an
        agent nobody checked the publisher against.
        """
        ctx = _ctx()
        delegate = _published(ctx, "Researcher")
        somebody_else = _version(uuid4())
        _repos(monkeypatch, agents=_agents(delegate), versions=_versions(somebody_else))

        problems = await _problems(
            ctx, _delegating({}, subagents=[_pin(delegate.id, somebody_else.id)])
        )

        assert problems == [
            f"Agent 'Researcher' has no published version {somebody_else.id} to pin"
        ]

    async def test_a_pin_to_a_version_that_is_gone_is_refused(self, monkeypatch):
        ctx = _ctx()
        delegate = _published(ctx, "Researcher")
        deleted = uuid4()
        _repos(monkeypatch, agents=_agents(delegate), versions=_versions())

        problems = await _problems(ctx, _delegating({}, subagents=[_pin(delegate.id, deleted)]))

        assert problems == [f"Agent 'Researcher' has no published version {deleted} to pin"]

    async def test_delegates_named_without_the_capability_enabled_are_refused(self, monkeypatch):
        """Pins nothing reads.

        The capability is what turns a pin into a tool the model can call, so
        without it three carefully chosen delegates are configuration with no
        effect - and the person who chose them is the last who would notice.
        """
        ctx = _ctx()
        delegate = _published(ctx, "Researcher")
        version = _version(delegate.id)
        _repos(monkeypatch, agents=_agents(delegate), versions=_versions(version))

        problems = await _problems(
            ctx,
            _spec(model_profile_id=uuid4(), subagents=[_pin(delegate.id, version.id)]),
        )

        assert problems == [
            "This agent names delegates, but its delegation capability is not enabled - "
            "nothing would ever call them. Enable it, or remove them."
        ]


class TestNameCollisions:
    """Two delegates the model cannot tell apart.

    A delegate is addressed by one name, so two of them sharing it leaves the
    model no way to say which it meant. `AgentSpec` already refuses the same agent
    pinned twice, and `uq_agent_org_slug` refuses two agents one handle - so what
    is left, and what these cover, is an inline specialist whose `name` nothing
    constrains taking a handle that is already in use.
    """

    async def test_a_specialist_taking_a_delegates_handle_is_refused(self, monkeypatch):
        """The handle is the agent row's slug, not anything derived from a spec.

        This delegate was renamed after the pinned version was published, so its
        spec still says "Old Research Bot" while its row - and the delegation the
        model is handed - says `research-bot`. A check that slugified the spec name
        would compare against a handle nobody uses and let the clash through.
        """
        ctx = _ctx()
        delegate = _published(ctx, "Research Bot")
        version = _version(delegate.id, spec=_spec(name="Old Research Bot"))
        _repos(monkeypatch, agents=_agents(delegate), versions=_versions(version))

        problems = await _problems(
            ctx,
            _delegating(
                {"inline": [_specialist("research-bot")]},
                subagents=[_pin(delegate.id, version.id)],
            ),
        )

        assert problems == [
            "More than one delegate is called 'research-bot', so the model has no way "
            "to say which it means"
        ]

    async def test_two_specialists_called_the_same_thing_are_refused(self):
        """Nothing else refuses this.

        A specialist has no row, so no constraint holds its name unique - the
        parent's config is free to carry two, and the second would shadow the
        first with nothing said.
        """
        problems = await _problems(
            _ctx(),
            _delegating({"inline": [_specialist("summariser"), _specialist("summariser")]}),
        )

        assert problems == [
            "More than one delegate is called 'summariser', so the model has no way "
            "to say which it means"
        ]


class TestDelegationCycles:
    """A loop in the delegation graph, caught while somebody can still fix it.

    `max_depth` bounds how deep one delegation goes, not whether the graph loops,
    so a cycle is not a bounded waste - it is a run spending the parent's budget
    delegating to itself. The chain is named because "there is a cycle" does not
    say which pin to remove.
    """

    async def test_an_agent_that_delegates_to_itself_is_refused(self, monkeypatch):
        ctx = _ctx()
        itself = _published(ctx, "Support")
        version = _version(itself.id, spec=_spec(name="Support"))
        _repos(monkeypatch, agents=_agents(itself), versions=_versions(version))

        problems = await _problems(
            ctx,
            _delegating({}, subagents=[_pin(itself.id, version.id)]),
            agent_id=itself.id,
        )

        assert problems == ["Delegation comes back to where it started: Support -> Support"]

    async def test_a_chain_that_returns_to_the_agent_being_published_is_refused(self, monkeypatch):
        """`A -> B -> A`, which only this publish can see.

        The pin that closes the loop is the one being added, so B's stored version
        says nothing about it. That is why the walk is told whose spec it is
        checking.
        """
        ctx = _ctx()
        parent, delegate = _published(ctx, "Support"), _published(ctx, "Researcher")
        parent_version = _version(parent.id, spec=_spec(name="Support"))
        delegate_version = _version(
            delegate.id,
            spec=_spec(name="Researcher", subagents=[_pin(parent.id, parent_version.id)]),
        )
        _repos(
            monkeypatch,
            agents=_agents(parent, delegate),
            versions=_versions(parent_version, delegate_version),
        )

        problems = await _problems(
            ctx,
            _delegating({}, subagents=[_pin(delegate.id, delegate_version.id)]),
            agent_id=parent.id,
        )

        assert problems == [
            "Delegation comes back to where it started: Support -> Researcher -> Support"
        ]

    async def test_a_loop_below_this_agent_is_found_without_knowing_whose_spec_it_is(
        self, monkeypatch
    ):
        """The draft check has no publish to hang an identity on.

        It still walks what is stored, so `B -> C -> B` is refused as you type.
        Only a loop closing on *this* agent needs the publish to be seen, and
        publish is the last point at which it can be.
        """
        ctx = _ctx()
        b, c = _published(ctx, "B"), _published(ctx, "C")
        b_version = _version(b.id)
        c_version = _version(c.id, spec=_spec(name="C", subagents=[_pin(b.id, b_version.id)]))
        b_version.spec = _spec(name="B", subagents=[_pin(c.id, c_version.id)]).model_dump(
            mode="json"
        )
        _repos(monkeypatch, agents=_agents(b, c), versions=_versions(b_version, c_version))

        problems = await _problems(ctx, _delegating({}, subagents=[_pin(b.id, b_version.id)]))

        assert problems == ["Delegation comes back to where it started: Support -> B -> C -> B"]

    async def test_two_delegates_reaching_one_shared_specialist_is_not_a_cycle(self, monkeypatch):
        """A diamond is a graph, not a loop, and publishing it must stay possible."""
        ctx = _ctx()
        shared = _published(ctx, "Editor")
        shared_version = _version(shared.id, spec=_spec(name="Editor"))
        first, second = _published(ctx, "Researcher"), _published(ctx, "Writer")
        versions = [
            _version(
                agent.id,
                spec=_spec(name=agent.name, subagents=[_pin(shared.id, shared_version.id)]),
            )
            for agent in (first, second)
        ]
        _repos(
            monkeypatch,
            agents=_agents(first, second, shared),
            versions=_versions(*versions, shared_version),
        )

        await AgentRegistryService(_db()).validate_spec(
            ctx,
            _delegating(
                {}, subagents=[_pin(first.id, versions[0].id), _pin(second.id, versions[1].id)]
            ),
            agent_id=uuid4(),
        )

    async def test_a_stale_pin_inside_a_delegate_does_not_block_this_publish(self, monkeypatch):
        """A delegate's own broken pin fails a run of *that* delegate, loudly.

        Refusing here would block a parent on a problem only the delegate's author
        can fix, in a spec this publisher may not even be able to see.
        """
        ctx = _ctx()
        delegate = _published(ctx, "Researcher")
        version = _version(
            delegate.id, spec=_spec(name="Researcher", subagents=[_pin(uuid4(), uuid4())])
        )
        _repos(monkeypatch, agents=_agents(delegate), versions=_versions(version))

        await AgentRegistryService(_db()).validate_spec(
            ctx, _delegating({}, subagents=[_pin(delegate.id, version.id)]), agent_id=uuid4()
        )

    async def test_a_graph_too_large_to_check_is_refused_rather_than_half_checked(
        self, monkeypatch
    ):
        """The walk is bounded, and says so instead of vouching for what it skipped.

        Nothing is expanded twice, so a loop already in stored data terminates it;
        this bound is about cost, because the number of pins is not bounded by the
        spec and every one is a read inside publish's transaction.
        """
        monkeypatch.setattr(agent_registry, "_MAX_DELEGATION_NODES", 1)
        ctx = _ctx()
        first, second = _published(ctx, "Researcher"), _published(ctx, "Writer")
        versions = [_version(agent.id, spec=_spec(name=agent.name)) for agent in (first, second)]
        _repos(monkeypatch, agents=_agents(first, second), versions=_versions(*versions))

        problems = await _problems(
            ctx,
            _delegating(
                {}, subagents=[_pin(first.id, versions[0].id), _pin(second.id, versions[1].id)]
            ),
            agent_id=uuid4(),
        )

        assert problems == [
            "This agent reaches more than 1 pinned delegate versions, which is more than "
            "publish can check. Delegate to fewer agents."
        ]


class TestAnAgentThatDoesNotDelegate:
    async def test_a_spec_with_no_delegates_and_no_specialists_is_unchanged(self, monkeypatch):
        """The regression guard: nothing about delegation touches an agent without it.

        Both repositories are set to refuse, so a lookup that should not happen
        fails the test rather than passing quietly on a mock.
        """
        _repos(monkeypatch)

        await AgentRegistryService(_db()).validate_spec(
            _ctx(), _spec(model_profile_id=uuid4(), capabilities=[{"id": "clock"}])
        )

        assert agent_registry.agent_repo.get.await_count == 0
        assert agent_registry.agent_repo.get_version.await_count == 0

    async def test_a_delegating_agent_whose_every_reference_resolves_publishes(self, monkeypatch):
        """One spec exercising every accepting path: a specialist with a capability,
        a collection and its own model; a shared capability the parent holds; and a
        pin that resolves to a version of an agent the publisher may run."""
        ctx = _ctx()
        delegate = _published(ctx, "Researcher")
        version = _version(delegate.id, spec=_spec(name="Researcher"))
        _repos(monkeypatch, agents=_agents(delegate), versions=_versions(version))
        monkeypatch.setattr(
            agent_registry.knowledge_base_repo,
            "get_by_id",
            AsyncMock(return_value=MagicMock(organization_id=ctx.organization_id)),
        )

        await AgentRegistryService(_db()).validate_spec(
            ctx,
            _delegating(
                {
                    "inline": [
                        _specialist(
                            capabilities=[{"id": "knowledge"}],
                            collection_ids=[str(uuid4())],
                            model_profile_id=str(uuid4()),
                        )
                    ],
                    "share_with_delegates": ["knowledge"],
                },
                subagents=[_pin(delegate.id, version.id)],
                capabilities=[{"id": "knowledge"}],
            ),
            agent_id=uuid4(),
        )
