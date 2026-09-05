"""Tests for per-agent model settings and the capability that owns reasoning.

Two behaviours carry this feature, and both are invisible in a passing run until
they are not:

*Unset stays unset.* A field nobody chose must reach the provider as an absent
key, never as `null` and never as a default somebody invented on the way. A
reasoning model rejects `temperature` however it is spelled, so the difference
between "absent" and "null" is the difference between an agent and an error.

*Withdrawn settings do not break a stored agent.* `model_settings` used to
accept any key. A published spec that used one must still load, and one that
asked for thinking must still think.
"""

import logging
import uuid

import pytest
from pydantic import SecretStr, ValidationError
from pydantic_ai.capabilities import Thinking

from app.agents.capabilities import CapabilityBinding, build, get, load_builtins
from app.agents.capabilities.thinking import ThinkingConfig
from app.agents.factory import build_agent
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import SPEC_VERSION, AgentSpec, ModelSettingsSpec
from app.core.secret_kinds import ApiKeySecret

_ID = uuid.uuid4()
_OTHER_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def _builtins_loaded():
    load_builtins()


def _model_spec(params: dict | None = None) -> ModelRequestSpec:
    return ModelRequestSpec(
        profile_id=uuid.uuid4(),
        label="GPT-4.1 (prod)",
        provider="openai",
        model="gpt-4.1",
        params=params or {},
        credential=ResolvedCredential(
            provider="openai", secret=ApiKeySecret(api_key=SecretStr("sk-test-key"))
        ),
        fallbacks=[],
    )


def _built_settings(spec: AgentSpec, params: dict | None = None) -> dict:
    """What the model would actually be given for this spec."""
    settings = build_agent(
        spec, _model_spec(params), organization_id=uuid.uuid4()
    ).agent.model_settings
    assert settings is not None
    return dict(settings)


class TestUnsetStaysUnset:
    """The property every other decision here is arranged around."""

    def test_a_spec_that_chose_nothing_serialises_to_nothing(self):
        """`null` is not a value a provider can be told; absence is the only way to say it."""
        assert AgentSpec(name="x").model_dump(mode="json")["model_settings"] == {}

    def test_only_the_chosen_settings_are_serialised(self):
        spec = AgentSpec(name="x", model_settings={"temperature": 0.2})

        assert spec.model_dump(mode="json")["model_settings"] == {"temperature": 0.2}

    def test_an_unset_temperature_never_reaches_the_model(self):
        """The failure this whole shape exists for.

        Reasoning models reject `temperature` outright, so an agent whose author
        never touched the control must produce a request with no such key - not
        one carrying `null`, and not one carrying a default the platform picked.
        """
        assert "temperature" not in _built_settings(AgentSpec(name="x"))

    def test_an_unset_setting_does_not_blank_out_the_profiles(self):
        """The same `null` read the other way round: as an override of the profile."""
        settings = _built_settings(AgentSpec(name="x"), {"temperature": 0.1, "max_tokens": 100})

        assert settings == {"temperature": 0.1, "max_tokens": 100}

    def test_the_agent_is_the_more_specific_statement_of_intent(self):
        settings = _built_settings(
            AgentSpec(name="x", model_settings={"temperature": 0.9}),
            {"temperature": 0.1, "max_tokens": 100},
        )

        assert settings == {"temperature": 0.9, "max_tokens": 100}

    def test_every_setting_reaches_the_model_under_its_own_name(self):
        """Names mirror `ModelSettings`, so a mistyped one would be dropped silently."""
        chosen = {
            "temperature": 0.4,
            "top_p": 0.9,
            "max_tokens": 2048,
            "parallel_tool_calls": False,
            "timeout": 30.0,
        }

        assert _built_settings(AgentSpec(name="x", model_settings=chosen)) == chosen

    def test_a_setting_set_to_zero_is_not_mistaken_for_unset(self):
        """`temperature: 0` is the most deliberate value there is."""
        spec = AgentSpec(name="x", model_settings={"temperature": 0.0})

        assert spec.model_dump(mode="json")["model_settings"] == {"temperature": 0.0}
        assert _built_settings(spec)["temperature"] == 0.0

    def test_the_yaml_export_omits_what_nobody_chose(self):
        """A spec is read in a client's repository; empty keys are noise there too."""
        rendered = AgentSpec(name="x", model_settings={"temperature": 0.4}).to_yaml()

        assert "temperature: 0.4" in rendered
        assert "top_p" not in rendered


class TestRangesAreRefusedBeforeAnythingRuns:
    """A provider error mid-conversation is the failure these ranges replace."""

    @pytest.mark.parametrize(
        "settings",
        [
            {"temperature": 2.5},
            {"temperature": -0.1},
            {"top_p": 0.0},
            {"top_p": 1.5},
            {"max_tokens": 0},
            {"max_tokens": 10_000_000},
            {"timeout": 0.0},
            {"timeout": 6_000.0},
        ],
    )
    def test_a_value_outside_its_range_is_refused(self, settings: dict):
        with pytest.raises(ValidationError):
            AgentSpec(name="x", model_settings=settings)

    def test_a_setting_this_version_does_not_expose_is_refused_when_written_fresh(self):
        """`extra="forbid"` is what makes a typo fail rather than do nothing."""
        with pytest.raises(ValidationError):
            ModelSettingsSpec.model_validate({"temperatrue": 0.5})


class TestSpecsPublishedBeforeThisExisted:
    """`model_settings` was `dict[str, Any]`; those specs are still stored."""

    def _version_5(self, settings: dict) -> dict:
        return {"spec_version": 5, "name": "Support", "model_settings": settings}

    def test_a_withdrawn_setting_does_not_stop_the_spec_from_loading(self):
        """Refusing would be a 500 on every run of an agent nobody touched."""
        spec = AgentSpec.model_validate(
            self._version_5({"temperature": 0.3, "logit_bias": {"a": 1}})
        )

        assert spec.model_settings.temperature == 0.3

    def test_dropping_a_withdrawn_setting_is_logged(self, caplog):
        """It changes what the provider is sent, so it may not happen in silence."""
        with caplog.at_level("WARNING"):
            AgentSpec.model_validate(self._version_5({"seed": 7}))

        assert "seed" in caplog.text

    def test_a_spec_with_nothing_withdrawn_is_left_alone(self, caplog):
        with caplog.at_level("WARNING"):
            AgentSpec.model_validate(self._version_5({"temperature": 0.3}))

        assert caplog.text == ""

    def test_a_thinking_setting_becomes_a_binding_on_the_capability(self):
        """Dropped like the others, it would quietly stop an agent reasoning."""
        spec = AgentSpec.model_validate(self._version_5({"thinking": "high"}))

        assert [(c.id, c.config) for c in spec.capabilities] == [("thinking", {"effort": "high"})]

    def test_thinking_enabled_without_a_level_asks_for_the_providers_default(self):
        spec = AgentSpec.model_validate(self._version_5({"thinking": True}))

        assert [(c.id, c.config) for c in spec.capabilities] == [("thinking", {})]

    def test_thinking_turned_off_binds_nothing(self):
        """Not binding the capability is how this version says "do not think"."""
        assert AgentSpec.model_validate(self._version_5({"thinking": False})).capabilities == []

    def test_an_explicit_binding_wins_over_the_migrated_one(self):
        """Otherwise re-reading a migrated spec would bind the capability twice."""
        spec = AgentSpec.model_validate(
            {
                **self._version_5({"thinking": "high"}),
                "capabilities": [{"id": "thinking", "config": {"effort": "low"}}],
            }
        )

        assert [(c.id, c.config) for c in spec.capabilities] == [("thinking", {"effort": "low"})]

    def test_a_migrated_spec_round_trips_through_yaml(self):
        spec = AgentSpec.model_validate(self._version_5({"thinking": "low", "top_k": 40}))

        assert AgentSpec.from_yaml(spec.to_yaml()) == spec

    def test_the_version_records_that_the_shape_changed(self):
        """A literal on purpose: this is the tripwire for a shape change nobody
        bumped, so it has to fail when the constant moves rather than follow it.
        8 added `observability.organization` and `observability.project` (#206);
        9 added `context_ids` (#48); 10 turned `mcp_server_ids` into
        `mcp_servers` (#1341); 11 made whose account a binding speaks through
        its kind, `account`, rather than a flag on it."""
        assert AgentSpec(name="x").spec_version == SPEC_VERSION == 11

    def test_a_version_9_spec_loads_its_mcp_ids_as_bindings(self):
        """`extra="forbid"` would otherwise refuse every stored spec that names
        an MCP server - a 500 on every run of something nobody touched."""
        spec = AgentSpec.model_validate({"name": "x", "mcp_server_ids": [str(_ID), str(_OTHER_ID)]})

        assert [(ref.account, ref.connection_id) for ref in spec.mcp_servers] == [
            ("organization", _ID),
            ("organization", _OTHER_ID),
        ]

    def test_the_migrated_field_does_not_survive_into_the_spec(self):
        """Left in place it would fail `extra="forbid"` on the way back in."""
        spec = AgentSpec.model_validate({"name": "x", "mcp_server_ids": [str(_ID)]})

        assert AgentSpec.from_yaml(spec.to_yaml()) == spec

    def test_an_explicit_binding_wins_over_the_legacy_ids(self):
        """Re-reading a spec this already migrated changes nothing."""
        spec = AgentSpec.model_validate(
            {
                "name": "x",
                "mcp_server_ids": [str(_OTHER_ID)],
                "mcp_servers": [{"account": "organization", "connection_id": str(_ID)}],
            }
        )

        assert [ref.connection_id for ref in spec.mcp_servers] == [_ID]

    def test_a_version_10_binding_loads_as_an_organization_binding(self):
        """Version 11 discriminates a binding on `account`, which a stored
        version-10 document does not carry. The tag is supplied rather than the
        document refused - a 500 on every run of something nobody touched."""
        spec = AgentSpec.model_validate(
            {"name": "x", "mcp_servers": [{"connection_id": str(_ID), "allowed_tools": ["search"]}]}
        )

        assert [
            (ref.account, ref.connection_id, ref.allowed_tools) for ref in spec.mcp_servers
        ] == [("organization", _ID, ["search"])]

    def test_the_withdrawn_substitution_flag_is_dropped_and_said_so(self, caplog):
        """`use_personal_when_available` substituted a credential in private
        conversations. Its replacement is a different *kind* of binding, and
        choosing that for somebody is not a migration's call - so the binding
        loads as the organization's, and the log says what to bind instead."""
        with caplog.at_level(logging.WARNING, logger="app.agents.spec"):
            spec = AgentSpec.model_validate(
                {
                    "name": "x",
                    "mcp_servers": [
                        {"connection_id": str(_ID), "use_personal_when_available": True}
                    ],
                }
            )

        assert [(ref.account, ref.connection_id) for ref in spec.mcp_servers] == [
            ("organization", _ID)
        ]
        assert "account: personal" in caplog.text
        assert AgentSpec.from_yaml(spec.to_yaml()) == spec

    def test_a_flag_that_was_off_is_dropped_quietly(self, caplog):
        """Off was the default, so nothing about the binding changes."""
        with caplog.at_level(logging.WARNING, logger="app.agents.spec"):
            AgentSpec.model_validate(
                {
                    "name": "x",
                    "mcp_servers": [
                        {"connection_id": str(_ID), "use_personal_when_available": False}
                    ],
                }
            )

        assert "use_personal_when_available" not in caplog.text

    def test_a_personal_binding_names_a_service_and_no_connection(self):
        spec = AgentSpec.model_validate(
            {"name": "x", "mcp_servers": [{"account": "personal", "catalog_key": "notion"}]}
        )

        assert [(ref.account, ref.catalog_key) for ref in spec.mcp_servers] == [
            ("personal", "notion")
        ]
        assert AgentSpec.from_yaml(spec.to_yaml()) == spec

    def test_a_personal_binding_carrying_a_connection_id_is_refused(self):
        """The two kinds are `extra="forbid"` each, so a document that mixes
        their fields is named rather than half-read."""
        with pytest.raises(ValidationError):
            AgentSpec.model_validate(
                {
                    "name": "x",
                    "mcp_servers": [
                        {"account": "personal", "catalog_key": "notion", "connection_id": str(_ID)}
                    ],
                }
            )

    def test_a_binding_that_is_not_a_mapping_is_named_by_validation(self):
        with pytest.raises(ValidationError):
            AgentSpec.model_validate({"name": "x", "mcp_servers": ["notion"]})

    def test_legacy_ids_that_are_not_a_list_are_refused(self):
        """Left in place rather than dropped, so validation names the field.

        This test used to assert the opposite - that the field was removed and
        the spec loaded with no bindings - which is what the code did and is a
        silent discard of what the author was binding. Imported YAML saying
        `mcp_server_ids: <uuid>` published happily having thrown the server
        away, where the old schema had reported it.
        """
        with pytest.raises(ValidationError):
            AgentSpec.model_validate({"name": "x", "mcp_server_ids": None})

    def test_a_malformed_legacy_field_is_refused_even_beside_a_good_binding(self):
        """A value this wrong is a mistake worth naming, not one to ignore
        because another field happens to say something valid."""
        with pytest.raises(ValidationError):
            AgentSpec.model_validate(
                {
                    "name": "x",
                    "mcp_server_ids": str(_ID),
                    "mcp_servers": [{"connection_id": str(_ID)}],
                }
            )

    def test_a_spec_that_is_not_a_mapping_is_left_to_pydantic(self):
        """The migration must not swallow a malformed document."""
        with pytest.raises(ValidationError):
            AgentSpec.model_validate(["not", "a", "spec"])

    def test_a_model_settings_value_that_is_not_a_mapping_is_left_to_pydantic(self):
        with pytest.raises(ValidationError):
            AgentSpec.model_validate({"name": "x", "model_settings": "temperature=0.5"})


class TestThinkingCapability:
    """Reasoning is composed like everything else an agent is given."""

    def test_it_is_in_the_catalog_the_builder_renders(self):
        definition = get("thinking")

        assert (definition.id, definition.tools) == ("thinking", ())
        assert definition.config_schema is ThinkingConfig

    def test_the_effort_levels_are_offered_as_an_enumeration(self):
        """The Builder's form is generated from this; a free-text box would not do."""
        schema = get("thinking").config_json_schema()

        assert schema is not None
        assert schema["properties"]["effort"]["anyOf"][0]["enum"] == [
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
        ]

    def test_a_level_reaches_pydantic_ais_own_capability(self):
        (built,) = build([CapabilityBinding(capability_id="thinking", config={"effort": "high"})])

        assert isinstance(built, Thinking)
        assert built.effort == "high"

    def test_binding_it_without_a_level_asks_for_the_providers_default(self):
        """`True` is the unified setting's "on, at whatever this provider defaults to"."""
        (built,) = build([CapabilityBinding(capability_id="thinking")])

        assert isinstance(built, Thinking)
        assert built.effort is True

    def test_a_level_no_provider_has_is_refused_at_publish(self):
        with pytest.raises(ValidationError):
            ThinkingConfig(effort="enormous")  # ty: ignore[invalid-argument-type]

    def test_it_writes_the_portable_setting_rather_than_a_providers_own(self):
        """What makes an agent survive being repointed at another model."""
        settings = Thinking(effort="low").get_model_settings()

        assert settings == {"thinking": "low"}
