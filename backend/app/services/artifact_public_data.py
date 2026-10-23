"""The owner's consent to show a page's data to anyone with its link (#1975).

The members' consent (:mod:`app.services.artifact_consent`) is to people who hold an
account here. A public link, and the sites that embed it, reach everyone else, so its data
needs a consent of its own, kept on the page: `public_data_fingerprint`, the digest of the
page queries it was given to, with the owner's membership it is valid under.

The data reaches an anonymous visitor only while :func:`public_data_holds` - the
organization's switch (`Organization.public_live_data`) is on, the consent is to the
queries of the version the link serves, the owner is the one it was given under, and that
version's consent from the members still holds. The switch is a kill switch: turning it
off hides the data and leaves the consent, which holds again when it is turned back on.

Anything that widens who sees it, or changes whose it is, clears the consent
(:func:`void_public_data`, audited `artifact.public_data_voided` with its reason): the link
turned off, its password removed, a new embedding site, a new owner, the members' consent
withdrawn, the page archived. A rotated address, an expiry and a pinned version change
nothing here: the first is the URL, not the data, and the other two decide which version is
served, which the fingerprint check already follows.

Confirming is the owner's, or an Owner's or Admin's, as themselves
(:func:`~app.services.artifact_consent.may_confirm`); withdrawing narrows, so any editor
may. No agent tool reaches either.
"""

import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.config import settings
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.artifact import Artifact, ArtifactVersion
from app.db.models.organization import Organization
from app.repositories import artifact_repo, organization_repo
from app.schemas.artifact import (
    ArtifactBinding,
    ArtifactDetail,
    ArtifactPublicDataCreate,
    ArtifactPublicDataDisclosure,
    ArtifactPublicDataRead,
    PublicDataNotHolding,
)
from app.services import rate_limit
from app.services.artifact_bindings import BindingRows
from app.services.artifact_consent import as_themselves, consent_holds, owner_membership_id
from app.services.artifact_requests import name_of

if TYPE_CHECKING:
    from app.services.artifact import ArtifactService

_OWNER_GONE = "The page's owner is no longer an active member, so its data can't be shared."
_AS_THEMSELVES = "This is not allowed while impersonating another account."


class PublicDataVoid(StrEnum):
    """Why a page's public data consent was cleared, as the audit entry records it."""

    LINK_OFF = "link_off"
    PASSWORD_REMOVED = "password_removed"
    ORIGIN_ADDED = "origin_added"
    OWNER_CHANGED = "owner_changed"
    CONSENT_WITHDRAWN = "consent_withdrawn"
    ARCHIVED = "archived"


def public_data_not_holding(
    artifact: Artifact,
    served_version: ArtifactVersion | None,
    owner_membership: UUID | None,
    org: Organization,
) -> PublicDataNotHolding | None:
    """Why a consented page's data is not shown on its link now, or `None`.

    `None` too when nothing is consented. The first gate to fail names the reason, in the
    order :func:`public_data_holds` takes them.
    """
    if artifact.public_data_fingerprint is None:
        return None
    if not org.public_live_data:
        return "switch_off"
    if served_version is None:
        return "no_served_version"
    # A served version that reads no data has no fingerprint, so it differs from the consent.
    if artifact.public_data_fingerprint != served_version.query_fingerprint:
        return "queries_changed"
    if owner_membership is None:
        return "owner_gone"
    if artifact.public_data_membership_id != owner_membership:
        return "owner_membership_changed"
    if not consent_holds(served_version, artifact, owner_membership):
        return "member_consent_missing"
    expires = artifact.public_expires_at
    if expires is not None and expires <= datetime.now(UTC):
        return "link_expired"
    return None


def public_data_holds(
    artifact: Artifact,
    served_version: ArtifactVersion | None,
    owner_membership: UUID | None,
    org: Organization,
) -> bool:
    """Whether the public page may be given its data: all of these, on every load.

    The organization's switch is on; the page's public consent names the queries of
    `served_version` - the version the link serves - and the owner's membership now; that
    version's consent from the members still holds; and the link has not expired. A version
    that reads no data has no fingerprint and so nothing to hold.
    """
    return (
        artifact.public_data_fingerprint is not None
        and public_data_not_holding(artifact, served_version, owner_membership, org) is None
    )


async def public_version(db: AsyncSession, artifact: Artifact) -> ArtifactVersion | None:
    """The version the page's public link serves: its pinned one, else the one its audience
    is served - never a version waiting for consent."""
    if artifact.public_version_number is not None:
        return await artifact_repo.get_version_by_number(
            db, artifact.id, artifact.public_version_number
        )
    return await artifact_repo.latest_served(db, artifact.id)


_CLEARED: dict[str, None] = {
    "public_data_fingerprint": None,
    "public_data_by_user_id": None,
    "public_data_membership_id": None,
    "public_data_at": None,
}


async def clear_public_data(
    db: AsyncSession,
    ctx: AuthContext,
    artifact: Artifact,
    *,
    action: str,
    details: dict[str, object],
) -> Artifact:
    """Clear the page's public data consent and audit `action`. The caller has checked there
    is one."""
    artifact = await artifact_repo.update(db, artifact=artifact, update_data=dict(_CLEARED))
    await record_audit(
        db,
        actor_user_id=ctx.subject_id,
        organization_id=artifact.organization_id,
        action=action,
        target_type="artifact",
        target_id=str(artifact.id),
        details=details,
    )
    return artifact


async def void_public_data(
    db: AsyncSession, ctx: AuthContext, artifact: Artifact, reason: PublicDataVoid
) -> Artifact:
    """Clear the page's public data consent because something changed under it, audited
    `artifact.public_data_voided` with the `reason`. Nothing happens when it has none."""
    if artifact.public_data_fingerprint is None:
        return artifact
    return await clear_public_data(
        db,
        ctx,
        artifact,
        action="artifact.public_data_voided",
        details={
            "reason": reason.value,
            "fingerprint": artifact.public_data_fingerprint,
            "consented_at": artifact.public_data_at.isoformat()
            if artifact.public_data_at
            else None,
        },
    )


def audience_digest(artifact: Artifact) -> str:
    """A digest of who the public link reaches: the embedding sites, whether a password
    guards it and whether the link is on. An expiry, a pinned version and a rotated address
    change none of it, so they are left out."""
    audience = {
        "embed_origins": sorted(artifact.embed_origins or []),
        "password_protected": artifact.public_password_hash is not None,
        "link_on": artifact.public_key is not None,
    }
    return hashlib.sha256(json.dumps(audience, sort_keys=True).encode()).hexdigest()


CACHE_SECONDS = 30
"""How long a binding's read is kept for the next anonymous visitor of the same page."""

CACHE_ENTRIES = 64
"""How many reads are kept at most, the least recently used dropped first."""

_CacheKey = tuple[UUID, str, str, UUID]
_cache: OrderedDict[_CacheKey, tuple[float, BindingRows]] = OrderedDict()
"""Reads of a public page's bindings, in this process and never in Redis: they are records.

Keyed by the version, the binding, the version's query fingerprint and the owner's
membership the data is read as. Every gate of :func:`public_data_holds` runs before a
lookup; only a read that answered is kept, never an unavailable or failed one."""


def _cached_bytes() -> int:
    return sum(kept[1].rows.bytes for kept in _cache.values())


def clear_public_reads() -> None:
    """Forget every kept read."""
    _cache.clear()


class PublicReads:
    """One anonymous load's use of the kept reads, and of the page's allowance of real ones.

    A read that is kept costs the tables nothing and is free; the first one that is not
    takes one of the page's reads for the minute, shared by all its visitors. Past that
    allowance, or while this process is already serving as many loads as it may, a binding
    that needs a read gets none.
    """

    def __init__(self, artifact_id: UUID, version: ArtifactVersion, membership: UUID) -> None:
        self.artifact_id = artifact_id
        self.version = version
        self.membership = membership
        self._admitted: bool | None = None

    def _key(self, name: str) -> _CacheKey:
        return (self.version.id, name, self.version.query_fingerprint or "", self.membership)

    def lookup(self, name: str) -> BindingRows | None:
        """The binding's kept read, if it is younger than :data:`CACHE_SECONDS`."""
        key = self._key(name)
        kept = _cache.get(key)
        if kept is None:
            return None
        if kept[0] <= time.monotonic():
            del _cache[key]
            return None
        _cache.move_to_end(key)
        return kept[1]

    def store(self, name: str, rows: BindingRows) -> None:
        """Keep a read that answered."""
        budget = settings.ARTIFACT_PUBLIC_DATA_CACHE_BYTES
        if rows.rows.bytes > budget:
            return
        key = self._key(name)
        _cache.pop(key, None)
        _cache[key] = (time.monotonic() + CACHE_SECONDS, rows)
        while len(_cache) > CACHE_ENTRIES or _cached_bytes() > budget:
            _cache.popitem(last=False)

    async def admit(self) -> bool:
        """Whether this load may read from the tables, counted once per load."""
        if self._admitted is None:
            decision = await rate_limit.consume_with_local_floor(
                surface="artifact_public_data",
                caller=f"artifact:{self.artifact_id}",
                limit=rate_limit.artifact_public_data_limit(),
            )
            self._admitted = decision.allowed
        return self._admitted


def _reach(bindings: Sequence[ArtifactBinding]) -> dict[UUID, set[UUID]]:
    reach: dict[UUID, set[UUID]] = {}
    for binding in bindings:
        for table_id, columns in binding.reach.tables.items():
            reach.setdefault(table_id, set()).update(columns)
    return reach


class ArtifactPublicDataService:
    """Show, give and take back the consent to a page's data on its public link."""

    def __init__(self, db: AsyncSession) -> None:
        # Imported here: the page service imports this module for the voiding.
        from app.services.artifact import ArtifactService

        self.db = db
        self.pages: ArtifactService = ArtifactService(db)

    async def _org(self, artifact: Artifact) -> Organization:
        org = await organization_repo.get_by_id(self.db, artifact.organization_id)
        assert org is not None  # the artifact's own organization
        return org

    async def state(
        self, ctx: AuthContext, artifact: Artifact, org: Organization | None = None
    ) -> ArtifactPublicDataRead:
        """Where the consent stands, for a caller who may edit the page."""
        org = org or await self._org(artifact)
        version = await public_version(self.db, artifact)
        membership = await owner_membership_id(self.db, artifact)
        return ArtifactPublicDataRead(
            switch_on=org.public_live_data,
            consented=artifact.public_data_fingerprint is not None,
            fingerprint=artifact.public_data_fingerprint,
            version=version.number if version is not None else None,
            by_name=(
                await name_of(self.db, artifact.public_data_by_user_id)
                if artifact.public_data_by_user_id is not None
                else None
            ),
            at=artifact.public_data_at,
            holds=public_data_holds(artifact, version, membership, org),
            not_holding=public_data_not_holding(artifact, version, membership, org),
        )

    def _refusal(
        self,
        artifact: Artifact,
        org: Organization,
        version: ArtifactVersion | None,
        membership: UUID | None,
    ) -> str | None:
        """Why the page's data cannot be confirmed for its link now, or `None`."""
        if not org.public_live_data:
            return "Live data on public pages is off for this organization."
        if artifact.public_key is None:
            return "The page has no public link; turn it on before confirming its data."
        if version is None or not version.bindings:
            return "The version the link serves reads no data, so there is nothing to confirm."
        if membership is None:
            return _OWNER_GONE
        if not consent_holds(version, artifact, membership):
            return "Confirm this version's data for members first."
        return None

    async def disclosure(self, ctx: AuthContext, artifact_id: UUID) -> ArtifactPublicDataDisclosure:
        """What confirming would share: the served version's page queries in words, as for the
        members, and who the public link and its embeds reach. For a caller who may confirm.

        Raises:
            NotFoundError: The artifact is not the caller's to open.
            AuthorizationError: The caller may not confirm its data.
        """
        artifact = await self.pages.get(ctx, artifact_id)
        self.pages.held_to_confirming(ctx, artifact)
        org = await self._org(artifact)
        version = await public_version(self.db, artifact)
        membership = await owner_membership_id(self.db, artifact)
        problem = self._refusal(artifact, org, version, membership)
        return ArtifactPublicDataDisclosure(
            switch_on=org.public_live_data,
            link_on=artifact.public_key is not None,
            password_protected=artifact.public_password_hash is not None,
            expires_at=artifact.public_expires_at,
            embed_origins=list(artifact.embed_origins or []),
            version=version.number if version is not None else None,
            fingerprint=version.query_fingerprint if version is not None else None,
            audience_digest=audience_digest(artifact),
            member_consent=version is not None
            and bool(version.bindings)
            and consent_holds(version, artifact, membership),
            data=(
                await self.pages.disclosure(ctx, artifact.id, version.id)
                if version is not None and version.bindings
                else None
            ),
            confirmable=problem is None,
            problem=problem,
        )

    async def confirm(
        self, ctx: AuthContext, artifact_id: UUID, data: ArtifactPublicDataCreate
    ) -> ArtifactDetail:
        """Consent to anyone with the link, and the sites embedding it, reading the data of the
        version the link serves.

        By the page's owner, or by a holder of `artifacts:edit` at scope `ALL` for them -
        each as themselves; a grant to edit the page is not enough. Recorded under the owner's
        membership now. Audited `artifact.public_data_consented` with the tables and columns
        by name, the embedding sites and whether a password is set - never a row.
        Confirming a consent that already holds changes nothing.

        Raises:
            NotFoundError: The artifact is not the caller's to open.
            AuthorizationError: The caller may not confirm its data.
            BadRequestError: The person did not confirm; the organization's switch is off; the
                page has no link; the served version reads no data or has no consent from
                the members.
            ConcurrentChangeError: The served version's page queries, or who the link reaches, are
                not the ones shown.
        """
        artifact = await self.pages.get(ctx, artifact_id)
        self.pages.held_to_confirming(ctx, artifact)
        # Under the lock a publish takes, so no version lands between this check and the write.
        await artifact_repo.lock(self.db, artifact.id)
        self.pages.held_to_confirming(ctx, artifact)
        if not data.confirmed:
            raise refused_field("confirmed", "Confirm what this shares before sharing it.")
        org = await self._org(artifact)
        version = await public_version(self.db, artifact)
        membership = await owner_membership_id(self.db, artifact)
        problem = self._refusal(artifact, org, version, membership)
        if problem is not None:
            raise BadRequestError(message=problem, details={"artifact_id": artifact.id})
        assert version is not None and membership is not None  # `_refusal` held them
        if version.query_fingerprint != data.fingerprint:
            raise ConcurrentChangeError(
                message="The page changed since you opened this. Review it again.",
                details={"artifact_id": artifact.id, "version_id": version.id},
            )
        if data.audience_digest != audience_digest(artifact):
            raise ConcurrentChangeError(
                message="Who the link reaches changed after you looked. Review it again.",
                details={"artifact_id": artifact.id},
            )
        if public_data_holds(artifact, version, membership, org):
            return await self.pages.detail(ctx, artifact)
        bindings = [ArtifactBinding.model_validate(binding) for binding in version.bindings]
        _, sources = await self.pages.tables_for_words(ctx, artifact, bindings)
        names = {table_id: source.name for table_id, source in sources.items()}
        columns = sorted(
            f"{source.name}.{column.label}"
            for table_id, reached in _reach(bindings).items()
            if (source := sources.get(table_id)) is not None
            for column in source.columns
            if column.id in reached
        )
        artifact = await artifact_repo.update(
            self.db,
            artifact=artifact,
            update_data={
                "public_data_fingerprint": version.query_fingerprint,
                "public_data_by_user_id": ctx.subject_id,
                "public_data_membership_id": membership,
                "public_data_at": datetime.now(UTC),
            },
        )
        details: dict[str, object] = {
            "version": version.number,
            "fingerprint": version.query_fingerprint,
            "tables": sorted(names.values()),
            "columns": columns,
            "embed_origins": list(artifact.embed_origins or []),
            "password_protected": artifact.public_password_hash is not None,
        }
        if ctx.subject_id != artifact.owner_user_id:
            details["for_owner"] = str(artifact.owner_user_id)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="artifact.public_data_consented",
            target_type="artifact",
            target_id=str(artifact.id),
            details=details,
        )
        return await self.pages.detail(ctx, artifact)

    async def withdraw(self, ctx: AuthContext, artifact_id: UUID) -> ArtifactDetail:
        """Take the consent back: the public page goes on without data until it is confirmed
        again. Narrowing, so any editor may, as themselves. Audited
        `artifact.public_data_withdrawn`; a page with no consent changes nothing.

        Raises:
            NotFoundError: The artifact is not the caller's to change.
            AuthorizationError: The caller is not acting as themselves.
        """
        artifact = await self.pages.get(ctx, artifact_id, perm=Perm.ARTIFACTS_EDIT)
        if not as_themselves(ctx):
            raise AuthorizationError(message=_AS_THEMSELVES, details={"artifact_id": artifact.id})
        await artifact_repo.lock(self.db, artifact.id)
        if artifact.public_data_fingerprint is not None:
            artifact = await clear_public_data(
                self.db,
                ctx,
                artifact,
                action="artifact.public_data_withdrawn",
                details={"fingerprint": artifact.public_data_fingerprint},
            )
        return await self.pages.detail(ctx, artifact)
