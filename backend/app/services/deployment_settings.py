"""This deployment's own identity, access policy and notices.

One row for the whole installation, administered by whoever holds `is_app_admin`.
The service is thin on purpose - there is no tenant to scope and no grant to
resolve, because the subject of every method is the deployment itself - but three
of its decisions are load-bearing:

**A read never writes.** No row means "every built-in default", which is the state
of a deployment nobody has configured, so `branding()` answers from defaults rather
than creating a row to hold them. That matters because the public branding endpoint
is unauthenticated and reached on every cold page load: a read-through that created
a row would let a stranger provoke an `INSERT`.

**The API answers overrides, not effective values.** A null crosses the wire as a
null and the renderer resolves it against its own built-in - the frontend against
`APP_NAME` and `SITE`, this side against `settings.PROJECT_NAME`. One default per
renderer beats an effective value computed here and a second copy of the same
constant on the other side, and `effective_app_name` is the one place this side
resolves it.

**An image's bytes are ours and its path is never a caller's.** `set_image` writes
the storage key itself, from a filename it mints out of the validated content type.
The reasoning is `AgentEmbedService.set_page_logo`'s, whole: this file is served
from the origin the app runs on, and a stored name is what decides whether a
browser treats it as a picture or as a script.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.maintenance import publish as publish_maintenance
from app.db.models.deployment_settings import DeploymentSettings
from app.db.updates import writable
from app.repositories import deployment_settings_repo
from app.schemas.deployment_settings import (
    BrandingRead,
    DeploymentSettingsRead,
    DeploymentSettingsUpdate,
    NoticeLevel,
    NoticeRead,
    SignupMode,
)
from app.services.file_storage import IMAGE_MIME_TYPES, MAX_AVATAR_SIZE, get_file_storage

logger = logging.getLogger(__name__)

ImageKind = Literal["logo", "favicon"]

_IMAGE_COLUMN: dict[ImageKind, str] = {"logo": "logo_path", "favicon": "favicon_path"}

_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
"""The extension minted for each accepted type. Keyed identically to
`IMAGE_MIME_TYPES`, which `set_image` checks against before reaching this - so the
lookup cannot miss, and there is one definition of "an image this platform accepts"
rather than a second one for branding.

SVG and ICO are deliberately absent. An SVG is a document that may carry script and
this file is served from the app's own origin; an ICO buys nothing a PNG favicon does
not already do in every browser this product supports.
"""

_STORAGE_KEY = "deployment"
"""The directory these two files live under.

A constant rather than an id, because there is one deployment. `save` keeps only
the last component of the name it is given, so this is the whole of the layout.
"""


class DeploymentSettingsService:
    """Read and write the installation's identity, in one row."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def branding(self) -> BrandingRead:
        """What any caller, signed in or not, may know about this deployment.

        Deliberately excludes the announcement: a banner is written for the people
        using the deployment - an upgrade window, an ops contact - and a stranger on
        the sign-in page has no part in it. `notice()` is that half, behind a session.
        """
        return _branding(await deployment_settings_repo.get(self.db))

    async def notice(self) -> NoticeRead:
        """The banner for a signed-in user, or an empty one when there is none."""
        row = await deployment_settings_repo.get(self.db)
        if row is None or not row.announcement:
            return NoticeRead()
        return NoticeRead(message=row.announcement, level=_notice_level(row.announcement_level))

    async def read(self) -> DeploymentSettingsRead:
        """The administrator's whole view, so one request fills one form."""
        row = await deployment_settings_repo.get(self.db)
        return DeploymentSettingsRead(
            **_branding(row).model_dump(),
            announcement=row.announcement if row else None,
            announcement_level=_notice_level(row.announcement_level) if row else "info",
            updated_at=row.updated_at if row else None,
        )

    async def update(
        self, *, actor_user_id: UUID, data: DeploymentSettingsUpdate
    ) -> DeploymentSettingsRead:
        """Write the fields this request named, creating the row if there is none.

        `writable` is what decides which explicit `null` reaches the row: one for a
        nullable identity column is "give me the built-in back" and is kept, and one
        for `signup_mode` or `maintenance_mode` is the schema's "not provided"
        sentinel and is dropped rather than arriving as a `NOT NULL` violation (#637).

        The audit entry names the fields, never their values: an announcement and a
        domain list are both operator text, and an audit row outlives the body it
        came from.
        """
        update_data = writable(data, over=DeploymentSettings)
        if not update_data:
            raise BadRequestError(message="Nothing to change")
        row = await deployment_settings_repo.upsert(self.db, update_data=update_data)
        # The middleware reads its verdict from a cache with a TTL, so a saved
        # change would otherwise take up to half a minute to close or reopen the
        # deployment - which an administrator experiences as a switch that did
        # nothing. Pushed from the row rather than from the request, because a
        # PATCH that touched only the name must not publish a stale `None`.
        await publish_maintenance(on=row.maintenance_mode, message=row.maintenance_message)
        await record_audit(
            self.db,
            actor_user_id=actor_user_id,
            action="deployment.settings_updated",
            target_type="deployment",
            details={"fields": sorted(update_data)},
        )
        return await self.read()

    async def set_image(
        self,
        *,
        actor_user_id: UUID,
        kind: ImageKind,
        file_data: bytes,
        content_type: str | None,
    ) -> DeploymentSettingsRead:
        """Store the wordmark or the favicon, and point the deployment at it.

        Raises:
            BadRequestError: For a file that is not an image this platform accepts,
                or one over the size limit.
        """
        if content_type not in IMAGE_MIME_TYPES:
            raise BadRequestError(message="Only JPEG, PNG, WebP, and GIF images are allowed")
        if len(file_data) > MAX_AVATAR_SIZE:
            raise BadRequestError(message="Image too large. Maximum 2MB.")

        column = _IMAGE_COLUMN[kind]
        row = await deployment_settings_repo.get(self.db)
        storage = get_file_storage()
        previous = getattr(row, column) if row else None
        # The name is minted from the type checked above, never taken from the
        # caller: `save` keeps whatever extension it is handed, and this file is
        # served from the origin the app itself runs on.
        path = await storage.save(_STORAGE_KEY, f"{kind}{_SUFFIX[content_type]}", file_data)
        await deployment_settings_repo.upsert(self.db, update_data={column: path})
        if previous:
            # A replaced picture is not worth failing an upload over, and the old
            # file is unreachable the moment the row stops pointing at it.
            with contextlib.suppress(Exception):
                await storage.delete(previous)
        await record_audit(
            self.db,
            actor_user_id=actor_user_id,
            action="deployment.settings_updated",
            target_type="deployment",
            details={"fields": [column]},
        )
        return await self.read()

    async def clear_image(self, *, actor_user_id: UUID, kind: ImageKind) -> DeploymentSettingsRead:
        """Drop the uploaded image, returning the deployment to the built-in mark.

        Idempotent: clearing when nothing is stored is the end state already, so it
        answers the current settings rather than reporting a missing file the caller
        does not care about.
        """
        column = _IMAGE_COLUMN[kind]
        row = await deployment_settings_repo.get(self.db)
        previous = getattr(row, column) if row else None
        if previous is None:
            return await self.read()
        await deployment_settings_repo.upsert(self.db, update_data={column: None})
        with contextlib.suppress(Exception):
            await get_file_storage().delete(previous)
        await record_audit(
            self.db,
            actor_user_id=actor_user_id,
            action="deployment.settings_updated",
            target_type="deployment",
            details={"fields": [column]},
        )
        return await self.read()

    async def image_path(self, kind: ImageKind) -> str | None:
        """The storage key of the stored image, for the route that serves it."""
        row = await deployment_settings_repo.get(self.db)
        if row is None:
            return None
        path: str | None = getattr(row, _IMAGE_COLUMN[kind])
        return path

    async def effective_app_name(self) -> str:
        """What this deployment calls itself, for the text the backend sends itself.

        The one place this side resolves the default, so an email cannot greet
        somebody in the name of a product the console stopped showing. Its built-in
        is `settings.PROJECT_NAME`, and `tests/test_deployment_branding.py` pins that
        equal to the frontend's `APP_NAME`.
        """
        row = await deployment_settings_repo.get(self.db)
        return (row.app_name if row else None) or settings.PROJECT_NAME


def _branding(row: DeploymentSettings | None) -> BrandingRead:
    """The public shape of a row, or of no row at all.

    No row means every default, so the empty model *is* the answer - there is
    nothing to create and nothing to fall back through.
    """
    if row is None:
        return BrandingRead()
    return BrandingRead(
        app_name=row.app_name,
        tagline=row.tagline,
        description=row.description,
        logo_url=_image_url("logo", row),
        favicon_url=_image_url("favicon", row),
        footer_text=row.footer_text,
        terms_url=row.terms_url,
        privacy_url=row.privacy_url,
        signup_mode=_signup_mode(row.signup_mode),
        allowed_email_domains=list(row.allowed_email_domains),
        maintenance_mode=row.maintenance_mode,
        maintenance_message=row.maintenance_message,
    )


def _image_url(kind: ImageKind, row: DeploymentSettings) -> str | None:
    """Where a browser fetches the stored image, with a token that changes on write.

    A path on this API rather than the storage key, which is an implementation
    detail of whichever backend is configured. The `?v=` is the row's `updated_at`:
    the address is constant, so without it a browser holding the previous bytes has
    no reason to ask again and a replaced logo looks like an upload that failed.
    """
    if getattr(row, _IMAGE_COLUMN[kind]) is None:
        return None
    written = row.updated_at or row.created_at
    return f"/api/v1/branding/{kind}?v={int(written.timestamp())}"


_SIGNUP_MODES: dict[str, SignupMode] = {
    "open": "open",
    "invite_only": "invite_only",
    "closed": "closed",
}

_NOTICE_LEVELS: dict[str, NoticeLevel] = {
    "info": "info",
    "warning": "warning",
    "critical": "critical",
}


def _signup_mode(stored: str) -> SignupMode:
    """The stored mode, narrowed to the three the API publishes.

    A column holds text and a `Literal` is a promise about it, so an unrecognised
    value - a hand-edited row, a mode removed in a later version - reads as `open`
    rather than failing the response model. `open` is the safe direction: the
    alternative refuses every registration on a deployment whose administrator never
    asked for that, and that refusal has no page to explain itself on.
    """
    return _SIGNUP_MODES.get(stored, "open")


def _notice_level(stored: str) -> NoticeLevel:
    """The stored level, narrowed the same way. An unknown level draws as `info`."""
    return _NOTICE_LEVELS.get(stored, "info")
