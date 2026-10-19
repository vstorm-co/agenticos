"""A person's saved browser sign-ins: kept, handed to their browses, forgotten (#2129).

Two kinds of caller. A person, through `BrowserSignInService`, lists theirs and
forgets one - the API never returns what a sign-in holds, only which site it is
for and when it was last used. And a browse, through `load_for` and `remember`,
which run inside an agent run with no request around them and so open a session
of their own.

**Sealed under the person, not the organization.** It is their session on
somebody else's site; an organization's key opening it would make every admin
with database access able to sign in as them. Rows are still kept per
organization, because the browser it is handed to is the organization's.

**Which runs may use one is not decided here.** The browser asks only when the
run's audience says it acts as the person, privately - see
`RunAudience.browses_signed_in` - and this module answers for whoever it is
asked about.
"""

import logging
from collections.abc import Sequence
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.browser_sign_ins import SignIn
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.core.vault import VaultScope, is_key_version_available, seal, unseal
from app.db.models.browser_sign_in import BrowserSignIn
from app.db.session import get_db_context
from app.repositories import browser_sign_in as sign_in_repo

logger = logging.getLogger(__name__)


class BrowserSignInService:
    """What a person may do with their own saved sign-ins."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def mine(self, ctx: AuthContext) -> Sequence[BrowserSignIn]:
        """The caller's sign-ins in this organization. No permission: they are theirs."""
        return await sign_in_repo.list_for(
            self.db, organization_id=ctx.organization_id, user_id=ctx.subject_id
        )

    async def forget(self, ctx: AuthContext, sign_in_id: UUID) -> None:
        """Delete one of the caller's sign-ins; the next browse starts signed out there.

        Raises:
            NotFoundError: No such sign-in is the caller's - including one that
                is somebody else's, which is not theirs to learn exists.
        """
        row = await sign_in_repo.get(
            self.db,
            sign_in_id,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
        )
        if row is None:
            raise NotFoundError(message="Sign-in not found", details={"sign_in_id": sign_in_id})
        await sign_in_repo.delete(self.db, db_sign_in=row)


async def load_for(organization_id: UUID, user_id: UUID) -> list[SignIn]:
    """Every sign-in a browse acting as this person starts with, marked as used.

    A row sealed under a master key this deployment no longer has, or one that no
    longer reads as a sign-in, is skipped and logged rather than failing the
    browse: the browse is still worth running, signed out there.
    """
    async with get_db_context() as db:
        rows = await sign_in_repo.list_for(db, organization_id=organization_id, user_id=user_id)
        loaded: list[SignIn] = []
        used: list[UUID] = []
        for row in rows:
            if not is_key_version_available(row.secret_key_version):
                logger.warning("browser_sign_in_key_retired", extra={"sign_in_id": str(row.id)})
                continue
            plaintext = unseal(
                row.sealed_state, scope=VaultScope.user(user_id), key_version=row.secret_key_version
            )
            try:
                loaded.append(SignIn.model_validate_json(plaintext))
            except ValidationError:
                logger.warning("browser_sign_in_unreadable", extra={"sign_in_id": str(row.id)})
                continue
            used.append(row.id)
        if used:
            await sign_in_repo.mark_used(db, used)
    return loaded


async def remember(organization_id: UUID, user_id: UUID, sign_in: SignIn) -> None:
    """Keep a sign-in for this person, replacing their earlier one to the same site."""
    sealed = seal(sign_in.model_dump_json(), scope=VaultScope.user(user_id))
    async with get_db_context() as db:
        await sign_in_repo.save(
            db,
            organization_id=organization_id,
            user_id=user_id,
            site=sign_in.site,
            sealed_state=sealed.ciphertext,
            key_version=sealed.key_version,
        )
