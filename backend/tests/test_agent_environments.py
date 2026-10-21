"""Tests for the environment service - which version answers under which name.

What is worth proving is what the service refuses. Promotion itself is a
one-field update; the value of the service is that an environment can never be
unpinned, never collide on a name, never point at another agent's version, and
that the default - the publish contract - cannot be renamed or removed here.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import (
    AlreadyExistsError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_environment import AgentEnvironmentConnection
from app.schemas.agent_environment import (
    EnvironmentConnectionWrite,
    EnvironmentCreate,
    EnvironmentUpdate,
)
from app.services.agent_environment import AgentEnvironmentService

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_CALLER = uuid.uuid4()

_REPO = "app.services.agent_environment.agent_environment_repo"
_EVALS = "app.services.agent_environment.eval_run_repo.count_live_in_environment"
_AGENTS = "app.services.agent_environment.agent_repo"
_AUDIT = "app.services.agent_environment.record_audit"


@pytest.fixture(autouse=True)
def _consent(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """No trigger runs as its creator unless a test says so."""
    withdraw = AsyncMock(return_value=0)
    monkeypatch.setattr(
        "app.services.agent_registry.agent_trigger_repo.withdraw_creator_consent", withdraw
    )
    return withdraw


@pytest.fixture(autouse=True)
def _no_suites(monkeypatch: pytest.MonkeyPatch) -> None:
    """No eval suite watches a promotion here; `integration/test_eval_suites` covers that."""
    monkeypatch.setattr(
        "app.services.eval_suite.EvalSuiteService.environment_promoted", AsyncMock()
    )
    monkeypatch.setattr("app.services.eval_suite.EvalSuiteService.environment_removed", AsyncMock())


@pytest.fixture(autouse=True)
def _no_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    """No environment here names a guard; `integration/test_promotion_gate` covers them."""
    monkeypatch.setattr(
        "app.services.agent_environment.promotion_gate_repo.guards_for", AsyncMock(return_value={})
    )
    monkeypatch.setattr(
        "app.services.agent_environment.promotion_gate_repo.guarding_through",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr("app.services.promotion_gate.PromotionGateService.enforce", AsyncMock())


def _ctx(role: str = OrgRoleName.OWNER) -> AuthContext:
    return AuthContext(user_id=_CALLER, organization_id=_ORG, role=role)


def _named(**attributes: object) -> MagicMock:
    mock = MagicMock(**{key: value for key, value in attributes.items() if key != "name"})
    if "name" in attributes:
        mock.name = attributes["name"]
    return mock


def _agent(*, current_version_id: uuid.UUID | None = None) -> MagicMock:
    return _named(
        id=uuid.uuid4(),
        name="Support",
        current_version_id=current_version_id or uuid.uuid4(),
    )


def _environment(*, agent_id: uuid.UUID, name: str = "dev", is_default: bool = False) -> MagicMock:
    return _named(
        id=uuid.uuid4(),
        agent_id=agent_id,
        name=name,
        version_id=uuid.uuid4(),
        is_default=is_default,
        logfire_token_secret_id=None,
        service_name=None,
    )


def _version(*, agent_id: uuid.UUID, number: int = 3) -> MagicMock:
    return MagicMock(id=uuid.uuid4(), agent_id=agent_id, version=number)


def _service(agent: MagicMock) -> AgentEnvironmentService:
    """A service whose agent lookup succeeds, so the tests can be about
    environments. The registry's own refusals are proven in
    `tests/test_agent_registry.py` against the real `resolve_access`."""
    service = AgentEnvironmentService(MagicMock())
    service.agents = MagicMock()
    service.agents.get = AsyncMock(return_value=agent)
    return service


class TestListing:
    async def test_a_listing_carries_the_version_number_the_history_names(self):
        """An id is not something a person can compare against the timeline."""
        agent = _agent()
        environment = _environment(agent_id=agent.id, name="production", is_default=True)
        version = _version(agent_id=agent.id, number=7)
        environment.version_id = version.id
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(
                f"{_AGENTS}.get_versions_by_ids",
                new=AsyncMock(return_value={version.id: version}),
            ),
            patch(f"{_AGENTS}.count_versions", new=AsyncMock(return_value=9)),
        ):
            environments.list_for_agent = AsyncMock(return_value=[environment])
            environments.list_connections = AsyncMock(return_value=[])
            items = await service.list_for_agent(_ctx(), agent.id)

        assert [(item.name, item.version, item.is_default) for item in items] == [
            ("production", 7, True)
        ]
        # Two publishes have happened since this one was promoted onto. Pinned on
        # purpose and forgotten look identical without the number.
        assert items[0].behind_by == 2

    async def test_a_version_deleted_mid_listing_renders_as_zero_not_a_crash(self):
        """The window between the two reads is not a state anyone can persist;
        taking the whole listing down for it would hide every other row."""
        agent = _agent()
        environment = _environment(agent_id=agent.id)
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(f"{_AGENTS}.get_versions_by_ids", new=AsyncMock(return_value={})),
            patch(f"{_AGENTS}.count_versions", new=AsyncMock(return_value=0)),
        ):
            environments.list_for_agent = AsyncMock(return_value=[environment])
            environments.list_connections = AsyncMock(return_value=[])
            items = await service.list_for_agent(_ctx(), agent.id)

        assert items[0].version == 0


class TestCreate:
    async def test_an_unpublished_agent_cannot_grow_environments(self):
        """There is no version to pin, so the name would answer with nothing."""
        agent = _agent()
        agent.current_version_id = None
        service = _service(agent)

        with pytest.raises(BadRequestError, match="Publish"):
            await service.create(_ctx(), agent.id, EnvironmentCreate(name="dev"))

    async def test_a_taken_name_is_refused_before_the_constraint_sees_it(self):
        agent = _agent()
        service = _service(agent)

        with patch(_REPO) as environments:
            environments.get_by_name = AsyncMock(return_value=_environment(agent_id=agent.id))

            with pytest.raises(AlreadyExistsError):
                await service.create(_ctx(), agent.id, EnvironmentCreate(name="dev"))

    async def test_no_version_named_means_the_default_environments_version(self):
        """The shorthand: a new environment starts where everyone already is."""
        agent = _agent()
        version = _version(agent_id=agent.id)
        agent.current_version_id = version.id
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(f"{_AGENTS}.get_version", new=AsyncMock(return_value=version)) as versions,
            patch(_AUDIT, new=AsyncMock()),
        ):
            environments.get_by_name = AsyncMock(return_value=None)
            environments.create = AsyncMock(return_value=_environment(agent_id=agent.id))
            await service.create(_ctx(), agent.id, EnvironmentCreate(name="dev"))

        assert versions.call_args.args[1] == version.id
        assert environments.create.call_args.kwargs["version_id"] == version.id

    async def test_another_agents_version_is_reported_as_missing(self):
        """A version id is data; the agent it belongs to is not negotiable."""
        agent = _agent()
        foreign = _version(agent_id=uuid.uuid4())
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(f"{_AGENTS}.get_version", new=AsyncMock(return_value=foreign)),
        ):
            environments.get_by_name = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError, match="Version"):
                await service.create(
                    _ctx(), agent.id, EnvironmentCreate(name="dev", version_id=foreign.id)
                )


class TestPromoteAndRename:
    async def test_promotion_repoints_and_audits_who_did_it(self):
        """ "Who put this version in front of users" is the first question after
        a bad release."""
        agent = _agent()
        environment = _environment(agent_id=agent.id, name="production", is_default=True)
        version = _version(agent_id=agent.id, number=12)
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(f"{_AGENTS}.get_version", new=AsyncMock(return_value=version)),
            patch(f"{_AGENTS}.update", new=AsyncMock()) as agents,
            patch(_AUDIT, new=AsyncMock()) as audit,
        ):
            environments.get = AsyncMock(return_value=environment)
            environments.update = AsyncMock(return_value=environment)
            await service.update(
                _ctx(), agent.id, environment.id, EnvironmentUpdate(version_id=version.id)
            )

        assert environments.update.call_args.kwargs["update_data"] == {"version_id": version.id}
        assert audit.call_args.kwargs["action"] == "agent.environment_promoted"
        assert audit.call_args.kwargs["details"]["version"] == 12
        # Promoting the default *is* the deploy, so the denormalized pointer
        # every surface naming no environment reads has to follow it. Publish
        # used to keep the two in step by moving both; a publish moves neither
        # now, so this is where they stay in step.
        assert agents.await_args.kwargs["update_data"] == {
            "current_version_id": environment.version_id
        }

    @pytest.mark.security
    @pytest.mark.parametrize("delegated", ["key", "impersonation"])
    async def test_a_publish_through_a_key_or_an_impersonator_keeps_nobody_s_consent(
        self, _consent: AsyncMock, delegated: str
    ):
        """Codex on #2062: the creator's own key kept their consent while it swapped
        the spec a routine runs as them."""
        from dataclasses import replace

        from app.services.agent_registry import AgentRegistryService

        ctx = _ctx()
        if delegated == "key":
            ctx = replace(ctx, api_key_id=uuid.uuid4())
        agent = _agent()
        with patch(
            "app.services.agent_registry.current_impersonator",
            return_value=uuid.uuid4() if delegated == "impersonation" else None,
        ):
            await AgentRegistryService(MagicMock()).withdraw_creator_consent(ctx, agent)

        assert _consent.await_args.kwargs == {"agent_id": agent.id, "kept_for": None}

    async def test_a_promotion_withdraws_other_peoples_run_as_me(self, _consent: AsyncMock):
        """Codex on #2062: a creator agreed to what the agent did then, not to a
        version somebody else put in front of their trigger."""
        agent = _agent()
        environment = _environment(agent_id=agent.id)
        version = _version(agent_id=agent.id, number=3)
        service = _service(agent)
        ctx = _ctx()
        _consent.return_value = 2

        with (
            patch(_REPO) as environments,
            patch(f"{_AGENTS}.get_version", new=AsyncMock(return_value=version)),
            patch(f"{_AGENTS}.update", new=AsyncMock()),
            patch(_AUDIT, new=AsyncMock()) as audit,
            patch("app.services.agent_registry.record_audit", new=AsyncMock()) as withdrawn,
        ):
            environments.get = AsyncMock(return_value=environment)
            environments.update = AsyncMock(return_value=environment)
            await service.update(
                ctx, agent.id, environment.id, EnvironmentUpdate(version_id=version.id)
            )

        assert _consent.await_args.kwargs == {"agent_id": agent.id, "kept_for": ctx.user_id}
        assert withdrawn.await_args.kwargs["action"] == "agent_trigger.creator_consent_withdrawn"
        assert withdrawn.await_args.kwargs["details"] == {"triggers": 2}
        audit.assert_awaited()

    async def test_switching_to_follows_latest_adopts_the_newest_version_now(self):
        """A mode that claims to follow and does not until something else happens is
        the half-true state the whole setting exists to remove."""
        agent = _agent()
        environment = _environment(agent_id=agent.id, name="dev")
        newest = _version(agent_id=agent.id, number=9)
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(f"{_AGENTS}.newest_version", new=AsyncMock(return_value=newest)),
            patch(_AUDIT, new=AsyncMock()),
        ):
            environments.get = AsyncMock(return_value=environment)
            environments.update = AsyncMock(return_value=environment)
            await service.update(
                _ctx(), agent.id, environment.id, EnvironmentUpdate(tracks_latest=True)
            )

        assert environments.update.call_args.kwargs["update_data"] == {
            "tracks_latest": True,
            "version_id": newest.id,
        }

    async def test_an_environment_already_on_the_newest_version_only_changes_its_mode(self):
        """Nothing to adopt: it is already there, and writing the version it already
        holds would audit a promotion that did not happen."""
        agent = _agent()
        environment = _environment(agent_id=agent.id, name="dev")
        newest = _version(agent_id=agent.id, number=9)
        newest.id = environment.version_id
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(f"{_AGENTS}.newest_version", new=AsyncMock(return_value=newest)),
            patch(f"{_AGENTS}.update", new=AsyncMock()) as agents,
            patch(_AUDIT, new=AsyncMock()),
        ):
            environments.get = AsyncMock(return_value=environment)
            environments.update = AsyncMock(return_value=environment)
            await service.update(
                _ctx(), agent.id, environment.id, EnvironmentUpdate(tracks_latest=True)
            )

        assert environments.update.call_args.kwargs["update_data"] == {"tracks_latest": True}
        agents.assert_not_awaited()

    async def test_an_agent_with_no_versions_at_all_only_changes_the_mode(self):
        """`current_version_id` is set and the newest read answers nothing - a version
        deleted out from under the pointer. Following nothing is still following."""
        agent = _agent()
        environment = _environment(agent_id=agent.id, name="dev")
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(f"{_AGENTS}.newest_version", new=AsyncMock(return_value=None)),
            patch(f"{_AGENTS}.update", new=AsyncMock()) as agents,
            patch(_AUDIT, new=AsyncMock()),
        ):
            environments.get = AsyncMock(return_value=environment)
            environments.update = AsyncMock(return_value=environment)
            await service.update(
                _ctx(), agent.id, environment.id, EnvironmentUpdate(tracks_latest=True)
            )

        assert environments.update.call_args.kwargs["update_data"] == {"tracks_latest": True}
        agents.assert_not_awaited()

    async def test_an_environment_cannot_be_unpinned(self):
        """`version_id: null` is not "track latest" - there is no such state."""
        agent = _agent()
        environment = _environment(agent_id=agent.id)
        service = _service(agent)

        with patch(_REPO) as environments:
            environments.get = AsyncMock(return_value=environment)

            with pytest.raises(BadRequestError, match="pinned"):
                await service.update(
                    _ctx(), agent.id, environment.id, EnvironmentUpdate(version_id=None)
                )

    async def test_the_default_keeps_its_name(self):
        """The default's name is part of the publish contract, not the caller's."""
        agent = _agent()
        environment = _environment(agent_id=agent.id, name="production", is_default=True)
        service = _service(agent)

        with patch(_REPO) as environments:
            environments.get = AsyncMock(return_value=environment)

            with pytest.raises(BadRequestError, match="default"):
                await service.update(
                    _ctx(), agent.id, environment.id, EnvironmentUpdate(name="prod-eu")
                )

    async def test_a_rename_onto_a_taken_name_is_refused(self):
        agent = _agent()
        environment = _environment(agent_id=agent.id, name="dev")
        service = _service(agent)

        with patch(_REPO) as environments:
            environments.get = AsyncMock(return_value=environment)
            environments.get_by_name = AsyncMock(
                return_value=_environment(agent_id=agent.id, name="staging")
            )

            with pytest.raises(AlreadyExistsError):
                await service.update(
                    _ctx(), agent.id, environment.id, EnvironmentUpdate(name="staging")
                )

    async def test_a_rename_is_audited_as_a_rename(self):
        agent = _agent()
        environment = _environment(agent_id=agent.id, name="dev")
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(_AUDIT, new=AsyncMock()) as audit,
        ):
            environments.get = AsyncMock(return_value=environment)
            environments.get_by_name = AsyncMock(return_value=None)
            environments.update = AsyncMock(return_value=environment)
            await service.update(
                _ctx(), agent.id, environment.id, EnvironmentUpdate(name="staging")
            )

        # Not "renamed": the same call also switches release mode now, and an
        # action that names one of the three things it can do is a label that
        # lies about the other two. The fields are in the details.
        assert audit.call_args.kwargs["action"] == "agent.environment_updated"
        assert audit.call_args.kwargs["details"]["fields"] == ["name"]

    async def test_an_update_that_names_nothing_is_refused(self):
        agent = _agent()
        environment = _environment(agent_id=agent.id)
        service = _service(agent)

        with patch(_REPO) as environments:
            environments.get = AsyncMock(return_value=environment)

            with pytest.raises(BadRequestError, match="Nothing to change"):
                await service.update(_ctx(), agent.id, environment.id, EnvironmentUpdate())

    async def test_another_agents_environment_is_reported_as_missing(self):
        """An environment id from a different agent must not act through this
        agent's routes - even inside one tenant."""
        agent = _agent()
        foreign = _environment(agent_id=uuid.uuid4())
        service = _service(agent)

        with patch(_REPO) as environments:
            environments.get = AsyncMock(return_value=foreign)

            with pytest.raises(NotFoundError, match="Environment"):
                await service.update(
                    _ctx(), agent.id, foreign.id, EnvironmentUpdate(name="staging")
                )


class TestObservabilityOverride:
    """An environment can aim its runs at their own Logfire project."""

    async def test_a_key_the_organization_does_not_hold_is_refused(self):
        agent = _agent()
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(
                f"{_AGENTS}.get_version", new=AsyncMock(return_value=_version(agent_id=agent.id))
            ),
            patch(
                "app.services.agent_environment.organization_secret_repo.get",
                new=AsyncMock(return_value=None),
            ),
        ):
            environments.get_by_name = AsyncMock(return_value=None)

            with pytest.raises(BadRequestError, match="vault"):
                await service.create(
                    _ctx(),
                    agent.id,
                    EnvironmentCreate(name="dev", logfire_token_secret_id=uuid.uuid4()),
                )

    async def test_a_key_for_something_else_is_refused_by_purpose(self):
        """A Tavily key behind a Logfire block traces into nothing, silently."""
        agent = _agent()
        environment = _environment(agent_id=agent.id)
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(
                "app.services.agent_environment.organization_secret_repo.get",
                new=AsyncMock(return_value=MagicMock(purpose="tavily")),
            ),
        ):
            environments.get = AsyncMock(return_value=environment)

            with pytest.raises(BadRequestError, match="not Logfire"):
                await service.update(
                    _ctx(),
                    agent.id,
                    environment.id,
                    EnvironmentUpdate(logfire_token_secret_id=uuid.uuid4()),
                )

    async def test_a_valid_key_and_service_name_travel_into_the_row(self):
        agent = _agent()
        secret_id = uuid.uuid4()
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(
                f"{_AGENTS}.get_version", new=AsyncMock(return_value=_version(agent_id=agent.id))
            ),
            patch(
                "app.services.agent_environment.organization_secret_repo.get",
                new=AsyncMock(return_value=MagicMock(purpose="logfire")),
            ),
            patch(_AUDIT, new=AsyncMock()),
        ):
            environments.get_by_name = AsyncMock(return_value=None)
            environments.create = AsyncMock(return_value=_environment(agent_id=agent.id))
            await service.create(
                _ctx(),
                agent.id,
                EnvironmentCreate(
                    name="client-prod",
                    logfire_token_secret_id=secret_id,
                    service_name="acme-support",
                ),
            )

        created = environments.create.call_args.kwargs
        assert created["logfire_token_secret_id"] == secret_id
        assert created["service_name"] == "acme-support"


_MCP = "app.services.agent_environment.mcp_connection_repo.get_org_scoped_by_ids"
_SECRETS = "app.services.agent_environment.organization_secret_repo.get"
_ACCESS = "app.services.agent_environment.resolve_access"


def _secret(*, name: str, kind: str = "api_key", purpose: str = "custom") -> MagicMock:
    return _named(id=uuid.uuid4(), name=name, kind=kind, purpose=purpose)


class TestConnectionOverrides:
    """An environment can answer a binding with a test system instead."""

    async def test_the_listing_carries_each_environments_overrides(self):
        agent = _agent()
        staging = _environment(agent_id=agent.id, name="staging")
        production_id, test_id = uuid.uuid4(), uuid.uuid4()
        override = AgentEnvironmentConnection(
            environment_id=staging.id,
            kind="mcp",
            production_id=production_id,
            test_connection_id=test_id,
        )
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(f"{_AGENTS}.get_versions_by_ids", new=AsyncMock(return_value={})),
            patch(f"{_AGENTS}.count_versions", new=AsyncMock(return_value=0)),
        ):
            environments.list_for_agent = AsyncMock(return_value=[staging])
            environments.list_connections = AsyncMock(return_value=[override])
            (item,) = await service.list_for_agent(_ctx(), agent.id)

        assert [(c.kind, c.production_id, c.test_id) for c in item.connections] == [
            ("mcp", production_id, test_id)
        ]

    async def test_a_deleted_test_side_lists_as_off_rather_than_vanishing(self):
        """Null is the binding switched off here; hiding the row would read as
        "production answers", which is exactly what does not happen."""
        override = AgentEnvironmentConnection(
            kind="secret", production_id=uuid.uuid4(), test_secret_id=None
        )

        assert override.test_id is None

    async def test_an_mcp_override_is_written_with_the_environment(self):
        agent = _agent()
        production, test = _named(id=uuid.uuid4()), _named(id=uuid.uuid4())
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(
                f"{_AGENTS}.get_version", new=AsyncMock(return_value=_version(agent_id=agent.id))
            ),
            patch(_MCP, new=AsyncMock(return_value={production.id: production, test.id: test})),
            patch(_AUDIT, new=AsyncMock()) as audit,
        ):
            environments.get_by_name = AsyncMock(return_value=None)
            environments.create = AsyncMock(return_value=_environment(agent_id=agent.id))
            environments.replace_connections = AsyncMock()
            await service.create(
                _ctx(),
                agent.id,
                EnvironmentCreate(
                    name="staging",
                    connections=[
                        EnvironmentConnectionWrite(
                            kind="mcp", production_id=production.id, test_id=test.id
                        )
                    ],
                ),
            )

        (row,) = environments.replace_connections.call_args.kwargs["connections"]
        assert (row.kind, row.production_id, row.test_connection_id, row.test_secret_id) == (
            "mcp",
            production.id,
            test.id,
            None,
        )
        assert audit.call_args.kwargs["details"]["connections"] == 1

    async def test_a_personal_or_foreign_connection_is_refused_on_either_side(self):
        """Both sides must be the organization's: a member's own connection behind
        an environment would answer for everybody who reaches it."""
        agent = _agent()
        environment = _environment(agent_id=agent.id)
        production = _named(id=uuid.uuid4())
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(_MCP, new=AsyncMock(return_value={production.id: production})),
        ):
            environments.get = AsyncMock(return_value=environment)

            with pytest.raises(BadRequestError, match="not shared with this organization"):
                await service.update(
                    _ctx(),
                    agent.id,
                    environment.id,
                    EnvironmentUpdate(
                        connections=[
                            EnvironmentConnectionWrite(
                                kind="mcp", production_id=production.id, test_id=uuid.uuid4()
                            )
                        ]
                    ),
                )

    async def test_two_overrides_of_one_binding_are_refused(self):
        agent = _agent()
        environment = _environment(agent_id=agent.id)
        production_id = uuid.uuid4()
        service = _service(agent)

        with patch(_REPO) as environments:
            environments.get = AsyncMock(return_value=environment)

            with pytest.raises(BadRequestError, match="one test replacement"):
                await service.update(
                    _ctx(),
                    agent.id,
                    environment.id,
                    EnvironmentUpdate(
                        connections=[
                            EnvironmentConnectionWrite(
                                kind="mcp", production_id=production_id, test_id=uuid.uuid4()
                            ),
                            EnvironmentConnectionWrite(
                                kind="mcp", production_id=production_id, test_id=uuid.uuid4()
                            ),
                        ]
                    ),
                )

    async def test_an_override_onto_itself_is_refused(self):
        agent = _agent()
        environment = _environment(agent_id=agent.id)
        same = uuid.uuid4()
        service = _service(agent)

        with patch(_REPO) as environments:
            environments.get = AsyncMock(return_value=environment)

            with pytest.raises(BadRequestError, match="different"):
                await service.update(
                    _ctx(),
                    agent.id,
                    environment.id,
                    EnvironmentUpdate(
                        connections=[
                            EnvironmentConnectionWrite(
                                kind="secret", production_id=same, test_id=same
                            )
                        ]
                    ),
                )

    @pytest.mark.security
    @pytest.mark.parametrize("missing", ["production", "test", "unreadable"])
    async def test_a_secret_the_caller_cannot_lend_reads_as_not_in_the_vault(self, missing):
        """Miss and refusal read alike, so the vault cannot be enumerated."""
        agent = _agent()
        environment = _environment(agent_id=agent.id)
        production, test = _secret(name="CRM"), _secret(name="CRM sandbox")
        found = {
            production.id: None if missing == "production" else production,
            test.id: None if missing == "test" else test,
        }
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(_MCP, new=AsyncMock(return_value={})),
            patch(_SECRETS, new=AsyncMock(side_effect=lambda _db, sid, **_: found[sid])),
            patch(_ACCESS, new=AsyncMock(return_value=missing != "unreadable")),
        ):
            environments.get = AsyncMock(return_value=environment)

            with pytest.raises(BadRequestError, match="vault"):
                await service.update(
                    _ctx(),
                    agent.id,
                    environment.id,
                    EnvironmentUpdate(
                        connections=[
                            EnvironmentConnectionWrite(
                                kind="secret", production_id=production.id, test_id=test.id
                            )
                        ]
                    ),
                )

    async def test_a_test_key_for_another_service_is_refused(self):
        """A Tavily key standing in for a CRM key fails hours later, far from here."""
        agent = _agent()
        environment = _environment(agent_id=agent.id)
        production = _secret(name="CRM", purpose="custom")
        test = _secret(name="Search", purpose="tavily")
        found = {production.id: production, test.id: test}
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(_MCP, new=AsyncMock(return_value={})),
            patch(_SECRETS, new=AsyncMock(side_effect=lambda _db, sid, **_: found[sid])),
            patch(_ACCESS, new=AsyncMock(return_value=True)),
        ):
            environments.get = AsyncMock(return_value=environment)

            with pytest.raises(BadRequestError, match="cannot stand in") as refused:
                await service.update(
                    _ctx(),
                    agent.id,
                    environment.id,
                    EnvironmentUpdate(
                        connections=[
                            EnvironmentConnectionWrite(
                                kind="secret", production_id=production.id, test_id=test.id
                            )
                        ]
                    ),
                )

        # Neither name: the caller may hold no grant on the production key.
        assert "CRM" not in refused.value.message and "Search" not in refused.value.message

    async def test_replacing_only_the_overrides_is_a_change_and_is_audited(self):
        agent = _agent()
        environment = _environment(agent_id=agent.id)
        production, test = _secret(name="CRM"), _secret(name="CRM sandbox")
        found = {production.id: production, test.id: test}
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(_MCP, new=AsyncMock(return_value={})),
            patch(_SECRETS, new=AsyncMock(side_effect=lambda _db, sid, **_: found[sid])),
            patch(_ACCESS, new=AsyncMock(return_value=True)),
            patch(_AUDIT, new=AsyncMock()) as audit,
        ):
            environments.get = AsyncMock(return_value=environment)
            environments.update = AsyncMock()
            environments.replace_connections = AsyncMock()
            await service.update(
                _ctx(),
                agent.id,
                environment.id,
                EnvironmentUpdate(
                    connections=[
                        EnvironmentConnectionWrite(
                            kind="secret", production_id=production.id, test_id=test.id
                        )
                    ]
                ),
            )

        environments.update.assert_not_awaited()
        (row,) = environments.replace_connections.call_args.kwargs["connections"]
        assert row.test_secret_id == test.id
        assert audit.call_args.kwargs["details"]["fields"] == ["connections"]
        # Ids, never a value: the audit trail is not a second copy of the vault.
        assert str(test.id) not in str(audit.call_args.kwargs["details"])

    async def test_the_default_environment_keeps_the_specs_connections(self):
        """The default is what every surface naming no environment runs - production."""
        agent = _agent()
        default = _environment(agent_id=agent.id, name="production", is_default=True)
        service = _service(agent)

        with patch(_REPO) as environments:
            environments.get = AsyncMock(return_value=default)

            with pytest.raises(BadRequestError, match="named environment"):
                await service.update(
                    _ctx(),
                    agent.id,
                    default.id,
                    EnvironmentUpdate(
                        connections=[
                            EnvironmentConnectionWrite(
                                kind="mcp", production_id=uuid.uuid4(), test_id=uuid.uuid4()
                            )
                        ]
                    ),
                )

    async def test_a_binding_can_be_switched_off_without_a_test_side(self):
        """Re-saving the list must keep an override whose test side was deleted:
        dropping it would quietly put staging back on production."""
        agent = _agent()
        environment = _environment(agent_id=agent.id)
        production = _named(id=uuid.uuid4())
        live_key = uuid.uuid4()
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(_MCP, new=AsyncMock(return_value={production.id: production})) as lookup,
            patch(_SECRETS, new=AsyncMock()) as secrets,
            patch(_AUDIT, new=AsyncMock()),
        ):
            environments.get = AsyncMock(return_value=environment)
            environments.replace_connections = AsyncMock()
            await service.update(
                _ctx(),
                agent.id,
                environment.id,
                EnvironmentUpdate(
                    connections=[
                        EnvironmentConnectionWrite(
                            kind="mcp", production_id=production.id, test_id=None
                        ),
                        EnvironmentConnectionWrite(
                            kind="secret", production_id=live_key, test_id=None
                        ),
                    ]
                ),
            )

        assert lookup.await_args.kwargs["connection_ids"] == [production.id]
        secrets.assert_not_awaited()
        rows = environments.replace_connections.call_args.kwargs["connections"]
        assert [(row.kind, row.test_id) for row in rows] == [("mcp", None), ("secret", None)]

    async def test_an_empty_list_clears_the_overrides(self):
        agent = _agent()
        environment = _environment(agent_id=agent.id)
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(_MCP, new=AsyncMock(return_value={})),
            patch(_AUDIT, new=AsyncMock()),
        ):
            environments.get = AsyncMock(return_value=environment)
            environments.replace_connections = AsyncMock()
            await service.update(
                _ctx(), agent.id, environment.id, EnvironmentUpdate(connections=[])
            )

        assert environments.replace_connections.call_args.kwargs["connections"] == []


class TestDelete:
    async def test_the_default_cannot_be_removed(self):
        """An agent without a default is one plain surfaces cannot run."""
        agent = _agent()
        environment = _environment(agent_id=agent.id, name="production", is_default=True)
        service = _service(agent)

        with patch(_REPO) as environments:
            environments.get = AsyncMock(return_value=environment)

            with pytest.raises(BadRequestError, match="default"):
                await service.delete(_ctx(), agent.id, environment.id)

    async def test_an_environment_with_a_run_still_working_is_not_removed(self):
        """The run's environment would become null, which reads as the default, and
        a staging run still working would then publish its pages over production's."""
        agent = _agent()
        environment = _environment(agent_id=agent.id, name="staging")
        service = _service(agent)
        order: list[str] = []

        with (
            patch(_REPO) as environments,
            patch(
                "app.services.agent_environment.agent_run_repo.count_unfinished_in_environment",
                new=AsyncMock(side_effect=lambda *_a, **_k: order.append("count") or 2),
            ),
        ):
            environments.get = AsyncMock(return_value=environment)
            environments.lock = AsyncMock(side_effect=lambda *_a, **_k: order.append("lock"))
            environments.delete = AsyncMock()
            with pytest.raises(ConcurrentChangeError, match="2 run"):
                await service.delete(_ctx(), agent.id, environment.id)

        environments.delete.assert_not_awaited()
        # Locked before counting, so no run can start in it between the two.
        assert order == ["lock", "count"]

    async def test_an_environment_with_an_eval_run_waiting_is_not_removed(self):
        """A queued eval run would otherwise go on against production's connections."""
        agent = _agent()
        environment = _environment(agent_id=agent.id, name="staging")
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(
                "app.services.agent_environment.agent_run_repo.count_unfinished_in_environment",
                new=AsyncMock(return_value=0),
            ),
            patch(_EVALS, new=AsyncMock(return_value=1)),
        ):
            environments.get = AsyncMock(return_value=environment)
            environments.lock = AsyncMock()
            environments.delete = AsyncMock()
            with pytest.raises(ConcurrentChangeError, match="1 eval run"):
                await service.delete(_ctx(), agent.id, environment.id)

        environments.delete.assert_not_awaited()

    async def test_a_named_environment_is_removed_and_audited(self):
        agent = _agent()
        environment = _environment(agent_id=agent.id, name="dev")
        service = _service(agent)

        order: list[str] = []
        with (
            patch(_REPO) as environments,
            patch(_AUDIT, new=AsyncMock()) as audit,
            patch(
                "app.services.agent_environment.artifact_repo.detach_environment",
                new=AsyncMock(side_effect=lambda *_a, **_k: order.append("detach")),
            ) as detach,
            patch(
                "app.services.agent_environment.agent_run_repo.count_unfinished_in_environment",
                new=AsyncMock(return_value=0),
            ),
            patch(_EVALS, new=AsyncMock(return_value=0)),
        ):
            environments.get = AsyncMock(return_value=environment)
            environments.lock = AsyncMock()
            environments.delete = AsyncMock(side_effect=lambda *_a, **_k: order.append("delete"))
            await service.delete(_ctx(), agent.id, environment.id)

        environments.delete.assert_awaited_once()
        # Its artifacts are detached first, or the foreign key would drop them into
        # the default environment's slot of the same name.
        assert detach.await_args.kwargs == {"environment_id": environment.id}
        assert order == ["detach", "delete"]
        assert audit.call_args.kwargs["details"]["name"] == "dev"
