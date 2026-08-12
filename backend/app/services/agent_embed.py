"""Publishing an agent as a widget, and letting a stranger talk to it.

Two audiences in one service, and they are told different things.

*The owner* creates, edits and deletes widgets. Who may is `agents:publish` on
that agent, resolved through `resolve_access` - the same permission and the same
reasoning as an exposure: both answer "what does the outside world reach", and
somebody who may freeze a version may say where it runs.

*The visitor* has a key from a script tag and nothing else. Everything they are
allowed to do is decided here, from the row that key names:

1. Is the widget active, and is its agent still published?
2. Is the page they are on one of the allowed origins?
3. In `jwt` mode, does their token verify against the customer's own secret?

The order matters. Origin is checked before the token because a request from an
unlisted site should learn nothing about whether a token would have worked.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.config import settings
from app.core.exceptions import (
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext, Perm
from app.core.vault import VaultScope, seal, unseal
from app.db.models.agent_embed import DEFAULT_THEME, AgentEmbed
from app.repositories import agent_embed_repo, agent_repo, organization_repo
from app.schemas.agent_embed import (
    EmbedCreate,
    EmbedRead,
    EmbedTheme,
    EmbedUpdate,
    EmbedVariable,
    HostedConfig,
    PublicEmbedConfig,
    PublicHostedConfig,
)
from app.services.agent_registry import AgentRegistryService
from app.services.file_storage import get_file_storage

logger = logging.getLogger(__name__)

# Long enough that guessing is hopeless, short enough to paste into a tag.
_KEY_BYTES = 24

# How stale a visitor token may be. The customer's backend mints these per page
# load; anything older is a token that leaked out of a browser somewhere.
_MAX_TOKEN_AGE_SECONDS = 60 * 60 * 12


@dataclass(frozen=True)
class Admission:
    """What admitting a visitor established, for whoever serves them next.

    `hosted` is not a preference the caller passes in - it is decided here, from
    the origin the browser reported, and it narrows what the connection may do:
    on a page of our own the only source of a declared variable is the URL, so
    only variables marked URL-safe are accepted from it. A caller-supplied flag
    would be a visitor asking to be trusted more.
    """

    embed: AgentEmbed
    visitor: str | None
    hosted: bool


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
        """Publish an agent as a widget.

        Raises:
            NotFoundError: If the agent is not reachable by this caller.
            AuthorizationError: Without `agents:publish` on that agent.
            BadRequestError: For a `jwt` embed with no secret, or a `public` one
                carrying a secret nothing would ever read.
        """
        agent = await self.agents.get(ctx, data.agent_id, perm=Perm.AGENTS_PUBLISH)

        self._check_secret(data.auth_mode, data.jwt_secret)
        if data.hosted:
            self._check_hostable(data.auth_mode, data.context_variables)

        embed = AgentEmbed(
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            owner_user_id=ctx.user_id,
            name=data.name,
            public_key=secrets.token_urlsafe(_KEY_BYTES),
            auth_mode=data.auth_mode,
            jwt_secret_encrypted=self._seal(ctx.organization_id, data.jwt_secret),
            allowed_origins=[_origin_of(str(origin)) for origin in data.allowed_origins],
            theme=data.theme.model_dump(),
            hosted=data.hosted,
            hosted_config=data.hosted_config.model_dump(),
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
                "auth_mode": created.auth_mode,
                "hosted": created.hosted,
            },
        )
        return self._read(created)

    async def update(self, ctx: AuthContext, embed_id: UUID, data: EmbedUpdate) -> EmbedRead:
        """Change a widget. The agent it points at is not changeable - see `EmbedUpdate`."""
        embed = await self._owned(ctx, embed_id)
        await self.agents.get(ctx, embed.agent_id, perm=Perm.AGENTS_PUBLISH)

        changes = data.model_dump(exclude_unset=True)
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
                changes["jwt_secret_encrypted"] = self._seal(ctx.organization_id, secret)
            elif mode == "public":
                changes["jwt_secret_encrypted"] = None
        changes.pop("jwt_secret", None)

        if "allowed_origins" in changes and changes["allowed_origins"] is not None:
            changes["allowed_origins"] = [
                _origin_of(str(origin)) for origin in changes["allowed_origins"]
            ]
        if "theme" in changes and changes["theme"] is not None:
            changes["theme"] = EmbedTheme.model_validate(changes["theme"]).model_dump()
        if "hosted_config" in changes and changes["hosted_config"] is not None:
            changes["hosted_config"] = HostedConfig.model_validate(
                changes["hosted_config"]
            ).model_dump()
        if "context_variables" in changes:
            # An explicit null means "declare none", not NULL: the column cannot
            # hold one, and a widget that declares nothing is the ordinary state
            # rather than an absence of information about it.
            changes["context_variables"] = [
                EmbedVariable.model_validate(variable).model_dump()
                for variable in (changes["context_variables"] or [])
            ]

        # Re-checked against what the row will hold rather than against what this
        # request said, because either half can arrive alone: turning hosting on
        # is refused by a `required` variable already stored, and marking a stored
        # variable un-URL-safe is refused while hosting is already on.
        if changes.get("hosted", embed.hosted):
            self._check_hostable(
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

    async def admit(self, public_key: str, *, origin: str | None, token: str | None) -> Admission:
        """Decide whether this visitor may talk to this widget.

        Returns the widget, the visitor's identity - the `sub` of their token, or
        None for an anonymous one - and whether they arrived on a page we serve
        ourselves. The identity is what a rate limit and a transcript are keyed
        on.

        Raises:
            EmbedDenied: For every refusal, without saying which.
        """
        embed = await agent_embed_repo.get_by_key(self.db, public_key)
        if embed is None or not embed.is_active:
            raise EmbedDenied("unknown or inactive widget")

        hosted = bool(embed.hosted) and origin is not None and _origin_of(origin) == _own_origin()
        if not hosted and not self._origin_allowed(embed, origin):
            # Logged, not answered: the person who needs this message is the
            # operator wondering why their widget is silent, not the caller.
            logger.info(
                "embed_origin_refused",
                extra={"embed_id": str(embed.id), "origin": origin},
            )
            raise EmbedDenied("origin not allowed")

        if embed.auth_mode == "public":
            return Admission(embed=embed, visitor=None, hosted=hosted)
        return Admission(embed=embed, visitor=self._verify_token(embed, token), hosted=hosted)

    async def find_hosted(self, public_key: str) -> AgentEmbed | None:
        """The embed a key names, if it is published as a page of our own.

        No origin check, and that is the security stance rather than an omission:
        the allow-list is a rule about *other people's* sites, and this page is
        ours. **A hosted link in `public` mode is protected by the key's
        unguessability, the embed's rate bucket, its budget and its pause switch -
        nothing else.** Written down here, in `docs/channels.md`, and nowhere
        implied.
        """
        embed = await agent_embed_repo.get_by_key(self.db, public_key)
        if embed is None or not embed.is_active or not embed.hosted:
            return None
        return embed

    async def hosted_config(self, embed: AgentEmbed) -> PublicHostedConfig:
        """What the hosted page renders itself from."""
        config = HostedConfig.model_validate(embed.hosted_config or {})
        agent = await agent_repo.get(self.db, embed.agent_id, organization_id=embed.organization_id)
        declared = [
            EmbedVariable.model_validate(variable) for variable in (embed.context_variables or [])
        ]
        return PublicHostedConfig(
            title=config.title or (agent.name if agent else "Assistant"),
            welcome=config.welcome,
            accent=config.accent,
            logo_url=self._logo_url(embed, config),
            agent_name=agent.name if agent else "Assistant",
            variables=[variable.name for variable in declared if variable.url_safe],
        )

    async def hosted_logo_path(self, public_key: str) -> str | None:
        """The file a hosted page's logo is served from, or `None` if there is none.

        The image is the agent's avatar or the organization's, both already
        uploaded through the paths that exist for them - so hosting a page adds a
        way to *read* one image without a session and no way to write one. `None`
        covers every reason there is nothing to send: hosting off, `logo` set to
        `none`, no avatar uploaded, or a stored path whose file has gone.
        """
        embed = await self.find_hosted(public_key)
        if embed is None:
            return None
        config = HostedConfig.model_validate(embed.hosted_config or {})
        if config.logo == "none":
            return None

        stored: str | None = None
        if config.logo == "agent":
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

    @staticmethod
    def _logo_url(embed: AgentEmbed, config: HostedConfig) -> str | None:
        """Where the page fetches its logo, or `None` when it shows none.

        A path on this API rather than the stored storage key: the key is an
        internal address, and the route that serves it is what decides a hosted
        embed may hand out that one image without a session.
        """
        if config.logo == "none":
            return None
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        return f"{base}/api/v1/embed/{embed.public_key}/logo"

    async def find_public(self, public_key: str) -> AgentEmbed | None:
        """The widget a key names, with no origin check.

        Only for serving the script itself, which carries no secret and decides
        nothing: the origin is what admits a socket, and that is `admit`.
        """
        return await agent_embed_repo.get_by_key(self.db, public_key)

    async def public_config(self, embed: AgentEmbed) -> PublicEmbedConfig:
        """What the widget renders itself from, before anybody authenticates."""
        agent = await agent_repo.get(self.db, embed.agent_id, organization_id=embed.organization_id)
        theme = {**DEFAULT_THEME, **(embed.theme or {})}
        return PublicEmbedConfig(
            title=str(theme.get("title", "")),
            subtitle=str(theme.get("subtitle", "")),
            greeting=str(theme.get("greeting", "")),
            placeholder=str(theme.get("placeholder", "")),
            accent=str(theme.get("accent", "#4f46e5")),
            position="left" if theme.get("position") == "left" else "right",
            launcher_label=str(theme.get("launcher_label", "Chat")),
            requires_token=embed.auth_mode == "jwt",
            agent_name=agent.name if agent else "Assistant",
        )

    def _origin_allowed(self, embed: AgentEmbed, origin: str | None) -> bool:
        """Whether the page the widget is on may use it.

        An empty allow-list denies everything. That is the safe default and the
        only honest one: a widget key lives in public HTML, so without an origin
        the key alone is the whole authorization.
        """
        allowed = [str(item).lower() for item in (embed.allowed_origins or [])]
        if not allowed or origin is None:
            return False
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
    def _check_hostable(auth_mode: str, variables: list[EmbedVariable]) -> None:
        """Refuse to host what a hosted page cannot honestly serve.

        Both refusals are explicit and at enable time, never a silent fallback to
        an unhosted embed: somebody who asked for a link and got none would go
        looking for the link.

        **`jwt` mode cannot be hosted.** The token would have to travel in the
        URL, which puts it in browser history, in `Referer` headers and in every
        chat client the link is pasted into - and the fragment trick that avoids
        some of that stops the link being "send it and it works", which is the
        whole point of a link. `jwt` on the widget is unaffected.

        **A required variable that is not URL-safe cannot be hosted.** On a page
        of our own the URL is the only source of a supplied value, so a variable
        the agent is promised and cannot be given would be a promise the surface
        structurally cannot keep.
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

    def _seal(self, organization_id: UUID, secret: str | None) -> str | None:
        if secret is None:
            return None
        return seal(secret, scope=VaultScope.organization(organization_id)).ciphertext

    async def _owned(self, ctx: AuthContext, embed_id: UUID) -> AgentEmbed:
        embed = await agent_embed_repo.get(self.db, embed_id, organization_id=ctx.organization_id)
        if embed is None:
            raise NotFoundError(message="Embed not found", details={"embed_id": str(embed_id)})
        return embed

    def _read(self, embed: AgentEmbed) -> EmbedRead:
        theme = {**DEFAULT_THEME, **(embed.theme or {})}
        return EmbedRead(
            id=embed.id,
            agent_id=embed.agent_id,
            name=embed.name,
            public_key=embed.public_key,
            auth_mode="jwt" if embed.auth_mode == "jwt" else "public",
            has_jwt_secret=embed.jwt_secret_encrypted is not None,
            allowed_origins=list(embed.allowed_origins or []),
            theme=EmbedTheme.model_validate(theme),
            hosted=embed.hosted,
            hosted_config=HostedConfig.model_validate(embed.hosted_config or {}),
            context=embed.context,
            context_variables=[
                EmbedVariable.model_validate(variable)
                for variable in (embed.context_variables or [])
            ],
            is_active=embed.is_active,
            rate_limit_per_minute=embed.rate_limit_per_minute,
            snippet=self.snippet_for(embed),
            socket_url=self.socket_url_for(embed),
            hosted_url=self.hosted_url_for(embed),
            created_at=embed.created_at,
            updated_at=embed.updated_at,
        )

    @staticmethod
    def snippet_for(embed: AgentEmbed) -> str:
        """The lines a customer pastes.

        Assembled here rather than in the browser so the deployment's own URL is
        known in exactly one place - a snippet built client-side would carry
        whatever host the dashboard happened to be opened on.

        A widget that declares variables gets the line that supplies them, with
        its own keys in it and `…` where the values go. The declaration is
        otherwise something an integrator has to find in a form and translate
        into a global by hand, which is a step nobody documents and everybody
        gets wrong once.
        """
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        tag = f'<script src="{base}/api/v1/embed/{embed.public_key}/widget.js" async></script>'
        declared = [str(variable.get("name", "")) for variable in (embed.context_variables or [])]
        if not any(declared):
            return tag
        keys = ", ".join(f"{name}: …" for name in declared if name)
        return f"<script>window.AgenticOSContext = {{ {keys} }};</script>\n{tag}"

    @staticmethod
    def hosted_url_for(embed: AgentEmbed) -> str | None:
        """The link, when hosting is on, and `None` when it is off.

        Off the *frontend's* base URL rather than the API's, because the page is
        served by the frontend and the socket it opens is what reaches the API -
        which is also why the origin the browser reports is this host and why
        `_own_origin` reads the same setting.
        """
        if not embed.hosted:
            return None
        return f"{settings.FRONTEND_URL.rstrip('/')}/e/{embed.public_key}"

    @staticmethod
    def socket_url_for(embed: AgentEmbed) -> str:
        """The socket a client of one's own connects to.

        The second integration this row offers, and the honest one for anybody
        building their own interface: a mobile app, a kiosk, a component in
        somebody's design system. The protocol behind it is the one the widget
        speaks, documented frame by frame in `docs/channels.md`.

        Assembled here for the same reason `snippet_for` is - the deployment's
        own URL is known in one place - and derived from it rather than declared
        separately, so a deployment cannot have a widget on one host and a socket
        on another.

        No `?token=…`: in `jwt` mode the token is minted per visitor by the
        customer's own backend, and a real one printed in a panel would be a
        working credential on a screen somebody shares.
        """
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        scheme = "wss" if base.startswith("https://") else "ws"
        _, _, rest = base.partition("://")
        return f"{scheme}://{rest}/api/v1/embed/{embed.public_key}/ws"
