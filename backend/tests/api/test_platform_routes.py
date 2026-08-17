"""Authorization at the route layer - the failure unit tests cannot see.

A service can be perfectly guarded and the platform still wide open. The gate is
one argument on a decorator, so a route that forgets `require(...)` or names
the wrong permission breaks no unit test anywhere: the service it calls is still
tested, still correct, and now reachable by anyone. Only a request through the
real app says otherwise, which is what everything here does.

The load-bearing test is :class:`TestEveryPlatformRouteIsGuarded`. The rest
prove that today's gates behave; that one proves the *next* route will have a
gate at all.

Callers are built from synthetic roles rather than the real ones - a role
holding exactly one permission, and a role holding every permission except one.
Driving the tests from `owner` and `viewer` would only show that some role
is refused somewhere; isolating a single permission is what makes "this route is
gated on *this* permission, and nothing else" an assertion rather than a hope.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute, RouteContext, iter_route_contexts
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import NotFoundError, RunExecutionError
from app.core.permissions import ROLE_PERMS, AuthContext, OrgRoleName, Perm, Scope
from app.db.models.resource_grant import Visibility
from app.main import app
from app.schemas.agent import ParkedCall
from app.services.agent_runner import RunSegment
from app.services.sharing import SharingService
from app.services.stats import StatsService
from app.services.transcript import RecordedToolCall

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid4()
_CALLER_ID = uuid4()
_SOME_ID = UUID("00000000-0000-0000-0000-0000000000ff")

# Path parameters are irrelevant to an authorization decision - the gate runs
# before the handler ever loads a row - so every one of them gets the same id.
_PATH_PARAM = re.compile(r"\{[^}]+\}")


def _url(path: str, query: str = "") -> str:
    return f"{settings.API_V1_STR}{_PATH_PARAM.sub(str(_SOME_ID), path)}{query}"


# -- callers ------------------------------------------------------------------


def only(permission: Perm) -> str:
    """Name of a role holding this permission and nothing else."""
    return f"test:only:{permission.value}"


def all_but(permission: Perm) -> str:
    """Name of a role holding every permission except this one."""
    return f"test:all-but:{permission.value}"


@pytest.fixture
def synthetic_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install the two isolating roles for every permission in the catalog.

    `AuthContext` reads its permissions out of `ROLE_PERMS` by name, so
    adding entries there is enough to describe a caller the product does not
    ship - which is the point: a real role holds too much to tell which of its
    permissions a route is actually checking.
    """
    for permission in Perm:
        monkeypatch.setitem(ROLE_PERMS, only(permission), {permission: Scope.ALL})
        monkeypatch.setitem(
            ROLE_PERMS,
            all_but(permission),
            {other: Scope.ALL for other in Perm if other is not permission},
        )


class _Absent:
    """A service stand-in whose every call reports its target as missing.

    Routes past the gate then answer 404, which makes "not 403" a statement
    about the gate rather than an accident of what a stub happened to return.
    A permitted caller reaching a handler is the whole assertion; what the
    handler would have found is another test's business.
    """

    def __getattr__(self, name: str) -> Any:
        # One route reaches through its service to the session underneath it
        # (`service.db`), so the stand-in has to answer as both.
        if name == "db":
            return self

        def absent(*args: Any, **kwargs: Any) -> Any:
            # Raising at call time rather than await time serves both shapes
            # of call site: an `await service.method()` never reaches the
            # await, and the one sync method in the surface
            # (`list_connectors`) refuses instead of handing FastAPI a
            # coroutine it cannot serialize.
            raise NotFoundError(message=f"nothing for {name}", details={})

        return absent


_SERVICE_DEPS = (
    deps.get_agent_registry_service,
    # The org-wide `GET /triggers` is the one gated trigger route, so past its gate
    # the stub answers 404 like the rest; the per-agent routes are ungated and never
    # reach this sweep.
    deps.get_agent_trigger_service,
    deps.get_agent_exposure_service,
    # Same shape again: a widget is one agent's public face, so who may publish
    # or take one down is `agents:publish` on that agent, resolved against its
    # grants rather than tested as a role.
    deps.get_agent_embed_service,
    deps.get_agent_runner_service,
    deps.get_approval_service,
    deps.get_skill_service,
    deps.get_context_service,
    deps.get_model_profile_service,
    deps.get_sharing_service,
    deps.get_mcp_connection_service,
    deps.get_secret_service,
    deps.get_knowledge_base_service,
    deps.get_collection_access_service,
    deps.get_sync_source_service,
    deps.get_rag_document_service,
    deps.get_stats_service,
)

Provider = Callable[[], object]


class ClientFactory(Protocol):
    def __call__(
        self, role: str, overrides: dict[Callable[..., object], Provider] | None = None
    ) -> AbstractAsyncContextManager[AsyncClient]: ...


@pytest.fixture
def as_role(mock_redis: MagicMock) -> Iterator[ClientFactory]:
    """Open a client whose caller holds exactly the permissions of `role`.

    Overriding `get_auth_context` replaces the token, the organization header
    and the membership lookup in one move: none of its sub-dependencies run, so
    the request exercises the gate and nothing else. `overrides` replaces
    individual dependencies for the tests that need a service to actually do
    something.
    """

    @asynccontextmanager
    async def open_client(
        role: str, overrides: dict[Callable[..., object], Provider] | None = None
    ) -> AsyncIterator[AsyncClient]:
        context = AuthContext(user_id=_CALLER_ID, organization_id=_ORGANIZATION_ID, role=str(role))
        absent = _Absent()
        app.dependency_overrides[deps.get_auth_context] = lambda: context
        app.dependency_overrides[deps.get_redis] = lambda: mock_redis
        app.dependency_overrides[deps.get_db_session] = lambda: absent
        for factory in _SERVICE_DEPS:
            app.dependency_overrides[factory] = lambda: absent
        app.dependency_overrides.update(overrides or {})
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client

    yield open_client
    app.dependency_overrides.clear()


# -- what each route is gated on ----------------------------------------------


@dataclass(frozen=True)
class Call:
    """One request, and the permission the platform intends to demand for it."""

    method: str
    path: str
    permission: Perm
    body: dict[str, Any] | None = None
    query: str = ""
    """Appended verbatim, so it carries its own `?` - there is no route here that
    needs one twice and no reason for this to guess."""

    def __str__(self) -> str:
        return f"{self.method} {self.path}"


_SPEC: dict[str, Any] = {"name": "Support"}

# The intended gate for every platform route, written by hand. This is the
# specification the tests below check the app against - so it must not be
# derived from the app, or a route wired to the wrong permission would simply
# rewrite its own expectation.
# Only routes that carry a role-level `require()` gate belong here.
#
# Deliberately absent: everything acting on a single agent or skill. Those
# delegate to a service that reads the role scope *and* the grants on that row,
# because a role-level gate would refuse a viewer holding an explicit edit grant
# before the grant was ever consulted. Their refusals are proven in
# tests/test_agent_registry.py, tests/test_skills.py and the grant flows in
# tests/integration/test_platform_flows.py.
CALLS: tuple[Call, ...] = (
    Call("GET", "/agents/capabilities", Perm.AGENTS_VIEW),
    Call("GET", "/agents/mcp-catalog", Perm.AGENTS_VIEW),
    Call("GET", "/agents", Perm.AGENTS_VIEW),
    Call("POST", "/agents", Perm.AGENTS_EDIT, body={"spec": _SPEC}),
    # Promoting a specialist creates an agent, so it is gated like `create` - and
    # this is where "a specialist created inside someone else's run does not become
    # their agent" is enforced: a caller without `agents:edit` is refused before the
    # conversion runs.
    Call(
        "POST",
        "/agents/promote",
        Perm.AGENTS_EDIT,
        body={
            "specialist": {
                "name": "invoice-parser",
                "description": "Pulls line items out of an invoice",
                "instructions": "Read the invoice and return its line items.",
            }
        },
    ),
    # The org-wide trigger listing: a collection route gated on seeing agents, the
    # same coarse door as `GET /agents`. Per-agent trigger routes stay ungated and
    # let the service resolve `agents:run` per row.
    Call("GET", "/triggers", Perm.AGENTS_VIEW),
    Call("GET", "/trigger-portals", Perm.AGENTS_VIEW),
    Call(
        "GET",
        "/trigger-portals/{portal_key}/targets",
        Perm.AGENTS_RUN,
        query="?connection_id=00000000-0000-0000-0000-000000000000",
    ),
    Call("GET", "/runs", Perm.RUNS_VIEW),
    Call(
        "GET",
        "/runs/export",
        Perm.RUNS_VIEW,
        query="?started_from=2020-01-01T00:00:00&started_to=2020-01-02T00:00:00",
    ),
    Call("GET", "/runs/{run_id}", Perm.RUNS_VIEW),
    Call("GET", "/runs/{run_id}/parked", Perm.APPROVALS_DECIDE),
    Call("POST", "/runs/{run_id}/resume", Perm.APPROVALS_DECIDE),
    Call("GET", "/approvals", Perm.APPROVALS_DECIDE),
    Call(
        "GET",
        "/approvals/export",
        Perm.APPROVALS_DECIDE,
        query="?created_from=2020-01-01T00:00:00&created_to=2020-01-02T00:00:00",
    ),
    Call("POST", "/approvals/{approval_id}", Perm.APPROVALS_DECIDE, body={"approved": True}),
    Call("GET", "/spend", Perm.RUNS_VIEW),
    Call(
        "GET",
        "/spend/export",
        Perm.RUNS_VIEW,
        query="?from=2020-01-01T00:00:00&to=2020-01-02T00:00:00",
    ),
    Call("GET", "/skills", Perm.SKILLS_VIEW),
    Call(
        "POST",
        "/skills",
        Perm.SKILLS_EDIT,
        body={"name": "refunds", "description": "How refunds work"},
    ),
    Call("GET", "/context", Perm.CONTEXT_VIEW),
    Call(
        "POST",
        "/context",
        Perm.CONTEXT_EDIT,
        body={"name": "glossary", "description": "What the words mean"},
    ),
    # Which providers exist and what shape of credential each takes is read by
    # the Builder's model picker, so it is gated on seeing agents rather than on
    # managing connections. Knowing Bedrock wants a key pair is not a secret.
    Call("GET", "/providers/catalog", Perm.AGENTS_VIEW),
    # Which models a provider offers, for the field where one is typed. Gated
    # on seeing agents like the catalog beside it: the answer is a public list
    # for OpenRouter and a list of model names for everyone else.
    Call("GET", "/providers/{provider}/models", Perm.AGENTS_VIEW),
    Call("GET", "/providers/model-profiles", Perm.AGENTS_VIEW),
    Call(
        "POST",
        "/providers/model-profiles",
        Perm.CONNECTIONS_MANAGE,
        # A model names the vault secret it is keyed by; there is no second key
        # store to leave it out and fall back on.
        body={
            "label": "GPT-4.1",
            "provider": "openai",
            "model": "gpt-4.1",
            "secret_id": "00000000-0000-0000-0000-000000000001",
        },
    ),
    Call("DELETE", "/providers/model-profiles/{profile_id}", Perm.CONNECTIONS_MANAGE),
    Call("GET", "/audit", Perm.AUDIT_READ),
    # The organization's MCP servers, per-resource routes included. That is the
    # same rule the agent routes follow, not an exception to it: a role gate is
    # wrong where a resource grant could widen the answer, and a connection has
    # no grants and nobody to share it with. `mcp:manage` is the whole
    # decision - the permission the catalog names for MCP servers, which used
    # to be advertised in the matrix and checked nowhere.
    Call("GET", "/mcp-connections", Perm.MCP_MANAGE),
    Call(
        # Declared above `/{connection_id}`, which would otherwise read the
        # literal segment as a malformed UUID and answer 422 before the gate.
        "POST",
        "/mcp-connections/oauth/start",
        Perm.MCP_MANAGE,
        body={"name": "github", "url": "https://mcp.example.com/mcp"},
    ),
    Call(
        "POST",
        "/mcp-connections",
        Perm.MCP_MANAGE,
        body={"name": "github", "url": "https://mcp.example.com/mcp"},
    ),
    Call(
        "PATCH",
        "/mcp-connections/{connection_id}",
        Perm.MCP_MANAGE,
        body={"is_enabled": False},
    ),
    Call("DELETE", "/mcp-connections/{connection_id}", Perm.MCP_MANAGE),
    Call("POST", "/mcp-connections/{connection_id}/test", Perm.MCP_MANAGE),
    # Knowledge bases: the collection routes carry the role gate; every
    # per-resource route hands the decision to the service, which resolves the
    # caller's scope and grants against the row - `readable_kb`/`writable_kb`.
    Call("GET", "/kb", Perm.COLLECTIONS_VIEW),
    Call("POST", "/kb", Perm.COLLECTIONS_EDIT, body={"name": "Docs", "scope": "org"}),
    # Org-level sync integrations hold encrypted credentials, so the whole
    # surface is `connections:manage` - the permission, not a role-name list,
    # which is what this router used to check.
    Call("GET", "/org/integrations", Perm.CONNECTIONS_MANAGE),
    Call("GET", "/org/integrations/connectors", Perm.CONNECTIONS_MANAGE),
    Call(
        "POST",
        "/org/integrations",
        Perm.CONNECTIONS_MANAGE,
        body={"name": "Drive", "connector_type": "gdrive", "config": {"folder_id": "abc"}},
    ),
    Call("DELETE", "/org/integrations/{source_id}", Perm.CONNECTIONS_MANAGE),
    Call("POST", "/org/integrations/{source_id}/trigger", Perm.CONNECTIONS_MANAGE),
    Call("GET", "/org/integrations/{source_id}/logs", Perm.CONNECTIONS_MANAGE),
    # The organization's secrets. Same permission as the provider keys, for the
    # A secret is a shared resource now: it has an owner, a visibility and
    # grants, so the *collection* routes carry a role gate and the per-row ones
    # (PATCH, DELETE) hand the decision to the service - a gate there would
    # refuse a member holding an explicit grant before `resolve_access` could
    # widen their access.
    Call("GET", "/secrets/kinds", Perm.SECRETS_VIEW),
    Call("GET", "/secrets/purposes", Perm.SECRETS_VIEW),
    Call("GET", "/secrets", Perm.SECRETS_VIEW),
    Call(
        "POST",
        "/secrets",
        Perm.SECRETS_EDIT,
        body={
            "name": "Weather API",
            "value": {"kind": "api_key", "api_key": "not-a-real-key"},
        },
    ),
    # Where sandboxes run, split across two gates. The reads carry
    # `connections:view` - a session list, an activity log and a host's ceilings
    # are what an operator watches when an agent keeps hitting a memory limit, and
    # that authority reaches no credential. The writes stay `connections:manage`,
    # the same permission the vault carries, because registering a host decides
    # which one an agent's shell runs on and attaches the secret that starts
    # containers there. Every route including the per-resource ones: a connection
    # has no grants, so a gate here cannot refuse somebody a grant would have
    # admitted.
    Call("GET", "/sandbox-connections", Perm.CONNECTIONS_VIEW),
    Call(
        "POST",
        "/sandbox-connections",
        Perm.CONNECTIONS_MANAGE,
        body={"name": "Local Docker", "kind": "docker", "base_url": "http://sandboxd:8080"},
    ),
    # Asking what this deployment can already see, and testing an address before a
    # row exists for it, are the same authority as registering one: both reach a
    # host, and the second unseals a credential to do it. `manage`, not `view`.
    Call("GET", "/sandbox-connections/local", Perm.CONNECTIONS_MANAGE),
    # The runtime catalog contacts nothing and names what this deployment's images
    # are built from - a read the connection form needs before an operator can
    # even see which runtimes a host allows, so it rides on `connections:view`.
    Call("GET", "/sandbox-connections/runtimes", Perm.CONNECTIONS_VIEW),
    Call("POST", "/sandbox-connections/local/credential", Perm.CONNECTIONS_MANAGE),
    Call(
        "POST",
        "/sandbox-connections/probe",
        Perm.CONNECTIONS_MANAGE,
        body={"base_url": "http://sandboxd:8080"},
    ),
    Call("PATCH", "/sandbox-connections/{connection_id}", Perm.CONNECTIONS_MANAGE, body={}),
    Call("DELETE", "/sandbox-connections/{connection_id}", Perm.CONNECTIONS_MANAGE),
    Call("GET", "/sandbox-connections/{connection_id}/policy", Perm.CONNECTIONS_VIEW),
    Call("GET", "/sandbox-connections/{connection_id}/sessions", Perm.CONNECTIONS_VIEW),
    Call(
        "GET",
        "/sandbox-connections/{connection_id}/sessions/{session_id}/events",
        Perm.CONNECTIONS_VIEW,
    ),
    # `raw` is the download and the image preview. Ungated for the same reason as
    # the rest of the workspace routes - the service scopes it, and a download must
    # not be the way around that.
    # The workspaces themselves carry no gate, and that is the change rather than
    # an omission: `connections:manage` widens the listing to the organization, and
    # a member sees the workspaces they are part of. A gate refused them outright,
    # which made a listing of their *own* files an operator screen.
    # `tests/test_sandbox_workspace.py::TestWorkspacesAreScopedToTheirReader` is
    # where the narrowing and the refusals are proven.
    # What an agent proposed changing about a skill. Reading one is reading a
    # candidate version of the organization's own instructions, so whoever may
    # read it is exactly whoever may accept it.
    Call("GET", "/skill-changes", Perm.SKILLS_EDIT),
    Call("GET", "/skill-changes/{proposal_id}", Perm.SKILLS_EDIT),
    Call("POST", "/skill-changes/{proposal_id}/apply", Perm.SKILLS_EDIT),
    Call("POST", "/skill-changes/{proposal_id}/discard", Perm.SKILLS_EDIT),
)

WRITE_CALLS: tuple[Call, ...] = tuple(call for call in CALLS if call.method != "GET")


class TestEachRouteDemandsItsOwnPermission:
    """The gate is exactly the permission the platform says it is.

    Two directions, because each catches a different mistake: refusing a caller
    who holds everything else catches a missing gate, and admitting a caller who
    holds only the one permission catches a gate wired to the wrong one - or to
    more permissions than the route needs.
    """

    @pytest.mark.parametrize("call", CALLS, ids=str)
    @pytest.mark.usefixtures("synthetic_roles")
    async def test_a_caller_missing_only_that_permission_is_refused(
        self, call: Call, as_role: ClientFactory
    ) -> None:
        async with as_role(all_but(call.permission)) as client:
            response = await client.request(
                call.method, _url(call.path, call.query), json=call.body
            )

        assert response.status_code == 403, (
            f"{call} admitted a caller holding every permission except {call.permission.value}"
        )

    @pytest.mark.parametrize("call", CALLS, ids=str)
    @pytest.mark.usefixtures("synthetic_roles")
    async def test_a_caller_holding_only_that_permission_gets_through(
        self, call: Call, as_role: ClientFactory
    ) -> None:
        """Past the gate the services are stubbed, so anything but 403 is a pass.

        422 is excluded as well: a request the app rejects as malformed never
        reached the gate, and would make this test pass for the wrong reason.
        """
        async with as_role(only(call.permission)) as client:
            response = await client.request(
                call.method, _url(call.path, call.query), json=call.body
            )

        assert response.status_code not in (403, 422), (
            f"{call} refused a caller holding {call.permission.value}"
        )


class TestViewersCannotWrite:
    @pytest.mark.parametrize("call", WRITE_CALLS, ids=str)
    async def test_a_viewer_is_refused(self, call: Call, as_role: ClientFactory) -> None:
        """A real role, not a synthetic one: this is the shipped configuration.

        Viewer is the role handed to auditors, contractors and anyone parked in
        an organization while their access is decided. Every mutation on the
        platform must be closed to it.
        """
        async with as_role(OrgRoleName.VIEWER) as client:
            response = await client.request(
                call.method, _url(call.path, call.query), json=call.body
            )

        assert response.status_code == 403


# The sandbox-connections reads an operator was written for, and the writes that
# stay closed to them. Real roles, not synthetic ones - this is the shipped
# configuration the issue is about, so a regression in `ROLE_PERMS` fails here
# rather than only in the synthetic-role gate sweep above.
_OPERATOR_MAY_READ: tuple[Call, ...] = (
    Call("GET", "/sandbox-connections", Perm.CONNECTIONS_VIEW),
    Call("GET", "/sandbox-connections/runtimes", Perm.CONNECTIONS_VIEW),
    Call("GET", "/sandbox-connections/{connection_id}/policy", Perm.CONNECTIONS_VIEW),
    Call("GET", "/sandbox-connections/{connection_id}/sessions", Perm.CONNECTIONS_VIEW),
    Call(
        "GET",
        "/sandbox-connections/{connection_id}/sessions/{session_id}/events",
        Perm.CONNECTIONS_VIEW,
    ),
)

_OPERATOR_MAY_NOT_WRITE: tuple[Call, ...] = (
    Call(
        "POST",
        "/sandbox-connections",
        Perm.CONNECTIONS_MANAGE,
        body={"name": "Local Docker", "kind": "docker", "base_url": "http://sandboxd:8080"},
    ),
    Call("PATCH", "/sandbox-connections/{connection_id}", Perm.CONNECTIONS_MANAGE, body={}),
    Call("DELETE", "/sandbox-connections/{connection_id}", Perm.CONNECTIONS_MANAGE),
    Call("POST", "/sandbox-connections/local/credential", Perm.CONNECTIONS_MANAGE),
    Call(
        "POST",
        "/sandbox-connections/probe",
        Perm.CONNECTIONS_MANAGE,
        body={"base_url": "http://sandboxd:8080"},
    ),
    # Reading what this deployment can already see unseals its own service token,
    # so it is a manage authority despite being a GET.
    Call("GET", "/sandbox-connections/local", Perm.CONNECTIONS_MANAGE),
)


class TestOperatorCanWatchSandboxesButNotManageThem:
    """The split, at the route layer and in the shipped `operator` role.

    An operator holds `connections:view` and not `connections:manage`, so the
    session list, the activity log and a host's ceilings answer while every route
    that points a host somewhere or unseals its credential refuses - which is the
    whole reason the permission was split rather than granted whole.
    """

    @pytest.mark.parametrize("call", _OPERATOR_MAY_READ, ids=str)
    async def test_an_operator_reaches_the_read(self, call: Call, as_role: ClientFactory) -> None:
        """Past the gate the service is stubbed, so anything but 403/422 is a pass."""
        async with as_role(OrgRoleName.OPERATOR) as client:
            response = await client.request(
                call.method, _url(call.path, call.query), json=call.body
            )

        assert response.status_code not in (403, 422), (
            f"{call} refused an operator holding connections:view"
        )

    @pytest.mark.parametrize("call", _OPERATOR_MAY_NOT_WRITE, ids=str)
    async def test_an_operator_is_refused_the_write(
        self, call: Call, as_role: ClientFactory
    ) -> None:
        async with as_role(OrgRoleName.OPERATOR) as client:
            response = await client.request(
                call.method, _url(call.path, call.query), json=call.body
            )

        assert response.status_code == 403, (
            f"{call} admitted an operator holding only connections:view"
        )


class TestBuilderStillReachesEverySandboxRoute:
    """The split must not narrow a role that managed connections before it.

    Builder held `connections:manage` and reached every sandbox route; giving it
    `connections:view` alongside keeps the reads it used to get through the one
    permission, and it must lose none of the writes either.
    """

    @pytest.mark.parametrize("call", _OPERATOR_MAY_READ + _OPERATOR_MAY_NOT_WRITE, ids=str)
    async def test_a_builder_reaches_it(self, call: Call, as_role: ClientFactory) -> None:
        async with as_role(OrgRoleName.BUILDER) as client:
            response = await client.request(
                call.method, _url(call.path, call.query), json=call.body
            )

        assert response.status_code not in (403, 422), (
            f"{call} refused a builder after the connections split"
        )


class TestPermissionIntrospectionIsOpenToEveryMember:
    """The UI cannot render a permissions matrix it is not allowed to read.

    Both endpoints describe the platform's rules rather than the organization's
    data, so gating them would only break the screen that explains to a member
    why they cannot do something.
    """

    @pytest.mark.parametrize("role", list(OrgRoleName), ids=lambda role: role.value)
    async def test_every_role_can_read_its_own_permissions(
        self, role: OrgRoleName, as_role: ClientFactory
    ) -> None:
        async with as_role(role) as client:
            response = await client.get(f"{settings.API_V1_STR}/me/permissions")

        assert response.status_code == 200
        assert response.json()["role"] == role.value

    @pytest.mark.parametrize("role", list(OrgRoleName), ids=lambda role: role.value)
    async def test_every_role_can_read_the_role_catalog(
        self, role: OrgRoleName, as_role: ClientFactory
    ) -> None:
        async with as_role(role) as client:
            response = await client.get(f"{settings.API_V1_STR}/roles/catalog")

        assert response.status_code == 200
        assert {entry["name"] for entry in response.json()["roles"]} >= {
            member.value for member in OrgRoleName
        }


# -- the guard ----------------------------------------------------------------

# Path prefixes owned by the platform layer. Everything the generated template
# brought with it authenticates differently and is not this file's business.
_PLATFORM_PREFIXES = (
    "/agents",
    "/runs",
    "/approvals",
    "/spend",
    # The dashboard's aggregates. Without the prefixes here the sweep would
    # pass over them silently - the worst kind of pass, since these routes
    # carry no `require()` at all and depend entirely on the service deciding
    # per scope. `/ratings` does not collide with the app-admin
    # `/admin/ratings`, whose tail starts with `/admin`.
    "/stats",
    "/ratings",
    "/skills",
    # Context files, shaped exactly like skills: the collection routes gate on
    # context:view/edit, the per-file routes resolve grants in the service.
    "/context",
    "/providers",
    "/audit",
    # The organization's MCP servers. `/me/mcp-connections` is a different
    # surface with a different owner and does not match this prefix, which is
    # the distinction this file is here to keep honest.
    "/mcp-connections",
    "/secrets",
    # Knowledge bases moved into the platform layer when their access rules
    # did: the service resolves scope and grants per row, so this sweep is
    # what notices the next /kb route that resolves neither.
    "/kb",
    "/org/integrations",
    # Where sandboxes run, what is running on them, and the files agents kept.
    # Every one of these is an operator surface holding a credential or another
    # tenant's work; without the prefixes here the sweep passed over them and the
    # claim that it proves their gates was simply untrue.
    "/sandbox-connections",
    "/sandbox-workspaces",
    "/skill-changes",
    # The org-wide trigger listing, gated on `agents:view` like its siblings
    # `GET /agents` and `GET /runs`, with the service still resolving scope and
    # grants per agent behind the gate. Without the prefix the sweep would pass
    # over `GET /triggers` and its "gated or resource-aware" claim would not
    # actually cover it. (Per-agent triggers live under `/agents`.)
    "/triggers",
    # The trigger-portals catalog, gated on `agents:view` like `/mcp-catalog` -
    # a distinct path, not a `/triggers` prefix, so it needs its own entry.
    "/trigger-portals",
)


def _is_platform(tail: str) -> bool:
    """Whether a path belongs to the platform layer rather than the template."""
    return tail.startswith(_PLATFORM_PREFIXES)


def _api_routes() -> Iterator[RouteContext]:
    """Every route the app serves, each with its fully-prefixed path.

    **Not** `for route in app.routes if isinstance(route, APIRoute)`. FastAPI
    0.141 stopped flattening included routers into `app.routes`: what sits there
    now is one `_IncludedRouter` wrapper per `include_router` call, so that
    isinstance check matched *nothing* and every sweep in this file passed over
    zero routes while reporting success. The failure was loud only because
    `test_the_permission_table_has_no_stale_entries` compares in the other
    direction and said all 38 gated routes had vanished.

    `iter_route_contexts` is the public replacement. A `RouteContext` carries the
    final `path` (prefixes applied, which is what these tests compare against)
    and `original_route`, which is the `APIRoute` whose dependency tree the
    permission sweeps read.
    """
    for context in iter_route_contexts(app.routes):
        if isinstance(context.original_route, APIRoute):
            yield context


def _platform_routes() -> list[tuple[str, RouteContext]]:
    """Every (method, route) pair the platform layer serves."""
    found = []
    for route in _api_routes():
        tail = route.path.removeprefix(settings.API_V1_STR)
        if not _is_platform(tail):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            found.append((method, route))
    return found


def _cell_values(call: Any) -> Iterator[Any]:
    for cell in getattr(call, "__closure__", None) or ():
        try:
            yield cell.cell_contents
        except ValueError:  # pragma: no cover - an empty cell cannot hold perms
            continue


def _required_permissions(route: RouteContext) -> frozenset[Perm]:
    """The permissions this route's dependency tree actually demands.

    Read out of the closure `require()` builds rather than off the source: a
    dependency that is declared but never wired in - the exact mistake this file
    exists to catch - is invisible to anything that reads the decorator.
    """
    required: set[Perm] = set()
    pending = list(route.original_route.dependant.dependencies)
    while pending:
        dependant = pending.pop()
        pending.extend(dependant.dependencies)
        for value in _cell_values(dependant.call):
            if isinstance(value, tuple) and value and all(isinstance(x, Perm) for x in value):
                required.update(value)
    return frozenset(required)


# Services whose read path calls `resolve_access`, and which therefore decide
# per row rather than per role. A route that depends on one of these is
# authorized even without a `require()` gate - and *must* be, for anything
# acting on a single resource.
RESOURCE_AWARE_SERVICES = (
    deps.get_sharing_service,
    deps.get_agent_registry_service,
    # Every exposure route acts on one agent, and the service resolves access to
    # it before touching a binding - so where an agent is available is decided
    # by the same grants that decide whether it can be published at all.
    deps.get_agent_exposure_service,
    # Triggers follow the exposures' shape exactly: every route acts on one agent,
    # and scheduling it to run itself is `agents:run` on that agent, resolved
    # against its grants - so a viewer with an explicit run grant is not refused
    # before the service can widen their access.
    deps.get_agent_trigger_service,
    # Environments follow the exposures' shape exactly: every route acts on one
    # agent, and which version answers under which name is `agents:publish` on
    # that agent, resolved against its grants.
    deps.get_agent_environment_service,
    # A secret is a shared resource: who may edit or delete one is its grants'
    # answer, resolved inside the service exactly as it is for an agent.
    deps.get_secret_service,
    # Same shape again: a widget is one agent's public face, so who may publish
    # or take one down is `agents:publish` on that agent, resolved against its
    # grants rather than tested as a role.
    deps.get_agent_embed_service,
    deps.get_agent_runner_service,
    deps.get_skill_service,
    # A context file is a shared resource shaped like a skill: who may read, edit
    # or delete one is its grants' answer, resolved inside the service. Every
    # per-file route (`GET/PATCH/DELETE /context/{id}`) depends on it.
    deps.get_context_service,
    # A knowledge base is a shared resource like the rest: reads resolve
    # through `readable_kb`, writes through `get_for_write`, both of which end
    # at `resolve_access` for org rows. Every per-KB route depends on it.
    deps.get_knowledge_base_service,
    # A workspace is not a shared resource with grants, but the decision is the
    # same shape: the service scopes every read to what the caller is part of -
    # their own user-scoped files, their own conversations, the shared workspace of
    # an agent they have talked to - and widens to the organization only for
    # `connections:manage`. A route gate would have refused a member outright,
    # which is what made a listing of *their own* files an operator screen.
    # `TestWorkspacesAreScopedToTheirReader` is where those refusals are proven.
    deps.get_sandbox_workspace_service,
    # The stats service decides per *scope parameter* rather than per grant on
    # a row - org-wide numbers demand runs:view, a caller's own rows demand
    # only that there is a caller. A route gate would refuse a member's
    # scope=own before the parameter was ever read. Same principle as the
    # rest of this list (the layer that can see the deciding fact decides),
    # new shape; `TestStatsScopeIsDecidedInTheService` proves the refusals.
    deps.get_stats_service,
)


def _delegates_to_a_resource_service(route: RouteContext) -> bool:
    """Whether the route hands the decision to a service that can see the grants."""
    pending = list(route.original_route.dependant.dependencies)
    while pending:
        dependant = pending.pop()
        pending.extend(dependant.dependencies)
        if dependant.call in RESOURCE_AWARE_SERVICES:
            return True
    return False


class TestEveryPlatformRouteIsGuarded:
    """The point of this file: the next ungated route fails here.

    Every other test in it names a route explicitly, which means none of them
    can notice a route that nobody remembered to name.
    """

    def test_no_platform_route_decides_nothing(self) -> None:
        """Authorization happens at the gate, or inside the sharing service.

        Every route acting on a *single* resource is the deliberate second
        case. A `require()` gate tests the *role*, so a viewer holding an
        explicit edit grant on one agent would be refused before
        `resolve_access` ever got to widen their access - contradicting the
        rule the access layer is built on. Those routes therefore carry no gate
        and let the service decide per row, which is proven by
        `TestSharingRoutesRefuseWithoutAGrant` below and by the grant flows in
        `tests/integration/test_platform_flows.py`.

        Routes acting on the *collection* - listing, creating, catalogs - keep
        their gate, because there is no resource whose grants could change the
        answer.
        """
        undecided = sorted(
            f"{method} {route.path}"
            for method, route in _platform_routes()
            if not _required_permissions(route) and not _delegates_to_a_resource_service(route)
        )
        assert not undecided, f"platform routes with no authorization at all: {undecided}"

    def test_every_gated_route_is_named_in_the_permission_table(self) -> None:
        """A new gated route must state which permission it is gated on.

        Failing here is not a bug report about the route - it is a missing entry
        in `CALLS`, without which nothing checks that its gate is the right one.
        """
        tested = {(call.method, f"{settings.API_V1_STR}{call.path}") for call in CALLS}
        untested = sorted(
            f"{method} {route.path}"
            for method, route in _platform_routes()
            if _required_permissions(route) and (method, route.path) not in tested
        )
        assert not untested, f"gated routes missing from CALLS: {untested}"

    def test_the_permission_table_has_no_stale_entries(self) -> None:
        """A route that was renamed or removed must not leave a test passing on nothing."""
        served = {(method, route.path) for method, route in _platform_routes()}
        stale = sorted(
            str(call)
            for call in CALLS
            if (call.method, f"{settings.API_V1_STR}{call.path}") not in served
        )
        assert not stale, f"CALLS names routes the app does not serve: {stale}"


# -- the sharing routes, whose gate lives one layer down ----------------------


@dataclass
class _SomeoneElsesResource:
    """A private row in the caller's organization, owned by somebody else."""

    organization_id: UUID
    id: UUID = field(default_factory=uuid4)
    owner_user_id: UUID = field(default_factory=uuid4)
    visibility: str = Visibility.PRIVATE.value


class _NoRows:
    def scalar_one_or_none(self) -> None:
        return None


class _NoGrantsSession:
    """Serves one resource and no grants - a member who was never shared with."""

    def __init__(self, resource: _SomeoneElsesResource) -> None:
        self._resource = resource

    async def get(self, model: Any, primary_key: Any) -> _SomeoneElsesResource:
        return self._resource

    async def execute(self, statement: Any) -> _NoRows:
        return _NoRows()


def _sharing_calls() -> list[tuple[str, str, dict[str, Any] | None]]:
    """Every sharing route the app serves, with a body it will accept."""
    bodies: dict[str, dict[str, Any] | None] = {
        "GET": None,
        "PUT": {"subject_user_id": str(uuid4()), "level": "edit"},
        "DELETE": None,
        "PATCH": {"visibility": "org"},
    }
    return [
        (method, route.path.removeprefix(settings.API_V1_STR), bodies[method])
        for method, route in _platform_routes()
        if "/sharing" in route.path
    ]


class TestSharingRoutesRefuseWithoutAGrant:
    """What the missing `require()` on those routes is replaced by.

    The caller here is a Member - a role that *holds* `collections:edit`, just
    not on this row. That is the case a role-level gate cannot express and the
    reason these routes delegate: the answer depends on the row, not the role.
    """

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        _sharing_calls(),
        ids=lambda value: value if isinstance(value, str) else "",
    )
    async def test_a_member_who_was_not_shared_with_is_refused(
        self, method: str, path: str, body: dict[str, Any] | None, as_role: ClientFactory
    ) -> None:
        session = _NoGrantsSession(_SomeoneElsesResource(organization_id=_ORGANIZATION_ID))
        overrides = {
            deps.get_db_session: lambda: session,
            deps.get_sharing_service: lambda: SharingService(session),
        }
        async with as_role(OrgRoleName.MEMBER, overrides) as client:
            response = await client.request(method, _url(path), json=body)

        # Reading reports the row as missing rather than forbidden, so ids
        # cannot be probed; changing it is an outright refusal.
        assert response.status_code == (404 if method == "GET" else 403)


class TestReadingWhatARunIsParkedOn:
    """`GET /runs/{run_id}/parked` hands a reloaded surface what the live frame had.

    The `tool_approval_required` frame exists only for whoever was watching the
    run park; reloading the conversation lost the panel and the only way to
    finish the run was the approvals queue on another page (#601). This is the
    same payload, read back off the rows.
    """

    async def test_the_parked_calls_come_back_with_the_approval_to_decide(
        self, as_role: ClientFactory, synthetic_roles: None
    ) -> None:
        run = MagicMock(id=uuid4())
        approval_id = uuid4()

        class _Parked:
            async def get_run(self, *args: Any, **kwargs: Any) -> Any:
                return run

            async def parked_calls(self, *args: Any, **kwargs: Any) -> list[ParkedCall]:
                return [
                    ParkedCall(
                        id=approval_id,
                        tool_call_id="call-1",
                        tool_name="send_email",
                        tool_args={"to": "ada@example.com"},
                    )
                ]

        overrides = {deps.get_agent_runner_service: lambda: _Parked()}
        async with as_role(only(Perm.APPROVALS_DECIDE), overrides) as client:
            response = await client.get(_url(f"/runs/{run.id}/parked"))

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": str(approval_id),
                "tool_call_id": "call-1",
                "tool_name": "send_email",
                "tool_args": {"to": "ada@example.com"},
            }
        ]

    async def test_a_run_in_another_organization_reads_as_absent(
        self, as_role: ClientFactory, synthetic_roles: None
    ) -> None:
        """The service resolves the run against the caller's organization before
        anything is read off it, so a foreign id answers the same 404 an unknown
        one does - the response cannot be used to learn that a run exists."""

        class _Elsewhere:
            async def get_run(self, *args: Any, **kwargs: Any) -> Any:
                raise NotFoundError(message="Run not found", details={})

        overrides = {deps.get_agent_runner_service: lambda: _Elsewhere()}
        async with as_role(only(Perm.APPROVALS_DECIDE), overrides) as client:
            response = await client.get(_url(f"/runs/{uuid4()}/parked"))

        assert response.status_code == 404


class TestResumeConveysAFailedContinuation:
    """A resume whose continuation raised is a 5xx that still names the run's status.

    The service records the run terminal and re-raises `RunExecutionError` carrying
    that status (agenticos#262). This proves the HTTP layer does not discard it: the
    failure is a 500 - not swallowed into a success - and the recorded status rides
    in the error envelope's `details`, which is the only place a web-chat surface can
    read a delegate's outcome when the resume did not return.
    """

    async def test_a_failed_resume_answers_5xx_with_the_status_in_the_body(
        self, as_role: ClientFactory, synthetic_roles: None
    ) -> None:
        run_id = uuid4()

        class _Failing:
            async def resume(self, *args: Any, **kwargs: Any) -> Any:
                raise RunExecutionError(
                    details={"run_id": str(run_id), "status": "failed"}
                ) from RuntimeError("the tool the approval unblocked then failed")

        overrides = {deps.get_agent_runner_service: lambda: _Failing()}
        async with as_role(only(Perm.APPROVALS_DECIDE), overrides) as client:
            response = await client.post(_url(f"/runs/{run_id}/resume"))

        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "RUN_EXECUTION_FAILED"
        assert body["error"]["details"] == {"run_id": str(run_id), "status": "failed"}


class TestResumeAnswersWithWhatTheContinuationDid:
    """The steps of the second half of a turn, which nothing else carries.

    A continuation executes inside this request rather than on the socket the
    conversation streams, so its tool calls reach no client unless this response
    holds them. Without them a surface could draw the approved call finishing and
    nothing after it - which is how approving a command showed no command running,
    and a second approval request arrived for a step that had never appeared.
    """

    async def test_the_continuations_tool_calls_are_in_the_response(
        self, as_role: ClientFactory, synthetic_roles: None
    ) -> None:
        run = MagicMock(
            id=uuid4(),
            status="awaiting_approval",
            cost_usd=Decimal("0.02"),
            input_tokens=13,
            output_tokens=7,
        )

        class _Resuming:
            async def resume(self, *args: Any, **kwargs: Any) -> Any:
                return RunSegment(
                    output="",
                    run=run,
                    settled={"call-0": "read 6 sheets"},
                    tool_calls=[
                        RecordedToolCall(
                            tool_call_id="call-1",
                            tool_name="execute",
                            args={"command": "python read.py"},
                            result="6 sheets",
                        ),
                        RecordedToolCall(
                            tool_call_id="call-2",
                            tool_name="execute",
                            args={"command": "python parse.py"},
                        ),
                    ],
                )

            async def parked_calls(self, *args: Any, **kwargs: Any) -> list[Any]:
                return []

        overrides = {deps.get_agent_runner_service: lambda: _Resuming()}
        async with as_role(only(Perm.APPROVALS_DECIDE), overrides) as client:
            response = await client.post(_url(f"/runs/{run.id}/resume"))

        assert response.status_code == 200
        steps = response.json()["steps"]
        assert [(step["tool_name"], step["args"], step["result"]) for step in steps] == [
            ("execute", {"command": "python read.py"}, "6 sheets"),
            # The call the run has parked on again: no result, because it has not
            # run - it is the one being decided.
            ("execute", {"command": "python parse.py"}, None),
        ]
        # And what the call the approver decided returned. It is not a step - the
        # caller drew that one before the run parked - so it arrives separately and
        # updates it, rather than putting the same command in the turn twice.
        assert response.json()["settled"] == [{"tool_call_id": "call-0", "result": "read 6 sheets"}]


# -- the stats routes, whose gate is the scope parameter ----------------------


_STATS_PATHS = ("/stats/usage", "/ratings/summary")


class TestStatsScopeIsDecidedInTheService:
    """The stats routes carry no `require()`; the service decides per scope.

    Same principle as the sharing rows - the layer that can see the deciding
    fact decides - but the fact is the `scope` parameter rather than a grant:
    org-wide numbers demand `runs:view`, a caller's own rows demand only that
    there is a caller. A route gate would refuse a member's `scope=own`
    before the parameter was ever read.
    """

    @pytest.fixture
    def stats_repos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every aggregate answers zero, so a 200 is a statement about the gate."""
        for name, value in (
            ("count_runs", 0),
            ("runs_by_day", []),
            ("runs_by_dimension", []),
            ("runs_by_agent", []),
            ("latency_percentiles_ms", (None, None)),
            ("sum_cost_window", Decimal(0)),
            ("cost_by_provider_window", []),
            ("count_distinct_users", 0),
            ("count_pending_approval_runs", 0),
            ("usage_by_user", []),
        ):
            monkeypatch.setattr(
                f"app.services.stats.agent_run_repo.{name}", AsyncMock(return_value=value)
            )
        monkeypatch.setattr(
            "app.services.stats.member_repo.count_for_org", AsyncMock(return_value=0)
        )
        # The window's cost is runs plus ingestion, so the second ledger is
        # stubbed alongside the first - otherwise a 500 from an unmocked query
        # would read as the gate refusing.
        monkeypatch.setattr(
            "app.services.stats.ingestion_spend_repo.sum_cost_window",
            AsyncMock(return_value=Decimal(0)),
        )
        monkeypatch.setattr(
            "app.services.stats.message_rating_repo.get_rating_summary_scoped",
            AsyncMock(
                return_value={
                    "total_ratings": 0,
                    "like_count": 0,
                    "dislike_count": 0,
                    "average_rating": 0.0,
                    "with_comments": 0,
                    "ratings_by_day": [],
                }
            ),
        )

    @staticmethod
    def _service() -> dict[Callable[..., object], Provider]:
        return {deps.get_stats_service: lambda: StatsService(MagicMock())}

    @pytest.mark.parametrize("path", _STATS_PATHS)
    async def test_org_scope_without_runs_view_is_refused(
        self, synthetic_roles: None, stats_repos: None, as_role: ClientFactory, path: str
    ) -> None:
        async with as_role(all_but(Perm.RUNS_VIEW), self._service()) as client:
            response = await client.get(_url(path, "?scope=org"))

        assert response.status_code == 403

    @pytest.mark.parametrize("path", _STATS_PATHS)
    async def test_org_scope_with_runs_view_is_answered(
        self, synthetic_roles: None, stats_repos: None, as_role: ClientFactory, path: str
    ) -> None:
        async with as_role(only(Perm.RUNS_VIEW), self._service()) as client:
            response = await client.get(_url(path, "?scope=org"))

        assert response.status_code == 200

    @pytest.mark.parametrize("path", _STATS_PATHS)
    async def test_a_member_is_refused_org_scope_but_answered_own(
        self, stats_repos: None, as_role: ClientFactory, path: str
    ) -> None:
        """The pair that a route-level gate cannot express."""
        async with as_role(OrgRoleName.MEMBER, self._service()) as client:
            refused = await client.get(_url(path, "?scope=org"))
            answered = await client.get(_url(path, "?scope=own"))

        assert refused.status_code == 403
        assert answered.status_code == 200

    @pytest.mark.parametrize("path", _STATS_PATHS)
    async def test_a_viewer_gets_their_own_rows_not_a_refusal(
        self, stats_repos: None, as_role: ClientFactory, path: str
    ) -> None:
        """Zero rows is the honest answer for a viewer; 403 would be a lie."""
        async with as_role(OrgRoleName.VIEWER, self._service()) as client:
            response = await client.get(_url(path, "?scope=own"))

        assert response.status_code == 200

    async def test_naming_the_organizations_people_is_refused_without_runs_view(
        self, synthetic_roles: None, stats_repos: None, as_role: ClientFactory
    ) -> None:
        """group_by=user is the one shape that answers with names, not counts."""
        async with as_role(all_but(Perm.RUNS_VIEW), self._service()) as client:
            response = await client.get(_url("/stats/usage", "?scope=org&group_by=user"))

        assert response.status_code == 403

    async def test_a_member_may_still_ask_the_person_table_about_themselves(
        self, stats_repos: None, as_role: ClientFactory
    ) -> None:
        async with as_role(OrgRoleName.MEMBER, self._service()) as client:
            response = await client.get(_url("/stats/usage", "?scope=own&group_by=user"))

        assert response.status_code == 200


# -- the inverse guard, for routes that are deliberately open -----------------

# What `/public` will serve: an agent exposed to anonymous visitors. Nothing
# is mounted there yet - the surface arrives with the identity work that makes it
# defensible - and this table is empty on purpose rather than absent, so the
# first public route lands into a guard instead of beside one.
#
# Adding a route under `/public` means adding it here. That is the whole point:
# `TestEveryPlatformRouteIsGuarded` proves a route demands *something*, which a
# route that demands nothing by design would pass by accident. This one proves
# somebody wrote down that it is open, and where its refusals are tested.
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset()

_AUTHENTICATED_CALLER_DEPS = (
    deps.get_auth_context,
    deps.get_current_user,
    deps.get_active_organization,
    # The WebSocket pair. A browser cannot set headers on a handshake, so the
    # socket reads its token from a subprotocol and its organization from the
    # query string - a different mechanism, the same claim, and it has to count
    # as authentication or the sweep below would report `/ws/agent` as open.
    deps.get_current_user_ws,
    deps.get_active_organization_ws,
)


def _public_routes() -> list[tuple[str, RouteContext]]:
    found = []
    for route in _api_routes():
        if not route.path.removeprefix(settings.API_V1_STR).startswith("/public"):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            found.append((method, route))
    return found


def _depends_on_a_caller(route: RouteContext | APIWebSocketRoute) -> bool:
    original = getattr(route, "original_route", route)
    pending = list(original.dependant.dependencies)
    while pending:
        dependant = pending.pop()
        pending.extend(dependant.dependencies)
        if dependant.call in _AUTHENTICATED_CALLER_DEPS:
            return True
    return False


class TestLiteralPathsOutrankTheirParameters:
    """`/agents/capabilities` must not be read as an agent named "capabilities".

    Starlette matches in declaration order, so a literal segment that sits below
    an `{agent_id}` route is answered by that route instead - as a 422 about a
    malformed UUID, before any gate or handler runs. Nothing else in the suite
    would notice: the gate test only asks whether a request is refused, and a 422
    is not a 403.
    """

    @pytest.mark.parametrize("literal", ["capabilities", "mcp-catalog"])
    def test_the_catalogs_are_matched_before_the_agent_detail_route(self, literal: str) -> None:
        # Declaration order is what matters here, and `iter_route_contexts`
        # preserves it - which is the order Starlette matches in.
        paths = [
            route.path
            for route in _api_routes()
            if route.path.startswith(f"{settings.API_V1_STR}/agents")
        ]

        assert paths.index(f"{settings.API_V1_STR}/agents/{literal}") < paths.index(
            f"{settings.API_V1_STR}/agents/{{agent_id}}"
        )


V1 = settings.API_V1_STR

# Every route in the application that anybody can call without a session, and
# the reason it has to be one.
#
# `TestEveryPlatformRouteIsGuarded` asks whether a route decides *something*,
# which a route deciding nothing by design passes without a sound. `/public`
# has the table above for exactly that reason - and `/public` was the wrong
# boundary to draw it at: `GET /rag/status/stream` shipped with no
# authentication and no tenant in its payload, nowhere near that prefix, and
# nothing in this suite had an opinion. It answered 500 in production only
# because its own dependency was constructed wrong.
#
# So the table covers the whole app. Adding an unauthenticated route means adding
# it here, next to routes whose openness somebody argued for; a route that lands
# in the diff of this list is a route a reviewer will look at.
UNAUTHENTICATED_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        # Custom brand icons. The consumer is a CSS mask URL in the browser,
        # which cannot attach a bearer token; what they reveal - which marks
        # this deployment ships - is what any signed-in page renders anyway.
        ("GET", f"{V1}/catalog/icons"),
        ("GET", f"{V1}/catalog/icons/{{name}}"),
        # Liveness and readiness. Called by the load balancer, which has no
        # session, and they report nothing but whether this process can reach
        # Postgres and Redis.
        ("GET", f"{V1}/health"),
        ("GET", f"{V1}/health/live"),
        ("GET", f"{V1}/health/ready"),
        ("GET", f"{V1}/ready"),
        # Becoming authenticated. Each of these is the request a caller makes
        # *before* they have anything to authenticate with; `refresh` and
        # `logout` carry their own credential in an HttpOnly cookie.
        ("POST", f"{V1}/auth/login"),
        ("POST", f"{V1}/auth/register"),
        ("POST", f"{V1}/auth/refresh"),
        ("POST", f"{V1}/auth/logout"),
        ("POST", f"{V1}/auth/password-reset/request"),
        ("POST", f"{V1}/auth/password-reset/confirm"),
        ("POST", f"{V1}/auth/magic-link/request"),
        ("POST", f"{V1}/auth/magic-link/verify"),
        ("GET", f"{V1}/oauth/google/login"),
        ("GET", f"{V1}/oauth/google/callback"),
        # Redirect targets. The provider drives the browser back here with a
        # code, and it cannot be asked to carry our session while doing so; the
        # code itself is the credential.
        ("POST", f"{V1}/me/mcp-connections/oauth/callback"),
        # Bearer-token surfaces where the token is in the URL, not a header.
        # A share link is a capability: whoever holds the token is the audience,
        # which is the whole point of being able to send it to somebody.
        ("GET", f"{V1}/conversations/shared/{{token}}"),
        # Avatars, rendered by `<img src>` in contexts that have no session -
        # an invitation email, a public share. An id, and a picture the owner
        # uploaded to be seen.
        ("GET", f"{V1}/users/avatar/{{user_id}}"),
        # Deployment configuration rather than tenant data: which parsers this
        # build has, and which embedding models it can index with. The same
        # answer for every caller, so there is nothing here to scope - and
        # nothing to protect either.
        ("GET", f"{V1}/rag/supported-formats"),
        ("GET", f"{V1}/rag/embedding-models"),
        # Inbound webhooks. Slack and Telegram will not send our tokens; they
        # sign or secret their own requests, and each handler verifies that
        # itself against the bot named in the path. A session dependency here
        # would simply mean the integration never worked.
        ("POST", f"{V1}/slack/{{bot_id}}/events"),
        ("POST", f"{V1}/telegram/{{bot_id}}/webhook"),
        # Mattermost is the same arrangement with a weaker primitive: it does
        # not sign bodies, so the handler compares the shared token the
        # integration was created with, and refuses when none is configured.
        ("POST", f"{V1}/mattermost/{{bot_id}}/webhook"),
        # An event trigger's inbound webhook. Same arrangement as Slack: GitHub
        # and the email relay sign the body with the trigger's own secret, and the
        # service verifies that HMAC against the trigger named in the path. A
        # session here would mean the integration could never deliver.
        ("POST", f"{V1}/webhooks/triggers/{{source}}/{{trigger_id}}"),
        # The public face of an embedded agent. There is no session to have:
        # these are reached from a stranger's browser on somebody else's site.
        # What authorises them is the widget's key plus the `Origin` the browser
        # reports, checked against the allow-list on the row - and, in `jwt`
        # mode, a token the customer's own backend signed. `widget.js` carries
        # no secret and decides nothing; the socket is where admission happens.
        ("GET", f"{V1}/embed/{{public_key}}/config"),
        ("GET", f"{V1}/embed/{{public_key}}/widget.js"),
        ("WEBSOCKET", f"{V1}/embed/{{public_key}}/ws"),
        # The hosted page (#517), and the difference is worth writing down
        # rather than filing under the three above: it has **no origin check**.
        # An allow-list is a rule about other people's sites, and this page is
        # ours, so what protects a hosted link in `public` mode is the key's
        # unguessability, the embed's rate bucket, its budget and its pause
        # switch - nothing else. `jwt` mode cannot be hosted at all, refused by
        # the service and by a CHECK constraint, because the token would have to
        # travel in the URL. `/logo` serves one image the operator already
        # uploaded through the authenticated avatar paths, which stay
        # authenticated; hosting adds a way to read that one file and no way to
        # write any.
        ("GET", f"{V1}/embed/{{public_key}}/hosted"),
        ("GET", f"{V1}/embed/{{public_key}}/logo"),
        # The one open route on this surface that *writes*, and the only one whose
        # exemption is about more than a read. It exists because a page whose
        # operator ticked "a visitor may attach a file" has to accept bytes from
        # somebody with no account; what bounds it is the page's own switch, a cap
        # of this surface's own, the MIME allowlist every upload goes through, and
        # a per-visitor-per-page limit in the shared Redis. The row is attributed
        # to whoever published the page, because `chat_files.user_id` is NOT NULL
        # and a stranger has nobody to be.
        ("POST", f"{V1}/embed/{{public_key}}/files"),
    }
)


def _routes_with_dependencies() -> list[tuple[str, str]]:
    """Every (method, path) the app serves, WebSocket handshakes included.

    Sockets are swept too because they are the easiest place to leave a hole:
    their authentication is hand-rolled - a token in a subprotocol, an
    organization in the query string - and none of it is visible in the
    decorator.
    """
    found = []
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        if isinstance(route, APIRoute):
            methods = sorted(context.methods - {"HEAD", "OPTIONS"})
            path = context.path
        elif isinstance(route, APIWebSocketRoute):
            methods = ["WEBSOCKET"]
            # FastAPI 0.141 leaves `RouteContext.path` empty for a websocket, and
            # `route.path` is the one the router was declared with - no include
            # prefix. `url_path_for` is the public way to the served path; the
            # placeholders go back in because these are compared as templates.
            path = _websocket_path(route)
        else:  # openapi.json, /docs, /redoc - served by Starlette, not us
            continue
        found.extend((method, path) for method in methods)
    return found


def _websocket_path(route: APIWebSocketRoute) -> str:
    """The full path a websocket route is served at, placeholders intact."""
    # `_PATH_PARAM` matches include their braces, so the placeholder is the match
    # itself and the keyword is that match without them.
    params = {
        placeholder.strip("{}"): placeholder for placeholder in _PATH_PARAM.findall(route.path)
    }
    return str(app.url_path_for(route.name, **params))


def _unauthenticated_routes() -> list[tuple[str, str]]:
    by_path: dict[str, Any] = {}
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        if isinstance(route, APIRoute):
            by_path[context.path] = context
        elif isinstance(route, APIWebSocketRoute):
            by_path[_websocket_path(route)] = route
    return [
        (method, path)
        for method, path in _routes_with_dependencies()
        if not _depends_on_a_caller(by_path[path])
    ]


class TestEveryUnauthenticatedRouteIsDeliberate:
    """A route that needs no session must have been chosen, not forgotten.

    The list it checks against is the argument; this class only makes forgetting
    to write one impossible.
    """

    def test_every_open_route_is_declared(self) -> None:
        undeclared = sorted(
            f"{method} {path}"
            for method, path in _unauthenticated_routes()
            if (method, path) not in UNAUTHENTICATED_ROUTES
        )
        assert not undeclared, (
            "routes reachable without a session that nothing declares as open: "
            f"{undeclared} - either add the caller dependency or add it to "
            "UNAUTHENTICATED_ROUTES with the reason it has to be open"
        )

    def test_the_declaration_has_no_stale_entries(self) -> None:
        """A route that gained a gate must lose its exemption, or the next one inherits it."""
        open_now = set(_unauthenticated_routes())
        stale = sorted(
            f"{method} {path}"
            for method, path in UNAUTHENTICATED_ROUTES
            if (method, path) not in open_now
        )
        assert not stale, f"UNAUTHENTICATED_ROUTES names routes that are not open: {stale}"

    def test_the_sweep_can_tell_the_two_apart(self) -> None:
        """Without this the guard passes by answering "authenticated" to everything.

        `_depends_on_a_caller` walks a dependency tree; if it stopped finding
        anything, every route would look open and both tests above would fail
        loudly - but if it started finding something everywhere, they would both
        pass on an empty set. This is the direction that fails quietly.
        """
        open_now = set(_unauthenticated_routes())

        assert ("GET", f"{V1}/health") in open_now
        assert ("GET", f"{V1}/agents") not in open_now
        assert ("WEBSOCKET", f"{V1}/ws/agent") not in open_now


class TestEveryPublicRouteIsDeliberate:
    """A route nobody has to authenticate for must have been chosen, not left.

    The guarded-route test above asks whether a route decides *anything*. A
    public route decides nothing by design and would sail through it, which is
    exactly the shape of the mistake worth catching here: a handler mounted
    outside the platform prefixes, reachable by anyone, that nobody reviewed.
    """

    def test_every_public_route_is_declared(self) -> None:
        undeclared = sorted(
            f"{method} {route.path}"
            for method, route in _public_routes()
            if (method, route.path) not in PUBLIC_ROUTES
        )
        assert not undeclared, (
            f"routes served under /public that nothing declares as open: {undeclared}"
        )

    def test_the_declaration_has_no_stale_entries(self) -> None:
        served = {(method, route.path) for method, route in _public_routes()}
        stale = sorted(
            f"{method} {path}" for method, path in PUBLIC_ROUTES if (method, path) not in served
        )
        assert not stale, f"PUBLIC_ROUTES names routes the app does not serve: {stale}"

    def test_no_public_route_quietly_requires_a_session(self) -> None:
        """A public page that 401s for a visitor is not public, it is broken.

        Worth asserting rather than assuming: the dependency that authenticates a
        caller is inherited through `Auth`, so one wrong annotation on a schema
        or a service is enough to pull it in without the route ever mentioning it.
        """
        gated = sorted(
            f"{method} {route.path}"
            for method, route in _public_routes()
            if _depends_on_a_caller(route) or _required_permissions(route)
        )
        assert not gated, f"/public routes demanding an authenticated caller: {gated}"
