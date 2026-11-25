"""Verify uploaded binding paths against platform-owned resource schemas."""

from pydantic import BaseModel, ValidationError

from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.core.field_errors import field_problems
from app.schemas.resource_bundle import (
    BundlePath,
    BundleReference,
    BundleResource,
    BundleResourceKind,
    ResourceBundle,
)
from app.services.portability.content import (
    ContextContent,
    McpContent,
    ModelContent,
    SkillContent,
    SkillSnapshotContent,
)
from app.services.portability.references import ResourcePin, resource_pins
from app.services.portability.workflows import WorkflowContent, workflow_omissions, workflow_pins

DEFINITION_MODELS: dict[BundleResourceKind, type[BaseModel]] = {
    BundleResourceKind.AGENT: AgentSpec,
    BundleResourceKind.WORKFLOW: WorkflowContent,
    BundleResourceKind.AGENT_VERSION: AgentSpec,
    BundleResourceKind.CONTEXT: ContextContent,
    BundleResourceKind.SKILL: SkillContent,
    BundleResourceKind.SKILL_VERSION: SkillSnapshotContent,
    BundleResourceKind.SKILL_FORK: SkillSnapshotContent,
    BundleResourceKind.MODEL_PROFILE: ModelContent,
    BundleResourceKind.MCP_CONNECTION: McpContent,
}

CREATE_PERMISSIONS = {
    BundleResourceKind.AGENT: "agents:edit",
    BundleResourceKind.WORKFLOW: "workflows:create",
    BundleResourceKind.CONTEXT: "context:edit",
    BundleResourceKind.SKILL: "skills:edit",
    BundleResourceKind.SKILL_VERSION: "skills:edit",
    BundleResourceKind.SKILL_FORK: "skills:edit",
    BundleResourceKind.MODEL_PROFILE: "connections:manage",
    BundleResourceKind.MCP_CONNECTION: "mcp:manage",
}


def definition_model(resource: BundleResource) -> BaseModel:
    model = DEFINITION_MODELS.get(resource.kind)
    if model is None or resource.definition is None:
        raise BadRequestError(
            message="This resource has no supported portable definition",
            details={"resource": resource.key},
        )
    try:
        return model.model_validate(resource.definition)
    except ValidationError as exc:
        raise BadRequestError(
            message="A resource definition does not match its type",
            details={
                "fields": field_problems(
                    exc.errors(include_input=False, include_url=False), root="bundle"
                )
            },
        ) from exc


def references_for(model: BaseModel) -> tuple[tuple[BundleReference, ResourcePin], ...]:
    return tuple(
        (
            BundleReference(
                path=pin.path,
                target=pin.bundle_key,
                is_key=pin.is_key,
                destination_field="version_number" if pin.source_number is not None else "id",
            ),
            pin,
        )
        for pin in (
            workflow_pins(model) if isinstance(model, WorkflowContent) else resource_pins(model)
        )
    )


def verify_references(bundle: ResourceBundle) -> None:
    """No uploaded path, resource kind or version owner chooses what gets rewritten."""
    by_key = {item.key: item for item in bundle.resources}
    for resource in bundle.resources:
        if resource.source_parent_id is not None:
            owner_key(bundle, resource)
        if resource.definition is None:
            continue
        actual = {
            (ref.path, ref.is_key): (ref, pin)
            for ref, pin in references_for(definition_model(resource))
        }
        declared = {(ref.path, ref.is_key): ref for ref in resource.references}
        if actual.keys() != declared.keys():
            raise BadRequestError(
                message="The manifest's reference paths do not match the resource schema"
            )
        for path, (expected, pin) in actual.items():
            reference = declared[path]
            target = by_key[reference.target]
            if (
                reference.destination_field != expected.destination_field
                or target.kind != pin.kind
                or target.source_id != pin.source_id
                or target.source_parent_id != pin.parent_id
                or (
                    pin.source_number is not None
                    and target.source_version != str(pin.source_number)
                )
            ):
                raise BadRequestError(
                    message="A reference must identify the resource and version declared by its schema"
                )


def owner_key(bundle: ResourceBundle, resource: BundleResource) -> str:
    owner_kind = (
        BundleResourceKind.AGENT
        if resource.kind == BundleResourceKind.AGENT_VERSION
        else BundleResourceKind.SKILL
    )
    matches = [
        item.key
        for item in bundle.resources
        if item.kind == owner_kind and item.source_id == resource.source_parent_id
    ]
    if resource.source_parent_id is None or len(matches) != 1:
        raise BadRequestError(
            message="A versioned dependency must identify exactly one declared owning resource"
        )
    return matches[0]


def binding_omissions(resource: BundleResource) -> dict[BundlePath, BundlePath]:
    """Skip a required-ID binding as a whole, retaining every policy on kept bindings."""
    if resource.kind == BundleResourceKind.WORKFLOW:
        return workflow_omissions(WorkflowContent.model_validate(resource.definition))
    if resource.kind not in (BundleResourceKind.AGENT, BundleResourceKind.AGENT_VERSION):
        return {}
    omit: dict[BundlePath, BundlePath] = {}
    for ref in resource.references:
        path = ref.path
        for field in (
            "mcp_servers",
            "skill_bindings",
            "subagents",
            "table_bindings",
            "external_agents",
        ):
            if field in path:
                index = path.index(field)
                if len(path) > index + 1 and isinstance(path[index + 1], int):
                    omit[path] = path[: index + 2]
                    break
    return omit


def require_agent_root(bundle: ResourceBundle) -> None:
    by_key = {resource.key: resource for resource in bundle.resources}
    if len(bundle.roots) != 1 or by_key[bundle.roots[0]].kind != BundleResourceKind.AGENT:
        raise BadRequestError(message="This importer requires exactly one agent root")


def require_supported_root(bundle: ResourceBundle) -> None:
    by_key = {resource.key: resource for resource in bundle.resources}
    if len(bundle.roots) != 1 or by_key[bundle.roots[0]].kind not in (
        BundleResourceKind.AGENT,
        BundleResourceKind.WORKFLOW,
    ):
        raise BadRequestError(message="This importer requires exactly one agent or workflow root")


def require_workflow_root(bundle: ResourceBundle) -> None:
    by_key = {resource.key: resource for resource in bundle.resources}
    if len(bundle.roots) != 1 or by_key[bundle.roots[0]].kind != BundleResourceKind.WORKFLOW:
        raise BadRequestError(message="This importer requires exactly one workflow root")
