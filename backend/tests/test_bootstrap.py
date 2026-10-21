"""Tests for the bootstrap command.

The command exists so a fresh install reaches a running agent. What matters is
that running it twice is safe - people re-run a setup script when they are not
sure it worked - and that a missing API key produces a visible half-built state
rather than an agent that silently cannot run.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.model_resolver import PROVIDERS
from app.commands import bootstrap as bootstrap_cmd
from app.commands.bootstrap import (
    DEFAULT_MODELS,
    _resolve_model,
    _resolve_organization,
    _resolve_starter_agents,
)
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.resource_grant import Visibility
from app.services.agent_templates import STARTER_TEMPLATE


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


class TestProviderDefaults:
    def test_every_provider_bootstrap_offers_is_one_the_platform_supports(self):
        """Bootstrap offers a shortlist, not the catalog - but not a fiction either.

        A provider here that the catalog does not have would fail at profile
        creation, after the owner and the organization were already created,
        leaving a half-built install.
        """
        assert set(DEFAULT_MODELS) <= set(PROVIDERS)

    def test_the_openrouter_default_is_namespaced(self):
        """A bare id is rejected at profile creation, which would break bootstrap."""
        assert "/" in DEFAULT_MODELS["openrouter"]


class TestOrganization:
    @pytest.mark.anyio
    async def test_an_existing_personal_org_is_reused(self):
        """It is where a new operator lands after signing in."""
        existing = MagicMock(name="Personal")
        with patch(
            "app.commands.bootstrap.organization_repo.get_personal_for_user",
            new=AsyncMock(return_value=existing),
        ):
            assert await _resolve_organization(MagicMock(), uuid.uuid4(), "Acme") is existing

    @pytest.mark.anyio
    async def test_a_fresh_install_gets_an_organization_and_an_owner(self):
        created = MagicMock(id=uuid.uuid4())
        with (
            patch(
                "app.commands.bootstrap.organization_repo.get_personal_for_user",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.commands.bootstrap.organization_repo.create",
                new=AsyncMock(return_value=created),
            ) as create_org,
            patch("app.commands.bootstrap.member_repo.create", new=AsyncMock()) as add_member,
        ):
            result = await _resolve_organization(MagicMock(), uuid.uuid4(), "Acme")

        assert result is created
        assert add_member.call_args.kwargs["role"] == OrgRoleName.OWNER.value
        # A bootstrapped org gets the same default cap as any other (#785).
        assert create_org.await_args.kwargs["monthly_budget_usd"] == Decimal("100")


class TestModel:
    @pytest.mark.anyio
    async def test_the_profile_it_already_created_is_reused(self):
        """Re-running bootstrap is what people do when unsure it worked; the
        profile it names is unique on its label, so a second run adopts the one
        the first left rather than creating a duplicate it would be refused."""
        existing = MagicMock(id=uuid.uuid4(), label="openai default")
        with patch(
            "app.commands.bootstrap.credential_repo.get_profile_by_label",
            new=AsyncMock(return_value=existing),
        ) as by_label:
            assert await _resolve_model(MagicMock(), _ctx(), "openai", None, None) == existing.id
        assert by_label.await_args.args[1] == "openai default"

    @pytest.mark.anyio
    async def test_an_unrelated_profile_is_not_adopted(self):
        """The bug this command was carrying: it reused the *first* profile it
        found, so a developer database already holding an unrelated one - or a
        profile a failed spec leaked - was adopted and `openai default` never
        created. `make platform-bootstrap` promises a known starting point, and
        that only holds if the profile it guarantees is the one it names."""
        created = MagicMock(id=uuid.uuid4(), label="openai default")
        with (
            patch(
                "app.commands.bootstrap.credential_repo.get_profile_by_label",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.commands.bootstrap.OrganizationSecretService.create",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4(), hint="1234")),
            ),
            patch(
                "app.commands.bootstrap.ModelProfileService.create_profile",
                new=AsyncMock(return_value=created),
            ) as create_profile,
        ):
            result = await _resolve_model(MagicMock(), _ctx(), "openai", "sk-test-1234", None)

        assert result == created.id
        assert create_profile.call_args.kwargs["label"] == "openai default"

    @pytest.mark.anyio
    async def test_a_key_is_stored_and_the_profile_points_at_it(self):
        secret = MagicMock(id=uuid.uuid4(), hint="1234")
        profile = MagicMock(id=uuid.uuid4(), label="openai default")

        with (
            patch(
                "app.commands.bootstrap.credential_repo.get_profile_by_label",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.commands.bootstrap.OrganizationSecretService.create",
                new=AsyncMock(return_value=secret),
            ),
            patch(
                "app.commands.bootstrap.ModelProfileService.create_profile",
                new=AsyncMock(return_value=profile),
            ) as create_profile,
        ):
            await _resolve_model(MagicMock(), _ctx(), "openai", "sk-test-1234", None)

        assert create_profile.call_args.kwargs["secret_id"] == secret.id

    @pytest.mark.anyio
    async def test_without_a_key_no_profile_is_created_at_all(self):
        """A keyless profile is a row that can never run and that nothing
        repoints - models are keyed from the vault, and the only way to give one
        a key is to add the model again. It appeared in the Builder as
        `openai default · no key`: an option whose only effect was to make an
        agent fail at its first message."""
        with (
            patch(
                "app.commands.bootstrap.credential_repo.get_profile_by_label",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.commands.bootstrap.ModelProfileService.create_profile",
                new=AsyncMock(),
            ) as create_profile,
        ):
            profile_id = await _resolve_model(MagicMock(), _ctx(), "openai", None, None)

        assert profile_id is None
        create_profile.assert_not_called()

    @pytest.mark.anyio
    async def test_an_explicit_model_id_overrides_the_default(self):
        profile = MagicMock(id=uuid.uuid4(), label="x")
        with (
            patch(
                "app.commands.bootstrap.credential_repo.get_profile_by_label",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.commands.bootstrap.OrganizationSecretService.create",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4(), hint="abcd")),
            ),
            patch(
                "app.commands.bootstrap.ModelProfileService.create_profile",
                new=AsyncMock(return_value=profile),
            ) as create_profile,
        ):
            await _resolve_model(MagicMock(), _ctx(), "openai", "sk-test-1234", "gpt-4o-mini")

        assert create_profile.call_args.kwargs["model"] == "gpt-4o-mini"


class TestStarterAgents:
    """The Architect and Claude Code like - what a new organization opens with."""

    @staticmethod
    def _patches(*, existing=None, assistant_status="ready", publish=None):
        agent = MagicMock(id=uuid.uuid4(), draft_spec={"name": "Claude Code like"})
        install = AsyncMock(return_value=MagicMock(agent_id=agent.id))
        mocks = {
            "state": AsyncMock(return_value=MagicMock(status=assistant_status, name="Architect")),
            "get_by_slug": AsyncMock(return_value=existing),
            "install": install,
            "get": AsyncMock(return_value=agent),
            "save_draft": AsyncMock(),
            "publish": publish or AsyncMock(),
            "sandbox": AsyncMock(return_value=True),
        }
        return (
            agent,
            mocks,
            (
                patch("app.commands.bootstrap.AssistantService.state", new=mocks["state"]),
                patch("app.commands.bootstrap.agent_repo.get_by_slug", new=mocks["get_by_slug"]),
                patch(
                    "app.commands.bootstrap.AgentRegistryService.install_template",
                    new=mocks["install"],
                ),
                patch("app.commands.bootstrap.AgentRegistryService.get", new=mocks["get"]),
                patch(
                    "app.commands.bootstrap.AgentRegistryService.save_draft",
                    new=mocks["save_draft"],
                ),
                patch("app.commands.bootstrap.AgentRegistryService.publish", new=mocks["publish"]),
                patch(
                    "app.commands.bootstrap.SandboxConnectionService.ensure_local_connection",
                    new=mocks["sandbox"],
                ),
            ),
        )

    @staticmethod
    async def _run(patches, profile_id):
        from contextlib import ExitStack

        with ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            await _resolve_starter_agents(MagicMock(), _ctx(), profile_id)

    @pytest.mark.anyio
    async def test_both_are_installed_and_the_starter_runs_on_the_bootstrapped_model(self):
        profile_id = uuid.uuid4()
        agent, mocks, patches = self._patches()

        await self._run(patches, profile_id)

        mocks["state"].assert_awaited_once()
        # From its template, and visible to the organization rather than to the
        # bootstrapper alone.
        assert mocks["install"].await_args.args[1] == STARTER_TEMPLATE
        assert mocks["install"].await_args.kwargs["visibility"] == Visibility.ORG
        spec = mocks["save_draft"].await_args.args[2]
        assert spec.model_profile_id == profile_id
        mocks["publish"].assert_awaited_once()

    @pytest.mark.anyio
    async def test_without_a_model_both_stay_drafts(self):
        _, mocks, patches = self._patches(assistant_status="needs_model")
        await self._run(patches, None)
        mocks["install"].assert_awaited_once()
        mocks["publish"].assert_not_awaited()
        # The sandbox does not wait for a model: it is set up on the first run.
        mocks["sandbox"].assert_awaited_once()

    @pytest.mark.anyio
    async def test_a_second_run_does_not_install_a_second_one(self):
        """Re-running a setup script is what people do when unsure it worked."""
        _, mocks, patches = self._patches(existing=MagicMock())
        await self._run(patches, uuid.uuid4())
        mocks["install"].assert_not_awaited()
        mocks["sandbox"].assert_awaited_once()

    @pytest.mark.anyio
    async def test_a_spec_this_deployment_cannot_publish_is_left_a_draft(self):
        """No sandbox to give it, say - the agent waits, the bootstrap does not stop."""
        publish = AsyncMock(side_effect=BadRequestError(message="No sandbox"))
        _, mocks, patches = self._patches(publish=publish)
        await self._run(patches, uuid.uuid4())
        publish.assert_awaited_once()


class TestEndToEnd:
    """The command itself, with the database and services stubbed.

    The helpers above cover the decisions; this covers the wiring - that the
    steps run in an order where each has what the previous produced, and that
    the transaction is committed rather than left open.
    """

    @pytest.fixture(autouse=True)
    def mirror(self, monkeypatch):
        """The registry-mirror step, stubbed for every test in this class.

        It is a real repository call and these tests hand `_bootstrap` a
        `MagicMock` session, so unstubbed it fails inside `count` at `await
        db.execute(...)`. That is a fact about the fixture rather than about the
        step, and the step has its own tests.
        """
        stub = AsyncMock()
        monkeypatch.setattr(bootstrap_cmd, "_resolve_mcp_mirror", stub)
        self.mirror = stub
        return stub

    @staticmethod
    def _db_context(db):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def context():
            yield db

        return context

    @pytest.mark.anyio
    async def test_a_fresh_install_walks_the_whole_chain(self):
        from app.commands.bootstrap import _bootstrap

        db = MagicMock()
        db.commit = AsyncMock()
        user = MagicMock(id=uuid.uuid4())
        org = MagicMock(id=uuid.uuid4())
        profile_id = uuid.uuid4()

        with (
            patch("app.commands.bootstrap.get_db_context", self._db_context(db)),
            patch(
                "app.commands.bootstrap.UserService.get_by_email",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.commands.bootstrap.UserService.register",
                new=AsyncMock(return_value=user),
            ) as register,
            patch(
                "app.commands.bootstrap._resolve_organization",
                new=AsyncMock(return_value=org),
            ),
            patch(
                "app.commands.bootstrap._resolve_model",
                new=AsyncMock(return_value=profile_id),
            ) as resolve_model,
            patch("app.commands.bootstrap._resolve_starter_agents", new=AsyncMock()) as demo,
        ):
            await _bootstrap(
                "admin@example.com", "password123", "Acme", "openai", "sk-test-1234", None
            )

        register.assert_awaited_once()
        # The agent must be given the model the previous step produced.
        assert demo.call_args.args[2] == profile_id
        assert resolve_model.await_count == 1
        self.mirror.assert_awaited()
        db.commit.assert_awaited_once()

    @pytest.mark.anyio
    async def test_the_owner_is_made_platform_admin(self):
        """Bootstrap's owner administers the deployment, not just their org.

        /admin, bulk /rag and user management all gate on `is_app_admin`; a
        fresh install whose only user cannot reach them has no way to grant
        the flag except the separate CLI command nobody is told about.
        """
        from app.commands.bootstrap import _bootstrap

        db = MagicMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        user = MagicMock(id=uuid.uuid4())
        user.is_app_admin = False

        with (
            patch("app.commands.bootstrap.get_db_context", self._db_context(db)),
            patch(
                "app.commands.bootstrap.UserService.get_by_email",
                new=AsyncMock(return_value=user),
            ),
            patch(
                "app.commands.bootstrap._resolve_organization",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch("app.commands.bootstrap._resolve_model", new=AsyncMock(return_value=None)),
            patch("app.commands.bootstrap._resolve_starter_agents", new=AsyncMock()),
        ):
            await _bootstrap("admin@example.com", "password123", "Acme", "openai", None, None)

        assert user.is_app_admin is True

    @pytest.mark.anyio
    async def test_an_existing_owner_is_not_registered_again(self):
        from app.commands.bootstrap import _bootstrap

        db = MagicMock()
        db.commit = AsyncMock()

        with (
            patch("app.commands.bootstrap.get_db_context", self._db_context(db)),
            patch(
                "app.commands.bootstrap.UserService.get_by_email",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch("app.commands.bootstrap.UserService.register", new=AsyncMock()) as register,
            patch(
                "app.commands.bootstrap._resolve_organization",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch("app.commands.bootstrap._resolve_model", new=AsyncMock(return_value=None)),
            patch("app.commands.bootstrap._resolve_starter_agents", new=AsyncMock()),
        ):
            await _bootstrap("admin@example.com", "password123", "Acme", "openai", None, None)

        register.assert_not_awaited()

    def test_the_click_entry_point_runs_the_coroutine(self):
        from click.testing import CliRunner

        from app.commands.bootstrap import bootstrap

        with patch("app.commands.bootstrap.asyncio.run") as run:
            result = CliRunner().invoke(bootstrap, ["--email", "a@b.c"])

        assert result.exit_code == 0
        run.assert_called_once()
