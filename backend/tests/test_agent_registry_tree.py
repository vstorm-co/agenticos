"""The delegation tree endpoint's walk - what one response may honestly say.

The map renders this tree for whoever opens an agent's page, so the walk is
access-checked against the *reader*, not the publisher: a pin to an agent the
caller may not see must be indistinguishable from a pin to one that does not
exist, or a parent's map becomes a probe over the organization's private
agents. And depth is the runtime's bound, not the roster's - the tree shows
what a run from this root can reach and marks the rest truncated, because
drawing levels that would never execute is the map lying about the product.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.capabilities import load_builtins
from app.agents.spec import AgentSpec
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.schemas.agent import DelegationTree
from app.services import agent_registry
from app.services.agent_registry import DELEGATION_CAPABILITY_ID, AgentRegistryService
from tests.test_agent_registry import _agent, _ctx, _db, _spec, _version
from tests.test_agent_registry_subagents import (
    _agents,
    _pin,
    _published,
    _repos,
    _specialist,
    _versions,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def builtins_loaded():
    load_builtins()


def _delegating_spec(
    *,
    name: str = "Support",
    subagents: list[dict[str, object]] | None = None,
    config: dict[str, object] | None = None,
    enabled: bool = True,
) -> AgentSpec:
    return AgentSpec(
        name=name,
        capabilities=[{"id": DELEGATION_CAPABILITY_ID, "config": config or {}, "enabled": enabled}],
        subagents=subagents or [],
    )


def _root(ctx: AuthContext, spec: AgentSpec):
    return _agent(ctx, name=spec.name, draft_spec=spec.model_dump(mode="json"))


async def _tree(ctx: AuthContext, root) -> DelegationTree:
    return await AgentRegistryService(_db()).delegation_tree(ctx, root.id)


class TestWhatResolves:
    async def test_a_pinned_delegates_own_delegates_render_beneath_it(self, monkeypatch):
        """Two hops in one response - the page-walk the endpoint replaces."""
        ctx = _ctx()
        grandchild = _published(ctx, "Editor")
        grandchild_version = _version(grandchild.id, spec=_spec(name="Editor"))
        child = _published(ctx, "Researcher")
        child_version = _version(
            child.id,
            number=2,
            spec=_delegating_spec(
                name="Researcher",
                subagents=[_pin(grandchild.id, grandchild_version.id)],
                config={"max_depth": 2},
            ),
        )
        child.current_version_id = child_version.id
        root = _root(
            ctx,
            _delegating_spec(subagents=[_pin(child.id, child_version.id)], config={"max_depth": 3}),
        )
        _repos(
            monkeypatch,
            agents=_agents(root, child, grandchild),
            versions=_versions(child_version, grandchild_version),
        )

        tree = await _tree(ctx, root)

        assert tree.max_depth == 3
        assert tree.max_fanout == 3
        assert not tree.truncated
        (node,) = tree.nodes
        assert node.key == f"delegate:{child.id}:0"
        assert node.status == "ok"
        assert node.name == "Researcher"
        assert node.pinned_version == 2
        assert not node.stale
        (leaf,) = node.children
        assert leaf.status == "ok"
        assert leaf.name == "Editor"
        assert leaf.children == []

    async def test_a_pin_behind_the_delegates_current_version_is_called_stale(self, monkeypatch):
        ctx = _ctx()
        child = _published(ctx, "Researcher")
        pinned = _version(child.id, number=1)
        child.current_version_id = uuid4()
        root = _root(ctx, _delegating_spec(subagents=[_pin(child.id, pinned.id)]))
        _repos(monkeypatch, agents=_agents(root, child), versions=_versions(pinned))

        tree = await _tree(ctx, root)

        assert tree.nodes[0].stale

    async def test_inline_specialists_render_at_their_level(self, monkeypatch):
        """A specialist has no page of its own; the tree is where it appears."""
        ctx = _ctx()
        child = _published(ctx, "Researcher")
        child_version = _version(
            child.id,
            spec=_delegating_spec(
                name="Researcher", config={"inline": [_specialist("editor")], "max_depth": 1}
            ),
        )
        child.current_version_id = child_version.id
        root = _root(
            ctx,
            _delegating_spec(
                subagents=[_pin(child.id, child_version.id)],
                config={"inline": [_specialist("summariser", preferred_mode="async")]},
                enabled=True,
            ),
        )
        _repos(monkeypatch, agents=_agents(root, child), versions=_versions(child_version))

        tree = await _tree(ctx, root)

        delegate, specialist = tree.nodes
        assert specialist.key == "specialist:0"
        assert specialist.kind == "specialist"
        assert specialist.name == "summariser"
        assert specialist.mode == "async"
        assert specialist.agent_id is None
        # max_depth 1 on the root: the child cannot delegate, so its own
        # specialist is behind the cap rather than drawn as reachable.
        assert delegate.children == []
        assert delegate.truncated

    async def test_a_diamond_reads_each_shared_row_once(self, monkeypatch):
        """Two parents pinning one delegate is one row read, not two."""
        ctx = _ctx()
        shared = _published(ctx, "Editor")
        shared_version = _version(shared.id, spec=_spec(name="Editor"))
        shared.current_version_id = shared_version.id
        first, second = _published(ctx, "Researcher"), _published(ctx, "Writer")
        versions = [
            _version(
                agent.id,
                spec=_delegating_spec(
                    name=agent.name,
                    subagents=[_pin(shared.id, shared_version.id)],
                    config={"max_depth": 1},
                ),
            )
            for agent in (first, second)
        ]
        root = _root(
            ctx,
            _delegating_spec(
                subagents=[_pin(first.id, versions[0].id), _pin(second.id, versions[1].id)],
                config={"max_depth": 2},
            ),
        )
        agents_mock = _agents(root, first, second, shared)
        _repos(monkeypatch, agents=agents_mock, versions=_versions(*versions, shared_version))

        tree = await _tree(ctx, root)

        assert [node.children[0].name for node in tree.nodes] == ["Editor", "Editor"]
        shared_reads = [call for call in agents_mock.await_args_list if call.args[1] == shared.id]
        assert len(shared_reads) == 1


class TestWhatIsRefused:
    async def test_a_delegate_the_caller_may_not_see_is_restricted_like_a_missing_one(
        self, monkeypatch
    ):
        """The no-probing rule, applied to the reader rather than the publisher.

        A member reading a shared parent's map must not learn the name - or the
        subtree - of a private delegate pinned into it, and must not be able to
        tell that pin from one pointing at nothing.
        """
        ctx = _ctx(OrgRoleName.MEMBER)
        forbidden = _published(ctx, "Secret Ops")
        forbidden.owner_user_id = uuid4()
        version = _version(forbidden.id)
        root = _root(ctx, _delegating_spec(subagents=[_pin(forbidden.id, version.id)]))
        monkeypatch.setattr(
            "app.services.access.resource_grant_repo.get_level", AsyncMock(return_value=None)
        )
        _repos(monkeypatch, agents=_agents(root, forbidden), versions=_versions(version))
        (refused,) = (await _tree(ctx, root)).nodes

        _repos(monkeypatch, agents=_agents(root), versions=_versions(version))
        (absent,) = (await _tree(ctx, root)).nodes

        assert refused == absent
        assert refused.status == "restricted"
        assert refused.name is None
        assert refused.children == []
        assert refused.agent_id == forbidden.id

    async def test_a_root_the_caller_may_not_see_is_not_found(self, monkeypatch):
        """Tenant isolation starts at the root: another org's id answers 404."""
        ctx = _ctx()
        _repos(monkeypatch)

        with pytest.raises(NotFoundError):
            await AgentRegistryService(_db()).delegation_tree(ctx, uuid4())

    async def test_a_pin_that_returns_to_its_own_branch_is_a_cycle_not_a_hang(self, monkeypatch):
        ctx = _ctx()
        child = _published(ctx, "Researcher")
        root = _root(ctx, _spec())
        root_version = _version(root.id, spec=_delegating_spec(name="Support"))
        child_version = _version(
            child.id,
            spec=_delegating_spec(
                name="Researcher",
                subagents=[_pin(root.id, root_version.id)],
                config={"max_depth": 3},
            ),
        )
        child.current_version_id = child_version.id
        root.draft_spec = _delegating_spec(
            subagents=[_pin(child.id, child_version.id)], config={"max_depth": 3}
        ).model_dump(mode="json")
        _repos(
            monkeypatch,
            agents=_agents(root, child),
            versions=_versions(root_version, child_version),
        )

        tree = await _tree(ctx, root)

        (node,) = tree.nodes
        (loop,) = node.children
        assert loop.status == "cycle"
        assert loop.name == "Support"
        assert loop.children == []

    async def test_a_pin_whose_version_is_gone_is_named_but_not_walked(self, monkeypatch):
        ctx = _ctx()
        child = _published(ctx, "Researcher")
        root = _root(ctx, _delegating_spec(subagents=[_pin(child.id, uuid4())]))
        _repos(monkeypatch, agents=_agents(root, child), versions=_versions())

        (node,) = (await _tree(ctx, root)).nodes

        assert node.status == "unpinned"
        assert node.name == "Researcher"
        assert node.pinned_version is None
        assert node.children == []


class TestWhereItStops:
    async def test_a_delegates_own_lower_depth_wins_over_what_the_branch_has_left(
        self, monkeypatch
    ):
        """`min(inherited, own)` - a caller cannot buy a delegate more nesting."""
        ctx = _ctx()
        grandchild = _published(ctx, "Editor")
        grandchild_version = _version(
            grandchild.id,
            spec=_delegating_spec(
                name="Editor", subagents=[_pin(uuid4(), uuid4())], config={"max_depth": 3}
            ),
        )
        grandchild.current_version_id = grandchild_version.id
        child = _published(ctx, "Researcher")
        child_version = _version(
            child.id,
            spec=_delegating_spec(
                name="Researcher",
                subagents=[_pin(grandchild.id, grandchild_version.id)],
                config={"max_depth": 1},
            ),
        )
        child.current_version_id = child_version.id
        root = _root(
            ctx,
            _delegating_spec(subagents=[_pin(child.id, child_version.id)], config={"max_depth": 3}),
        )
        _repos(
            monkeypatch,
            agents=_agents(root, child, grandchild),
            versions=_versions(child_version, grandchild_version),
        )

        tree = await _tree(ctx, root)

        (node,) = tree.nodes
        # The branch had 2 levels left but Researcher's own policy allows 1, so
        # its roster renders and Editor's does not.
        (leaf,) = node.children
        assert leaf.name == "Editor"
        assert leaf.truncated
        assert leaf.children == []

    async def test_a_delegate_with_delegation_switched_off_is_truncated_not_expanded(
        self, monkeypatch
    ):
        """A roster behind a disabled binding never runs, so it is not drawn."""
        ctx = _ctx()
        child = _published(ctx, "Researcher")
        child_version = _version(
            child.id,
            spec=_delegating_spec(
                name="Researcher", subagents=[_pin(uuid4(), uuid4())], enabled=False
            ),
        )
        child.current_version_id = child_version.id
        root = _root(
            ctx,
            _delegating_spec(subagents=[_pin(child.id, child_version.id)], config={"max_depth": 3}),
        )
        _repos(monkeypatch, agents=_agents(root, child), versions=_versions(child_version))

        (node,) = (await _tree(ctx, root)).nodes

        assert node.truncated
        assert node.children == []

    async def test_a_delegate_whose_policy_does_not_parse_delegates_nothing_here(self, monkeypatch):
        """The parse failure is publish validation's report; the tree just stops."""
        ctx = _ctx()
        child = _published(ctx, "Researcher")
        broken = _delegating_spec(name="Researcher", subagents=[_pin(uuid4(), uuid4())])
        payload = broken.model_dump(mode="json")
        payload["capabilities"][0]["config"] = {"max_depth": 99}
        child_version = _version(child.id)
        child_version.spec = payload
        child.current_version_id = child_version.id
        root = _root(
            ctx,
            _delegating_spec(subagents=[_pin(child.id, child_version.id)], config={"max_depth": 3}),
        )
        _repos(monkeypatch, agents=_agents(root, child), versions=_versions(child_version))

        (node,) = (await _tree(ctx, root)).nodes

        assert node.status == "ok"
        assert node.truncated
        assert node.children == []

    async def test_a_root_that_cannot_delegate_still_shows_its_roster_unexpanded(self, monkeypatch):
        """The Builder draws the pins either way; the tree says they cannot run."""
        ctx = _ctx()
        child = _published(ctx, "Researcher")
        child_version = _version(
            child.id,
            spec=_delegating_spec(name="Researcher", subagents=[_pin(uuid4(), uuid4())]),
        )
        child.current_version_id = child_version.id
        root = _root(
            ctx,
            _delegating_spec(subagents=[_pin(child.id, child_version.id)], enabled=False),
        )
        _repos(monkeypatch, agents=_agents(root, child), versions=_versions(child_version))

        tree = await _tree(ctx, root)

        assert tree.max_depth == 1
        (node,) = tree.nodes
        assert node.status == "ok"
        assert node.truncated
        assert node.children == []

    async def test_the_walk_stops_at_its_node_bound_and_says_so(self, monkeypatch):
        """The read bound the cycle walk has, applied to the same graph."""
        monkeypatch.setattr(agent_registry, "_MAX_DELEGATION_NODES", 2)
        ctx = _ctx()
        delegates = [_published(ctx, f"D{index}") for index in range(3)]
        versions = [_version(delegate.id) for delegate in delegates]
        root = _root(
            ctx,
            _delegating_spec(
                subagents=[
                    _pin(delegate.id, version.id)
                    for delegate, version in zip(delegates, versions, strict=True)
                ]
            ),
        )
        _repos(monkeypatch, agents=_agents(root, *delegates), versions=_versions(*versions))

        tree = await _tree(ctx, root)

        assert tree.truncated
        assert len(tree.nodes) == 2
