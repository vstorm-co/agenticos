"""The `generate_image` tool, and the text the model reads before calling it.

The image is produced by a **subagent** running a dedicated image model, not by
the agent's own model. That is the one shape that works everywhere: native image
generation is only offered by a handful of models, it is delivered as a provider
tool the run's budget guard prices as part of the main request, and its result
never passes through this code - so it can be neither stored tenant-scoped nor
placed in the workspace. A local subagent can, at the cost that this code has to
meter it: the library's own `image_generation_tool` discards the subagent's usage
(`result.output` and nothing else), which is exactly the invisible spend #16 was.
So the subagent is run here rather than reused, and its usage is booked to the
run's ledger through :func:`record_ambient_usage` - the runner holds a
`metered_by` block open around the whole run, so a tool call inside it reaches the
same ledger the main model requests do.

Where the image goes is two answers at once - stored organization-scoped and,
when a workspace is open, written under `output/` as well - and it is the same
answer for speech and video, so it lives in :mod:`app.agents.capabilities._generated`.
A later `execute` step can then use the image it just made: assemble it into a
PDF, a slide, a page.
"""

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.capabilities import NativeTool
from pydantic_ai.exceptions import UnexpectedModelBehavior, UserError
from pydantic_ai.messages import BinaryImage
from pydantic_ai.models import Model, infer_model
from pydantic_ai.native_tools import ImageGenerationTool
from pydantic_ai.providers import infer_provider_class
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._failures import steer
from app.agents.capabilities._generated import admit, store_generated
from app.agents.capabilities._metered import MeteredModel
from app.agents.capabilities.budget import can_afford_ambient_call
from app.agents.deps import AgentDeps
from app.agents.observability import inherited_instrumentation

logger = logging.getLogger(__name__)

RESERVED_BYTES = 16 * 1024 * 1024
"""What one image holds against the quota while it is drawn (#2310).

The image models here answer at most a few megapixels - a PNG of a 4096-pixel
square at its worst runs to tens of megabytes, a typical answer to one or two -
so a flat 16 MiB covers what is usually made with room to spare. An image larger
than this is still recorded at its real size."""

_SUBAGENT_INSTRUCTIONS = (
    "Generate an image based on the user prompt. Do not ask clarifying questions."
)


class GeneratedImage(BaseModel):
    """What `generate_image` returns - a reference to the image, not the bytes.

    The interface renders the image from `url`; the model is told to describe
    what it made and leave this payload alone, the way a chart result is handled.
    `filename` and `url` are absent only on a run with no organization to scope
    storage to (a preview, a test), where the image was generated but not kept.
    """

    kind: Literal["generated_image"] = "generated_image"
    filename: str | None = None
    url: str | None = None
    media_type: str
    prompt: str
    workspace_path: str | None = Field(
        default=None,
        description="Where the image was written in the workspace, if one was open.",
    )


def parse_generated_image(result: str) -> GeneratedImage | None:
    """Parse a `generate_image` tool result back into a model.

    Returns `None` for an error string or any other tool's result, so a consumer
    - the chat, a channel adapter - falls back to plain text rather than raising.
    """
    try:
        payload = GeneratedImage.model_validate_json(result)
    except ValidationError:
        return None
    return payload if payload.kind == "generated_image" else None


def _build_image_model(model_id: str, api_key: str) -> Model:
    """A model client for one image model, authenticated with the org's key.

    `infer_model` parses the provider prefix (`openai-responses:`, `google:`) and
    hands the provider name to the factory, which builds the provider class with
    the key - the same indirection the main model resolver uses, without going
    through the profile catalog a chat model is resolved from.
    """
    return infer_model(
        model_id,
        # Every provider reachable here takes `api_key`, but the inferred class is
        # the abstract `Provider`, whose only `__init__` is `object`'s - the same
        # gap `model_resolver._build_provider` documents.
        provider_factory=lambda name: infer_provider_class(name)(api_key=api_key),  # ty: ignore[unknown-argument]
    )


def build_image_toolset(
    *,
    model_id: str,
    api_key: str | None,
    tool_settings: dict[str, Any],
) -> FunctionToolset[Any]:
    """A `generate_image` tool bound to one image model and its key.

    Everything the model must not choose is closed over: the model, the key and the
    image settings. The model chooses only the prompt.
    """

    async def generate_image(ctx: RunContext[AgentDeps], prompt: str) -> str:
        """Generate an image from a written description.

        Use this when the user asks for a picture, illustration, logo, icon,
        concept art or any visual that should be *drawn* - not for plotting
        numbers you already have, which is `create_chart`. Put the whole
        description in `prompt`: subject, style, composition, colours, mood. The
        interface generates the image, stores it and shows it to the user, so say
        in one line what you made and leave the returned JSON alone - the user is
        looking at the picture, not the payload.

        Args:
            prompt: A detailed description of the image to generate.

        Returns:
            A JSON reference to the generated image, already on its way to the
            user.
        """
        if api_key is None:
            # Unreachable once published - a missing required secret is refused at
            # publish and again at build. It is a retry rather than a crash for
            # the preview and test paths that build without a key: the run
            # survives, and nothing is spent or stored.
            return steer(ctx, "Image generation has no API key configured.")
        if not await can_afford_ambient_call():
            return "Not made: this run has spent its budget."
        slot = await admit(ctx, estimate_bytes=RESERVED_BYTES, verdict="Not made")
        if isinstance(slot, str):
            return slot
        async with slot:
            model = MeteredModel(_build_image_model(model_id, api_key))
            agent: PydanticAgent[None, BinaryImage] = PydanticAgent(
                model,
                output_type=BinaryImage,
                capabilities=[NativeTool(ImageGenerationTool(**tool_settings))],
                instructions=_SUBAGENT_INSTRUCTIONS,
            )
            agent.instrument = inherited_instrumentation(ctx.agent)
            try:
                result = await agent.run(prompt)
            except (UserError, UnexpectedModelBehavior) as exc:
                # The image model refused or misbehaved - a bad prompt, an
                # unsupported setting. Hand it back for the model to rephrase rather
                # than ending the turn on an error string. Its own text does not
                # travel: on the last attempt `steer` returns this rather than
                # raising it, and a returned string is stored and streamed verbatim
                # where a retry prompt is replaced with a notice (#681, #695).
                logger.exception("Image generation failed")
                return steer(
                    ctx,
                    f"Image generation failed ({type(exc).__name__}). "
                    "Rephrase the prompt, or answer without an image.",
                )

            image = result.output
            image_format = image.format or "png"
            stored = await store_generated(
                ctx, image.data, filename=f"image.{image_format}", slot=slot
            )

            return GeneratedImage(
                filename=stored.filename,
                url=stored.url,
                media_type=image.media_type,
                prompt=prompt,
                workspace_path=stored.workspace_path,
            ).model_dump_json()

    toolset: FunctionToolset[Any] = FunctionToolset()
    toolset.add_function(generate_image, takes_ctx=True)
    return toolset
