"""Organization API keys: issuing, listing, revoking, and authenticating a request (#1794).

A key carries its issuer's authority, narrowed twice: to the scopes it was issued
with, and - at every use - to what the issuer may still do. Authentication
therefore re-reads the issuer's membership on every request rather than trusting
anything frozen into the key, which is what makes demoting or removing a member
narrow or stop every key they hold.

The plaintext is in exactly one response, the one that creates it. It is never
logged, audited or returned again; refusals name the key by its prefix at most.
"""

import hashlib
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import current_impersonator, record_audit
from app.core.exceptions import (
    AuthenticationError,
    BadRequestError,
    InternalError,
    NotFoundError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.api_key import ApiKey
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.session import get_db_context
from app.repositories import api_key as api_key_repo
from app.repositories import member as member_repo
from app.repositories import organization as organization_repo
from app.repositories import user as user_repo
from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyList,
    ApiKeyPreset,
    ApiKeyRead,
    ApiKeyScopeCatalog,
    ApiKeyStatus,
)
from app.schemas.change_event import ChangeSurface

KEY_PREFIX = "aos_"
"""What every organization key starts with - so a secret scanner, a log scrubber
and :func:`is_api_key` recognise one without a database round trip."""

_PREFIX_LENGTH = len(KEY_PREFIX) + 8
_PREFIX_ATTEMPTS = 5
"""How many prefixes a mint draws before deciding the namespace is the problem."""
_SECRET_BYTES = 32
_TOUCH_EVERY = timedelta(minutes=1)
_RUN_CREDENTIAL_LIFETIME = timedelta(hours=2)
"""Long enough for a run that waits on an approval for a while; a run parked
longer than this asks the platform again for a fresh one when it resumes."""
_DEFAULT_LIFETIME = timedelta(days=90)
"""What a key created without an expiry gets. A key that lives for ever is a
secret that never stops working when it leaks, so the default is a lifetime,
not an absence of one."""
_MAX_LIFETIME = timedelta(days=90)
_EXPIRY_CLOCK_TOLERANCE = timedelta(minutes=5)
_REFUSED = "Invalid, expired or revoked API key"

# Keys never manage keys: a leaked one must not be able to mint its successors.
_NOT_GRANTABLE = frozenset({Perm.API_KEYS_CREATE, Perm.API_KEYS_MANAGE})

_READ_ONLY = frozenset(
    {
        Perm.AGENTS_VIEW,
        Perm.COLLECTIONS_VIEW,
        Perm.SKILLS_VIEW,
        Perm.CONTEXT_VIEW,
        Perm.ARTIFACTS_VIEW,
        Perm.PROJECTS_VIEW,
        Perm.RUNS_VIEW,
        Perm.MEMBERS_VIEW,
    }
)
_KNOWLEDGE_INGEST = frozenset({Perm.COLLECTIONS_VIEW, Perm.COLLECTIONS_EDIT})


def api_key_prefix(raw: str) -> str:
    """The part of a presented key that names it - what it is looked up and limited by."""
    return raw[:_PREFIX_LENGTH]


def is_api_key(token: str) -> bool:
    """Whether a bearer token is an organization key rather than a session JWT."""
    return token.startswith(KEY_PREFIX)


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _status(key: ApiKey, now: datetime) -> ApiKeyStatus:
    if key.revoked_at is not None:
        return "revoked"
    if key.expires_at is not None and key.expires_at <= now:
        return "expired"
    return "active"


def _read(key: ApiKey, issuer_email: str, now: datetime) -> ApiKeyRead:
    return ApiKeyRead(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        scopes=list(key.scopes),
        user_id=key.user_id,
        issuer_email=issuer_email,
        status=_status(key, now),
        expires_at=key.expires_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
        created_at=key.created_at,
    )


@dataclass(frozen=True)
class KeyCaller:
    """Who a key-authenticated request is: the issuer, and their narrowed context."""

    user: User
    organization: Organization
    context: AuthContext
    api_key_id: UUID
    prefix: str
    surface: ChangeSurface = "api_key"
    """Which kind of client holds the key - what a change it makes is attributed to."""

    name: str = ""


class ApiKeyService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _grantable(ctx: AuthContext) -> list[Perm]:
        return sorted(perm for perm in ctx.permissions if perm not in _NOT_GRANTABLE)

    def scope_catalog(self, ctx: AuthContext) -> ApiKeyScopeCatalog:
        """The permissions the caller may put on a key, and the presets over them.

        "Read-only" and "Full access" hold what the caller has of them, so a
        Member's full access is a Member's. "Knowledge ingest" is a task rather than
        a ceiling - read a collection and add to it - so it is offered only to a
        caller who can do both; half of it would be a key that cannot ingest.
        """
        held = self._grantable(ctx)
        presets: list[ApiKeyPreset] = []
        read_only = [perm.value for perm in held if perm in _READ_ONLY]
        if read_only:
            presets.append(ApiKeyPreset(id="read_only", scopes=read_only))
        if set(held) >= _KNOWLEDGE_INGEST:
            presets.append(ApiKeyPreset(id="knowledge_ingest", scopes=sorted(_KNOWLEDGE_INGEST)))
        # Standing personal consent is a separate, informed opt-in, including
        # when the person chooses the broad organization-access preset.
        ordinary = [perm.value for perm in held if perm is not Perm.PERSONAL_CONSENT]
        if ordinary:
            presets.append(ApiKeyPreset(id="full_access", scopes=ordinary))
        return ApiKeyScopeCatalog(scopes=[perm.value for perm in held], presets=presets)

    async def create(self, ctx: AuthContext, data: ApiKeyCreate) -> ApiKeyCreated:
        """Issue a key carrying the caller's authority, narrowed to `data.scopes`.

        Raises:
            BadRequestError: A scope the caller does not hold, or cannot grant, or an
                expiry already in the past - named on the field.
        """
        held = set(self._grantable(ctx))
        refused = sorted(perm.value for perm in data.scopes if perm not in held)
        if refused:
            raise refused_field(
                "scopes", f"You cannot grant what you do not hold: {', '.join(refused)}"
            )
        now = datetime.now(UTC)
        if data.expires_at is not None:
            if data.expires_at <= now:
                raise refused_field("expires_at", "The expiry has to be in the future")
            if data.expires_at > now + _MAX_LIFETIME + _EXPIRY_CLOCK_TOLERANCE:
                raise refused_field("expires_at", "The expiry cannot be more than 90 days away")
        key, row = await self._mint(
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            name=data.name,
            scopes=sorted({perm.value for perm in data.scopes}),
            expires_at=data.expires_at if data.expires_at is not None else now + _DEFAULT_LIFETIME,
            oauth_grant_id=None,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="api_key.created",
            target_type="api_key",
            target_id=str(row.id),
            details={"name": row.name, "prefix": row.prefix, "scopes": row.scopes},
        )
        issuer = await user_repo.get_by_id(self.db, ctx.subject_id)
        email = issuer.email if issuer is not None else ""
        return ApiKeyCreated(**_read(row, email, now).model_dump(), key=key)

    async def _free_prefix(self) -> str:
        """A visible prefix no key carries yet.

        Thirty-two random bits, unique across every key, OAuth access token and
        run credential together: by tens of thousands of rows a collision is
        likely, and it failed the unique constraint - and with it the key, the
        run or the refresh being issued. Drawn again rather than widened, since
        the prefix's length is how a presented key is split into prefix and secret.
        """
        for _ in range(_PREFIX_ATTEMPTS):
            prefix = KEY_PREFIX + secrets.token_hex(4)
            if not await api_key_repo.prefix_taken(self.db, prefix):
                return prefix
        raise InternalError(
            message="Could not draw a free API key prefix",
            details={"attempts": _PREFIX_ATTEMPTS},
        )

    async def _mint(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        name: str,
        scopes: list[str],
        expires_at: datetime | None,
        oauth_grant_id: UUID | None,
        internal: bool = False,
    ) -> tuple[str, ApiKey]:
        """A new key and its row; the plaintext exists only in the returned string.

        Raises:
            InternalError: Every prefix drawn was taken - a namespace that full is
                a defect to look at, not a key to keep trying for.
        """
        prefix = await self._free_prefix()
        key = prefix + secrets.token_urlsafe(_SECRET_BYTES)
        row = await api_key_repo.create(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            name=name,
            prefix=prefix,
            key_hash=_digest(key),
            scopes=scopes,
            expires_at=expires_at,
            oauth_grant_id=oauth_grant_id,
            internal=internal,
        )
        return key, row

    async def issue_for_grant(
        self,
        *,
        grant_id: UUID,
        organization_id: UUID,
        user_id: UUID,
        client_name: str,
        scopes: list[str],
        expires_at: datetime,
    ) -> str:
        """An OAuth access token: a short-lived key under the grant it was issued for (#2059).

        Not audited one by one - a client refreshes every hour - the consent and
        its revocation are. Its own requests are audited like any key's.
        """
        key, _row = await self._mint(
            organization_id=organization_id,
            user_id=user_id,
            name=f"OAuth: {client_name}"[:100],
            scopes=scopes,
            expires_at=expires_at,
            oauth_grant_id=grant_id,
        )
        return key

    async def issue_for_run(
        self, ctx: AuthContext, *, agent_id: UUID | None = None, conversation_id: UUID | None = None
    ) -> str | None:
        """A short-lived credential carrying `ctx`, for the in-app assistant (#1798).

        The assistant operates the platform through the public API as the person
        it runs for, so it needs what an integration needs: a key, holding exactly
        what `ctx` holds - narrowed again on every call to the person's current
        role, like any key. `None` when nobody is behind the run: an anonymous
        visitor has no authority to lend, and neither does a run where the
        publisher stands in for one - a public widget, an embed, an unlinked
        channel member. That context names the publisher only so the run has a
        subject; lending their authority to whoever typed would hand a stranger
        the publisher's agents, runs and members.

        Minted per run and never listed; lapsed ones are swept as new ones are made.
        """
        if ctx.user_id is None or ctx.subject_is_publisher_fallback:
            return None
        now = datetime.now(UTC)
        await api_key_repo.delete_expired_internal(self.db, user_id=ctx.user_id, before=now)
        key, _row = await self._mint(
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            name="Platform assistant",
            scopes=[perm.value for perm in self._grantable(ctx)],
            expires_at=now + _RUN_CREDENTIAL_LIFETIME,
            oauth_grant_id=None,
            internal=True,
        )
        provenance: dict[str, UUID] = {}
        if agent_id is not None:
            provenance["source_agent_id"] = agent_id
        if (
            conversation_id is not None
            and ctx.api_key_id is None
            and ctx.key_scopes is None
            and ctx.fired_as_creator is None
            and ctx.routine_id is None
            and current_impersonator() is None
        ):
            provenance["source_conversation_id"] = conversation_id
        if provenance:
            await api_key_repo.update(self.db, key=_row, update_data=provenance)
        return key

    async def rotate(self, ctx: AuthContext, key_id: UUID) -> ApiKeyCreated:
        """Replace a key's secret, revoking the old one in the same transaction.

        The replacement carries the same name, scopes, issuer and organization
        as the key it replaces - the same access, under a secret nobody has
        seen. Its expiry is the old key's when one was set, and a fresh default
        lifetime when the old key had none. The old key stops working at once:
        there is no overlap window, so the caller swaps to the returned secret
        in the same step. Provenance (`source_agent_id`,
        `source_conversation_id`) is not carried over - it names the chat that
        minted an internal key, not authority.

        The plaintext is in exactly one response, this one, like `create`.

        Raises:
            NotFoundError: Not this organization's key, or not issued by the
                caller - the same answer as `revoke`, so an id cannot be used
                to learn which keys exist.
            BadRequestError: The key is internal, OAuth-grant-backed, revoked,
                or expired.
        """
        key = await api_key_repo.get(self.db, key_id, organization_id=ctx.organization_id)
        if key is None or key.user_id != ctx.subject_id:
            raise NotFoundError(message="API key not found", details={"api_key_id": key_id})
        if key.internal or key.oauth_grant_id is not None:
            raise BadRequestError(message="Internal and OAuth keys cannot be rotated")
        now = datetime.now(UTC)
        if _status(key, now) != "active":
            # A revoked key rotated back to life would undo the revocation -
            # the leak it was revoked for would have a fresh secret.
            raise BadRequestError(
                message="Only an active key can be rotated",
                details={"api_key_id": key_id, "status": _status(key, now)},
            )
        new_key, row = await self._mint(
            organization_id=key.organization_id,
            user_id=key.user_id,
            name=key.name,
            scopes=list(key.scopes),
            expires_at=min(key.expires_at, now + _MAX_LIFETIME)
            if key.expires_at is not None
            else now + _DEFAULT_LIFETIME,
            oauth_grant_id=key.oauth_grant_id,
            internal=key.internal,
        )
        await api_key_repo.update(self.db, key=key, update_data={"revoked_at": now})
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="api_key.rotated",
            target_type="api_key",
            target_id=str(row.id),
            details={
                "name": key.name,
                "old_prefix": key.prefix,
                "new_prefix": row.prefix,
            },
        )
        issuer = await user_repo.get_by_id(self.db, key.user_id)
        email = issuer.email if issuer is not None else ""
        return ApiKeyCreated(**_read(row, email, now).model_dump(), key=new_key)

    async def list_keys(self, ctx: AuthContext) -> ApiKeyList:
        """Every key in the organization for `api_keys:manage`, otherwise the caller's own."""
        mine_only = None if ctx.has(Perm.API_KEYS_MANAGE) else ctx.subject_id
        rows = await api_key_repo.list_for_organization(
            self.db, organization_id=ctx.organization_id, user_id=mine_only
        )
        now = datetime.now(UTC)
        items = [_read(key, email, now) for key, email in rows]
        return ApiKeyList(items=items, total=len(items))

    async def revoke(self, ctx: AuthContext, key_id: UUID) -> ApiKeyRead:
        """Stop a key working, at once. Revoking a revoked key changes nothing.

        Raises:
            NotFoundError: Not this organization's key, or somebody else's for a
                caller without `api_keys:manage` - the same answer, so an id cannot
                be used to learn which keys exist.
        """
        key = await api_key_repo.get(self.db, key_id, organization_id=ctx.organization_id)
        if key is None or (key.user_id != ctx.subject_id and not ctx.has(Perm.API_KEYS_MANAGE)):
            raise NotFoundError(message="API key not found", details={"api_key_id": key_id})
        now = datetime.now(UTC)
        if key.revoked_at is None:
            key = await api_key_repo.update(self.db, key=key, update_data={"revoked_at": now})
            await record_audit(
                self.db,
                actor_user_id=ctx.subject_id,
                organization_id=ctx.organization_id,
                action="api_key.revoked",
                target_type="api_key",
                target_id=str(key.id),
                details={"name": key.name, "prefix": key.prefix},
            )
        issuer = await user_repo.get_by_id(self.db, key.user_id)
        return _read(key, issuer.email if issuer is not None else "", now)

    async def authenticate(self, raw: str) -> KeyCaller:
        """The issuer and narrowed context a presented key stands for.

        Every refusal is the same sentence: whether a prefix exists, was revoked or
        has expired is not something a caller holding a wrong key may learn.

        Raises:
            AuthenticationError: Unknown, wrong, revoked or expired key, or an issuer
                who is no longer an active member of the key's organization.
        """
        key = await api_key_repo.get_by_prefix(self.db, api_key_prefix(raw))
        if key is None or not secrets.compare_digest(key.key_hash, _digest(raw)):
            raise AuthenticationError(message=_REFUSED)
        now = datetime.now(UTC)
        caller = await self._caller(key, now)
        await api_key_repo.touch(self.db, key.id, at=now, stale_before=now - _TOUCH_EVERY)
        return caller

    async def context_for_key(self, api_key_id: UUID, *, organization_id: UUID) -> AuthContext:
        """The context a key stands for *now*, for work it asked for earlier.

        An asynchronous run executes after the request that queued it, and the
        key may have been revoked, or its issuer demoted or removed, in between.
        So the worker re-establishes the context by the same checks
        `authenticate` makes - minus the secret, which it never had - rather
        than trusting the one the request was answered under.

        One check differs: a key that has merely expired still stands for work it
        started while it was valid. Expiry bounds what a key can start; the work
        then belongs to its issuer, so an OAuth token's hour or a run credential's
        two hours do not cut a long run short. Revoking the key, or its OAuth
        grant, stops the work, as does its issuer leaving.

        Raises:
            AuthenticationError: The key is gone or revoked, or its issuer is no
                longer an active member of its organization.
        """
        key = await api_key_repo.get(self.db, api_key_id, organization_id=organization_id)
        if key is None:
            raise AuthenticationError(message=_REFUSED)
        return (await self._caller(key, datetime.now(UTC), started_earlier=True)).context

    async def _caller(
        self, key: ApiKey, now: datetime, *, started_earlier: bool = False
    ) -> KeyCaller:
        status = _status(key, now)
        if status == "revoked" or (status == "expired" and not started_earlier):
            raise AuthenticationError(message=_REFUSED, details={"prefix": key.prefix})
        membership = await member_repo.get_active(
            self.db, organization_id=key.organization_id, user_id=key.user_id
        )
        issuer = await user_repo.get_by_id(self.db, key.user_id)
        organization = await organization_repo.get_by_id(self.db, key.organization_id)
        if membership is None or issuer is None or not issuer.is_active or organization is None:
            raise AuthenticationError(message=_REFUSED, details={"prefix": key.prefix})
        return KeyCaller(
            user=issuer,
            organization=organization,
            api_key_id=key.id,
            prefix=key.prefix,
            name=key.name,
            surface="mcp" if key.oauth_grant_id else "assistant" if key.internal else "api_key",
            context=AuthContext(
                user_id=key.user_id,
                organization_id=key.organization_id,
                role=membership.role,
                api_key_id=key.id,
                key_scopes=frozenset(Perm(scope) for scope in key.scopes if scope in Perm),
                key_internal=key.internal,
                source_conversation_id=key.source_conversation_id if key.internal else None,
            ),
        )


#: What a job's row says when the API key it was started with no longer stands.
KEY_GONE = "The API key that started this was revoked or no longer exists, so it was stopped."


async def job_context(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID | None,
    api_key_id: UUID | None,
) -> AuthContext | None:
    """The authority background work runs with, rebuilt when the work starts.

    Work queued by a request runs later, under a context it rebuilds rather
    than the request's: whoever started it may have lost their role, and a key
    it was started with may have been narrowed or revoked. So it is the
    starter's role as it is now, narrowed to the key's scopes as they are now
    - a job does no more than the request that started it could do today. A
    job is not the starter talking, so it reads and writes none of their
    personal memory.

    Returns:
        The context, or `None` when the starter is no longer an active member.

    Raises:
        AuthenticationError: Started with a key that is now revoked, gone or in
            another organization, with :data:`KEY_GONE` as the message the job's
            row shows. A key that has only expired still stands for the job.
    """
    if api_key_id is not None:
        try:
            ctx = await ApiKeyService(db).context_for_key(
                api_key_id, organization_id=organization_id
            )
        except AuthenticationError:
            raise AuthenticationError(message=KEY_GONE) from None
        return replace(ctx, subject_is_publisher_fallback=True)
    membership = (
        None
        if user_id is None
        else await member_repo.get_active(db, organization_id=organization_id, user_id=user_id)
    )
    if user_id is None or membership is None:
        return None
    return AuthContext(
        user_id=user_id,
        organization_id=organization_id,
        role=membership.role,
        subject_is_publisher_fallback=True,
    )


async def mint_for_run(
    ctx: AuthContext, *, agent_id: UUID | None = None, conversation_id: UUID | None = None
) -> str | None:
    """:meth:`ApiKeyService.issue_for_run`, committed before it returns.

    The credential is presented by an in-process request on a session of its
    own, so it has to be visible outside the run's transaction - and a delegate
    is built mid-run, long after that transaction's opening commit, where a key
    flushed on the run's session would not be seen until the run ended.
    """
    async with get_db_context() as db:
        return await ApiKeyService(db).issue_for_run(
            ctx, agent_id=agent_id, conversation_id=conversation_id
        )
