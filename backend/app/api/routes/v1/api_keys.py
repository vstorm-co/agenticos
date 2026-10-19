"""Organization API keys - issued, listed and revoked from a signed-in session.

Not in the public API, deliberately: a key never manages keys, so a leaked one
cannot mint its own successors or revoke the one that would replace it.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import ApiKeySvc, Auth, require
from app.core.permissions import Perm
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyList, ApiKeyScopeCatalog

router = APIRouter()


@router.get(
    "/scopes",
    response_model=ApiKeyScopeCatalog,
    dependencies=[Depends(require(Perm.API_KEYS_CREATE))],
)
async def list_api_key_scopes(service: ApiKeySvc, ctx: Auth) -> Any:
    """The permissions the caller may put on a key, and the presets over them."""
    return service.scope_catalog(ctx)


@router.get("", response_model=ApiKeyList)
async def list_api_keys(service: ApiKeySvc, ctx: Auth) -> Any:
    """The caller's own keys - or every key in the organization, with `api_keys:manage`."""
    return await service.list_keys(ctx)


@router.post(
    "",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.API_KEYS_CREATE))],
)
async def create_api_key(data: ApiKeyCreate, service: ApiKeySvc, ctx: Auth) -> Any:
    """Issue a key. The response holds the key itself, once - it is not stored readably."""
    return await service.create(ctx, data)


@router.delete("/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def revoke_api_key(api_key_id: UUID, service: ApiKeySvc, ctx: Auth) -> None:
    """Stop a key working, at once. Your own, or anybody's with `api_keys:manage`."""
    await service.revoke(ctx, api_key_id)
