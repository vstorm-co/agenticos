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

Where the image goes is two answers at once. It is always persisted
organization-scoped (:mod:`app.services.generated_media`) and returned as a
reference the interface renders. When the run also has a workspace open - an agent
with the sandbox capability - the same bytes are written into it under
`/output`, so a later `execute` step can use the image it just made: assemble it
into a PDF, a slide, a page. An agent without a workspace still generates and
shows images; it simply has nowhere to build with them, which is the honest
difference between the two.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import ModelRetry
from pydantic_ai.capabilities import NativeTool
from pydantic_ai.exceptions import UnexpectedModelBehavior, UserError
from pydantic_ai.messages import BinaryImage
from pydantic_ai.models import Model, infer_model
from pydantic_ai.native_tools import ImageGenerationTool
from pydantic_ai.providers import infer_provider_class
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai_backends import ensure_async

from app.agents.capabilities.budget import record_ambient_usage
from app.agents.deps import AgentDeps
from app.services.generated_media import generated_image_url, save_generated_image

WORKSPACE_OUTPUT_DIR = "output"
"""Where a generated image lands in the run's workspace, when there is one.

A single well-known directory so the model can be told where to look for what it
made without the path being an argument it has to remember and repeat.

Relative to the working directory, for the reason `UPLOAD_DIR` is: an absolute
path is resolved as absolute, which put a generated image outside the workspace -
unreachable by the agent's own shell, absent from the browser, and not in the
snapshot a channel diffs to decide what to post back (#1039).
"""

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
    workspace_backend: Any | None,
) -> FunctionToolset[Any]:
    """A `generate_image` tool bound to one image model and its key.

    Everything the model must not choose is closed over: the model, the key, the
    image settings and the workspace it may write into. The model chooses only the
    prompt.
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
            # publish and again at build. It is a `ModelRetry` rather than a crash
            # for the preview and test paths that build without a key: the run
            # survives, and nothing is spent or stored.
            raise ModelRetry("Image generation has no API key configured.")

        model = _build_image_model(model_id, api_key)
        agent: PydanticAgent[None, BinaryImage] = PydanticAgent(
            model,
            output_type=BinaryImage,
            capabilities=[NativeTool(ImageGenerationTool(**tool_settings))],
            instructions=_SUBAGENT_INSTRUCTIONS,
        )
        try:
            result = await agent.run(prompt)
        except (UserError, UnexpectedModelBehavior) as exc:
            # The image model refused or misbehaved - a bad prompt, an
            # unsupported setting. Hand it back for the model to rephrase rather
            # than ending the turn on an error string.
            raise ModelRetry(f"Image generation failed: {exc}") from exc

        image = result.output
        # Booked to the run's ledger, which the runner is holding open. The model
        # names itself and its provider (`model.system`), the hint `genai-prices`
        # prices from - the same shape the image describer books usage with. Image
        # models are frequently unpriced there, in which case this records at zero
        # and flags the run's cost as partial - the honest outcome, and the one
        # #58 asked to be sure of rather than assume.
        record_ambient_usage(model.model_name, result.usage, provider=model.system)

        image_format = image.format or "png"
        organization_id = ctx.deps.organization_id
        filename: str | None = None
        url: str | None = None
        if organization_id is not None:
            filename = await save_generated_image(
                organization_id, image.data, image_format=image_format
            )
            url = generated_image_url(filename)

        workspace_path: str | None = None
        if workspace_backend is not None:
            leaf = filename or f"image.{image_format}"
            workspace_path = f"{WORKSPACE_OUTPUT_DIR}/{leaf}"
            await ensure_async(workspace_backend).write(workspace_path, image.data)

        return GeneratedImage(
            filename=filename,
            url=url,
            media_type=image.media_type,
            prompt=prompt,
            workspace_path=workspace_path,
        ).model_dump_json()

    toolset: FunctionToolset[Any] = FunctionToolset()
    toolset.add_function(generate_image, takes_ctx=True)
    return toolset
