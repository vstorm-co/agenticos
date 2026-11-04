"""Making one video through the provider a binding chose.

The facade over :mod:`.clients`: it checks the request against what the catalog
says the model can make, sets the deadline, and turns a transport failure into
the same refusal a provider's own error would be.
"""

import asyncio
import logging
from collections.abc import Callable

import httpx

from app.services.video_generation.clients import CLIENTS, Clip, FirstFrame, JobStage, VideoCall
from app.services.video_generation.exceptions import VideoFailure, VideoProviderError
from app.services.video_models import VideoProvider

logger = logging.getLogger(__name__)

REQUEST_SECONDS = 60.0
"""The client's default timeout for each phase of a request - connecting, sending,
the wait between two chunks of an answer. A status read and a download use
shorter, deadline-bound timeouts of their own; Gemini, which answers in the
submitting request itself, is given the rest of the job's deadline."""


async def generate_video(
    provider: VideoProvider,
    *,
    model: str,
    prompt: str,
    resolution: str,
    aspect_ratio: str,
    api_key: str,
    timeout_seconds: float,
    duration: int | None = None,
    audio: bool | None = None,
    first_frame: FirstFrame | None = None,
    reached: Callable[[JobStage], None] | None = None,
    base_url: str | None = None,
) -> Clip:
    """Make one clip with one provider's model, and return its bytes.

    Args:
        provider: The catalog entry, which says how to call it.
        model: A model the entry lists.
        prompt: What the clip shows.
        resolution: One the model renders.
        aspect_ratio: One the model renders.
        api_key: The binding's key, sent in a header and nowhere else.
        timeout_seconds: How long the whole job may take, polling included.
        duration: Seconds within the model's range. Ignored where the model
            decides its own length.
        audio: Whether the clip carries sound. Ignored where the model decides.
        first_frame: An image the clip starts from, for a model that takes one.
        reached: Told how far the job got - `sent`, `submitted`, then `made` - so a caller
            can book what the provider bills although no clip comes back.
        base_url: Where to call the provider instead of the catalog's address -
            an Alibaba workspace host.

    Raises:
        VideoProviderError: The provider refused, failed, timed out, or returned
            no video.
        ValueError: A request the catalog says the model cannot make - which the
            binding's validation and the tool refuse first.
    """
    chosen = provider.model(model)
    if chosen is None:
        raise ValueError(f"{provider.provider} does not offer {model}")
    if resolution not in chosen.resolutions or aspect_ratio not in chosen.aspect_ratios:
        raise ValueError(f"{model} does not render {resolution} at {aspect_ratio}")
    if duration is not None and not chosen.min_seconds <= duration <= chosen.max_seconds:
        raise ValueError(f"{model} makes {chosen.min_seconds}-{chosen.max_seconds} seconds")
    if first_frame is not None and not chosen.first_frame:
        raise ValueError(f"{model} does not start from an image")
    if not prompt.strip():
        raise ValueError("There is no prompt")
    call = VideoCall(
        provider=provider.provider,
        base_url=base_url or provider.base_url,
        api_key=api_key,
        model=model,
        prompt=prompt.strip(),
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        duration=duration if chosen.duration_choosable else None,
        audio=audio if chosen.audio == "optional" else None,
        first_frame=first_frame,
        **({} if reached is None else {"reached": reached}),
    )
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    try:
        async with httpx.AsyncClient(timeout=REQUEST_SECONDS) as client:
            return await CLIENTS[provider.api](client, call, deadline)
    except httpx.TimeoutException:
        # One slow request before the job's deadline is a provider having a bad
        # moment, not the job running past the time it was given.
        logger.warning("Video request to %s timed out", provider.provider, exc_info=True)
        failure = (
            VideoFailure.TIMED_OUT
            if asyncio.get_running_loop().time() >= deadline
            else VideoFailure.UNAVAILABLE
        )
        raise VideoProviderError(failure, provider=provider.provider) from None
    except httpx.HTTPError:
        logger.warning("Video request to %s failed in transit", provider.provider, exc_info=True)
        raise VideoProviderError(VideoFailure.UNAVAILABLE, provider=provider.provider) from None
