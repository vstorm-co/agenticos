"""Reference discovery follows owned schemas, never value spelling or prose."""

from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.agents.capabilities import all_capabilities, load_builtins
from app.agents.spec import AgentSpec, CapabilityBindingSpec, OrgMcpServerRef, PersonalMcpServerRef
from app.schemas.resource_bundle import BundleResourceKind
from app.services.portability.references import _resolved, _shape, agent_pins, resource_pins


def test_agent_inventory_covers_top_level_and_nested_bindings_without_touching_prose() -> None:
    load_builtins()
    model, skill, kb, context, mcp, secret, sandbox, browser, follow, workflow = [
        uuid4() for _ in range(10)
    ]
    spec = AgentSpec(
        name="Researcher",
        instructions=f"An external account is {skill}",
        model_profile_id=model,
        skill_ids=[skill],
        collection_ids=[kb],
        context_ids=[context],
        mcp_servers=[
            OrgMcpServerRef(connection_id=mcp, allowed_tools=[str(skill)], approval="all"),
            PersonalMcpServerRef(account="personal", catalog_key="notion"),
        ],
        capabilities=[
            CapabilityBindingSpec(
                id="sandbox",
                secret_id=secret,
                config={"connection_id": str(sandbox), "env": {"BUSINESS_ID": str(skill)}},
            ),
            CapabilityBindingSpec(id="browser_use", config={"step_model_profile_id": str(browser)}),
            CapabilityBindingSpec(id="follow_ups", config={"model_profile_id": str(follow)}),
            CapabilityBindingSpec(id="workflows", config={"workflow_ids": [str(workflow)]}),
        ],
    )
    pins = {(pin.path, pin.kind, pin.source_id) for pin in agent_pins(spec)}
    assert pins == {
        (("model_profile_id",), BundleResourceKind.MODEL_PROFILE, model),
        (("skill_ids", 0), BundleResourceKind.SKILL, skill),
        (("collection_ids", 0), BundleResourceKind.KNOWLEDGE_BASE, kb),
        (("context_ids", 0), BundleResourceKind.CONTEXT, context),
        (("mcp_servers", 0, "connection_id"), BundleResourceKind.MCP_CONNECTION, mcp),
        (("capabilities", 0, "secret_id"), BundleResourceKind.SECRET, secret),
        (
            ("capabilities", 0, "config", "connection_id"),
            BundleResourceKind.SANDBOX_CONNECTION,
            sandbox,
        ),
        (
            ("capabilities", 1, "config", "step_model_profile_id"),
            BundleResourceKind.MODEL_PROFILE,
            browser,
        ),
        (
            ("capabilities", 2, "config", "model_profile_id"),
            BundleResourceKind.MODEL_PROFILE,
            follow,
        ),
        (("capabilities", 3, "config", "workflow_ids", 0), BundleResourceKind.WORKFLOW, workflow),
    }


def test_union_discrimination_keeps_personal_accounts_without_an_organization_binding() -> None:
    load_builtins()
    connection = uuid4()
    spec = AgentSpec(
        name="Researcher",
        capabilities=[
            CapabilityBindingSpec(
                id="mirage",
                config={
                    "mounts": [
                        {
                            "path": "/personal/",
                            "backend": "notion",
                            "account": {"kind": "personal"},
                        },
                        {
                            "path": "/organization/",
                            "backend": "notion",
                            "account": {"kind": "organization", "connection_id": str(connection)},
                        },
                    ]
                },
            )
        ],
    )
    pins = agent_pins(spec)
    assert len(pins) == 1
    assert pins[0].path == ("capabilities", 0, "config", "mounts", 1, "account", "connection_id")
    assert pins[0].source_id == connection


def test_an_unmarked_uuid_is_a_schema_error_rather_than_a_guessed_resource() -> None:
    class Unmarked(BaseModel):
        id: UUID

    with pytest.raises(ValueError, match="x-resource"):
        resource_pins(Unmarked(id=uuid4()))


def test_resource_metadata_requires_uuid_strings_not_untyped_identifiers() -> None:
    class InvalidResource(BaseModel):
        value: int = Field(json_schema_extra={"x-resource": "skill"})

    with pytest.raises(TypeError, match="UUID strings"):
        resource_pins(InvalidResource(value=42))


def test_unknown_resource_metadata_is_not_silently_ignored() -> None:
    class UnknownResource(BaseModel):
        value: UUID = Field(json_schema_extra={"x-resource": "not_registered"})

    with pytest.raises(ValueError, match="not_registered"):
        resource_pins(UnknownResource(value=uuid4()))


def test_invalid_schema_references_and_discriminators_do_not_trigger_remote_resolution() -> None:
    with pytest.raises(ValueError, match="local definition"):
        _resolved({"$ref": "https://example.com/schema"}, {})
    with pytest.raises(ValueError, match="local definition"):
        _resolved({"$ref": "#/$defs/Missing"}, {})
    with pytest.raises(ValueError, match="any declared schema branch"):
        _shape(
            {"oneOf": [{"type": "null"}, {"properties": {"kind": {"const": "organization"}}}]},
            {},
            {"kind": "personal"},
        )


def test_all_owned_uuid_fields_declare_their_resource_kind() -> None:
    load_builtins()
    schemas = [
        AgentSpec.model_json_schema(),
        *(c.config_schema.model_json_schema() for c in all_capabilities() if c.config_schema),
    ]

    def check(value: JsonValue, *, marked: bool = False) -> None:
        if isinstance(value, dict):
            marked = marked or isinstance(value.get("x-resource"), str)
            if value.get("format") == "uuid":
                assert marked, f"An owned UUID field has no resource metadata: {value}"
            for key, item in value.items():
                check(item, marked=False if key in ("$defs", "properties") else marked)
        elif isinstance(value, list):
            for item in value:
                check(item, marked=marked)

    for schema in schemas:
        check(schema)


def test_dictionary_values_and_context_keys_retain_their_reference_location() -> None:
    load_builtins()
    context, secret = uuid4(), uuid4()
    spec = AgentSpec(
        name="Researcher",
        context_ids=[context],
        capabilities=[
            CapabilityBindingSpec(
                id="context", config={"file_settings": {str(context): {"mode": "link"}}}
            ),
            CapabilityBindingSpec(
                id="mirage", config={"mounts": [{"secrets": {"app": str(secret)}}]}
            ),
            CapabilityBindingSpec(id="charts"),
        ],
    )
    pins = agent_pins(spec)
    assert any(
        pin.is_key and pin.source_id == context and pin.kind == BundleResourceKind.CONTEXT
        for pin in pins
    )
    assert any(
        pin.path == ("capabilities", 1, "config", "mounts", 0, "secrets", "app")
        and pin.source_id == secret
        for pin in pins
    )


def test_dictionary_keys_without_resource_metadata_are_rejected() -> None:
    class UnmarkedKeys(BaseModel):
        data: dict[UUID, str]

    with pytest.raises(ValueError, match="dictionary keys"):
        resource_pins(UnmarkedKeys(data={uuid4(): "text"}))


def test_a_capability_shaped_schema_cannot_omit_the_capability_identity() -> None:
    class MissingCapabilityIdentity(BaseModel):
        model_config = ConfigDict(title="CapabilityBindingSpec")
        config: dict[str, str] = Field(default_factory=dict)

    with pytest.raises(TypeError, match="declare its id"):
        resource_pins(MissingCapabilityIdentity())


def test_versioned_pins_keep_their_owner_and_shared_references_are_not_duplicated() -> None:
    from app.agents.spec import SkillBindingSpec, SubagentRef
    from app.services.portability.snapshots import agent_snapshot

    agent, version, skill, fork = [uuid4() for _ in range(4)]
    spec = AgentSpec(
        name="Researcher",
        skill_ids=[skill],
        skill_bindings=[SkillBindingSpec(skill_id=skill, fork_id=fork)],
        subagents=[SubagentRef(agent_id=agent, agent_version_id=version)],
    )
    pins = agent_pins(spec)
    assert next(p for p in pins if p.source_id == version).parent_id == agent
    assert next(p for p in pins if p.source_id == fork).parent_id == skill
    bundle = agent_snapshot(spec)
    entries = {entry.key: entry for entry in bundle.resources}
    assert len([entry for entry in entries.values() if entry.kind == BundleResourceKind.SKILL]) == 1
    assert entries[f"agent_version/{version}"].source_parent_id == agent
    assert entries[f"skill_fork/{fork}"].source_parent_id == skill
    assert AgentSpec.model_validate(bundle.resources[0].definition) == spec


def test_agent_snapshot_keeps_self_references_as_edges_to_the_root() -> None:
    from app.agents.spec import SubagentRef
    from app.services.portability.snapshots import agent_snapshot

    source = uuid4()
    spec = AgentSpec(
        name="Researcher", subagents=[SubagentRef(agent_id=source, agent_version_id=uuid4())]
    )
    snapshot = agent_snapshot(spec, source_id=source)
    assert (
        len([entry for entry in snapshot.resources if entry.kind == BundleResourceKind.AGENT]) == 1
    )
    assert snapshot.resources[0].references[0].target == snapshot.roots[0]


def test_one_version_cannot_be_claimed_under_different_source_agents() -> None:
    from app.agents.spec import SubagentRef
    from app.services.portability.snapshots import agent_snapshot

    version = uuid4()
    spec = AgentSpec(
        name="Researcher",
        subagents=[
            SubagentRef(agent_id=uuid4(), agent_version_id=version),
            SubagentRef(agent_id=uuid4(), agent_version_id=version),
        ],
    )
    with pytest.raises(ValueError, match="two different owners"):
        agent_snapshot(spec)


def test_an_owned_version_reference_requires_its_declared_parent() -> None:
    class MissingParent(BaseModel):
        value: UUID = Field(
            json_schema_extra={"x-resource": "agent_version", "x-resource-parent": "agent_id"}
        )

    with pytest.raises(TypeError, match="owning resource"):
        resource_pins(MissingParent(value=uuid4()))


def test_main_skill_version_numbers_get_distinct_bundle_identities() -> None:
    from app.agents.spec import SkillBindingSpec
    from app.services.portability.snapshots import agent_snapshot

    skill = uuid4()
    spec = AgentSpec(
        name="Researcher",
        skill_ids=[skill],
        skill_bindings=[SkillBindingSpec(skill_id=skill, version=3)],
    )
    snapshot = agent_snapshot(spec)
    version_key = f"skill_version/{skill}-v3"
    version = next(entry for entry in snapshot.resources if entry.key == version_key)
    assert version.source_id is None
    assert version.source_parent_id == skill
    assert version.source_version == "3"
    pin = next(
        reference
        for reference in snapshot.resources[0].references
        if reference.target == version_key
    )
    assert pin.destination_field == "version_number"


@pytest.mark.parametrize("number", [0, -1])
def test_numbered_resources_must_have_a_valid_owner_and_positive_version(number: int) -> None:
    class InvalidVersion(BaseModel):
        skill_id: UUID = Field(json_schema_extra={"x-resource": "skill"})
        version: int = Field(
            json_schema_extra={"x-resource": "skill_version", "x-resource-parent": "skill_id"}
        )

    with pytest.raises(ValueError, match="positive number"):
        resource_pins(InvalidVersion(skill_id=uuid4(), version=number))


def test_a_number_without_a_declared_owner_cannot_name_a_resource() -> None:
    class UnscopedVersion(BaseModel):
        version: int = Field(json_schema_extra={"x-resource": "skill_version"})

    with pytest.raises(ValueError, match="owner"):
        resource_pins(UnscopedVersion(version=3))


def test_incomplete_internal_reference_identities_are_not_serialized_as_valid_keys() -> None:
    from app.services.portability.references import ResourcePin

    pin = ResourcePin(path=("version",), kind=BundleResourceKind.SKILL_VERSION, source_id=None)
    with pytest.raises(ValueError, match="owner and version"):
        result = pin.bundle_key
        pytest.fail(f"Invalid reference received a key: {result}")
