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
from app.db.models.agent import Agent, AgentStatus
from app.db.models.organization import Organization
from app.repositories import agent_repo, organization_secret_repo, voice_call_repo
from app.repositories import organization as organization_repo
from app.services import realtime_models
from app.services.realtime_models import RealtimeModelEntry, Transport
from app.services.spend import month_start
from app.services.voice import limits

VoiceUnavailable = Literal[
    "org_off", "not_in_chat", "no_voice", "not_offered", "no_key", "minutes_exhausted"
]


def voice_switched_on(organization: Organization | None, surface: Literal["web", "embed"]) -> bool:
    """Whether the organization's switches let a call run on `surface`.

    The one copy of the rule: readiness (the entry button, the embed form and the
    public config), a start and the heartbeat's mid-call revocation all read it,
    and must agree. The `/chat` switch binds the console's calls only.
    """
    return (
        organization is not None
        and organization.voice_conversations_enabled
        and (surface != "web" or organization.voice_in_chat)
    )


def agent_takes_calls(agent: Agent | None) -> bool:
    """Whether an agent has a published default version and is not archived."""
    return (
        agent is not None
        and agent.current_version_id is not None
        and agent.status != AgentStatus.ARCHIVED.value
    )


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
    """Whether a call to an agent would start and, if not, the first reason why.

    What the call button reads before it is offered. `cap_seconds` and
    `minutes_left` are as a new call would get them, before any reconnect.
    """

    available: bool
    unavailable: VoiceUnavailable | None
    transport: Transport | None
    provider: str | None
    model: str | None
    cap_seconds: int
    minutes_left: int | None


class VoiceSettingsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def published_spec(self, agent: Agent) -> AgentSpec | None:
        """The spec `/chat` would run: the default version, or `None` for none or archived."""
        # The second test only narrows the type: `agent_takes_calls` has made it.
        if not agent_takes_calls(agent) or agent.current_version_id is None:
            return None
        version = await agent_repo.get_version(
            self.db, agent.current_version_id, organization_id=agent.organization_id
        )
        return None if version is None else AgentSpec.model_validate(version.spec)

    async def minutes_left_seconds(self, organization: Organization) -> int | None:
        """Seconds left in this month's call minutes, or `None` when only budgets bind.

        Read on every heartbeat and every public config fetch, so the month's SUM
        is not run for an organization with no minutes cap to measure it against.
        """
        if organization.voice_monthly_minutes is None:
            return None
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
        unseals the key: a key deleted since keeps its id in the published spec,
        so its row is looked up and a missing one reads as `no_key`; one that no
        longer unseals is refused at start. A key's visibility is not read here
        or at start: once bound, a key is lent to whoever may run the agent, as a
        text run's is.
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
        if not voice_switched_on(organization, surface):
            reason = (
                "org_off"
                if organization is None or not organization.voice_conversations_enabled
                else "not_in_chat"
            )
        elif spec is None or spec.voice is None:
            reason = "no_voice"
        elif (
            spec.voice.secret_id is None
            or await organization_secret_repo.get(
                self.db, spec.voice.secret_id, organization_id=organization_id
            )
            is None
        ):
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
        )
