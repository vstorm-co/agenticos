"""Native product nodes call the capability's operation service as the run principal."""

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.session import get_worker_db_context
from app.services.integrations import PRODUCTS, AccountSelection, IntegrationService
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError


class IntegrationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parameters: dict[str, str] = Field(default_factory=dict, title="Identifiers")
    query: dict[str, str] = Field(default_factory=dict, title="Query")
    body: dict[str, JsonValue] | None = Field(default=None, title="Request body")


class IntegrationOutput(BaseModel):
    result: dict[str, JsonValue]


def handler_for(
    product_id: str, operation_id: str
) -> Callable[[BaseModel | None, BaseModel | None], Awaitable[NodeResult]]:
    async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
        if not isinstance(config, AccountSelection) or not isinstance(node_input, IntegrationInput):
            return Failed(
                error=WorkflowError(
                    code="INTEGRATION_NOT_CONFIGURED",
                    message="Choose an account and operation input",
                )
            )
        current = context.current()
        if config.account == "personal" and current.public_origin:
            return Failed(
                error=WorkflowError(
                    code="INTEGRATION_NO_PERSON",
                    message="A public workflow cannot borrow its publisher's personal account",
                    bypassable=False,
                )
            )
        try:
            async with get_worker_db_context() as db:
                result = await IntegrationService(db).run(
                    product_id,
                    operation_id,
                    config,
                    organization_id=current.auth.organization_id,
                    person_id=current.auth.user_id,
                    parameters=node_input.parameters,
                    query=node_input.query,
                    body=node_input.body,
                    workflow_run_id=current.workflow_run_id,
                )
            return Completed(output=IntegrationOutput(result=result))
        except AppException as exc:
            return Failed(error=WorkflowError(code=exc.code, message=exc.message, bypassable=False))

    return handle


def check_for(
    product_id: str,
) -> Callable[[AsyncSession, AuthContext, BaseModel], Awaitable[list[tuple[str, str]]]]:
    async def check(
        db: AsyncSession, auth: AuthContext, config: BaseModel
    ) -> list[tuple[str, str]]:
        if not isinstance(config, AccountSelection):
            return [("account", "Choose an integration account")]
        try:
            await IntegrationService(db).binding_account(PRODUCTS[product_id], config, auth)
        except AppException as exc:
            return [("account", exc.message)]
        return []

    return check
