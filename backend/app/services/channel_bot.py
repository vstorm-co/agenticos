"""ChannelBotService - business logic for bot management (PostgreSQL async).

A bot token is sealed with :mod:`app.core.vault`, bound to the organization the
bot belongs to. It used to be Fernet-encrypted with one deployment-wide key,
which meant a ciphertext copied from one tenant's row into another's decrypted
happily - the token itself is what talks to Slack or Telegram as that
organization, so that was a tenant boundary with nothing behind it.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import spawn_after_commit
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.field_errors import refused_field
from app.core.vault import SealedSecret, VaultScope, seal, unseal
from app.db.models.channel_bot import ChannelBot
from app.db.updates import writable
from app.repositories import agent_exposure_repo, channel_bot_repo, channel_session_repo
from app.schemas.channel_bot import (
    BotAgent,
    ChannelBotCreate,
    ChannelBotRead,
    ChannelBotUpdate,
)
from app.services.channels import (
    SECRET_MINTED_BY_US,
    connection_state,
    get_adapter,
    inbound_webhook_url,
)
from app.services.channels.supervisor import close_inbound_stream, open_inbound_stream

logger = logging.getLogger(__name__)


def seal_bot_token(token: str, *, organization_id: UUID) -> SealedSecret:
    """Seal a bot token for the organization that owns the bot."""
    return seal(token, scope=VaultScope.organization(organization_id))


def unseal_bot_token(bot: ChannelBot) -> str:
    """Recover a bot's token.

    A module-level function rather than a method because the inbound paths -
    the webhook router and the polling loop at startup - have the row and no
    service, and the row is what carries the organization the envelope is bound
    to.
    """
    return unseal(
        bot.token_encrypted,
        scope=VaultScope.organization(bot.organization_id),
        key_version=bot.secret_key_version,
    )


def unseal_webhook_secret(bot: ChannelBot) -> str | None:
    """The secret an inbound webhook is authenticated against, or None if unset.

    A module-level function for the same reason :func:`unseal_bot_token` is: the
    two webhook routes hold the row and no service, and the row carries the
    organization the envelope is bound to.

    None is the caller's problem to name, and both callers name it the same way -
    a webhook that cannot be authenticated is refused rather than trusted.
    """
    if bot.webhook_secret_encrypted is None:
        return None
    return unseal(
        bot.webhook_secret_encrypted,
        scope=VaultScope.organization(bot.organization_id),
        key_version=bot.secret_key_version,
    )


def unseal_slack_signing_secret(bot: ChannelBot) -> str | None:
    """The secret inbound Slack events are verified with, or None if unset.

    None is the caller's problem to name: a webhook that cannot be verified
    must refuse, and the refusal should say which bot to configure.
    """
    if bot.slack_signing_secret_encrypted is None:
        return None
    return unseal(
        bot.slack_signing_secret_encrypted,
        scope=VaultScope.organization(bot.organization_id),
        key_version=bot.secret_key_version,
    )


def unseal_slack_app_token(bot: ChannelBot) -> str | None:
    """The app-level token Socket Mode connects with, or None if unset."""
    if bot.slack_app_token_encrypted is None:
        return None
    return unseal(
        bot.slack_app_token_encrypted,
        scope=VaultScope.organization(bot.organization_id),
        key_version=bot.secret_key_version,
    )


class ChannelBotService:
    """Service for channel bot management.

    `organization_id` is the tenant every management call is scoped to. It is
    `None` only on the inbound path (webhook / poller), where no member is
    making the request and the bot row itself carries the organization - those
    callers may use :meth:`find_active` and :meth:`get_decrypted_token` and
    nothing else.
    """

    def __init__(self, db: AsyncSession, organization_id: UUID | None = None) -> None:
        self.db = db
        self.organization_id = organization_id

    @property
    def _org_id(self) -> UUID:
        """The tenant for management calls, or a loud failure if unscoped."""
        if self.organization_id is None:
            raise RuntimeError(
                "ChannelBotService was built without an organization - this instance may only "
                "serve inbound dispatch. Use the org-scoped dependency for management calls."
            )
        return self.organization_id

    def _reopen_stream(self, bot: ChannelBot) -> None:
        """Make this bot's inbound connection match the row it now has.

        One method for every write, because "does this change the stream" is a
        question with a long and growing answer - the token, the server address,
        the delivery mode and whether the bot is switched on at all - and a rule
        listing them is a rule the next column forgets. Reopening a stream
        nobody changed costs one reconnect.

        Deferred with `spawn_after_commit`, never spawned: a connection opened
        against a row the transaction then rolls back is one talking to
        somebody's Mattermost about a bot that does not exist. Every value the
        deferred coroutine needs is read out here, while the row is still
        attached to this session - it must hold primitives and nothing else.

        A bot in webhook mode has no stream to open, and neither has a paused
        one; both are *closed*, which is what makes switching a bot to webhooks
        or pausing it take effect now rather than at the next restart.
        """
        bot_id, platform = str(bot.id), bot.platform
        if bot.webhook_mode or not bot.is_active:
            spawn_after_commit(
                self.db,
                close_inbound_stream(bot_id=bot_id, platform=platform),
                name=f"close_channel_stream:{bot_id}",
            )
            return
        spawn_after_commit(
            self.db,
            open_inbound_stream(
                bot_id=bot_id,
                platform=platform,
                token=unseal_bot_token(bot),
                api_base_url=bot.api_base_url,
                app_token=unseal_slack_app_token(bot),
            ),
            name=f"open_channel_stream:{bot_id}",
        )

    async def create(self, data: ChannelBotCreate) -> ChannelBot:
        """Create a new channel bot with its credentials sealed, and open its stream.

        A polling bot is reached over a connection this process holds, and only
        the lifespan ever opened one - so registering a bot wrote a row and
        produced silence until somebody restarted the API.

        Raises:
            BadRequestError: If Slack-app credentials arrive on a bot that is
                not a Slack bot - accepting them would store secrets nothing
                will ever read.
        """
        self._check_slack_fields(data.platform, data.slack_signing_secret, data.slack_app_token)
        sealed = seal_bot_token(data.token, organization_id=self._org_id)
        webhook_secret = self._initial_webhook_secret(data)
        bot = await channel_bot_repo.create(
            self.db,
            organization_id=self._org_id,
            platform=data.platform,
            name=data.name,
            token_encrypted=sealed.ciphertext,
            secret_key_version=sealed.key_version,
            webhook_mode=data.webhook_mode,
            webhook_url=data.webhook_url,
            api_base_url=data.api_base_url,
            webhook_secret_encrypted=self._seal_at(webhook_secret, key_version=sealed.key_version),
            access_policy=data.access_policy.model_dump(),
            slack_signing_secret_encrypted=self._seal_at(
                data.slack_signing_secret, key_version=sealed.key_version
            ),
            slack_app_token_encrypted=self._seal_at(
                data.slack_app_token, key_version=sealed.key_version
            ),
        )
        self._reopen_stream(bot)
        return bot

    @staticmethod
    def _initial_webhook_secret(data: ChannelBotCreate) -> str | None:
        """The secret this bot's inbound webhook will be authenticated against.

        Supplied wins, because the platform that generated the token is the one
        that has to recognise it: a Mattermost outgoing webhook is created in its
        own System Console and *it* mints the token. Minting one here regardless
        is what made the Mattermost webhook path unusable - the bot looked
        configured and compared Mattermost's token against a local random string
        nobody could overwrite.

        Otherwise one is minted only where the deployment is the side that hands
        it over, which is Telegram's `setWebhook`. A bot in webhook mode on a
        platform we cannot tell gets none, and refuses inbound calls until an
        operator pastes the platform's own token - which is the honest state, not
        a broken one.
        """
        if data.webhook_secret is not None:
            return data.webhook_secret
        if data.webhook_mode and data.platform in SECRET_MINTED_BY_US:
            return secrets.token_urlsafe(32)
        return None

    def _seal_at(self, value: str | None, *, key_version: int) -> str | None:
        """Seal an optional credential at the row's key version.

        All of a bot's ciphertexts share one `secret_key_version` column, so a
        value sealed later must use the version the row already carries - or
        rotating the master key would leave a row whose column is honest about
        only some of its envelopes.
        """
        if value is None:
            return None
        return seal(
            value, scope=VaultScope.organization(self._org_id), key_version=key_version
        ).ciphertext

    @staticmethod
    def _check_server_url(platform: str, api_base_url: str | None) -> None:
        """Which platform may carry a server URL, and which may not lose one.

        The create path states this as a schema rule, where it can see the
        platform and the URL in one object. An update sees only the fields that
        were sent, so the platform comes from the row - and clearing the URL is
        the case the schema cannot express at all: a Mattermost bot whose server
        is set back to null stops being able to reply, open its stream, or fetch
        an attachment, which is the state every Mattermost bot was in before the
        field existed.
        """
        if platform == "mattermost" and api_base_url is None:
            raise refused_field(
                "api_base_url",
                "A Mattermost bot cannot lose its server URL - it is self-hosted, "
                "so there is no default address to fall back to",
                platform=platform,
            )
        if platform != "mattermost" and api_base_url is not None:
            raise refused_field(
                "api_base_url",
                f"A server URL is for a self-hosted platform - a {platform} bot "
                "has one address for everybody",
                platform=platform,
            )

    @staticmethod
    def _check_slack_fields(
        platform: str, signing_secret: str | None, app_token: str | None
    ) -> None:
        if platform != "slack" and (signing_secret is not None or app_token is not None):
            raise BadRequestError(
                message="Signing secret and app token are Slack-app credentials - "
                f"a {platform} bot has nothing to verify with them",
                details={"platform": platform},
            )

    async def get(self, bot_id: UUID, *, for_update: bool = False) -> ChannelBot:
        """Get one of this organization's bots; raises NotFoundError if not found.

        A bot belonging to another organization is reported as missing rather
        than forbidden, so the endpoint cannot be used to probe for bot ids.
        """
        bot = await channel_bot_repo.get_for_org(
            self.db, bot_id, organization_id=self._org_id, for_update=for_update
        )
        if not bot:
            raise NotFoundError(
                message="Channel bot not found",
                details={"bot_id": str(bot_id)},
            )
        return bot

    async def find_active(self, bot_id: UUID) -> ChannelBot | None:
        """Return an active bot by ID, or None (inbound webhook / poller path)."""
        bot = await channel_bot_repo.get_for_inbound(self.db, bot_id)
        if not bot or not bot.is_active:
            return None
        return bot

    async def list_all(self, *, skip: int = 0, limit: int = 50) -> tuple[list[ChannelBotRead], int]:
        """This organization's bots, with who answers on each, and the total.

        The agents come back with the rows rather than being fetched per bot by
        the client: "registered and silent" is the state somebody opens this
        page to explain, and a listing that named only the bot could not tell it
        from "working". One grouped query for the page, not one per row.
        """
        bots = await channel_bot_repo.list_for_org(
            self.db, organization_id=self._org_id, skip=skip, limit=limit
        )
        answering = await agent_exposure_repo.active_agents_for_bots(
            self.db, channel_bot_ids=[bot.id for bot in bots]
        )
        total = await channel_bot_repo.count(self.db, organization_id=self._org_id)
        # One read per row, from the Redis every worker shares - the supervisor
        # holding the socket is usually in another process, so this cannot be
        # asked of the adapter here. A webhook bot is not asked at all: it holds
        # no connection, and a `down` beside one would be a fault reported about
        # a design (#1351).
        connections = {
            bot.id: await connection_state.read(bot.id) for bot in bots if not bot.webhook_mode
        }
        return [
            ChannelBotRead.model_validate(bot).model_copy(
                update={
                    "connection": connections.get(bot.id),
                    "agents": [
                        BotAgent(
                            id=agent.id,
                            name=agent.name,
                            slug=agent.slug,
                            has_avatar=agent.has_avatar,
                        )
                        for agent in answering.get(bot.id, [])
                    ],
                }
            )
            for bot in bots
        ], total

    async def list_by_platform(self, platform: str | None = None) -> list[ChannelBot]:
        """Return this organization's bots, optionally filtered by platform."""
        if platform:
            return await channel_bot_repo.get_by_platform(
                self.db, platform, organization_id=self._org_id
            )
        return await channel_bot_repo.list_for_org(self.db, organization_id=self._org_id)

    async def update(self, bot_id: UUID, data: ChannelBotUpdate) -> ChannelBot:
        """Update a channel bot. Only the fields the caller sent are applied;
        an explicit null clears a Slack credential, an omission leaves it."""
        # Locked from the read: every credential below is sealed at the row's
        # recorded key version, and a rotation committing between an unlocked
        # read and this write would tag the new envelopes with a version they
        # were not sealed under.
        bot = await self.get(bot_id, for_update=True)
        update_data = writable(data, over=ChannelBot)
        if "api_base_url" in update_data:
            self._check_server_url(bot.platform, update_data["api_base_url"])
        if "slack_signing_secret" in update_data or "slack_app_token" in update_data:
            self._check_slack_fields(
                bot.platform,
                update_data.get("slack_signing_secret"),
                update_data.get("slack_app_token"),
            )
        if "slack_signing_secret" in update_data:
            update_data["slack_signing_secret_encrypted"] = self._seal_at(
                update_data.pop("slack_signing_secret"), key_version=bot.secret_key_version
            )
        if "slack_app_token" in update_data:
            update_data["slack_app_token_encrypted"] = self._seal_at(
                update_data.pop("slack_app_token"), key_version=bot.secret_key_version
            )
        if update_data.get("token") is not None:
            # Sealed at the row's existing version, beside its other envelopes, and
            # the version column is left alone. Re-sealing the token afresh (at the
            # default v1) and resetting `secret_key_version` to match left the
            # column disagreeing with any sibling envelope sealed at a rotated
            # version - latent until a master-key rotation runs, then unreadable
            # (#552). One version per row, and an update never resets it.
            update_data["token_encrypted"] = self._seal_at(
                update_data.pop("token"), key_version=bot.secret_key_version
            )
        else:
            # A null token is "leave it", not "blank it". `token_encrypted` is NOT
            # NULL, and `writable` cannot drop the null for us because the schema
            # field (`token`) and the column (`token_encrypted`) have different
            # names - so a `{"token": null}` would otherwise seal to None and fail
            # the insert. Dropping it keeps a PATCH that sends null as "unchanged".
            update_data.pop("token", None)
        if "webhook_secret" in update_data:
            update_data["webhook_secret_encrypted"] = self._seal_at(
                update_data.pop("webhook_secret"), key_version=bot.secret_key_version
            )
        # A bot that enters webhook mode here used to get no secret: one was
        # minted at create time and only when `webhook_mode` was already true,
        # which is not the schema's default. So every bot switched over
        # afterwards had a null secret, and the receiver treated that as "skip
        # verification" - an open endpoint reached by anyone who guessed a bot
        # id (#4). Minted at the row's existing key version, beside its other
        # envelopes, and only where we are the side that hands the secret over.
        if (
            update_data.get("webhook_mode")
            and bot.webhook_secret_encrypted is None
            and "webhook_secret_encrypted" not in update_data
            and bot.platform in SECRET_MINTED_BY_US
        ):
            update_data["webhook_secret_encrypted"] = self._seal_at(
                secrets.token_urlsafe(32), key_version=bot.secret_key_version
            )
        # Both policies are stored as JSON, so a submitted model has to become a
        # dict either way - and a `None` means "leave it alone", not "clear it":
        # clearing `access_policy` would silently return a bot to the default
        # rather than to nothing.
        for field in ("access_policy",):
            value = update_data.get(field)
            if value is not None and hasattr(value, "model_dump"):
                update_data[field] = value.model_dump()
        updated = await channel_bot_repo.update(self.db, db_bot=bot, update_data=update_data)
        self._reopen_stream(updated)
        return updated

    async def delete(self, bot_id: UUID) -> None:
        """Delete a channel bot, and close the connection it was reached over."""
        bot = await self.get(bot_id)
        platform = bot.platform
        await channel_bot_repo.delete(self.db, bot_id, organization_id=self._org_id)
        # After the commit, and read out first: the row is gone by then, so the
        # platform has to be a string this coroutine already holds.
        spawn_after_commit(
            self.db,
            close_inbound_stream(bot_id=str(bot_id), platform=platform),
            name=f"close_channel_stream:{bot_id}",
        )

    async def activate(self, bot_id: UUID) -> ChannelBot:
        """Set is_active = True, and open the stream it is reached over."""
        bot = await self.get(bot_id)
        activated = await channel_bot_repo.update(
            self.db, db_bot=bot, update_data={"is_active": True}
        )
        self._reopen_stream(activated)
        return activated

    async def deactivate(self, bot_id: UUID) -> ChannelBot:
        """Set is_active = False, and close the stream, so it stops now.

        The mirror of `activate`, and the worse of the two to get wrong: a bot
        switched off went on answering until somebody restarted the API, so
        "stop it" needed a deploy.
        """
        bot = await self.get(bot_id)
        deactivated = await channel_bot_repo.update(
            self.db, db_bot=bot, update_data={"is_active": False}
        )
        self._reopen_stream(deactivated)
        return deactivated

    def get_decrypted_token(self, bot: ChannelBot) -> str:
        """Return the bot's token in the clear, for an immediate platform call."""
        return unseal_bot_token(bot)

    async def get_active_polling_bots(self, platform: str) -> list[ChannelBot]:
        """Return active polling (non-webhook) bots for the given platform.

        Deployment-wide, not org-scoped - the poller serves every tenant. Each
        bot returned carries its own `organization_id`.
        """
        return await channel_bot_repo.get_active_polling_bots(self.db, platform)

    async def list_sessions(
        self, bot_id: UUID, *, skip: int = 0, limit: int = 50
    ) -> tuple[list, int]:
        """List channel sessions for this bot."""
        items = await channel_session_repo.list_by_bot(self.db, bot_id, skip=skip, limit=limit)
        total = await channel_session_repo.count_by_bot(self.db, bot_id)
        return items, total

    async def register_webhook(self, bot_id: UUID) -> dict[str, Any]:
        """Register a webhook URL with the bot's platform.

        Looks up the bot, picks the adapter for its platform, builds the platform-specific
        webhook URL from settings, and asks the adapter to register it.
        """
        bot = await self.get(bot_id)
        adapter = get_adapter(bot.platform)
        token = self.get_decrypted_token(bot)
        webhook_url = inbound_webhook_url(bot.platform, bot_id)
        success = await adapter.register_webhook(
            token, url=webhook_url, secret=unseal_webhook_secret(bot)
        )
        return {"success": success, "webhook_url": webhook_url}

    async def delete_webhook(self, bot_id: UUID) -> dict[str, Any]:
        """Remove the webhook from the bot's platform (switches to polling mode)."""
        bot = await self.get(bot_id)
        adapter = get_adapter(bot.platform)
        token = self.get_decrypted_token(bot)
        success = await adapter.delete_webhook(token)
        return {"success": success}
