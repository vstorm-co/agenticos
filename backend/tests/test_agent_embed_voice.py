"""Voice calls on a widget or a hosted page: off until switched on, and only where a call would start (#54)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.schemas.agent_embed import PageConfig, SocketConfig, WidgetConfig
from app.services.agent_embed import AgentEmbedService, EmbedDenied

pytestmark = pytest.mark.anyio
_M = "app.services.agent_embed"


def _readiness(unavailable: str | None = None, transport: str | None = "webrtc"):
    return SimpleNamespace(
        available=unavailable is None, unavailable=unavailable, transport=transport
    )


def _embed(kind: str = "widget", **config):
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        agent_id=uuid4(),
        kind=kind,
        name="Help",
        public_key="key-123",
        is_active=True,
        auth_mode="public",
        allowed_origins=[] if kind == "page" else ["https://acme.test"],
        config={"kind": kind, **config},
        context_variables=[],
        logo_path=None,
    )


def _agent():
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        current_version_id=uuid4(),
        status="published",
        name="Helper",
        slug="helper",
        avatar_path=None,
        avatar_url=None,
        avatar_color=None,
    )


def _service() -> AgentEmbedService:
    return AgentEmbedService(MagicMock())


def test_an_embed_written_before_voice_existed_reads_as_off():
    assert WidgetConfig.model_validate({"kind": "widget"}).voice_conversation is False
    assert (
        PageConfig.model_validate({"kind": "page", "allow_voice": True}).voice_conversation is False
    )


@pytest.mark.parametrize("unavailable", ["no_voice", "no_key", "not_offered"])
async def test_switching_calls_on_is_refused_while_none_would_start(unavailable):
    agent = _agent()
    with (
        patch(
            f"{_M}.VoiceSettingsService.readiness", AsyncMock(return_value=_readiness(unavailable))
        ),
        pytest.raises(BadRequestError) as refused,
    ):
        await _service()._check_voice_conversation(
            agent, before=None, after=WidgetConfig(voice_conversation=True)
        )
    assert refused.value.details["fields"][0]["field"] == "config.voice_conversation"


async def test_switching_calls_on_where_one_would_start_is_accepted():
    with patch(f"{_M}.VoiceSettingsService.readiness", AsyncMock(return_value=_readiness())):
        await _service()._check_voice_conversation(
            _agent(), before=PageConfig(), after=PageConfig(voice_conversation=True)
        )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        # Already on: a key deleted since must not make the embed impossible to rename.
        (WidgetConfig(voice_conversation=True), WidgetConfig(voice_conversation=True, title="x")),
        (None, WidgetConfig()),
        (None, SocketConfig()),
    ],
    ids=["already-on", "off", "socket"],
)
async def test_only_switching_calls_on_is_checked(before, after):
    with patch(f"{_M}.VoiceSettingsService.readiness", AsyncMock()) as readiness:
        await _service()._check_voice_conversation(_agent(), before=before, after=after)
    readiness.assert_not_awaited()


async def test_the_public_config_offers_a_call_only_while_one_would_start():
    service = _service()
    embed = _embed()
    agent = _agent()
    with patch(f"{_M}.VoiceSettingsService.readiness", AsyncMock(return_value=_readiness())):
        assert await service._public_voice(embed, agent, enabled=True) == (True, "webrtc")
        assert await service._public_voice(embed, agent, enabled=False) == (False, None)
        assert await service._public_voice(embed, None, enabled=True) == (False, None)
        agent.status = "archived"
        assert await service._public_voice(embed, agent, enabled=True) == (False, None)
    with patch(
        f"{_M}.VoiceSettingsService.readiness",
        AsyncMock(return_value=_readiness("org_off", transport="webrtc")),
    ):
        assert await service._public_voice(embed, _agent(), enabled=True) == (False, None)


async def test_the_widget_and_the_page_are_told_about_calls():
    agent = _agent()
    with (
        patch(f"{_M}.agent_repo.get", AsyncMock(return_value=agent)),
        patch(
            f"{_M}.VoiceSettingsService.readiness",
            AsyncMock(return_value=_readiness(transport="relay")),
        ),
    ):
        widget = await _service().public_config(_embed("widget", voice_conversation=True))
        page = await _service().page_config(_embed("page", voice_conversation=True, logo="none"))
    assert (widget.voice_conversation, widget.voice_transport) == (True, "relay")
    assert (page.voice_conversation, page.voice_transport) == (True, "relay")


async def test_a_page_without_calls_says_so_without_asking_about_voice():
    with (
        patch(f"{_M}.agent_repo.get", AsyncMock(return_value=_agent())),
        patch(f"{_M}.VoiceSettingsService.readiness", AsyncMock()) as readiness,
    ):
        page = await _service().page_config(_embed("page", logo="none"))
    assert (page.voice_conversation, page.voice_transport) == (False, None)
    readiness.assert_not_awaited()


class TestAdmittingACall:
    async def test_a_widget_is_admitted_by_its_allow_list_and_its_switch(self):
        embed = _embed("widget", voice_conversation=True)
        with patch(f"{_M}.agent_embed_repo.get_by_key", AsyncMock(return_value=embed)):
            admission = await _service().admit_voice(
                "key-123", origin="https://acme.test", token=None, visitor_key=None
            )
        assert admission.embed is embed and admission.visitor is None

    @pytest.mark.security
    async def test_a_widget_from_another_site_is_refused(self):
        embed = _embed("widget", voice_conversation=True)
        with (
            patch(f"{_M}.agent_embed_repo.get_by_key", AsyncMock(return_value=embed)),
            pytest.raises(EmbedDenied),
        ):
            await _service().admit_voice(
                "key-123", origin="https://evil.test", token=None, visitor_key=None
            )

    async def test_a_page_is_admitted_from_this_deployment_with_a_visitor_key(self):
        embed = _embed("page", voice_conversation=True)
        with patch(f"{_M}.agent_embed_repo.get_by_key", AsyncMock(return_value=embed)):
            admission = await _service().admit_voice(
                "key-123", origin=settings.FRONTEND_URL, token=None, visitor_key="a" * 32
            )
            with pytest.raises(BadRequestError):
                await _service().admit_voice(
                    "key-123", origin=settings.FRONTEND_URL, token=None, visitor_key=None
                )
        assert admission.embed is embed

    @pytest.mark.security
    async def test_a_page_opened_from_another_site_is_refused(self):
        """A socket handshake has no preflight: the origin is what keeps other sites out."""
        embed = _embed("page", voice_conversation=True)
        with (
            patch(f"{_M}.agent_embed_repo.get_by_key", AsyncMock(return_value=embed)),
            pytest.raises(EmbedDenied),
        ):
            await _service().admit_voice(
                "key-123", origin="https://evil.test", token=None, visitor_key="a" * 32
            )

    @pytest.mark.parametrize(
        "embed",
        [
            _embed("widget"),
            _embed("socket"),
            SimpleNamespace(
                **{**_embed("widget", voice_conversation=True).__dict__, "is_active": False}
            ),
            None,
        ],
        ids=["calls-off", "socket", "paused", "unknown"],
    )
    async def test_everything_else_is_one_refusal(self, embed):
        with (
            patch(f"{_M}.agent_embed_repo.get_by_key", AsyncMock(return_value=embed)),
            pytest.raises(EmbedDenied),
        ):
            await _service().admit_voice(
                "key-123", origin="https://acme.test", token=None, visitor_key="a" * 32
            )


class TestTheCallScript:
    """`voice.js` is served only for an active widget whose calls are switched on."""

    async def test_a_widget_with_calls_on_gets_its_script(self):
        embed = _embed("widget", voice_conversation=True)
        with patch(f"{_M}.agent_embed_repo.get_by_key", AsyncMock(return_value=embed)):
            assert await _service().find_voice_widget("key-123") is embed

    @pytest.mark.parametrize(
        "embed",
        [
            _embed("widget"),
            _embed("page", voice_conversation=True),
            _embed("socket", voice_conversation=True),
            SimpleNamespace(
                **{**_embed("widget", voice_conversation=True).__dict__, "is_active": False}
            ),
            None,
        ],
        ids=["calls-off", "page", "socket", "paused", "unknown"],
    )
    async def test_anything_else_gets_none(self, embed):
        with patch(f"{_M}.agent_embed_repo.get_by_key", AsyncMock(return_value=embed)):
            assert await _service().find_voice_widget("key-123") is None


class TestCallsOnASave:
    """The switch is checked where it is saved, not only in the helper."""

    @pytest.mark.security
    async def test_creating_a_widget_with_calls_on_where_none_would_start_is_refused(self):
        from app.schemas.agent_embed import EmbedCreate

        agent = _agent()
        service = _service()
        with (
            patch.object(service.agents, "get", AsyncMock(return_value=agent)),
            patch(
                f"{_M}.VoiceSettingsService.readiness",
                AsyncMock(return_value=_readiness("org_off")),
            ) as readiness,
            patch(f"{_M}.agent_embed_repo.create", AsyncMock()) as created,
            pytest.raises(BadRequestError) as refused,
        ):
            await service.create(
                MagicMock(organization_id=uuid4()),
                EmbedCreate.model_validate(
                    {
                        "agent_id": str(agent.id),
                        "name": "Shop",
                        "config": {"kind": "widget", "voice_conversation": True},
                        "allowed_origins": ["https://shop.example"],
                    }
                ),
            )

        assert refused.value.details["fields"][0]["field"] == "config.voice_conversation"
        assert readiness.await_args.kwargs["agent"] is agent
        created.assert_not_awaited()

    @pytest.mark.security
    async def test_switching_calls_on_in_an_update_where_none_would_start_is_refused(self):
        from app.schemas.agent_embed import EmbedUpdate

        embed = _embed("page")
        service = _service()
        with (
            patch.object(service, "_owned", AsyncMock(return_value=embed)),
            patch.object(service.agents, "get", AsyncMock(return_value=_agent())),
            patch(
                f"{_M}.VoiceSettingsService.readiness",
                AsyncMock(return_value=_readiness("no_voice")),
            ),
            patch(f"{_M}.agent_embed_repo.update", AsyncMock()) as updated,
            pytest.raises(BadRequestError) as refused,
        ):
            await service.update(
                MagicMock(organization_id=uuid4()),
                embed.id,
                EmbedUpdate.model_validate(
                    {"config": {"kind": "page", "voice_conversation": True}}
                ),
            )

        assert refused.value.details["fields"][0]["field"] == "config.voice_conversation"
        updated.assert_not_awaited()
