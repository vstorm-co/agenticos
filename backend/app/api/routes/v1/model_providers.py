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
from app.core.permissions import Perm
from app.schemas.model_profile import (
    ModelProfileCreate,
    ModelProfileList,
    ModelProfileRead,
    ProviderCatalog,
    ProviderInfo,
    ProviderModelList,
    ProviderModelRead,
)
from app.services.model_catalog import models_for
from app.services.model_profile import provider_catalog

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
        )
        for spec in provider_catalog()
    ]
    return ProviderCatalog(items=items, total=len(items))


@router.get(
    "/model-profiles",
    response_model=ModelProfileList,
    dependencies=[Depends(require(Perm.AGENTS_VIEW))],
)
async def list_model_profiles(service: ModelProfileSvc, ctx: Auth) -> Any:
    """Selectable models. Readable by anyone who can see agents - the Builder's dropdown."""
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
        params=data.params,
        allow_byo=data.allow_byo,
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
            ProviderModelRead(id=entry.id, name=entry.name, context_length=entry.context_length)
            for entry in models
        ],
        total=len(models),
        source=source,
    )
