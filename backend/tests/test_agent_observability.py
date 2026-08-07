"""Per-agent Logfire: whose project a run's traces land in.

The property worth pinning is not that Logfire works - that is Logfire's
problem. It is that an agent with no observability block is left alone, that a
token which has gone missing does not stop the agent running, and that the
write token never leaves the vault path it came in on.
"""

import uuid
from unittest.mock import MagicMock, patch

from app.agents.factory import _instrument
from app.agents.spec import AgentSpec, ObservabilitySpec
from app.core.secret_kinds import ApiKeySecret

MODULE = "app.agents.factory"


def _secret(token: str = "pylf_v1_eu_secret") -> ApiKeySecret:
    return ApiKeySecret(api_key=token)


class TestInstrumentation:
    def test_an_agent_that_asked_for_nothing_is_left_on_the_deployment_config(self):
        """The default, and the one that must stay free: no per-agent exporter."""
        agent = MagicMock()
        with patch(f"{MODULE}.instrument_agent") as instrument:
            _instrument(agent, AgentSpec(name="a"), {}, agent_id=None)

        instrument.assert_not_called()

    def test_the_agents_own_token_and_environment_are_used(self):
        secret_id = uuid.uuid4()
        spec = AgentSpec(
            name="Support",
            observability=ObservabilitySpec(
                token_secret_id=secret_id, service_name="acme-support", environment="production"
            ),
        )
        agent = MagicMock()

        with patch(f"{MODULE}.instrument_agent") as instrument:
            _instrument(agent, spec, {secret_id: _secret()}, agent_id=uuid.uuid4())

        kwargs = instrument.call_args.kwargs
        assert kwargs["token"] == "pylf_v1_eu_secret"
        assert kwargs["service_name"] == "acme-support"
        assert kwargs["environment"] == "production"

    def test_the_agent_names_itself_when_no_service_name_was_given(self):
        """A blank service name in Logfire is a project nobody can read."""
        secret_id = uuid.uuid4()
        spec = AgentSpec(name="Support", observability=ObservabilitySpec(token_secret_id=secret_id))

        with patch(f"{MODULE}.instrument_agent") as instrument:
            _instrument(MagicMock(), spec, {secret_id: _secret()}, agent_id=None)

        assert instrument.call_args.kwargs["service_name"] == "Support"

    def test_a_secret_deleted_after_publish_leaves_the_agent_running(self):
        """The alternative is an agent that stops answering because a trace
        destination went away, which is the observability tail wagging the dog."""
        spec = AgentSpec(name="a", observability=ObservabilitySpec(token_secret_id=uuid.uuid4()))

        with patch(f"{MODULE}.instrument_agent") as instrument:
            _instrument(MagicMock(), spec, {}, agent_id=None)

        instrument.assert_not_called()


class TestSpec:
    def test_the_token_is_stored_as_a_reference_never_a_value(self):
        """A spec is exported as YAML into somebody's repository. A write token
        in a checked-in file is a token that has to be rotated."""
        assert "token" not in {
            field for field in ObservabilitySpec.model_fields if field != "token_secret_id"
        }

    def test_an_unknown_key_is_refused(self):
        # `extra="forbid"`, like every other block: a misspelled field that is
        # silently accepted is a setting somebody believes is on.
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            # `project` used to stand in for an unknown key here and is now a real
            # field - where a client's traces can be *read*, which a write token
            # does not say (#206). A plausible wrong name for it is the better
            # example anyway: that is what somebody actually types.
            ObservabilitySpec(project_slug="acme")  # ty: ignore[unknown-argument]

    def test_a_slug_that_would_escape_the_url_is_refused(self):
        """`organization` and `project` are interpolated into a Logfire URL path
        when a run's trace link is built, so a value with a slash or a query
        character would point the link somewhere other than the project. A length
        bound does not stop that; the slug pattern does."""
        import pytest
        from pydantic import ValidationError

        for bad in ["../evil", "acme/prod", "acme?x=1", "Acme Corp", "acme_prod"]:
            with pytest.raises(ValidationError):
                ObservabilitySpec(organization=bad)
            with pytest.raises(ValidationError):
                ObservabilitySpec(project=bad)

    def test_an_ordinary_slug_is_accepted(self):
        spec = ObservabilitySpec(organization="vstorm", project="agenticos-eu")
        assert (spec.organization, spec.project) == ("vstorm", "agenticos-eu")
