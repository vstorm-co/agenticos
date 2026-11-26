"""Official application grants: durable registrations and generation-bound vault rotation.

Registration is committed before exchanging a code: a failed exchange or declined
plan consent must not cause another application registration on the next sign-in.
The operator gate applies to sign-in, refresh and every inference request.
"""

import json
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import anyio
import httpx2
from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_ai.exceptions import UserError
from pydantic_ai.providers.openai_chatgpt import (
    OpenAIChatGPTCredentials,
    OpenAIChatGPTCredentialSource,
    OpenAIChatGPTOAuthFlow,
)
from pydantic_ai.providers.openai_codex import CredentialsRefreshError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.redis import RedisClient
from app.core.config import settings
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import OpenAIChatGPTSecret, SecretKind, seal_secret, unseal_kind
from app.core.vault import VaultScope
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import Visibility
from app.db.session import get_db_context
from app.repositories import chatgpt_registration as registrations
from app.repositories import member_repo, organization_secret_repo
from app.services.access import SECRET, resolve_access
from app.services.organization_secret import OrganizationSecretService
from app.services.personal_model_key import personal_connection_owner

if TYPE_CHECKING:
    from app.services.model_catalog import CatalogModel


PURPOSE = "openai_chatgpt"
_PREFIX = "chatgpt-plan:sign-in:"
_TTL = 900


def require_enabled() -> UUID:
    """The installation's registration host, once the operator enabled plan usage."""
    host_id = settings.OPENAI_CHATGPT_HOST_ID
    if not settings.OPENAI_CHATGPT_PLAN_USAGE_ENABLED or host_id is None:
        raise BadRequestError(
            message="Official ChatGPT plan usage is disabled. The operator must verify this deployment's eligibility before enabling it."
        )
    return host_id


def as_secret(value: OpenAIChatGPTCredentials) -> OpenAIChatGPTSecret:
    return OpenAIChatGPTSecret(
        client_id=value.client_id,
        access_token=SecretStr(value.access_token),
        refresh_token=SecretStr(value.refresh_token),
        id_token=SecretStr(value.id_token) if value.id_token else None,
        scope=value.scope,
    )


def credentials(value: OpenAIChatGPTSecret) -> OpenAIChatGPTCredentials:
    return OpenAIChatGPTCredentials(
        client_id=value.client_id,
        access_token=value.access_token.get_secret_value(),
        refresh_token=value.refresh_token.get_secret_value(),
        id_token=value.id_token.get_secret_value() if value.id_token else None,
        scope=value.scope,
    )


class _Pending(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    owner: UUID
    organization: UUID
    generation: UUID
    host_id: UUID
    client_id: str | None
    verifier: SecretStr
    nonce: str


@dataclass(frozen=True)
class ConnectedChatGPT:
    connection: OrganizationSecret
    plan_usage_granted: bool


class ChatGPTPlanService:
    def __init__(self, db: AsyncSession, redis: RedisClient) -> None:
        self.db, self.redis = db, redis

    async def start_sign_in(self, ctx: AuthContext) -> str:
        host_id = require_enabled()
        owner = personal_connection_owner(ctx)
        row = await registrations.start(
            self.db,
            organization_id=ctx.organization_id,
            user_id=owner,
            host_id=host_id,
        )
        if row.host_id != host_id:
            raise BadRequestError(
                message="The ChatGPT installation identity changed. Restore its original host ID before reconnecting."
            )
        flow = OpenAIChatGPTOAuthFlow(
            app_name="AgenticOS", host_id=row.host_id.urn, client_id=row.client_id
        )
        pending = _Pending(
            owner=owner,
            organization=ctx.organization_id,
            generation=row.generation,
            host_id=row.host_id,
            client_id=row.client_id,
            verifier=SecretStr(flow.code_verifier),
            nonce=flow.nonce,
        )
        # Redis already owns short-lived PKCE material; do not serialize its repr.
        payload = {
            **pending.model_dump(mode="json"),
            "verifier": pending.verifier.get_secret_value(),
        }
        await self.redis.set(_PREFIX + flow.state, json.dumps(payload), ttl=_TTL)
        return flow.authorization_url(extra_params={"prompt": "consent"})

    async def _finish(
        self,
        ctx: AuthContext,
        callback_url: str,
        store: Callable[[OpenAIChatGPTSecret], Awaitable[OrganizationSecret]],
    ) -> ConnectedChatGPT:
        require_enabled()
        owner = personal_connection_owner(ctx)
        parsed = urlsplit(callback_url.strip())
        query = parse_qs(parsed.query, keep_blank_values=True)
        if (
            parsed.scheme != "http"
            or parsed.netloc != "127.0.0.1:1455"
            or parsed.path != "/auth/callback"
            or parsed.fragment
        ):
            raise BadRequestError(
                message="Paste the official 127.0.0.1:1455 ChatGPT callback address"
            )
        if any(len(values) != 1 for values in query.values()) or not query.get("state", [""])[0]:
            raise BadRequestError(message="ChatGPT returned an invalid callback")
        state = query["state"][0]
        key = _PREFIX + state
        raw = await self.redis.get(key)
        pending = _Pending.model_validate_json(raw) if raw else None
        if (
            raw is None
            or pending is None
            or pending.owner != owner
            or pending.organization != ctx.organization_id
        ):
            raise NotFoundError(message="This ChatGPT sign-in expired or was already used")
        if not await self.redis.delete_if_equal(key, raw):
            raise ConflictError(message="This ChatGPT sign-in was already used")
        if "error" in query or not query.get("code", [""])[0]:
            raise BadRequestError(
                message="ChatGPT sign-in was refused. Start again to request plan sharing."
            )
        flow = OpenAIChatGPTOAuthFlow(
            app_name="AgenticOS",
            host_id=pending.host_id.urn,
            client_id=pending.client_id,
            state=state,
        )
        callback_client = query.get("client_id", [pending.client_id])[0]
        if (
            not callback_client
            or (
                pending.client_id is None
                and callback_client
                == parse_qs(urlsplit(flow.authorization_url()).query)["client_id"][0]
            )
            or len(callback_client) > 512
            or (pending.client_id is not None and callback_client != pending.client_id)
        ):
            raise BadRequestError(
                message="ChatGPT did not acknowledge the expected application registration"
            )
        # A separate transaction makes the issued client durable even if token
        # exchange fails. It also rejects a callback superseded by a new sign-in.
        async with get_db_context() as db:
            if not await registrations.claim_client(
                db,
                organization_id=ctx.organization_id,
                user_id=owner,
                generation=pending.generation,
                client_id=callback_client,
            ):
                raise ConflictError(
                    message="ChatGPT sign-in changed. Start again with the saved registration."
                )
        flow.code_verifier = pending.verifier.get_secret_value()
        flow.nonce = pending.nonce
        try:
            with anyio.fail_after(30):
                value = await flow.exchange_code(query["code"][0], client_id=callback_client)
        except (CredentialsRefreshError, UserError, httpx2.HTTPError, TimeoutError) as failed:
            raise BadRequestError(
                message="ChatGPT did not complete sign-in. Its registration was saved; start again."
            ) from failed
        # Hold the intent lock through the final local write. A newer sign-in
        # cannot overwrite this grant after a reconnect wins.
        row = await registrations.get(
            self.db, organization_id=ctx.organization_id, user_id=owner, locked=True
        )
        if row is None or row.generation != pending.generation:
            raise ConflictError(message="A newer ChatGPT sign-in superseded this callback")
        return ConnectedChatGPT(await store(as_secret(value)), value.plan_usage_granted)

    async def create(
        self,
        ctx: AuthContext,
        *,
        callback_url: str,
        name: str,
        description: str | None,
        visibility: Visibility,
    ) -> ConnectedChatGPT:
        if visibility != Visibility.PRIVATE or not ctx.has(Perm.SECRETS_EDIT):
            raise BadRequestError(
                message="An official ChatGPT grant must be stored privately by its owner"
            )

        async def store(value: OpenAIChatGPTSecret) -> OrganizationSecret:
            return await OrganizationSecretService(self.db).create(
                ctx,
                name=name,
                value=value,
                description=description,
                purpose=PURPOSE,
                visibility=Visibility.PRIVATE,
            )

        return await self._finish(ctx, callback_url, store)

    async def reconnect(
        self, ctx: AuthContext, secret_id: UUID, *, callback_url: str
    ) -> ConnectedChatGPT:
        row = await OrganizationSecretService(self.db).get_usable(
            ctx, secret_id, kind=SecretKind.OPENAI_CHATGPT
        )
        if row.owner_user_id != personal_connection_owner(ctx) or not await resolve_access(
            self.db, ctx, row, Perm.SECRETS_EDIT, resource_type=SECRET
        ):
            raise NotFoundError(message="ChatGPT grant not found")

        async def store(value: OpenAIChatGPTSecret) -> OrganizationSecret:
            return await OrganizationSecretService(self.db).update(ctx, secret_id, value=value)

        return await self._finish(ctx, callback_url, store)


class VaultChatGPTCredentials(OpenAIChatGPTCredentialSource):
    def __init__(self, *, organization_id: UUID, secret_id: UUID, generation: UUID) -> None:
        self.organization_id, self.secret_id, self.generation = (
            organization_id,
            secret_id,
            generation,
        )
        self._predecessor: SecretStr | None = None

    def __repr__(self) -> str:
        return f"VaultChatGPTCredentials(secret_id={self.secret_id})"

    async def _row(self, db: AsyncSession, *, locked: bool = False) -> OrganizationSecret:
        host_id = require_enabled()
        read = organization_secret_repo.get_locked if locked else organization_secret_repo.get
        row = await read(db, self.secret_id, organization_id=self.organization_id)
        if (
            row is None
            or row.authorization_generation != self.generation
            or row.kind != SecretKind.OPENAI_CHATGPT
            or row.owner_user_id is None
            or await member_repo.get(
                db, organization_id=self.organization_id, user_id=row.owner_user_id
            )
            is None
        ):
            raise BadRequestError(
                message="The ChatGPT grant changed or its owner left. Reconnect before another request."
            )
        registration = await registrations.get(
            db, organization_id=self.organization_id, user_id=row.owner_user_id
        )
        if registration is None or registration.host_id != host_id:
            raise BadRequestError(
                message="The ChatGPT installation registration changed. Restore its original host ID before another request."
            )
        return row

    async def visible_to(self, user_id: UUID) -> bool:
        """A shared model profile cannot lend another member the owner's grant."""
        async with get_db_context() as db:
            row = await organization_secret_repo.get(
                db, self.secret_id, organization_id=self.organization_id
            )
            if (
                row is None
                or row.owner_user_id != user_id
                or row.authorization_generation != self.generation
            ):
                return False
            member = await member_repo.get(
                db, organization_id=self.organization_id, user_id=user_id
            )
            if member is None:
                return False
            ctx = AuthContext(
                user_id=user_id, organization_id=self.organization_id, role=member.role
            )
            return await resolve_access(db, ctx, row, Perm.SECRETS_VIEW, resource_type=SECRET)

    async def assert_current(self) -> None:
        async with get_db_context() as db:
            await self._row(db)

    async def load(self) -> OpenAIChatGPTCredentials:
        async with get_db_context() as db:
            row = await self._row(db)
            value = unseal_kind(
                row.sealed_secret,
                model=OpenAIChatGPTSecret,
                scope=VaultScope.organization(self.organization_id),
                key_version=row.key_version,
            )
        self._predecessor = value.refresh_token
        return credentials(value)

    async def save(self, credentials: OpenAIChatGPTCredentials) -> None:
        async with get_db_context() as db:
            row = await self._row(db, locked=True)
            held = unseal_kind(
                row.sealed_secret,
                model=OpenAIChatGPTSecret,
                scope=VaultScope.organization(self.organization_id),
                key_version=row.key_version,
            )
            if (
                self._predecessor is None
                or not secrets.compare_digest(
                    held.refresh_token.get_secret_value(), self._predecessor.get_secret_value()
                )
                or held.client_id != credentials.client_id
            ):
                raise ConflictError(
                    message="Another ChatGPT connection or refresh won. Start a new request."
                )
            sealed = seal_secret(
                as_secret(credentials), scope=VaultScope.organization(self.organization_id)
            )
            await organization_secret_repo.update(
                db,
                secret=row,
                update_data={
                    "sealed_secret": sealed.ciphertext,
                    "hint": sealed.hint,
                    "key_version": sealed.key_version,
                },
            )
        self._predecessor = SecretStr(credentials.refresh_token)


class _CatalogEntry(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    slug: str
    display_name: str
    visibility: str


class _Catalog(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    models: list[_CatalogEntry]


async def account_models(db: AsyncSession, ctx: AuthContext, secret_id: UUID) -> list[CatalogModel]:
    """An uncached, bounded catalog under the exact selected grant, never an API key."""
    from openai import OpenAIError
    from pydantic import ValidationError

    from app.agents.chatgpt_plan import ChatGPTPlanProvider
    from app.services.model_catalog import CatalogModel

    require_enabled()
    row = await OrganizationSecretService(db).get_usable(
        ctx, secret_id, kind=SecretKind.OPENAI_CHATGPT
    )
    if ctx.user_id is None or row.owner_user_id != ctx.user_id:
        raise AuthorizationError(
            message="Only the grant owner may list this ChatGPT account's models"
        )
    source = VaultChatGPTCredentials(
        organization_id=ctx.organization_id,
        secret_id=row.id,
        generation=row.authorization_generation,
    )
    provider = ChatGPTPlanProvider(source)
    try:
        with anyio.fail_after(15):
            async with provider:
                client = provider.client.with_options(timeout=10, max_retries=0)
                async with client.models.with_streaming_response.list() as response:
                    body = bytearray()
                    async for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 2 * 1024 * 1024:
                            raise BadRequestError(
                                message="ChatGPT returned an excessive model catalog"
                            )
                catalog = _Catalog.model_validate_json(body)
    except (OpenAIError, UserError, httpx2.HTTPError, ValidationError, TimeoutError) as failed:
        raise BadRequestError(
            message="This ChatGPT account's models could not be listed. Check plan sharing and reconnect."
        ) from failed
    if len(catalog.models) > 2048:
        raise BadRequestError(message="ChatGPT returned an excessive model catalog")
    result: list[CatalogModel] = []
    seen: set[str] = set()
    for model in catalog.models:
        if model.visibility != "list":
            continue
        if (
            not model.slug
            or len(model.slug) > 255
            or any(not character.isprintable() or character.isspace() for character in model.slug)
            or not model.display_name
            or len(model.display_name) > 256
            or model.slug in seen
        ):
            raise BadRequestError(
                message="ChatGPT returned ambiguous or unsupported model identities"
            )
        seen.add(model.slug)
        result.append(CatalogModel(id=model.slug, name=model.display_name, surfaces=("responses",)))
    return result
