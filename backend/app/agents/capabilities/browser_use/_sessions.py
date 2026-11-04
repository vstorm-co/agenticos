"""Bounded, owner-sealed conversation checkpoints, never live browser handles."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.browser_sign_ins import SignIn
from app.core.vault import VaultScope, seal, unseal
from app.services import live_browse

MAX_TABS = 8


class SavedTab(BaseModel):
    """Reloadable page state; DOM, pending forms and JavaScript memory are not retained."""

    id: str
    url: str
    sign_in: SignIn | None = Field(default=None, repr=False)


class SavedBrowser(BaseModel):
    """A checkpoint is bound to the complete conversation identity inside the envelope."""

    scope: str
    tabs: list[SavedTab] = Field(max_length=MAX_TABS)
    active: str


class Envelope(BaseModel):
    ciphertext: str = Field(repr=False)
    key_version: int


async def save(scope: str, owner: UUID, tabs: list[SavedTab], active: str) -> None:
    """Seal a private checkpoint. Expiration releases storage without a cleanup job."""
    state = SavedBrowser(scope=scope, tabs=tabs, active=active)
    sealed = seal(state.model_dump_json(), scope=VaultScope.user(owner))
    await live_browse.save_session(
        scope,
        Envelope(ciphertext=sealed.ciphertext, key_version=sealed.key_version).model_dump_json(),
    )


async def load(scope: str, owner: UUID) -> SavedBrowser | None:
    """Read only this owner's conversation; a moved envelope cannot cross conversations."""
    raw = await live_browse.load_session(scope)
    if raw is None:
        return None
    envelope = Envelope.model_validate_json(raw)
    state = SavedBrowser.model_validate_json(
        unseal(envelope.ciphertext, scope=VaultScope.user(owner), key_version=envelope.key_version)
    )
    return state if state.scope == scope else None
