"""Personal model keys: approved destinations, user-sealed storage, no shared fallback."""

from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.audience import run_impersonated
from app.agents.model_resolver import (
    ModelApi,
    ModelRegion,
    ModelRequestSpec,
    ResolvedCredential,
    get_provider,
    is_decision_api,
)
from app.core.audit import current_impersonator, record_audit
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret, unseal_secret
from app.core.vault import VaultScope
from app.db.models.credential import ModelProfile
from app.repositories import personal_model_key as key_repo
from app.schemas.personal_model_key import (
    AgentModelConnectionRead,
    PersonalModelDestination,
    PersonalModelKeyCreate,
    PersonalModelKeyRead,
)
from app.services.model_outputs import model_outputs


def personal_connection_owner(ctx: AuthContext) -> UUID:
    if (
        current_impersonator() is not None
        or run_impersonated()
        or ctx.user_id is None
        or ctx.api_key_id is not None
        or ctx.key_scopes is not None
        or ctx.subject_is_publisher_fallback
        or ctx.channel_identity_id is not None
    ):
        raise AuthorizationError(
            message="Personal model connections require your signed-in web session"
        )
    return ctx.user_id


def personal_profile_problem(profile: ModelProfile) -> str | None:
    if profile.provider == "github_copilot" and profile.base_url is not None:
        return "Copilot requires the fixed GitHub.com gateway"
    if get_provider(profile.provider).secret_kind != SecretKind.API_KEY:
        return "Personal model connections currently support API-key providers only"
    if profile.fallback_profile_ids:
        return "Remove model fallbacks before enabling personal keys; the model must stay fixed"
    if (
        is_decision_api(profile.provider, profile.api)
        or not model_outputs(profile.provider, profile.model, base_url=profile.base_url).chat
    ):
        return "Personal model connections require a chat model"
    return None


class PersonalModelKeyService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def mine(self, ctx: AuthContext) -> list[PersonalModelKeyRead]:
        rows = await key_repo.list_for(
            self.db, organization_id=ctx.organization_id, user_id=personal_connection_owner(ctx)
        )
        return [PersonalModelKeyRead.model_validate(row) for row in rows]

    async def _profile(self, ctx: AuthContext, agent_id: UUID) -> ModelProfile | None:
        from app.services.agent_registry import AgentRegistryService

        personal_connection_owner(ctx)
        _, spec, _ = await AgentRegistryService(self.db).get_runnable_spec(ctx, agent_id)
        if spec.model_credential_mode != "personal":
            return None
        # Import locally to keep the registry's publish validator independent of
        # the personal connection's authenticated-agent lookup.
        from app.services.model_profile import ModelProfileService

        profile = await ModelProfileService(self.db).profile_for_organization(
            ctx.organization_id, profile_id=spec.model_profile_id
        )
        if problem := personal_profile_problem(profile):
            raise BadRequestError(message=problem)
        return profile

    async def destination(self, ctx: AuthContext, agent_id: UUID) -> PersonalModelDestination:
        """An approved personal model destination, checked through current agent run access."""
        profile = await self._profile(ctx, agent_id)
        if profile is None:
            raise BadRequestError(message="This agent uses its organization's model key")
        return PersonalModelDestination(
            profile_id=profile.id,
            provider=profile.provider,
            endpoint=profile.base_url,
            model=profile.model,
        )

    async def status(self, ctx: AuthContext, agent_id: UUID) -> AgentModelConnectionRead:
        profile = await self._profile(ctx, agent_id)
        if profile is None:
            return AgentModelConnectionRead(personal=False, connected=True)
        row = await key_repo.get(
            self.db,
            organization_id=ctx.organization_id,
            user_id=personal_connection_owner(ctx),
            provider=profile.provider,
            endpoint=profile.base_url or "",
        )
        return AgentModelConnectionRead(
            personal=True,
            connected=row is not None,
            profile_id=profile.id,
            provider=profile.provider,
            endpoint=profile.base_url,
            model=profile.model,
        )

    async def save(
        self, ctx: AuthContext, agent_id: UUID, data: PersonalModelKeyCreate
    ) -> AgentModelConnectionRead:
        profile = await self._profile(ctx, agent_id)
        if profile is None:
            raise BadRequestError(message="This agent uses its organization's model key")
        destination = PersonalModelDestination(
            profile_id=profile.id,
            provider=profile.provider,
            endpoint=profile.base_url,
            model=profile.model,
        )
        if data.expected_destination != destination:
            raise ConflictError(
                message="The agent's model destination changed. Review it before entering your key again.",
                code="PERSONAL_MODEL_DESTINATION_CHANGED",
            )
        owner = personal_connection_owner(ctx)
        sealed = seal_secret(ApiKeySecret(api_key=data.api_key), scope=VaultScope.user(owner))
        await key_repo.bump_generation(
            self.db,
            organization_id=ctx.organization_id,
            user_id=owner,
            provider=profile.provider,
            endpoint=profile.base_url or "",
        )
        await key_repo.save(
            self.db,
            organization_id=ctx.organization_id,
            user_id=owner,
            provider=profile.provider,
            endpoint=profile.base_url or "",
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
            details={"provider": profile.provider},
        )
        return await self.status(ctx, agent_id)

    async def delete(self, ctx: AuthContext, key_id: UUID) -> None:
        owner = personal_connection_owner(ctx)
        row = await key_repo.get_by_id(
            self.db, organization_id=ctx.organization_id, user_id=owner, key_id=key_id
        )
        if row is None:
            raise NotFoundError(message="Personal model connection not found")
        await key_repo.bump_generation(
            self.db,
            organization_id=ctx.organization_id,
            user_id=owner,
            provider=row.provider,
            endpoint=row.endpoint,
        )
        if not await key_repo.delete(
            self.db, organization_id=ctx.organization_id, user_id=owner, key_id=key_id
        ):
            raise NotFoundError(message="Personal model connection not found")
        await record_audit(
            self.db,
            organization_id=ctx.organization_id,
            actor_user_id=owner,
            action="personal_model_key.deleted",
            target_type="personal_model_key",
            target_id=str(key_id),
        )

    async def resolve(self, ctx: AuthContext, profile: ModelProfile) -> ModelRequestSpec:
        from app.services.personal_copilot import PersonalCopilotToken, sealed_fingerprint

        owner = personal_connection_owner(ctx)
        if problem := personal_profile_problem(profile):
            raise BadRequestError(message=problem, code="PERSONAL_MODEL_CONFIGURATION")
        row = await key_repo.get(
            self.db,
            organization_id=ctx.organization_id,
            user_id=owner,
            provider=profile.provider,
            endpoint=profile.base_url or "",
        )
        if row is None:
            raise AuthorizationError(
                message="Connect your own model API key in chat settings before sending a message",
                code="PERSONAL_MODEL_KEY_REQUIRED",
                details={"profile_id": str(profile.id)},
            )
        secret = unseal_secret(
            row.sealed_secret,
            kind=SecretKind.API_KEY,
            scope=VaultScope.user(owner),
            key_version=row.key_version,
        )
        if not isinstance(secret, ApiKeySecret):
            raise TypeError("A personal model key has the wrong secret kind")
        return ModelRequestSpec(
            profile_id=profile.id,
            label=profile.label,
            provider=profile.provider,
            model=profile.model,
            params=dict(profile.params),
            context_length=profile.context_length,
            fallbacks=[],
            credential=ResolvedCredential(
                provider=profile.provider,
                secret=secret,
                credential_id=row.id,
                token_source=PersonalCopilotToken(
                    ctx.organization_id, owner, row.id, sealed_fingerprint(row.sealed_secret)
                )
                if profile.provider == "github_copilot"
                else None,
                routing={
                    **(
                        {"credential_fingerprint": sealed_fingerprint(row.sealed_secret)}
                        if profile.provider == "github_copilot"
                        else {}
                    ),
                    "credential_updated_at": row.updated_at.isoformat()
                    if row.updated_at is not None
                    else None,
                },
                base_url=profile.base_url,
                api=TypeAdapter[ModelApi | None](ModelApi | None).validate_python(profile.api),
                region=TypeAdapter[ModelRegion | None](ModelRegion | None).validate_python(
                    profile.region
                ),
            ),
        )
