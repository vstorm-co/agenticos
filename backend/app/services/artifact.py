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
import json
import logging
import re
import secrets
import weakref
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any
from uuid import UUID

from markdown_it import MarkdownIt
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.background import spawn_after_commit
from app.core.config import settings
from app.core.exceptions import (
    AccessRequestableError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
    RateLimitError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm, Scope
from app.core.security import (
    create_artifact_view_token,
    get_password_hash,
    read_uuid_claim,
    verify_password,
    verify_special_token,
)
from app.db.models.artifact import (
    SERVED_STATES,
    Artifact,
    ArtifactMediaType,
    ArtifactVersion,
    ConsentState,
)
from app.db.models.artifact_share_request import (
    ShareRequestKind,
    ShareRequestStatus,
    VoidReason,
)
from app.db.models.resource_grant import GrantLevel, Visibility
from app.db.session import get_db_context
from app.db.updates import writable
from app.repositories import (
    agent_environment_repo,
    agent_run_repo,
    artifact_repo,
    artifact_share_request_repo,
    group_repo,
    member_repo,
    resource_grant_repo,
    user_repo,
    virtual_table_repo,
)
from app.schemas.artifact import (
    ArtifactAgent,
    ArtifactAgentList,
    ArtifactAutoConsentUpdate,
    ArtifactBinding,
    ArtifactBindingRead,
    ArtifactConsentCreate,
    ArtifactConsentRead,
    ArtifactData,
    ArtifactDetail,
    ArtifactDisclosure,
    ArtifactList,
    ArtifactOwnerUpdate,
    ArtifactPublicLinkRead,
    ArtifactPublicLinkUpdate,
    ArtifactRead,
    ArtifactUpdate,
    ArtifactVersionList,
    ArtifactVersionRead,
    ArtifactView,
    BindingData,
    BindingDisclosure,
    BindingRequest,
    PublicArtifactRead,
)
from app.services import rate_limit
from app.services.access import (
    ARTIFACT,
    accessible_ids,
    member_context,
    resolve_access,
    visible_resource_ids,
)
from app.services.artifact_bindings import (
    KEPT,
    BindingRows,
    Refused,
    Unavailable,
    check_bindings,
    describe,
    disclose,
    fingerprint,
    page_data,
    page_source,
    reresolve,
    shape_for,
    unavailable,
)
from app.services.artifact_consent import (
    AUTO_CONSENT_TEXTS,
    AUTO_CONSENT_WORDING,
    PAGE_ROLES,
    Served,
    VersionConsent,
    as_themselves,
    consent_for,
    consent_holds,
    grown,
    may_confirm,
    may_grant_edit_data,
    owner_membership_id,
    served,
    served_many,
    shown_state,
    visible_versions,
)
from app.services.artifact_ownership import (
    change_owner,
    may_change_owner,
    require_may_change_owner,
)
from app.services.artifact_requests import (
    file_audience_request,
    name_of,
    on_new_version,
    settle_version_request,
    void_all,
    widens,
)
from app.services.file_storage import get_file_storage
from app.services.sharing import ShareChange
from app.services.virtual_tables import ReadDeadline, TableSource, VirtualTableService
from app.services.virtual_tables.exceptions import DeadlineReached, InvalidQueryError

logger = logging.getLogger(__name__)

NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"
"""What a name may be. The same rule as the column's CHECK, stated once for the tool."""

LIVE_PAGE = "This page reads live data; only a run acting for a member can republish it."
"""The one refusal a run with no member behind it gets for changing a bound page.

One text whatever it sent, so such a run cannot tell from the refusal whether a
binding it guessed at resolves to the stored one.
"""

_MARKDOWN_BINDINGS = (
    "Bindings need an HTML page; a Markdown page runs no scripts. A republish keeps the "
    "current version's bindings unless it passes others: pass `bindings: {}` to drop them."
)

_IN_FLIGHT = "Your previous data load is still running. Try again in a moment."
_OWNER_GONE = "The page's owner is no longer an active member, so its data can't be shared."
_AS_THEMSELVES = "This needs you signed in as yourself, not on somebody's behalf."
NOT_AVAILABLE_YET = "This page isn't available yet: its owner hasn't confirmed the data it shares."
_BUSY = "Too many pages are loading data right now. Try again in a moment."
_STATEMENT_TIMEOUT = "57014"
"""Postgres's `query_canceled`: a statement stopped by its `statement_timeout`."""

# One gate per event loop on how many page loads this process serves at once, for
# `core/blocking.py`'s reason: an `asyncio.Semaphore` binds to the loop that made
# it, and a finished loop's gate is collected with it. Each load holds a database
# connection for up to the page's deadline, so a load past the gate is refused at
# once rather than queued behind it.
_load_gates: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def _load_gate() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    gate = _load_gates.get(loop)
    if gate is None:
        gate = asyncio.Semaphore(settings.ARTIFACT_DATA_MAX_CONCURRENT_LOADS)
        _load_gates[loop] = gate
    return gate


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

_DATA_BRIDGE = (
    (Path(__file__).resolve().parent.parent / "core" / "catalog" / "artifact_data_bridge.js")
    .read_text("utf-8")
    .strip()
)
"""The page side of a bound page's data, one function expression, read once at import.

Kept as a file of its own so `frontend/src/lib/artifact-data-bridge.test.ts` can run
it in jsdom; it is not in :data:`ARTIFACT_LIBRARY`, so it is never served by name.
"""

_SCRIPT_ESCAPES = {
    "<": "\\u003c",
    ">": "\\u003e",
    "&": "\\u0026",
    "\u2028": "\\u2028",
    "\u2029": "\\u2029",
}
"""What JSON leaves raw that an inline script cannot hold.

`<` and `>` could close the script or open a comment, `&` is escaped with them so
no character reference survives, and the two separators end a line in older
script parsers. Each becomes the JSON escape of itself, so the value reads back
unchanged.
"""


def _script_json(value: object) -> str:
    text = json.dumps(value)
    for raw, escaped in _SCRIPT_ESCAPES.items():
        text = text.replace(raw, escaped)
    return text


_EDITOR_ONLY = {"reason", "changed"}
"""What a binding says to the editor's strip and never to the page, as the console's `forPage` drops it."""


def platform_script(
    *,
    nonce: str,
    live: bool,
    names: Sequence[str],
    initial: Mapping[str, BindingData] | None = None,
) -> str:
    """What a served page gets before its own markup: the link bridge, then the data bridge.

    The data bridge defines `window.agenticos` (`data`, `onData`) and learns the
    binding names, the nonce and whether to ask for data. Normally the records
    come later, posted by the console that fetched them as the viewer. With
    `initial` - what :meth:`ArtifactService.content` read for a member served the
    page's data - they are written in here as `[name, binding]` pairs (never an
    object, whose `__proto__` key a script literal would take for a prototype), so
    the page has them on load. Nothing else from the database is written in.
    """
    page_config: dict[str, object] = {"n": nonce, "live": live, "names": list(names)}
    if initial is not None:
        page_config["initial"] = [
            [name, binding.model_dump(mode="json", exclude=_EDITOR_ONLY)]
            for name, binding in initial.items()
        ]
    config = _script_json(page_config)
    return (
        f'{PLATFORM_SCRIPT}<script data-agenticos="data">({_DATA_BRIDGE})'
        f"(window, document, {config});</script>"
    )


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
    "agenticos-3.css": "text/css; charset=utf-8",
    "agenticos-3.js": "text/javascript; charset=utf-8",
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
    return content_address("lib/")


def content_address(rest: str) -> str:
    """An address under the content route, on the content origin - where a frame loads from."""
    return f"{_content_origin()}{settings.API_V1_STR}/artifact-content/{rest}"


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
            f"`name` {name!r} is not a valid artifact name. Use 1-64 lower-case letters, "
            "digits and hyphens, starting with a letter or digit - for example "
            "`weekly-report`. Reuse the same name to update an artifact you published before."
        )
    if len(data) > settings.ARTIFACT_MAX_BYTES:
        return (
            f"The page is {len(data):,} bytes, over the {settings.ARTIFACT_MAX_BYTES:,}-byte "
            "limit for one artifact. Trim it - smaller images, less repeated data, a "
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
    """True when the bytes and the bindings matched the current version's, so no version
    was added."""
    visibility: str
    public: bool
    bindings: dict[str, BindingDisclosure | str] = field(default_factory=dict)
    """Each binding's page query in words, for one this publication resolved, or
    :data:`~app.services.artifact_bindings.KEPT` for one carried from the previous version."""
    consent: ConsentState = ConsentState.NOT_NEEDED
    """Where the version's data stands with the page's owner, as a person reads it."""
    audience_version: int | None = None
    """The version everyone else who opens the page is served; `None` when none yet."""
    owner_name: str | None = None
    """Who owns the page's data, for a version that waits for them."""


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
    bindings: Mapping[str, BindingRequest] | None = None,
    run_person: UUID | None = None,
    table_grants: Mapping[UUID, frozenset[str]] | None = None,
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
            bindings=bindings,
            run_person=run_person,
            table_grants=table_grants,
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
    bindings: Mapping[str, BindingRequest] | None = None,
    run_person: UUID | None = None,
    table_grants: Mapping[UUID, frozenset[str]] | None = None,
) -> PublishedArtifact:
    """Publish a page as a new version of the agent's artifact of this name.

    The name is looked up in the environment the run answered from: a run in a
    named environment publishes a page of its own, and the default environment's
    page of the same name is never touched by it.

    Creates the artifact on the first publication, private to `owner_user_id`,
    titled with its name when no `title` is given; a republish without one keeps
    the title it had. Idempotent on the bytes and the bindings: publishing exactly the
    page and bindings the current version holds adds no version, so a schedule that
    found nothing new leaves the history as it was. A new title is taken either way, and so is the publication time -
    retention measures age from `published_at`, and a page a schedule still
    republishes every day is alive whether or not its numbers moved.

    An existing artifact is republished only for the person who owns it or for
    one holding `artifacts:edit` on it, grants included - the name is shared by
    everyone who runs the agent, and a second member's run must not replace the
    page behind somebody else's link.

    The caller has already checked :func:`publish_problem`; the size is enforced
    again here because this is the function that writes.

    A version stores the page queries it reads live data through, and they are part of
    what "unchanged" compares. They are resolved by
    :func:`~app.services.artifact_bindings.check_bindings` as the member behind the
    run, read again here, who must read every table a query reaches; a query the
    publish changes must also be readable by the page's owner, whose access every
    viewer reads it with. A page whose current version has bindings is changed only
    by a run acting for a member: a run with none behind it - a widget visitor, an
    outsider's webhook - must not swap the code that receives the owner's records, or
    what they are. It may still republish the page unchanged, which takes the new
    title and publication time.

    Args:
        expected_version: The version an edit was made against. When the current
            version is another one by the time the lock is held, nothing is
            written - the edits would silently undo whatever landed in between.
        bindings: The page queries the model asked for, replacing the current ones
            whole; `None` keeps the current version's, `{}` clears them.
        run_person: The member the run acts for (`AgentDeps.run_person`), or `None`.
            One who has since left, or been deactivated, counts as none.
        table_grants: The agent spec's operations per table id; `None` grants none.

    Raises:
        AuthorizationError: The name belongs to an artifact this run's person
            may not edit, the page is archived, or the page reads live data and
            no member is behind the run (:data:`LIVE_PAGE`). The message is
            written for the model.
        BadRequestError: A binding cannot stand, or a Markdown page would have
            bindings. The message is written for the model.
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
                f"An artifact named {name!r} already exists for this agent, and it is not "
                "one this run may change. Publish under a different name."
            ),
            details={"name": name},
        )
    if artifact.archived_at is not None:
        raise AuthorizationError(message=_archived_page(name), details={"name": name})
    latest = await artifact_repo.latest_version(db, artifact.id)
    if expected_version is not None and (latest is None or latest.number != expected_version):
        raise ConcurrentChangeError(
            message=(
                f"The artifact {name!r} changed after it was read. Read it again with "
                "`read_artifact` and make the edits against what it holds now."
            ),
            details={"name": name, "version": latest.number if latest is not None else None},
        )
    person = (
        await member_context(db, organization_id=organization_id, user_id=run_person)
        if run_person is not None
        else None
    )
    previous = _bindings_of(latest)
    same_bytes = latest is not None and latest.sha256 == sha256 and latest.media_type == media_type
    # Before anything is checked: a run with nobody behind it hears this one text for
    # every change to a bound page, never what is wrong with the bindings it sent.
    if person is None and previous and (bindings is not None or not same_bytes):
        raise _live_page(name)
    checks = await check_bindings(
        db,
        requested=bindings,
        previous=previous,
        person=person,
        owner=await _owner(db, artifact, person) if person is not None and bindings else None,
        grants=table_grants or {},
    )
    problems = list(dict.fromkeys(c.problem for c in checks if c.problem is not None))
    if problems:
        raise BadRequestError(message=" ".join(problems), details={"name": name})
    # Every check without a problem carries its binding.
    effective = [c.binding for c in checks if c.binding is not None]
    if effective and media_type == ArtifactMediaType.MARKDOWN:
        raise BadRequestError(message=_MARKDOWN_BINDINGS, details={"name": name})
    canonical = sorted(
        (binding.model_dump(mode="json") for binding in effective), key=lambda b: b["name"]
    )
    unchanged = same_bytes and latest is not None and latest.bindings == canonical
    echo: dict[str, BindingDisclosure | str] = {
        c.name: c.disclosure if c.disclosure is not None else KEPT for c in checks
    }

    retitle = {"title": title} if title else {}
    if unchanged and latest is not None:
        artifact = await artifact_repo.update(
            db, artifact=artifact, update_data={**retitle, "published_at": datetime.now(UTC)}
        )
        return await _published(
            db, artifact, latest, created=created, unchanged=True, bindings=echo
        )

    path = _storage_path(artifact, sha256, media_type)
    await get_file_storage().save_at(path, data)
    if retitle:
        artifact = await artifact_repo.update(db, artifact=artifact, update_data=retitle)
    digest = fingerprint(effective)
    version = await _append_version(
        db,
        artifact,
        latest,
        media_type=media_type.value,
        size_bytes=len(data),
        sha256=sha256,
        storage_path=path,
        run_id=run_id,
        bindings=canonical,
        consent=await consent_for(db, artifact, fingerprint=digest, person=person),
    )
    await record_audit(
        db,
        actor_user_id=owner_user_id,
        organization_id=organization_id,
        action="artifact.published",
        target_type="artifact",
        target_id=str(artifact.id),
        details={
            "name": name,
            "version": version.number,
            "agent_id": str(agent_id),
            "query_fingerprint": digest,
        },
    )
    await _audit_automatic_consent(
        db, artifact, version, actor_user_id=person.user_id if person else None
    )
    return await _published(db, artifact, version, created=created, unchanged=False, bindings=echo)


def _binding_reads(version: ArtifactVersion | None) -> list[ArtifactBindingRead]:
    """A version's bindings as a client reads them: field names, never column ids."""
    return [
        ArtifactBindingRead(
            name=binding.name, table_id=binding.table_id, fields=list(binding.fields)
        )
        for binding in _bindings_of(version)
    ]


async def _owner(db: AsyncSession, artifact: Artifact, person: AuthContext) -> AuthContext | None:
    """The page's owner as the member they are now: `person` when it is theirs, `None`
    when nobody active owns it."""
    if artifact.owner_user_id == person.user_id:
        return person
    if artifact.owner_user_id is None:
        return None
    return await member_context(
        db, organization_id=artifact.organization_id, user_id=artifact.owner_user_id
    )


def _live_page(name: str) -> AuthorizationError:
    return AuthorizationError(message=LIVE_PAGE, details={"name": name})


def _archived_page(name: str) -> str:
    """The refusal a run gets for publishing over an archived page, written for the model.

    Said only to a run that may edit the page; any other run hears that the name is
    not its to change, before the archive is looked at.
    """
    return (
        f"The artifact {name!r} is archived, so it cannot be published again. Tell the "
        "person: someone who may edit it can restore it from its page in the console. "
        "Or publish under a different name."
    )


def _bindings_of(version: ArtifactVersion | None) -> list[ArtifactBinding]:
    return [] if version is None else [ArtifactBinding.model_validate(b) for b in version.bindings]


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
    bindings: list[dict[str, Any]],
    consent: VersionConsent,
    restored_from: int | None = None,
) -> ArtifactVersion:
    """Add the next version, mark the publication, and prune past the kept window.

    `consent` is who published it and the consent it starts with
    (:func:`~app.services.artifact_consent.consent_for`). `restored_from` is the
    number of the version a restore copied; a publish leaves it unset.
    """
    version = await artifact_repo.create_version(
        db,
        artifact_id=artifact.id,
        number=(latest.number + 1) if latest is not None else 1,
        media_type=media_type,
        size_bytes=size_bytes,
        sha256=sha256,
        storage_path=storage_path,
        run_id=run_id,
        bindings=bindings,
        restored_from=restored_from,
        consent=consent.columns(),
    )
    await artifact_repo.update(
        db, artifact=artifact, update_data={"published_at": datetime.now(UTC)}
    )
    await on_new_version(db, artifact, version)
    await _prune(db, artifact)
    return version


async def _audit_automatic_consent(
    db: AsyncSession, artifact: Artifact, version: ArtifactVersion, *, actor_user_id: UUID | None
) -> None:
    """Record a version that was consented as it was published, without anyone confirming."""
    if version.consent_state != ConsentState.CONSENTED.value:
        return
    await record_audit(
        db,
        actor_user_id=actor_user_id,
        organization_id=artifact.organization_id,
        action="artifact.data_consented",
        target_type="artifact",
        target_id=str(artifact.id),
        details={
            "version": version.number,
            "fingerprint": version.query_fingerprint,
            "automatic": True,
            "via_grant": str(version.consent_via_grant) if version.consent_via_grant else None,
        },
    )


async def _owner_name(db: AsyncSession, artifact: Artifact) -> str | None:
    """The page owner as people know them: their name, or their address without one."""
    if artifact.owner_user_id is None:
        return None
    user = await user_repo.get_by_id(db, artifact.owner_user_id)
    if user is None:
        return None
    return user.full_name or user.email


def _not_available_yet(artifact: Artifact) -> NotFoundError:
    """What a viewer is told of a page none of whose versions they may be served yet.

    A 404 with a reason of its own rather than a plain one: they may open the page,
    so it is not news to them that it exists, and the console says why it is empty.
    """
    return NotFoundError(
        message=NOT_AVAILABLE_YET,
        details={"artifact_id": artifact.id, "reason": "not_available_yet"},
    )


def room_may_see(artifact: Artifact) -> bool:
    """Whether a page may be opened for a group chat, whoever in it is speaking.

    Only an organization-wide page: everyone in the channel reads the answer, and
    a private or team page - or one shared with the speaker alone - is reachable
    only through the speaker's own role, ownership or grant. The same rule
    `list_for_agent` applies to a room's listing.
    """
    return artifact.visibility == Visibility.ORG.value


async def _open_current(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    reader_user_id: UUID | None,
    run_id: UUID | None,
    name: str,
    room: bool = False,
) -> tuple[Artifact, ArtifactVersion, bytes]:
    """This agent's artifact of this name, the version its reader is served and its bytes.

    Found by the same identity a publish uses - the agent, the run's environment,
    the name - and opened only when the run's person may open it in the console,
    and, for a `room`, only when :func:`room_may_see` it as well. An archived page
    is not opened at all. The version is the one the console would serve the
    run's person (:func:`_served_to`): the latest for its owner, its editors and
    the roles that read every table, the newest consented one for anyone else and
    for a room.

    Raises:
        NotFoundError: No such artifact, an archived one, or one this person (or
            this room) may not open - one answer for all three, as everywhere
            else an artifact is refused - no version available to them yet, or
            its bytes are gone from storage.
    """
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
    if (
        artifact is None
        or artifact.archived_at is not None
        or (room and not room_may_see(artifact))
        or not await _may(db, artifact, reader_user_id, Perm.ARTIFACTS_VIEW)
    ):
        raise NotFoundError(
            message=f"There is no artifact named {name!r} that this run may open.",
            details={"name": name},
        )
    version = (await _served_to(db, artifact, reader_user_id, room=room)).version
    if version is None:
        raise NotFoundError(
            message=(
                f"The artifact {name!r} isn't available to the person this run is for yet: "
                "its owner hasn't confirmed the data it shares."
            ),
            details={"name": name},
        )
    data = await _load_version(
        version, missing=f"The artifact {name!r} has lost its content; publish it again."
    )
    return artifact, version, data


async def _served_to(
    db: AsyncSession, artifact: Artifact, user_id: UUID | None, *, room: bool
) -> Served:
    """The version a run's reader is served, as the console would serve them.

    The owner by the shortcut :func:`_may` takes; anyone else with the role they hold
    now. A `room` - a group chat everyone in it reads - is served what the page's
    audience is.
    """
    if room or user_id is None:
        return await served(db, None, artifact, can_edit=False)
    if user_id == artifact.owner_user_id:
        latest = await artifact_repo.latest_version(db, artifact.id)
        return Served(version=latest, data=latest is not None, latest=True)
    reader = await _member_auth(db, organization_id=artifact.organization_id, user_id=user_id)
    if reader is None:
        return await served(db, None, artifact, can_edit=False)
    can_edit = await resolve_access(
        db, reader, artifact, Perm.ARTIFACTS_EDIT, resource_type=ARTIFACT
    )
    return await served(db, reader, artifact, can_edit=can_edit)


async def read_source(
    *,
    organization_id: UUID,
    agent_id: UUID,
    reader_user_id: UUID | None,
    run_id: UUID | None,
    name: str,
    room: bool = False,
) -> ArtifactSource:
    """The current version of this agent's artifact of this name, as it was written.

    In a `room` only a page :func:`room_may_see` opens: its source - a static page's
    records among it - would otherwise be read out to everyone in the chat.

    Raises:
        NotFoundError: See :func:`_open_current`.
    """
    async with get_db_context() as db:
        artifact, version, data = await _open_current(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            reader_user_id=reader_user_id,
            run_id=run_id,
            name=name,
            room=room,
        )
    return ArtifactSource(
        name=artifact.name,
        title=artifact.title,
        version_number=version.number,
        media_type=ArtifactMediaType(version.media_type),
        text=data.decode("utf-8"),
    )


@dataclass(frozen=True)
class ArtifactPreview:
    """A page's current version as a frame is served it, and the data it would be posted."""

    name: str
    title: str
    version_number: int
    media_type: ArtifactMediaType
    source: bytes
    """The page as the agent wrote it - what the lint reads."""
    document: bytes
    """The page as served: rendered, behind the platform script for `nonce`."""
    nonce: str
    injected_lines: int
    """How many lines the platform script adds before the page's own: a line number
    the browser reports in the page is this many past the line the agent wrote."""
    binding_names: list[str]
    bindings: dict[str, BindingData] | None
    """Each binding as the run's person would be served it, `{}` when no data could be
    read for them, `None` for a page with no bindings - one that never asks."""
    data_note: str | None
    """Why the bindings are `{}`, in a sentence for the model."""


_PREVIEW_IN_A_ROOM = (
    "This conversation is a group chat, so the page was drawn without its data: every "
    "binding shows as unavailable."
)
_PREVIEW_NOBODY = (
    "Nobody this run is for may read the page's data, so every binding shows as unavailable."
)


async def preview_source(
    *,
    organization_id: UUID,
    agent_id: UUID,
    reader_user_id: UUID,
    run_id: UUID | None,
    name: str,
    room: bool,
) -> ArtifactPreview:
    """The current version of this agent's page as a viewer's frame would be served it.

    Opened as :func:`read_source` opens it. The data is what the console would
    post a viewer who is the run's person: :meth:`ArtifactService.data` asked as
    `reader_user_id`'s membership now, which reads each binding's page query as the
    page's owner, for a viewer it serves data at all. In a room only a page
    :func:`room_may_see` opens at all, and it gets no data, since a picture of the
    page's records would be read by the whole channel; nor does a reader who is no
    longer an active member, or one whose data load is refused for being busy.

    Raises:
        NotFoundError: See :func:`_open_current`.
    """
    async with get_db_context() as db:
        artifact, version, data = await _open_current(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            reader_user_id=reader_user_id,
            run_id=run_id,
            name=name,
            room=room,
        )
        bindings, note = await _preview_data(
            db, artifact, version, reader_user_id=reader_user_id, room=room
        )
    nonce = secrets.token_urlsafe(16)
    live = bool(version.bindings)
    names = [binding["name"] for binding in version.bindings]
    return ArtifactPreview(
        name=artifact.name,
        title=artifact.title,
        version_number=version.number,
        media_type=ArtifactMediaType(version.media_type),
        source=data,
        document=render(version, data, title=artifact.title, nonce=nonce, live=live),
        nonce=nonce,
        injected_lines=platform_script(nonce=nonce, live=live, names=names).count("\n"),
        binding_names=names,
        bindings=bindings,
        data_note=note,
    )


async def _preview_data(
    db: AsyncSession,
    artifact: Artifact,
    version: ArtifactVersion,
    *,
    reader_user_id: UUID,
    room: bool,
) -> tuple[dict[str, BindingData] | None, str | None]:
    """The bindings a preview posts the page, and why they are empty when they are."""
    if not version.bindings:
        return None, None
    if room:
        return {}, _PREVIEW_IN_A_ROOM
    person = await member_context(
        db, organization_id=artifact.organization_id, user_id=reader_user_id
    )
    if person is None:
        return {}, _PREVIEW_NOBODY
    try:
        read = await ArtifactService(db).data(person, artifact.id, version.id)
    except (RateLimitError, NotFoundError) as refused:
        # Busy - the person's own console may be loading this page right now - or
        # pruned between opening it and reading it. The picture is still worth
        # drawing; it says the data was not there and why.
        return (
            {},
            f"The page's data was not read ({refused.message}), so every binding shows as unavailable.",
        )
    return read.bindings, None


LIST_LIMIT = 50
"""How many pages `list_artifacts` shows, newest publication first."""


@dataclass(frozen=True)
class ListedArtifact:
    """One page in a run's listing of its agent's pages."""

    name: str
    title: str
    version_number: int
    media_type: ArtifactMediaType
    bindings: list[str]
    """The names of the current version's bindings; empty for a page with no live data."""
    visibility: str
    public: bool
    published_at: datetime
    console_path: str
    may_edit: bool
    """Whether a publish from this run may write a new version of it."""


@dataclass(frozen=True)
class ArtifactListing:
    items: list[ListedArtifact]
    total: int


async def list_for_run(
    *,
    organization_id: UUID,
    agent_id: UUID,
    reader_user_id: UUID,
    editor_user_id: UUID | None,
    run_id: UUID | None,
    room: bool,
    limit: int = LIST_LIMIT,
) -> ArtifactListing:
    """List from a run, on a short-lived session of its own. See :func:`list_for_run_with`."""
    async with get_db_context() as db:
        return await list_for_run_with(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            reader_user_id=reader_user_id,
            editor_user_id=editor_user_id,
            run_id=run_id,
            room=room,
            limit=limit,
        )


async def list_for_run_with(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    reader_user_id: UUID,
    editor_user_id: UUID | None,
    run_id: UUID | None,
    room: bool,
    limit: int = LIST_LIMIT,
) -> ArtifactListing:
    """This agent's pages in the run's environment that `reader_user_id` may open.

    The console's listing rule, read with the reader's membership now: their own
    pages, organization-wide ones and those shared with them, or all of them for a
    role that reaches every page. A reader who is no longer an active member keeps
    only their own, as :func:`_may` lets them open. In a `room` only
    organization-wide pages are listed - a list read into a group chat never
    holds a page the reader reaches through their role, their ownership or a
    grant made to them alone; see :func:`room_may_see`.

    `may_edit` is answered for `editor_user_id`, the identity a publish is checked
    as, which on a public surface is the publisher rather than the reader. Each page
    is listed at the version the reader is served, as :func:`_open_current` opens it;
    one with none available to them yet is left out.
    """
    environment_id = await _environment_of_run(
        db, run_id=run_id, organization_id=organization_id, agent_id=agent_id
    )
    reader = await _member_auth(db, organization_id=organization_id, user_id=reader_user_id)
    see_all, shared_ids = False, []
    if reader is not None and not room:
        shared = await visible_resource_ids(
            db, reader, resource_type=ARTIFACT, perm=Perm.ARTIFACTS_VIEW
        )
        see_all, shared_ids = shared is None, shared or []
    items, total = await artifact_repo.list_for_agent(
        db,
        organization_id=organization_id,
        agent_id=agent_id,
        environment_id=environment_id,
        reader_id=reader_user_id,
        member=reader is not None,
        room=room,
        see_all=see_all,
        shared_ids=shared_ids,
        limit=limit,
    )
    # A room is read by everyone in it, so it is served what the audience is.
    current = await served_many(db, None if room else reader, items)
    editor = (
        await _member_auth(db, organization_id=organization_id, user_id=editor_user_id)
        if editor_user_id is not None
        else None
    )
    editable = (
        await accessible_ids(db, editor, items, Perm.ARTIFACTS_EDIT, resource_type=ARTIFACT)
        if editor is not None
        else set()
    )
    listed = [
        ListedArtifact(
            name=item.name,
            title=item.title,
            version_number=version.number,
            media_type=ArtifactMediaType(version.media_type),
            bindings=[binding["name"] for binding in version.bindings],
            visibility=item.visibility,
            public=item.public_key is not None,
            published_at=item.published_at,
            console_path=console_url_for(item.id, item.organization_id),
            # The owner shortcut `_may` takes, before any role: a run for nobody
            # still writes over a page nobody owns.
            may_edit=item.owner_user_id == editor_user_id or item.id in editable,
        )
        for item in items
        if (version := current.get(item.id)) is not None
    ]
    return ArtifactListing(items=listed, total=total)


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


@dataclass(frozen=True)
class RunShare:
    """What a run's `share_artifact` did, for the tool to report."""

    name: str
    asked: list[str]
    """What the request now asks for, in words: `org`, a person's name, a group's name."""
    already: list[str]
    """Of what was named, what the page was shared with at least that widely already."""
    unknown: list[str]
    """Names that match no member and no group of the organization."""
    ambiguous: list[str]
    """Names that match more than one member or group."""
    waiting_for: str | None
    """Who decides the request, by name; `None` with no request filed, or nobody left to."""
    filed: bool


async def request_share(
    *,
    organization_id: UUID,
    agent_id: UUID,
    run_person: UUID,
    run_id: UUID | None,
    name: str,
    visibility: Visibility | None,
    people: Sequence[str],
    room: bool = False,
) -> RunShare:
    """Ask for a page to be shared, from a run, on a short-lived session of its own. See
    :func:`request_share_with`."""
    async with get_db_context() as db:
        return await request_share_with(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            run_person=run_person,
            run_id=run_id,
            name=name,
            visibility=visibility,
            people=people,
            room=room,
        )


async def request_share_with(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    run_person: UUID,
    run_id: UUID | None,
    name: str,
    visibility: Visibility | None,
    people: Sequence[str],
    room: bool = False,
) -> RunShare:
    """File an `audience` request to share this agent's page of this name, as the run's person.

    A run never widens a page itself, not even for its owner: the request waits in the
    page's Share dialog for whoever decides it (the owner, or an Owner or Admin for a page
    without one), signed in as themselves - one mechanism for every caller. `people` are
    members' names or addresses and groups' names, each shared view-only; a name that
    matches nobody, or several, is reported and left out. What the page is shared with
    already is left out too, and with nothing left no request is filed. The public link is
    never touched.

    Raises:
        NotFoundError: No such live page that the run's person may open, or - in a `room` -
            that is not organization-wide, as everywhere a run opens a page.
        AuthorizationError: The person may open the page but not change who it is shared with.
        ConflictError: The page is archived (see :func:`file_audience_request`).
        RateLimitError: The person filed too many requests in the last hour.
    """
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
    if (
        artifact is None
        or artifact.archived_at is not None
        or (room and not room_may_see(artifact))
        or not await _may(db, artifact, run_person, Perm.ARTIFACTS_VIEW)
    ):
        raise NotFoundError(
            message=f"There is no artifact named {name!r} that this run may open.",
            details={"name": name},
        )
    if not await _may(db, artifact, run_person, Perm.ARTIFACTS_EDIT):
        raise AuthorizationError(
            message=f"This run's person may open {name!r} but not change who it is shared with.",
            details={"name": name},
        )
    ctx = await member_context(db, organization_id=organization_id, user_id=run_person)
    if ctx is None:  # `_may` lets a page's owner through by id, member or not
        raise AuthorizationError(
            message=f"This run's person is no longer a member, so cannot share {name!r}.",
            details={"name": name},
        )
    changes: list[ShareChange] = []
    labels: list[str] = []
    unknown: list[str] = []
    ambiguous: list[str] = []
    if visibility is not None:
        changes.append(ShareChange(visibility=visibility))
        labels.append(visibility.value)
    for term in dict.fromkeys(text.strip() for text in people if text.strip()):
        found = [
            (change, label)
            for change, label in await _subjects_named(db, organization_id, term)
            if change.subject_user_id not in (artifact.owner_user_id, run_person)
        ]
        if not found:
            unknown.append(term)
        elif len(found) > 1:
            ambiguous.append(term)
        else:
            change, label = found[0]
            changes.append(change)
            labels.append(label)
    widening = [
        (change, label)
        for change, label in zip(changes, labels, strict=True)
        if await widens(db, artifact, change)
    ]
    already = [
        label
        for change, label in zip(changes, labels, strict=True)
        if (change, label) not in widening
    ]
    if not widening:
        return RunShare(
            name=artifact.name,
            asked=[],
            already=already,
            unknown=unknown,
            ambiguous=ambiguous,
            waiting_for=None,
            filed=False,
        )
    await file_audience_request(
        db,
        ctx,
        artifact,
        [change for change, _ in widening],
        via_run={"run_id": str(run_id) if run_id is not None else None, "agent_id": str(agent_id)},
    )
    return RunShare(
        name=artifact.name,
        asked=[label for _, label in widening],
        already=already,
        unknown=unknown,
        ambiguous=ambiguous,
        waiting_for=(
            await name_of(db, artifact.owner_user_id)
            if await owner_membership_id(db, artifact) is not None
            and artifact.owner_user_id is not None
            else None
        ),
        filed=True,
    )


async def _subjects_named(
    db: AsyncSession, organization_id: UUID, term: str
) -> list[tuple[ShareChange, str]]:
    """The members and groups of the organization a name or address stands for, as view-only
    shares with the label to report each by. Compared case-insensitively and whole: the
    sharing dialogs pick from a list, and a run has only the words it was given."""
    wanted = term.lower()  # as Postgres `lower()` folds it, as in `find_active`
    found: list[tuple[ShareChange, str]] = [
        (ShareChange(subject_user_id=user_id, level=GrantLevel.READ), full_name or email)
        for user_id, email, full_name in await member_repo.find_active(
            db, organization_id=organization_id, term=term
        )
    ]
    found += [
        (ShareChange(subject_group_id=group.id, level=GrantLevel.READ), group.name)
        for group, _ in await group_repo.list_for_org(db, organization_id)
        if group.name.lower() == wanted
    ]
    return found


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
    ctx = await _member_auth(db, organization_id=artifact.organization_id, user_id=user_id)
    if ctx is None:
        return False
    return await resolve_access(db, ctx, artifact, perm, resource_type=ARTIFACT)


async def _member_auth(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> AuthContext | None:
    """`user_id` as the member a run acts for now, or `None` when they are not an active one."""
    membership = await member_repo.get_active(db, organization_id=organization_id, user_id=user_id)
    if membership is None:
        return None
    return AuthContext(user_id=user_id, organization_id=organization_id, role=membership.role)


async def _prune(db: AsyncSession, artifact: Artifact) -> None:
    """Drop the versions past `ARTIFACT_MAX_VERSIONS`, their bytes after the commit.

    The version a public link is pinned to is kept however old it is: the link
    would otherwise open nothing the moment a schedule published past it. So is
    the version the page's audience is served, while newer ones wait for consent.

    A pruned version's bytes stay when a kept version has the same content: the
    path is the digest, so a page that went back to an earlier state shares it.
    """
    audience = await artifact_repo.latest_served(db, artifact.id)
    beyond = await artifact_repo.versions_beyond(
        db,
        artifact.id,
        keep=settings.ARTIFACT_MAX_VERSIONS,
        pinned=artifact.public_version_number,
        served=audience.number if audience is not None else None,
    )
    if not beyond:
        return
    await artifact_repo.delete_versions(db, [version.id for version in beyond])
    kept = set(await artifact_repo.storage_paths(db, artifact.id))
    orphaned = sorted({version.storage_path for version in beyond} - kept)
    if orphaned:
        spawn_after_commit(db, _unlink_best_effort(orphaned), name="artifact-prune")


async def _published(
    db: AsyncSession,
    artifact: Artifact,
    version: ArtifactVersion,
    *,
    created: bool,
    unchanged: bool,
    bindings: dict[str, BindingDisclosure | str],
) -> PublishedArtifact:
    consent = ConsentState.NOT_NEEDED
    audience: ArtifactVersion | None = version
    owner: str | None = None
    if version.bindings:
        consent = shown_state(version, artifact, await owner_membership_id(db, artifact))
        if consent != ConsentState.CONSENTED:
            audience = await artifact_repo.latest_served(db, artifact.id)
            owner = await _owner_name(db, artifact)
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
        bindings=bindings,
        consent=consent,
        audience_version=audience.number if audience is not None else None,
        owner_name=owner,
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
    return f"/artifacts/{artifact_id}?org={organization_id}"


def _view(
    version: ArtifactVersion,
    *,
    live: bool,
    viewer: AuthContext | None = None,
    inject: bool = False,
    public_key: str | None = None,
    awaiting_consent: bool = False,
) -> ArtifactView:
    """A signed address for one version's bytes, valid for `ARTIFACT_VIEW_TTL_SECONDS`.

    A fresh nonce for every address, so each load of a frame has its own. With a
    `viewer` the address is a member's: it names them, and with `inject` the page
    is served with its data written in (:meth:`ArtifactService.content` decides that
    afresh on each load). Without one it is a public link's, whose pages never get data.
    """
    lifetime = timedelta(seconds=settings.ARTIFACT_VIEW_TTL_SECONDS)
    nonce = secrets.token_urlsafe(16)
    token = create_artifact_view_token(
        version.id,
        expires_in=lifetime,
        nonce=nonce,
        live=live,
        audience="public" if viewer is None else "member",
        user_id=None if viewer is None else viewer.user_id,
        organization_id=None if viewer is None else viewer.organization_id,
        inject=inject,
        public_key=public_key,
    )
    return ArtifactView(
        url=f"{_content_origin()}{settings.API_V1_STR}/artifact-content/{token}",
        expires_at=datetime.now(UTC) + lifetime,
        version=ArtifactVersionRead.model_validate(version),
        nonce=nonce,
        live=live,
        injected=inject,
        awaiting_consent=awaiting_consent,
        bindings=len(version.bindings),
    )


def with_platform_script(document: bytes, script: str) -> bytes:
    """The document with the platform `script` first in it, after the doctype.

    First, because the script only listens on `document`, and a `<script>`
    before `<html>` is placed by the parser into the head it opens implicitly -
    the page's own `<html lang>` attributes still land on that element. After
    the doctype, because one that is not first is ignored and the page renders
    in quirks mode. It used to look for `<head>`, then `<html>`, by pattern, and
    a `<!-- <head> -->` comment or the text of a script put it where it never ran.
    """
    lead = next(_DOCUMENT_LEAD.finditer(document)).end()
    return document[:lead] + script.encode("utf-8") + document[lead:]


def render(
    version: ArtifactVersion,
    data: bytes,
    *,
    title: str,
    nonce: str,
    live: bool,
    initial: Mapping[str, BindingData] | None = None,
) -> bytes:
    """The document a frame shows: HTML as written, Markdown rendered into a page.

    Either way behind :func:`platform_script`, which names the version's bindings
    and, with `initial`, carries their data.
    """
    if version.media_type == ArtifactMediaType.MARKDOWN:
        body = _MARKDOWN.render(data.decode("utf-8"))
        data = _MARKDOWN_PAGE.format(title=escape(title), body=body).encode("utf-8")
    names = [binding["name"] for binding in version.bindings]
    script = platform_script(nonce=nonce, live=live, names=names, initial=initial)
    return with_platform_script(data, script)


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
        self,
        ctx: AuthContext,
        artifact_id: UUID,
        *,
        perm: Perm = Perm.ARTIFACTS_VIEW,
        archived: bool = False,
    ) -> Artifact:
        """The artifact, when the caller may do `perm` to it.

        Args:
            archived: Whether an archived artifact is found too. Only reading it,
                archiving, restoring and deleting it ask for one; to every other
                path an archived page is a missing one.

        Raises:
            NotFoundError: No such artifact in the caller's organization, one the
                caller may not do `perm` to, or an archived one not asked for.
        """
        artifact = await artifact_repo.get(
            self.db, artifact_id, organization_id=ctx.organization_id
        )
        # 404 for all three: whether a private artifact exists is itself something
        # the caller may not learn, and a revoked member is told the same thing.
        if (
            artifact is None
            or (artifact.archived_at is not None and not archived)
            or not await resolve_access(self.db, ctx, artifact, perm, resource_type=ARTIFACT)
        ):
            raise NotFoundError(
                message="Artifact not found", details={"artifact_id": str(artifact_id)}
            )
        return artifact

    async def read(self, ctx: AuthContext, artifact_id: UUID) -> ArtifactDetail:
        """One artifact, and whether the caller may manage it - decided here, grants included.

        An archived artifact is read only by a caller who may edit it, the one who
        can restore it; anybody else is told it is not found.
        """
        try:
            artifact = await self.get(ctx, artifact_id, archived=True)
        except NotFoundError:
            await self._offer_access_request(ctx, artifact_id)
            raise
        can_edit = await resolve_access(
            self.db, ctx, artifact, Perm.ARTIFACTS_EDIT, resource_type=ARTIFACT
        )
        if artifact.archived_at is not None and not can_edit:
            raise NotFoundError(
                message="Artifact not found", details={"artifact_id": str(artifact_id)}
            )
        return await self._detail(ctx, artifact, can_edit=can_edit)

    async def _offer_access_request(self, ctx: AuthContext, artifact_id: UUID) -> None:
        """Answer a member who cannot open a page that they may ask for access, in place of
        "not found" - and nothing else about it: no title, owner or agent.

        Raises nothing for anyone else (another organization's page, an archived or
        missing one, a caller with no member behind them), who keep the plain 404.

        Raises:
            AccessRequestableError: The page is in the caller's organization, live, and
                theirs to ask for.
        """
        artifact = await artifact_repo.get(
            self.db, artifact_id, organization_id=ctx.organization_id
        )
        if artifact is None or artifact.archived_at is not None or ctx.user_id is None:
            return
        if (
            await member_repo.get_active(
                self.db, organization_id=ctx.organization_id, user_id=ctx.user_id
            )
            is None
        ):
            return
        asked = await artifact_share_request_repo.pending(
            self.db, artifact.id, kind=ShareRequestKind.ACCESS, requester_user_id=ctx.user_id
        )
        raise AccessRequestableError(
            details={"artifact_id": artifact.id, "requested": asked is not None}
        )

    async def _detail(
        self, ctx: AuthContext, artifact: Artifact, *, can_edit: bool
    ) -> ArtifactDetail:
        """The artifact at the version `ctx` is served, with its consent for one served the latest."""
        view = await served(self.db, ctx, artifact, can_edit=can_edit)
        current = view.version
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
            may_change_owner=may_change_owner(ctx, artifact),
            may_grant_edit_data=may_grant_edit_data(ctx, artifact),
            bindings=_binding_reads(current) if can_edit else [],
            consent=(
                await self._consent(ctx, artifact, current, can_edit=can_edit)
                if view.latest and current is not None and current.bindings
                else None
            ),
        )

    async def _consent(
        self, ctx: AuthContext, artifact: Artifact, latest: ArtifactVersion, *, can_edit: bool
    ) -> ArtifactConsentRead:
        """Where the latest version's data stands, for a caller served it."""
        membership = await owner_membership_id(self.db, artifact)
        state = shown_state(latest, artifact, membership)
        audience = await artifact_repo.latest_served(self.db, artifact.id)
        confirms = may_confirm(ctx, artifact)
        automatic = state == ConsentState.CONSENTED and latest.consent_automatic
        owner = ctx.user_id is not None and ctx.user_id == artifact.owner_user_id
        return ArtifactConsentRead(
            version=latest.number,
            state=state.value,
            fingerprint=latest.query_fingerprint,
            automatic=automatic,
            grown=await grown(self.db, ctx, artifact, latest) if automatic and confirms else [],
            via=(
                await name_of(self.db, latest.consent_via_grant)
                if automatic and confirms and latest.consent_via_grant is not None
                else None
            ),
            audience_version=audience.number if audience is not None else None,
            shared=audience is not None
            and (not audience.bindings or consent_holds(audience, artifact, membership)),
            owner_name=await _owner_name(self.db, artifact),
            withdrawn_at=artifact.consent_withdrawn_at,
            auto_consent=artifact.auto_consent,
            may_confirm=confirms,
            may_withdraw=can_edit and as_themselves(ctx),
            may_enable_auto_consent=owner and as_themselves(ctx),
            may_disable_auto_consent=owner or ctx.scope_for(Perm.ARTIFACTS_EDIT) is Scope.ALL,
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
            live=current is not None and bool(current.bindings),
            archived_at=artifact.archived_at,
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
        include_archived: bool = False,
        search: str | None = None,
        agent_id: UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> ArtifactList:
        """A page of the artifacts this caller may open, newest publication first.

        Archived ones only with `include_archived`, by the same visibility rules. Each
        is read at the version the caller is served; one with none available to them
        yet has no `current_version`.
        """
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
            include_archived=include_archived,
            search=search,
            agent_id=agent_id,
            skip=skip,
            limit=limit,
        )
        current = await served_many(self.db, ctx, items)
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
        """The kept versions the caller may open, newest first.

        All of them for a caller served the latest version; for the page's audience,
        the consented or unbound ones up to the one it is served - never one waiting
        for consent, or declined.
        """
        artifact = await self.get(ctx, artifact_id)
        view = await self._served(ctx, artifact)
        versions = visible_versions(view, await artifact_repo.list_versions(self.db, artifact.id))
        membership = (
            await owner_membership_id(self.db, artifact)
            if any(version.consent_state == ConsentState.CONSENTED.value for version in versions)
            else None
        )
        return ArtifactVersionList(
            items=[
                ArtifactVersionRead.model_validate(version).model_copy(
                    update={"consent_state": shown_state(version, artifact, membership).value}
                )
                for version in versions
            ],
            total=len(versions),
        )

    async def _served(self, ctx: AuthContext, artifact: Artifact) -> Served:
        """The version `ctx` is served of `artifact`, with whether they may edit it decided here."""
        can_edit = await resolve_access(
            self.db, ctx, artifact, Perm.ARTIFACTS_EDIT, resource_type=ARTIFACT
        )
        return await served(self.db, ctx, artifact, can_edit=can_edit)

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
        new is stored. The new version records the number it was restored from,
        so the history says which versions a person put back rather than a run
        wrote. Restoring the current version changes nothing.

        A restored version's page queries are kept, and what they reach is read
        again from the tables now (:func:`~app.services.artifact_bindings.reresolve`):
        the caller and the page's owner must both read every table they reach. Its
        consent is decided as a publish's is: carried when the queries match the
        newest consent that holds, automatic for the owner's own restore with
        auto-consent on, and waiting for the owner otherwise.

        Raises:
            NotFoundError: The artifact is not the caller's to change, the version
                is not one of its kept versions, or storage no longer has its
                bytes - restored, it would be a current version that 404s.
            AuthorizationError: The caller or the page's owner cannot read a table
                the version's data reads.
            BadRequestError: A table no longer answers a filter or the sort of the
                version's data - a column converted since.
        """
        artifact = await self.get(ctx, artifact_id, perm=Perm.ARTIFACTS_EDIT)
        locked = await artifact_repo.lock(self.db, artifact.id)
        source = await artifact_repo.get_version(self.db, version_id, artifact_id=artifact.id)
        if locked is None or source is None:
            raise NotFoundError(
                message="This version of the artifact is no longer kept",
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
        bindings = await self._reresolved(ctx, locked, _bindings_of(source))
        version = await _append_version(
            self.db,
            locked,
            latest,
            media_type=source.media_type,
            size_bytes=source.size_bytes,
            sha256=source.sha256,
            storage_path=source.storage_path,
            run_id=None,
            bindings=[binding.model_dump(mode="json") for binding in bindings],
            consent=await consent_for(
                self.db, locked, fingerprint=fingerprint(bindings), person=ctx
            ),
            restored_from=source.number,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="artifact.version_restored",
            target_type="artifact",
            target_id=str(locked.id),
            details={
                "version": version.number,
                "restored": source.number,
                "bindings": [binding.name for binding in bindings],
            },
        )
        await _audit_automatic_consent(self.db, locked, version, actor_user_id=ctx.user_id)
        return await self._detail(ctx, locked, can_edit=True)

    async def _reresolved(
        self, ctx: AuthContext, artifact: Artifact, stored: list[ArtifactBinding]
    ) -> list[ArtifactBinding]:
        """A restored version's page queries, each with its reach read again as `ctx`."""
        if not stored:
            return []
        owner = await _owner(self.db, artifact, ctx)
        resolved: list[ArtifactBinding] = []
        refused: list[Refused] = []
        for binding in stored:
            outcome = await reresolve(self.db, binding, person=ctx, owner=owner)
            if isinstance(outcome, Refused):
                refused.append(outcome)
            else:
                resolved.append(outcome)
        if refused:
            message = f"{' '.join(r.message for r in refused)} So this version can't be restored."
            details = {"artifact_id": artifact.id}
            if any(r.forbidden for r in refused):
                raise AuthorizationError(message=message, details=details)
            raise BadRequestError(message=message, details=details)
        return resolved

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
            BadRequestError: An expiry in the past, a version that is not kept or
                whose data waits for consent, or an embedding site that is not an
                origin - each naming its field.
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
            raise refused_field(
                "pinned_version_id", "That version of the artifact is no longer kept."
            )
        # The link is for the audience, which never sees a version waiting for consent.
        if version.consent_state not in SERVED_STATES:
            raise refused_field(
                "pinned_version_id",
                "That version's data hasn't been confirmed by the page's owner, so the link "
                "can't show it.",
            )
        # A kept row whose bytes are gone would pin the link to a page that 404s.
        if not await get_file_storage().exists(version.storage_path):
            raise refused_field("pinned_version_id", "That version's content is gone from storage.")
        return version.number

    async def clear_public_link(self, ctx: AuthContext, artifact_id: UUID) -> ArtifactDetail:
        """Turn the public address off. A frame already open keeps its page until its
        signed address expires, `ARTIFACT_VIEW_TTL_SECONDS` at most."""
        artifact = await self.get(ctx, artifact_id, perm=Perm.ARTIFACTS_EDIT)
        artifact = await self._turn_off_public_link(ctx, artifact)
        return await self._detail(ctx, artifact, can_edit=True)

    async def _turn_off_public_link(self, ctx: AuthContext, artifact: Artifact) -> Artifact:
        """Clear the public key, audited, when one is on. Its settings stay for next time."""
        if artifact.public_key is None:
            return artifact
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
        return artifact

    async def archive(self, ctx: AuthContext, artifact_id: UUID) -> ArtifactDetail:
        """Archive a page: it keeps its versions, grants and name, and serves nothing.

        Its public link is turned off, as `clear_public_link` turns it off, and a
        restore does not turn it back on - an address that was sent out before the
        archive stays dead until someone makes a new one. A signed address minted
        before the archive serves nothing more either, so a frame already open
        keeps only what it had loaded. Archiving twice is not an error.

        Raises:
            NotFoundError: The artifact is not the caller's to change.
        """
        artifact = await self.get(ctx, artifact_id, perm=Perm.ARTIFACTS_EDIT, archived=True)
        if artifact.archived_at is not None:
            return await self._detail(ctx, artifact, can_edit=True)
        artifact = await self._turn_off_public_link(ctx, artifact)
        artifact = await artifact_repo.update(
            self.db, artifact=artifact, update_data={"archived_at": datetime.now(UTC)}
        )
        await void_all(self.db, artifact, VoidReason.ARCHIVED)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="artifact.archived",
            target_type="artifact",
            target_id=str(artifact.id),
            details={"name": artifact.name},
        )
        return await self._detail(ctx, artifact, can_edit=True)

    async def unarchive(self, ctx: AuthContext, artifact_id: UUID) -> ArtifactDetail:
        """Restore an archived page, so it is served again, as archiving left it.

        Asks for the same edit right archiving does. The public link stays off.

        Raises:
            NotFoundError: The artifact is not the caller's to change.
            BadRequestError: The artifact is not archived.
        """
        artifact = await self.get(ctx, artifact_id, perm=Perm.ARTIFACTS_EDIT, archived=True)
        if artifact.archived_at is None:
            raise BadRequestError(
                message=f"Artifact '{artifact.title}' is not archived",
                details={"artifact_id": artifact.id},
            )
        artifact = await artifact_repo.update(
            self.db, artifact=artifact, update_data={"archived_at": None}
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="artifact.unarchived",
            target_type="artifact",
            target_id=str(artifact.id),
            details={"name": artifact.name},
        )
        return await self._detail(ctx, artifact, can_edit=True)

    async def delete(self, ctx: AuthContext, artifact_id: UUID) -> None:
        """Delete an artifact, every version, its grants and its link - archived or not.

        The bytes go after the commit, so a rollback leaves rows that still point
        at what is stored.
        """
        artifact = await self.get(ctx, artifact_id, perm=Perm.ARTIFACTS_EDIT, archived=True)
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

    async def disclosure(
        self, ctx: AuthContext, artifact_id: UUID, version_id: UUID
    ) -> ArtifactDisclosure:
        """What confirming a version would share, and with whom, in words.

        Each page query as its owner reads the tables now, every table it reads, and
        the page's audience: its visibility, the people and groups it is shared with,
        and the roles that open every page. For a caller who may confirm it
        (:func:`~app.services.artifact_consent.may_confirm`).

        Raises:
            NotFoundError: The artifact is not the caller's to open, or the version is
                not one of its kept versions.
            AuthorizationError: The caller may not confirm its data.
        """
        artifact = await self.get(ctx, artifact_id)
        self.held_to_confirming(ctx, artifact)
        version = await self.kept(artifact, version_id)
        bindings = _bindings_of(version)
        problem, sources = await self.tables_for_words(ctx, artifact, bindings)
        people, groups = await self._grantees(artifact)
        shown = {
            binding.name: binding
            for binding in bindings
            if all(table_id in sources for table_id in binding.reach.tables)
        }
        return ArtifactDisclosure(
            version=version.number,
            fingerprint=version.query_fingerprint,
            bindings={name: disclose(binding, sources) for name, binding in shown.items()},
            parts={name: describe(binding, sources) for name, binding in shown.items()},
            tables=sorted({source.name for source in sources.values()}),
            visibility=artifact.visibility,
            people=people,
            groups=groups,
            roles=list(PAGE_ROLES),
            problem=problem,
        )

    async def tables_for_words(
        self, ctx: AuthContext, artifact: Artifact, bindings: Sequence[ArtifactBinding]
    ) -> tuple[str | None, dict[UUID, TableSource]]:
        """The tables `bindings` reach, as the page's owner reads them - and, for what the
        owner no longer can, as `ctx` does - to put a page query into words.

        The first part is why it cannot be confirmed: the owner is gone or can't read a table.
        """
        owner = (
            await member_context(
                self.db, organization_id=artifact.organization_id, user_id=artifact.owner_user_id
            )
            if artifact.owner_user_id is not None
            else None
        )
        problem, sources = await self._owner_reads(owner, bindings)
        if owner is not None and owner.user_id != ctx.user_id:
            # An admin confirming for the owner may read a table the owner no longer
            # can; the words are still worth showing beside the refusal.
            _, mine = await self._owner_reads(ctx, bindings)
            sources = {**mine, **sources}
        return problem, sources

    async def _grantees(self, artifact: Artifact) -> tuple[list[str], list[str]]:
        """The addresses of the people and the names of the groups the page is shared with."""
        grants = await resource_grant_repo.list_for_resource(
            self.db,
            organization_id=artifact.organization_id,
            resource_type=ARTIFACT.key,
            resource_id=artifact.id,
        )
        emails = await member_repo.get_emails_for_users(
            self.db,
            organization_id=artifact.organization_id,
            user_ids=[grant.subject_user_id for grant in grants if grant.subject_user_id],
        )
        names = await group_repo.get_names(
            self.db,
            organization_id=artifact.organization_id,
            group_ids=[grant.subject_group_id for grant in grants if grant.subject_group_id],
        )
        return (
            sorted(email for email in emails.values() if email is not None),
            sorted(names.values()),
        )

    async def confirm_data(
        self,
        ctx: AuthContext,
        artifact_id: UUID,
        version_id: UUID,
        data: ArtifactConsentCreate,
    ) -> ArtifactDetail:
        """Consent to the page's audience reading the latest version's data.

        By the page's owner, or by a holder of `artifacts:edit` at scope `ALL` for
        them - each as themselves; a grant to edit the page is not enough. The
        consent is recorded under the owner's membership now, so it lapses if they
        leave, and the owner must still read every table the queries reach. Audited
        `artifact.data_consented`, with `for_owner` when an admin gave it. Confirming
        a consent that already holds changes nothing.

        Raises:
            NotFoundError: The artifact is not the caller's to open, or the version is
                not one of its kept versions.
            AuthorizationError: The caller may not confirm its data, or the page's
                owner is no longer an active member or can't read a table it reaches.
            ConcurrentChangeError: The version is no longer the latest, or its page
                queries are not the ones the person was shown.
            BadRequestError: The version reads no data.
        """
        artifact = await self.get(ctx, artifact_id)
        self.held_to_confirming(ctx, artifact)
        # Under the lock a publish takes, so no version lands between this check and the write.
        await artifact_repo.lock(self.db, artifact.id)
        # Again on the locked, fresh row: a switch of owner committed since `get` must not
        # let the old owner record a consent under the new owner's membership.
        self.held_to_confirming(ctx, artifact)
        version = await self.kept(artifact, version_id)
        latest = await artifact_repo.latest_version(self.db, artifact.id)
        if (
            latest is None
            or latest.id != version.id
            or version.query_fingerprint != data.fingerprint
        ):
            raise ConcurrentChangeError(
                message="The page changed after you looked at it. Review what it shares now.",
                details={"artifact_id": artifact.id, "version_id": version.id},
            )
        if not version.bindings:
            raise BadRequestError(
                message="This version reads no data, so there is nothing to confirm.",
                details={"artifact_id": artifact.id, "version_id": version.id},
            )
        owner = (
            await member_context(
                self.db, organization_id=artifact.organization_id, user_id=artifact.owner_user_id
            )
            if artifact.owner_user_id is not None
            else None
        )
        problem, _ = await self._owner_reads(owner, _bindings_of(version))
        membership = await owner_membership_id(self.db, artifact)
        if problem is not None or owner is None or membership is None:
            raise AuthorizationError(
                message=problem or _OWNER_GONE, details={"artifact_id": artifact.id}
            )
        if consent_holds(version, artifact, membership):
            return await self._detail(ctx, artifact, can_edit=await self._can_edit(ctx, artifact))
        await artifact_repo.update_version(
            self.db,
            version=version,
            update_data={
                "consent_state": ConsentState.CONSENTED.value,
                "consented_at": datetime.now(UTC),
                "consented_by_user_id": ctx.subject_id,
                "consented_by_membership_id": membership,
                "consent_automatic": False,
            },
        )
        await settle_version_request(
            self.db,
            artifact,
            version,
            status=ShareRequestStatus.APPROVED,
            by_user_id=ctx.user_id,
        )
        details: dict[str, object] = {
            "version": version.number,
            "fingerprint": version.query_fingerprint,
            "automatic": False,
        }
        if ctx.subject_id != artifact.owner_user_id:
            details["for_owner"] = str(artifact.owner_user_id)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="artifact.data_consented",
            target_type="artifact",
            target_id=str(artifact.id),
            details=details,
        )
        return await self._detail(ctx, artifact, can_edit=await self._can_edit(ctx, artifact))

    async def withdraw_consent(self, ctx: AuthContext, artifact_id: UUID) -> ArtifactDetail:
        """Stop the page's audience reading its data: void every consent given so far.

        Withdrawing narrows who reads the data, so anyone who may edit the page may,
        as themselves. Every consent on every version is void, not just the latest's -
        the audience keeps the page and gets its bindings `awaiting_consent`, never an
        older version's data - and auto-consent is turned off, so only the owner
        confirming again shares it. Every `edit_data` grant on the page is lowered to
        `edit` too, so a data editor's next republish waits for the owner instead of
        undoing the withdrawal. Audited `artifact.data_withdrawn`.

        Raises:
            NotFoundError: The artifact is not the caller's to change.
            AuthorizationError: The caller is not acting as themselves.
        """
        artifact = await self.get(ctx, artifact_id, perm=Perm.ARTIFACTS_EDIT)
        if not as_themselves(ctx):
            raise AuthorizationError(message=_AS_THEMSELVES, details={"artifact_id": artifact.id})
        await artifact_repo.lock(self.db, artifact.id)
        audience = await artifact_repo.latest_served(self.db, artifact.id)
        auto_consent_was_on = artifact.auto_consent
        artifact = await artifact_repo.update(
            self.db,
            artifact=artifact,
            update_data={"consent_withdrawn_at": datetime.now(UTC), "auto_consent": False},
        )
        lowered = await resource_grant_repo.lower_edit_data(
            self.db, organization_id=artifact.organization_id, resource_id=artifact.id
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="artifact.data_withdrawn",
            target_type="artifact",
            target_id=str(artifact.id),
            details={
                "audience_version": audience.number if audience is not None else None,
                "auto_consent_was_on": auto_consent_was_on,
                "edit_data_lowered": lowered,
            },
        )
        return await self._detail(ctx, artifact, can_edit=True)

    async def set_auto_consent(
        self, ctx: AuthContext, artifact_id: UUID, data: ArtifactAutoConsentUpdate
    ) -> ArtifactDetail:
        """Turn "don't ask for consent on republish" on or off.

        On: only the page's owner, as themselves, having confirmed the text that says
        what it does (`confirmed` names its version, :data:`AUTO_CONSENT_WORDING`).
        Off: the owner, or a holder of `artifacts:edit` at scope `ALL`. Audited
        `artifact.auto_consent_changed` with the confirmed text's version.

        Raises:
            NotFoundError: The artifact is not the caller's to open.
            AuthorizationError: The caller may not make this change.
            BadRequestError: Turning it on without confirming the current text.
        """
        artifact = await self.get(ctx, artifact_id)
        # Who the owner is is read on the locked, fresh row, not the one `get` returned.
        await artifact_repo.lock(self.db, artifact.id)
        owner = ctx.user_id is not None and ctx.user_id == artifact.owner_user_id
        if data.enabled and not (owner and as_themselves(ctx)):
            raise AuthorizationError(
                message="Only the page's owner, signed in as themselves, can turn this on.",
                details={"artifact_id": artifact.id},
            )
        if not data.enabled and not (owner or ctx.scope_for(Perm.ARTIFACTS_EDIT) is Scope.ALL):
            raise AuthorizationError(
                message="Only the page's owner or an admin can turn this off.",
                details={"artifact_id": artifact.id},
            )
        if data.enabled and data.confirmed != AUTO_CONSENT_WORDING:
            raise refused_field(
                "confirmed", "Confirm what turning this on does before turning it on."
            )
        if artifact.auto_consent != data.enabled:
            artifact = await artifact_repo.update(
                self.db, artifact=artifact, update_data={"auto_consent": data.enabled}
            )
            await record_audit(
                self.db,
                actor_user_id=ctx.subject_id,
                organization_id=ctx.organization_id,
                action="artifact.auto_consent_changed",
                target_type="artifact",
                target_id=str(artifact.id),
                details={
                    "enabled": data.enabled,
                    "wording": AUTO_CONSENT_WORDING if data.enabled else None,
                    "wording_text": AUTO_CONSENT_TEXTS[AUTO_CONSENT_WORDING]
                    if data.enabled
                    else None,
                },
            )
        return await self._detail(ctx, artifact, can_edit=await self._can_edit(ctx, artifact))

    async def change_owner(
        self, ctx: AuthContext, artifact_id: UUID, data: ArtifactOwnerUpdate
    ) -> ArtifactDetail:
        """Hand the page to another active member of its organization.

        Only its owner, or an Owner or Admin for any page (`artifacts:edit` at scope `ALL`,
        a page without an owner included), each signed in as themselves - not a grant to
        edit it. Immediate: the page's data waits for the new owner's consent, and
        auto-consent goes off. Audited `artifact.owner_changed`; the old and the new
        owner are notified. See :func:`app.services.artifact_ownership.change_owner`.

        Raises:
            NotFoundError: The artifact is not the caller's to open.
            AuthorizationError: The caller may not change its owner.
            BadRequestError: The new owner owns it already, or is not an active member.
        """
        artifact = await self.get(ctx, artifact_id)
        require_may_change_owner(ctx, artifact)
        artifact = await change_owner(self.db, ctx, artifact, new_owner_user_id=data.user_id)
        return await self._detail(ctx, artifact, can_edit=await self._can_edit(ctx, artifact))

    @staticmethod
    def held_to_confirming(ctx: AuthContext, artifact: Artifact) -> None:
        if not may_confirm(ctx, artifact):
            raise AuthorizationError(
                message=(
                    "Only the page's owner, or an Owner or Admin for them, can confirm its "
                    "data - signed in as themselves."
                ),
                details={"artifact_id": artifact.id},
            )

    async def _can_edit(self, ctx: AuthContext, artifact: Artifact) -> bool:
        return await resolve_access(
            self.db, ctx, artifact, Perm.ARTIFACTS_EDIT, resource_type=ARTIFACT
        )

    async def kept(self, artifact: Artifact, version_id: UUID) -> ArtifactVersion:
        version = await artifact_repo.get_version(self.db, version_id, artifact_id=artifact.id)
        if version is None:
            raise NotFoundError(
                message="This version of the artifact is no longer kept",
                details={"artifact_id": artifact.id, "version_id": version_id},
            )
        return version

    async def _owner_reads(
        self, reader: AuthContext | None, bindings: Sequence[ArtifactBinding]
    ) -> tuple[str | None, dict[UUID, TableSource]]:
        """Every table the page queries reach, as `reader` reads them, and what they can't.

        Check 1 as the page's owner: `None` when every table is readable, otherwise a
        sentence naming the ones that are not - or saying the owner is gone.
        """
        if reader is None:
            return _OWNER_GONE, {}
        service = VirtualTableService(self.db)
        sources: dict[UUID, TableSource] = {}
        lacking: list[UUID] = []
        for table_id in sorted({table for b in bindings for table in b.reach.tables}):
            try:
                sources[table_id] = await service.table_source(reader, table_id)
            except NotFoundError:
                lacking.append(table_id)
        if not lacking:
            return None, sources
        return (
            f"The page's owner can't read {len(lacking)} of the tables its data reads, so it "
            "can't be shared. Ask them for access, or publish the page without those tables.",
            sources,
        )

    async def view(
        self,
        ctx: AuthContext,
        artifact_id: UUID,
        *,
        version_id: UUID | None = None,
        data: bool = False,
    ) -> ArtifactView:
        """A signed address for the version the caller is served, or for one named version.

        The page's audience may name only a version :meth:`versions` lists for it, so
        it never opens one waiting for consent.

        With `data`, and only for the version the caller is served, the page is served
        with its bindings' data written into it (`injected`), so it has them on load.
        Without it - a thumbnail, a card, a history preview - the page gets none.

        Raises:
            NotFoundError: The artifact is not the caller's to open, nothing of it is
                available to them yet (`not_available_yet`), or the version asked for
                was pruned or is not one they may open.
        """
        artifact = await self.get(ctx, artifact_id)
        view = await self._served(ctx, artifact)
        if view.version is None:
            raise _not_available_yet(artifact)
        version = view.version
        if version_id is not None and version_id != version.id:
            asked = await artifact_repo.get_version(self.db, version_id, artifact_id=artifact.id)
            if asked is None or not visible_versions(view, [asked]):
                raise NotFoundError(
                    message="This version of the artifact is no longer kept",
                    details={"artifact_id": str(artifact_id), "version_id": version_id},
                )
            # An older version's bindings say what it read once; only the version a
            # viewer is served reads data, so only its page asks for it.
            return _view(asked, live=False, viewer=ctx)
        live = bool(version.bindings)
        # Only a member is served data: an app admin who belongs to no organization
        # reads through the data route, which refuses them with the reason to show.
        member = (
            live
            and data
            and ctx.user_id is not None
            and await member_context(
                self.db, organization_id=artifact.organization_id, user_id=ctx.user_id
            )
            is not None
        )
        return _view(
            version,
            live=live,
            viewer=ctx,
            inject=bool(member),
            awaiting_consent=live and not view.data,
        )

    async def data(self, ctx: AuthContext, artifact_id: UUID, version_id: UUID) -> ArtifactData:
        """A page version's live data: every binding's page query, read as the page's owner.

        Everyone allowed the data reads the same records, whatever their own access to
        the tables: the owner's, as the member they are now. The owner and the roles
        that read every table (`tables:view` at scope `ALL`) are allowed it always;
        anyone else only while the owner's consent to the version they are served
        holds (:mod:`app.services.artifact_consent`), and otherwise gets every binding
        `unavailable`, `awaiting_consent`.

        A binding is `unavailable` when the owner is no longer an active member
        (`creator_gone`) or cannot read a table its query reaches
        (`creator_lost_access`), when something it reaches changed since it was
        published (`source_changed`, naming what in `changed`), or when the page's
        deadline left no time for it (`timeout`); only a caller who may edit the page
        is told why, but `awaiting_consent` is told to everyone. Only the version the
        caller is served is read; another gets every binding `unavailable` with the
        reason `not_current`, and `current` false - unlike `reason`, told to every
        viewer, so a console showing it moves to the version served now.

        Each binding reads in a savepoint of its own, so a query stopped by its
        `statement_timeout` costs that binding alone and the request still commits.
        The page's deadline is a deadline, never a cancellation: it is checked before
        every query and between bindings.

        Raises:
            RateLimitError: `ctx` already has a load in flight, or this process is
                serving as many loads as it may. Refused at once, never queued.
            NotFoundError: The artifact is not the caller's to open, or the version
                is not one of its kept versions that the caller may open.
        """
        async with rate_limit.one_in_flight(
            "artifact_data",
            f"org:{ctx.organization_id}:user:{ctx.subject_id}",
            ttl_seconds=settings.ARTIFACT_DATA_READ_TIMEOUT_SECONDS + 5,
            message=_IN_FLIGHT,
        ):
            gate = _load_gate()
            if gate.locked():
                raise RateLimitError(message=_BUSY, details={"retry_after_seconds": 1})
            async with gate:
                return await self._data(ctx, artifact_id, version_id)

    async def _data(self, ctx: AuthContext, artifact_id: UUID, version_id: UUID) -> ArtifactData:
        artifact = await self.get(ctx, artifact_id)
        can_edit = await resolve_access(
            self.db, ctx, artifact, Perm.ARTIFACTS_EDIT, resource_type=ARTIFACT
        )
        view = await served(self.db, ctx, artifact, can_edit=can_edit)
        version = await artifact_repo.get_version(self.db, version_id, artifact_id=artifact.id)
        if version is None or not visible_versions(view, [version]):
            raise NotFoundError(
                message="This version of the artifact is no longer kept",
                details={"artifact_id": str(artifact_id), "version_id": str(version_id)},
            )
        current = view.version is not None and view.version.id == version.id
        return ArtifactData(
            bindings=await self._read_page(
                artifact, version, view, can_edit=can_edit, current=current
            ),
            current=current,
            read_at=datetime.now(UTC),
        )

    async def _read_page(
        self,
        artifact: Artifact,
        version: ArtifactVersion,
        view: Served,
        *,
        can_edit: bool,
        current: bool,
        isolate_failures: bool = False,
    ) -> dict[str, BindingData]:
        """Every binding of `version` read as the page's owner, shaped for one viewer.

        The one read the data route and a page served with its data share. With
        `isolate_failures` a binding the database failed on is `failed` rather than an
        error, so the page still renders.
        """
        deadline = ReadDeadline(
            settings.ARTIFACT_DATA_READ_TIMEOUT_SECONDS,
            settings.ARTIFACT_DATA_STATEMENT_TIMEOUT_MS,
        )
        bindings = sorted(_bindings_of(version), key=lambda item: item.name)
        owner = (
            await member_context(
                self.db, organization_id=artifact.organization_id, user_id=artifact.owner_user_id
            )
            if bindings and artifact.owner_user_id is not None
            else None
        )
        reads: dict[str, BindingRows | Unavailable] = {}
        for binding in bindings:
            if not current:
                reads[binding.name] = Unavailable("not_current")
            elif owner is None:
                reads[binding.name] = self._unavailable(binding, Unavailable("creator_gone"))
            elif not view.data:
                reads[binding.name] = Unavailable("awaiting_consent")
            else:
                try:
                    reads[binding.name] = await self._read_binding(owner, binding, deadline)
                except DBAPIError as failed:
                    if not isolate_failures:
                        raise
                    # Never the message: a database error carries its bound parameters,
                    # which are the query's filter values.
                    logger.warning(
                        "artifact_data_binding_failed",
                        extra={
                            "binding": binding.name,
                            "table_id": str(binding.table_id),
                            "error_type": type(failed).__name__,
                            "sqlstate": getattr(failed.orig, "sqlstate", None),
                        },
                    )
                    reads[binding.name] = self._unavailable(binding, Unavailable("failed"))
        return page_data(reads, max_bytes=settings.ARTIFACT_DATA_MAX_BYTES, can_edit=can_edit)

    async def _read_binding(
        self, owner: AuthContext, binding: ArtifactBinding, deadline: ReadDeadline
    ) -> BindingRows | Unavailable:
        """One binding's page query read as the page's `owner`, or why it reads nothing."""
        if deadline.remaining_ms() <= 0:
            return self._unavailable(binding, Unavailable("timeout"))
        service = VirtualTableService(self.db)
        table: str | None = None
        try:
            async with self.db.begin_nested():
                prior = await virtual_table_repo.statement_timeout(self.db)
                source = await page_source(service, owner, binding, deadline=deadline)
                if isinstance(source, Unavailable):
                    await virtual_table_repo.restore_statement_timeout(self.db, setting=prior)
                    return self._unavailable(binding, source)
                table = source.name
                rows = await service.read_bound(
                    owner,
                    table_id=source.id,
                    columns=source.columns,
                    filters=binding.filters,
                    sort=binding.sort,
                    column_ids=list(binding.fields.values()),
                    shape=shape_for(source.columns, binding.fields),
                    max_records=min(binding.limit, settings.ARTIFACT_DATA_MAX_RECORDS),
                    max_bytes=settings.ARTIFACT_DATA_MAX_BYTES,
                    deadline=deadline,
                )
                # Only on success: a statement stopped by its timeout aborts the
                # savepoint, and rolling that back restores the setting by itself.
                await virtual_table_repo.restore_statement_timeout(self.db, setting=prior)
        except InvalidQueryError:
            # The revisions match, yet the table no longer answers a filter or the sort:
            # a query restored before its columns were converted. One binding, never the page.
            return self._unavailable(binding, Unavailable("source_changed", table))
        except DeadlineReached:
            return self._unavailable(binding, Unavailable("timeout"))
        except DBAPIError as failed:
            if getattr(failed.orig, "sqlstate", None) != _STATEMENT_TIMEOUT:
                raise
            return self._unavailable(binding, Unavailable("timeout"))
        return BindingRows(fields=binding.fields, rows=rows)

    @staticmethod
    def _unavailable(binding: ArtifactBinding, unavailable: Unavailable) -> Unavailable:
        # Never the exception: a database error carries its bound parameters, which
        # are the query's filter values.
        logger.info(
            "artifact_data_binding_unavailable",
            extra={
                "binding": binding.name,
                "table_id": str(binding.table_id),
                "reason": unavailable.reason,
            },
        )
        return unavailable

    async def _public(self, public_key: str) -> tuple[Artifact, ArtifactVersion]:
        """The artifact behind a public key and the version its link shows.

        Its pinned version, or the one the page's audience is served - never a version
        waiting for consent, whose page a stranger must not see before members do.

        Raises:
            NotFoundError: No artifact has this key - never made, revoked, rotated,
                expired or archived, which the caller cannot tell apart - or none of
                its versions is available to its audience yet.
        """
        artifact = await artifact_repo.get_by_public_key(self.db, public_key)
        # Archiving clears the key; checked here as well, so an archived page with a
        # key - written by hand, or by a path that forgot - still opens nothing.
        if artifact is not None and (
            artifact.archived_at is not None
            or (
                artifact.public_expires_at is not None
                and artifact.public_expires_at <= datetime.now(UTC)
            )
        ):
            artifact = None
        version = None
        if artifact is not None:
            version = (
                await artifact_repo.get_version_by_number(
                    self.db, artifact.id, artifact.public_version_number
                )
                if artifact.public_version_number is not None
                else await artifact_repo.latest_served(self.db, artifact.id)
            )
        if artifact is None or version is None:
            raise NotFoundError(message="Artifact not found")
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
            title=artifact.title,
            published_at=artifact.published_at,
            # A stranger is nobody the data could be read as.
            view=_view(version, live=False, public_key=public_key),
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
            frame_url=None if protected else _view(version, live=False, public_key=public_key).url,
            public_url=public_url_for(artifact) or "",
        )
        return EmbedDocument(
            document=document,
            policy=embed_security_policy(nonce=nonce, embed_origins=origins),
            available=True,
        )

    async def content(self, token: str) -> ServedArtifact:
        """The document behind a signed address, ready to serve, and who may frame it.

        A member's address is framed by the console alone; a public link's also by the
        sites its page names for embedding. A member's address minted for a page's
        data (`inj`) is served with each binding's page query already read in - for
        the viewer it names, as they are served now (:meth:`_injection`). A public
        address never gets data.

        Raises:
            NotFoundError: The token is invalid or expired, its version is gone,
                its artifact was archived since it was minted, or storage no
                longer has the version's bytes. One answer for all five, so the
                route gives an attacker nothing to distinguish.
        """
        payload = verify_special_token(token, "artifact_view", audience=("member", "public"))
        version_id = read_uuid_claim(payload, "sub") if payload is not None else None
        found = (
            await artifact_repo.get_version_with_artifact(self.db, version_id)
            if version_id is not None
            else None
        )
        if payload is None or found is None or found[1].archived_at is not None:
            raise NotFoundError(message="Artifact not found")
        version, artifact = found
        data = await _load_version(version, missing="Artifact not found")
        member = payload.get("aud") == "member"
        embeddable = (
            not member and artifact.public_key is not None and artifact.public_password_hash is None
        )
        # A token minted before the nonce existed has none to match replies on,
        # so its page is served as not live.
        nonce = payload.get("n")
        if not isinstance(nonce, str):
            nonce, live = "", False
        else:
            live = payload.get("live") is True
        initial = (
            await self._injection(payload, artifact, version)
            if member and live and payload.get("inj") is True
            else None
        )
        return ServedArtifact(
            document=render(
                version, data, title=artifact.title, nonce=nonce, live=live, initial=initial
            ),
            embed_origins=list(artifact.embed_origins or []) if embeddable else [],
        )

    async def _injection(
        self, claims: dict[str, Any], artifact: Artifact, version: ArtifactVersion
    ) -> dict[str, BindingData]:
        """What a page served to a member carries as its data: each binding, as they read it now.

        The token names the viewer, and nothing it says is trusted past that: the member
        is looked up as they are now, must still be allowed the page, and gets data only
        for the version they are served, by the consent rules of :func:`served` - the
        owner and the roles that read every table always, an editor or the audience while
        the owner's consent holds, and otherwise every binding `awaiting_consent`.
        A token for another organization, a viewer no longer a member or a version no
        longer served to them reads nothing. The load counts against the viewer's data
        limit and holds their one load in flight, as the data route does; refused, or
        failed in the database, a binding is `busy` or `failed` and the page still renders.
        Reasons are told only to an editor, as on the data route.
        """
        names = sorted(binding.name for binding in _bindings_of(version))
        user_id = read_uuid_claim(claims, "uid")
        organization_id = read_uuid_claim(claims, "org")
        reader = (
            await member_context(self.db, organization_id=artifact.organization_id, user_id=user_id)
            if user_id is not None and organization_id == artifact.organization_id
            else None
        )
        nothing = {name: unavailable(None) for name in names}
        if reader is None:
            return nothing
        try:
            artifact = await self.get(reader, artifact.id)
        except NotFoundError:
            return nothing
        can_edit = await resolve_access(
            self.db, reader, artifact, Perm.ARTIFACTS_EDIT, resource_type=ARTIFACT
        )
        view = await served(self.db, reader, artifact, can_edit=can_edit)
        if view.version is None or view.version.id != version.id:
            return page_data(
                {name: Unavailable("not_current") for name in names},
                max_bytes=settings.ARTIFACT_DATA_MAX_BYTES,
                can_edit=can_edit,
            )
        caller = f"org:{reader.organization_id}:user:{reader.subject_id}"
        busy = page_data(
            {name: Unavailable("busy") for name in names},
            max_bytes=settings.ARTIFACT_DATA_MAX_BYTES,
            can_edit=can_edit,
        )
        decision = await rate_limit.consume_with_local_floor(
            surface="artifact_data", caller=caller, limit=rate_limit.artifact_data_limit()
        )
        if not decision.allowed:
            return busy
        try:
            async with rate_limit.one_in_flight(
                "artifact_data",
                caller,
                ttl_seconds=settings.ARTIFACT_DATA_READ_TIMEOUT_SECONDS + 5,
                message=_IN_FLIGHT,
            ):
                gate = _load_gate()
                if gate.locked():
                    return busy
                async with gate:
                    return await self._read_page(
                        artifact,
                        version,
                        view,
                        can_edit=can_edit,
                        current=True,
                        isolate_failures=True,
                    )
        except RateLimitError:
            return busy
