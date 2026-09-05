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
from app.core.background import spawn_after_commit
from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.maintenance import publish as publish_maintenance
from app.db.models.deployment_settings import DeploymentSettings
from app.db.updates import writable
from app.repositories import deployment_settings_repo
from app.schemas.deployment_settings import (
    BrandingRead,
    DeploymentLimits,
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
        """What an open page has to keep asking: the banner, and whether we are shut.

        One read for both, because a client polling for an announcement is a client
        that also needs to hear about a maintenance window opened after its page
        was rendered - and two endpoints on two intervals would be two answers that
        can disagree about the same row.

        No row, or no announcement, still answers the maintenance half: the
        defaults are "nothing to say" rather than "nothing to report".
        """
        row = await deployment_settings_repo.get(self.db)
        if row is None:
            return NoticeRead()
        return NoticeRead(
            message=row.announcement or None,
            level=_notice_level(row.announcement_level),
            maintenance_mode=row.maintenance_mode,
            maintenance_message=row.maintenance_message,
        )

    async def read(self) -> DeploymentSettingsRead:
        """The administrator's whole view, so one request fills one form."""
        row = await deployment_settings_repo.get(self.db)
        return DeploymentSettingsRead(
            **_branding(row).model_dump(),
            announcement=row.announcement if row else None,
            announcement_level=_notice_level(row.announcement_level) if row else "info",
            max_organizations_per_user=row.max_organizations_per_user if row else None,
            max_agents_per_organization=row.max_agents_per_organization if row else None,
            notify_impersonated_users=row.notify_impersonated_users if row else False,
            updated_at=row.updated_at if row else None,
        )

    async def notifies_impersonated_users(self) -> bool:
        """Whether an impersonation emails its target, as whatever starts one reads it.

        No row is the unconfigured deployment, and the unconfigured answer is no:
        an upgrade must not start mailing people about a thing nobody turned on.
        """
        row = await deployment_settings_repo.get(self.db)
        return bool(row and row.notify_impersonated_users)

    async def limits(self) -> DeploymentLimits:
        """The two ceilings, as whatever creates the thing they bound reads them.

        Null for either is no ceiling, and an installation with no row at all is
        uncapped on both - which is what a self-hosted deployment for one company
        wants without opening the page.
        """
        row = await deployment_settings_repo.get(self.db)
        return DeploymentLimits(
            organizations_per_user=row.max_organizations_per_user if row else None,
            agents_per_organization=row.max_agents_per_organization if row else None,
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
        #
        # After the commit, not before it: published eagerly, a request that then
        # failed - on the audit write, or on the commit itself - left Redis
        # advertising a state the database rolled back, for up to the TTL. A
        # failed disable reopened the deployment; a failed enable closed it while
        # answering an error. `spawn_after_commit` is what makes the cache unable
        # to run ahead of the truth, and the values are scalars, so nothing here
        # holds the session it waits on.
        spawn_after_commit(
            self.db,
            publish_maintenance(on=row.maintenance_mode, message=row.maintenance_message),
            name="deployment_maintenance_publish",
        )
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
            # After the commit, because a delete cannot be rolled back with the
            # row that authorised it: deleted eagerly, an audit write or a commit
            # that then failed restored `previous` as the active image and the
            # bytes it names were already gone - an error answered, and a
            # deployment pointing at a missing file. The replacement is left an
            # orphan on rollback instead, which is the harmless half of the trade.
            spawn_after_commit(self.db, _delete_quietly(previous), name="deployment_image_replaced")
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
        spawn_after_commit(self.db, _delete_quietly(previous), name="deployment_image_cleared")
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


async def _delete_quietly(path: str) -> None:
    """Remove a file the settings row no longer points at, failing quietly.

    A replaced or cleared picture is unreachable the moment the row stops naming
    it, so the delete is housekeeping: worth attempting, never worth turning into
    an error somebody has to act on. It runs after the commit, where there is no
    response left to fail.
    """
    with contextlib.suppress(Exception):
        await get_file_storage().delete(path)


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
        logo_version=_image_version("logo", row),
        favicon_version=_image_version("favicon", row),
        footer_text=row.footer_text,
        terms_url=row.terms_url,
        privacy_url=row.privacy_url,
        signup_mode=_signup_mode(row.signup_mode),
        allowed_email_domains=list(row.allowed_email_domains),
        maintenance_mode=row.maintenance_mode,
        maintenance_message=row.maintenance_message,
    )


def _image_version(kind: ImageKind, row: DeploymentSettings) -> int | None:
    """When the stored image was last written, or `None` when there is none.

    The row's `updated_at`, falling back to `created_at`: a Core upsert that inserts
    leaves `updated_at` null, so without the fallback every image on a freshly
    created row would be served under the same token. That token is the only reason
    a replaced image ever appears - the address is constant and the bytes carry a
    year of `immutable` - so one that does not move is an upload that looks failed.

    In **microseconds**, which is the column's own resolution and not decoration:
    truncated to a second, replacing a logo twice within the same second minted the
    same token for both, and a client holding the first went on showing it for a
    year against a replacement that had certainly succeeded. `now()` is the
    transaction's timestamp and these are separate transactions, so the two differ.
    """
    if getattr(row, _IMAGE_COLUMN[kind]) is None:
        return None
    written = row.updated_at or row.created_at
    return int(written.timestamp() * 1_000_000)


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
