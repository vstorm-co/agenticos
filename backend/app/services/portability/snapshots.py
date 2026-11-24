"""Pure agent snapshots with one bundle identity per referenced resource."""

from uuid import UUID

from pydantic import JsonValue, TypeAdapter

from app.agents.spec import AgentSpec
from app.schemas.agent import agent_draft_revision
from app.schemas.resource_bundle import (
    BundleContentLayer,
    BundleReference,
    BundleResource,
    BundleResourceKind,
    ResourceBundle,
)
from app.services.portability.references import agent_pins

_OBJECT = TypeAdapter(dict[str, JsonValue])


def agent_snapshot(spec: AgentSpec, *, source_id: UUID | None = None) -> ResourceBundle:
    """Build the reference inventory before reading or including any dependencies.

    Reference-only descriptors deliberately reveal no resource names or contents.
    The application service enriches only entries the requester can access.
    Source IDs remain metadata/reuse candidates, never destination authority.
    """
    root_key = f"agent/{source_id if source_id is not None else 'root'}"
    descriptors: dict[str, BundleResource] = {}
    references: list[BundleReference] = []
    for pin in agent_pins(spec):
        key = pin.bundle_key
        references.append(
            BundleReference(
                path=pin.path,
                target=key,
                is_key=pin.is_key,
                destination_field="version_number" if pin.source_number is not None else "id",
            )
        )
        if key == root_key:
            continue
        previous = descriptors.get(key)
        if previous is not None and previous.source_parent_id != pin.parent_id:
            raise ValueError("A versioned resource cannot belong to two different owners")
        descriptors[key] = BundleResource(
            key=key,
            kind=pin.kind,
            source_id=pin.source_id,
            source_parent_id=pin.parent_id,
            source_version=None if pin.source_number is None else str(pin.source_number),
            name=pin.kind.value,
        )
    root = BundleResource(
        key=root_key,
        kind=BundleResourceKind.AGENT,
        source_id=source_id,
        name=spec.name,
        source_version=agent_draft_revision(spec),
        definition=_OBJECT.validate_python(spec.model_dump(mode="json")),
        references=tuple(references),
        included=frozenset({BundleContentLayer.DEFINITION}),
    )
    return ResourceBundle(roots=(root_key,), resources=(root, *descriptors.values()))
