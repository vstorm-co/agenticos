"""One workflow node per native product operation, using the same authenticated call."""

from app.services.integrations import PRODUCTS, AccountSelection
from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.integration_action._handler import (
    IntegrationInput,
    IntegrationOutput,
    check_for,
    handler_for,
)

for product in PRODUCTS.values():
    for operation in product.operations:
        register(
            NodeDefinition(
                id=f"integration.{product.id}.{operation.id}",
                version=1,
                name=f"{product.name}: {operation.id.replace('_', ' ')}",
                category={"outlook_mail": "outlook", "microsoft_files": "onedrive"}.get(
                    product.id, product.id
                ),
                description=operation.description,
                kind="action",
                config_schema=AccountSelection,
                input_schema=IntegrationInput,
                output_schema=IntegrationOutput,
                ports=(
                    Port(id="in", label="In", kind="input", schema=IntegrationInput),
                    Port(id="out", label="Out", kind="output", schema=IntegrationOutput),
                ),
                effect_kind="write" if operation.side_effecting else "read",
                retry_guarantee="none" if operation.side_effecting else "idempotent",
                handler=handler_for(product.id, operation.id),
                resource_check=check_for(product.id, operation.id),
            )
        )
