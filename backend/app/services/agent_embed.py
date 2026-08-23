"""Publishing an agent on a public surface, and letting a stranger talk to it.

Two audiences in one service, and they are told different things.

*The owner* creates, edits and deletes embeds. Who may is `agents:publish` on
that agent, resolved through `resolve_access` - the same permission and the same
reasoning as an exposure: both answer "what does the outside world reach", and
somebody who may freeze a version may say where it runs.

*The visitor* has a key from a script tag, a client of their own or a link, and
nothing else. Everything they are allowed to do is decided here, from the row
that key names:

1. Is the embed active, and is its agent still published?
2. Is the origin they arrived from one this embed accepts?
3. In `jwt` mode, does their token verify against the customer's own secret?

The order matters. Origin is checked before the token because a request from an
unlisted site should learn nothing about whether a token would have worked.

Step 2 is the one place the three kinds diverge at admission: a `widget` and a
`socket` are checked against the operator's allow-list, and a `page` against
this deployment's own origin, because it is the only site that serves one.
"""

from __future__ import annotations

import contextlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID

import jwt
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.config import settings
from app.core.exceptions import (
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext, Perm
from app.core.vault import VaultScope, current_key_version, seal_fields, unseal
from app.db.models.agent_embed import AgentEmbed
from app.db.models.chat_file import ChatFile
from app.db.updates import cleared, writable
from app.repositories import agent_embed_repo, agent_repo, organization_repo
from app.schemas.agent_embed import (
    EmbedConfig,
    EmbedCreate,
    EmbedRead,
    EmbedUpdate,
    EmbedVariable,
    PageConfig,
    PublicEmbedConfig,
    PublicPageConfig,
    WidgetConfig,
)
from app.services.agent_registry import AgentRegistryService
from app.services.file_storage import IMAGE_MIME_TYPES, MAX_AVATAR_SIZE, get_file_storage
from app.services.file_upload import FileUploadService

logger = logging.getLogger(__name__)

# Long enough that guessing is hopeless, short enough to paste into a tag.
_KEY_BYTES = 24

# How stale a visitor token may be. The customer's backend mints these per page
# load; anything older is a token that leaked out of a browser somewhere.
_MAX_TOKEN_AGE_SECONDS = 60 * 60 * 12

_CONFIG_ADAPTER: TypeAdapter[EmbedConfig] = TypeAdapter(EmbedConfig)

# What a stored logo is called on disk, keyed on the type it was accepted as. A
# name is not decoration here: `/logo` is proxied from the origin the hosted page
# runs on, and a browser handed `logo.html` runs it. Keys are `IMAGE_MIME_TYPES`,
# and `set_page_logo` refuses anything outside that set before reaching this.
_LOGO_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


@dataclass(frozen=True)
class Admission:
    """What admitting a visitor established, for whoever serves them next."""

    embed: AgentEmbed
    visitor: str | None


class EmbedDenied(Exception):
    """The widget refuses this visitor, and the reason is not theirs to know.

    One exception for every refusal - inactive, wrong origin, bad token - so a
    caller cannot accidentally tell a stranger which of the three it was, and
    an origin probe learns nothing about tokens.
    """


def _own_origin() -> str:
    """The origin this deployment's own pages are served from.

    Derived from settings in the same place the socket URL is, and never
    hardcoded: a hosted page is served by the frontend, so what a browser reports
    when it opens the socket from `/e/<key>` is that host and not the API's.
    """
    return _origin_of(settings.FRONTEND_URL)


def _origin_of(value: str) -> str:
    """Scheme and host of a URL, which is what a browser sends as `Origin`."""
    parsed = urlparse(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return value.strip().rstrip("/").lower()
    return f"{parsed.scheme}://{parsed.netloc}".lower()


class AgentEmbedService:
    """Widgets: managing them, and admitting the people who arrive through one."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.agents = AgentRegistryService(db)

    async def list_for_agent(self, ctx: AuthContext, agent_id: UUID) -> list[EmbedRead]:
        """Every widget publishing one agent.

        Needs only `agents:view`: where an agent answers is part of what it is,
        and hiding it from somebody who can already read the agent would make
        the Builder lie by omission.
        """
        agent = await self.agents.get(ctx, agent_id)
        rows = await agent_embed_repo.list_for_agent(
            self.db, agent_id=agent.id, organization_id=ctx.organization_id
        )
        return [self._read(row) for row in rows]

    async def create(self, ctx: AuthContext, data: EmbedCreate) -> EmbedRead:
        """Publish an agent on one public surface.

        Raises:
            NotFoundError: If the agent is not reachable by this caller.
            AuthorizationError: Without `agents:publish` on that agent.
            BadRequestError: For a `jwt` embed with no secret, a `public` one
                carrying a secret nothing would ever read, or an origin list
                that contradicts the kind - see `_check_origins`.
        """
        agent = await self.agents.get(ctx, data.agent_id, perm=Perm.AGENTS_PUBLISH)

        kind = data.config.kind
        self._check_secret(data.auth_mode, data.jwt_secret)
        self._check_origins(kind, [str(origin) for origin in data.allowed_origins])
        if kind == "page":
            self._check_page(data.auth_mode, data.context_variables)

        sealed_jwt, jwt_version = self._seal(ctx.organization_id, data.jwt_secret)
        embed = AgentEmbed(
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            owner_user_id=ctx.user_id,
            name=data.name,
            kind=kind,
            public_key=secrets.token_urlsafe(_KEY_BYTES),
            auth_mode=data.auth_mode,
            jwt_secret_encrypted=sealed_jwt,
            secret_key_version=jwt_version,
            allowed_origins=[_origin_of(str(origin)) for origin in data.allowed_origins],
            config=data.config.model_dump(),
            context=data.context,
            context_variables=[variable.model_dump() for variable in data.context_variables],
            rate_limit_per_minute=data.rate_limit_per_minute,
        )
        created = await agent_embed_repo.create(self.db, embed=embed)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.embed_created",
            target_type="agent",
            target_id=str(agent.id),
            details={
                "embed_id": str(created.id),
                "kind": created.kind,
                "auth_mode": created.auth_mode,
            },
        )
        return self._read(created)

    async def update(self, ctx: AuthContext, embed_id: UUID, data: EmbedUpdate) -> EmbedRead:
        """Change a widget. The agent it points at is not changeable - see `EmbedUpdate`."""
        embed = await self._owned(ctx, embed_id)
        await self.agents.get(ctx, embed.agent_id, perm=Perm.AGENTS_PUBLISH)

        # `writable` rather than a dump: on an `*Update` a `None` is the "not
        # provided" sentinel, and `exclude_unset` keeps an explicitly sent one - so
        # `{"name": null}` used to reach a `NOT NULL` column and come back a 500
        # naming a constraint, for a request the API's own types say is legal. This
        # used to be a hand-kept list of five field names here; the column decides
        # now, so a field added to the schema is covered the day it is added (#637).
        changes = writable(data, over=AgentEmbed)

        mode = changes.get("auth_mode", embed.auth_mode)
        if "auth_mode" in changes or "jwt_secret" in changes:
            secret = changes.get("jwt_secret")
            # Keeping the stored secret is only allowed when the mode is not
            # changing: switching to `jwt` without providing one would leave the
            # widget verifying against whatever was there before.
            if secret is None and mode == "jwt" and embed.auth_mode != "jwt":
                raise BadRequestError(message="Switching to token auth needs a signing secret")
            self._check_secret(mode, secret, allow_missing=mode == embed.auth_mode)
            if secret is not None:
                changes["jwt_secret_encrypted"], changes["secret_key_version"] = self._seal(
                    ctx.organization_id, secret
                )
            elif mode == "public":
                changes["jwt_secret_encrypted"] = None
        changes.pop("jwt_secret", None)

        if "allowed_origins" in changes:
            self._check_origins(embed.kind, [str(origin) for origin in changes["allowed_origins"]])
            changes["allowed_origins"] = [
                _origin_of(str(origin)) for origin in changes["allowed_origins"]
            ]
        # An explicit null means "back to the defaults", not NULL. `writable` drops
        # it - which is the right default for a column that cannot hold one - so the
        # two fields with a default worth returning to ask what the caller *sent*
        # and put it back themselves. Dropping alone would answer a perfectly
        # sensible request by doing nothing at all.
        if "config" in changes or cleared(data, "config"):
            config = self._parse_config(changes.get("config"), kind=embed.kind)
            changes["config"] = config.model_dump()
        if "context_variables" in changes or cleared(data, "context_variables"):
            # "Declare none", for the same reason: a widget that declares nothing is
            # the ordinary state rather than an absence of information about it.
            changes["context_variables"] = [
                EmbedVariable.model_validate(variable).model_dump()
                for variable in (changes.get("context_variables") or [])
            ]

        # Re-checked against what the row will hold rather than against what this
        # request said, because either half can arrive alone: marking a stored
        # variable un-URL-safe is refused on a page that already exists, and so
        # is switching one to token auth.
        if embed.kind == "page":
            self._check_page(
                mode,
                [
                    EmbedVariable.model_validate(variable)
                    for variable in changes.get("context_variables", embed.context_variables or [])
                ],
            )

        updated = await agent_embed_repo.update(self.db, db_embed=embed, update_data=changes)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.embed_updated",
            target_type="agent",
            target_id=str(embed.agent_id),
            # Field names only. An origin list is fine to record; a signing
            # secret is not, and "which fields changed" answers the question an
            # audit trail is read for without carrying either.
            details={"embed_id": str(embed.id), "fields": sorted(changes)},
        )
        return self._read(updated)

    async def delete(self, ctx: AuthContext, embed_id: UUID) -> None:
        """Take a widget down. Every page carrying its key stops working."""
        embed = await self._owned(ctx, embed_id)
        await self.agents.get(ctx, embed.agent_id, perm=Perm.AGENTS_PUBLISH)

        await agent_embed_repo.delete(self.db, db_embed=embed)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.embed_deleted",
            target_type="agent",
            target_id=str(embed.agent_id),
            details={"embed_id": str(embed_id)},
        )

    async def set_page_logo(
        self,
        ctx: AuthContext,
        embed_id: UUID,
        *,
        file_data: bytes,
        content_type: str | None,
    ) -> EmbedRead:
        """Upload the image a hosted page shows, and point the page at it.

        The bytes go into this platform's own storage and the path is written to
        a column, never taken from a request body - see `AgentEmbed.logo_path`.
        Setting `config.logo` to `custom` in the same statement is what makes the
        upload finish the job: an operator who uploads a picture and finds the
        page still showing the agent's avatar has been given a form that lies.

        **The caller's filename is not taken**, unlike every other upload here: the
        stored name is minted from the validated type, because `/logo` serves this
        file from the origin the hosted page runs on and a name decides what a
        browser thinks it is.

        Raises:
            NotFoundError: If the embed is not this organization's.
            AuthorizationError: Without `agents:publish` on its agent.
            BadRequestError: For a kind with no page to brand, a file that is not
                an image this platform accepts, or one over the size limit.
        """
        if content_type not in IMAGE_MIME_TYPES:
            raise BadRequestError(message="Only JPEG, PNG, WebP, and GIF images are allowed")
        if len(file_data) > MAX_AVATAR_SIZE:
            raise BadRequestError(message="Logo image too large. Maximum 2MB.")

        embed = await self._owned(ctx, embed_id)
        if embed.kind != "page":
            raise BadRequestError(
                message="Only a hosted page shows a logo. A widget is styled by its own theme.",
                details={"kind": embed.kind},
            )
        await self.agents.get(ctx, embed.agent_id, perm=Perm.AGENTS_PUBLISH)

        storage = get_file_storage()
        if embed.logo_path:
            # A replaced picture is not worth failing an upload over, and the old
            # file is unreachable the moment the row stops pointing at it.
            with contextlib.suppress(Exception):
                await storage.delete(embed.logo_path)
        # The id alone: `save` keeps only the last component of what it is given,
        # so a `embeds/` prefix reads as a directory layout it would silently drop.
        #
        # And the name is built from the type checked above rather than from the one
        # sent: `save` keeps whatever extension it is handed, `/logo` is served from
        # the origin the hosted page is on, and `logo.html` there is a script rather
        # than a picture. The extension is the only part of a filename this route
        # has any use for, so nothing is lost by minting it.
        path = await storage.save(str(embed.id), f"logo{_LOGO_SUFFIX[content_type]}", file_data)

        config = PageConfig.model_validate(embed.config).model_copy(update={"logo": "custom"})
        updated = await agent_embed_repo.update(
            self.db,
            db_embed=embed,
            update_data={"logo_path": path, "config": config.model_dump()},
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.embed_updated",
            target_type="agent",
            target_id=str(embed.agent_id),
            details={"embed_id": str(embed.id), "fields": ["logo_path"]},
        )
        return self._read(updated)

    async def admit(self, public_key: str, *, origin: str | None, token: str | None) -> Admission:
        """Decide whether this visitor may talk to this embed.

        Returns the embed and the visitor's identity - the `sub` of their token,
        or None for an anonymous one. The identity is what a rate limit and a
        transcript are keyed on.

        Raises:
            EmbedDenied: For every refusal, without saying which.
        """
        embed = await agent_embed_repo.get_by_key(self.db, public_key)
        if embed is None or not embed.is_active:
            raise EmbedDenied("unknown or inactive embed")

        if not self._origin_allowed(embed, origin):
            # Logged, not answered: the person who needs this message is the
            # operator wondering why their embed is silent, not the caller.
            logger.info(
                "embed_origin_refused",
                extra={"embed_id": str(embed.id), "kind": embed.kind, "origin": origin},
            )
            raise EmbedDenied("origin not allowed")

        if embed.auth_mode == "public":
            return Admission(embed=embed, visitor=None)
        return Admission(embed=embed, visitor=self._verify_token(embed, token))

    async def find_page(self, public_key: str) -> AgentEmbed | None:
        """The embed a key names, if it is published as a page of our own.

        No origin check, and that is the security stance rather than an omission:
        the allow-list is a rule about *other people's* sites, and this page is
        ours. **A page in `public` mode is protected by the key's unguessability,
        the embed's rate bucket, its budget and its pause switch - nothing else.**
        Written down here, in `docs/channels.md`, and nowhere implied.
        """
        embed = await agent_embed_repo.get_by_key(self.db, public_key)
        if embed is None or not embed.is_active or embed.kind != "page":
            return None
        return embed

    async def page_config(self, embed: AgentEmbed) -> PublicPageConfig:
        """What the hosted page renders itself from."""
        config = PageConfig.model_validate(embed.config)
        agent = await agent_repo.get(self.db, embed.agent_id, organization_id=embed.organization_id)
        declared = [
            EmbedVariable.model_validate(variable) for variable in (embed.context_variables or [])
        ]
        return PublicPageConfig(
            title=config.title or (agent.name if agent else "Assistant"),
            welcome=config.welcome,
            accent=config.accent,
            logo_url=await self._logo_url(embed, config),
            agent_name=agent.name if agent else "Assistant",
            variables=[variable.name for variable in declared if variable.url_safe],
            allow_voice=config.allow_voice,
            allow_new_conversation=config.allow_new_conversation,
            allow_files=config.allow_files,
        )

    async def accept_upload(
        self, embed: AgentEmbed, *, data: bytes, filename: str, content_type: str | None
    ) -> ChatFile:
        """Store a file a stranger sent to a hosted page.

        The bytes go through exactly what a member's upload goes through -
        `FileUploadService.upload`, and so the MIME allowlist, the parser and the
        storage backend - with one narrowing in front of it: a cap of this
        surface's own. A member uploading a fifty-megabyte export is somebody the
        organization employs; the same allowance on a public link is a way to fill
        a disk from an address nobody knows.

        **The row belongs to the member who published the page.** A visitor has no
        account, `chat_files.user_id` is `NOT NULL`, and inventing an owner is not
        available - so the owner is the same person the run is attributed to,
        which is the answer already given for who a public turn runs as. A page
        whose publisher's account is gone therefore cannot take files, and says so
        rather than storing them against nobody.

        Raises:
            EmbedDenied: If this page does not accept files, or has no owner to
                attribute them to. One refusal for both, because a visitor is owed
                "not here" and nothing about the operator's configuration.
            BadRequestError: If the file is too large or of a type nothing here
                can read. That one *is* said: it is about what they sent.
        """
        config = PageConfig.model_validate(embed.config)
        if not config.allow_files or embed.owner_user_id is None:
            raise EmbedDenied("this embed does not accept files")
        if len(data) > settings.EMBED_MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise BadRequestError(
                message=(
                    f"That file is too large. The limit here is "
                    f"{settings.EMBED_MAX_UPLOAD_SIZE_MB}MB."
                ),
                details={"limit_mb": settings.EMBED_MAX_UPLOAD_SIZE_MB},
            )
        return await FileUploadService(self.db).upload(
            user_id=embed.owner_user_id,
            file_data=data,
            filename=filename,
            content_type=content_type,
        )

    async def page_logo_path(self, public_key: str) -> str | None:
        """The file a hosted page's logo is served from, or `None` if there is none.

        The image is the agent's avatar or the organization's, both already
        uploaded through the paths that exist for them - so publishing a page adds
        a way to *read* one image without a session and no way to write one.
        `None` covers every reason there is nothing to send: not a page, `logo`
        set to `none`, no avatar uploaded, or a stored path whose file has gone.
        """
        embed = await self.find_page(public_key)
        if embed is None:
            return None
        return await self._logo_file(embed, PageConfig.model_validate(embed.config))

    async def _logo_file(self, embed: AgentEmbed, config: PageConfig) -> str | None:
        """Where this page's logo actually is on disk, if it is anywhere.

        Takes the embed rather than a key so the two callers can share it without
        reading the row twice: the config route already holds it, and it has to ask
        the same question before advertising a URL - see `_logo_url`.
        """
        if config.logo == "none":
            return None

        stored: str | None = None
        if config.logo == "custom":
            stored = embed.logo_path
        elif config.logo == "agent":
            agent = await agent_repo.get(
                self.db, embed.agent_id, organization_id=embed.organization_id
            )
            stored = agent.avatar_url if agent else None
        else:
            organization = await organization_repo.get_by_id(self.db, embed.organization_id)
            stored = organization.avatar_url if organization else None
        if not stored:
            return None

        full = get_file_storage().get_full_path(stored)
        return str(full) if full is not None and full.exists() else None

    async def _logo_url(self, embed: AgentEmbed, config: PageConfig) -> str | None:
        """Where the page fetches its logo, or `None` when there is none to fetch.

        A path on this API rather than the stored storage key: the key is an
        internal address, and the route that serves it is what decides a hosted
        embed may hand out that one image without a session.

        **It answers `None` whenever the route behind it would answer 404**, which
        is why it resolves the file rather than reasoning about the setting. The
        previous version covered one of those cases - `custom` with nothing uploaded -
        and its comment gave the reason for all of them: a browser cannot tell a 404
        from a slow image, so it renders a broken glyph and says nothing. The default
        is `agent`, and an agent with no avatar is the common case, so every hosted
        page published without one showed that glyph in its header (#634).

        The extra work is a read the config route was making anyway, because
        `_logo_file` is handed the embed it already holds.
        """
        if await self._logo_file(embed, config) is None:
            return None
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        return f"{base}/api/v1/embed/{embed.public_key}/logo"

    async def find_public(self, public_key: str) -> AgentEmbed | None:
        """The widget a key names, with no origin check.

        Only for serving the script itself, which carries no secret and decides
        nothing: the origin is what admits a socket, and that is `admit`.

        A key of another kind names nothing here. The script it would be handed
        is a bubble that renders a launcher and calls `/config` - which a page
        and a socket integration have no answer for.
        """
        embed = await agent_embed_repo.get_by_key(self.db, public_key)
        if embed is None or embed.kind != "widget":
            return None
        return embed

    async def public_config(self, embed: AgentEmbed) -> PublicEmbedConfig:
        """What the widget renders itself from, before anybody authenticates.

        Raises:
            EmbedDenied: For any other kind. A page renders from `page_config`
                and a socket integration renders itself, so this is the widget's
                own shape - and validating another kind's config against it
                would answer a reachable request with a 500.
        """
        if embed.kind != "widget":
            raise EmbedDenied("not a widget")
        agent = await agent_repo.get(self.db, embed.agent_id, organization_id=embed.organization_id)
        config = WidgetConfig.model_validate(embed.config)
        return PublicEmbedConfig(
            title=config.title,
            subtitle=config.subtitle,
            greeting=config.greeting,
            placeholder=config.placeholder,
            accent=config.accent,
            position=config.position,
            launcher_label=config.launcher_label,
            requires_token=embed.auth_mode == "jwt",
            agent_name=agent.name if agent else "Assistant",
        )

    def _origin_allowed(self, embed: AgentEmbed, origin: str | None) -> bool:
        """Whether the site this visitor arrived from may use this embed.

        A `page` accepts exactly one origin - this deployment's own, because it
        is the only place that serves one - and the operator's allow-list has no
        say, in either direction: it cannot widen a page to a third-party site
        and it cannot be what a page is refused by.

        For the other two kinds an empty allow-list denies everything. That is
        the safe default and the only honest one: the key lives in public HTML or
        in somebody's client, so without an origin the key alone would be the
        whole authorization.

        A missing `Origin` is refused on every kind. A browser sends one; a client
        of your own sends nothing unless it sets one, and that is `4003`.
        """
        if origin is None:
            return False
        if embed.kind == "page":
            return _origin_of(origin) == _own_origin()
        allowed = [str(item).lower() for item in (embed.allowed_origins or [])]
        return _origin_of(origin) in allowed

    def _verify_token(self, embed: AgentEmbed, token: str | None) -> str:
        """Check a visitor token against the customer's own signing secret.

        HS256 with a shared secret, because the customer's backend is what mints
        these and a symmetric secret is the one thing every stack can sign with.
        We verify; we never issue. Their user database stays theirs.
        """
        if not token or not embed.jwt_secret_encrypted:
            raise EmbedDenied("token required")
        secret = unseal(
            embed.jwt_secret_encrypted,
            scope=VaultScope.organization(embed.organization_id),
            key_version=embed.secret_key_version,
        )
        try:
            claims = jwt.decode(token, secret, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise EmbedDenied("token rejected") from exc

        issued_at = claims.get("iat")
        if isinstance(issued_at, int | float):
            age = datetime.now(UTC).timestamp() - float(issued_at)
            if age > _MAX_TOKEN_AGE_SECONDS:
                raise EmbedDenied("token too old")

        subject = claims.get("sub")
        if not subject:
            # Without a subject there is nothing to rate-limit per visitor, and
            # one leaked token becomes the whole widget's budget.
            raise EmbedDenied("token has no subject")
        return str(subject)

    @staticmethod
    def _check_page(auth_mode: str, variables: list[EmbedVariable]) -> None:
        """Refuse to publish a page that cannot honestly serve what it promises.

        Both refusals are explicit and at publish time, never a silent fallback
        to a widget: somebody who asked for a link and got none would go looking
        for the link.

        **A page cannot use `jwt` mode.** The token would have to travel in the
        URL, which puts it in browser history, in `Referer` headers and in every
        chat client the link is pasted into - and the fragment trick that avoids
        some of that stops the link being "send it and it works", which is the
        whole point of a link. `jwt` on a widget or a socket is unaffected.

        **A required variable that is not URL-safe cannot be on a page.** Its URL
        is the only source of a supplied value there, so a variable the agent is
        promised and cannot be given would be a promise the surface structurally
        cannot keep.
        """
        if auth_mode != "public":
            raise BadRequestError(
                message=(
                    "A hosted page cannot use token auth: the token would travel in the "
                    "URL, and so into history, referrers and every chat client the link "
                    "is pasted into. Publish it as public, or use the widget."
                ),
                details={"auth_mode": auth_mode},
            )
        unreachable = sorted(
            variable.name for variable in variables if variable.required and not variable.url_safe
        )
        if unreachable:
            raise BadRequestError(
                message=(
                    "A hosted page can only be told a variable through its own URL, so a "
                    "required variable has to be marked URL-safe. Mark it, or make it "
                    "optional."
                ),
                details={"variables": unreachable},
            )

    @staticmethod
    def _check_origins(kind: str, origins: list[str]) -> None:
        """The allow-list has to match the surface, in both directions.

        A widget or a socket with an empty list can never open anything: the list
        is what admits them, so publishing one is asking for a surface that
        refuses every visitor. Refused here rather than left as a disabled button
        somewhere, because the reason belongs to the domain.

        A page with a list is the mirror image - dead configuration, or worse,
        somebody's belief that it is what protects the link. It is not; the key's
        unguessability is.
        """
        if kind == "page":
            if origins:
                raise BadRequestError(
                    message=(
                        "A hosted page is served from this deployment's own origin, so an "
                        "allowed-sites list has nothing to say about it. What protects the "
                        "link is its key, the rate limit and the budget."
                    ),
                    details={"kind": kind},
                )
            return
        if not origins:
            raise BadRequestError(
                message=(
                    "Name at least one site this may be opened from. An empty list allows "
                    "nothing, so this would be published and refuse every visitor."
                ),
                details={"kind": kind},
            )

    @staticmethod
    def _parse_config(value: object, *, kind: str) -> EmbedConfig:
        """Read a submitted config, and refuse one of a different kind.

        `None` means "back to the defaults" and takes the row's own kind, which
        is why this is not simply the schema's own validation: the union is
        tagged, and an untagged `{}` has to be resolved against the row rather
        than rejected as ambiguous.
        """
        submitted = value if isinstance(value, dict) else {}
        if submitted.get("kind", kind) != kind:
            raise BadRequestError(
                message=(
                    "An embed cannot change kind. Every tag, client and link already "
                    "names this key - publish a new one instead."
                ),
                details={"kind": kind, "submitted": str(submitted.get("kind"))},
            )
        return _CONFIG_ADAPTER.validate_python({**submitted, "kind": kind})

    def _check_secret(
        self, auth_mode: str, secret: str | None, *, allow_missing: bool = False
    ) -> None:
        if auth_mode == "jwt" and secret is None and not allow_missing:
            raise BadRequestError(message="Token auth needs a signing secret")
        if auth_mode == "public" and secret is not None:
            raise BadRequestError(
                message="A public widget authenticates nobody, so a signing secret would "
                "be stored and never read"
            )

    def _seal(self, organization_id: UUID, secret: str | None) -> tuple[str | None, int]:
        """The sealed JWT secret and the key version that sealed it, to store as a
        pair - so a master-key rotation can `rewrap` the row and it stays readable
        (#552). A public embed carries no secret and records the current version.
        """
        if secret is None:
            return None, current_key_version()
        sealed, version = seal_fields(
            {"jwt_secret": secret}, scope=VaultScope.organization(organization_id)
        )
        return sealed["jwt_secret"].ciphertext, version

    async def _owned(self, ctx: AuthContext, embed_id: UUID) -> AgentEmbed:
        embed = await agent_embed_repo.get(self.db, embed_id, organization_id=ctx.organization_id)
        if embed is None:
            raise NotFoundError(message="Embed not found", details={"embed_id": str(embed_id)})
        return embed

    def _read(self, embed: AgentEmbed) -> EmbedRead:
        config = _CONFIG_ADAPTER.validate_python(embed.config)
        return EmbedRead(
            id=embed.id,
            agent_id=embed.agent_id,
            name=embed.name,
            kind=config.kind,
            config=config,
            public_key=embed.public_key,
            auth_mode="jwt" if embed.auth_mode == "jwt" else "public",
            has_jwt_secret=embed.jwt_secret_encrypted is not None,
            allowed_origins=list(embed.allowed_origins or []),
            context=embed.context,
            context_variables=[
                EmbedVariable.model_validate(variable)
                for variable in (embed.context_variables or [])
            ],
            is_active=embed.is_active,
            rate_limit_per_minute=embed.rate_limit_per_minute,
            has_custom_logo=bool(embed.logo_path),
            snippet=self.snippet_for(embed),
            socket_url=self.socket_url_for(embed),
            page_url=self.page_url_for(embed),
            created_at=embed.created_at,
            updated_at=embed.updated_at,
        )

    @staticmethod
    def snippet_for(embed: AgentEmbed) -> str | None:
        """The lines a customer pastes, on a widget, and `None` on the other kinds.

        Assembled here rather than in the browser so the deployment's own URL is
        known in exactly one place - a snippet built client-side would carry
        whatever host the dashboard happened to be opened on.

        A widget that declares variables gets the line that supplies them, with
        its own keys in it and `…` where the values go. The declaration is
        otherwise something an integrator has to find in a form and translate
        into a global by hand, which is a step nobody documents and everybody
        gets wrong once.
        """
        if embed.kind != "widget":
            return None
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        tag = f'<script src="{base}/api/v1/embed/{embed.public_key}/widget.js" async></script>'
        declared = [str(variable.get("name", "")) for variable in (embed.context_variables or [])]
        if not any(declared):
            return tag
        keys = ", ".join(f"{name}: …" for name in declared if name)
        return f"<script>window.AgenticOSContext = {{ {keys} }};</script>\n{tag}"

    @staticmethod
    def page_url_for(embed: AgentEmbed) -> str | None:
        """The link, on a page, and `None` on the other kinds.

        Off the *frontend's* base URL rather than the API's, because the page is
        served by the frontend and the socket it opens is what reaches the API -
        which is also why the origin the browser reports is this host and why
        `_own_origin` reads the same setting.
        """
        if embed.kind != "page":
            return None
        return f"{settings.FRONTEND_URL.rstrip('/')}/e/{embed.public_key}"

    @staticmethod
    def socket_url_for(embed: AgentEmbed) -> str | None:
        """The socket a client connects to, and `None` on a page.

        Published on a `socket` embed because it is the whole integration, and on
        a `widget` because the widget speaks this protocol - so "write your own
        client instead" is a step rather than a rewrite. A page opens its socket
        itself and nobody integrates against it, so printing the URL there would
        be handing out an address with no use and one more thing to explain.

        Assembled here for the same reason `snippet_for` is - the deployment's
        own URL is known in one place - and derived from it rather than declared
        separately, so a deployment cannot have a widget on one host and a socket
        on another.

        No `?token=…`: in `jwt` mode the token is minted per visitor by the
        customer's own backend, and a real one printed in a panel would be a
        working credential on a screen somebody shares.
        """
        if embed.kind == "page":
            return None
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        scheme = "wss" if base.startswith("https://") else "ws"
        _, _, rest = base.partition("://")
        return f"{scheme}://{rest}/api/v1/embed/{embed.public_key}/ws"
