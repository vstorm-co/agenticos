"""Resolve a product's approved account before spending its credential."""

from dataclasses import replace
from typing import ClassVar, Literal, Self
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.odoo_credential import OdooCredential
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret
from app.db.models.mcp_connection import McpConnection
from app.repositories import mcp_connection_repo, member_repo
from app.services.integrations import client
from app.services.integrations.catalog import PRODUCTS, Operation, Product, application_scopes


class AccountToken(ApiKeySecret):
    """An ephemeral bearer token minted from an authorized connected account.

    This type is never a storable secret kind. Connectors accept it instead of
    arbitrary API keys, so a vault key cannot be spent against another service.
    """

    connection_id: UUID
    provider: Literal["google", "microsoft", "slack", "odoo"]


class OdooAccountToken(AccountToken):
    provider: Literal["odoo"] = "odoo"
    credential: OdooCredential


class AccountSelection(BaseModel):
    """A personal account is selected by name at run time, never by its author's id."""

    model_config = ConfigDict(extra="forbid")

    account: Literal["personal", "organization"] = Field(
        default="personal",
        title="Account owner",
        description="Use each person's own account or an organization account.",
    )
    account_name: str = Field(
        default="",
        max_length=320,
        title="Account name",
        description="The connected account's name or label. Leave empty only when exactly one account is connected.",
    )
    connection_id: UUID | None = Field(
        default=None,
        title="Organization account",
        description="The organization account to use when account owner is organization.",
    )
    channels: list[str] = Field(
        default_factory=list,
        max_length=20,
        title="Conversations",
        description="Conversation IDs to read in Slack or Teams change feeds. Teams channels use channel/team-id/channel-id. Leave empty for Teams app-only reads of all chats for the configured subject.",
    )
    disabled_tools: list[str] = Field(
        default_factory=list,
        title="Disabled tools",
        description="Stable tool IDs this capability must not offer.",
        json_schema_extra={"x-advanced": True},
    )
    _product_id: ClassVar[str | None] = None

    @model_validator(mode="after")
    def _known_tools(self) -> Self:
        if self._product_id is not None:
            allowed = {
                f"{self._product_id}_{op.id}" for op in PRODUCTS[self._product_id].operations
            }
            if not set(self.disabled_tools) <= allowed:
                raise ValueError("Disabled tools must belong to this product")
        return self


class IntegrationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def account(
        self,
        product: Product,
        selection: AccountSelection,
        *,
        organization_id: UUID,
        person_id: UUID | None,
    ) -> McpConnection:
        from app.services.mcp_connection import account_source_organization

        if selection.account == "organization":
            row = (
                await mcp_connection_repo.get_account(self.db, selection.connection_id)
                if selection.connection_id
                else None
            )
            if row is None or row.scope != "org" or row.organization_id != organization_id:
                raise NotFoundError(message="Organization integration account not found")
        else:
            if person_id is None:
                raise AuthorizationError(
                    message="This run has no person whose integration account it may use"
                )
            if (
                await member_repo.get_active(
                    self.db, organization_id=organization_id, user_id=person_id
                )
                is None
            ):
                raise AuthorizationError(
                    message="Integration access requires current organization membership"
                )
            rows = await mcp_connection_repo.list_accounts(
                self.db, provider=product.provider, user_id=person_id
            )
            owned = [row for row in rows if account_source_organization(row) == organization_id]
            named = [
                row
                for row in owned
                if selection.account_name and row.name == selection.account_name
            ]
            candidates = named or [
                row
                for row in owned
                if not selection.account_name
                or selection.account_name in {row.label, row.account_email}
            ]
            if len(candidates) != 1:
                raise BadRequestError(
                    message="Connect one integration account or select an unambiguous account name"
                )
            row = candidates[0]
        if row.catalog_key != product.provider or not row.is_enabled:
            raise AuthorizationError(
                message="This account is disabled or belongs to another integration"
            )
        return row

    async def binding_account(
        self, product: Product, selection: AccountSelection, ctx: AuthContext
    ) -> McpConnection:
        from app.services.integrations.authority import authorize
        from app.services.mcp_connection import McpConnectionService

        account = await self.account(
            product, selection, organization_id=ctx.organization_id, person_id=ctx.user_id
        )
        if selection.account == "organization":
            await authorize(self.db, account, ctx)
        if await McpConnectionService(self.db).account_needs_reconnect(
            account, organization_id=ctx.organization_id
        ):
            raise AuthorizationError(message="Reconnect this integration account before binding it")
        return account

    @staticmethod
    def check_operation_scopes(
        account: McpConnection, product: Product, operation: Operation
    ) -> None:
        from app.services.mcp_connection import McpConnectionService

        allowed_scopes = (
            application_scopes(product.id, operation)
            if account.auth_type == "application" and product.provider == "microsoft"
            else operation.scopes
        )
        if not set(allowed_scopes).intersection(account.granted_scopes or ()):
            raise AuthorizationError(
                message="Reconnect this account with the permissions this operation requires"
            )

        if (
            account.auth_type == "application"
            and operation.side_effecting
            and not McpConnectionService.application_writes_enabled(account)
        ):
            raise AuthorizationError(
                message="Writes were not enabled when connecting this application account"
            )

    async def source_token(
        self,
        *,
        organization_id: UUID,
        connection_id: UUID,
        provider: Literal["google", "microsoft", "slack", "odoo"],
    ) -> AccountToken:
        from app.services.mcp_connection import McpConnectionService

        product = PRODUCTS[
            {
                "google": "google_drive",
                "microsoft": "microsoft_files",
                "slack": "slack",
                "odoo": "odoo_contacts",
            }[provider]
        ]
        row = await self.account(
            product,
            AccountSelection(account="organization", connection_id=connection_id),
            organization_id=organization_id,
            person_id=None,
        )
        if not can_read_feed(row, product.id):
            raise AuthorizationError(
                message="Reconnect this account with the knowledge product's read permissions"
            )
        if provider == "odoo":
            credential = McpConnectionService(self.db).integration_odoo_credential(
                row, organization_id=organization_id
            )
            return OdooAccountToken(
                api_key=credential.api_key, credential=credential, connection_id=connection_id
            )
        token = await McpConnectionService(self.db).integration_access_token(
            row, organization_id=organization_id
        )
        if token is None:
            raise AuthorizationError(
                message="Reconnect the organization account used by this knowledge source"
            )
        return AccountToken(api_key=token, connection_id=connection_id, provider=provider)

    async def run(
        self,
        product_id: str,
        operation_id: str,
        selection: AccountSelection,
        *,
        organization_id: UUID,
        person_id: UUID | None,
        parameters: dict[str, str],
        query: dict[str, str],
        body: dict[str, JsonValue] | None,
        agent_run_id: UUID | None = None,
        workflow_run_id: UUID | None = None,
    ) -> dict[str, JsonValue]:
        from app.services.mcp_connection import McpConnectionService

        product = PRODUCTS[product_id]
        if f"{product_id}_{operation_id}" in selection.disabled_tools:
            raise AuthorizationError(message="This integration tool is disabled")
        operation = next((op for op in product.operations if op.id == operation_id), None)
        if operation is None:
            raise BadRequestError(message="Unknown integration operation")
        account = await self.account(
            product, selection, organization_id=organization_id, person_id=person_id
        )
        if selection.account == "organization":
            from app.services.integrations.authority import authorize, run_author

            author = await run_author(
                self.db,
                organization_id=organization_id,
                person_id=person_id,
                agent_run_id=agent_run_id,
                workflow_run_id=workflow_run_id,
            )
            await authorize(self.db, account, author)
        self.check_operation_scopes(account, product, operation)
        if product.provider == "odoo":
            from app.services.integrations.odoo import execute

            credential = McpConnectionService(self.db).integration_odoo_credential(
                account, organization_id=organization_id
            )
            return await execute(
                credential, operation, parameters=parameters, query=query, body=body
            )
        if product.provider == "imap":
            from app.services.integrations.imap import execute_mail

            credential = McpConnectionService(self.db).integration_mail_credential(
                account, organization_id=organization_id
            )
            return await execute_mail(credential, operation.id, parameters=parameters, query=query)
        token = await McpConnectionService(self.db).integration_access_token(
            account, organization_id=organization_id
        )
        if token is None:
            raise AuthorizationError(message="This integration account needs to be connected again")
        if (
            account.auth_type == "application"
            and product.provider == "microsoft"
            and "/me/" in operation.url
        ):
            if not account.account_email:
                raise AuthorizationError(message="This application account has no target mailbox")
            operation = replace(
                operation,
                url=operation.url.replace(
                    "/me/", "/users/" + quote(account.account_email, safe="") + "/"
                ),
            )
        if product_id == "slack" and operation_id == "my_mentions":
            identity = await client.execute(
                Operation(
                    "identity", "Read Slack identity", "GET", "https://slack.com/api/auth.test", ()
                ),
                token,
                parameters={},
                query={},
                body=None,
            )
            user_id = identity.get("user_id")
            if not isinstance(user_id, str) or not user_id:
                raise BadRequestError(message="Slack did not identify the connected user")
            if not set(query) <= set(operation.query):
                raise BadRequestError(
                    message="Use only the parameters declared by this integration tool"
                )
            operation = replace(operation, query=(*operation.query, "query"))
            query = {**query, "query": f"<@{user_id}>"}
        return await client.execute(operation, token, parameters=parameters, query=query, body=body)


def can_read_feed(
    account: McpConnection, portal_key: str, channels: tuple[str, ...] | None = None
) -> bool:
    product_id = {"google": "gmail", "microsoft": "outlook_mail", "imap": "imap_mail"}.get(
        portal_key, portal_key
    )
    product = PRODUCTS.get(product_id)
    if product is None or product.provider != account.catalog_key:
        return False
    scopes = set(account.granted_scopes or ())
    if product_id == "slack":
        return bool(scopes & {"channels:history", "groups:history", "im:history", "mpim:history"})
    if product_id == "teams":
        chat = (
            {"Chat.Read.All"}
            if account.auth_type == "application"
            else {"Chat.Read", "Chat.ReadWrite"}
        )
        if channels is None:
            return bool(scopes & (chat | {"ChannelMessage.Read.All"}))
        need_channels = any(channel.startswith("channel/") for channel in channels)
        need_chats = not channels or any(not channel.startswith("channel/") for channel in channels)
        return (not need_channels or "ChannelMessage.Read.All" in scopes) and (
            not need_chats or bool(scopes & chat)
        )
    operation = next(op for op in product.operations if not op.side_effecting)
    required_scopes = (
        application_scopes(product_id, operation)
        if account.auth_type == "application" and product.provider == "microsoft"
        else operation.scopes
    )
    return bool(scopes.intersection(required_scopes))
