"""A declared product operation becomes one named, individually gated tool."""

from collections.abc import Awaitable, Callable

from pydantic import JsonValue
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.deps import AgentDeps
from app.core.exceptions import AppException
from app.db.session import get_db_context
from app.services.integrations import PRODUCTS, AccountSelection, IntegrationService, Operation


def _operation_tool(
    product_id: str, operation: Operation, selection: AccountSelection
) -> Callable[..., Awaitable[dict[str, JsonValue]]]:
    async def call(
        ctx: RunContext[AgentDeps],
        parameters: dict[str, str] | None = None,
        query: dict[str, str] | None = None,
        body: dict[str, JsonValue] | None = None,
    ) -> dict[str, JsonValue]:
        """Call this integration operation.

        Returns:
            The provider's JSON object, including its pagination cursor when present,
            or an error explaining why this account cannot perform the operation.
        """
        deps = ctx.deps
        if deps.organization_id is None:
            return {"error": "This run has no organization for an integration account"}
        if selection.account == "personal" and (deps.audience is None or not deps.audience.private):
            return {
                "error": "Personal integration accounts are available only in a private conversation"
            }
        try:
            async with get_db_context() as db:
                return await IntegrationService(db).run(
                    product_id,
                    operation.id,
                    selection,
                    organization_id=deps.organization_id,
                    person_id=deps.run_person,
                    parameters=parameters or {},
                    query=query or {},
                    body=body,
                )
        except AppException as exc:
            return {"error": exc.message}

    call.__doc__ = (
        operation.description
        + f"\n\nRequired parameters: {', '.join(operation.parameters) or 'none'}. "
        + f"Allowed query fields: {', '.join(operation.query) or 'none'}. "
        + "The body follows this product's native API format. "
        + "Only the selected connected account is reachable.\n\nReturns:\n"
        + "    The provider's JSON object with its next-page cursor when present, or an error. "
        + "Responses exceeding 2 MB are refused; narrow the query."
    )
    return call


def build_toolset(product_id: str, selection: AccountSelection) -> FunctionToolset[AgentDeps]:
    toolset: FunctionToolset[AgentDeps] = FunctionToolset()
    for operation in PRODUCTS[product_id].operations:
        if f"{product_id}_{operation.id}" in selection.disabled_tools:
            continue
        toolset.add_function(
            _operation_tool(product_id, operation, selection), name=f"{product_id}_{operation.id}"
        )
    return toolset
