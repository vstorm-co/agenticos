"""Resolve an opted-in voice as one provider/model/voice/key group."""

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.text_to_speech import TextToSpeechConfig
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import BadRequestError
from app.core.field_errors import refused_field
from app.core.secret_kinds import SecretKind
from app.db.models.agent_run import AgentRun
from app.repositories import agent_run_repo
from app.repositories import organization as organization_repo
from app.schemas.organization import OrganizationTextToSpeech
from app.services import provider_keys


class TextToSpeechSettingsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def validate_defaults(
        self, organization_id: UUID, defaults: OrganizationTextToSpeech | None
    ) -> None:
        """A shared default may spend only an organization-visible provider key."""
        if defaults is None or not defaults.enabled:
            return
        self._config(defaults)
        problem = await provider_keys.key_problem(
            self.db,
            defaults.secret_id,
            organization_id=organization_id,
            provider=defaults.provider,
            kind=SecretKind.API_KEY,
            feature="text to speech",
            ctx=None,
        )
        if problem is not None:
            raise refused_field("text_to_speech", problem)

    @staticmethod
    def _config(defaults: OrganizationTextToSpeech) -> TextToSpeechConfig:
        try:
            return TextToSpeechConfig(
                provider=defaults.provider, model=defaults.model, voice=defaults.voice
            )
        except ValidationError as exc:
            raise refused_field(
                "text_to_speech", "Choose an offered speech model and a voice it can use."
            ) from exc

    async def resolve_binding(
        self,
        organization_id: UUID,
        binding: CapabilityBindingSpec,
        *,
        snapshot: OrganizationTextToSpeech | None = None,
    ) -> CapabilityBindingSpec:
        """Keep explicit overrides intact; never mix an inherited key with another provider."""
        if (
            not binding.enabled
            or binding.id != "text_to_speech"
            or binding.config.get("use_organization_defaults") is not True
        ):
            return binding
        org = await organization_repo.get_by_id(self.db, organization_id)
        defaults = (
            OrganizationTextToSpeech.model_validate(org.text_to_speech)
            if org is not None and org.text_to_speech is not None
            else None
        )
        if defaults is None or not defaults.enabled:
            raise BadRequestError(
                message="Organization text to speech is disabled. Enable its default or choose an agent override.",
                code="SPEECH_DEFAULTS_UNAVAILABLE",
            )
        defaults = snapshot or defaults
        await self.validate_defaults(organization_id, defaults)
        config = {
            **binding.config,
            "provider": defaults.provider,
            "model": defaults.model,
            "voice": defaults.voice,
            "use_organization_defaults": False,
        }
        return binding.model_copy(update={"config": config, "secret_id": defaults.secret_id})

    async def resolve_spec(
        self,
        organization_id: UUID,
        spec: AgentSpec,
        *,
        snapshot: OrganizationTextToSpeech | None = None,
    ) -> tuple[AgentSpec, OrganizationTextToSpeech | None]:
        """Keep a parked run's destination fixed while rechecking its shared key."""
        bindings: list[CapabilityBindingSpec] = []
        inherited: OrganizationTextToSpeech | None = None
        for binding in spec.capabilities:
            resolved = await self.resolve_binding(organization_id, binding, snapshot=snapshot)
            bindings.append(resolved)
            if resolved is not binding:
                inherited = OrganizationTextToSpeech.model_validate(
                    {
                        "provider": resolved.config["provider"],
                        "model": resolved.config["model"],
                        "voice": resolved.config["voice"],
                        "secret_id": resolved.secret_id,
                    }
                )
        return spec.model_copy(update={"capabilities": bindings}), inherited

    async def for_run(self, organization_id: UUID, spec: AgentSpec, run: AgentRun) -> AgentSpec:
        """A delegated voice shares the run's pinned destination, never a new default."""
        if not any(
            binding.enabled
            and binding.id == "text_to_speech"
            and binding.config.get("use_organization_defaults") is True
            for binding in spec.capabilities
        ):
            return spec
        snapshot = (
            OrganizationTextToSpeech.model_validate(run.text_to_speech_defaults)
            if run.text_to_speech_defaults is not None
            else None
        )
        resolved, inherited = await self.resolve_spec(organization_id, spec, snapshot=snapshot)
        if snapshot is None and inherited is not None:
            await agent_run_repo.set_text_to_speech_defaults(
                self.db, run=run, defaults=inherited.model_dump(mode="json")
            )
        return resolved
