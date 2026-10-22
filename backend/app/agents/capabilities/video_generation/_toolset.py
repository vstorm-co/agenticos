"""The `generate_video` tool, and the text the model reads before calling it.

The clip is made by the provider the binding chose, through
:func:`app.services.video_generation.generate_video`, and kept where a generated
image is kept (:mod:`app.agents.capabilities._generated`) - so a person watches it
where they would have seen the picture, and a later step finds it under `output/`.

**A clip can start from a picture the agent already has**: a file this
organization generated - the `filename` `generate_image` returned - or a path in
the run's workspace. That is what lets "draw a logo, then animate it" be two calls.

**The binding's settings are defaults the model may override.** The shapes are
the model's own; the resolutions are every one up to the highest the binding
allows, or every one the model renders where it sets none; the length runs to
the longest clip; sound can be asked for where the model makes it optional. The
shapes and resolutions are offered as an `enum` in the tool's schema with the
usual one as its default (:mod:`app.agents.capabilities._choices`), and a
parameter with nothing to choose is not offered at all.

**The budget is asked before the job is submitted, with the clip's price.** Video
is sold per second at a rate set by the resolution, so a clip's cost is known in
advance - at the model's longest where the model decides its own length - and a
run is refused one that would carry it past a cap. What it cost is booked after,
by the length the provider reports where it reports one.

**Whose mistake decides the shape of a failure** (`_failures.py`). A prompt, a
length, a ratio or an image the model can fix is steered, as is a provider that
is down. A refused key, a spent budget, a content-policy refusal and a job past
the binding's time limit are returned: the model cannot fix the first two, a
retry prompt on a refusal invites it to look for a way around one, and a retry of
a slow job is a second bill. A job past its time limit is still booked, at its
estimate: the provider may finish it and bill it after the call has given up.
"""

import asyncio
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ValidationError
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.workspaces import WorkspaceError

from app.agents.capabilities._choices import Choice, schema_for
from app.agents.capabilities._failures import steer
from app.agents.capabilities._generated import (
    WORKSPACE_OUTPUT_DIR,
    admit,
    store_generated,
)
from app.agents.capabilities.budget import can_afford_ambient_call, record_ambient_cost
from app.agents.deps import AgentDeps
from app.core.exceptions import NotFoundError
from app.services.file_storage import sniff_image_header
from app.services.generated_media import load_generated_media
from app.services.video_generation import (
    MAX_CLIP_BYTES,
    FirstFrame,
    VideoFailure,
    VideoProviderError,
    generate_video,
)
from app.services.video_models import by_provider, price_per_second

FRAME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
"""The images every provider here starts a clip from."""

MAX_FRAME_BYTES = 10 * 1024 * 1024
"""The largest starting image sent: every provider's own limit is at least this."""

RESERVED_BYTES_PER_SECOND = 2 * 1024 * 1024
"""What one second of a clip holds against the quota while it is made (#2310).

16 Mbit/s, past what the providers here encode even 1080p at, so the clip's
length - the model's longest where the model decides its own - times this
covers what is usually made. Never more than the most a clip download takes
(`MAX_CLIP_BYTES`). A clip larger than this is still recorded at its real size."""


@dataclass(frozen=True)
class VideoSettings:
    """What the binding decided: the defaults a clip gets, and the limits on what
    the model may ask for instead."""

    provider: str
    model: str
    resolution: str
    resolutions: tuple[str, ...]
    """What the model may ask for, shortest first: every resolution up to the
    binding's highest, or every one the model renders where it sets none."""

    aspect_ratio: str
    aspect_ratios: tuple[str, ...]
    """The shapes the model renders, which the model may ask for."""

    seconds: int
    max_seconds: int
    audio: bool | None
    audio_optional: bool
    """Whether the model makes sound optional, so a call may ask for it on or off."""

    timeout_seconds: int
    base_url: str | None = None
    """The provider's API base for this binding, where it is not the catalog's."""


class GeneratedVideo(BaseModel):
    """What `generate_video` returns - a reference to the clip, not the bytes.

    `filename` and `url` are absent only on a run with no organization to scope
    storage to (a preview, a test), where the clip was made but not kept.
    """

    kind: Literal["generated_video"] = "generated_video"
    filename: str | None = None
    url: str | None = None
    media_type: str = "video/mp4"
    prompt: str
    seconds: float | None = None
    resolution: str | None = None
    workspace_path: str | None = None


def parse_generated_video(result: str) -> GeneratedVideo | None:
    """Parse a `generate_video` result, or `None` for any other text."""
    try:
        payload = GeneratedVideo.model_validate_json(result)
    except ValidationError:
        return None
    return payload if payload.kind == "generated_video" else None


async def _frame_bytes(ctx: RunContext[AgentDeps], source: str) -> bytes | str:
    """The named file's bytes, or a sentence saying why there are none.

    An image this run's own tools generated is looked for first - a bare leaf name
    is what `generate_image` hands back - and only those: the store is
    organization-wide and the run may be driven by somebody who is not a member,
    so a leaf name somebody supplies, or that any other tool's output quotes, is
    never enough. Then the workspace, where a generated image is also kept under
    `output/` - which is how an image from an earlier turn is reached. A workspace
    file's size is read before its bytes, so a large one is refused unread.
    """
    organization_id = ctx.deps.organization_id
    if organization_id is not None and source in ctx.deps.generated_files:
        try:
            return await load_generated_media(organization_id, source)
        except NotFoundError:
            pass
    if ctx.workspace.attached:
        candidates = [source] if "/" in source else [source, f"{WORKSPACE_OUTPUT_DIR}/{source}"]
        for path in candidates:
            try:
                entry = await ctx.workspace.stat(path)
                if entry.size is not None and entry.size > MAX_FRAME_BYTES:
                    return _too_large(source)
                return await ctx.workspace.read_bytes(path)
            except FileNotFoundError, IsADirectoryError, NotADirectoryError:
                continue
            except PermissionError:
                return f"Reading {source!r} from your workspace was refused."
            except WorkspaceError as failed:
                return f"Reading {source!r} from your workspace failed: {failed}"
    return (
        f"There is no image called {source!r} generated in this run"
        + (" or in your workspace." if ctx.workspace.attached else ".")
        + " Use the `filename` generate_image returned, or a workspace path."
    )


def _too_large(source: str) -> str:
    return f"{source!r} is larger than {MAX_FRAME_BYTES // (1024 * 1024)} MB. Use a smaller image."


async def _read_frame(ctx: RunContext[AgentDeps], source: str) -> FirstFrame | str:
    """The starting image the model named, or a sentence saying why there is none.

    Typed by its bytes, never its name: a JPEG saved as `.png` is sent as a JPEG,
    and a file that is no image at all is refused here rather than by the provider.
    """
    data = await _frame_bytes(ctx, source)
    if isinstance(data, str):
        return data
    if len(data) > MAX_FRAME_BYTES:
        return _too_large(source)
    mime_type = sniff_image_header(data[:16])
    if mime_type not in FRAME_TYPES:
        return f"{source!r} is not a PNG, JPEG or WebP image."
    return FirstFrame(data=data, mime_type=mime_type)


def build_video_toolset(
    settings: VideoSettings, *, api_key: str | None
) -> FunctionToolset[AgentDeps]:
    """A `generate_video` tool bound to one provider, model and key.

    The model chooses what the clip shows and, within the binding's limits, how
    long it runs, its shape, its resolution, and the image it starts from.
    """
    ledger_name = f"{settings.provider}:{settings.model}"

    async def generate_video_tool(
        ctx: RunContext[AgentDeps],
        prompt: str,
        seconds: int | None = None,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
        audio: bool | None = None,
        first_frame: str | None = None,
    ) -> str:
        """Make a short video from a written description.

        Use this when the user asks for a video, an animation, a clip or a shot -
        not for a still picture, which is `generate_image`. Describe the shot in
        `prompt`: subject, action, camera movement, setting, light, style, and any
        sound. A clip takes minutes to make and is billed by the second, so make
        one when it is asked for, not to try something out. The interface stores
        the clip and plays it to the user, so say in one line what you made and
        leave the returned JSON alone.

        Args:
            prompt: What the video shows, as a director would describe the shot.
            seconds: How long it runs. Left out, the agent's usual length. A length
                outside what the model makes is refused with the range stated;
                a model that decides its own length ignores it.
            aspect_ratio: The shape, such as "16:9" or "9:16". Left out, the
                agent's usual shape.
            resolution: How sharp, such as "720p". Higher costs more per second,
                so ask for more only when the user wants it. Left out, the
                agent's usual resolution.
            audio: Whether the clip carries sound. Left out, the agent's usual
                setting.
            first_frame: An image to start from - the `filename` generate_image
                returned in this run, or a path in your workspace (where a
                generated image is also kept, under `output/`). PNG, JPEG or
                WebP.

        Returns:
            A JSON reference to the clip, already on its way to the user. Or, where
            nothing was made, a sentence saying why.
        """
        if api_key is None:
            return steer(ctx, "Video generation has no API key configured.")
        if not prompt.strip():
            return steer(ctx, "`prompt` is empty. Describe the shot to make.")
        entry = by_provider(settings.provider)
        model = entry.model(settings.model) if entry is not None else None
        if entry is None or model is None:
            return (
                "Not made: this agent's video model is no longer offered. Its author needs to "
                "choose another in the agent's settings."
            )

        duration: int | None = None
        if model.duration_choosable:
            duration = settings.seconds if seconds is None else seconds
            if not model.min_seconds <= duration <= settings.max_seconds:
                return steer(
                    ctx,
                    f"`seconds` must be {model.min_seconds} to {settings.max_seconds} for this "
                    "agent's video model.",
                )
        shape = aspect_ratio or settings.aspect_ratio
        if shape not in settings.aspect_ratios:
            return steer(ctx, f"`aspect_ratio` must be one of {', '.join(settings.aspect_ratios)}.")
        sharpness = resolution or settings.resolution
        if sharpness not in settings.resolutions:
            return steer(
                ctx,
                f"`resolution` must be one of {', '.join(settings.resolutions)}; this agent "
                "may use nothing higher.",
            )
        if audio is not None and not settings.audio_optional:
            return steer(ctx, "This agent's video model has no sound setting; leave `audio` out.")
        sound = settings.audio if audio is None else audio
        frame: FirstFrame | None = None
        if first_frame:
            if not model.first_frame:
                return steer(ctx, "This agent's video model cannot start from an image.")
            read = await _read_frame(ctx, first_frame)
            if isinstance(read, str):
                return steer(ctx, read)
            frame = read

        price = price_per_second(model, sharpness, on=datetime.now(UTC).date())
        priced_seconds = duration if duration is not None else model.max_seconds
        estimate = None if price is None else price * priced_seconds
        if not await can_afford_ambient_call(estimate or Decimal(0)):
            if estimate is None:
                return "Not made: this run has spent its budget."
            return (
                f"Not made: this clip would cost about ${estimate:.2f}, more than the budget "
                "this run has left."
            )

        slot = await admit(
            ctx,
            estimate_bytes=min(priced_seconds * RESERVED_BYTES_PER_SECOND, MAX_CLIP_BYTES),
            verdict="Not made",
        )
        if isinstance(slot, str):
            return slot
        async with slot:
            # How far the job got, as the client reports it: what the provider may
            # bill no longer depends on whether a clip comes back.
            stages: set[str] = set()
            try:
                clip = await generate_video(
                    entry,
                    model=settings.model,
                    prompt=prompt,
                    resolution=sharpness,
                    aspect_ratio=shape,
                    api_key=api_key,
                    timeout_seconds=settings.timeout_seconds,
                    duration=duration,
                    audio=sound,
                    first_frame=frame,
                    reached=stages.add,
                    base_url=settings.base_url,
                )
            except asyncio.CancelledError:
                # The run went away - a person pressed stop, a call hung up - while
                # the provider had the job. It may still finish and bill it, so its
                # estimate is booked, or the next clip would spend the same money.
                if stages & {"sent", "submitted"}:
                    record_ambient_cost(ledger_name, estimate)
                raise
            except VideoProviderError as exc:
                if "made" in stages:
                    # Finished and billed; only fetching the clip failed. Booked, and
                    # answered rather than retried: a second attempt is a second bill.
                    record_ambient_cost(ledger_name, estimate)
                    return (
                        "Not delivered: the video was made and billed, but it could not be "
                        "fetched from the provider. Tell the user rather than trying again - a "
                        "second attempt is billed again."
                    )
                if "sent" in stages:
                    # The request may have reached the provider with nothing to say
                    # whether a job came of it, so it is treated as one that did.
                    record_ambient_cost(ledger_name, estimate)
                    return (
                        "Not confirmed: the request reached the video provider, but its answer "
                        "was lost, so the video may still be made and billed. Tell the user "
                        "rather than trying again - a second attempt may be billed again."
                    )
                match exc.failure:
                    case VideoFailure.CREDENTIALS:
                        return (
                            "Not made: the video provider refused this agent's API key. Its author "
                            "needs to replace the key in the vault."
                        )
                    case VideoFailure.TIMED_OUT:
                        # Submitted and not cancelled in time, so possibly billed: an
                        # estimate booked is a cap held, where nothing booked would let
                        # the next clip spend the same money again.
                        if "submitted" in stages:
                            record_ambient_cost(ledger_name, estimate)
                        return (
                            f"Not made: the video was not ready within {settings.timeout_seconds} "
                            "seconds. Tell the user rather than trying again - a second attempt is "
                            "billed again."
                        )
                    case VideoFailure.POLICY:
                        return (
                            "Not made: the video provider's content policy refused this prompt "
                            "or image. Tell the user rather than rewording the same request."
                        )
                    case _:
                        return steer(
                            ctx, f"{exc.message} Try once more, or answer without a video."
                        )

            # The provider's own figure, within what the model can make: a negative or
            # non-finite length would hand budget back or poison the ledger.
            made_seconds = (
                min(clip.seconds, model.max_seconds)
                if clip.seconds is not None and math.isfinite(clip.seconds) and clip.seconds > 0
                else priced_seconds
            )
            record_ambient_cost(
                ledger_name, None if price is None else price * Decimal(str(made_seconds))
            )
            stored = await store_generated(ctx, clip.data, filename="video.mp4", slot=slot)
            return GeneratedVideo(
                filename=stored.filename,
                url=stored.url,
                prompt=prompt,
                seconds=clip.seconds,
                resolution=sharpness,
                workspace_path=stored.workspace_path,
            ).model_dump_json()

    toolset: FunctionToolset[AgentDeps] = FunctionToolset()
    # One clip at a time: the budget is asked with a clip's price and reserves
    # nothing, so two clips priced at once could each fit and together pass a cap.
    toolset.add_function(
        generate_video_tool,
        name="generate_video",
        takes_ctx=True,
        sequential=True,
        prepare=schema_for(
            {
                "aspect_ratio": Choice(settings.aspect_ratios, usual=settings.aspect_ratio),
                "resolution": Choice(settings.resolutions, usual=settings.resolution),
                # A model whose sound is fixed has nothing to choose.
                **({} if settings.audio_optional else {"audio": Choice((), usual="")}),
            }
        ),
    )
    return toolset
