"""Generated photos reach the same channel picture path as charts and diagrams."""

from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image

from app.agents.capabilities.image_generation._toolset import GeneratedImage
from app.core.config import settings
from app.services.channels.mentions import drawn_picture
from app.services.generated_media import save_generated_media
from app.services.transcript import RecordedToolCall

pytestmark = pytest.mark.anyio


def receipt(filename: str | None, *, media_type: str = "image/png") -> RecordedToolCall:
    return RecordedToolCall(
        tool_call_id="photo",
        tool_name="generate_image",
        args={"prompt": "Coworkers carrying bags"},
        result=GeneratedImage(
            filename=filename, media_type=media_type, prompt="Coworkers carrying bags"
        ).model_dump_json(),
    )


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP"])
async def test_a_generated_photo_is_attached_as_a_real_png(
    monkeypatch: pytest.MonkeyPatch, tmp_path, format: str
) -> None:
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    organization = uuid4()
    buffer = BytesIO()
    Image.new("RGB", (32, 24), "red").save(buffer, format=format)
    filename = await save_generated_media(organization, buffer.getvalue(), filename="photo.img")
    notices: list[str] = []
    png = await drawn_picture(
        [receipt(filename)], organization_id=organization, conversation_id=None, notices=notices
    )
    assert png is not None
    with Image.open(BytesIO(png)) as image:
        assert image.format == "PNG" and image.size == (32, 24)
    assert notices == []


@pytest.mark.security
@pytest.mark.parametrize("filename", [None, "missing.png", "../other/private.png"])
async def test_an_unavailable_generated_photo_reports_the_delivery_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path, filename: str | None
) -> None:
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    notices: list[str] = []
    png = await drawn_picture(
        [receipt(filename)], organization_id=uuid4(), conversation_id=None, notices=notices
    )
    assert png is None
    assert len(notices) == 1 and "could not be attached" in notices[0]


@pytest.mark.security
async def test_a_generated_photo_from_another_tenant_is_not_attached(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    filename = await save_generated_media(uuid4(), b"private", filename="photo.png")
    notices: list[str] = []
    assert (
        await drawn_picture(
            [receipt(filename)], organization_id=uuid4(), conversation_id=None, notices=notices
        )
        is None
    )
    assert len(notices) == 1


@pytest.mark.parametrize("content", [b"not an image", b""])
async def test_invalid_media_does_not_silently_confirm_a_picture(
    monkeypatch: pytest.MonkeyPatch, tmp_path, content: bytes
) -> None:
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    organization = uuid4()
    filename = await save_generated_media(organization, content, filename="photo.png")
    notices: list[str] = []
    assert (
        await drawn_picture(
            [receipt(filename)], organization_id=organization, conversation_id=None, notices=notices
        )
        is None
    )
    assert len(notices) == 1


@pytest.mark.security
async def test_an_oversized_generation_is_refused_before_loading(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from app.services.channels.attachments import MAX_OUTBOUND_BYTES

    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    organization = uuid4()
    filename = await save_generated_media(
        organization, b"x" * (MAX_OUTBOUND_BYTES + 1), filename="large.png"
    )
    notices: list[str] = []
    assert (
        await drawn_picture(
            [receipt(filename)], organization_id=organization, conversation_id=None, notices=notices
        )
        is None
    )
    assert len(notices) == 1


async def test_a_failed_photo_cannot_be_replaced_by_an_unrelated_earlier_chart() -> None:
    from app.agents.capabilities.charts._spec import ChartSpec

    chart = RecordedToolCall(
        tool_call_id="chart",
        tool_name="create_chart",
        args={},
        result=ChartSpec(
            chart_type="bar",
            title="Earlier chart",
            data=[{"x": "A", "y": 1}],
            x_key="x",
            series=[{"key": "y"}],
        ).model_dump_json(),
    )
    notices: list[str] = []
    assert (
        await drawn_picture(
            [chart, receipt(None)], organization_id=uuid4(), conversation_id=None, notices=notices
        )
        is None
    )
    assert notices


async def test_delivery_notices_are_optional_for_callers() -> None:
    assert (
        await drawn_picture([receipt(None)], organization_id=uuid4(), conversation_id=None) is None
    )


async def test_a_malformed_image_receipt_reports_missing_delivery() -> None:
    call = RecordedToolCall(
        tool_call_id="photo", tool_name="generate_image", args={}, result="invalid result"
    )
    notices: list[str] = []
    assert (
        await drawn_picture([call], organization_id=uuid4(), conversation_id=None, notices=notices)
        is None
    )
    assert notices


def test_decoded_photo_size_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.channels import mentions

    buffer = BytesIO()
    Image.new("RGB", (2, 2)).save(buffer, format="PNG")
    monkeypatch.setattr(mentions, "MAX_OUTBOUND_BYTES", 1)
    with pytest.raises(ValueError, match="byte limit"):
        mentions._photo_png(buffer.getvalue())


@pytest.mark.security
def test_decoded_photo_pixel_count_is_bounded() -> None:
    from unittest.mock import MagicMock, patch

    from app.services.channels.mentions import _photo_png

    image = MagicMock(width=4097, height=4096)
    image.__enter__.return_value = image
    with (
        patch("app.services.channels.mentions.Image.open", return_value=image),
        pytest.raises(ValueError, match="pixel limit"),
    ):
        _photo_png(b"compressed image")


@pytest.mark.parametrize("platform", ["mattermost", "slack", "teams", "telegram"])
async def test_a_photo_approved_in_the_channel_reaches_the_resumed_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path, platform: str
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse, ToolCallPart

    from app.db.models.channel_prompt import APPROVAL
    from app.services.agent_runner import RunSegment
    from app.services.channels import prompts

    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    organization = uuid4()
    buffer = BytesIO()
    Image.new("RGB", (32, 24), "red").save(buffer, format="PNG")
    filename = await save_generated_media(organization, buffer.getvalue(), filename="photo.png")
    call = receipt(filename)
    paused = MagicMock(
        paused_state={
            "messages": ModelMessagesTypeAdapter.dump_python(
                [
                    ModelResponse(
                        parts=[
                            ToolCallPart("create_chart", {}, tool_call_id="already-delivered"),
                            ToolCallPart("generate_image", {}, tool_call_id=call.tool_call_id),
                        ]
                    )
                ],
                mode="json",
            ),
            "tool_call_ids": {str(uuid4()): call.tool_call_id},
        }
    )
    monkeypatch.setattr(prompts.agent_run_repo, "claim_parked_run", AsyncMock(return_value=paused))
    savepoint = MagicMock(is_active=True, commit=AsyncMock())
    service = prompts.ChannelPrompts(MagicMock(begin_nested=AsyncMock(return_value=savepoint)))
    segment = RunSegment(
        output="Four coworkers carrying bags.",
        run=MagicMock(conversation_id=None),
        tool_calls=[],
        settled={call.tool_call_id: call.result},
    )
    monkeypatch.setattr(service, "_decide", AsyncMock(return_value=segment))
    completed = await service._settle(MagicMock(), MagicMock(kind=APPROVAL), 0)
    assert completed is not None
    adapter = MagicMock(send_message=AsyncMock())
    monkeypatch.setattr(prompts, "get_adapter", lambda _: adapter)
    monkeypatch.setattr(prompts, "unseal_bot_token", lambda _: "test-token")
    await service._send_segment(
        MagicMock(organization_id=organization), platform, "channel:thread", completed
    )
    message = adapter.send_message.await_args.args[1]
    assert message.platform_chat_id == "channel:thread"
    assert message.image_png.startswith(b"\x89PNG")
    assert message.text == "Four coworkers carrying bags."


@pytest.mark.security
async def test_a_file_replaced_after_the_size_check_still_has_a_bounded_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from unittest.mock import AsyncMock

    from app.services import generated_media
    from app.services.channels.attachments import MAX_OUTBOUND_BYTES

    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    organization = uuid4()
    filename = await save_generated_media(
        organization, b"x" * (MAX_OUTBOUND_BYTES + 2), filename="large.png"
    )
    stored = await generated_media.open_generated_media(organization, filename)
    monkeypatch.setattr(
        generated_media,
        "open_generated_media",
        AsyncMock(
            return_value=generated_media.StoredGeneratedMedia(
                storage_path=stored.storage_path, size=1
            )
        ),
    )
    notices: list[str] = []
    assert (
        await drawn_picture(
            [receipt(filename)], organization_id=organization, conversation_id=None, notices=notices
        )
        is None
    )
    assert len(notices) == 1


async def test_the_storage_contract_can_return_a_plain_async_iterator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.services import generated_media
    from app.services.channels import mentions

    buffer = BytesIO()
    Image.new("RGB", (2, 2)).save(buffer, format="PNG")

    class Chunks:
        def __init__(self) -> None:
            self.done = False

        def __aiter__(self) -> Chunks:
            return self

        async def __anext__(self) -> bytes:
            if self.done:
                raise StopAsyncIteration
            self.done = True
            return buffer.getvalue()

    monkeypatch.setattr(
        generated_media,
        "open_generated_media",
        AsyncMock(
            return_value=generated_media.StoredGeneratedMedia(
                storage_path="test", size=buffer.tell()
            )
        ),
    )
    monkeypatch.setattr(
        mentions, "get_file_storage", lambda: MagicMock(open_range=AsyncMock(return_value=Chunks()))
    )
    assert (
        await drawn_picture([receipt("photo.png")], organization_id=uuid4(), conversation_id=None)
        is not None
    )


@pytest.mark.parametrize("resumed", [False, True])
async def test_an_adapter_failure_reports_unconfirmed_delivery_without_retrying_the_photo(
    monkeypatch: pytest.MonkeyPatch, resumed: bool
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.services.channels import prompts, router
    from app.services.channels.formatting import PICTURE_DELIVERY_UNCONFIRMED

    adapter = MagicMock(send_message=AsyncMock(side_effect=[OSError("upload failed"), None]))
    module = prompts if resumed else router
    monkeypatch.setattr(module, "get_adapter", lambda _: adapter)
    monkeypatch.setattr(module, "unseal_bot_token", lambda _: "test-token")
    bot = MagicMock()
    if resumed:
        monkeypatch.setattr(prompts, "drawn_picture", AsyncMock(return_value=b"png"))
        await prompts.ChannelPrompts(MagicMock())._send_segment(
            bot, "mattermost", "channel:thread", MagicMock(output="Ready", tool_calls=[])
        )
    else:
        await router.ChannelMessageRouter()._send_reply(
            bot,
            MagicMock(platform="mattermost", platform_chat_id="channel:thread"),
            "Ready",
            image_png=b"png",
        )
    original, notice = [call.args[1] for call in adapter.send_message.await_args_list]
    assert original.image_png == b"png"
    assert notice.image_png is None
    assert notice.text == PICTURE_DELIVERY_UNCONFIRMED
    assert notice.platform_chat_id == "channel:thread"


async def test_a_text_only_continuation_failure_still_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.services.channels import prompts

    monkeypatch.setattr(prompts, "drawn_picture", AsyncMock(return_value=None))
    monkeypatch.setattr(
        prompts,
        "get_adapter",
        lambda _: MagicMock(send_message=AsyncMock(side_effect=OSError("offline"))),
    )
    monkeypatch.setattr(prompts, "unseal_bot_token", lambda _: "test-token")
    with pytest.raises(OSError, match="offline"):
        await prompts.ChannelPrompts(MagicMock())._send_segment(
            MagicMock(), "mattermost", "channel:thread", MagicMock(output="Ready", tool_calls=[])
        )


async def test_media_read_timeouts_are_reported_without_regenerating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    from app.services.channels import mentions

    monkeypatch.setattr(mentions, "_generated_picture", AsyncMock(side_effect=TimeoutError))
    notices: list[str] = []
    assert (
        await drawn_picture(
            [receipt("photo.png")], organization_id=uuid4(), conversation_id=None, notices=notices
        )
        is None
    )
    assert len(notices) == 1
