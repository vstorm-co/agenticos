"""Settings -> Secrets: credentials a custom capability needs.

Write-only from the API's point of view. A value goes in, it is sealed, and what
comes back is a name, a kind and four characters. There is no endpoint that
returns a plaintext, because no client needs one: the only reader is the agent
runner, which injects it into the capability instance that declared it.

A secret is now a *shared resource* like an agent or a skill: it has an owner, a
visibility and grants. So the collection routes carry a role gate on
`secrets:view` / `secrets:edit`, and everything acting on one row hands the
decision to the service, which resolves it against that row - a role gate there
would refuse a member holding an explicit grant before `resolve_access` could
widen their access.

The catalogs (`/kinds`, `/purposes`) describe the deployment rather than the
tenant, and are readable by anyone who may see a secret at all.

A ChatGPT sign-in (`/openai-codex`) is the one secret nobody types: the value is
an OAuth grant, so it is stored by finishing a sign-in rather than by posting it.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Auth, OpenAICodexSvc, SecretSvc, require
from app.core.permissions import Perm
from app.core.secret_kinds import describe_kinds
from app.core.secret_purposes import all_purposes
from app.db.models.resource_grant import Visibility
from app.schemas.secret import (
    OpenAICodexSecretCreate,
    OpenAICodexSecretReconnect,
    OpenAICodexSignIn,
    SecretCreate,
    SecretKindList,
    SecretList,
    SecretPurposeList,
    SecretPurposeRead,
    SecretRead,
    SecretUpdate,
)

router = APIRouter()


@router.get(
    "/kinds",
    response_model=SecretKindList,
    dependencies=[Depends(require(Perm.SECRETS_VIEW))],
)
async def list_secret_kinds() -> Any:
    """The shapes a secret can have, and the JSON Schema each form is built from."""
    items = describe_kinds()
    return SecretKindList(items=items, total=len(items))


@router.get(
    "/purposes",
    response_model=SecretPurposeList,
    dependencies=[Depends(require(Perm.SECRETS_VIEW))],
)
async def list_secret_purposes() -> Any:
    """What a secret can be for - model providers, services, and `custom`.

    Served rather than hard-coded in the client because the model providers are
    generated from the same table the runtime builds clients out of: a second
    copy in the frontend would drift the moment a provider is added, leaving a
    model nobody can key.
    """
    items = [
        SecretPurposeRead(
            id=entry.id,
            label=entry.label,
            category=entry.category.value,
            kind=entry.kind,
            help_url=entry.help_url,
            description=entry.description,
            icon=entry.icon,
        )
        for entry in all_purposes()
    ]
    return SecretPurposeList(items=items, total=len(items))


@router.get("", response_model=SecretList, dependencies=[Depends(require(Perm.SECRETS_VIEW))])
async def list_secrets(
    service: SecretSvc,
    ctx: Auth,
    purpose: Annotated[list[str] | None, Query(description="Only keys for these")] = None,
) -> Any:
    """The secrets this caller may see, identified by name, purpose and hint.

    `purpose` is what a picker filters on: the Tavily keys for a web-search
    slot, the OpenRouter ones for a model picker.
    """
    items = await service.list_secrets(ctx, purposes=purpose)
    return SecretList(items=items, total=len(items))


@router.post(
    "",
    response_model=SecretRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.SECRETS_EDIT))],
)
async def create_secret(data: SecretCreate, service: SecretSvc, ctx: Auth) -> Any:
    """Store a secret, sealed for this organization."""
    return await service.create(
        ctx,
        name=data.name,
        value=data.value,
        description=data.description,
        purpose=data.purpose,
        visibility=Visibility(data.visibility),
    )


@router.post("/openai-codex/sign-in", response_model=OpenAICodexSignIn)
async def start_openai_codex_sign_in(service: OpenAICodexSvc, ctx: Auth) -> Any:
    """Begin a ChatGPT sign-in. The address it ends on is redeemable once, by you.

    Open to any member: starting stores nothing in the vault, and what the
    address is redeemed for - a new secret, or reconnecting one somebody may
    edit through a grant - is authorized when it is.
    """
    return OpenAICodexSignIn(authorization_url=await service.start_sign_in(ctx))


@router.post(
    "/openai-codex",
    response_model=SecretRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.SECRETS_EDIT))],
)
async def create_openai_codex_secret(
    data: OpenAICodexSecretCreate, service: OpenAICodexSvc, ctx: Auth
) -> Any:
    """Finish a ChatGPT sign-in and store it, sealed for this organization."""
    return await service.create(
        ctx,
        callback_url=data.callback_url,
        name=data.name,
        description=data.description,
        visibility=Visibility(data.visibility),
    )


@router.put("/{secret_id}/openai-codex", response_model=SecretRead)
async def reconnect_openai_codex_secret(
    secret_id: UUID, data: OpenAICodexSecretReconnect, service: OpenAICodexSvc, ctx: Auth
) -> Any:
    """Sign in with ChatGPT again, in place of a sign-in that stopped working."""
    return await service.reconnect(ctx, secret_id, callback_url=data.callback_url)


@router.patch("/{secret_id}", response_model=SecretRead)
async def update_secret(secret_id: UUID, data: SecretUpdate, service: SecretSvc, ctx: Auth) -> Any:
    """Rename, re-describe or rotate. A rotation cannot change the kind."""
    return await service.update(
        ctx,
        secret_id,
        name=data.name,
        description=data.description,
        value=data.value,
    )


@router.delete("/{secret_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_secret(secret_id: UUID, service: SecretSvc, ctx: Auth) -> None:
    """Delete a secret. Agents referencing it fail loudly at their next run."""
    await service.delete(ctx, secret_id)
