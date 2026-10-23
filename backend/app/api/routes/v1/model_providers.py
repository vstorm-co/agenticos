"""Settings -> AI providers: the models an organization can select.

Credentials are write-only from the API's point of view. They go in, they are
sealed, and what comes back is a label and four characters - there is no
endpoint that returns a secret, because no legitimate client needs one.

The catalog endpoint is what the model form is built from: it says which shape
of key each provider takes, so a Bedrock form asks for an AWS key
pair and an Ollama form asks for a URL and nothing else.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import Auth, ModelProfileSvc, SecretSvc, require
from app.api.public_api import PUBLIC
from app.core.permissions import Perm
from app.schemas.model_profile import (
    ImageModelRead,
    ImageProviderList,
    ImageProviderRead,
    ModelProfileCreate,
    ModelProfileList,
    ModelProfileRead,
    ProviderCatalog,
    ProviderInfo,
    ProviderModelList,
    ProviderModelRead,
    RealtimeModelRead,
    RealtimeProviderList,
    RealtimeProviderRead,
    SpeechToTextModelRead,
    SpeechToTextProviderList,
    SpeechToTextProviderRead,
    TextToSpeechModelRead,
    TextToSpeechProviderList,
    TextToSpeechProviderRead,
    TextToSpeechVoiceRead,
    VideoModelRead,
    VideoProviderList,
    VideoProviderRead,
)
from app.services import realtime_models
from app.services.image_models import image_providers
from app.services.model_catalog import models_for
from app.services.model_profile import provider_catalog
from app.services.speech_to_text import LANGUAGES as SPEECH_TO_TEXT_LANGUAGES
from app.services.speech_to_text import providers as speech_to_text_providers
from app.services.text_to_speech_models import providers as text_to_speech_providers
from app.services.video_models import providers as video_providers

router = APIRouter()


@router.get(
    "/catalog",
    response_model=ProviderCatalog,
    dependencies=[Depends(require(Perm.AGENTS_VIEW))],
)
async def list_provider_catalog() -> Any:
    """Every provider a credential can be stored for, and what it needs.

    Gated on `agents:view` rather than `connections:manage`: the Builder's
    model picker reads it to label a profile, and knowing that Bedrock takes an
    AWS key pair is not a secret.
    """
    items = [
        ProviderInfo(
            id=spec.id,
            name=spec.name,
            secret_kind=spec.secret_kind,
            supports_base_url=spec.supports_base_url,
            keyless=spec.keyless,
            apis=list(spec.apis),
            native_api=spec.native_api,
        )
        for spec in provider_catalog()
    ]
    return ProviderCatalog(items=items, total=len(items))


@router.get(
    "/model-profiles",
    response_model=ModelProfileList,
    dependencies=[PUBLIC, Depends(require(Perm.AGENTS_VIEW))],
)
async def list_model_profiles(service: ModelProfileSvc, ctx: Auth) -> Any:
    """Selectable models. Readable by anyone who can see agents - the Builder's dropdown.

    Public, so a key - and the Architect, choosing the model a draft publishes
    on - can read which models the organization has (#2301).
    """
    items = await service.list_profiles(ctx)
    return ModelProfileList(items=items, total=len(items))


@router.post(
    "/model-profiles",
    response_model=ModelProfileRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def create_model_profile(
    data: ModelProfileCreate, service: ModelProfileSvc, ctx: Auth
) -> Any:
    """Define a selectable model backed by one of the organization's keys."""
    return await service.create_profile(
        ctx,
        label=data.label,
        provider=data.provider,
        model=data.model,
        secret_id=data.secret_id,
        base_url=data.base_url,
        api=data.api,
        params=data.params,
        fallback_profile_ids=data.fallback_profile_ids,
    )


@router.delete(
    "/model-profiles/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def delete_model_profile(profile_id: UUID, service: ModelProfileSvc, ctx: Auth) -> None:
    await service.delete_profile(ctx, profile_id)


@router.get(
    "/image-models",
    response_model=ImageProviderList,
    dependencies=[Depends(require(Perm.AGENTS_VIEW))],
)
async def list_image_models() -> Any:
    """Which providers can draw an image, and which of their models may be asked to.

    Answered here rather than decided in the console, because both halves are the
    platform's: whether a provider's model class honours the image tool is
    `supported_native_tools()` on the SDK, and which models it offers is
    `app/core/catalog/image_models.json`. A console that kept either would be a
    second copy - one that an SDK upgrade makes wrong, and one that makes adding a
    model released this morning a frontend release.

    No credential is read: this is a catalog, not a listing. It says nothing about
    what the organization has a key for - the secret field beside it does that.

    Declared before `/{provider}/models`, because that path would otherwise match
    "image-models" as a provider.
    """
    providers = image_providers()
    return ImageProviderList(
        items=[
            ImageProviderRead(
                provider=entry.provider,
                name=entry.name,
                models=[
                    ImageModelRead(id=model.id, name=model.name, description=model.description)
                    for model in entry.models
                ],
            )
            for entry in providers
        ],
        total=len(providers),
    )


@router.get(
    "/speech-to-text-models",
    response_model=SpeechToTextProviderList,
    dependencies=[Depends(require(Perm.AGENTS_VIEW))],
)
async def list_speech_to_text_models() -> Any:
    """Which providers can transcribe a voice note, and with which models.

    The same shape and the same reasoning as `/image-models`: both halves are the
    platform's, so a console that kept either would hold a copy that a catalog
    change makes wrong. The filtering matters more here than the listing does - an
    entry whose credential is not a plain API key, or whose API shape has no
    client, is dropped, because a picker entry that fails when somebody sends a
    voice note is worse than one that is absent.

    No credential is read. This says what the deployment can offer; the key a
    pair is sent with is chosen beside it, from the vault keys whose purpose is
    the provider, and the picker that offers them is what says a provider has
    none.

    `languages` is the ISO-639-1 codes a recording may be pinned to, which an
    organization's dictation settings choose from.

    Declared before `/{provider}/models`, which would otherwise match
    "speech-to-text-models" as a provider.
    """
    offered = speech_to_text_providers()
    return SpeechToTextProviderList(
        items=[
            SpeechToTextProviderRead(
                provider=entry.provider,
                name=entry.name,
                models=[
                    SpeechToTextModelRead(
                        id=model.id, name=model.name, description=model.description
                    )
                    for model in entry.models
                ],
            )
            for entry in offered
        ],
        total=len(offered),
        languages=list(SPEECH_TO_TEXT_LANGUAGES),
    )


@router.get(
    "/realtime-models",
    response_model=RealtimeProviderList,
    dependencies=[Depends(require(Perm.AGENTS_VIEW))],
)
async def list_realtime_models() -> Any:
    """Which providers can hold a voice conversation, with which models and voices.

    The same shape and reasoning as `/speech-to-text-models`. No credential is
    read; the key is chosen beside the pair, from vault keys whose purpose is
    the provider. Declared before `/{provider}/models`.
    """
    offered = realtime_models.providers()
    return RealtimeProviderList(
        items=[
            RealtimeProviderRead(
                provider=entry.provider,
                name=entry.name,
                secret_kind=entry.secret_kind.value,
                deployment=entry.deployment,
                models=[
                    RealtimeModelRead(
                        id=model.id,
                        name=model.name,
                        description=model.description,
                        transport=model.transport,
                        voices=list(model.voices),
                        default_voice=model.default_voice,
                        supports_thinking=model.supports_thinking,
                        input_sample_rate=model.input_sample_rate,
                        output_sample_rate=model.output_sample_rate,
                    )
                    for model in entry.models
                ],
            )
            for entry in offered
        ],
        total=len(offered),
    )


@router.get(
    "/text-to-speech-models",
    response_model=TextToSpeechProviderList,
    dependencies=[Depends(require(Perm.AGENTS_VIEW))],
)
async def list_text_to_speech_models() -> Any:
    """Which providers can speak a text aloud, with which models, voices and formats.

    The same shape and the same reasoning as `/image-models`: the catalog is the
    platform's, so a console that kept a copy would hold one a catalog change makes
    wrong. Voices are listed per model because OpenAI's older models speak in only
    some of its voices. A provider whose voices belong to the account - ElevenLabs -
    lists none and says so in `account_voices`, and a binding names one by id.

    No credential is read. This says what the deployment can offer, not what this
    organization has a key for - the secret field beside it does that.

    Declared before `/{provider}/models`, which would otherwise match
    "text-to-speech-models" as a provider.
    """
    offered = text_to_speech_providers()
    return TextToSpeechProviderList(
        items=[
            TextToSpeechProviderRead(
                provider=entry.provider,
                name=entry.name,
                formats=list(entry.formats),
                account_voices=entry.account_voices,
                models=[
                    TextToSpeechModelRead(
                        id=model.id,
                        name=model.name,
                        description=model.description,
                        max_characters=model.max_characters,
                        takes_instructions=model.takes_instructions,
                        voices=[
                            TextToSpeechVoiceRead(
                                id=voice.id, name=voice.name, description=voice.description
                            )
                            for voice in entry.voices_for(model)
                        ],
                    )
                    for model in entry.models
                ],
            )
            for entry in offered
        ],
        total=len(offered),
    )


@router.get(
    "/video-models",
    response_model=VideoProviderList,
    dependencies=[Depends(require(Perm.AGENTS_VIEW))],
)
async def list_video_models() -> Any:
    """Which providers can make a video, and what each of their models can make.

    The same shape and the same reasoning as `/image-models`. Each model states the
    lengths, aspect ratios and resolutions it takes and whether its clips carry
    sound, because the providers differ on every one and the Builder offers only
    what the chosen model can make. No credential is read.

    Declared before `/{provider}/models`, which would otherwise match
    "video-models" as a provider.
    """
    offered = video_providers()
    return VideoProviderList(
        items=[
            VideoProviderRead(
                provider=entry.provider,
                name=entry.name,
                models=[
                    VideoModelRead(
                        id=model.id,
                        name=model.name,
                        description=model.description,
                        min_seconds=model.min_seconds,
                        max_seconds=model.max_seconds,
                        duration_choosable=model.duration_choosable,
                        aspect_ratios=list(model.aspect_ratios),
                        resolutions=list(model.resolutions),
                        audio=model.audio,
                        first_frame=model.first_frame,
                    )
                    for model in entry.models
                ],
            )
            for entry in offered
        ],
        total=len(offered),
    )


@router.get(
    "/{provider}/models",
    response_model=ProviderModelList,
    dependencies=[Depends(require(Perm.AGENTS_VIEW))],
)
async def list_provider_models(provider: str, secrets: SecretSvc, ctx: Auth) -> Any:
    """What this provider offers, for the field where a model id is chosen.

    Suggestions, not a constraint - the field stays free text, because a
    provider ships a model the morning after this was cached. `source` says
    whether the provider answered or the deployment's own list was used, so the
    UI can be honest about which it is showing.

    The key comes from the vault, when the listing needs one and the
    organization has one. Nothing here opens it: the vault service hands back a
    bearer token for this one outbound request, and providers that publish a
    public list (OpenRouter) are asked without one.
    """
    api_key = await secrets.listing_key(ctx, provider)
    models, source = await models_for(provider, api_key=api_key)
    return ProviderModelList(
        items=[
            ProviderModelRead(
                id=entry.id,
                name=entry.name,
                context_length=entry.context_length,
                output_modalities=list(entry.output_modalities),
            )
            for entry in models
        ],
        total=len(models),
        source=source,
    )
