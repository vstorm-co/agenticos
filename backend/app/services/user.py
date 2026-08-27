import asyncio
import contextlib
import logging
import secrets
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AlreadyExistsError,
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.security import (
    create_magic_link_token,
    create_password_reset_token,
    get_password_hash,
    verify_password,
    verify_special_token,
)
from app.db.models.user import User
from app.db.updates import writable
from app.repositories import (
    member_repo,
    organization_repo,
    organization_secret_repo,
    session_repo,
    user_repo,
)
from app.schemas.conversation_share import AdminUserList, AdminUserRead
from app.schemas.user import (
    AdminUserDetail,
    AdminUserMembership,
    UserCreate,
    UserUpdate,
)
from app.services.deployment_settings import DeploymentSettingsService
from app.services.email.service import get_email_service
from app.services.file_storage import avatar_filename, get_file_storage
from app.services.organization import OrganizationService
from app.services.signup_policy import check_may_register

logger = logging.getLogger(__name__)

# A real bcrypt hash of a value nobody holds, computed once at import. An
# address with no account is verified against this rather than short-circuited,
# so an unknown address costs the same ~170ms as a known one and the timing no
# longer says which addresses have accounts (#947).
_DUMMY_HASH = get_password_hash(secrets.token_urlsafe(32))


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _is_first_user(self) -> bool:
        count = (await self.db.execute(select(func.count()).select_from(User))).scalar_one()
        return count == 0

    async def get_by_id(self, user_id: UUID) -> User:
        user = await user_repo.get_by_id(self.db, user_id)
        if not user:
            raise NotFoundError(
                message="User not found",
                details={"user_id": user_id},
            )
        return user

    async def get_by_email(self, email: str) -> User | None:
        return await user_repo.get_by_email(self.db, email)

    async def get_multi(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[User]:
        return await user_repo.get_multi(self.db, skip=skip, limit=limit)

    async def delete_non_admins(self) -> int:
        """Delete every non-admin user, reconciling each as single deletion does.

        Not a bulk `DELETE users`: every account has a personal org whose
        `created_by_user_id` FK is RESTRICT, so a bulk delete 500s on the first
        row (#1124). Each goes through `delete`, which runs `_release_owned_rows`
        - purging the personal org, promoting private secrets, handing off or
        refusing owned orgs - the same reconciliation `DELETE /users/{id}` uses.

        `is_app_admin` is rechecked under the row lock, not just filtered by the
        list: a `create-app-admin` that promotes a listed account before this loop
        reaches it would otherwise have it deleted despite the command's promise
        to keep admins, since `delete` does not re-read the flag (#1139).
        """
        removed = 0
        for candidate in await user_repo.list_non_admins(self.db):
            locked = await user_repo.get_by_id_for_update(self.db, candidate.id)
            if locked is None or locked.is_app_admin:
                continue
            await self.delete(candidate.id)
            removed += 1
        return removed

    async def has_any(self) -> bool:
        return await user_repo.has_any(self.db)

    async def admin_detail(self, user_id: UUID) -> AdminUserDetail:
        """Where this person has access, when they were last here, what is open.

        Three reads rather than one because they are three tables, and they are
        here rather than in the drawer because a client assembling them would
        make three round trips to answer one question - and would have to know
        that "no sessions ever" and "no sessions now" are different answers.

        The user is fetched first so an unknown id is a 404 rather than an empty
        detail about nobody.
        """
        await self.get_by_id(user_id)
        memberships = await organization_repo.list_for_user(self.db, user_id)
        sessions = await session_repo.get_user_sessions(self.db, user_id, active_only=True)
        return AdminUserDetail(
            memberships=[
                AdminUserMembership(
                    organization_id=organization.id,
                    name=organization.name,
                    slug=organization.slug,
                    is_personal=organization.is_personal,
                    role=role,
                )
                for organization, role in memberships
            ],
            # The sessions come back most-recently-used first, so the head is
            # both answers: when they were last here, and the newest one open.
            last_seen_at=sessions[0].last_used_at if sessions else None,
            active_sessions=len(sessions),
            newest_session_at=max((s.created_at for s in sessions), default=None),
        )

    async def admin_list_with_counts(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        search: str | None = None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
    ) -> AdminUserList:
        rows, total = await user_repo.admin_list_with_counts(
            self.db,
            skip=skip,
            limit=limit,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        items = [
            AdminUserRead(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                is_active=user.is_active,
                is_app_admin=user.is_app_admin,
                conversation_count=conv_count,
                created_at=user.created_at,
            )
            for user, conv_count in rows
        ]
        return AdminUserList(items=items, total=total)

    async def register(self, user_in: UserCreate) -> User:
        """The first user to register is auto-promoted to app-admin - no separate CLI step needed.

        Gated on this deployment's sign-up policy, which is why the check sits after
        the duplicate-address one: an address that already has an account is told
        so whatever the policy says, and a closed deployment is not a way to find
        out who is registered.

        `invitation_token` is passed through and nothing here reads it: it admits an
        address the policy would otherwise refuse, and joining the organization is
        still a separate `InvitationService.accept` the client makes once it has a
        session. Registering with a token does *not* accept the invitation.
        """
        existing = await user_repo.get_by_email(self.db, user_in.email)
        if existing:
            raise AlreadyExistsError(
                message="Email already registered",
                details={"email": user_in.email},
            )

        is_first_user = await self._is_first_user()
        await check_may_register(
            self.db,
            email=user_in.email,
            is_first_user=is_first_user,
            invitation_token=user_in.invitation_token,
        )

        hashed_password = await asyncio.to_thread(get_password_hash, user_in.password)
        user = await user_repo.create(
            self.db,
            email=user_in.email,
            hashed_password=hashed_password,
            full_name=user_in.full_name,
            is_app_admin=is_first_user,
        )
        org_service = OrganizationService(self.db)
        await org_service.create_personal_org(user.id, user_in.email)
        try:
            login_url = settings.FRONTEND_URL.rstrip("/") + "/login"
            await get_email_service().send_welcome(
                to=user.email,
                name=user.full_name or user.email,
                login_url=login_url,
                app_name=await DeploymentSettingsService(self.db).effective_app_name(),
            )
        except Exception:
            logger.exception(
                "welcome_email_failed",
                extra={"user_id": str(user.id), "email": user.email},
            )
        return user

    async def get_or_create_oauth_user(
        self,
        *,
        provider: str,
        provider_id: str,
        email: str,
        full_name: str | None = None,
        invitation_token: str | None = None,
    ) -> User:
        """Email-matched existing accounts get the OAuth identity attached rather than creating a duplicate.

        `invitation_token` is the one the sign-in was started with, carried through
        the provider round trip in the session. It admits an address the policy
        would otherwise refuse and nothing else: joining the organization is still a
        separate `InvitationService.accept`. Without it an `invite_only` deployment
        refused the Google button for precisely the invitations that need a token -
        a link constraining neither an address nor a domain, which the address-based
        fallback cannot see - so one person could register with a password and not
        with the provider offered beside it.
        """
        existing = await user_repo.get_by_oauth(self.db, provider, provider_id)
        if existing:
            return existing

        by_email = await user_repo.get_by_email(self.db, email)
        if by_email is not None:
            await user_repo.update(
                self.db,
                db_user=by_email,
                update_data={"oauth_provider": provider, "oauth_id": provider_id},
            )
            return by_email

        # The second path that mints an account, and the reason the policy is not
        # simply a check inside `register`: a deployment with Google sign-in and a
        # closed sign-up form is not closed at all if this branch is ungated, and
        # nothing about the OAuth callback looks like a registration.
        await check_may_register(
            self.db,
            email=email,
            is_first_user=await self._is_first_user(),
            invitation_token=invitation_token,
        )

        user = await user_repo.create(
            self.db,
            email=email,
            hashed_password=None,
            full_name=full_name,
            oauth_provider=provider,
            oauth_id=provider_id,
        )
        org_service = OrganizationService(self.db)
        await org_service.create_personal_org(user.id, user.email)
        try:
            login_url = settings.FRONTEND_URL.rstrip("/") + "/login"
            await get_email_service().send_welcome(
                to=user.email,
                name=user.full_name or user.email,
                login_url=login_url,
                app_name=await DeploymentSettingsService(self.db).effective_app_name(),
            )
        except Exception:
            logger.exception(
                "welcome_email_failed",
                extra={"user_id": str(user.id), "email": user.email},
            )
        return user

    async def authenticate(self, email: str, password: str) -> User:
        user = await user_repo.get_by_email(self.db, email)
        # bcrypt is ~170ms with no suspension point, so it runs in a thread rather
        # than blocking the event loop for every other request the worker holds
        # (#947). And always against a hash: an unknown address is checked against
        # `_DUMMY_HASH` rather than skipping bcrypt, so it cannot be told apart
        # from a known one by how long the refusal takes.
        stored = user.hashed_password if user and user.hashed_password else _DUMMY_HASH
        ok = await asyncio.to_thread(verify_password, password, stored)
        if not user or not user.hashed_password or not ok:
            raise AuthenticationError(message="Invalid email or password")
        if not user.is_active:
            raise AuthenticationError(message="User account is disabled")
        return user

    async def update(self, user_id: UUID, user_in: UserUpdate) -> User:
        user = await self.get_by_id(user_id)

        update_data = writable(user_in, over=User)
        if "password" in update_data:
            update_data["hashed_password"] = await asyncio.to_thread(
                get_password_hash, update_data.pop("password")
            )

        return await user_repo.update(self.db, db_user=user, update_data=update_data)

    async def update_current(self, user: User, user_in: UserUpdate) -> User:
        """A user updating their own row through `/users/me`.

        `UserUpdate` carries `is_active`, and this route reaches the same column
        the admin route does - so without the same refusal an app admin could
        suspend themselves here, the exact lock-out #941 guards against one route
        over (a single-admin install then stays locked until somebody reaches a
        terminal). A non-admin deactivating their own account only affects
        themselves and an admin can restore it, so the guard is the app admin's
        alone.
        """
        if user.is_app_admin and user_in.is_active is False:
            raise AuthorizationError(
                message="You cannot suspend your own account; ask another app admin to."
            )
        return await self.update(user.id, user_in)

    async def update_avatar(self, user_id: UUID, file_data: bytes, content_type: str) -> User:
        ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
        if content_type not in ALLOWED_AVATAR_TYPES:
            raise ValueError("Only JPEG, PNG, WebP, and GIF images are allowed")
        if len(file_data) > 2 * 1024 * 1024:
            raise ValueError("Avatar image too large. Maximum 2MB.")

        storage = get_file_storage()

        user = await self.get_by_id(user_id)
        if user.avatar_url:
            with contextlib.suppress(Exception):
                await storage.delete(user.avatar_url)

        # Stored under a suffix from the validated type, not the caller's
        # filename: the served type is guessed from the name on disk, so a valid
        # image uploaded as `avatar` or `avatar.txt` would otherwise be
        # unrenderable (#702).
        storage_path = await storage.save(
            f"avatars/{user_id}", avatar_filename(content_type), file_data
        )
        return await user_repo.update(
            self.db, db_user=user, update_data={"avatar_url": storage_path}
        )

    def get_avatar_path(self, avatar_url: str) -> str | None:
        full_path = get_file_storage().get_full_path(avatar_url)
        return str(full_path) if full_path is not None else None

    async def delete(self, user_id: UUID) -> User:
        # FOR UPDATE before the reconcile: releasing the rows that would block the
        # delete and then deleting is check-then-act, so a private secret or
        # personal org inserted concurrently (both take FOR KEY SHARE on this row)
        # would land a fresh CHECK/RESTRICT blocker between the reconcile and the
        # DELETE and 500 it. The lock makes that insert wait, so the reconcile
        # sees every child there is - a fresh read under READ COMMITTED (#1115).
        user = await user_repo.get_by_id_for_update(self.db, user_id)
        if not user:
            raise NotFoundError(
                message="User not found",
                details={"user_id": user_id},
            )
        await self._release_owned_rows(user_id)
        await user_repo.delete(self.db, user_id)
        return user

    async def _release_owned_rows(self, user_id: UUID) -> None:
        """Hand on or remove what would otherwise block the user's deletion (#9).

        Three FK/CHECK pairs make a bare `DELETE users` 500: a private secret's
        owner is `SET NULL` under a check that forbids an ownerless private
        secret; every signup creates a personal org, and `created_by_user_id` is
        `RESTRICT`. Each is resolved here in the request's own transaction, before
        the row goes.

        A fourth case is not a 500 but a silent orphan: a user who is the sole
        Owner of an org they did *not* create takes its last owner membership with
        them (`ON DELETE CASCADE`), leaving nobody who can manage it. That is
        refused here too (#1117).
        """
        await organization_secret_repo.promote_owned_private_to_org(self.db, owner_user_id=user_id)

        org_service = OrganizationService(self.db)
        handled: set[UUID] = set()
        for org in await organization_repo.list_created_by(self.db, user_id):
            handled.add(org.id)
            if org.is_personal:
                await org_service.purge(org)
                continue
            heir = await member_repo.other_owner_id(
                self.db, organization_id=org.id, exclude_user_id=user_id
            )
            if heir is None:
                raise BadRequestError(
                    message="Cannot delete the sole owner of a shared organization; "
                    "transfer ownership or delete the organization first",
                    details={"user_id": user_id, "organization_id": org.id},
                )
            await organization_repo.reassign_creator(self.db, org=org, new_creator_id=heir)

        # Ownership moves without the creator FK, so a user can be the sole Owner
        # of an org they did not create - one `list_created_by` never returns.
        # Deleting them cascades that last owner membership away and leaves the
        # org ownerless: no 500, but nobody can manage it through the owner-gated
        # APIs (#1117). Refuse, unless another owner is there to keep it.
        for org in await organization_repo.list_owned_by(self.db, user_id):
            if org.id in handled:
                continue
            other_owner = await member_repo.other_owner_id(
                self.db, organization_id=org.id, exclude_user_id=user_id
            )
            if other_owner is None:
                raise BadRequestError(
                    message="Cannot delete the sole owner of a shared organization; "
                    "transfer ownership or delete the organization first",
                    details={"user_id": user_id, "organization_id": org.id},
                )

    async def admin_update(
        self, user_id: UUID, user_in: UserUpdate, *, acting_admin_id: UUID
    ) -> User:
        """An app admin updating another user's row, refusing self-suspension.

        `is_active` is enforced on the very next request, so an admin flipping
        their own to false is signed out of a deployment they administer - and on
        a single-admin install that ends administration until somebody reaches a
        terminal (#941). An admin genuinely leaving does it through another admin,
        which is also what keeps the audit trail readable.

        Only `is_active` is guarded because it is the only privilege this schema
        carries: `is_app_admin` is not a `UserUpdate` field - the one global
        privilege is granted by CLI, never over a surface a request can reach - so
        there is no self-demotion here to refuse.
        """
        if user_id == acting_admin_id and user_in.is_active is False:
            raise AuthorizationError(
                message="You cannot suspend your own account; ask another app admin to."
            )
        return await self.update(user_id, user_in)

    async def admin_delete(self, user_id: UUID, *, acting_admin_id: UUID) -> User:
        """An app admin deleting a user, refusing self-deletion.

        Deleting your own row takes the account and its conversations with it, and
        on a single-admin install leaves the deployment with no administrator (#941).
        Because `is_app_admin` cannot be cleared over the API, the set of app admins
        only ever shrinks by deletion - so refusing self-deletion is what keeps the
        last admin from being the one removed: any other admin deleting the *last*
        one would have to be deleting themselves.
        """
        if user_id == acting_admin_id:
            raise AuthorizationError(
                message="You cannot delete your own account; ask another app admin to."
            )
        return await self.delete(user_id)

    async def issue_password_reset_token(self, email: str) -> tuple[User, str] | None:
        """Returns None (not raises) to avoid leaking whether the email is registered."""
        user = await user_repo.get_by_email(self.db, email)
        if user is None or not user.is_active:
            return None
        token = create_password_reset_token(subject=str(user.id))
        return user, token

    async def confirm_password_reset(self, token: str, new_password: str) -> User:
        payload = verify_special_token(token, expected_type="password_reset")
        if payload is None or "sub" not in payload:
            raise AuthenticationError(message="Reset link is invalid or has expired")
        try:
            user_id = UUID(str(payload["sub"]))
        except (TypeError, ValueError) as exc:
            raise AuthenticationError(message="Reset link is invalid or has expired") from exc

        user = await self.get_by_id(user_id)
        if not user.is_active:
            raise AuthenticationError(message="Account is disabled")

        await user_repo.update(
            self.db,
            db_user=user,
            update_data={
                "hashed_password": await asyncio.to_thread(get_password_hash, new_password)
            },
        )
        # Revoke any active sessions so a previously-issued refresh token cannot
        # outlive a password reset. The current request returns no tokens - the
        # user must log in again.
        await session_repo.deactivate_all_user_sessions(self.db, user.id)
        return user

    async def issue_magic_link_token(
        self, email: str, *, return_to: str | None = None
    ) -> tuple[User, str] | None:
        user = await user_repo.get_by_email(self.db, email)
        if user is None or not user.is_active:
            return None
        token = create_magic_link_token(subject=str(user.id), return_to=return_to)
        return user, token

    async def consume_magic_link_token(self, token: str) -> tuple[User, str | None]:
        """The account the link is for, and where it was headed.

        Caller is responsible for minting access/refresh tokens for the returned
        user. The return path comes back rather than being applied here: it is
        the client that navigates, and `postSignInDestination` on that side is
        the one place deciding whether a path is safe to honour - the same
        judgement for a password login, an OAuth callback and this (#1214).
        """
        payload = verify_special_token(token, expected_type="magic_link")
        if payload is None or "sub" not in payload:
            raise AuthenticationError(message="Magic link is invalid or has expired")
        try:
            user_id = UUID(str(payload["sub"]))
        except (TypeError, ValueError) as exc:
            raise AuthenticationError(message="Magic link is invalid or has expired") from exc

        user = await self.get_by_id(user_id)
        if not user.is_active:
            raise AuthenticationError(message="Account is disabled")
        claimed = payload.get("rt")
        return user, claimed if isinstance(claimed, str) else None
