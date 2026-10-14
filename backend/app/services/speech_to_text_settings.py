"""Which engine and language a recording is transcribed with, and why (#1797).

Three places can say: the organization, the agent a recording reaches, and the
channel bot it arrived on. This is the one place that decides between them, so
the composer's dictation, a channel voice note and the Voice cards showing what
is inherited cannot each grow their own idea of the order.

**The pair and the language resolve separately.** The provider and model go
together - a model is only meaningful on its provider - and come from the first
of bot, agent, organization that names one. The language comes from the agent,
then the organization, then nobody (the engine detects it). A bot has no
language of its own. So an agent that pins `pl` in an organization transcribing
on OpenAI in English gets OpenAI in Polish, which is the issue's own example.

**A bot resolves through its own agent**, the one its exposure serves - never
an agent somebody `@mentions`. Transcription runs before mention routing, and a
handle said aloud in a voice note could not be routed anyway. Which *version*
of that agent is read is the one the run will use: the exposure's environment
pins one, otherwise the default. A draft or archived agent has nothing
published to read: the composer is answered by the organization on its own,
and a bot is told nothing answers on it, so its voice notes are not paid for.

The engine choice for `/chat` (off, browser, server) and the longest dictation
stay the organization's; nothing here overrides them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import SpeechToTextSpec
from app.db.models.agent import Agent, AgentStatus
from app.db.models.agent_exposure import AgentExposure
from app.db.models.channel_bot import ChannelBot
from app.db.models.organization import Organization
from app.repositories import agent_environment_repo, agent_exposure_repo, agent_repo
from app.repositories import organization as organization_repo

PairSource = Literal["bot", "agent", "organization"]
LanguageSource = Literal["agent", "organization"]


@dataclass(frozen=True)
class ResolvedSpeechToText:
    """The engine a recording goes to, and which level chose each half."""

    provider: str
    model: str
    language: str | None
    """An ISO-639-1 code, or `None` for the engine to detect."""
    pair_source: PairSource
    language_source: LanguageSource | None
    """`None` when nobody pinned a language."""


@dataclass(frozen=True)
class BotSpeechToText:
    """What a channel bot's voice notes resolve to, and through which agent."""

    exposed: bool
    """Whether an agent answers on the bot: exposed, not archived, with a
    version to run. Without one every message is refused, so a voice note is
    not worth a paid transcription."""
    agent_name: str | None
    resolved: ResolvedSpeechToText | None
    agent_id: UUID | None = None
    """The agent the bot serves, which a voice note's usage row is attributed to."""


def resolve(
    *,
    organization: Organization,
    agent: SpeechToTextSpec | None,
    bot: ChannelBot | None = None,
) -> ResolvedSpeechToText | None:
    """The engine and language for one recording, or `None` when nothing resolves.

    Pure: the rows and the spec block come in, nothing is read. A bot switched
    off resolves to nothing whatever the others say - off is the bot operator's
    word, and it is final. A pair is taken as stored, even one the catalog has
    since withdrawn: falling through to the next level would quietly move a
    recording to a provider nobody chose for it, and the transcription itself
    refuses a withdrawn model by name.
    """
    if bot is not None and not bot.transcribe_voice_notes:
        return None

    pair: tuple[str, str, PairSource] | None = None
    if bot is not None and bot.speech_to_text_provider and bot.speech_to_text_model:
        pair = (bot.speech_to_text_provider, bot.speech_to_text_model, "bot")
    elif agent is not None and agent.provider and agent.model:
        pair = (agent.provider, agent.model, "agent")
    elif organization.speech_to_text_provider and organization.speech_to_text_model:
        pair = (
            organization.speech_to_text_provider,
            organization.speech_to_text_model,
            "organization",
        )
    if pair is None:
        return None

    language: str | None = None
    language_source: LanguageSource | None = None
    if agent is not None and agent.language:
        language, language_source = agent.language, "agent"
    elif organization.speech_to_text_language:
        language, language_source = organization.speech_to_text_language, "organization"

    provider, model, pair_source = pair
    return ResolvedSpeechToText(
        provider=provider,
        model=model,
        language=language,
        pair_source=pair_source,
        language_source=language_source,
    )


class SpeechToTextSettingsService:
    """Loads what `resolve` needs, for the three places that ask."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def for_agent(self, agent: Agent) -> ResolvedSpeechToText | None:
        """What dictation into this agent's composer transcribes with.

        Read from the agent's published default version, which is the one `/chat`
        runs - a draft change to the Voice card takes effect on publish, like
        every other spec field. The caller has already decided the person may
        reach this agent; this only reads.
        """
        organization = await self._organization(agent.organization_id)
        if organization is None:
            return None
        override = await self._override(agent, version_id=agent.current_version_id)
        return resolve(organization=organization, agent=override)

    async def for_bot(self, bot: ChannelBot, *, inherited: bool = False) -> BotSpeechToText:
        """What this bot's voice notes transcribe with, through the agent it serves.

        Args:
            bot: The bot, already loaded inside its organization.
            inherited: Answer as though the bot named no pair and were switched on
                - what choosing "inherit" would give, for the hint beside it.

        The exposure is read once. With none active the answer says so and
        resolves nothing, so the router skips a paid call for a message it is
        about to refuse. An agent archived, or with no version for the exposure
        to run, answers the same way - unlike `for_agent`, which falls back to
        the organization: a composer's member may still be shown what the
        organization would use, but a bot's run refuses the turn, and a voice
        note transcribed for it is a paid call for text nobody reads.
        """
        exposed = await agent_exposure_repo.list_active_for_bot(self.db, channel_bot_id=bot.id)
        organization = await self._organization(bot.organization_id)
        if not exposed or organization is None:
            return BotSpeechToText(exposed=bool(exposed), agent_name=None, resolved=None)
        # At most one, which `uq_exposure_bot` guarantees.
        exposure, agent = exposed[0]
        version_id = await self._exposed_version(exposure, agent)
        if version_id is None or agent.status == AgentStatus.ARCHIVED.value:
            return BotSpeechToText(exposed=False, agent_name=agent.name, resolved=None)
        override = await self._override(agent, version_id=version_id)
        resolved = resolve(
            organization=organization,
            agent=override,
            bot=None if inherited else bot,
        )
        return BotSpeechToText(
            exposed=True, agent_name=agent.name, agent_id=agent.id, resolved=resolved
        )

    async def _organization(self, organization_id: UUID) -> Organization | None:
        return await organization_repo.get_by_id(self.db, organization_id)

    async def _exposed_version(self, exposure: AgentExposure, agent: Agent) -> UUID | None:
        """The version a run through this exposure answers with.

        The exposure's environment pins one; without an environment it is the
        default, as `AgentRunnerService.execute` resolves it. An environment
        that has gone, or that belongs to another agent, falls back to the
        default rather than refusing: the run would refuse, and that refusal
        is the run's to make, not transcription's.
        """
        if exposure.environment_id is None:
            return agent.current_version_id
        environment = await agent_environment_repo.get(
            self.db, exposure.environment_id, organization_id=agent.organization_id
        )
        if environment is None or environment.agent_id != agent.id:
            return agent.current_version_id
        return environment.version_id

    async def _override(self, agent: Agent, *, version_id: UUID | None) -> SpeechToTextSpec | None:
        """The agent's speech-to-text block at one version, or `None`.

        `None` for an agent with nothing published or one archived: neither has
        a version anybody runs, so the organization answers alone rather than
        the recording being refused. Only the one block is parsed - it is the
        only part read, and a published spec passed publish validation whole.
        """
        if version_id is None or agent.status == AgentStatus.ARCHIVED.value:
            return None
        version = await agent_repo.get_version(
            self.db, version_id, organization_id=agent.organization_id
        )
        if version is None:
            return None
        block = version.spec.get("speech_to_text")
        return SpeechToTextSpec.model_validate(block) if block else None
