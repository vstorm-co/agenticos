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

from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.schemas.agent_environment import EnvironmentCreate, EnvironmentUpdate
from app.services.agent_environment import AgentEnvironmentService

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_CALLER = uuid.uuid4()

_REPO = "app.services.agent_environment.agent_environment_repo"
_AGENTS = "app.services.agent_environment.agent_repo"
_AUDIT = "app.services.agent_environment.record_audit"


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
            patch(f"{_AGENTS}.get_version", new=AsyncMock(return_value=version)),
        ):
            environments.list_for_agent = AsyncMock(return_value=[environment])
            items = await service.list_for_agent(_ctx(), agent.id)

        assert [(item.name, item.version, item.is_default) for item in items] == [
            ("production", 7, True)
        ]

    async def test_a_version_deleted_mid_listing_renders_as_zero_not_a_crash(self):
        """The window between the two reads is not a state anyone can persist;
        taking the whole listing down for it would hide every other row."""
        agent = _agent()
        environment = _environment(agent_id=agent.id)
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(f"{_AGENTS}.get_version", new=AsyncMock(return_value=None)),
        ):
            environments.list_for_agent = AsyncMock(return_value=[environment])
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

        assert audit.call_args.kwargs["action"] == "agent.environment_renamed"

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

    async def test_a_named_environment_is_removed_and_audited(self):
        agent = _agent()
        environment = _environment(agent_id=agent.id, name="dev")
        service = _service(agent)

        with (
            patch(_REPO) as environments,
            patch(_AUDIT, new=AsyncMock()) as audit,
        ):
            environments.get = AsyncMock(return_value=environment)
            environments.delete = AsyncMock()
            await service.delete(_ctx(), agent.id, environment.id)

        environments.delete.assert_awaited_once()
        assert audit.call_args.kwargs["details"]["name"] == "dev"
