"""Which engine and language a recording resolves to, and through which agent (#1797).

The order is the contract: the pair from the bot, then the agent, then the
organization; the language from the agent, then the organization, then the
engine's own detection. A bot switched off resolves to nothing whatever the
others say. And a bot resolves through the agent its exposure serves, at the
version that exposure runs - the same one the runner would answer with.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.spec import SpeechToTextSpec
from app.services.speech_to_text_settings import (
    PairSource,
    ResolvedSpeechToText,
    SpeechToTextSettingsService,
    resolve,
)

pytestmark = pytest.mark.anyio

_ORG_ID = uuid.uuid4()
_ORG_KEY = uuid.uuid4()
_AGENT_KEY = uuid.uuid4()
_BOT_KEY = uuid.uuid4()
_MODULE = "app.services.speech_to_text_settings"


def _org(
    provider: str | None = "openai",
    model: str | None = "gpt-4o-transcribe",
    language: str | None = "en",
    secret_id: uuid.UUID | None = _ORG_KEY,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=_ORG_ID,
        speech_to_text_provider=provider,
        speech_to_text_model=model,
        speech_to_text_secret_id=secret_id if provider else None,
        speech_to_text_language=language,
    )


def _bot(
    *,
    transcribe: bool = True,
    provider: str | None = None,
    model: str | None = None,
    secret_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=_ORG_ID,
        transcribe_voice_notes=transcribe,
        speech_to_text_provider=provider,
        speech_to_text_model=model,
        speech_to_text_secret_id=secret_id,
    )


def _agent(*, status: str = "published", version_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=_ORG_ID,
        name="Support",
        status=status,
        current_version_id=version_id if version_id is not None else uuid.uuid4(),
    )


class TestThePair:
    def test_the_organization_answers_when_nobody_else_does(self):
        resolved = resolve(organization=_org(), agent=None)

        assert resolved == ResolvedSpeechToText(
            provider="openai",
            model="gpt-4o-transcribe",
            secret_id=_ORG_KEY,
            language="en",
            pair_source="organization",
            language_source="organization",
        )

    def test_the_agent_wins_over_the_organization(self):
        resolved = resolve(
            organization=_org(), agent=SpeechToTextSpec(provider="groq", model="whisper-large-v3")
        )

        assert resolved is not None
        assert (resolved.provider, resolved.model, resolved.pair_source) == (
            "groq",
            "whisper-large-v3",
            "agent",
        )

    def test_the_bot_wins_over_the_agent(self):
        resolved = resolve(
            organization=_org(),
            agent=SpeechToTextSpec(provider="groq", model="whisper-large-v3"),
            bot=_bot(provider="mistral", model="voxtral-mini-latest"),
        )

        assert resolved is not None
        assert (resolved.provider, resolved.pair_source) == ("mistral", "bot")

    def test_a_bot_with_no_pair_inherits_the_agents(self):
        resolved = resolve(
            organization=_org(),
            agent=SpeechToTextSpec(provider="groq", model="whisper-large-v3"),
            bot=_bot(),
        )

        assert resolved is not None
        assert resolved.pair_source == "agent"

    def test_an_agent_override_works_where_the_organization_has_no_pair(self):
        resolved = resolve(
            organization=_org(provider=None, model=None),
            agent=SpeechToTextSpec(provider="openai", model="whisper-1"),
        )

        assert resolved is not None
        assert resolved.model == "whisper-1"

    def test_a_half_pair_on_the_agent_is_passed_over(self):
        """A draft can hold one; a published spec cannot, but a half pair must never
        reach a provider as a model of `None`."""
        resolved = resolve(organization=_org(), agent=SpeechToTextSpec(provider="groq"))

        assert resolved is not None
        assert resolved.pair_source == "organization"

    def test_nothing_resolves_when_nobody_names_a_pair(self):
        assert (
            resolve(
                organization=_org(provider=None, model=None),
                agent=SpeechToTextSpec(language="pl"),
                bot=_bot(),
            )
            is None
        )

    def test_a_bot_switched_off_resolves_to_nothing_whatever_the_others_say(self):
        assert (
            resolve(
                organization=_org(),
                agent=SpeechToTextSpec(provider="groq", model="whisper-large-v3"),
                bot=_bot(transcribe=False),
            )
            is None
        )


class TestTheKeyGoesWithThePair:
    """A key is named at the level that names the pair, and never carries over."""

    def test_each_level_brings_its_own_key(self):
        agent = SpeechToTextSpec(provider="groq", model="whisper-large-v3", secret_id=_AGENT_KEY)
        bot = _bot(provider="mistral", model="voxtral-mini-latest", secret_id=_BOT_KEY)

        from_org = resolve(organization=_org(), agent=None)
        from_agent = resolve(organization=_org(), agent=agent)
        from_bot = resolve(organization=_org(), agent=agent, bot=bot)

        assert from_org is not None and from_agent is not None and from_bot is not None
        assert (from_org.secret_id, from_agent.secret_id, from_bot.secret_id) == (
            _ORG_KEY,
            _AGENT_KEY,
            _BOT_KEY,
        )

    def test_a_pair_with_no_key_does_not_borrow_another_levels(self):
        """A key reaches only the provider it was chosen for - so an agent's
        Groq pair with no key yet is not sent with the organization's OpenAI key."""
        resolved = resolve(
            organization=_org(), agent=SpeechToTextSpec(provider="groq", model="whisper-large-v3")
        )

        assert resolved is not None
        assert (resolved.provider, resolved.secret_id) == ("groq", None)

    def test_a_language_only_override_keeps_the_organizations_pair_and_key(self):
        resolved = resolve(organization=_org(), agent=SpeechToTextSpec(language="pl"))

        assert resolved is not None
        assert (resolved.provider, resolved.secret_id, resolved.language) == (
            "openai",
            _ORG_KEY,
            "pl",
        )

    @pytest.mark.parametrize(
        ("source", "shared"), [("organization", True), ("bot", True), ("agent", False)]
    )
    def test_only_an_agents_key_is_lent_rather_than_shared(self, source: PairSource, shared: bool):
        resolved = ResolvedSpeechToText(
            provider="openai",
            model="whisper-1",
            secret_id=_ORG_KEY,
            language=None,
            pair_source=source,
            language_source=None,
        )

        assert resolved.shared_key is shared


def _secret(**overrides: object) -> SimpleNamespace:
    row = {"name": "Team OpenAI", "kind": "api_key", "purpose": "openai", "visibility": "org"}
    row.update(overrides)
    return SimpleNamespace(**row)


class TestWhichKeyALevelMayName:
    """`key_problem`: the one check every level saves a key through."""

    async def _problem(self, row: object, *, ctx: object = None, access: bool = True) -> str | None:
        with (
            patch(f"{_MODULE}.organization_secret_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{_MODULE}.resolve_access", new=AsyncMock(return_value=access)) as checked,
        ):
            problem = await SpeechToTextSettingsService(MagicMock()).key_problem(
                uuid.uuid4(), organization_id=_ORG_ID, provider="openai", ctx=ctx
            )
        if ctx is None:
            checked.assert_not_awaited()
        return problem

    async def test_an_organization_visible_api_key_for_the_provider_is_accepted(self):
        assert await self._problem(_secret()) is None

    async def test_a_key_in_no_vault_of_this_organization_is_refused(self):
        assert await self._problem(None) == "That key is not in this organization's vault"

    @pytest.mark.parametrize("visibility", ["private", "team"])
    async def test_a_shared_level_refuses_a_key_not_everybody_can_see(self, visibility: str):
        problem = await self._problem(_secret(visibility=visibility))

        assert problem is not None
        assert "organization-wide" in problem

    async def test_a_key_of_another_kind_is_refused(self):
        problem = await self._problem(_secret(kind="azure_openai"))

        assert problem is not None
        assert "needs an API key" in problem

    async def test_a_key_for_another_provider_is_refused(self):
        problem = await self._problem(_secret(purpose="groq"))

        assert problem is not None
        assert "is a key for groq" in problem

    async def test_an_agents_key_may_be_private_when_the_publisher_can_view_it(self):
        assert await self._problem(_secret(visibility="private"), ctx=MagicMock()) is None

    async def test_a_key_the_publisher_cannot_view_reads_as_missing(self):
        """So a refusal cannot be used to enumerate somebody else's vault."""
        problem = await self._problem(_secret(), ctx=MagicMock(), access=False)

        assert problem == "That key is not in this organization's vault"


class TestTheLanguage:
    def test_the_agents_language_wins_and_keeps_the_organizations_pair(self):
        """The issue's example: a Polish agent in an English organization."""
        resolved = resolve(organization=_org(language="en"), agent=SpeechToTextSpec(language="pl"))

        assert resolved is not None
        assert (resolved.provider, resolved.language, resolved.language_source) == (
            "openai",
            "pl",
            "agent",
        )
        assert resolved.pair_source == "organization"

    def test_the_organizations_language_reaches_a_bot_with_its_own_pair(self):
        """A bot has no language field; the organization's applies to its pair too."""
        resolved = resolve(
            organization=_org(language="de"),
            agent=None,
            bot=_bot(provider="groq", model="whisper-large-v3"),
        )

        assert resolved is not None
        assert (resolved.language, resolved.language_source) == ("de", "organization")

    def test_nobody_pinning_a_language_leaves_the_engine_to_detect_it(self):
        resolved = resolve(organization=_org(language=None), agent=None)

        assert resolved is not None
        assert (resolved.language, resolved.language_source) == (None, None)


def _service() -> SpeechToTextSettingsService:
    return SpeechToTextSettingsService(MagicMock())


def _version(override: dict[str, str] | None) -> SimpleNamespace:
    spec: dict[str, object] = {"name": "Support"}
    if override is not None:
        spec["speech_to_text"] = override
    return SimpleNamespace(id=uuid.uuid4(), spec=spec)


class TestForAnAgent:
    async def test_the_published_default_version_is_read(self):
        agent = _agent()
        get_version = AsyncMock(return_value=_version({"language": "pl"}))
        with (
            patch(f"{_MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=_org())),
            patch(f"{_MODULE}.agent_repo.get_version", new=get_version),
        ):
            resolved = await _service().for_agent(agent)

        assert resolved is not None
        assert resolved.language == "pl"
        assert get_version.await_args.args[1] == agent.current_version_id
        assert get_version.await_args.kwargs["organization_id"] == _ORG_ID

    @pytest.mark.parametrize(
        "agent",
        [
            SimpleNamespace(
                id=uuid.uuid4(),
                organization_id=_ORG_ID,
                name="Draft",
                status="draft",
                current_version_id=None,
            ),
            _agent(status="archived"),
        ],
        ids=["never-published", "archived"],
    )
    async def test_an_agent_with_nothing_running_falls_back_to_the_organization(self, agent):
        get_version = AsyncMock()
        with (
            patch(f"{_MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=_org())),
            patch(f"{_MODULE}.agent_repo.get_version", new=get_version),
        ):
            resolved = await _service().for_agent(agent)

        assert resolved is not None
        assert resolved.pair_source == "organization"
        get_version.assert_not_awaited()

    async def test_a_version_that_cannot_be_read_falls_back_to_the_organization(self):
        """`get_version` is tenant-scoped, so another organization's version reads
        as missing here - and that agent's override is never applied."""
        with (
            patch(f"{_MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=_org())),
            patch(f"{_MODULE}.agent_repo.get_version", new=AsyncMock(return_value=None)),
        ):
            resolved = await _service().for_agent(_agent())

        assert resolved is not None
        assert resolved.pair_source == "organization"

    async def test_no_organization_resolves_nothing(self):
        with patch(f"{_MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)):
            assert await _service().for_agent(_agent()) is None


def _exposure(*, environment_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(environment_id=environment_id)


class TestForABot:
    async def test_a_bot_with_no_agent_bound_resolves_nothing_and_says_so(self):
        with (
            patch(
                f"{_MODULE}.agent_exposure_repo.list_active_for_bot",
                new=AsyncMock(return_value=[]),
            ),
            patch(f"{_MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=_org())),
        ):
            settings = await _service().for_bot(_bot())

        assert (settings.exposed, settings.resolved) == (False, None)

    async def test_a_bot_inherits_from_the_agent_it_serves(self):
        agent = _agent()
        with (
            patch(
                f"{_MODULE}.agent_exposure_repo.list_active_for_bot",
                new=AsyncMock(return_value=[(_exposure(), agent)]),
            ),
            patch(f"{_MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=_org())),
            patch(
                f"{_MODULE}.agent_repo.get_version",
                new=AsyncMock(
                    return_value=_version({"provider": "groq", "model": "whisper-large-v3"})
                ),
            ),
        ):
            settings = await _service().for_bot(_bot())

        assert settings.exposed is True
        assert settings.agent_name == "Support"
        assert settings.agent_id == agent.id
        assert settings.resolved is not None
        assert (settings.resolved.provider, settings.resolved.pair_source) == ("groq", "agent")

    async def test_an_environment_pinned_exposure_reads_that_environments_version(self):
        """The version the run will answer with, not the default of the moment."""
        agent = _agent()
        environment = SimpleNamespace(agent_id=agent.id, version_id=uuid.uuid4())
        get_version = AsyncMock(return_value=_version({"language": "pl"}))
        with (
            patch(
                f"{_MODULE}.agent_exposure_repo.list_active_for_bot",
                new=AsyncMock(return_value=[(_exposure(environment_id=uuid.uuid4()), agent)]),
            ),
            patch(f"{_MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=_org())),
            patch(f"{_MODULE}.agent_environment_repo.get", new=AsyncMock(return_value=environment)),
            patch(f"{_MODULE}.agent_repo.get_version", new=get_version),
        ):
            settings = await _service().for_bot(_bot())

        assert get_version.await_args.args[1] == environment.version_id
        assert settings.resolved is not None
        assert settings.resolved.language == "pl"

    @pytest.mark.parametrize("environment_agent", ["missing", "another-agent"])
    async def test_an_environment_that_is_not_this_agents_falls_back_to_the_default(
        self, environment_agent: str
    ):
        agent = _agent()
        environment = (
            None
            if environment_agent == "missing"
            else SimpleNamespace(agent_id=uuid.uuid4(), version_id=uuid.uuid4())
        )
        get_version = AsyncMock(return_value=_version(None))
        with (
            patch(
                f"{_MODULE}.agent_exposure_repo.list_active_for_bot",
                new=AsyncMock(return_value=[(_exposure(environment_id=uuid.uuid4()), agent)]),
            ),
            patch(f"{_MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=_org())),
            patch(f"{_MODULE}.agent_environment_repo.get", new=AsyncMock(return_value=environment)),
            patch(f"{_MODULE}.agent_repo.get_version", new=get_version),
        ):
            await _service().for_bot(_bot())

        assert get_version.await_args.args[1] == agent.current_version_id

    async def test_inherited_ignores_the_bots_own_pair_and_switch(self):
        """The hint beside "Inherit" answers what inheriting would give, whatever
        the bot is set to while somebody is deciding."""
        with (
            patch(
                f"{_MODULE}.agent_exposure_repo.list_active_for_bot",
                new=AsyncMock(return_value=[(_exposure(), _agent())]),
            ),
            patch(f"{_MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=_org())),
            patch(f"{_MODULE}.agent_repo.get_version", new=AsyncMock(return_value=_version(None))),
        ):
            settings = await _service().for_bot(
                _bot(transcribe=False, provider="groq", model="whisper-large-v3"), inherited=True
            )

        assert settings.resolved is not None
        assert settings.resolved.pair_source == "organization"

    @pytest.mark.parametrize(
        "agent",
        [
            SimpleNamespace(
                id=uuid.uuid4(),
                organization_id=_ORG_ID,
                name="Draft",
                status="draft",
                current_version_id=None,
            ),
            _agent(status="archived"),
        ],
        ids=["never-published", "archived"],
    )
    async def test_a_bot_whose_agent_runs_nothing_transcribes_nothing(self, agent):
        """Unlike the composer, no organization fallback: the run refuses the
        turn, so a voice note transcribed for it is paid for and never read."""
        get_version = AsyncMock()
        with (
            patch(
                f"{_MODULE}.agent_exposure_repo.list_active_for_bot",
                new=AsyncMock(return_value=[(_exposure(), agent)]),
            ),
            patch(f"{_MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=_org())),
            patch(f"{_MODULE}.agent_repo.get_version", new=get_version),
        ):
            settings = await _service().for_bot(_bot())

        assert (settings.exposed, settings.resolved) == (False, None)
        assert settings.agent_name == agent.name
        get_version.assert_not_awaited()
