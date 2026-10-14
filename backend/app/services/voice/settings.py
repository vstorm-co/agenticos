"""Whether an agent can take a call, and on which model (#54).

The agent's Voice section is the only level that names a realtime model: there
is no organization default, because the organization's settings are limits, not
a model. So resolution is the published section alone, and readiness is that
plus the organization's switches and its remaining minutes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, VoiceSpec
from app.agents.voice import voice_unavailable
from app.db.models.agent import Agent, AgentStatus
from app.db.models.organization import Organization
from app.repositories import agent_repo, voice_call_repo
from app.repositories import organization as organization_repo
from app.services import realtime_models
from app.services.realtime_models import RealtimeModelEntry, Transport
from app.services.spend import month_start
from app.services.voice import limits

VoiceUnavailable = Literal[
    "org_off", "not_in_chat", "no_voice", "not_offered", "no_key", "minutes_exhausted"
]


@dataclass(frozen=True)
class ResolvedVoice:
    """A published Voice section a call can be built from."""

    provider: str
    model: str
    deployment: str | None
    secret_id: UUID
    voice: str
    language: str | None
    voice_note: str | None
    max_call_seconds: int | None
    entry: RealtimeModelEntry

    @property
    def wire_model(self) -> str:
        """What the provider is asked for: an Azure deployment name, or the model id."""
        return self.deployment or self.model

    @property
    def label(self) -> str:
        """How the run row and Activity name what answered."""
        return f"{self.entry.name} ({self.voice})"


def resolve_voice(block: VoiceSpec | None) -> ResolvedVoice | None:
    """The section as a call needs it, or `None` when it cannot hold one.

    Pure. A section publish would refuse - a pair outside the catalog, no key -
    resolves to nothing rather than to a call that fails while somebody talks.
    """
    if block is None or block.provider is None or block.secret_id is None:
        return None
    provider = realtime_models.by_provider(block.provider)
    if provider is None:
        return None
    catalog_model = block.base_model if provider.deployment else block.model
    if catalog_model is None or (provider.deployment and not block.deployment):
        return None
    entry = realtime_models.offered(block.provider, catalog_model)
    if entry is None:
        return None
    return ResolvedVoice(
        provider=block.provider,
        model=catalog_model,
        deployment=block.deployment if provider.deployment else None,
        secret_id=block.secret_id,
        voice=block.voice if block.voice in entry.voices else entry.default_voice,
        language=block.language,
        voice_note=block.voice_note,
        max_call_seconds=block.max_call_seconds,
        entry=entry,
    )


@dataclass(frozen=True)
class VoiceReadiness:
    available: bool
    unavailable: VoiceUnavailable | None
    transport: Transport | None
    provider: str | None
    model: str | None
    cap_seconds: int
    minutes_left: int | None
    unavailable_capabilities: list[str]


class VoiceSettingsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def published_spec(self, agent: Agent) -> AgentSpec | None:
        """The spec `/chat` would run: the default version, or `None` for none or archived."""
        if agent.current_version_id is None or agent.status == AgentStatus.ARCHIVED.value:
            return None
        version = await agent_repo.get_version(
            self.db, agent.current_version_id, organization_id=agent.organization_id
        )
        return None if version is None else AgentSpec.model_validate(version.spec)

    async def minutes_left_seconds(self, organization: Organization) -> int | None:
        used = await voice_call_repo.seconds_since(
            self.db, organization_id=organization.id, since=month_start()
        )
        return limits.minutes_left_seconds(
            monthly_minutes=organization.voice_monthly_minutes, used_seconds=used
        )

    async def readiness(
        self, *, organization_id: UUID, agent: Agent, surface: Literal["web", "embed"] = "web"
    ) -> VoiceReadiness:
        """Whether a call would start, from settings alone - the entry button reads this.

        The caller has already decided the person may run this agent. Never
        opens the vault: a key deleted since resolves its column to null and
        reads as `no_key`; a key made private since is refused at start.
        """
        organization = await organization_repo.get_by_id(self.db, organization_id)
        spec = await self.published_spec(agent)
        resolved = resolve_voice(None if spec is None else spec.voice)
        left = None if organization is None else await self.minutes_left_seconds(organization)
        cap = (
            0
            if organization is None
            else limits.call_cap_seconds(
                org_max=organization.voice_max_call_seconds,
                agent_max=None if resolved is None else resolved.max_call_seconds,
                chain_elapsed=0,
                minutes_left=left,
            )
        )
        reason: VoiceUnavailable | None = None
        if organization is None or not organization.voice_conversations_enabled:
            reason = "org_off"
        elif surface == "web" and not organization.voice_in_chat:
            reason = "not_in_chat"
        elif spec is None or spec.voice is None:
            reason = "no_voice"
        elif spec.voice.secret_id is None:
            reason = "no_key"
        elif resolved is None:
            reason = "not_offered"
        elif left is not None and left < limits.MIN_CALL_SECONDS:
            reason = "minutes_exhausted"
        return VoiceReadiness(
            available=reason is None,
            unavailable=reason,
            transport=None if resolved is None else resolved.entry.transport,
            provider=None if resolved is None else resolved.provider,
            model=None if resolved is None else resolved.model,
            cap_seconds=cap,
            minutes_left=None if left is None else left // 60,
            unavailable_capabilities=[] if spec is None else voice_unavailable(spec),
        )
