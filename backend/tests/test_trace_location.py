"""Where a run's trace went, and whether that is enough to open it.

`agent_runs.logfire_trace_id` existed from the baseline and was never written, so
the API promised a deep link it had never once delivered. Filling it is only half
of one: a Logfire URL needs a project, and the only thing the platform ever holds
is a *write* token, which carries no project name.

So the two travel together, and the tests below are mostly about the ways they
could come apart - a trace id for a trace that was never exported, or a project
slug belonging to somewhere else's traces.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import logfire
import pytest
from opentelemetry import trace

from app.agents.observability import TraceLocation, current_trace_id, trace_location
from app.agents.spec import AgentSpec, ObservabilitySpec
from app.core.config import settings


@pytest.fixture
def inside_a_span():
    """A real OpenTelemetry span, because the id under test is OpenTelemetry's.

    Faking `get_current_span` would prove the formatting and nothing about where
    the id comes from - and the id a Logfire URL wants is the OTel trace id,
    which several things other than Logfire may have started.
    """
    with logfire.span("a run"):
        yield trace.get_current_span().get_span_context()


def _redirected(project: str | None) -> AgentSpec:
    """An agent whose traces go to a Logfire project of its own."""
    return AgentSpec(
        name="Support",
        observability=ObservabilitySpec(token_secret_id=uuid.uuid4(), project=project),
    )


class TestReadingTheTraceId:
    def test_the_id_is_the_thirty_two_hex_characters_a_logfire_url_wants(self, inside_a_span):
        found = current_trace_id()

        assert found == format(inside_a_span.trace_id, "032x")
        assert len(found) == 32
        assert int(found, 16) == inside_a_span.trace_id

    def test_outside_any_span_there_is_no_id(self):
        """OpenTelemetry answers with an invalid context whose trace id is zero.
        `"000...0"` in the column would be an id that resolves to nothing - the
        same lie as the null it replaces, written the other way round."""
        assert current_trace_id() is None


class TestWhereToRecordItAsGoing:
    """Four outcomes, and each of them is somebody's real deployment."""

    def test_an_agent_with_its_own_project_records_both(self, inside_a_span):
        located = trace_location(_redirected("client-org/client-traces"))

        assert located == TraceLocation(
            trace_id=format(inside_a_span.trace_id, "032x"),
            project="client-org/client-traces",
        )

    def test_a_deployment_with_a_token_and_a_slug_records_both(self, inside_a_span):
        with (
            patch.object(settings, "LOGFIRE_TOKEN", "pylf_v1_eu_secret"),
            patch.object(settings, "LOGFIRE_PROJECT", "vstorm/agenticos"),
        ):
            located = trace_location(AgentSpec(name="Support"))

        assert located.trace_id == format(inside_a_span.trace_id, "032x")
        assert located.project == "vstorm/agenticos"

    def test_a_token_with_no_slug_still_records_the_id(self, inside_a_span):
        """The trace is real and somebody with Logfire access can find it. The
        missing link is a configuration fact, not a lie in the schema."""
        with (
            patch.object(settings, "LOGFIRE_TOKEN", "pylf_v1_eu_secret"),
            patch.object(settings, "LOGFIRE_PROJECT", None),
        ):
            located = trace_location(AgentSpec(name="Support"))

        assert located.trace_id is not None
        assert located.project is None

    def test_a_deployment_with_no_logfire_records_nothing(self, inside_a_span):
        """Spans exist whether or not there is a token - `if-token-present` builds
        them and drops them - so an id read off the span here would name a trace
        that was never exported anywhere."""
        with patch.object(settings, "LOGFIRE_TOKEN", None):
            assert trace_location(AgentSpec(name="Support")) == TraceLocation(None, None)

    def test_a_redirected_agent_never_borrows_the_deployments_slug(self, inside_a_span):
        """Its traces went to the token's project. The deployment's slug would
        link into a project they are not in, which is worse than no link."""
        with (
            patch.object(settings, "LOGFIRE_TOKEN", "pylf_v1_eu_secret"),
            patch.object(settings, "LOGFIRE_PROJECT", "vstorm/agenticos"),
        ):
            located = trace_location(_redirected(None))

        assert located.trace_id is not None
        assert located.project is None
