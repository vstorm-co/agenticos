"""Owner-bound, bounded device polling into the existing personal model vault."""

import math
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import anyio
import httpx2
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.github_copilot import CopilotAccountAPI, CopilotPending
from app.clients.redis import RedisClient
from app.core.audit import record_audit
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, seal_secret
from app.core.vault import VaultScope
from app.repositories import personal_model_key as key_repo
from app.schemas.personal_model_key import (
    CopilotSignInChallenge,
    CopilotSignInResult,
    PersonalModelDestination,
)
from app.services.personal_model_key import PersonalModelKeyService, personal_connection_owner

_PREFIX = "copilot:personal-sign-in:"


class _Pending(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    owner: UUID
    organization: UUID
    agent_id: UUID
    destination: PersonalModelDestination
    client_id: str
    device_code: str = Field(repr=False)
    interval: int = Field(gt=0)
    next_poll: AwareDatetime
    expires_at: AwareDatetime
    generation: UUID


class CopilotSignInService:
    def __init__(
        self, db: AsyncSession, redis: RedisClient, account: CopilotAccountAPI, *, client_id: str
    ) -> None:
        self.db = db
        self.redis = redis
        self.account = account
        self.client_id = client_id
        self.keys = PersonalModelKeyService(db)

    async def start(
        self, ctx: AuthContext, agent_id: UUID, expected: PersonalModelDestination
    ) -> CopilotSignInChallenge:
        owner = personal_connection_owner(ctx)
        destination = await self.keys.destination(ctx, agent_id)
        self._destination(destination, expected)
        if not self.client_id.strip():
            raise BadRequestError(
                message="Configure AgenticOS's own GitHub OAuth App client ID with device flow enabled before connecting Copilot."
            )
        generation = await key_repo.bump_generation(
            self.db,
            organization_id=ctx.organization_id,
            user_id=owner,
            provider="github_copilot",
            endpoint="",
        )
        challenge = await self.account.start(self.client_id)
        if challenge.expires_in > 3600 or challenge.interval > challenge.expires_in:
            raise BadRequestError(
                message="GitHub returned unsupported device authorization timing."
            )
        now = datetime.now(UTC)
        pending = _Pending(
            owner=owner,
            organization=ctx.organization_id,
            agent_id=agent_id,
            destination=destination,
            client_id=self.client_id,
            device_code=challenge.device_code,
            interval=challenge.interval,
            next_poll=now + timedelta(seconds=challenge.interval),
            expires_at=now + timedelta(seconds=challenge.expires_in),
            generation=generation,
        )
        handle = secrets.token_urlsafe(32)
        await self.redis.set(_PREFIX + handle, pending.model_dump_json(), ttl=challenge.expires_in)
        return CopilotSignInChallenge(
            handle=handle,
            user_code=challenge.user_code,
            verification_uri=challenge.verification_uri,
            expires_at=pending.expires_at,
            poll_after_seconds=challenge.interval,
        )

    @staticmethod
    def _destination(actual: PersonalModelDestination, expected: PersonalModelDestination) -> None:
        if actual.provider != "github_copilot" or actual.endpoint is not None:
            raise BadRequestError(
                message="Copilot sign-in requires a personal GitHub.com Copilot model profile"
            )
        if actual != expected:
            raise ConflictError(
                message="The agent's model destination changed. Start sign-in again.",
                code="PERSONAL_MODEL_DESTINATION_CHANGED",
            )

    async def poll(self, ctx: AuthContext, agent_id: UUID, handle: str) -> CopilotSignInResult:
        owner = personal_connection_owner(ctx)
        key = _PREFIX + handle
        raw = await self.redis.get(key)
        if raw is None:
            raise NotFoundError(
                message="This Copilot sign-in expired or was already used. Start again."
            )
        pending = _Pending.model_validate_json(raw)
        if (
            pending.owner != owner
            or pending.organization != ctx.organization_id
            or pending.agent_id != agent_id
        ):
            raise NotFoundError(
                message="This Copilot sign-in expired or was already used. Start again."
            )
        self._destination(await self.keys.destination(ctx, agent_id), pending.destination)
        now = datetime.now(UTC)
        if pending.client_id != self.client_id or now >= pending.expires_at:
            await self.redis.delete_if_equal(key, raw)
            raise BadRequestError(
                message="This Copilot sign-in expired or its application changed. Start again."
            )
        wait = math.ceil((pending.next_poll - now).total_seconds())
        if wait > 0:
            return CopilotSignInResult(status="pending", poll_after_seconds=wait)
        lease = secrets.token_urlsafe(24)
        lock = key + ":poll"
        if not await self.redis.set(lock, lease, ttl=60, nx=True):
            return CopilotSignInResult(status="pending", poll_after_seconds=pending.interval)
        try:
            # A completed or throttled poll may have won while this request waited.
            if await self.redis.get(key) != raw:
                raise ConflictError(message="Copilot sign-in changed. Refresh its status.")
            try:
                with anyio.fail_after(
                    max(0, (pending.expires_at - datetime.now(UTC)).total_seconds())
                ):
                    result = await self.account.poll(
                        client_id=pending.client_id, device_code=pending.device_code
                    )
            except (httpx2.HTTPError, TimeoutError) as failed:
                await self.redis.delete_if_equal(key, raw)
                raise BadRequestError(
                    message="Copilot authorization could not be confirmed. Start sign-in again."
                ) from failed
            except BaseException:
                with anyio.CancelScope(shield=True):
                    await self.redis.delete_if_equal(key, raw)
                raise
            if isinstance(result, CopilotPending):
                if result.error == "slow_down":
                    pending.interval = max(pending.interval + 5, result.interval or 0)
                pending.next_poll = datetime.now(UTC) + timedelta(seconds=pending.interval)
                ttl = math.ceil((pending.expires_at - datetime.now(UTC)).total_seconds())
                if ttl <= 0:
                    await self.redis.delete_if_equal(key, raw)
                    raise BadRequestError(message="Copilot sign-in expired. Start again.")
                if not await self.redis.replace_if_equal(
                    key, raw, pending.model_dump_json(), ttl=ttl
                ):
                    raise ConflictError(
                        message="Copilot sign-in was already consumed. Start again."
                    )
                return CopilotSignInResult(status="pending", poll_after_seconds=pending.interval)
            # Consume before verification/storage. A token is never exchanged twice,
            # and cancellation cannot leave an already consumed device code reusable.
            if not await self.redis.delete_if_equal(key, raw):
                raise ConflictError(message="Copilot sign-in was already consumed. Start again.")
            models = await self.account.models(result.access_token)
            if pending.destination.model not in {model.id for model in models}:
                raise BadRequestError(
                    message="This account and AgenticOS application do not offer the selected model on Chat Completions. No credential was saved."
                )
            self._destination(await self.keys.destination(ctx, agent_id), pending.destination)
            sealed = seal_secret(
                ApiKeySecret(api_key=result.access_token), scope=VaultScope.user(owner)
            )
            if not await key_repo.claim_generation(
                self.db,
                organization_id=ctx.organization_id,
                user_id=owner,
                provider="github_copilot",
                endpoint="",
                expected=pending.generation,
            ):
                raise ConflictError(
                    message="Your model connection changed during sign-in. No older grant replaced it."
                )
            await key_repo.save(
                self.db,
                organization_id=ctx.organization_id,
                user_id=owner,
                provider="github_copilot",
                endpoint="",
                sealed_secret=sealed.ciphertext,
                key_version=sealed.key_version,
            )
            await record_audit(
                self.db,
                organization_id=ctx.organization_id,
                actor_user_id=owner,
                action="personal_model_key.saved",
                target_type="agent",
                target_id=str(agent_id),
                details={"provider": "github_copilot"},
            )
            return CopilotSignInResult(status="connected")
        finally:
            with anyio.CancelScope(shield=True):
                await self.redis.delete_if_equal(lock, lease)
