"""Shared image execution; callers own authority, metering and file persistence.

Workflow submissions use an owned client with transport retries disabled and one
model request. A failed or lost answer must never silently become a second paid
image. Existing agent tools explicitly retain their established retry policy.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from google.genai import Client as GoogleClient
from google.genai.types import HttpOptions, HttpRetryOptions
from httpx2 import AsyncClient as ImageHTTPClient
from httpx2 import Response, Timeout
from openai import AsyncOpenAI
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.capabilities import NativeTool
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import BinaryContent, BinaryImage
from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.instrumented import InstrumentationSettings
from pydantic_ai.native_tools import ImageGenerationTool
from pydantic_ai.providers import infer_provider_class
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

_INSTRUCTIONS = "Generate an image based on the user prompt. Do not ask clarifying questions."


async def _refuse_redirect(response: Response) -> None:
    if response.is_redirect:
        raise UserError("The image provider redirected its paid request")


def _legacy_model(model_id: str, api_key: str) -> Model:
    """Preserve the existing agent provider factory, whose shared clients it owns."""
    return infer_model(
        model_id,
        # The SDK's abstract Provider lacks the concrete API-key constructor.
        # This is the existing agent factory; strict workflow clients are typed below.
        provider_factory=lambda name: infer_provider_class(name)(api_key=api_key),  # ty: ignore[unknown-argument]
    )


@asynccontextmanager
async def open_image_model(
    model_id: str, api_key: str, *, single_request: bool = True
) -> AsyncGenerator[Model]:
    """Open the chosen image model without an implicit paid-request retry.

    Strict mode supports the catalog's API-key image providers. Endpoints are
    explicit so SDK environment overrides cannot move the organization's key.
    Both sync and async Google transports belong to this context and are closed.
    Legacy agent mode retains the SDK factory and its shared-client lifecycle.
    """
    if not single_request:
        yield _legacy_model(model_id, api_key)
        return
    prefix, separator, name = model_id.partition(":")
    if not separator or not name:
        raise UserError("Choose a catalog image model")
    if prefix not in {"openai-responses", "google"}:
        raise UserError("This image provider has no single-request workflow transport")
    # A 307 redirect can repeat a paid POST even with SDK retries disabled.
    # The workflow's enclosing deadline remains authoritative for slow images.
    async with ImageHTTPClient(
        follow_redirects=False,
        timeout=Timeout(600.0, connect=5.0),
        event_hooks={"response": [_refuse_redirect]},
    ) as transport:
        if prefix == "openai-responses":
            async with AsyncOpenAI(
                api_key=api_key,
                base_url="https://api.openai.com/v1",
                max_retries=0,
                http_client=transport,
            ) as client:
                provider = OpenAIProvider(openai_client=client)
                yield infer_model(model_id, provider_factory=lambda _name: provider)
            return
        with GoogleClient(
            vertexai=False,
            api_key=api_key,
            http_options=HttpOptions(
                base_url="https://generativelanguage.googleapis.com",
                retry_options=HttpRetryOptions(attempts=1),
                httpx_async_client=transport,
            ),
        ) as google_client:
            async with google_client.aio:
                google_provider = GoogleProvider(client=google_client)
                yield infer_model(model_id, provider_factory=lambda _name: google_provider)


async def generate_image(
    model: Model,
    *,
    prompt: str,
    tool: ImageGenerationTool,
    reference_image: BinaryContent | None = None,
    instrument: InstrumentationSettings | bool | None = None,
    model_settings: ModelSettings | None = None,
    single_request: bool = True,
) -> BinaryImage:
    """Return one image without storing or charging it a second time.

    A reference is supplied as already-authorized bytes, never as a URL. Strict
    mode also disables model/output correction retries: an unusable response is
    terminal for this operation, even when a provider may already have billed it.
    The caller may wrap `model` once to account for its usage.
    """
    if single_request:
        model_settings = ModelSettings(**(model_settings or {}))
        if model_settings.get("extra_body") is not None:
            raise UserError("Workflow image settings cannot override the provider request body")
        # Per-request settings otherwise override the owned client's retry policy.
        model_settings["max_retries"] = 0
        if model.system == "openai":
            # The SDK merges these fields last, including over caller settings.
            # An omitted tier inherits project defaults, which may cost more
            # than the workflow's standard-price reservation.
            model_settings["extra_body"] = {"max_tool_calls": 1, "service_tier": "default"}
    agent: PydanticAgent[None, BinaryImage] = PydanticAgent(
        model,
        output_type=BinaryImage,
        capabilities=[NativeTool(tool)],
        instructions=_INSTRUCTIONS,
        model_settings=model_settings,
        retries=0 if single_request else None,
    )
    agent.instrument = instrument
    supplied = prompt if reference_image is None else [prompt, reference_image]
    if single_request:
        result = await agent.run(supplied, usage_limits=UsageLimits(request_limit=1))
    else:
        result = await agent.run(supplied)
    return result.output
