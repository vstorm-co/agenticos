"""An impersonation is a session an administrator holds, and it can be ended.

The token `POST /admin/users/{id}/impersonate` mints names a row in `sessions`,
and every request made with it is refused the moment that row is gone, ended or
expired. Most of what is asserted here is a refusal, because that is the whole
of the change: before it, the token was good for its hour whatever anybody did
(#1044).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.audit import current_impersonator, set_impersonator
from app.core.exceptions import AuthenticationError, BadRequestError, NotFoundError
from app.core.security import create_access_token, verify_token
from app.db.models.audit_log import AppAdminAuditLog
from app.repositories import session as session_repo
from app.services import impersonation as module
from app.services.email.service import EmailKey
from app.services.impersonation import WINDOW, ImpersonationService, current_impersonation
from app.services.session import SessionService, hash_token

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean_context() -> Iterator[None]:
    """Both context variables outlive a test that set them; neither may leak."""
    yield
    set_impersonator(None)
    module._active.set(None)


def _user(*, email: str, is_active: bool = True) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = email
    user.full_name = None
    user.is_active = is_active
    return user


def _db() -> MagicMock:
    """A session whose `add` is a plain call, so the audit entry can be read back."""
    db = MagicMock()
    db.flush = AsyncMock()
    return db


def _row(
    *,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    impersonator_id: uuid.UUID | None,
    token: str,
    is_active: bool = True,
    expires_at: datetime | None = None,
) -> MagicMock:
    row = MagicMock()
    row.id = session_id
    row.user_id = user_id
    row.impersonator_user_id = impersonator_id
    row.refresh_token_hash = hash_token(token)
    row.is_active = is_active
    row.expires_at = expires_at or datetime.now(UTC) + timedelta(minutes=30)
    return row


def _created_row(**kwargs: Any) -> MagicMock:
    """What `session_repo.create` would hand back for the arguments it was given."""
    row = MagicMock()
    row.id = kwargs["session_id"]
    row.user_id = kwargs["user_id"]
    row.impersonator_user_id = kwargs["impersonator_user_id"]
    row.refresh_token_hash = kwargs["refresh_token_hash"]
    row.expires_at = kwargs["expires_at"]
    row.is_active = True
    return row


def _audit_entries(db: MagicMock) -> list[AppAdminAuditLog]:
    return [
        call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], AppAdminAuditLog)
    ]


class TestStarting:
    @pytest.fixture
    def target(self) -> MagicMock:
        return _user(email="customer@example.com")

    @pytest.fixture
    def admin(self) -> MagicMock:
        return _user(email="admin@example.com")

    @pytest.fixture
    def repos(self, target: MagicMock) -> Iterator[dict[str, AsyncMock]]:
        create = AsyncMock(side_effect=lambda db, **kwargs: _created_row(**kwargs))
        with (
            patch("app.repositories.user.get_by_id", new=AsyncMock(return_value=target)) as users,
            patch("app.repositories.session.create", new=create),
            patch(
                "app.repositories.deployment_settings.get", new=AsyncMock(return_value=None)
            ) as settings,
            patch.object(module, "spawn_after_commit") as spawn,
        ):
            yield {"users": users, "create": create, "settings": settings, "spawn": spawn}

    async def test_the_token_names_its_session_and_the_session_holds_the_token(
        self, repos: dict[str, AsyncMock], admin: MagicMock, target: MagicMock
    ) -> None:
        """The two halves that make an impersonation endable: the token says which
        row it is, and the row says which token it was minted for."""
        response = await ImpersonationService(_db()).start(
            admin=admin, target_id=target.id, ip_address="1.2.3.4", user_agent="Chrome"
        )

        payload = verify_token(response.access_token)
        assert payload is not None
        assert payload["sub"] == str(target.id)
        assert payload["act"] == str(admin.id)
        assert payload["sid"] == str(response.session_id)

        written = repos["create"].await_args.kwargs
        assert written["session_id"] == response.session_id
        assert written["user_id"] == target.id
        assert written["impersonator_user_id"] == admin.id
        assert written["refresh_token_hash"] == hash_token(response.access_token)
        assert written["device_name"] == "Chrome"

    async def test_the_window_is_an_hour_on_the_row_and_on_the_token(
        self, repos: dict[str, AsyncMock], admin: MagicMock, target: MagicMock
    ) -> None:
        before = datetime.now(UTC)
        response = await ImpersonationService(_db()).start(
            admin=admin, target_id=target.id, ip_address=None, user_agent=None
        )

        assert response.expires_in == int(WINDOW.total_seconds())
        assert before + WINDOW <= response.expires_at <= datetime.now(UTC) + WINDOW
        assert repos["create"].await_args.kwargs["expires_at"] == response.expires_at

    async def test_the_start_is_audited_with_the_session_and_its_expiry(
        self, repos: dict[str, AsyncMock], admin: MagicMock, target: MagicMock
    ) -> None:
        """An operator answering "who was in this account, and until when" reads
        the entry, not the row - the row is deactivated and paged out."""
        db = _db()
        response = await ImpersonationService(db).start(
            admin=admin, target_id=target.id, ip_address="1.2.3.4", user_agent=None
        )

        (entry,) = _audit_entries(db)
        assert entry.action == "admin.user.impersonate"
        assert entry.actor_user_id == admin.id
        assert entry.impersonator_user_id is None
        assert entry.target_id == str(target.id)
        assert entry.details == {
            "target_email": target.email,
            "session_id": str(response.session_id),
            "expires_at": response.expires_at.isoformat(),
        }
        assert entry.ip_address == "1.2.3.4"

    async def test_acting_as_yourself_is_refused(
        self, repos: dict[str, AsyncMock], target: MagicMock
    ) -> None:
        """Nobody acting as anybody; the row would name the same person twice."""
        with pytest.raises(BadRequestError):
            await ImpersonationService(_db()).start(
                admin=target, target_id=target.id, ip_address=None, user_agent=None
            )

        repos["create"].assert_not_awaited()

    async def test_a_suspended_account_cannot_be_impersonated(
        self, repos: dict[str, AsyncMock], admin: MagicMock, target: MagicMock
    ) -> None:
        """Every request would refuse the disabled subject anyway; refusing at the
        start leaves no credential that only looks like one."""
        target.is_active = False

        with pytest.raises(BadRequestError) as refused:
            await ImpersonationService(_db()).start(
                admin=admin, target_id=target.id, ip_address=None, user_agent=None
            )

        assert refused.value.details == {"user_id": target.id}
        repos["create"].assert_not_awaited()

    async def test_an_unknown_target_is_not_found(
        self, repos: dict[str, AsyncMock], admin: MagicMock
    ) -> None:
        repos["users"].return_value = None

        with pytest.raises(NotFoundError):
            await ImpersonationService(_db()).start(
                admin=admin, target_id=uuid.uuid4(), ip_address=None, user_agent=None
            )

    async def test_a_nested_impersonation_names_the_human_who_started_the_chain(
        self, repos: dict[str, AsyncMock], target: MagicMock
    ) -> None:
        """A impersonates app-admin B, whose session impersonates C. The token and
        the row must keep naming A, not B - or the chain launders A out of the
        audit trail one hop at a time (#943)."""
        a = uuid.uuid4()
        b = _user(email="b@example.com")
        set_impersonator(a)

        db = _db()
        response = await ImpersonationService(db).start(
            admin=b, target_id=target.id, ip_address=None, user_agent=None
        )

        payload = verify_token(response.access_token)
        assert payload is not None
        assert payload["act"] == str(a)
        assert response.impersonated_by == str(a)
        assert repos["create"].await_args.kwargs["impersonator_user_id"] == a
        (entry,) = _audit_entries(db)
        assert (entry.actor_user_id, entry.impersonator_user_id) == (b.id, a)


class TestTellingTheTarget:
    """A deployment policy, off by default - never a default of the code."""

    @pytest.fixture
    def admin(self) -> MagicMock:
        return _user(email="admin@example.com")

    @pytest.fixture
    def target(self) -> MagicMock:
        target = _user(email="customer@example.com")
        target.full_name = "Cust Omer"
        return target

    @pytest.fixture
    def start(self, admin: MagicMock, target: MagicMock) -> Any:
        async def _start(settings_row: Any) -> MagicMock:
            create = AsyncMock(side_effect=lambda db, **kwargs: _created_row(**kwargs))
            with (
                patch("app.repositories.user.get_by_id", new=AsyncMock(return_value=target)),
                patch("app.repositories.session.create", new=create),
                patch(
                    "app.repositories.deployment_settings.get",
                    new=AsyncMock(return_value=settings_row),
                ),
                patch.object(module, "spawn_after_commit") as spawn,
            ):
                await ImpersonationService(_db()).start(
                    admin=admin, target_id=target.id, ip_address=None, user_agent=None
                )
            return spawn

        return _start

    async def test_an_unconfigured_deployment_tells_nobody(self, start: Any) -> None:
        spawn = await start(None)

        spawn.assert_not_called()

    async def test_a_deployment_that_has_not_turned_it_on_tells_nobody(self, start: Any) -> None:
        spawn = await start(MagicMock(notify_impersonated_users=False, app_name=None))

        spawn.assert_not_called()

    async def test_the_email_goes_out_after_the_commit_when_turned_on(
        self, start: Any, admin: MagicMock, target: MagicMock
    ) -> None:
        """After the commit, so a start that failed to record itself tells nobody;
        under the deployment's own name, so the mail does not greet somebody in
        the name of a product the console stopped showing."""
        spawn = await start(MagicMock(notify_impersonated_users=True, app_name="Acme Agents"))

        spawn.assert_called_once()
        notice = spawn.call_args.args[1]
        send = AsyncMock()
        with patch.object(module, "get_email_service", return_value=MagicMock(send=send)):
            await notice

        send.assert_awaited_once_with(
            key=EmailKey.IMPERSONATION_NOTICE,
            to=target.email,
            context={"name": "Cust Omer", "admin_email": admin.email, "app_name": "Acme Agents"},
        )

    async def test_a_nested_impersonation_names_the_human_not_the_account_between(
        self, admin: MagicMock, target: MagicMock
    ) -> None:
        """A acts as app-admin B and, as B, impersonates C. The notice C gets names
        A - who the row, the token and the audit trail name - not B."""
        a = _user(email="a@example.com")
        set_impersonator(a.id)
        accounts = {target.id: target, a.id: a}
        create = AsyncMock(side_effect=lambda db, **kwargs: _created_row(**kwargs))
        with (
            patch(
                "app.repositories.user.get_by_id",
                new=AsyncMock(side_effect=lambda db, user_id: accounts[user_id]),
            ),
            patch("app.repositories.session.create", new=create),
            patch(
                "app.repositories.deployment_settings.get",
                new=AsyncMock(
                    return_value=MagicMock(notify_impersonated_users=True, app_name=None)
                ),
            ),
            patch.object(module, "spawn_after_commit") as spawn,
        ):
            await ImpersonationService(_db()).start(
                admin=admin, target_id=target.id, ip_address=None, user_agent=None
            )

        send = AsyncMock()
        with patch.object(module, "get_email_service", return_value=MagicMock(send=send)):
            await spawn.call_args.args[1]

        assert send.await_args.kwargs["context"]["admin_email"] == "a@example.com"

    async def test_a_notice_that_cannot_be_sent_raises_nothing(self, start: Any) -> None:
        """The impersonation has already started and been recorded; a mail server
        that is down is a log line, not a second failure."""
        spawn = await start(MagicMock(notify_impersonated_users=True, app_name=None))
        notice = spawn.call_args.args[1]
        send = AsyncMock(side_effect=RuntimeError("smtp down"))

        with patch.object(module, "get_email_service", return_value=MagicMock(send=send)):
            await notice


class TestVerifying:
    """Every request carrying `act` is bound to its row, or refused."""

    def setup_method(self) -> None:
        self.admin_id = uuid.uuid4()
        self.target_id = uuid.uuid4()
        self.session_id = uuid.uuid4()
        self.token = create_access_token(
            str(self.target_id), act=str(self.admin_id), sid=str(self.session_id)
        )
        self.payload = verify_token(self.token) or {}

    def _live_row(self, **overrides: Any) -> MagicMock:
        row = _row(
            session_id=self.session_id,
            user_id=self.target_id,
            impersonator_id=self.admin_id,
            token=self.token,
        )
        for name, value in overrides.items():
            setattr(row, name, value)
        return row

    def _admin(self, *, is_active: bool = True, is_app_admin: bool = True) -> MagicMock:
        admin = _user(email="admin@example.com", is_active=is_active)
        admin.id = self.admin_id
        admin.is_app_admin = is_app_admin
        return admin

    async def _verify(
        self,
        row: MagicMock | None,
        *,
        payload: dict[str, Any] | None = None,
        admin: MagicMock | None = None,
    ) -> Any:
        with (
            patch("app.repositories.session.get_by_id", new=AsyncMock(return_value=row)),
            patch(
                "app.repositories.user.get_by_id",
                new=AsyncMock(return_value=self._admin() if admin is None else admin),
            ),
        ):
            return await ImpersonationService(_db()).verify(
                payload=payload if payload is not None else self.payload,
                token=self.token,
                subject=str(self.target_id),
            )

    async def test_an_ordinary_token_costs_no_query_and_clears_the_context(self) -> None:
        """A request with no `act` is most requests; it must not pay for a lookup,
        and it must not inherit an impersonation a previous task left behind."""
        set_impersonator(uuid.uuid4())
        plain = verify_token(create_access_token("somebody")) or {}

        with patch("app.repositories.session.get_by_id", new=AsyncMock()) as lookup:
            result = await ImpersonationService(_db()).verify(
                payload=plain, token="irrelevant", subject="somebody"
            )

        assert result is None
        lookup.assert_not_awaited()
        assert current_impersonator() is None
        assert current_impersonation() is None

    async def test_a_live_impersonation_is_bound_to_its_row(self) -> None:
        row = self._live_row()

        active = await self._verify(row)

        assert active is not None
        assert (active.session_id, active.user_id, active.impersonator_id) == (
            self.session_id,
            self.target_id,
            self.admin_id,
        )
        assert active.expires_at == row.expires_at
        assert current_impersonation() == active
        assert current_impersonator() == self.admin_id

    async def test_a_token_minted_before_impersonations_were_sessions_is_refused(self) -> None:
        """`act` with no `sid` is exactly the unendable credential this replaces."""
        legacy = verify_token(create_access_token(str(self.target_id), act=str(self.admin_id)))
        assert legacy is not None

        with pytest.raises(AuthenticationError):
            await self._verify(self._live_row(), payload=legacy)

    async def test_an_ended_impersonation_is_refused(self) -> None:
        """The whole point: a token whose row was deactivated - by the
        administrator, by "sign out everywhere", by a password reset - is refused
        on the very next request rather than served for the rest of its hour."""
        with pytest.raises(AuthenticationError, match="ended"):
            await self._verify(self._live_row(is_active=False))

        assert current_impersonation() is None

    async def test_an_expired_impersonation_is_refused_before_the_token_is(self) -> None:
        """The row's window, not the token's `exp`, is what ends it - so a row
        somebody shortened is honoured without reissuing anything."""
        with pytest.raises(AuthenticationError, match="ended"):
            await self._verify(self._live_row(expires_at=datetime.now(UTC) - timedelta(seconds=1)))

    async def test_a_row_that_no_longer_exists_is_refused(self) -> None:
        """A deleted administrator's rows cascade away; their impersonation ends
        with them rather than surviving as a token nobody can trace."""
        with pytest.raises(AuthenticationError, match="ended"):
            await self._verify(None)

    async def test_a_row_held_by_another_administrator_is_refused(self) -> None:
        with pytest.raises(AuthenticationError, match="ended"):
            await self._verify(self._live_row(impersonator_user_id=uuid.uuid4()))

    async def test_a_row_for_another_account_is_refused(self) -> None:
        with pytest.raises(AuthenticationError, match="ended"):
            await self._verify(self._live_row(user_id=uuid.uuid4()))

    async def test_a_suspended_administrator_stops_acting_as_anybody(self) -> None:
        """`is_active` is enforced on the administrator's own token by the subject
        check, which an impersonation token never reaches; without this a
        suspended administrator keeps acting as somebody else for the hour."""
        with pytest.raises(AuthenticationError, match="ended"):
            await self._verify(self._live_row(), admin=self._admin(is_active=False))

    async def test_a_demoted_administrator_stops_acting_as_anybody(self) -> None:
        with pytest.raises(AuthenticationError, match="ended"):
            await self._verify(self._live_row(), admin=self._admin(is_app_admin=False))

    async def test_a_token_carried_onto_another_session_is_refused(self) -> None:
        """The row holds the hash of the token it was minted for, so a `sid` pasted
        onto a different token - however its signature was obtained - binds to
        nothing."""
        other = create_access_token(
            str(self.target_id),
            expires_delta=timedelta(hours=2),
            act=str(self.admin_id),
            sid=str(self.session_id),
        )
        assert other != self.token

        with pytest.raises(AuthenticationError, match="ended"):
            await self._verify(self._live_row(refresh_token_hash=hash_token(other)))


class TestDescribing:
    async def test_an_ordinary_request_has_nothing_to_describe(self) -> None:
        assert await ImpersonationService(_db()).describe() is None

    async def test_a_live_impersonation_names_the_administrator_and_the_deadline(self) -> None:
        admin = _user(email="admin@example.com")
        admin.full_name = "Ada Min"
        active = module.ActiveImpersonation(
            session_id=uuid.uuid4(), user_id=uuid.uuid4(), impersonator_id=admin.id, expires_at=NOW
        )
        module._active.set(active)

        with patch("app.repositories.user.get_by_id", new=AsyncMock(return_value=admin)):
            described = await ImpersonationService(_db()).describe()

        assert described is not None
        assert described.session_id == active.session_id
        assert described.expires_at == NOW
        assert (described.impersonator.id, described.impersonator.email) == (admin.id, admin.email)
        assert described.impersonator.full_name == "Ada Min"


class TestEnding:
    async def test_a_request_that_is_nobody_acting_as_anybody_cannot_end_one(self) -> None:
        with (
            patch("app.repositories.session.deactivate", new=AsyncMock()) as deactivate,
            pytest.raises(BadRequestError),
        ):
            await ImpersonationService(_db()).end(ip_address=None)

        deactivate.assert_not_awaited()

    async def test_ending_closes_the_row_and_is_audited_as_the_administrator(self) -> None:
        """The same shape as the start - the administrator as the actor, the
        account as the target - rather than the account with somebody behind it,
        so the two entries read as one story."""
        admin_id, user_id, session_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        module._active.set(
            module.ActiveImpersonation(
                session_id=session_id, user_id=user_id, impersonator_id=admin_id, expires_at=NOW
            )
        )
        set_impersonator(admin_id)
        db = _db()

        with patch("app.repositories.session.deactivate", new=AsyncMock()) as deactivate:
            await ImpersonationService(db).end(ip_address="1.2.3.4")

        deactivate.assert_awaited_once_with(db, session_id)
        (entry,) = _audit_entries(db)
        assert entry.action == "admin.user.impersonation_ended"
        assert entry.actor_user_id == admin_id
        assert entry.impersonator_user_id is None
        assert (entry.target_type, entry.target_id) == ("user", str(user_id))
        assert entry.details == {"session_id": str(session_id)}
        assert entry.ip_address == "1.2.3.4"


class TestTheSessionMachinery:
    """What the rows themselves have to refuse and hide."""

    async def test_an_impersonation_is_not_a_refresh_token(self) -> None:
        """Its row is found by the hash of its access token, and a refresh minted
        from it would be a plain week-long session as the target - no `act`, no
        `sid`, the administrator laundered out of everything that follows."""
        row = _row(
            session_id=uuid.uuid4(), user_id=uuid.uuid4(), impersonator_id=uuid.uuid4(), token="t"
        )
        with (
            patch(
                "app.repositories.session.get_by_refresh_token_hash",
                new=AsyncMock(return_value=row),
            ),
            patch("app.repositories.session.update_last_used", new=AsyncMock()) as touched,
        ):
            assert await SessionService(AsyncMock()).validate_refresh_token("t") is None

        touched.assert_not_awaited()

    async def test_a_persons_own_session_still_refreshes(self) -> None:
        row = _row(session_id=uuid.uuid4(), user_id=uuid.uuid4(), impersonator_id=None, token="t")
        with (
            patch(
                "app.repositories.session.get_by_refresh_token_hash",
                new=AsyncMock(return_value=row),
            ),
            patch("app.repositories.session.update_last_used", new=AsyncMock()),
        ):
            assert await SessionService(AsyncMock()).validate_refresh_token("t") is row

    async def test_the_row_is_written_under_the_id_the_token_already_names(self) -> None:
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        session_id = uuid.uuid4()

        row = await session_repo.create(
            db,
            session_id=session_id,
            user_id=uuid.uuid4(),
            refresh_token_hash="h",
            expires_at=NOW,
            impersonator_user_id=uuid.uuid4(),
        )

        assert row.id == session_id

    @staticmethod
    async def _statement(query: Any) -> str:
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalars=lambda: MagicMock(all=list), scalar_one=lambda: 0)
        )
        await query(db)
        return str(db.execute.await_args.args[0])

    async def test_a_persons_devices_do_not_list_an_administrators_access(self) -> None:
        """Whether the person is told is the deployment's policy; a row in their
        devices list would decide it for them. The count and the "last seen" the
        admin drawer reads are narrowed the same way, so nobody reads as present
        who was not there."""
        listing = await self._statement(lambda db: session_repo.get_user_sessions(db, uuid.uuid4()))
        count = await self._statement(lambda db: session_repo.count_user_sessions(db, uuid.uuid4()))

        assert "sessions.impersonator_user_id IS NULL" in listing
        assert "sessions.impersonator_user_id IS NULL" in count

    async def test_signing_out_everywhere_ends_an_administrators_access_too(self) -> None:
        """Revocation is deliberately not narrowed: a password reset and "sign out
        everywhere" reach every row under the id, impersonations included."""
        revoke = await self._statement(
            lambda db: session_repo.deactivate_all_user_sessions(db, uuid.uuid4())
        )

        assert "impersonator_user_id" not in revoke
