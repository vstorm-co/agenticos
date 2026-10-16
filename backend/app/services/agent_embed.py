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
    RateLimitError,
)
from app.core.field_errors import refused_field
from app.core.logging import one_line
from app.core.permissions import AuthContext, Perm
from app.core.vault import VaultScope, current_key_version, seal_fields, unseal
from app.db.models.agent import Agent, AgentStatus
from app.db.models.agent_embed import AgentEmbed
from app.db.models.chat_file import ChatFile
from app.db.updates import cleared, writable
from app.repositories import agent_embed_repo, agent_repo, organization_repo
from app.schemas.agent_embed import (
    DictationMode,
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
from app.services import rate_limit
from app.services.agent_registry import AgentRegistryService
from app.services.file_storage import IMAGE_MIME_TYPES, MAX_AVATAR_SIZE, get_file_storage
from app.services.file_upload import FileUploadService
from app.services.ml import MLService
from app.services.realtime_models import Transport
from app.services.speech_to_text import RecordingFormat
from app.services.transcription_usage import TranscriptionCall
from app.services.voice import VoiceSettingsService

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


@dataclass(frozen=True)
class PublicDictation:
    """What a public config says about the microphone, after the readiness check."""

    mode: DictationMode
    max_seconds: int
    format: RecordingFormat


_DICTATION_DEFAULT_SECONDS = 300
"""What a public config says the limit is when the organization was not read.

Only sent with `off` or `browser`, where nothing is recorded by the page and the
figure is never used - so reading the organization on every page load to fill it
in would be a query for nothing.
"""

_SERVER_DICTATION_UNAVAILABLE = (
    "Server dictation needs a speech-to-text provider and a key for it, set for this "
    "agent or for the organization. Set one up on the Voice card, or choose Browser or Off."
)


_VOICE_UNAVAILABLE = (
    "Voice calls need the organization's voice switch on and a voice set up on this "
    "agent's Voice card."
)


class EmbedDenied(Exception):
    """The widget refuses this visitor, and the reason is not theirs to know.

    One exception for every refusal - inactive, wrong origin, bad token - so a
    caller cannot accidentally tell a stranger which of the three it was, and
    an origin probe learns nothing about tokens.
    """


def _runs(agent: Agent) -> bool:
    """Whether the agent behind an embed has a published version anybody runs."""
    return agent.current_version_id is not None and agent.status != AgentStatus.ARCHIVED.value


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
        await self._check_dictation(agent, before=None, after=data.config)
        await self._check_voice_conversation(agent, before=None, after=data.config)

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
        agent = await self.agents.get(ctx, embed.agent_id, perm=Perm.AGENTS_PUBLISH)

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
            stored = _CONFIG_ADAPTER.validate_python(embed.config)
            await self._check_dictation(agent, before=stored, after=config)
            await self._check_voice_conversation(agent, before=stored, after=config)
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
        return self._admit(embed, origin=origin, token=token)

    def _admit(self, embed: AgentEmbed, *, origin: str | None, token: str | None) -> Admission:
        """Steps 2 and 3 of admission, on a row already found active."""
        if not self._origin_allowed(embed, origin):
            # Logged, not answered: the person who needs this message is the
            # operator wondering why their embed is silent, not the caller.
            logger.info(
                "embed_origin_refused",
                extra={"embed_id": str(embed.id), "kind": embed.kind, "origin": one_line(origin)},
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
        dictation = await self._public_dictation(embed, agent, config.dictation)
        voice_conversation, voice_transport = await self._public_voice(
            embed, agent, enabled=config.voice_conversation
        )
        return PublicPageConfig(
            title=config.title or (agent.name if agent else "Assistant"),
            welcome=config.welcome,
            accent=config.accent,
            logo_url=await self._logo_url(embed, config),
            agent_name=agent.name if agent else "Assistant",
            variables=[variable.name for variable in declared if variable.url_safe],
            dictation=dictation.mode,
            dictation_max_seconds=dictation.max_seconds,
            dictation_format=dictation.format,
            voice_conversation=voice_conversation,
            voice_transport=voice_transport,
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
        """The storage path a hosted page's logo is served from, or `None`.

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
        """The storage path of this page's logo, if the backend still holds one.

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

        return stored if await get_file_storage().exists(stored) else None

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

    async def find_voice_widget(self, public_key: str) -> AgentEmbed | None:
        """The widget a key names, if its call script is to be served (#54).

        Active and with its stored voice switch on; no origin check, for the
        reason `find_public` gives. Whether a call would actually start - the
        organization's switch, the agent's voice - is the public config's to say
        and the socket's to refuse: the script decides nothing.
        """
        embed = await self.find_public(public_key)
        if embed is None or not embed.is_active:
            return None
        if not WidgetConfig.model_validate(embed.config).voice_conversation:
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
        dictation = await self._public_dictation(embed, agent, config.dictation)
        voice_conversation, voice_transport = await self._public_voice(
            embed, agent, enabled=config.voice_conversation
        )
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
            dictation=dictation.mode,
            dictation_max_seconds=dictation.max_seconds,
            dictation_format=dictation.format,
            voice_conversation=voice_conversation,
            voice_transport=voice_transport,
        )

    async def admit_dictation(
        self,
        public_key: str,
        *,
        origin: str | None,
        token: str | None,
        visitor_key: str | None,
    ) -> Admission:
        """Admit a visitor sending a recording, by the rules of the surface they are on.

        The kinds take different paths, and neither borrows the other's:

        - **widget** - `admit`, exactly as the socket: the origin against the
          allow-list, and in `jwt` mode the customer's signed token.
        - **page** - no origin check, as for everything else a page does (see
          `find_page`), and a well-formed continuity key, as an upload needs.
          The page's own `X-Visitor-Key` header is what makes a third-party
          site's browser unable to send one at all: a custom header is a CORS
          preflight, and only this deployment's own origin passes it.
        - **socket** - nothing to dictate into, so the same refusal as an
          unknown key.

        `visitor_key` is the continuity key already checked for shape
        (`embed_session.continuity_key`), or `None`.

        Raises:
            EmbedDenied: For every refusal about the embed, without saying which.
            BadRequestError: A page reached without a usable visitor key - which
                is about what the caller sent, not about the page.
        """
        embed = await agent_embed_repo.get_by_key(self.db, public_key)
        if embed is None or not embed.is_active:
            raise EmbedDenied("unknown or inactive embed")
        if embed.kind == "widget":
            return self._admit(embed, origin=origin, token=token)
        if embed.kind == "page":
            if visitor_key is None:
                raise BadRequestError(
                    message="A visitor key is required", details={"header": "X-Visitor-Key"}
                )
            return Admission(embed=embed, visitor=None)
        raise EmbedDenied("a socket has no microphone")

    async def admit_voice(
        self,
        public_key: str,
        *,
        origin: str | None,
        token: str | None,
        visitor_key: str | None,
    ) -> Admission:
        """Admit a visitor opening a voice call, by the rules of the embed socket (#54).

        - **widget** - `admit`'s rules: the origin against the allow-list, and in
          `jwt` mode the customer's signed token.
        - **page** - this deployment's own origin, as the page's chat socket is
          checked, plus a well-formed continuity key: the call lands in the thread
          that key holds. A socket handshake carries no custom header, so the
          origin is what keeps a third-party site from opening one; the dictation
          route's preflight argument does not apply here.
        - **socket** - nothing to call from, so the same refusal as an unknown key.

        Then the stored config's `voice_conversation` has to be on. Whether a call
        would actually start - the organization's switch, the agent's voice, the
        month's minutes - is the call's own refusal, sent on the socket.

        Raises:
            EmbedDenied: For every refusal about the embed, without saying which.
            BadRequestError: A page reached without a usable visitor key.
        """
        embed = await agent_embed_repo.get_by_key(self.db, public_key)
        if embed is None or not embed.is_active or embed.kind == "socket":
            raise EmbedDenied("unknown, inactive or a socket")
        admission = self._admit(embed, origin=origin, token=token)
        if embed.kind == "page" and visitor_key is None:
            raise BadRequestError(message="A visitor key is required", details={"query": "visitor"})
        config = _CONFIG_ADAPTER.validate_python(embed.config)
        if not isinstance(config, PageConfig | WidgetConfig) or not config.voice_conversation:
            raise EmbedDenied("voice calls are off")
        return admission

    async def dictate(
        self,
        admission: Admission,
        *,
        content: bytes,
        mime_type: str,
        reported_seconds: float | None,
    ) -> str:
        """Transcribe a visitor's recording on the organization's own engine (#1797).

        The gate is **this embed's** `dictation` setting, and nothing else: the
        organization's `/chat` engine is about the console's composer, and an
        organization that keeps its members on the browser's recogniser may still
        want a page that does not hand a visitor's voice to a browser vendor. So
        the organization is passed to `MLService.transcribe_dictation` only when
        the embed says `server`; the provider, model, language and the longest
        dictation are resolved there, the same as for the composer.

        The agent has to be published and not archived: there is nothing for the
        text to be sent to otherwise, and a paid transcription for a message the
        socket would refuse is money spent on nothing.

        **Raw PCM unless the deployment accepts compressed audio**, whose
        length is its size, so the link's rate limit times the longest
        dictation bounds what a stranger can spend exactly. Where compressed
        audio is accepted, **a recording whose length cannot be read is
        refused** (`unsupported_type`), where the console accepts one under its
        byte cap: the length is what the provider bills, the visitor is a
        stranger, and bytes alone let low-bitrate Opus carry hours.

        **The usage row has no requester**, a `jwt` visitor included - neither is
        a member, and attributing a stranger's call to whoever published the page
        would put it on a person's record who never made it. It carries the
        surface (`hosted` or `widget`) and the agent instead.

        Raises:
            EmbedDenied: Not `server`, or no published agent behind it.
            RateLimitError: A `jwt` visitor past their own allowance.
            ConfigurationError, BadRequestError, ExternalServiceError: As
                `MLService.transcribe_dictation`, with the same `reason`s.
        """
        embed = admission.embed
        config = _CONFIG_ADAPTER.validate_python(embed.config)
        if not isinstance(config, PageConfig | WidgetConfig) or config.dictation != "server":
            raise EmbedDenied("this embed does not take recordings")
        agent = await agent_repo.get(self.db, embed.agent_id, organization_id=embed.organization_id)
        if agent is None or not _runs(agent):
            raise EmbedDenied("nothing published to dictate to")
        if admission.visitor is not None:
            decision = await rate_limit.embed_dictation_visitor_allowed(
                public_key=embed.public_key, visitor=admission.visitor
            )
            if not decision.allowed:
                raise RateLimitError(
                    message="Too many dictations in the last minute. Wait and try again.",
                    details={"retry_after_seconds": decision.retry_after_seconds},
                )
        organization = await organization_repo.get_by_id(self.db, embed.organization_id)
        return await MLService(self.db).transcribe_dictation(
            TranscriptionCall(
                organization_id=embed.organization_id,
                surface="hosted" if embed.kind == "page" else "widget",
                provider=None,
                model=None,
                agent_id=agent.id,
            ),
            organization=organization,
            agent=agent,
            content=content,
            mime_type=mime_type,
            reported_seconds=reported_seconds,
            accept_unmeasured=False,
        )

    async def _public_dictation(
        self, embed: AgentEmbed, agent: Agent | None, mode: DictationMode
    ) -> PublicDictation:
        """What a public config tells the page about its microphone.

        Only `server` is checked, and it is sent as `off` whenever a recording
        would be refused as `not_configured` - no published agent, no pair, or
        no credential. A visitor is owed a page without a microphone rather than
        one that fails, and nothing about the operator's setup; the operator
        sees the same answer as a disabled choice in the embed form.
        """
        if mode != "server":
            return PublicDictation(mode=mode, max_seconds=_DICTATION_DEFAULT_SECONDS, format="wav")
        organization = await organization_repo.get_by_id(self.db, embed.organization_id)
        if organization is None or agent is None or not _runs(agent):
            return PublicDictation(mode="off", max_seconds=_DICTATION_DEFAULT_SECONDS, format="wav")
        server = await MLService(self.db).server_dictation(agent)
        return PublicDictation(
            mode="server" if server.available else "off",
            max_seconds=organization.dictation_max_seconds,
            format=server.format,
        )

    async def _check_dictation(
        self, agent: Agent, *, before: EmbedConfig | None, after: EmbedConfig
    ) -> None:
        """Refuse switching `server` on while no provider would answer it.

        Only the switch is checked - a config that *becomes* `server` - and not
        every save of one that already is: a credential deleted since would
        otherwise make a page impossible to rename, and the public config
        already sends such a page as `off`. The same readiness the form reads
        (`server_available`), so a choice the form offers is one this accepts.
        """
        if not isinstance(after, PageConfig | WidgetConfig) or after.dictation != "server":
            return
        if isinstance(before, PageConfig | WidgetConfig) and before.dictation == "server":
            return
        if not (await MLService(self.db).server_dictation(agent)).available:
            raise refused_field("config.dictation", _SERVER_DICTATION_UNAVAILABLE)

    async def _public_voice(
        self, embed: AgentEmbed, agent: Agent | None, *, enabled: bool
    ) -> tuple[bool, Transport | None]:
        """Whether a public config offers a call, and over which transport (#54).

        Offered only while a call would start for a visitor - the embed's switch,
        a published agent, and a ready voice on the embed surface - and otherwise
        sent as off with no transport: a visitor gets no call button rather than
        one that fails, and nothing about the operator's setup.
        """
        if not enabled or agent is None or not _runs(agent):
            return False, None
        readiness = await VoiceSettingsService(self.db).readiness(
            organization_id=embed.organization_id, agent=agent, surface="embed"
        )
        if not readiness.available or readiness.transport is None:
            return False, None
        return True, readiness.transport

    async def _check_voice_conversation(
        self, agent: Agent, *, before: EmbedConfig | None, after: EmbedConfig
    ) -> None:
        """Refuse switching calls on while no call could start - the dictation rule.

        Only the switch is checked, not every save of an embed already on: a key
        deleted since must not make the page impossible to rename, and the public
        config already sends such an embed as off. A month whose minutes are used
        up is not refused - the setup is complete, and calls start again when the
        month turns.
        """
        if not isinstance(after, PageConfig | WidgetConfig) or not after.voice_conversation:
            return
        if isinstance(before, PageConfig | WidgetConfig) and before.voice_conversation:
            return
        readiness = await VoiceSettingsService(self.db).readiness(
            organization_id=agent.organization_id, agent=agent, surface="embed"
        )
        if readiness.unavailable not in (None, "minutes_exhausted"):
            raise refused_field("config.voice_conversation", _VOICE_UNAVAILABLE)

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
        except (jwt.PyJWTError, TypeError) as exc:
            # `exp`/`iat` as null, [] or {} makes PyJWT's own validation run
            # `int()` on it - a raw `TypeError`, not a `PyJWTError` - so without
            # this a malformed-but-signed token escaped as a 500 rather than a
            # clean refusal (#1107).
            raise EmbedDenied("token rejected") from exc

        issued_at = claims.get("iat")
        if not isinstance(issued_at, int | float) or (
            datetime.now(UTC).timestamp() - float(issued_at) > _MAX_TOKEN_AGE_SECONDS
        ):
            # A within-window `iat` is required, not checked opportunistically:
            # PyJWT enforces neither `iat` nor a 12h ceiling, so a token with no
            # `iat` - or a stale one hidden behind a far-future `exp` - would be
            # fresh until it expired, if ever, and one scraped from a browser tab
            # would answer on the organization's bill that whole time. `exp` is
            # not an alternative: it lets a customer *shorten* the window (PyJWT
            # rejects an expired token at decode), never extend it past the 12h
            # platform ceiling (#23).
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
