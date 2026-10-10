"""Artifacts - pages agents publish, who may open them, and how they are served.

Four callers, four entry points:

- **A run** publishes and reads back through :func:`publish` and
  :func:`read_source`, module-level functions that open their own short-lived
  session, the way the memory store and conversation search are reached: a tool
  must not hold the run's session across a model call.
- **A member** manages and opens artifacts through :class:`ArtifactService`,
  with every per-row decision taken by `resolve_access`.
- **A browser frame** loads the bytes through :meth:`ArtifactService.content`,
  which authenticates nothing but a signed, short-lived token. The access
  decision was taken when the token was minted - by a grant in
  :meth:`ArtifactService.view`, or by the public link in
  :meth:`ArtifactService.public_view` - so the content route can live on an
  origin no cookie reaches, and every response it gives carries a `sandbox`
  policy that puts the page in an opaque origin of its own.
- **Another site** frames a public page through :meth:`ArtifactService.embed`,
  a small document of this deployment's own that frames the page in turn, and is
  allowed to be framed only by the origins the artifact names.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path
from uuid import UUID

from markdown_it import MarkdownIt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.background import spawn_after_commit
from app.core.config import settings
from app.core.exceptions import (
    AuthorizationError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.core.security import (
    create_artifact_view_token,
    get_password_hash,
    read_uuid_claim,
    verify_password,
    verify_special_token,
)
from app.db.models.artifact import Artifact, ArtifactMediaType, ArtifactVersion
from app.db.session import get_db_context
from app.db.updates import writable
from app.repositories import (
    agent_environment_repo,
    agent_run_repo,
    artifact_repo,
    member_repo,
    resource_grant_repo,
)
from app.schemas.artifact import (
    ArtifactAgent,
    ArtifactAgentList,
    ArtifactDetail,
    ArtifactList,
    ArtifactPublicLinkRead,
    ArtifactPublicLinkUpdate,
    ArtifactRead,
    ArtifactUpdate,
    ArtifactVersionList,
    ArtifactVersionRead,
    ArtifactView,
    PublicArtifactRead,
)
from app.services.access import ARTIFACT, resolve_access, visible_resource_ids
from app.services.file_storage import get_file_storage
from app.services.notifications import NotificationService

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

PLATFORM_SCRIPT = """<script data-agenticos="platform">(function () {
  "use strict";
  function send(href) {
    try { parent.postMessage({ type: "agenticos:open-link", href: String(href) }, "*"); }
    catch (error) { /* no parent to ask - the page was opened on its own */ }
  }
  function external(raw) {
    try {
      var url = new URL(raw, location.href);
      return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
    } catch (error) { return null; }
  }
  document.addEventListener("click", function (event) {
    if (event.defaultPrevented || event.button !== 0) return;
    var link = event.target && event.target.closest ? event.target.closest("a[href]") : null;
    if (!link || (link.getAttribute("href") || "").charAt(0) === "#") return;
    var href = external(link.href);
    if (href === null) return;
    event.preventDefault();
    send(href);
  });
  window.open = function (raw) {
    var href = raw ? external(String(raw)) : null;
    if (href !== null) send(href);
    return null;
  };
})();</script>"""
"""What every served page gets before its own markup: a link click becomes a request.

The page has no `allow-popups`, so a link to another site cannot open, and a
navigation inside the frame is refused by the console's `frame-src`. This turns the
click into a message to the frame's parent, which shows the address and opens it
only when a person agrees (#1969). The page could send the same message itself -
its script runs - so the message is a request and never a permission: the person
reading the address is what stands between a prompt-injected page and an address
that carries what it shows. `*` as the target because an opaque origin cannot name
its parent's; the message carries nothing but the address.

Injected when served rather than when stored, so the stored bytes stay what the
agent wrote - what `read_artifact` returns and what the digest is taken over.
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

# What may come before the first real content of a document: a byte-order mark,
# whitespace, comments and the doctype. Always matches, possibly empty, and only
# at the start - so nothing inside a comment, a script or the body can move it.
_DOCUMENT_LEAD = re.compile(
    rb"\A(?:\xef\xbb\xbf)?(?:\s+|<!--.*?-->)*(?:<!doctype\b[^>]*>)?", re.IGNORECASE | re.DOTALL
)

_LIBRARY_ROOT = Path(__file__).resolve().parent.parent / "core" / "catalog" / "artifact_lib"

ARTIFACT_LIBRARY: dict[str, str] = {
    "chart-4.5.1.umd.min.js": "text/javascript; charset=utf-8",
    "d3-7.9.0.min.js": "text/javascript; charset=utf-8",
    "lucide-1.46.0.min.js": "text/javascript; charset=utf-8",
    "agenticos-1.css": "text/css; charset=utf-8",
    "agenticos-2.css": "text/css; charset=utf-8",
    "agenticos-2.js": "text/javascript; charset=utf-8",
}
"""The files a page may load, by the name it loads them as, and their media type.

Served from `lib/` beside the page's own address, so a page names them relatively
- `<script src="lib/chart-4.5.1.umd.min.js">` - and keeps working if the
deployment moves its content to another origin. Every name carries its version:
a page published against one keeps getting exactly that one. See
`app/core/catalog/artifact_lib/README.md`.
"""

_library_bytes: dict[str, bytes] = {}

_EMBED_ORIGIN = re.compile(
    r"^https://(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*(:\d{1,5})?$"
)
_LOCAL_EMBED_ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d{1,5})?$")


def _content_origin() -> str:
    return (settings.ARTIFACT_ORIGIN or settings.PUBLIC_BASE_URL).rstrip("/")


def _library_source() -> str:
    """Where the library set is served, as a source expression: a path, not the origin."""
    return f"{_content_origin()}{settings.API_V1_STR}/artifact-content/lib/"


def content_security_policy(*, embed_origins: Sequence[str] = ()) -> str:
    """The policy every content response carries.

    Args:
        embed_origins: The sites allowed to frame this page through its embed, when
            its public link is on. The embed document is on the content origin
            itself, so that origin is allowed with them; with none, only the
            console may frame the page.
    """
    frame_ancestors = [settings.FRONTEND_URL.rstrip("/")]
    if embed_origins:
        frame_ancestors = [*frame_ancestors, _content_origin(), *embed_origins]
    library = _library_source()
    return "; ".join(
        [
            # No `allow-same-origin`: the page gets an opaque origin, so it can read
            # no cookie, no storage and no DOM of the console that frames it, and a
            # request it makes carries nothing of whoever is looking at it. No
            # `allow-popups` either: `connect-src` does not govern navigation, so a
            # popup is a channel to an address the page chooses - one click on a
            # prompt-injected report would carry its numbers out in a URL. A link
            # asks its parent instead (`PLATFORM_SCRIPT`), and a person decides.
            "sandbox allow-scripts allow-modals",
            # Self-contained by construction. `connect-src 'none'` and no remote
            # sources mean a page cannot load code from, or send what it shows to,
            # anywhere - a prompt-injected report cannot beacon the numbers it was
            # built from. The one exception is this deployment's own library set,
            # named by its path so nothing else on the origin is reachable.
            "default-src 'none'",
            f"script-src 'unsafe-inline' 'unsafe-eval' data: blob: {library}",
            f"style-src 'unsafe-inline' data: {library}",
            "img-src data: blob:",
            f"font-src data: {library}",
            "media-src data: blob:",
            "worker-src blob:",
            "connect-src 'none'",
            "form-action 'none'",
            "base-uri 'none'",
            "frame-src 'none'",
            f"frame-ancestors {' '.join(frame_ancestors)}",
        ]
    )


def embed_security_policy(*, nonce: str, embed_origins: Sequence[str]) -> str:
    """The policy of the embed document: its own script, the page's frame, those framers."""
    frame_ancestors = " ".join(embed_origins) if embed_origins else "'none'"
    return "; ".join(
        [
            "default-src 'none'",
            f"script-src 'nonce-{nonce}'",
            "style-src 'unsafe-inline'",
            f"frame-src {_content_origin()}",
            "img-src data:",
            "connect-src 'none'",
            "form-action 'none'",
            "base-uri 'none'",
            f"frame-ancestors {frame_ancestors}",
        ]
    )


def normalise_embed_origins(origins: Sequence[str]) -> list[str]:
    """The origins as `frame-ancestors` will name them, or a refusal naming the bad one.

    Scheme and host only - a path in `frame-ancestors` is ignored by some browsers
    and honoured by others - and `https://`, because a page framed over plain HTTP
    can be framed by anybody on the network. `http://localhost` is the one
    exception, for trying an embed on a laptop. One leading `*.` covers a site's
    subdomains; a wildcard anywhere else is refused.

    Raises:
        BadRequestError: An origin that is not one of those shapes.
    """
    kept: list[str] = []
    for raw in origins:
        origin = raw.strip().rstrip("/").lower()
        shaped = _EMBED_ORIGIN.fullmatch(origin) or _LOCAL_EMBED_ORIGIN.fullmatch(origin)
        # The patterns take up to five digits; a port past 65535 is not one a
        # browser will navigate to, so the embed it names could never load.
        port = origin.rsplit(":", 1)[1] if shaped and origin.count(":") == 2 else None
        if not shaped or (port is not None and not 0 < int(port) <= 65535):
            raise refused_field(
                "embed_origins",
                f"{raw!r} is not a site origin. Give the scheme and host only, as "
                "`https://intranet.example.com` or `https://*.example.com`.",
            )
        if origin not in kept:
            kept.append(origin)
    return kept


def publish_problem(*, name: str, media_type: ArtifactMediaType, data: bytes) -> str | None:
    """Why this publication would be refused, in words the model can act on.

    `None` when it is acceptable. Checked by the tool before anything is written,
    so a mistake costs a retry rather than a half-made artifact.
    """
    if not re.fullmatch(NAME_PATTERN, name):
        return (
            f"`name` {name!r} is not a valid app name. Use 1-64 lower-case letters, "
            "digits and hyphens, starting with a letter or digit - for example "
            "`weekly-report`. Reuse the same name to update an app you published before."
        )
    if len(data) > settings.ARTIFACT_MAX_BYTES:
        return (
            f"The page is {len(data):,} bytes, over the {settings.ARTIFACT_MAX_BYTES:,}-byte "
            "limit for one app. Trim it - smaller images, less repeated data, a "
            "library from the served set instead of an inlined copy - rather than "
            "splitting it."
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
    organization_id: UUID
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


@dataclass(frozen=True)
class ArtifactSource:
    """The current version of an artifact as the agent wrote it, for `read_artifact`."""

    name: str
    title: str
    version_number: int
    media_type: ArtifactMediaType
    text: str


@dataclass(frozen=True)
class ServedArtifact:
    """A rendered version, and who besides the console may frame it."""

    document: bytes
    embed_origins: list[str]


@dataclass(frozen=True)
class EmbedDocument:
    """The embed page for a public link: the document, its policy, and whether it opens."""

    document: bytes
    policy: str
    available: bool


async def _load_version(version: ArtifactVersion, *, missing: str) -> bytes:
    """A version's bytes, or `NotFoundError` when storage no longer has them.

    A row and its bytes can part company - a restored database beside an older
    volume, an object store emptied by hand - and a page whose bytes are gone is a
    page that is not there, not a server error. Logged, because unlike a stale
    link it means storage and the database disagree.

    Raises:
        NotFoundError: With `missing` as its message.
    """
    try:
        return await get_file_storage().load(version.storage_path)
    except FileNotFoundError:
        logger.warning(
            "artifact_bytes_missing",
            extra={"version_id": str(version.id), "storage_path": version.storage_path},
        )
        raise NotFoundError(message=missing, details={"version_id": str(version.id)}) from None


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


async def _environment_of_run(
    db: AsyncSession, *, run_id: UUID | None, organization_id: UUID, agent_id: UUID
) -> UUID | None:
    """The named environment a run answered from, or `None` for the default one.

    Read off the run row the runner stamped, so the model has no say in it and no
    surface has to pass it along. The default environment is `None` whether the run
    named it or not, so it stays one slot per name.
    """
    if run_id is None:
        return None
    run = await agent_run_repo.get_run(db, run_id, organization_id=organization_id)
    if run is None or run.environment_id is None:
        return None
    environment = await agent_environment_repo.get(
        db, run.environment_id, organization_id=organization_id
    )
    if environment is None or environment.is_default or environment.agent_id != agent_id:
        return None
    return environment.id


async def publish(
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_user_id: UUID | None,
    run_id: UUID | None,
    name: str,
    title: str | None,
    media_type: ArtifactMediaType,
    data: bytes,
    expected_version: int | None = None,
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
            expected_version=expected_version,
        )


async def publish_with(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_user_id: UUID | None,
    run_id: UUID | None,
    name: str,
    title: str | None,
    media_type: ArtifactMediaType,
    data: bytes,
    expected_version: int | None = None,
) -> PublishedArtifact:
    """Publish a page as a new version of the agent's artifact of this name.

    The name is looked up in the environment the run answered from: a run in a
    named environment publishes a page of its own, and the default environment's
    page of the same name is never touched by it.

    Creates the artifact on the first publication, private to `owner_user_id`,
    titled with its name when no `title` is given; a republish without one keeps
    the title it had. Idempotent on the bytes: publishing exactly what the current version holds
    adds no version, so a schedule that found nothing new leaves the history as
    it was. A new title is taken either way, and so is the publication time -
    retention measures age from `published_at`, and a page a schedule still
    republishes every day is alive whether or not its numbers moved.

    An existing artifact is republished only for the person who owns it or for
    one holding `artifacts:edit` on it, grants included - the name is shared by
    everyone who runs the agent, and a second member's run must not replace the
    page behind somebody else's link.

    The caller has already checked :func:`publish_problem`; the size is enforced
    again here because this is the function that writes.

    Args:
        expected_version: The version an edit was made against. When the current
            version is another one by the time the lock is held, nothing is
            written - the edits would silently undo whatever landed in between.

    Raises:
        AuthorizationError: The name belongs to an artifact this run's person
            may not edit. The message is written for the model.
        ConcurrentChangeError: `expected_version` is no longer the current one.
    """
    if len(data) > settings.ARTIFACT_MAX_BYTES:
        raise ValueError("artifact content over ARTIFACT_MAX_BYTES reached publish_with()")
    sha256 = hashlib.sha256(data).hexdigest()
    environment_id = await _environment_of_run(
        db, run_id=run_id, organization_id=organization_id, agent_id=agent_id
    )
    artifact, created = await _locked_artifact(
        db,
        organization_id=organization_id,
        agent_id=agent_id,
        environment_id=environment_id,
        owner_user_id=owner_user_id,
        name=name,
        title=title or name,
    )
    if not created and not await _may(db, artifact, owner_user_id, Perm.ARTIFACTS_EDIT):
        raise AuthorizationError(
            message=(
                f"An app named {name!r} already exists for this agent, and it is not "
                "one this run may change. Publish under a different name."
            ),
            details={"name": name},
        )
    latest = await artifact_repo.latest_version(db, artifact.id)
    if expected_version is not None and (latest is None or latest.number != expected_version):
        raise ConcurrentChangeError(
            message=(
                f"The app {name!r} changed after it was read. Read it again with "
                "`read_artifact` and make the edits against what it holds now."
            ),
            details={"name": name, "version": latest.number if latest is not None else None},
        )
    retitle = {"title": title} if title else {}
    if latest is not None and latest.sha256 == sha256 and latest.media_type == media_type:
        artifact = await artifact_repo.update(
            db, artifact=artifact, update_data={**retitle, "published_at": datetime.now(UTC)}
        )
        return _published(artifact, latest, created=created, unchanged=True)

    path = _storage_path(artifact, sha256, media_type)
    await get_file_storage().save_at(path, data)
    if retitle:
        artifact = await artifact_repo.update(db, artifact=artifact, update_data=retitle)
    version = await _append_version(
        db,
        artifact,
        latest,
        media_type=media_type.value,
        size_bytes=len(data),
        sha256=sha256,
        storage_path=path,
        run_id=run_id,
        actor_user_id=owner_user_id,
    )
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


async def _append_version(
    db: AsyncSession,
    artifact: Artifact,
    latest: ArtifactVersion | None,
    *,
    media_type: str,
    size_bytes: int,
    sha256: str,
    storage_path: str,
    run_id: UUID | None,
    actor_user_id: UUID | None,
) -> ArtifactVersion:
    """Add the next version, mark the publication, prune past the kept window, and
    tell the page's followers."""
    version = await artifact_repo.create_version(
        db,
        artifact_id=artifact.id,
        number=(latest.number + 1) if latest is not None else 1,
        media_type=media_type,
        size_bytes=size_bytes,
        sha256=sha256,
        storage_path=storage_path,
        run_id=run_id,
    )
    await artifact_repo.update(
        db, artifact=artifact, update_data={"published_at": datetime.now(UTC)}
    )
    await _prune(db, artifact)
    await _notify_followers(db, artifact, version, actor_user_id=actor_user_id)
    return version


async def _notify_followers(
    db: AsyncSession, artifact: Artifact, version: ArtifactVersion, *, actor_user_id: UUID | None
) -> None:
    """Tell everybody following the page that it has a new version (#1977).

    Not the person whose run or restore made it - they know. And only followers
    who can still open the page: following grants nothing, so one who lost
    access is skipped here and again when the inbox is read. An `unchanged`
    republish never reaches this, so a schedule that found nothing new is quiet.
    """
    followers = [
        user_id
        for user_id in await artifact_repo.follower_ids(db, artifact.id)
        if user_id != actor_user_id
    ]
    readers = [
        user_id for user_id in followers if await _may(db, artifact, user_id, Perm.ARTIFACTS_VIEW)
    ]
    await NotificationService(db).artifact_version_published(
        recipients=readers,
        organization_id=artifact.organization_id,
        artifact_id=artifact.id,
        title=artifact.title,
        version_number=version.number,
        actor_user_id=actor_user_id,
    )


async def read_source(
    *,
    organization_id: UUID,
    agent_id: UUID,
    reader_user_id: UUID | None,
    run_id: UUID | None,
    name: str,
) -> ArtifactSource:
    """The current version of this agent's artifact of this name, as it was written.

    Found by the same identity a publish uses - the agent, the run's environment,
    the name - and opened only when the run's person may open it in the console.

    Raises:
        NotFoundError: No such artifact, or one this person may not open - one
            answer for both, as everywhere else an artifact is refused.
    """
    async with get_db_context() as db:
        environment_id = await _environment_of_run(
            db, run_id=run_id, organization_id=organization_id, agent_id=agent_id
        )
        artifact = await artifact_repo.get_by_identity(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            environment_id=environment_id,
            name=name,
        )
        version = (
            await artifact_repo.latest_version(db, artifact.id)
            if artifact is not None
            and await _may(db, artifact, reader_user_id, Perm.ARTIFACTS_VIEW)
            else None
        )
        if artifact is None or version is None:
            raise NotFoundError(
                message=f"There is no app named {name!r} that this run may open.",
                details={"name": name},
            )
        data = await _load_version(
            version, missing=f"The app {name!r} has lost its content; publish it again."
        )
    return ArtifactSource(
        name=artifact.name,
        title=artifact.title,
        version_number=version.number,
        media_type=ArtifactMediaType(version.media_type),
        text=data.decode("utf-8"),
    )


async def _locked_artifact(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    environment_id: UUID | None,
    owner_user_id: UUID | None,
    name: str,
    title: str,
) -> tuple[Artifact, bool]:
    """The artifact to write to, locked, and whether this call created it.

    Two first publications of one name can race; the loser's insert fails on the
    unique index inside a savepoint and it takes the winner's row instead.
    """
    existing = await artifact_repo.get_for_update(
        db,
        organization_id=organization_id,
        agent_id=agent_id,
        environment_id=environment_id,
        name=name,
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
                environment_id=environment_id,
                name=name,
                title=title,
            )
    except IntegrityError:
        winner = await artifact_repo.get_for_update(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            environment_id=environment_id,
            name=name,
        )
        if winner is None:
            raise
        return winner, False
    return created, True


async def _may(db: AsyncSession, artifact: Artifact, user_id: UUID | None, perm: Perm) -> bool:
    """Whether a run acting for `user_id` may do `perm` to `artifact`.

    Its owner may, and so may anybody `resolve_access` gives `perm` - the rule a
    person managing it in the console is held to. The role is read from an active
    membership, so a departed or deactivated member's run keeps no reach, and a
    run with nobody behind it reaches only an artifact that has nobody behind it
    either.
    """
    if artifact.owner_user_id == user_id:
        return True
    if user_id is None:
        return False
    membership = await member_repo.get_active(
        db, organization_id=artifact.organization_id, user_id=user_id
    )
    if membership is None:
        return False
    ctx = AuthContext(
        user_id=user_id,
        organization_id=artifact.organization_id,
        role=membership.role,
    )
    return await resolve_access(db, ctx, artifact, perm, resource_type=ARTIFACT)


async def _prune(db: AsyncSession, artifact: Artifact) -> None:
    """Drop the versions past `ARTIFACT_MAX_VERSIONS`, their bytes after the commit.

    The version a public link is pinned to is kept however old it is: the link
    would otherwise open nothing the moment a schedule published past it.

    A pruned version's bytes stay when a kept version has the same content: the
    path is the digest, so a page that went back to an earlier state shares it.
    """
    beyond = await artifact_repo.versions_beyond(
        db,
        artifact.id,
        keep=settings.ARTIFACT_MAX_VERSIONS,
        pinned=artifact.public_version_number,
    )
    if not beyond:
        return
    await artifact_repo.delete_versions(db, [version.id for version in beyond])
    kept = set(await artifact_repo.storage_paths(db, artifact.id))
    orphaned = sorted({version.storage_path for version in beyond} - kept)
    if orphaned:
        spawn_after_commit(db, _unlink_best_effort(orphaned), name="artifact-prune")


def _published(
    artifact: Artifact, version: ArtifactVersion, *, created: bool, unchanged: bool
) -> PublishedArtifact:
    return PublishedArtifact(
        artifact_id=artifact.id,
        organization_id=artifact.organization_id,
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


def embed_url_for(artifact: Artifact) -> str | None:
    """The address another site frames, on the content origin, or `None` when the link is off."""
    if artifact.public_key is None:
        return None
    return f"{_content_origin()}{settings.API_V1_STR}/artifact-embed/{artifact.public_key}"


def console_url_for(artifact_id: UUID, organization_id: UUID) -> str:
    """Where a member opens it in the console, naming the organization it is in.

    The console scopes every request to the reader's last-used organization, so
    somebody in two of them following a link into the other would be told the
    page is not available. `?org=` is the parameter the console adopts for that,
    the same one alert links carry.
    """
    return f"/apps/{artifact_id}?org={organization_id}"


def _view(version: ArtifactVersion) -> ArtifactView:
    """A signed address for one version's bytes, valid for `ARTIFACT_VIEW_TTL_SECONDS`."""
    lifetime = timedelta(seconds=settings.ARTIFACT_VIEW_TTL_SECONDS)
    token = create_artifact_view_token(version.id, expires_in=lifetime)
    return ArtifactView(
        url=f"{_content_origin()}{settings.API_V1_STR}/artifact-content/{token}",
        expires_at=datetime.now(UTC) + lifetime,
        version=ArtifactVersionRead.model_validate(version),
    )


def with_platform_script(document: bytes) -> bytes:
    """The document with :data:`PLATFORM_SCRIPT` first in it, after the doctype.

    First, because the script only listens on `document`, and a `<script>`
    before `<html>` is placed by the parser into the head it opens implicitly -
    the page's own `<html lang>` attributes still land on that element. After
    the doctype, because one that is not first is ignored and the page renders
    in quirks mode. It used to look for `<head>`, then `<html>`, by pattern, and
    a `<!-- <head> -->` comment or the text of a script put it where it never ran.
    """
    lead = next(_DOCUMENT_LEAD.finditer(document)).end()
    return document[:lead] + PLATFORM_SCRIPT.encode("utf-8") + document[lead:]


def render(version: ArtifactVersion, data: bytes, *, title: str) -> bytes:
    """The document a frame shows: HTML as written, Markdown rendered into a page."""
    if version.media_type == ArtifactMediaType.MARKDOWN:
        body = _MARKDOWN.render(data.decode("utf-8"))
        data = _MARKDOWN_PAGE.format(title=escape(title), body=body).encode("utf-8")
    return with_platform_script(data)


async def library_file(name: str) -> tuple[bytes, str]:
    """One file of the library set and its media type, read once and kept.

    Raises:
        NotFoundError: The name is not one the set serves.
    """
    media_type = ARTIFACT_LIBRARY.get(name)
    if media_type is None:
        raise NotFoundError(message="No such library file", details={"name": name})
    data = _library_bytes.get(name)
    if data is None:
        data = await asyncio.to_thread((_LIBRARY_ROOT / name).read_bytes)
        _library_bytes[name] = data
    return data, media_type


def _embed_document(*, nonce: str, title: str, frame_url: str | None, public_url: str) -> bytes:
    """The embed page: the artifact in a sandboxed frame, and a bar for its links.

    Without a frame URL it says the page opens on its own address instead - a link
    behind a password cannot be typed into somebody else's site. Nor does it carry
    the page's title then: the embed address answers anyone who has the key, and a
    title is often exactly what the password was meant to keep - a client's name.
    """
    safe_title = escape(title) if frame_url is not None else "Protected page"
    if frame_url is None:
        body = (
            f'<p class="note">This page is protected. <a href="{escape(public_url)}" '
            'target="_blank" rel="noopener noreferrer">Open it on its own page</a>.</p>'
        )
    else:
        body = (
            f'<iframe id="page" title="{safe_title}" src="{escape(frame_url)}" '
            'sandbox="allow-scripts allow-modals" referrerpolicy="no-referrer"></iframe>'
            '<div id="bar" hidden><span>Open <strong id="address"></strong>?</span>'
            '<a id="open" target="_blank" rel="noopener noreferrer">Open</a>'
            '<button id="cancel" type="button">Cancel</button></div>'
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>{safe_title}</title>
<style>
:root {{ color-scheme: light dark; }}
html, body {{ margin: 0; height: 100%; }}
body {{ font: 14px/1.4 system-ui, sans-serif; }}
iframe {{ border: 0; width: 100%; height: 100%; display: block; }}
.note {{ padding: 1rem; }}
#bar {{ position: fixed; left: 0; right: 0; bottom: 0; display: flex; gap: 0.5rem;
  align-items: center; padding: 0.5rem 0.75rem; background: Canvas; color: CanvasText;
  border-top: 1px solid color-mix(in srgb, CanvasText 20%, transparent); }}
#bar span {{ flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
#bar[hidden] {{ display: none; }}
</style></head><body>
{body}
<script nonce="{nonce}">(function () {{
  var frame = document.getElementById("page");
  var bar = document.getElementById("bar");
  if (!frame || !bar) return;
  var open = document.getElementById("open");
  window.addEventListener("message", function (event) {{
    if (event.source !== frame.contentWindow) return;
    // One address at a time: while the bar asks about one, a page posting another
    // would swap what the reader is reading for what they then click.
    if (!bar.hidden) return;
    var data = event.data;
    if (!data || data.type !== "agenticos:open-link" || typeof data.href !== "string") return;
    var url;
    try {{ url = new URL(data.href); }} catch (error) {{ return; }}
    if (url.protocol !== "https:" && url.protocol !== "http:") return;
    document.getElementById("address").textContent = url.href;
    open.href = url.href;
    bar.hidden = false;
  }});
  open.addEventListener("click", function () {{ bar.hidden = true; }});
  document.getElementById("cancel").addEventListener("click", function () {{ bar.hidden = true; }});
}})();</script>
</body></html>
""".encode()


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
            raise NotFoundError(message="App not found", details={"artifact_id": str(artifact_id)})
        return artifact

    async def read(self, ctx: AuthContext, artifact_id: UUID) -> ArtifactDetail:
        """One artifact, and whether the caller may manage it - decided here, grants included."""
        artifact = await self.get(ctx, artifact_id)
        can_edit = await resolve_access(
            self.db, ctx, artifact, Perm.ARTIFACTS_EDIT, resource_type=ARTIFACT
        )
        return await self._detail(ctx, artifact, can_edit=can_edit)

    async def follow(self, ctx: AuthContext, artifact_id: UUID) -> ArtifactDetail:
        """Be told in the inbox when this page gets a new version (#1977).

        Anybody who may open the page may follow it; following twice is
        following once.
        """
        artifact = await self.get(ctx, artifact_id)
        await artifact_repo.follow(self.db, artifact_id=artifact.id, user_id=ctx.subject_id)
        return await self.read(ctx, artifact.id)

    async def unfollow(self, ctx: AuthContext, artifact_id: UUID) -> ArtifactDetail:
        """Stop being told about new versions. Not following already is not an error."""
        artifact = await self.get(ctx, artifact_id)
        await artifact_repo.unfollow(self.db, artifact_id=artifact.id, user_id=ctx.subject_id)
        return await self.read(ctx, artifact.id)

    async def _detail(
        self, ctx: AuthContext, artifact: Artifact, *, can_edit: bool
    ) -> ArtifactDetail:
        current = await artifact_repo.latest_version(self.db, artifact.id)
        names = await artifact_repo.environment_names(
            self.db, [artifact.environment_id] if artifact.environment_id else []
        )
        pinned = (
            await artifact_repo.get_version_by_number(
                self.db, artifact.id, artifact.public_version_number
            )
            if artifact.public_version_number is not None
            else None
        )
        return ArtifactDetail(
            **self._read(artifact, current, names).model_dump(),
            can_edit=can_edit,
            following=ctx.user_id is not None
            and await artifact_repo.is_following(
                self.db, artifact_id=artifact.id, user_id=ctx.user_id
            ),
            public_link=ArtifactPublicLinkRead(
                expires_at=artifact.public_expires_at,
                pinned_version_id=pinned.id if pinned is not None else None,
                pinned_version=artifact.public_version_number,
                password_protected=artifact.public_password_hash is not None,
                view_count=artifact.public_view_count,
                last_viewed_at=artifact.public_last_viewed_at,
                embed_origins=list(artifact.embed_origins or []),
                embed_url=embed_url_for(artifact),
            ),
        )

    @staticmethod
    def _read(
        artifact: Artifact, current: ArtifactVersion | None, environment_names: dict[UUID, str]
    ) -> ArtifactRead:
        return ArtifactRead(
            id=artifact.id,
            name=artifact.name,
            title=artifact.title,
            visibility=artifact.visibility,
            owner_user_id=artifact.owner_user_id,
            agent_id=artifact.agent_id,
            environment_id=artifact.environment_id,
            environment_name=(
                environment_names.get(artifact.environment_id)
                if artifact.environment_id is not None
                else None
            ),
            public_url=public_url_for(artifact),
            published_at=artifact.published_at,
            current_version=(
                ArtifactVersionRead.model_validate(current) if current is not None else None
            ),
            created_at=artifact.created_at,
            updated_at=artifact.updated_at,
        )

    async def _visibility(self, ctx: AuthContext) -> tuple[bool, list[UUID]]:
        """Whether the caller's role reaches every artifact, and which ones are shared with it."""
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=ARTIFACT, perm=Perm.ARTIFACTS_VIEW
        )
        return shared is None, [] if shared is None else shared

    async def list_readable(
        self,
        ctx: AuthContext,
        *,
        shared_with_me: bool = False,
        search: str | None = None,
        agent_id: UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> ArtifactList:
        """A page of the artifacts this caller may open, newest publication first."""
        see_all, grant_ids = await self._visibility(ctx)
        if shared_with_me and see_all:
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
            see_all=see_all,
            shared_ids=grant_ids,
            shared_with_me=shared_with_me,
            search=search,
            agent_id=agent_id,
            skip=skip,
            limit=limit,
        )
        current = await artifact_repo.latest_versions(self.db, [item.id for item in items])
        names = await artifact_repo.environment_names(
            self.db, sorted({item.environment_id for item in items if item.environment_id})
        )
        return ArtifactList(
            items=[self._read(item, current.get(item.id), names) for item in items], total=total
        )

    async def publishing_agents(self, ctx: AuthContext) -> ArtifactAgentList:
        """The agents behind the artifacts this caller may open - the list's agent filter."""
        see_all, grant_ids = await self._visibility(ctx)
        agents = await artifact_repo.publishing_agents(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=see_all,
            shared_ids=grant_ids,
        )
        return ArtifactAgentList(
            items=[ArtifactAgent(id=agent_id, name=name) for agent_id, name in agents]
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
        return await self._detail(ctx, artifact, can_edit=True)

    async def restore_version(
        self, ctx: AuthContext, artifact_id: UUID, version_id: UUID
    ) -> ArtifactDetail:
        """Make a kept version the current one again, as a new version with its bytes.

        History is never rewritten: the restore is itself a version, so it can be
        undone the same way, and the conversation that published the version it
        replaced still opens that one. The bytes are content-addressed, so nothing
        new is stored. Restoring the current version changes nothing.

        Raises:
            NotFoundError: The artifact is not the caller's to change, the version
                is not one of its kept versions, or storage no longer has its
                bytes - restored, it would be a current version that 404s.
        """
        artifact = await self.get(ctx, artifact_id, perm=Perm.ARTIFACTS_EDIT)
        locked = await artifact_repo.lock(self.db, artifact.id)
        source = await artifact_repo.get_version(self.db, version_id, artifact_id=artifact.id)
        if locked is None or source is None:
            raise NotFoundError(
                message="This version of the app is no longer kept",
                details={"artifact_id": artifact_id, "version_id": version_id},
            )
        latest = await artifact_repo.latest_version(self.db, locked.id)
        if latest is not None and latest.id == source.id:
            return await self._detail(ctx, locked, can_edit=True)
        if not await get_file_storage().exists(source.storage_path):
            logger.warning(
                "artifact_bytes_missing",
                extra={"version_id": str(source.id), "storage_path": source.storage_path},
            )
            raise NotFoundError(
                message="That version's content is gone from storage, so it cannot be restored",
                details={"artifact_id": artifact_id, "version_id": version_id},
            )
        version = await _append_version(
            self.db,
            locked,
            latest,
            media_type=source.media_type,
            size_bytes=source.size_bytes,
            sha256=source.sha256,
            storage_path=source.storage_path,
            run_id=None,
            actor_user_id=ctx.subject_id,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="artifact.version_restored",
            target_type="artifact",
            target_id=str(locked.id),
            details={"version": version.number, "restored": source.number},
        )
        return await self._detail(ctx, locked, can_edit=True)

    async def set_public_link(self, ctx: AuthContext, artifact_id: UUID) -> ArtifactDetail:
        """Turn on the "anyone with the link" address, or rotate it when it is on.

        Rotating is the same call on purpose: a link that leaked is replaced by
        asking for a link, and the old key stops opening anything at once. The
        link's settings stay: a new address for the same link.
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
        return await self._detail(ctx, artifact, can_edit=True)

    async def update_public_link(
        self, ctx: AuthContext, artifact_id: UUID, data: ArtifactPublicLinkUpdate
    ) -> ArtifactDetail:
        """Change the public link's expiry, pinned version, password or embedding sites.

        The settings hold whether or not the link is on, so they can be made before
        it is. The audit entry names which settings changed, never a password.

        Raises:
            NotFoundError: The artifact is not the caller's to change.
            BadRequestError: An expiry in the past, a version that is not kept, or
                an embedding site that is not an origin - each naming its field.
        """
        artifact = await self.get(ctx, artifact_id, perm=Perm.ARTIFACTS_EDIT)
        changes = writable(data, over=Artifact)
        update: dict[str, object] = {}
        if "expires_at" in changes:
            expires_at = changes["expires_at"]
            if expires_at is not None and expires_at <= datetime.now(UTC):
                raise refused_field("expires_at", "The link's expiry has to be in the future.")
            update["public_expires_at"] = expires_at
        if "pinned_version_id" in changes:
            # Under the lock a publish takes before it prunes, so the version
            # checked here cannot be pruned between the check and the write.
            await artifact_repo.lock(self.db, artifact.id)
            update["public_version_number"] = await self._pinned_number(
                artifact, changes["pinned_version_id"]
            )
        if "password" in changes:
            password = changes["password"]
            update["public_password_hash"] = (
                await asyncio.to_thread(get_password_hash, password)
                if password is not None
                else None
            )
        if "embed_origins" in changes:
            update["embed_origins"] = normalise_embed_origins(changes["embed_origins"])
        if update:
            artifact = await artifact_repo.update(self.db, artifact=artifact, update_data=update)
            await record_audit(
                self.db,
                actor_user_id=ctx.subject_id,
                organization_id=ctx.organization_id,
                action="artifact.public_link_updated",
                target_type="artifact",
                target_id=str(artifact.id),
                details={"fields": sorted(changes)},
            )
        return await self._detail(ctx, artifact, can_edit=True)

    async def _pinned_number(self, artifact: Artifact, version_id: UUID | None) -> int | None:
        if version_id is None:
            return None
        version = await artifact_repo.get_version(self.db, version_id, artifact_id=artifact.id)
        if version is None:
            raise refused_field("pinned_version_id", "That version of the app is no longer kept.")
        # A kept row whose bytes are gone would pin the link to a page that 404s.
        if not await get_file_storage().exists(version.storage_path):
            raise refused_field("pinned_version_id", "That version's content is gone from storage.")
        return version.number

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
        return await self._detail(ctx, artifact, can_edit=True)

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
                message="This version of the app is no longer kept",
                details={"artifact_id": str(artifact_id), "version_id": version_id},
            )
        return _view(version)

    async def _public(self, public_key: str) -> tuple[Artifact, ArtifactVersion]:
        """The artifact behind a public key and the version its link shows.

        Raises:
            NotFoundError: No artifact has this key - never made, revoked, rotated
                or expired, which the caller cannot tell apart.
        """
        artifact = await artifact_repo.get_by_public_key(self.db, public_key)
        if artifact is not None and (
            artifact.public_expires_at is not None
            and artifact.public_expires_at <= datetime.now(UTC)
        ):
            artifact = None
        version = None
        if artifact is not None:
            version = (
                await artifact_repo.get_version_by_number(
                    self.db, artifact.id, artifact.public_version_number
                )
                if artifact.public_version_number is not None
                else await artifact_repo.latest_version(self.db, artifact.id)
            )
        if artifact is None or version is None:
            raise NotFoundError(message="App not found")
        return artifact, version

    async def public_view(
        self, public_key: str, *, password: str | None = None
    ) -> PublicArtifactRead:
        """The version behind a public link, for a caller with no account.

        Behind a password, a caller who gave none learns only that one is needed -
        not the title, not when it was published. Each page shown is one view on
        the link's counter.

        Raises:
            NotFoundError: The link does not open anything.
            AuthorizationError: The password given is not the link's.
        """
        artifact, version = await self._public(public_key)
        if artifact.public_password_hash is not None:
            if password is None:
                return PublicArtifactRead(password_required=True)
            if not await asyncio.to_thread(
                verify_password, password, artifact.public_password_hash
            ):
                raise AuthorizationError(
                    message="That password is not right.", details={"password_required": True}
                )
        await artifact_repo.count_public_view(self.db, artifact.id, at=datetime.now(UTC))
        return PublicArtifactRead(
            title=artifact.title, published_at=artifact.published_at, view=_view(version)
        )

    async def embed(self, public_key: str) -> EmbedDocument:
        """The document another site frames for a public link.

        Framed only by the origins the artifact names; with none, by nobody. A link
        behind a password says to open it on its own page, and a link that opens
        nothing says so - both as documents, since what the visitor sees is a frame
        on somebody else's page rather than an API answer.
        """
        nonce = secrets.token_urlsafe(16)
        try:
            artifact, version = await self._public(public_key)
        except NotFoundError:
            return EmbedDocument(
                document=(
                    b"<!doctype html><meta charset=utf-8><title>Not available</title>"
                    b"<p style='font:14px system-ui;padding:1rem'>This page is not available.</p>"
                ),
                policy=embed_security_policy(nonce=nonce, embed_origins=[]),
                available=False,
            )
        origins = list(artifact.embed_origins or [])
        protected = artifact.public_password_hash is not None
        if not protected:
            await artifact_repo.count_public_view(self.db, artifact.id, at=datetime.now(UTC))
        document = _embed_document(
            nonce=nonce,
            title=artifact.title,
            frame_url=None if protected else _view(version).url,
            public_url=public_url_for(artifact) or "",
        )
        return EmbedDocument(
            document=document,
            policy=embed_security_policy(nonce=nonce, embed_origins=origins),
            available=True,
        )

    async def content(self, token: str) -> ServedArtifact:
        """The document behind a signed address, ready to serve, and who may frame it.

        Raises:
            NotFoundError: The token is invalid or expired, its version is gone,
                or storage no longer has the version's bytes. One answer for all
                four, so the route gives an attacker nothing to distinguish.
        """
        payload = verify_special_token(token, "artifact_view")
        version_id = read_uuid_claim(payload, "sub") if payload is not None else None
        found = (
            await artifact_repo.get_version_with_artifact(self.db, version_id)
            if version_id is not None
            else None
        )
        if found is None:
            raise NotFoundError(message="App not found")
        version, artifact = found
        data = await _load_version(version, missing="App not found")
        embeddable = artifact.public_key is not None and artifact.public_password_hash is None
        return ServedArtifact(
            document=render(version, data, title=artifact.title),
            embed_origins=list(artifact.embed_origins or []) if embeddable else [],
        )
