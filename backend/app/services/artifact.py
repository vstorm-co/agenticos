"""Artifacts - pages agents publish, who may open them, and how they are served.

Three callers, three entry points:

- **A run** publishes through :func:`publish`, a module-level function that opens
  its own short-lived session, the way the memory store and conversation search
  are reached: a tool must not hold the run's session across a model call.
- **A member** manages and opens artifacts through :class:`ArtifactService`,
  with every per-row decision taken by `resolve_access`.
- **A browser frame** loads the bytes through :meth:`ArtifactService.content`,
  which authenticates nothing but a signed, short-lived token. The access
  decision was taken when the token was minted - by a grant in
  :meth:`ArtifactService.view`, or by the public link in
  :meth:`ArtifactService.public_view` - so the content route can live on an
  origin no cookie reaches, and every response it gives carries a `sandbox`
  policy that puts the page in an opaque origin of its own.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape
from uuid import UUID

from markdown_it import MarkdownIt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.background import spawn_after_commit
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm
from app.core.security import create_artifact_view_token, read_uuid_claim, verify_special_token
from app.db.models.artifact import Artifact, ArtifactMediaType, ArtifactVersion
from app.db.session import get_db_context
from app.repositories import artifact_repo, resource_grant_repo
from app.schemas.artifact import (
    ArtifactDetail,
    ArtifactList,
    ArtifactRead,
    ArtifactUpdate,
    ArtifactVersionList,
    ArtifactVersionRead,
    ArtifactView,
    PublicArtifactRead,
)
from app.services.access import ARTIFACT, resolve_access, visible_resource_ids
from app.services.file_storage import get_file_storage

logger = logging.getLogger(__name__)

NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"
"""What a name may be. The same rule as the column's CHECK, stated once for the tool."""

_PUBLIC_KEY_BYTES = 24
"""192 bits, the hosted page's rule: the key is the whole of what guards the link."""

_EXTENSIONS: dict[ArtifactMediaType, str] = {
    ArtifactMediaType.HTML: "html",
    ArtifactMediaType.MARKDOWN: "md",
}

_MARKDOWN = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")
"""Raw HTML in a Markdown artifact is escaped rather than passed through.

The page is sandboxed either way, so this is not the isolation boundary. It is what
makes the format honest: an agent that wants script writes an HTML artifact, and a
Markdown one renders as the document it reads as.
"""

_MARKDOWN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ font: 16px/1.6 system-ui, sans-serif; max-width: 46rem; margin: 2rem auto;
  padding: 0 1rem; }}
pre, code {{ font-family: ui-monospace, monospace; font-size: 0.9em; }}
pre {{ overflow-x: auto; padding: 0.75rem; border-radius: 6px;
  background: color-mix(in srgb, currentColor 8%, transparent); }}
table {{ border-collapse: collapse; }}
th, td {{ border: 1px solid color-mix(in srgb, currentColor 25%, transparent);
  padding: 0.35rem 0.6rem; }}
img {{ max-width: 100%; }}
</style></head><body>
{body}
</body></html>
"""

CONTENT_SECURITY_POLICY_BASE = (
    # No `allow-same-origin`: the page gets an opaque origin, so it can read no
    # cookie, no storage and no DOM of the console that frames it, and a request it
    # makes carries nothing of whoever is looking at it. Popups so a link in a
    # report opens; everything that would navigate or submit elsewhere is off.
    "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox allow-modals; "
    # Self-contained by construction. `connect-src 'none'` and no remote sources
    # mean a page cannot load code from, or send what it shows to, anywhere - a
    # prompt-injected report cannot beacon the numbers it was built from.
    "default-src 'none'; "
    "script-src 'unsafe-inline' 'unsafe-eval' data: blob:; "
    "style-src 'unsafe-inline' data:; "
    "img-src data: blob:; "
    "font-src data:; "
    "media-src data: blob:; "
    "worker-src blob:; "
    "connect-src 'none'; "
    "form-action 'none'; "
    "base-uri 'none'; "
    "frame-src 'none'"
)
"""The policy every content response carries, before `frame-ancestors`."""


def content_security_policy() -> str:
    """The full policy: the base above, framed only by this deployment's own pages."""
    frontend = settings.FRONTEND_URL.rstrip("/")
    return f"{CONTENT_SECURITY_POLICY_BASE}; frame-ancestors {frontend}"


def publish_problem(*, name: str, media_type: ArtifactMediaType, data: bytes) -> str | None:
    """Why this publication would be refused, in words the model can act on.

    `None` when it is acceptable. Checked by the tool before anything is written,
    so a mistake costs a retry rather than a half-made artifact.
    """
    if not re.fullmatch(NAME_PATTERN, name):
        return (
            f"`name` {name!r} is not a valid artifact name. Use 1-64 lower-case letters, "
            "digits and hyphens, starting with a letter or digit - for example "
            "`weekly-report`. Reuse the same name to update an artifact you published before."
        )
    if len(data) > settings.ARTIFACT_MAX_BYTES:
        return (
            f"The page is {len(data):,} bytes, over the {settings.ARTIFACT_MAX_BYTES:,}-byte "
            "limit for one artifact. Trim it - smaller images, less repeated data - rather "
            "than splitting it."
        )
    if not data.strip():
        return "The page is empty. Publish the finished document."
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return f"The {_EXTENSIONS[media_type]} content is not valid UTF-8 text."
    return None


@dataclass(frozen=True)
class PublishedArtifact:
    """What a publication did, for the tool to report."""

    artifact_id: UUID
    version_id: UUID
    version_number: int
    name: str
    title: str
    created: bool
    """True when this publication made the artifact, not a version of an existing one."""
    unchanged: bool
    """True when the bytes matched the current version and no version was added."""
    visibility: str
    public: bool


def _storage_path(artifact: Artifact, sha256: str, media_type: ArtifactMediaType) -> str:
    """Content-addressed under the artifact, so deleting the artifact is one prefix."""
    return f"{_prefix(artifact.organization_id, artifact.id)}{sha256}.{_EXTENSIONS[media_type]}"


def _prefix(organization_id: UUID, artifact_id: UUID) -> str:
    return f"artifacts/{organization_id}/{artifact_id}/"


async def _unlink_best_effort(paths: list[str]) -> None:
    """Remove stored versions after the rows that named them are committed.

    Best effort, logged: the rows are already gone, so a failure leaves bytes
    nothing points at, bounded by the artifact's own prefix.
    """
    storage = get_file_storage()
    for path in paths:
        try:
            await storage.delete(path)
        except Exception:
            logger.exception("Could not remove a pruned artifact version at %s", path)


async def _remove_prefix_best_effort(prefix: str) -> None:
    try:
        await get_file_storage().delete_prefix(prefix)
    except Exception:
        logger.exception("Could not remove a deleted artifact's stored versions under %s", prefix)


async def publish(
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_user_id: UUID | None,
    run_id: UUID | None,
    name: str,
    title: str,
    media_type: ArtifactMediaType,
    data: bytes,
) -> PublishedArtifact:
    """Publish from a run, on a short-lived session of its own. See :func:`publish_with`."""
    async with get_db_context() as db:
        return await publish_with(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            owner_user_id=owner_user_id,
            run_id=run_id,
            name=name,
            title=title,
            media_type=media_type,
            data=data,
        )


async def publish_with(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_user_id: UUID | None,
    run_id: UUID | None,
    name: str,
    title: str,
    media_type: ArtifactMediaType,
    data: bytes,
) -> PublishedArtifact:
    """Publish a page as a new version of the agent's artifact of this name.

    Creates the artifact on the first publication, private to `owner_user_id`.
    Idempotent on the bytes: publishing exactly what the current version holds
    adds no version, so a schedule that found nothing new leaves the history as
    it was. A new title is taken either way.

    The caller has already checked :func:`publish_problem`; the size is enforced
    again here because this is the function that writes.
    """
    if len(data) > settings.ARTIFACT_MAX_BYTES:
        raise ValueError("artifact content over ARTIFACT_MAX_BYTES reached publish_with()")
    sha256 = hashlib.sha256(data).hexdigest()
    artifact, created = await _locked_artifact(
        db,
        organization_id=organization_id,
        agent_id=agent_id,
        owner_user_id=owner_user_id,
        name=name,
        title=title,
    )
    latest = await artifact_repo.latest_version(db, artifact.id)
    if latest is not None and latest.sha256 == sha256 and latest.media_type == media_type:
        if artifact.title != title:
            artifact = await artifact_repo.update(
                db, artifact=artifact, update_data={"title": title}
            )
        return _published(artifact, latest, created=created, unchanged=True)

    path = _storage_path(artifact, sha256, media_type)
    await get_file_storage().save_at(path, data)
    version = await artifact_repo.create_version(
        db,
        artifact_id=artifact.id,
        number=(latest.number + 1) if latest is not None else 1,
        media_type=media_type.value,
        size_bytes=len(data),
        sha256=sha256,
        storage_path=path,
        run_id=run_id,
    )
    artifact = await artifact_repo.update(
        db,
        artifact=artifact,
        update_data={"title": title, "published_at": datetime.now(UTC)},
    )
    await _prune(db, artifact.id)
    await record_audit(
        db,
        actor_user_id=owner_user_id,
        organization_id=organization_id,
        action="artifact.published",
        target_type="artifact",
        target_id=str(artifact.id),
        details={"name": name, "version": version.number, "agent_id": str(agent_id)},
    )
    return _published(artifact, version, created=created, unchanged=False)


async def _locked_artifact(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_user_id: UUID | None,
    name: str,
    title: str,
) -> tuple[Artifact, bool]:
    """The artifact to write to, locked, and whether this call created it.

    Two first publications of one name can race; the loser's insert fails on the
    unique constraint inside a savepoint and it takes the winner's row instead.
    """
    existing = await artifact_repo.get_for_update(
        db, organization_id=organization_id, agent_id=agent_id, name=name
    )
    if existing is not None:
        return existing, False
    try:
        async with db.begin_nested():
            created = await artifact_repo.create(
                db,
                organization_id=organization_id,
                owner_user_id=owner_user_id,
                agent_id=agent_id,
                name=name,
                title=title,
            )
    except IntegrityError:
        winner = await artifact_repo.get_for_update(
            db, organization_id=organization_id, agent_id=agent_id, name=name
        )
        if winner is None:
            raise
        return winner, False
    return created, True


async def _prune(db: AsyncSession, artifact_id: UUID) -> None:
    """Drop the versions past `ARTIFACT_MAX_VERSIONS`, their bytes after the commit.

    A pruned version's bytes stay when a kept version has the same content: the
    path is the digest, so a page that went back to an earlier state shares it.
    """
    beyond = await artifact_repo.versions_beyond(
        db, artifact_id, keep=settings.ARTIFACT_MAX_VERSIONS
    )
    if not beyond:
        return
    await artifact_repo.delete_versions(db, [version.id for version in beyond])
    kept = set(await artifact_repo.storage_paths(db, artifact_id))
    orphaned = sorted({version.storage_path for version in beyond} - kept)
    if orphaned:
        spawn_after_commit(db, _unlink_best_effort(orphaned), name="artifact-prune")


def _published(
    artifact: Artifact, version: ArtifactVersion, *, created: bool, unchanged: bool
) -> PublishedArtifact:
    return PublishedArtifact(
        artifact_id=artifact.id,
        version_id=version.id,
        version_number=version.number,
        name=artifact.name,
        title=artifact.title,
        created=created,
        unchanged=unchanged,
        visibility=artifact.visibility,
        public=artifact.public_key is not None,
    )


def public_url_for(artifact: Artifact) -> str | None:
    """The link a stranger opens, on the frontend's own origin, or `None` when off."""
    if artifact.public_key is None:
        return None
    return f"{settings.FRONTEND_URL.rstrip('/')}/a/{artifact.public_key}"


def console_url_for(artifact_id: UUID) -> str:
    """Where a member opens it in the console - the path the chat card links to."""
    return f"/artifacts/{artifact_id}"


def _content_origin() -> str:
    return (settings.ARTIFACT_ORIGIN or settings.PUBLIC_BASE_URL).rstrip("/")


def _view(version: ArtifactVersion) -> ArtifactView:
    """A signed address for one version's bytes, valid for `ARTIFACT_VIEW_TTL_SECONDS`."""
    lifetime = timedelta(seconds=settings.ARTIFACT_VIEW_TTL_SECONDS)
    token = create_artifact_view_token(version.id, expires_in=lifetime)
    return ArtifactView(
        url=f"{_content_origin()}{settings.API_V1_STR}/artifact-content/{token}",
        expires_at=datetime.now(UTC) + lifetime,
        version=ArtifactVersionRead.model_validate(version),
    )


def render(version: ArtifactVersion, data: bytes, *, title: str) -> bytes:
    """The document a frame shows: HTML as written, Markdown rendered into a page."""
    if version.media_type == ArtifactMediaType.MARKDOWN:
        body = _MARKDOWN.render(data.decode("utf-8"))
        return _MARKDOWN_PAGE.format(title=escape(title), body=body).encode("utf-8")
    return data


class ArtifactService:
    """Open, share and manage the artifacts an organization's agents published."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(
        self, ctx: AuthContext, artifact_id: UUID, *, perm: Perm = Perm.ARTIFACTS_VIEW
    ) -> Artifact:
        artifact = await artifact_repo.get(
            self.db, artifact_id, organization_id=ctx.organization_id
        )
        # 404 for both: whether a private artifact exists is itself something the
        # caller may not learn, and a revoked member is told the same thing.
        if artifact is None or not await resolve_access(
            self.db, ctx, artifact, perm, resource_type=ARTIFACT
        ):
            raise NotFoundError(
                message="Artifact not found", details={"artifact_id": str(artifact_id)}
            )
        return artifact

    async def read(self, ctx: AuthContext, artifact_id: UUID) -> ArtifactDetail:
        """One artifact, and whether the caller may manage it - decided here, grants included."""
        artifact = await self.get(ctx, artifact_id)
        can_edit = await resolve_access(
            self.db, ctx, artifact, Perm.ARTIFACTS_EDIT, resource_type=ARTIFACT
        )
        return await self._detail(artifact, can_edit=can_edit)

    async def _detail(self, artifact: Artifact, *, can_edit: bool) -> ArtifactDetail:
        current = await artifact_repo.latest_version(self.db, artifact.id)
        return ArtifactDetail(**self._read(artifact, current).model_dump(), can_edit=can_edit)

    @staticmethod
    def _read(artifact: Artifact, current: ArtifactVersion | None) -> ArtifactRead:
        return ArtifactRead(
            id=artifact.id,
            name=artifact.name,
            title=artifact.title,
            visibility=artifact.visibility,
            owner_user_id=artifact.owner_user_id,
            agent_id=artifact.agent_id,
            public_url=public_url_for(artifact),
            published_at=artifact.published_at,
            current_version=(
                ArtifactVersionRead.model_validate(current) if current is not None else None
            ),
            created_at=artifact.created_at,
            updated_at=artifact.updated_at,
        )

    async def list_readable(
        self,
        ctx: AuthContext,
        *,
        shared_with_me: bool = False,
        search: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> ArtifactList:
        """A page of the artifacts this caller may open, newest publication first."""
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=ARTIFACT, perm=Perm.ARTIFACTS_VIEW
        )
        grant_ids = [] if shared is None else shared
        if shared_with_me and shared is None:
            grant_ids = await resource_grant_repo.list_shared_ids(
                self.db,
                organization_id=ctx.organization_id,
                subject_user_id=ctx.subject_id,
                resource_type=ARTIFACT.key,
            )
        items, total = await artifact_repo.list_visible(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=grant_ids,
            shared_with_me=shared_with_me,
            search=search,
            skip=skip,
            limit=limit,
        )
        current = await artifact_repo.latest_versions(self.db, [item.id for item in items])
        return ArtifactList(
            items=[self._read(item, current.get(item.id)) for item in items], total=total
        )

    async def versions(self, ctx: AuthContext, artifact_id: UUID) -> ArtifactVersionList:
        artifact = await self.get(ctx, artifact_id)
        versions = await artifact_repo.list_versions(self.db, artifact.id)
        return ArtifactVersionList(
            items=[ArtifactVersionRead.model_validate(version) for version in versions],
            total=len(versions),
        )

    async def update(
        self, ctx: AuthContext, artifact_id: UUID, data: ArtifactUpdate
    ) -> ArtifactDetail:
        """Retitle an artifact. Its content is the agent's to change, by republishing."""
        artifact = await self.get(ctx, artifact_id, perm=Perm.ARTIFACTS_EDIT)
        if data.title is not None:
            artifact = await artifact_repo.update(
                self.db, artifact=artifact, update_data={"title": data.title}
            )
        return await self._detail(artifact, can_edit=True)

    async def set_public_link(self, ctx: AuthContext, artifact_id: UUID) -> ArtifactDetail:
        """Turn on the "anyone with the link" address, or rotate it when it is on.

        Rotating is the same call on purpose: a link that leaked is replaced by
        asking for a link, and the old key stops opening anything at once.
        """
        artifact = await self.get(ctx, artifact_id, perm=Perm.ARTIFACTS_EDIT)
        rotated = artifact.public_key is not None
        artifact = await artifact_repo.update(
            self.db,
            artifact=artifact,
            update_data={"public_key": secrets.token_urlsafe(_PUBLIC_KEY_BYTES)},
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="artifact.public_link_rotated" if rotated else "artifact.public_link_enabled",
            target_type="artifact",
            target_id=str(artifact.id),
        )
        return await self._detail(artifact, can_edit=True)

    async def clear_public_link(self, ctx: AuthContext, artifact_id: UUID) -> ArtifactDetail:
        """Turn the public address off. A frame already open keeps its page until its
        signed address expires, `ARTIFACT_VIEW_TTL_SECONDS` at most."""
        artifact = await self.get(ctx, artifact_id, perm=Perm.ARTIFACTS_EDIT)
        if artifact.public_key is not None:
            artifact = await artifact_repo.update(
                self.db, artifact=artifact, update_data={"public_key": None}
            )
            await record_audit(
                self.db,
                actor_user_id=ctx.subject_id,
                organization_id=ctx.organization_id,
                action="artifact.public_link_disabled",
                target_type="artifact",
                target_id=str(artifact.id),
            )
        return await self._detail(artifact, can_edit=True)

    async def delete(self, ctx: AuthContext, artifact_id: UUID) -> None:
        """Delete an artifact, every version, its grants and its link.

        The bytes go after the commit, so a rollback leaves rows that still point
        at what is stored.
        """
        artifact = await self.get(ctx, artifact_id, perm=Perm.ARTIFACTS_EDIT)
        await resource_grant_repo.delete_for_resource(
            self.db,
            organization_id=ctx.organization_id,
            resource_type=ARTIFACT.key,
            resource_id=artifact.id,
        )
        prefix = _prefix(artifact.organization_id, artifact.id)
        await artifact_repo.delete_artifact(self.db, artifact)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="artifact.deleted",
            target_type="artifact",
            target_id=str(artifact_id),
            details={"name": artifact.name},
        )
        spawn_after_commit(self.db, _remove_prefix_best_effort(prefix), name="artifact-delete")

    async def view(
        self, ctx: AuthContext, artifact_id: UUID, *, version_id: UUID | None = None
    ) -> ArtifactView:
        """A signed address for the current version, or for one named version.

        Raises:
            NotFoundError: The artifact is not the caller's to open, it has no
                version, or the version asked for was pruned.
        """
        artifact = await self.get(ctx, artifact_id)
        version = (
            await artifact_repo.get_version(self.db, version_id, artifact_id=artifact.id)
            if version_id is not None
            else await artifact_repo.latest_version(self.db, artifact.id)
        )
        if version is None:
            raise NotFoundError(
                message="This version of the artifact is no longer kept",
                details={"artifact_id": str(artifact_id), "version_id": version_id},
            )
        return _view(version)

    async def public_view(self, public_key: str) -> PublicArtifactRead:
        """The current version behind a public link, for a caller with no account.

        Raises:
            NotFoundError: No artifact has this key - never made, revoked or
                rotated, which the caller cannot tell apart.
        """
        artifact = await artifact_repo.get_by_public_key(self.db, public_key)
        version = (
            await artifact_repo.latest_version(self.db, artifact.id)
            if artifact is not None
            else None
        )
        if artifact is None or version is None:
            raise NotFoundError(message="Artifact not found")
        return PublicArtifactRead(
            title=artifact.title, published_at=artifact.published_at, view=_view(version)
        )

    async def content(self, token: str) -> bytes:
        """The document behind a signed address, ready to serve.

        Raises:
            NotFoundError: The token is invalid or expired, or its version is gone.
                One answer for all three, so the route gives an attacker nothing to
                distinguish.
        """
        payload = verify_special_token(token, "artifact_view")
        version_id = read_uuid_claim(payload, "sub") if payload is not None else None
        found = (
            await artifact_repo.get_version_with_artifact(self.db, version_id)
            if version_id is not None
            else None
        )
        if found is None:
            raise NotFoundError(message="Artifact not found")
        version, artifact = found
        data = await get_file_storage().load(version.storage_path)
        return render(version, data, title=artifact.title)
