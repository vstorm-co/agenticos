"""Portable file parsing and declared references preserve data and refuse ambiguity."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.capabilities import load_builtins
from app.agents.spec import AgentSpec, OrgMcpServerRef
from app.core.exceptions import BadRequestError
from app.schemas.resource_bundle import (
    BundleContentLayer,
    BundleImportChoice,
    BundleResource,
    BundleResourceKind,
    BundleSelection,
    ResourceBundle,
)
from app.services.portability import documents
from app.services.portability.content import ContextContent
from app.services.portability.contracts import (
    agent_omissions,
    definition_model,
    owner_key,
    verify_references,
)
from app.services.portability.snapshots import agent_snapshot


@pytest.mark.parametrize("file_format", ["yaml", "json"])
def test_document_round_trip_keeps_exact_instructions_and_bindings(file_format: str) -> None:
    spec = AgentSpec(
        name="Researcher", instructions="  Keep indentation\n\n", context_ids=[uuid4()]
    )
    bundle = agent_snapshot(spec)
    encoded = documents.document_bytes(bundle, file_format)
    assert documents.parse_document(encoded.decode()) == bundle
    assert (
        documents.parse_document(spec.to_yaml()).resources[0].definition["instructions"]
        == spec.instructions
    )
    verify_references(bundle)


@pytest.mark.parametrize(
    "text",
    [
        "[invalid",
        "- an item",
        "instructions: !!python/object:bad {}",
        "name: &name Agent\ninstructions: *name",
        "name: Agent\nunknown: true",
    ],
)
def test_invalid_or_expanding_documents_have_safe_errors(text: str) -> None:
    with pytest.raises(BadRequestError) as exc:
        documents.parse_document(text)
    assert text not in str(exc.value.details)


def test_size_and_event_limits_are_checked_before_building_an_expanded_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(documents, "MAX_DOCUMENT_BYTES", 10)
    with pytest.raises(BadRequestError, match="4 MiB"):
        documents.parse_document("name: Researcher")
    monkeypatch.setattr(documents, "MAX_DOCUMENT_BYTES", 1000)
    monkeypatch.setattr(documents, "MAX_DOCUMENT_EVENTS", 2)
    with pytest.raises(BadRequestError, match="excessive"):
        documents.parse_document("name: Agent")


def test_recursive_parser_failure_is_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    def exhausted(*args: object, **kwargs: object) -> object:
        raise RecursionError

    monkeypatch.setattr(documents.yaml, "safe_load", exhausted)
    with pytest.raises(BadRequestError, match="valid YAML"):
        documents.parse_document("name: Agent")


def test_selection_drops_unselected_contents_but_preserves_reference_inventory() -> None:
    identity = uuid4()
    original = agent_snapshot(AgentSpec(name="Agent", context_ids=[identity]))
    context = original.resources[1].model_copy(
        update={
            "definition": ContextContent(name="Policy", content="private body").model_dump(
                mode="json"
            ),
            "included": frozenset({BundleContentLayer.DEFINITION}),
        }
    )
    bundle = original.model_copy(update={"resources": (original.resources[0], context)})
    selected = documents.select_content(
        bundle,
        BundleSelection(resources={original.roots[0]: frozenset({BundleContentLayer.DEFINITION})}),
    )
    assert selected.resources[1].definition is None
    assert selected.resources[1].references == ()
    assert selected.resources[0].references == original.resources[0].references
    assert "private body" not in documents.document_bytes(selected, "json").decode()
    assert bundle.resources[1].definition is not None


@pytest.mark.parametrize(
    "selection",
    [
        {},
        {"context/unknown": ["definition"]},
        {"agent/root": ["definition", "context_content"]},
        {"agent/root": ["context_content"]},
    ],
)
def test_invalid_selection_is_refused(selection: dict[str, list[str]]) -> None:
    with pytest.raises(BadRequestError):
        documents.select_content(
            agent_snapshot(AgentSpec(name="Agent")),
            BundleSelection.model_validate({"resources": selection}),
        )


@pytest.mark.parametrize(
    "choice",
    [
        {"action": "reuse"},
        {"action": "skip", "destination_id": str(uuid4())},
        {"action": "skip", "name": "Changed"},
    ],
)
def test_mapping_decisions_cannot_carry_conflicting_authority(choice: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        BundleImportChoice.model_validate(choice)


def test_uploaded_paths_and_kinds_cannot_rewrite_application_text() -> None:
    identity = uuid4()
    bundle = agent_snapshot(
        AgentSpec(name="Agent", instructions=str(identity), context_ids=[identity])
    )
    root, dependency = bundle.resources
    malicious = root.model_copy(
        update={"references": (root.references[0].model_copy(update={"path": ("instructions",)}),)}
    )
    with pytest.raises(BadRequestError, match="reference paths"):
        verify_references(bundle.model_copy(update={"resources": (malicious, dependency)}))
    wrong_kind = dependency.model_copy(update={"kind": BundleResourceKind.SECRET})
    with pytest.raises(BadRequestError, match="resource and version"):
        verify_references(bundle.model_copy(update={"resources": (root, wrong_kind)}))


def test_unsupported_and_invalid_definitions_are_refused_without_input_echoes() -> None:
    resource = BundleResource(key="context/test", kind=BundleResourceKind.CONTEXT, name="Context")
    with pytest.raises(BadRequestError, match="supported"):
        definition_model(resource)
    with pytest.raises(BadRequestError) as exc:
        definition_model(
            resource.model_copy(update={"definition": {"name": "", "content": "SECRET BODY"}})
        )
    assert "SECRET BODY" not in str(exc.value.details)


def test_skip_removes_a_whole_mcp_binding_without_rewriting_its_policy() -> None:
    load_builtins()
    spec = AgentSpec(
        name="Agent",
        mcp_servers=[
            OrgMcpServerRef(connection_id=uuid4(), allowed_tools=["read"], approval="all")
        ],
    )
    resource = agent_snapshot(spec).resources[0]
    assert agent_omissions(resource) == {("mcp_servers", 0, "connection_id"): ("mcp_servers", 0)}
    context = BundleResource(key="context/test", kind=BundleResourceKind.CONTEXT, name="Context")
    assert agent_omissions(context) == {}


def test_version_owner_must_be_declared_exactly_once() -> None:
    resource = BundleResource(
        key="skill_version/pin",
        kind=BundleResourceKind.SKILL_VERSION,
        name="Pinned",
        source_parent_id=uuid4(),
        source_version="3",
    )
    bundle = ResourceBundle(roots=(resource.key,), resources=(resource,))
    with pytest.raises(BadRequestError, match="owning"):
        owner_key(bundle, resource)
    with pytest.raises(BadRequestError, match="owning"):
        verify_references(bundle)


def test_textual_downloads_never_silently_drop_declared_binary_assets() -> None:
    from app.schemas.resource_bundle import BundleAsset

    bundle = agent_snapshot(AgentSpec(name="Agent"))
    root = bundle.resources[0].model_copy(
        update={
            "included": frozenset({BundleContentLayer.DEFINITION, BundleContentLayer.PROJECT_FILES})
        }
    )
    bundle = bundle.model_copy(
        update={
            "resources": (root,),
            "assets": (
                BundleAsset(
                    resource=root.key,
                    layer=BundleContentLayer.PROJECT_FILES,
                    name="data.txt",
                    sha256="0" * 64,
                    size_bytes=0,
                    media_type="text/plain",
                ),
            ),
        }
    )
    with pytest.raises(BadRequestError, match="ZIP"):
        documents.document_bytes(bundle, "json")
    context = BundleResource(
        key="context/body",
        kind=BundleResourceKind.CONTEXT,
        name="Context",
        definition={"name": "Context", "content": "body"},
        included=frozenset({BundleContentLayer.DEFINITION, BundleContentLayer.CONTEXT_CONTENT}),
    )
    selection_bundle = bundle.model_copy(update={"resources": (root, context), "assets": ()})
    with pytest.raises(BadRequestError, match="definition before"):
        documents.select_content(
            selection_bundle,
            BundleSelection(
                resources={
                    root.key: frozenset({BundleContentLayer.DEFINITION}),
                    context.key: frozenset({BundleContentLayer.CONTEXT_CONTENT}),
                }
            ),
        )


def test_secret_dictionary_keys_are_not_confused_with_structural_agent_fields() -> None:
    from app.agents.spec import CapabilityBindingSpec

    load_builtins()
    secret = uuid4()
    spec = AgentSpec(
        name="Agent",
        capabilities=[
            CapabilityBindingSpec(
                id="mirage",
                config={
                    "mounts": [
                        {
                            "path": "/notes/",
                            "backend": "notion",
                            "secrets": {"subagents": str(secret)},
                        }
                    ]
                },
            )
        ],
    )
    resource = agent_snapshot(spec).resources[0]
    assert agent_omissions(resource) == {}


@pytest.mark.parametrize(
    "text",
    [
        "name: First\nname: Second",
        '{"name":"First","name":"Second"}',
        "name: Agent\nmodel_params: {1: value}",
        "name: Agent\nmodel_params: {? [key]: value}",
    ],
)
def test_ambiguous_configuration_keys_are_refused(text: str) -> None:
    with pytest.raises(BadRequestError, match="unique string keys"):
        documents.parse_document(text)


@pytest.mark.parametrize("file_format", ["yaml", "json"])
def test_download_cannot_exceed_the_import_document_limit(
    monkeypatch: pytest.MonkeyPatch, file_format: str
) -> None:
    monkeypatch.setattr(documents, "MAX_DOCUMENT_BYTES", 10)
    with pytest.raises(BadRequestError, match="4 MiB"):
        documents.document_bytes(agent_snapshot(AgentSpec(name="Agent")), file_format)


def test_secret_dictionary_keys_named_like_bindings_are_not_binding_containers() -> None:
    from app.schemas.resource_bundle import BundleReference

    resource = BundleResource(
        key="agent/root",
        kind=BundleResourceKind.AGENT,
        name="Agent",
        definition={"secrets": {"subagents": "value"}},
        included=frozenset({BundleContentLayer.DEFINITION}),
        references=(
            BundleReference(path=("secrets", "subagents"), target="secret/value", is_key=True),
        ),
    )
    assert agent_omissions(resource) == {}


@pytest.mark.parametrize(
    "url",
    [
        "https://mcp.example.test/?anything=PRIVATE",
        "https://mcp.example.test/#PRIVATE",
        "https://user:PRIVATE@mcp.example.test/",
        "http://[invalid",
    ],
)
def test_portable_connection_definitions_never_guess_which_url_values_are_secret(url: str) -> None:
    from app.services.portability.content import McpContent

    resource = BundleResource(
        key="mcp_connection/source",
        kind=BundleResourceKind.MCP_CONNECTION,
        name="Connection",
        definition={"name": "custom", "url": url},
        included=frozenset({BundleContentLayer.DEFINITION}),
    )
    with pytest.raises(BadRequestError) as exc:
        definition_model(resource)
    assert "PRIVATE" not in str(exc.value.details)
    assert McpContent(name="custom", url="https://mcp.example.test/endpoint").url.endswith(
        "/endpoint"
    )


def test_portable_model_settings_keep_generation_parameters_but_not_transport_credentials() -> None:
    from app.services.portability.content import ModelContent, portable_connection_settings

    assert portable_connection_settings(None)
    assert portable_connection_settings(
        "https://models.example.test/api", {"temperature": 0.2, "extra_headers": {}}
    )
    assert ModelContent(
        label="Model", provider="openai", model="test", params={"temperature": 0.2}
    ).params == {"temperature": 0.2}
    with pytest.raises(ValidationError, match="destination"):
        ModelContent(
            label="Model",
            provider="openai",
            model="test",
            params={"extra_headers": {"X-Unknown": "PRIVATE"}},
        )
    with pytest.raises(ValidationError, match="destination"):
        ModelContent(
            label="Model",
            provider="openai",
            model="test",
            base_url="https://models.example.test/?custom=PRIVATE",
        )


def test_agent_import_boundary_refuses_other_or_multiple_roots() -> None:
    from app.services.portability.contracts import require_agent_root

    resource = BundleResource(key="context/root", kind=BundleResourceKind.CONTEXT, name="Context")
    with pytest.raises(BadRequestError, match="exactly one agent"):
        require_agent_root(ResourceBundle(roots=(resource.key,), resources=(resource,)))
