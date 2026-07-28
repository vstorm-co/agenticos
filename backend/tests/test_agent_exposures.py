"""Tests for deciding where an agent is available.

The value of this service is almost entirely in what it refuses. Binding an
agent to a bot is one insert; the reasons it must not happen are a cross-tenant
bot, an agent the caller may look at but not publish, a platform no exposure
covers, a second binding racing a unique constraint, and an exposure id borrowed
from another agent in the same organization.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_exposure import ExposureSurface
from app.schemas.agent_exposure import ExposureCreate, ExposureUpdate
from app.services.agent_exposure import AgentExposureService

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_CALLER = uuid.uuid4()


def _ctx(role: str = OrgRoleName.OWNER) -> AuthContext:
    return AuthContext(user_id=_CALLER, organization_id=_ORG, role=role)


def _named(**attributes: object) -> MagicMock:
    """A stand-in with a real ``.name``.

    ``MagicMock(name=...)`` names the *mock* rather than setting an attribute, so
    ``.name`` comes back as another mock — which a schema then rejects several
    layers away from the mistake.
    """
    mock = MagicMock(**{key: value for key, value in attributes.items() if key != "name"})
    mock.name = attributes["name"]
    return mock


def _agent(*, agent_id: uuid.UUID | None = None, name: str = "Support") -> MagicMock:
    return _named(id=agent_id or uuid.uuid4(), name=name)


def _bot(*, platform: str = "slack", name: str = "Acme Support", bot_id=None) -> MagicMock:
    return _named(id=bot_id or uuid.uuid4(), platform=platform, name=name, is_active=True)


def _service(agent: MagicMock | None = None) -> AgentExposureService:
    """A service whose agent lookup succeeds, so the tests can be about bindings.

    The registry's own refusals — a missing agent, one the caller may not
    publish, another tenant's — are proven in ``tests/test_agent_registry.py``
    against the real ``resolve_access``. Re-proving them through a second
    service would test the mock.
    """
    service = AgentExposureService(MagicMock())
    service.agents = MagicMock()
    service.agents.get = AsyncMock(return_value=agent or _agent())
    return service


class TestCreate:
    async def test_a_bot_from_another_organization_is_reported_as_missing(self):
        """Not "forbidden": a probeable id is how a tenant boundary is mapped."""
        service = _service()
        with patch("app.services.agent_exposure.channel_bot_repo") as bots:
            bots.get_for_org = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.create(
                    _ctx(), uuid.uuid4(), ExposureCreate(channel_bot_id=uuid.uuid4())
                )

    async def test_the_bot_is_looked_up_inside_the_callers_organization(self):
        """The lookup is the boundary; without the scope the refusal above cannot happen."""
        service = _service()
        bot = _bot()
        with (
            patch("app.services.agent_exposure.channel_bot_repo") as bots,
            patch("app.services.agent_exposure.agent_exposure_repo") as exposures,
            patch("app.services.agent_exposure.record_audit", new=AsyncMock()),
        ):
            bots.get_for_org = AsyncMock(return_value=bot)
            exposures.get_for_bot = AsyncMock(return_value=None)
            exposures.create = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))

            await service.create(_ctx(), uuid.uuid4(), ExposureCreate(channel_bot_id=bot.id))

        assert bots.get_for_org.call_args.kwargs["organization_id"] == _ORG

    async def test_a_platform_no_exposure_covers_is_refused_at_binding_time(self):
        """A binding that can never route is worse than none: it looks correct."""
        service = _service()
        with patch("app.services.agent_exposure.channel_bot_repo") as bots:
            bots.get_for_org = AsyncMock(return_value=_bot(platform="discord"))

            with pytest.raises(BadRequestError) as refused:
                await service.create(
                    _ctx(), uuid.uuid4(), ExposureCreate(channel_bot_id=uuid.uuid4())
                )

        assert refused.value.details == {"platform": "discord"}

    async def test_the_surface_is_taken_from_the_bot_not_from_the_caller(self):
        """One source of truth for which platform a binding serves."""
        service = _service()
        bot = _bot(platform="telegram")
        with (
            patch("app.services.agent_exposure.channel_bot_repo") as bots,
            patch("app.services.agent_exposure.agent_exposure_repo") as exposures,
            patch("app.services.agent_exposure.record_audit", new=AsyncMock()),
        ):
            bots.get_for_org = AsyncMock(return_value=bot)
            exposures.get_for_bot = AsyncMock(return_value=None)
            exposures.create = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))

            await service.create(_ctx(), uuid.uuid4(), ExposureCreate(channel_bot_id=bot.id))

        assert exposures.create.call_args.kwargs["surface"] == ExposureSurface.TELEGRAM.value

    @pytest.mark.parametrize("is_active", [True, False])
    async def test_a_second_binding_to_the_same_bot_is_refused(self, is_active):
        """Including a paused one — it still occupies the unique constraint.

        Letting the insert reach the database would turn a question the service
        can answer into an IntegrityError with nothing useful in it.
        """
        service = _service()
        existing = MagicMock(id=uuid.uuid4(), is_active=is_active)
        with (
            patch("app.services.agent_exposure.channel_bot_repo") as bots,
            patch("app.services.agent_exposure.agent_exposure_repo") as exposures,
        ):
            bots.get_for_org = AsyncMock(return_value=_bot())
            exposures.get_for_bot = AsyncMock(return_value=existing)
            exposures.create = AsyncMock()

            with pytest.raises(AlreadyExistsError) as refused:
                await service.create(
                    _ctx(), uuid.uuid4(), ExposureCreate(channel_bot_id=uuid.uuid4())
                )

        assert refused.value.details["exposure_id"] == str(existing.id)
        exposures.create.assert_not_called()

    async def test_binding_demands_permission_to_publish_the_agent(self):
        """Where an agent runs is the same class of decision as what runs."""
        service = _service()
        with (
            patch("app.services.agent_exposure.channel_bot_repo") as bots,
            patch("app.services.agent_exposure.agent_exposure_repo") as exposures,
            patch("app.services.agent_exposure.record_audit", new=AsyncMock()),
        ):
            bots.get_for_org = AsyncMock(return_value=_bot())
            exposures.get_for_bot = AsyncMock(return_value=None)
            exposures.create = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))

            await service.create(_ctx(), uuid.uuid4(), ExposureCreate(channel_bot_id=uuid.uuid4()))

        assert service.agents.get.call_args.kwargs["perm"].value == "agents:publish"

    async def test_the_binding_is_recorded_in_the_audit_trail(self):
        """ "Why did it answer in that channel" starts with who put it there."""
        agent = _agent()
        service = _service(agent)
        bot = _bot()
        audit = AsyncMock()
        with (
            patch("app.services.agent_exposure.channel_bot_repo") as bots,
            patch("app.services.agent_exposure.agent_exposure_repo") as exposures,
            patch("app.services.agent_exposure.record_audit", new=audit),
        ):
            bots.get_for_org = AsyncMock(return_value=bot)
            exposures.get_for_bot = AsyncMock(return_value=None)
            exposures.create = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))

            await service.create(_ctx(), agent.id, ExposureCreate(channel_bot_id=bot.id))

        assert audit.call_args.kwargs["action"] == "agent.exposed"
        assert audit.call_args.kwargs["details"]["channel_bot_id"] == str(bot.id)


class TestReading:
    async def test_a_listing_names_the_bot_a_person_would_recognise(self):
        agent = _agent()
        service = _service(agent)
        bot = _bot(name="Acme Support")
        exposure = MagicMock(
            id=uuid.uuid4(),
            agent_id=agent.id,
            surface="slack",
            channel_bot_id=bot.id,
            is_active=True,
            max_per_run_usd=None,
            monthly_usd=None,
            created_at=None,
        )
        with (
            patch("app.services.agent_exposure.agent_exposure_repo") as exposures,
            patch("app.services.agent_exposure.channel_bot_repo") as bots,
        ):
            exposures.list_for_agent = AsyncMock(return_value=[exposure])
            bots.list_for_org = AsyncMock(return_value=[bot])

            items = await service.list_for_agent(_ctx(), agent.id)

        assert [(item.surface, item.channel_bot_name) for item in items] == [
            (ExposureSurface.SLACK, "Acme Support")
        ]

    async def test_a_bot_deleted_between_the_two_queries_still_renders(self):
        """A blank row in the Builder is worse than one that says what happened."""
        agent = _agent()
        service = _service(agent)
        exposure = MagicMock(
            id=uuid.uuid4(),
            agent_id=agent.id,
            surface="slack",
            channel_bot_id=uuid.uuid4(),
            is_active=True,
            max_per_run_usd=None,
            monthly_usd=None,
            created_at=None,
        )
        with (
            patch("app.services.agent_exposure.agent_exposure_repo") as exposures,
            patch("app.services.agent_exposure.channel_bot_repo") as bots,
        ):
            exposures.list_for_agent = AsyncMock(return_value=[exposure])
            bots.list_for_org = AsyncMock(return_value=[])

            items = await service.list_for_agent(_ctx(), agent.id)

        assert items[0].channel_bot_name == "(removed)"

    async def test_a_listing_is_scoped_to_the_callers_organization(self):
        agent = _agent()
        service = _service(agent)
        with (
            patch("app.services.agent_exposure.agent_exposure_repo") as exposures,
            patch("app.services.agent_exposure.channel_bot_repo") as bots,
        ):
            exposures.list_for_agent = AsyncMock(return_value=[])
            bots.list_for_org = AsyncMock(return_value=[])

            await service.list_for_agent(_ctx(), agent.id)

        assert exposures.list_for_agent.call_args.kwargs["organization_id"] == _ORG

    async def test_the_picker_leaves_out_bots_no_exposure_could_serve(self):
        """Offering a choice that would be refused is a form of lying."""
        service = _service()
        with patch("app.services.agent_exposure.channel_bot_repo") as bots:
            bots.list_for_org = AsyncMock(
                return_value=[_bot(platform="slack"), _bot(platform="discord")]
            )

            targets = await service.targets(_ctx(), uuid.uuid4())

        assert [target.platform for target in targets] == [ExposureSurface.SLACK]

    async def test_the_picker_needs_only_permission_to_see_the_agent(self):
        """Choosing where an agent goes must not require running the bots.

        ``channels:manage`` governs a bot's token, webhook and access policy.
        Demanding it here would leave the Builders who publish agents unable to
        put one in Slack, and the section read-only for the people it is for.
        """
        service = _service()
        with patch("app.services.agent_exposure.channel_bot_repo") as bots:
            bots.list_for_org = AsyncMock(return_value=[])

            await service.targets(_ctx(OrgRoleName.VIEWER), uuid.uuid4())

        assert service.agents.get.call_args.kwargs == {}


class TestChangingABinding:
    async def test_an_exposure_belonging_to_another_agent_is_not_reachable(self):
        """A cross-resource escalation that stays inside one organization.

        Scoping only by organization would let somebody pass another agent's
        exposure id to an agent they *can* publish and unbind it.
        """
        agent = _agent()
        service = _service(agent)
        with patch("app.services.agent_exposure.agent_exposure_repo") as exposures:
            exposures.get = AsyncMock(return_value=MagicMock(agent_id=uuid.uuid4()))
            exposures.delete = AsyncMock()

            with pytest.raises(NotFoundError):
                await service.delete(_ctx(), agent.id, uuid.uuid4())

            exposures.delete.assert_not_called()

    async def test_an_exposure_from_another_organization_is_not_reachable(self):
        agent = _agent()
        service = _service(agent)
        with patch("app.services.agent_exposure.agent_exposure_repo") as exposures:
            exposures.get = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.delete(_ctx(), agent.id, uuid.uuid4())

        assert exposures.get.call_args.kwargs["organization_id"] == _ORG

    @pytest.mark.parametrize(
        ("is_active", "action"),
        [(False, "agent.exposure_paused"), (True, "agent.exposure_resumed")],
    )
    async def test_pausing_and_resuming_are_recorded_as_different_acts(self, is_active, action):
        """The two edits somebody searches the trail for after a bot went quiet."""
        agent = _agent()
        service = _service(agent)
        audit = AsyncMock()
        exposure = MagicMock(id=uuid.uuid4(), agent_id=agent.id)
        with (
            patch("app.services.agent_exposure.agent_exposure_repo") as exposures,
            patch("app.services.agent_exposure.record_audit", new=audit),
        ):
            exposures.get = AsyncMock(return_value=exposure)
            exposures.update = AsyncMock(return_value=exposure)

            await service.update(_ctx(), agent.id, exposure.id, ExposureUpdate(is_active=is_active))

        assert exposures.update.call_args.kwargs["update_data"] == {"is_active": is_active}
        assert audit.call_args.kwargs["action"] == action

    async def test_changing_only_the_budget_leaves_the_binding_running(self):
        """A field nobody sent must not be written.

        ``is_active`` has no meaningful default here: sending one would pause a
        live binding every time somebody adjusted its ceiling, and resuming it
        would be a second request nobody knew to make.
        """
        agent = _agent()
        service = _service(agent)
        exposure = MagicMock(id=uuid.uuid4(), agent_id=agent.id)
        with (
            patch("app.services.agent_exposure.agent_exposure_repo") as exposures,
            patch("app.services.agent_exposure.record_audit", new=AsyncMock()),
        ):
            exposures.get = AsyncMock(return_value=exposure)
            exposures.update = AsyncMock(return_value=exposure)

            await service.update(
                _ctx(), agent.id, exposure.id, ExposureUpdate(monthly_usd=Decimal("25"))
            )

        assert exposures.update.call_args.kwargs["update_data"] == {"monthly_usd": Decimal("25")}

    async def test_a_budget_change_is_recorded_with_the_numbers(self):
        """ "Somebody changed the budget" is not an entry anyone can act on later."""
        agent = _agent()
        service = _service(agent)
        audit = AsyncMock()
        exposure = MagicMock(id=uuid.uuid4(), agent_id=agent.id)
        with (
            patch("app.services.agent_exposure.agent_exposure_repo") as exposures,
            patch("app.services.agent_exposure.record_audit", new=audit),
        ):
            exposures.get = AsyncMock(return_value=exposure)
            exposures.update = AsyncMock(return_value=exposure)

            await service.update(
                _ctx(), agent.id, exposure.id, ExposureUpdate(max_per_run_usd=Decimal("0.5"))
            )

        assert audit.call_args.kwargs["action"] == "agent.exposure_updated"
        # A string, because the trail is JSON and a Decimal does not survive the
        # round trip as itself.
        assert audit.call_args.kwargs["details"]["changes"] == {"max_per_run_usd": "0.5"}

    async def test_a_binding_can_be_created_with_the_caps_it_will_run_under(self):
        service = _service()
        bot = _bot()
        with (
            patch("app.services.agent_exposure.channel_bot_repo") as bots,
            patch("app.services.agent_exposure.agent_exposure_repo") as exposures,
            patch("app.services.agent_exposure.record_audit", new=AsyncMock()),
        ):
            bots.get_for_org = AsyncMock(return_value=bot)
            exposures.get_for_bot = AsyncMock(return_value=None)
            exposures.create = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))

            await service.create(
                _ctx(),
                uuid.uuid4(),
                ExposureCreate(
                    channel_bot_id=bot.id,
                    max_per_run_usd=Decimal("0.5"),
                    monthly_usd=Decimal("25"),
                ),
            )

        written = exposures.create.call_args.kwargs
        assert (written["max_per_run_usd"], written["monthly_usd"]) == (
            Decimal("0.5"),
            Decimal("25"),
        )

    async def test_removing_a_binding_is_recorded_with_the_surface_it_removed(self):
        """After the fact, the row is gone; the trail is the only record of it."""
        agent = _agent()
        service = _service(agent)
        audit = AsyncMock()
        exposure = MagicMock(id=uuid.uuid4(), agent_id=agent.id, surface="telegram")
        with (
            patch("app.services.agent_exposure.agent_exposure_repo") as exposures,
            patch("app.services.agent_exposure.record_audit", new=audit),
        ):
            exposures.get = AsyncMock(return_value=exposure)
            exposures.delete = AsyncMock()

            await service.delete(_ctx(), agent.id, exposure.id)

        exposures.delete.assert_awaited_once_with(service.db, exposure)
        assert audit.call_args.kwargs["action"] == "agent.unexposed"
        assert audit.call_args.kwargs["details"]["surface"] == "telegram"

    async def test_changing_a_binding_demands_permission_to_publish_the_agent(self):
        agent = _agent()
        service = _service(agent)
        exposure = MagicMock(id=uuid.uuid4(), agent_id=agent.id, surface="slack")
        with (
            patch("app.services.agent_exposure.agent_exposure_repo") as exposures,
            patch("app.services.agent_exposure.record_audit", new=AsyncMock()),
        ):
            exposures.get = AsyncMock(return_value=exposure)
            exposures.delete = AsyncMock()

            await service.delete(_ctx(), agent.id, exposure.id)

        assert service.agents.get.call_args.kwargs["perm"].value == "agents:publish"
