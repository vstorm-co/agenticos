"""Running models on a ChatGPT subscription: the sign-in, and the tokens it rotates.

Two things make this unlike every other provider credential.

**Nobody can type it.** A ChatGPT sign-in is an OAuth grant, and the only client
OpenAI lets a third party use for it pins its redirect to
`http://localhost:1455/auth/callback`. A deployment on any other host never
receives that redirect, so the browser lands on an address that does not load and
the person pastes that address back here. The code in it is bound to a PKCE
verifier this service minted and kept in Redis, so a pasted address is worth
nothing to anybody but the sign-in that started it.

The Codex CLI's own `~/.codex/auth.json` is deliberately *not* accepted. It
holds the CLI's grant, and the refresh token below is single-use: whichever of
the two refreshed first would sign the other out.

**It changes while it is used.** A refresh spends the refresh token it presents,
so the new pair has to reach the vault before the process ends, or the next run
finds a token the authorization server has already retired.
:class:`VaultCodexCredentials` is the provider's credential source: it reads the
pair from the vault on first use and before every refresh - adopting one another
process already rotated - and seals the new pair back under the same id. That is
best-effort, as Pydantic AI's protocol says: two runs refreshing in the same
instant can still race, and the loser is asked to sign in again.
"""

import json
import logging
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx2
from pydantic_ai.providers.openai_codex import (
    CredentialsRefreshError,
    OpenAICodexCredentials,
    OpenAICodexCredentialSource,
    OpenAICodexOAuthFlow,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.redis import RedisClient
from app.core.exceptions import BadRequestError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import OpenAICodexSecret, SecretKind, seal_secret, unseal_secret
from app.core.vault import VaultScope
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import Visibility
from app.db.session import get_db_context
from app.repositories import member_repo, organization_secret_repo
from app.services.access import SECRET, resolve_access
from app.services.organization_secret import OrganizationSecretService

logger = logging.getLogger(__name__)

PURPOSE = "openai_codex"
"""The vault purpose, and the provider id - the two are the same string."""

_PENDING_KEY = "openai-codex:sign-in:{state}"
# Long enough to sign in, pass a second factor and find the address bar; short
# enough that an abandoned verifier does not outlive the afternoon.
_PENDING_TTL_SECONDS = 15 * 60


def _as_secret(credentials: OpenAICodexCredentials) -> OpenAICodexSecret:
    return OpenAICodexSecret(
        access_token=credentials.access_token,
        refresh_token=credentials.refresh_token,
        account_id=credentials.account_id,
    )


class VaultCodexCredentials(OpenAICodexCredentialSource):
    """One vault secret as the place a Codex provider keeps its tokens.

    Holds ids, never tokens, so it can sit on a resolved credential and in a
    repr. Each call opens a session of its own: a refresh happens in the middle
    of a model request, inside a run whose own session commits on its own
    schedule, and the rotated pair must be durable whether or not that run is.

    Neither method writes an audit entry. A refresh is the provider renewing a
    grant somebody already gave, and recording one per expiry would bury the
    sign-ins and rotations people actually did.
    """

    def __init__(self, *, organization_id: UUID, secret_id: UUID) -> None:
        self.organization_id = organization_id
        self.secret_id = secret_id

    def __repr__(self) -> str:
        return f"VaultCodexCredentials(secret_id={self.secret_id})"

    async def _row(self, db: AsyncSession) -> OrganizationSecret:
        secret = await organization_secret_repo.get(
            db, self.secret_id, organization_id=self.organization_id
        )
        if secret is None:
            raise BadRequestError(
                message="The ChatGPT sign-in this model runs on is no longer in the vault",
                details={"secret_id": str(self.secret_id)},
            )
        return secret

    async def visible_to(self, user_id: UUID) -> bool:
        """Whether this person may see the sign-in in the vault themselves.

        Asked before the coding agent hands the tokens to Codex, where whatever
        Codex runs can read them: running an agent must not reach a sign-in its
        runner could not have chosen.
        """
        async with get_db_context() as db:
            membership = await member_repo.get(
                db, organization_id=self.organization_id, user_id=user_id
            )
            if membership is None:
                return False
            ctx = AuthContext(
                user_id=user_id, organization_id=self.organization_id, role=membership.role
            )
            secret = await organization_secret_repo.get(
                db, self.secret_id, organization_id=self.organization_id
            )
            return secret is not None and await resolve_access(
                db, ctx, secret, Perm.SECRETS_VIEW, resource_type=SECRET
            )

    async def load(self) -> OpenAICodexCredentials:
        """The pair as the vault holds it now."""
        async with get_db_context() as db:
            secret = await self._row(db)
            value = unseal_secret(
                secret.sealed_secret,
                kind=SecretKind.OPENAI_CODEX,
                scope=VaultScope.organization(self.organization_id),
                key_version=secret.key_version,
            )
        # `unseal_secret` refuses any other kind, so this is the only shape here.
        assert isinstance(value, OpenAICodexSecret)
        return OpenAICodexCredentials(
            access_token=value.access_token.get_secret_value(),
            refresh_token=value.refresh_token.get_secret_value(),
            account_id=value.account_id,
        )

    async def swap(self, previous: OpenAICodexCredentials, rotated: OpenAICodexCredentials) -> bool:
        """Seal `rotated` over the secret only if it still holds `previous`.

        What a task's sandbox hands back is whatever its `auth.json` held, which
        anything the task ran could have rewritten - another account's tokens
        among them. So it is taken only for the same account, and only over the
        pair written for the task: a reconnect, or a refresh the provider made in
        the meantime, is newer and stays. Compared under the row's lock.

        Returns:
            Whether the rotated pair was stored.
        """
        if rotated.account_id != previous.account_id:
            logger.warning("codex_rotation_for_another_account_refused")
            return False
        async with get_db_context() as db:
            secret = await organization_secret_repo.get_locked(
                db, self.secret_id, organization_id=self.organization_id
            )
            if secret is None:
                return False
            held = unseal_secret(
                secret.sealed_secret,
                kind=SecretKind.OPENAI_CODEX,
                scope=VaultScope.organization(self.organization_id),
                key_version=secret.key_version,
            )
            assert isinstance(held, OpenAICodexSecret)
            if held.refresh_token.get_secret_value() != previous.refresh_token:
                return False
            sealed = seal_secret(
                _as_secret(rotated), scope=VaultScope.organization(self.organization_id)
            )
            await organization_secret_repo.update(
                db,
                secret=secret,
                update_data={
                    "sealed_secret": sealed.ciphertext,
                    "hint": sealed.hint,
                    "key_version": sealed.key_version,
                },
            )
        return True

    async def save(self, credentials: OpenAICodexCredentials) -> None:
        """Seal a freshly rotated pair over the old one, under the same id."""
        async with get_db_context() as db:
            secret = await self._row(db)
            sealed = seal_secret(
                _as_secret(credentials), scope=VaultScope.organization(self.organization_id)
            )
            await organization_secret_repo.update(
                db,
                secret=secret,
                update_data={
                    "sealed_secret": sealed.ciphertext,
                    "hint": sealed.hint,
                    "key_version": sealed.key_version,
                },
            )


def _read_callback(callback_url: str) -> tuple[str, str]:
    """The code and state from the address the sign-in ended on.

    The whole address is what a person can copy, so that is what is asked for;
    a bare query string is accepted too. A refusal from ChatGPT arrives the same
    way, with `error` in place of `code`, and is named as one rather than as a
    malformed paste.
    """
    text = callback_url.strip()
    query = parse_qs(urlsplit(text).query or text.lstrip("?"))
    if "error" in query:
        raise refused_field(
            "callback_url",
            "ChatGPT reported the sign-in as refused. Start again and approve it",
        )
    code, state = query.get("code", [""])[0], query.get("state", [""])[0]
    if not code or not state:
        raise refused_field(
            "callback_url",
            "Paste the whole address ChatGPT sent you to - it carries a code and a state",
        )
    return code, state


class OpenAICodexService:
    """Sign in with ChatGPT, and store what comes back in the vault."""

    def __init__(self, db: AsyncSession, redis: RedisClient) -> None:
        self.db = db
        self.redis = redis

    async def start_sign_in(self, ctx: AuthContext) -> str:
        """Begin a sign-in and return the address to send the person to.

        The verifier stays here, bound to whoever started it: the address pasted
        back is only redeemable by the same person in the same organization.
        """
        flow = OpenAICodexOAuthFlow()
        await self.redis.set(
            _PENDING_KEY.format(state=flow.state),
            json.dumps(
                {
                    "code_verifier": flow.code_verifier,
                    "user_id": str(ctx.subject_id),
                    "organization_id": str(ctx.organization_id),
                }
            ),
            ttl=_PENDING_TTL_SECONDS,
        )
        return flow.authorization_url()

    async def _finish_sign_in(self, ctx: AuthContext, callback_url: str) -> OpenAICodexSecret:
        """Exchange the pasted code for a token pair.

        The pending sign-in is consumed before the exchange, so an address works
        once whatever the outcome. One started by somebody else reads exactly
        like an expired one: which states exist is not this caller's to learn.
        """
        code, state = _read_callback(callback_url)
        raw = await self.redis.getdel(_PENDING_KEY.format(state=state))
        pending = json.loads(raw) if raw is not None else None
        if (
            pending is None
            or pending["user_id"] != str(ctx.subject_id)
            or (pending["organization_id"] != str(ctx.organization_id))
        ):
            raise refused_field(
                "callback_url",
                "This sign-in has expired or was already used. Start again",
            )
        flow = OpenAICodexOAuthFlow(state=state)
        flow.code_verifier = pending["code_verifier"]
        try:
            credentials = await flow.exchange_code(code)
        except CredentialsRefreshError:
            # The token endpoint's own words go to the log; the form gets what
            # the person can do about it.
            logger.warning("ChatGPT refused a sign-in code", exc_info=True)
            raise refused_field(
                "callback_url",
                "ChatGPT did not accept this sign-in - it may have expired. Start again",
            ) from None
        except httpx2.HTTPError:
            # A timeout or a failed connection says nothing about the code, but
            # the pending sign-in is spent already, so the person starts again.
            logger.warning("ChatGPT could not be reached to finish a sign-in", exc_info=True)
            raise refused_field(
                "callback_url",
                "ChatGPT could not be reached to finish this sign-in. Start again",
            ) from None
        return _as_secret(credentials)

    async def create(
        self,
        ctx: AuthContext,
        *,
        callback_url: str,
        name: str,
        description: str | None,
        visibility: Visibility,
    ) -> OrganizationSecret:
        """Finish a sign-in and store it as a new vault secret."""
        value = await self._finish_sign_in(ctx, callback_url)
        return await OrganizationSecretService(self.db).create(
            ctx,
            name=name,
            value=value,
            description=description,
            purpose=PURPOSE,
            visibility=visibility,
        )

    async def reconnect(
        self, ctx: AuthContext, secret_id: UUID, *, callback_url: str
    ) -> OrganizationSecret:
        """Finish a sign-in and put it in place of an existing one.

        What a refresh that was refused asks for: the grant is gone, and every
        model keyed by this secret keeps its id. Permission and kind are checked
        by the rotation itself, as for any other secret.
        """
        value = await self._finish_sign_in(ctx, callback_url)
        return await OrganizationSecretService(self.db).update(ctx, secret_id, value=value)
