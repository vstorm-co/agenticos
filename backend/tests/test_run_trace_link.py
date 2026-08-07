"""The trace id on a run, and the link into it.

`AgentRunRead.logfire_trace_id` was documented as *"Deep-link into the full
trace"* and was null on every row ever written. `finish()` took the id as a
parameter, `finish_run` wrote it `if logfire_trace_id is not None`, and no caller
passed one - so the guard was always false and the public API promised a
capability it had never delivered (#206).

Two halves, and they fail differently. The id is now read inside `finish`, which
is reached from a `finally` on every surface - so the tests below care most about
the run that *ended badly*, since that is the one somebody wants a trace for. The
link is resolved per run rather than per deployment, because `ObservabilitySpec`
exists to send one agent's traces to a client's own project, and a URL built from
the deployment's slugs would point at a project that does not contain the run.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry import trace

from app.agents.observability import current_trace_id
from app.agents.spec import AgentSpec, ObservabilitySpec
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import RunStatus
from app.services.agent_runner import AgentRunnerService

pytestmark = pytest.mark.anyio

MODULE = "app.services.agent_runner"


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


class TestReadingTheTraceIdOffTheCurrentSpan:
    def test_a_deployment_that_is_not_tracing_records_no_id(self):
        """OpenTelemetry answers with an all-zero context when nothing is tracing.
        Formatting it would store `000…0` and every link built from it would
        resolve to nothing, which is worse than an empty column."""
        assert current_trace_id() is None

    def test_inside_a_span_the_id_is_thirty_two_hex_characters(self):
        """The W3C trace-id format, and what Logfire puts in a URL."""
        tracer = trace.get_tracer_provider().get_tracer(__name__)
        with tracer.start_as_current_span("a run"):
            recorded = current_trace_id()

        if recorded is None:  # pragma: no cover - no SDK installed in this env
            pytest.skip("no tracer provider is recording in this environment")
        assert len(recorded) == 32
        assert recorded == recorded.lower()
        assert int(recorded, 16) != 0


class TestTheIdIsWrittenHoweverTheRunEnded:
    @staticmethod
    def _prepared() -> MagicMock:
        prepared = MagicMock()
        prepared.run = MagicMock(id=uuid.uuid4(), conversation_id=None)
        prepared.built.ledger = MagicMock(
            input_tokens=10,
            output_tokens=2,
            total_usd=Decimal("0.01"),
            has_unpriced_models=False,
        )
        prepared.approvals.requested = []
        prepared.delegations = []
        return prepared

    @pytest.mark.parametrize(
        "status",
        [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.BUDGET_EXCEEDED],
        ids=lambda status: status.value,
    )
    async def test_every_ending_records_the_trace(self, status):
        """`finish` is reached from a `finally` on every surface, which is exactly
        why the id is read here rather than passed in by each caller. A run that
        ended `failed` is the one somebody opens Logfire for."""
        service = AgentRunnerService(MagicMock(commit=AsyncMock()))
        prepared = self._prepared()

        with (
            patch(f"{MODULE}.current_trace_id", return_value="a" * 32),
            patch(f"{MODULE}.agent_run_repo.finish_run", new=AsyncMock()) as finish,
            patch.object(service, "_collect_outbound", new=AsyncMock()),
            patch.object(service, "_propose_skill_changes", new=AsyncMock()),
            patch.object(service, "_write_approvals", new=AsyncMock()),
            patch.object(service, "_write_delegations", new=AsyncMock()),
            patch.object(service, "_notify", new=AsyncMock()),
            patch.object(service.workspaces, "close", new=AsyncMock()),
        ):
            await service.finish(prepared, status=status)

        assert finish.await_args.kwargs["logfire_trace_id"] == "a" * 32


class TestWhereTheTraceCanBeRead:
    @staticmethod
    def _run(**overrides) -> SimpleNamespace:
        row = {"logfire_trace_id": "b" * 32, "agent_version_id": None}
        row.update(overrides)
        return SimpleNamespace(**row)

    @staticmethod
    def _version(stored: object) -> SimpleNamespace:
        """A stored version row. `MagicMock(spec=...)` cannot be used: `spec` is
        the constructor's own keyword, so it would configure the mock rather than
        set an attribute."""
        return SimpleNamespace(spec=stored)

    async def test_the_deployments_slugs_build_the_link(self):
        service = AgentRunnerService(MagicMock())

        with patch(f"{MODULE}.settings") as configured:
            configured.LOGFIRE_ORGANIZATION = "vstorm"
            configured.LOGFIRE_PROJECT = "agenticos"
            configured.LOGFIRE_BASE_URL = "https://logfire-us.pydantic.dev"
            url = await service.trace_url(_ctx(), self._run())

        assert url == (
            "https://logfire-us.pydantic.dev/vstorm/agenticos?q=trace_id%3D%27" + "b" * 32 + "%27"
        )

    async def test_a_trailing_slash_on_the_base_url_does_not_double(self):
        service = AgentRunnerService(MagicMock())

        with patch(f"{MODULE}.settings") as configured:
            configured.LOGFIRE_ORGANIZATION = "vstorm"
            configured.LOGFIRE_PROJECT = "agenticos"
            configured.LOGFIRE_BASE_URL = "https://logfire-eu.pydantic.dev/"
            url = await service.trace_url(_ctx(), self._run())

        assert url is not None
        assert url.startswith("https://logfire-eu.pydantic.dev/vstorm/agenticos?")

    async def test_no_slugs_configured_means_no_link_rather_than_a_broken_one(self):
        """A `LOGFIRE_TOKEN` is a write credential and carries neither slug, so a
        deployment can trace successfully and still have nowhere to link. The id
        stays on the row: it is useful to anybody with Logfire access."""
        service = AgentRunnerService(MagicMock())

        with patch(f"{MODULE}.settings") as configured:
            configured.LOGFIRE_ORGANIZATION = None
            configured.LOGFIRE_PROJECT = None
            assert await service.trace_url(_ctx(), self._run()) is None

    async def test_an_organization_without_a_project_is_not_half_a_link(self):
        service = AgentRunnerService(MagicMock())

        with patch(f"{MODULE}.settings") as configured:
            configured.LOGFIRE_ORGANIZATION = "vstorm"
            configured.LOGFIRE_PROJECT = None
            assert await service.trace_url(_ctx(), self._run()) is None

    async def test_a_run_that_was_not_traced_has_nowhere_to_link(self):
        service = AgentRunnerService(MagicMock())

        with patch(f"{MODULE}.settings") as configured:
            configured.LOGFIRE_ORGANIZATION = "vstorm"
            configured.LOGFIRE_PROJECT = "agenticos"
            assert await service.trace_url(_ctx(), self._run(logfire_trace_id=None)) is None

    async def test_an_agent_that_redirects_its_traces_links_into_that_project(self):
        """The whole reason `ObservabilitySpec` exists: a client's agent traces
        into the client's own project. A link built from the deployment's slugs
        would point at a project that does not contain this run."""
        service = AgentRunnerService(MagicMock())
        version = self._version(
            {"observability": {"organization": "acme", "project": "assistants"}}
        )

        with (
            patch(f"{MODULE}.settings") as configured,
            patch(f"{MODULE}.agent_repo.get_version", new=AsyncMock(return_value=version)),
        ):
            configured.LOGFIRE_ORGANIZATION = "vstorm"
            configured.LOGFIRE_PROJECT = "agenticos"
            configured.LOGFIRE_BASE_URL = "https://logfire-us.pydantic.dev"
            url = await service.trace_url(_ctx(), self._run(agent_version_id=uuid.uuid4()))

        assert url is not None
        assert "/acme/assistants?" in url
        assert "vstorm" not in url

    async def test_an_agent_that_names_a_token_but_no_slugs_offers_no_link(self):
        """A client hands over a write token, not their organization slug. Falling
        back to the deployment's would link into a project this run is not in -
        which is worse than no link, because it looks like it worked."""
        service = AgentRunnerService(MagicMock())
        version = self._version({"observability": {"token_secret_id": str(uuid.uuid4())}})

        with (
            patch(f"{MODULE}.settings") as configured,
            patch(f"{MODULE}.agent_repo.get_version", new=AsyncMock(return_value=version)),
        ):
            configured.LOGFIRE_ORGANIZATION = "vstorm"
            configured.LOGFIRE_PROJECT = "agenticos"
            configured.LOGFIRE_BASE_URL = "https://logfire-us.pydantic.dev"
            url = await service.trace_url(_ctx(), self._run(agent_version_id=uuid.uuid4()))

        # The agent redirects nothing readable, so the deployment's slugs stand.
        assert url is not None
        assert "/vstorm/agenticos?" in url

    @pytest.mark.parametrize(
        "stored",
        [{}, {"observability": None}, {"observability": "production"}],
        ids=["no block", "null block", "not a mapping"],
    )
    async def test_a_spec_with_no_readable_observability_block_falls_back(self, stored):
        service = AgentRunnerService(MagicMock())

        with (
            patch(f"{MODULE}.settings") as configured,
            patch(
                f"{MODULE}.agent_repo.get_version",
                new=AsyncMock(return_value=self._version(stored)),
            ),
        ):
            configured.LOGFIRE_ORGANIZATION = "vstorm"
            configured.LOGFIRE_PROJECT = "agenticos"
            configured.LOGFIRE_BASE_URL = "https://logfire-us.pydantic.dev"
            url = await service.trace_url(_ctx(), self._run(agent_version_id=uuid.uuid4()))

        assert url is not None

    async def test_a_spec_whose_observability_block_no_longer_validates_falls_back(self, caplog):
        """The agent whose spec has stopped building is exactly the one somebody is
        trying to read a trace for. Refusing the link would make a debugging aid
        fail on the runs that need debugging."""
        service = AgentRunnerService(MagicMock())
        version = self._version({"observability": {"organization": "x" * 200}})

        with (
            patch(f"{MODULE}.settings") as configured,
            patch(f"{MODULE}.agent_repo.get_version", new=AsyncMock(return_value=version)),
        ):
            configured.LOGFIRE_ORGANIZATION = "vstorm"
            configured.LOGFIRE_PROJECT = "agenticos"
            configured.LOGFIRE_BASE_URL = "https://logfire-us.pydantic.dev"
            url = await service.trace_url(_ctx(), self._run(agent_version_id=uuid.uuid4()))

        assert url is not None
        assert "run_trace_observability_unreadable" in caplog.text

    async def test_a_version_that_has_been_deleted_falls_back(self):
        service = AgentRunnerService(MagicMock())

        with (
            patch(f"{MODULE}.settings") as configured,
            patch(f"{MODULE}.agent_repo.get_version", new=AsyncMock(return_value=None)),
        ):
            configured.LOGFIRE_ORGANIZATION = "vstorm"
            configured.LOGFIRE_PROJECT = "agenticos"
            configured.LOGFIRE_BASE_URL = "https://logfire-us.pydantic.dev"
            url = await service.trace_url(_ctx(), self._run(agent_version_id=uuid.uuid4()))

        assert url is not None


class TestTheSpecCarriesTheSlugs:
    def test_a_stored_spec_written_before_this_still_loads(self):
        """The whole cost of the bump. Both fields are optional with a default, so
        a document that predates them takes `None` and nothing needs migrating."""
        spec = AgentSpec.model_validate(
            {
                "name": "Clerk",
                "instructions": "Answer questions.",
                "model_profile_id": str(uuid.uuid4()),
                "observability": {"service_name": "clerk", "environment": "production"},
            }
        )

        assert spec.observability is not None
        assert (spec.observability.organization, spec.observability.project) == (None, None)

    def test_the_slugs_survive_a_yaml_round_trip(self):
        """A spec is exported into a client's repository and read back from it."""
        spec = AgentSpec(
            name="Clerk",
            instructions="Answer questions.",
            model_profile_id=uuid.uuid4(),
            observability=ObservabilitySpec(organization="acme", project="assistants"),
        )

        assert AgentSpec.from_yaml(spec.to_yaml()) == spec
