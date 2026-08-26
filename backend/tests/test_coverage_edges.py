"""The paths that only run when something has already gone wrong.

Every case here is a branch the happy path never reaches: a provider package
that is not installed, a search API that answers 500, a Logfire token that does
not configure, a capability whose stored config no longer parses. They are the
branches most likely to be wrong, because nobody runs them by accident - and
each one is on the platform layer, which this repository holds to 100%.
"""

import sys
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.budget import BudgetScope
from app.agents.capabilities.web_research._search import SearchUnavailable, search
from app.agents.observability import instrument_agent
from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import SecretCondition
from app.db.models.agent_run import ApprovalStatus, RunStatus
from app.services.agent_runner import AgentRunnerService

SEARCH = "app.agents.capabilities.web_research._search"


class TestSearchProvidersThatCannotAnswer:
    """A provider that is unreachable must raise, never return zero results:
    the model reads "no hits" as an answer and carries on from memory."""

    @pytest.mark.anyio
    async def test_a_missing_duckduckgo_package_is_reported(self):
        with (
            patch.dict(sys.modules, {"ddgs": None}),
            pytest.raises(SearchUnavailable, match="ddgs"),
        ):
            await search("q", provider="duckduckgo", api_key=None, max_results=3)

    @pytest.mark.anyio
    async def test_a_duckduckgo_failure_is_reported(self):
        module = MagicMock()
        module.DDGS = MagicMock(side_effect=RuntimeError("ratelimited"))
        with (
            patch.dict(sys.modules, {"ddgs": module}),
            pytest.raises(SearchUnavailable, match="DuckDuckGo search is unavailable"),
        ):
            await search("q", provider="duckduckgo", api_key=None, max_results=3)

    @pytest.mark.anyio
    async def test_a_missing_tavily_package_is_reported(self):
        with (
            patch.dict(sys.modules, {"tavily": None}),
            pytest.raises(SearchUnavailable, match="tavily-python"),
        ):
            await search("q", provider="tavily", api_key="k", max_results=3)

    @pytest.mark.anyio
    async def test_a_brave_failure_is_reported(self):
        with (
            patch("httpx.AsyncClient", side_effect=RuntimeError("connection refused")),
            pytest.raises(SearchUnavailable, match="Brave"),
        ):
            await search("q", provider="brave", api_key="k", max_results=3)

    @pytest.mark.anyio
    async def test_an_exa_failure_is_reported(self):
        with (
            patch("httpx.AsyncClient", side_effect=RuntimeError("connection refused")),
            pytest.raises(SearchUnavailable, match="Exa"),
        ):
            await search("q", provider="exa", api_key="k", max_results=3)


class TestPerAgentTracing:
    """An agent that cannot export traces still answers questions. Refusing to
    build it would turn an observability misconfiguration into an outage."""

    def test_a_configured_instance_is_attached_to_the_agent(self):
        instance = MagicMock()
        agent = MagicMock()
        with patch("logfire.configure", return_value=instance) as configure:
            attached = instrument_agent(
                agent, token="pylf_token", service_name="acme", environment="production"
            )

        assert attached is True
        instance.instrument_pydantic_ai.assert_called_once_with(agent)
        assert configure.call_args.kwargs["service_name"] == "acme"

    def test_the_instance_is_reused_for_the_same_project(self):
        """Configuring starts an exporter and a flush thread; doing it per run
        would leak one of each per conversation."""
        with patch("logfire.configure", return_value=MagicMock()) as configure:
            instrument_agent(agent := MagicMock(), token="same", service_name="s", environment="e")
            instrument_agent(agent, token="same", service_name="s", environment="e")

        configure.assert_called_once()

    def test_a_configuration_failure_is_swallowed(self):
        with patch("logfire.configure", side_effect=RuntimeError("bad token")):
            assert (
                instrument_agent(MagicMock(), token="nope", service_name="x", environment=None)
                is False
            )

    def test_an_instrumentation_failure_is_swallowed(self):
        instance = MagicMock()
        instance.instrument_pydantic_ai.side_effect = RuntimeError("version mismatch")
        with patch("logfire.configure", return_value=instance):
            assert (
                instrument_agent(MagicMock(), token="tok-2", service_name="y", environment=None)
                is False
            )


class TestConditionalSecrets:
    def test_a_configuration_that_does_not_parse_needs_nothing(self):
        """`None` reaches here when a capability has no schema at all; demanding
        a key for it would refuse a binding nothing can satisfy."""
        assert SecretCondition(field="method", equals=("tavily",)).is_met(None) is False

    @pytest.mark.anyio
    async def test_a_binding_whose_stored_config_is_invalid_reports_only_that(self):
        """The caller already names the config problem. Adding "and it needs a
        secret" would be a second complaint about the same broken field."""
        from app.core.exceptions import BadRequestError
        from app.services.agent_registry import AgentRegistryService

        definition = MagicMock()
        definition.secret = MagicMock()
        definition.validate_config.side_effect = BadRequestError(message="bad config")
        binding = MagicMock(id="web_research", config={"method": 42}, secret_id=None)

        problems = await AgentRegistryService(MagicMock())._secret_problems(
            _ctx(), binding, definition
        )

        assert problems == []

    @pytest.mark.anyio
    async def test_a_keyless_configuration_with_nothing_selected_is_fine(self):
        """DuckDuckGo publishes with no key. This is the branch that makes the
        free default usable at all - without it the conditional requirement
        would be a requirement."""
        from app.services.agent_registry import AgentRegistryService

        definition = MagicMock()
        definition.secret = MagicMock()
        definition.needs_secret.return_value = False
        definition.validate_config.return_value = MagicMock()
        binding = MagicMock(id="web_research", config={"method": "duckduckgo"})
        binding.secret_id = None

        problems = await AgentRegistryService(MagicMock())._secret_problems(
            _ctx(), binding, definition
        )

        assert problems == []

    @pytest.mark.anyio
    async def test_a_keyless_configuration_with_a_stored_reference_still_complains(self):
        """DuckDuckGo needs no key, but a binding pointing at one would store a
        reference nothing reads - the quiet half of a misconfiguration, and the
        only one nobody would otherwise notice."""
        from app.services.agent_registry import AgentRegistryService

        definition = MagicMock()
        definition.secret = MagicMock(kind=MagicMock(value="api_key"), description="the key")
        definition.needs_secret.return_value = False
        definition.validate_config.return_value = MagicMock()
        binding = MagicMock(id="web_research", config={"method": "duckduckgo"})
        binding.secret_id = uuid.uuid4()

        with patch(
            "app.services.agent_registry.organization_secret_repo.get",
            new=AsyncMock(return_value=None),
        ):
            problems = await AgentRegistryService(MagicMock())._secret_problems(
                _ctx(), binding, definition
            )

        assert len(problems) == 1
        assert "does not have" in problems[0]


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


class TestRunNotifications:
    @pytest.mark.anyio
    async def test_a_budget_stop_is_reported_with_the_reason_it_gave(self):
        """A run stopped from Slack or a schedule ends silently otherwise, and
        the first anybody hears of the ceiling is somebody asking why the agent
        went quiet."""
        with patch("app.services.agent_runner.NotificationService") as notifications:
            notifications.return_value.budget_exceeded = AsyncMock()
            await AgentRunnerService(MagicMock())._notify(
                MagicMock(),
                agent=MagicMock(),
                spec=AgentSpec(name="Support"),
                status=RunStatus.BUDGET_EXCEEDED,
                error="Monthly budget exhausted",
                budget_scope=BudgetScope.ORGANIZATION,
            )

        kwargs = notifications.return_value.budget_exceeded.call_args.kwargs
        assert kwargs["reason"] == "Monthly budget exhausted"
        # Carried through, not re-derived: it decides whether the agent's own
        # audience is consulted or the organization's administrators are.
        assert kwargs["scope"] is BudgetScope.ORGANIZATION

    @pytest.mark.anyio
    async def test_a_parked_run_tells_somebody_which_tools_are_waiting(self):
        approvals = [
            MagicMock(tool_id="send_email", status=ApprovalStatus.PENDING.value),
            MagicMock(tool_id="already_decided", status=ApprovalStatus.APPROVED.value),
        ]
        run = MagicMock(id=uuid.uuid4(), organization_id=uuid.uuid4(), cost_usd=Decimal(0))

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=approvals),
            ),
            patch("app.services.agent_runner.NotificationService") as notifications,
        ):
            notifications.return_value.approval_requested = AsyncMock()
            await AgentRunnerService(MagicMock())._notify(
                run,
                agent=MagicMock(),
                spec=AgentSpec(name="Support"),
                status=RunStatus.AWAITING_APPROVAL,
                error=None,
                budget_scope=None,
            )

        # Only what is still waiting: naming a decided call would send somebody
        # to a queue with nothing in it.
        assert notifications.return_value.approval_requested.call_args.kwargs["tools"] == [
            "send_email"
        ]

    @pytest.mark.anyio
    async def test_an_ordinary_ending_notifies_nobody(self):
        with patch("app.services.agent_runner.NotificationService") as notifications:
            await AgentRunnerService(MagicMock())._notify(
                MagicMock(),
                agent=MagicMock(),
                spec=AgentSpec(name="Support"),
                status=RunStatus.COMPLETED,
                error=None,
                budget_scope=None,
            )

        notifications.return_value.budget_exceeded.assert_not_called()
        notifications.return_value.approval_requested.assert_not_called()
