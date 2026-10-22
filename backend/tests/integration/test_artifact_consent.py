"""A page owner's consent to share its data, on real rows (#1974).

`tests/test_artifact_consent.py` and `tests/test_artifact_consent_actions.py` hold the
decisions with the database stubbed; these prove them where only a real database
can: the consent a publish starts with read back from the rows before it, the
audience's version picked by the partial index's query, a withdrawal voiding every
consent by its cut-off, pruning keeping what the audience is served, and the CHECK
holding a consented row to a membership.

The page belongs to Olga, a Member who reads the orders table by a grant - so the
roles that read every table (Owner, Admin, Builder, Operator) are someone else, and
whom the page's data reaches is the consent's to decide.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.artifact import Artifact, ArtifactMediaType, ArtifactVersion
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel, Visibility
from app.repositories import artifact_repo, resource_grant_repo
from app.schemas.artifact import (
    ArtifactAutoConsentUpdate,
    ArtifactConsentCreate,
    ArtifactPublicLinkUpdate,
    BindingRequest,
)
from app.schemas.virtual_table import TableRead
from app.services import artifact as artifacts
from app.services.access import ARTIFACT, TABLE
from app.services.artifact import ArtifactService
from app.services.artifact_consent import AUTO_CONSENT_WORDING
from app.services.file_storage import LocalFileStorage
from app.services.virtual_tables import VirtualTableService
from tests.integration.virtual_table_support import (
    cid,
    ctx_for,
    insert_rows,
    make_org,
    make_user,
    orders_table,
)

pytestmark = pytest.mark.anyio

READ = frozenset({"read"})
CUSTOMERS = {"customer": "Customer"}
WIDER = {"customer": "Customer", "quantity": "Quantity"}


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[LocalFileStorage]:
    local = LocalFileStorage(tmp_path)
    with (
        patch("app.services.artifact.get_file_storage", return_value=local),
        patch("app.services.file_storage.get_file_storage", return_value=local),
    ):
        yield local


@dataclass
class _World:
    db: AsyncSession
    org: Organization
    olga: AuthContext
    agent: Agent
    table: TableRead
    page_id: uuid.UUID | None = None

    @property
    def service(self) -> ArtifactService:
        return ArtifactService(self.db)

    async def member(
        self,
        role: str = "member",
        *,
        page: GrantLevel | None = None,
        reads_table: bool = False,
    ) -> AuthContext:
        user = await make_user(self.db)
        self.db.add(OrganizationMember(organization_id=self.org.id, user_id=user.id, role=role))
        await self.db.flush()
        ctx = AuthContext(user_id=user.id, organization_id=self.org.id, role=role)
        if page is not None:
            assert self.page_id is not None
            await self._grant(ctx, ARTIFACT.key, self.page_id, page)
        if reads_table:
            await self._grant(ctx, TABLE.key, self.table.id, GrantLevel.READ)
        return ctx

    async def _grant(
        self, ctx: AuthContext, resource_type: str, resource_id: uuid.UUID, level: GrantLevel
    ) -> None:
        assert ctx.user_id is not None
        await resource_grant_repo.upsert(
            self.db,
            organization_id=self.org.id,
            subject_user_id=ctx.user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            level=level,
        )

    async def publish(
        self,
        body: str,
        *,
        fields: dict[str, str] | None = CUSTOMERS,
        by: AuthContext | None = None,
        stand_in: AuthContext | None = None,
    ) -> artifacts.PublishedArtifact:
        """Olga's run publishes `body`, bound to the orders table unless `fields` is None.

        `by` is the member behind the run, Olga unless said otherwise; `stand_in` the
        identity a publish is checked as, which is `by` unless said otherwise.
        """
        person = by or self.olga
        published = await artifacts.publish_with(
            self.db,
            organization_id=self.org.id,
            agent_id=self.agent.id,
            owner_user_id=(stand_in or person).user_id,
            run_id=None,
            name="pipeline",
            title="Pipeline",
            media_type=ArtifactMediaType.HTML,
            data=body.encode(),
            bindings={} if fields is None else {"orders": self.query(fields)},
            run_person=person.user_id,
            table_grants={self.table.id: READ},
        )
        self.page_id = published.artifact_id
        return published

    def query(self, fields: dict[str, str]) -> BindingRequest:
        return BindingRequest(table=self.table.id, fields=fields)

    async def version(self, number: int) -> ArtifactVersion:
        assert self.page_id is not None
        found = await artifact_repo.get_version_by_number(self.db, self.page_id, number)
        assert found is not None
        return found

    async def confirm(self, ctx: AuthContext, number: int) -> None:
        assert self.page_id is not None
        version = await self.version(number)
        assert version.query_fingerprint is not None
        await self.service.confirm_data(
            ctx,
            self.page_id,
            version.id,
            ArtifactConsentCreate(fingerprint=version.query_fingerprint),
        )

    async def served(self, ctx: AuthContext) -> tuple[int | None, str]:
        """The version `ctx` opens, and what its data says: `ok` or why not."""
        assert self.page_id is not None
        try:
            view = await self.service.view(ctx, self.page_id)
        except NotFoundError as refused:
            return None, str((refused.details or {}).get("reason"))
        data = await self.service.data(ctx, self.page_id, view.version.id)
        binding = data.bindings["orders"]
        return view.version.number, binding.status if binding.status == "ok" else str(
            binding.reason
        )

    async def share_with_everyone(self) -> None:
        assert self.page_id is not None
        page = await artifact_repo.get(self.db, self.page_id, organization_id=self.org.id)
        assert page is not None
        page.visibility = Visibility.ORG.value
        await self.db.flush()


async def _world(db: AsyncSession) -> _World:
    boss = await make_user(db)
    org = await make_org(db, owner=boss)
    tables = VirtualTableService(db)
    table = await orders_table(tables, ctx_for(boss, org))
    await insert_rows(db, table, [{cid(table, "Customer"): "Ann", cid(table, "Quantity"): 3}])
    olga_user = await make_user(db)
    db.add(OrganizationMember(organization_id=org.id, user_id=olga_user.id, role="member"))
    await db.flush()
    olga = AuthContext(user_id=olga_user.id, organization_id=org.id, role="member")
    agent = Agent(
        organization_id=org.id,
        name="Reporter",
        created_by_user_id=olga_user.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
    )
    db.add(agent)
    await db.flush()
    await resource_grant_repo.upsert(
        db,
        organization_id=org.id,
        subject_user_id=olga_user.id,
        resource_type=TABLE.key,
        resource_id=table.id,
        level=GrantLevel.READ,
    )
    return _World(db, org, olga, agent, table)


async def _actions(db: AsyncSession, page_id: uuid.UUID) -> list[tuple[str, dict]]:
    rows = await db.execute(
        select(AppAdminAuditLog.action, AppAdminAuditLog.details)
        .where(AppAdminAuditLog.target_id == str(page_id))
        .order_by(AppAdminAuditLog.seq)
    )
    return [(action, details or {}) for action, details in rows.tuples()]


class TestTheConsentAPublishStartsWith:
    async def test_a_page_without_bindings_needs_none(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)

        published = await world.publish("<p>plain</p>", fields=None)

        version = await world.version(1)
        assert (published.consent.value, version.consent_state) == ("not_needed", "not_needed")
        assert version.query_fingerprint is None
        assert version.published_by_user_id == world.olga.user_id
        assert version.published_by_membership_id is not None

    async def test_a_bound_page_waits_for_its_owner(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)

        published = await world.publish("<p>v1</p>")

        assert published.consent.value == "pending"
        assert published.audience_version is None
        assert (await world.version(1)).query_fingerprint is not None

    async def test_a_republish_with_the_consented_queries_is_consented_automatically(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        await world.confirm(world.olga, 1)

        same = await world.publish("<p>v2</p>")
        wider = await world.publish("<p>v3</p>", fields=WIDER)

        two = await world.version(2)
        assert (same.consent.value, two.consent_automatic) == ("consented", True)
        assert two.consented_by_membership_id == (await world.version(1)).consented_by_membership_id
        assert (wider.consent.value, wider.audience_version) == ("pending", 2)

    async def test_the_owner_s_own_run_is_consented_with_auto_consent_on(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        await world.service.set_auto_consent(
            world.olga,
            published.artifact_id,
            ArtifactAutoConsentUpdate(enabled=True, confirmed=AUTO_CONSENT_WORDING),
        )

        wider = await world.publish("<p>v2</p>", fields=WIDER)

        assert wider.consent.value == "consented"
        assert (await world.version(2)).consent_automatic is True
        actions = [action for action, _ in await _actions(db, published.artifact_id)]
        assert "artifact.auto_consent_changed" in actions
        assert actions[-1] == "artifact.data_consented"

    @pytest.mark.security
    async def test_auto_consent_is_decided_by_the_run_s_person_never_the_stand_in(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """A run checked as the page's owner but acting for an editor is the editor's."""
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        await world.service.set_auto_consent(
            world.olga,
            published.artifact_id,
            ArtifactAutoConsentUpdate(enabled=True, confirmed=AUTO_CONSENT_WORDING),
        )
        editor = await world.member(page=GrantLevel.EDIT, reads_table=True)

        theirs = await world.publish("<p>v2</p>", fields=WIDER, by=editor, stand_in=world.olga)

        assert theirs.consent.value == "pending"
        assert (await world.version(2)).published_by_user_id == editor.user_id


class TestConfirming:
    async def test_the_owner_s_confirm_shares_the_data_with_the_audience(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        await world.share_with_everyone()
        reader = await world.member(role="viewer")
        assert await world.served(reader) == (None, "not_available_yet")

        await world.confirm(world.olga, 1)

        assert await world.served(reader) == (1, "ok")
        [(action, details)] = [
            entry
            for entry in await _actions(db, published.artifact_id)
            if entry[0] == "artifact.data_consented"
        ]
        assert details["automatic"] is False
        assert "for_owner" not in details

    @pytest.mark.security
    async def test_an_admin_confirms_for_the_owner(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        admin = await world.member(role="admin")

        await world.confirm(admin, 1)

        version = await world.version(1)
        assert version.consented_by_user_id == admin.user_id
        member = await db.scalar(
            select(OrganizationMember.id).where(
                OrganizationMember.user_id == world.olga.user_id,
                OrganizationMember.organization_id == world.org.id,
            )
        )
        assert version.consented_by_membership_id == member
        details = (await _actions(db, published.artifact_id))[-1][1]
        assert details["for_owner"] == str(world.olga.user_id)

    @pytest.mark.security
    async def test_an_editor_by_grant_cannot_confirm(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        editor = await world.member(page=GrantLevel.EDIT, reads_table=True)

        with pytest.raises(AuthorizationError):
            await world.confirm(editor, 1)

        assert (await world.version(1)).consent_state == "pending"

    @pytest.mark.security
    async def test_a_confirm_after_a_newer_publish_is_a_conflict(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        shown = await world.version(1)
        await world.publish("<p>v2</p>", fields=WIDER)

        with pytest.raises(ConcurrentChangeError):
            await world.service.confirm_data(
                world.olga,
                published.artifact_id,
                shown.id,
                ArtifactConsentCreate(fingerprint=shown.query_fingerprint or ""),
            )

    @pytest.mark.security
    async def test_an_owner_who_lost_read_on_a_table_cannot_share_it(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        await resource_grant_repo.revoke(
            db,
            organization_id=world.org.id,
            subject_user_id=world.olga.subject_id,
            resource_type=TABLE.key,
            resource_id=world.table.id,
        )
        admin = await world.member(role="admin")

        with pytest.raises(AuthorizationError, match="can't read 1 of the tables"):
            await world.confirm(admin, 1)


class TestWithdrawing:
    @pytest.mark.security
    async def test_a_withdrawal_voids_every_consent_and_the_audience_keeps_the_page(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """The audience is not handed an older version's data: it keeps its version and
        every binding awaits consent."""
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        await world.share_with_everyone()
        await world.confirm(world.olga, 1)
        await world.publish("<p>v2</p>")  # consented automatically: same queries
        reader = await world.member(role="viewer")
        editor = await world.member(page=GrantLevel.EDIT)
        assert await world.served(reader) == (2, "ok")

        await world.service.withdraw_consent(editor, published.artifact_id)

        assert await world.served(reader) == (2, "awaiting_consent")
        listed = await world.service.versions(world.olga, published.artifact_id)
        assert [item.consent_state for item in listed.items] == ["withdrawn", "withdrawn"]
        # Nothing carries forward from a consent that no longer holds.
        again = await world.publish("<p>v3</p>")
        assert again.consent.value == "pending"
        assert (await _actions(db, published.artifact_id))[-1][0] != "artifact.data_consented"

    @pytest.mark.security
    async def test_a_reader_cannot_withdraw(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        reader = await world.member(page=GrantLevel.READ)

        with pytest.raises(NotFoundError):
            await world.service.withdraw_consent(reader, published.artifact_id)


class TestWhoIsServedWhichVersion:
    @pytest.mark.security
    async def test_the_audience_keeps_the_consented_version_while_a_newer_one_waits(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        await world.share_with_everyone()
        await world.confirm(world.olga, 1)
        await world.publish("<p>v2</p>", fields=WIDER)
        pending = await world.version(2)
        reader = await world.member(role="viewer")
        page_id = published.artifact_id

        assert await world.served(reader) == (1, "ok")
        assert [item.number for item in (await world.service.versions(reader, page_id)).items] == [
            1
        ]
        with pytest.raises(NotFoundError):
            await world.service.view(reader, page_id, version_id=pending.id)
        with pytest.raises(NotFoundError):
            await world.service.data(reader, page_id, pending.id)
        detail = await world.service.read(reader, page_id)
        assert detail.current_version is not None
        assert (detail.current_version.number, detail.consent) == (1, None)
        listing = await world.service.list_readable(reader)
        assert [item.current_version.number for item in listing.items if item.current_version] == [
            1
        ]

    @pytest.mark.security
    @pytest.mark.parametrize("role", ["builder", "operator", "admin"])
    async def test_the_roles_that_read_every_table_see_the_latest_with_its_data(
        self, db: AsyncSession, storage: LocalFileStorage, role: str
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")

        assert await world.served(await world.member(role=role)) == (1, "ok")

    @pytest.mark.security
    async def test_an_editor_sees_the_latest_page_without_unconsented_data(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        editor = await world.member(page=GrantLevel.EDIT)

        assert await world.served(editor) == (1, "awaiting_consent")
        detail = await world.service.read(editor, published.artifact_id)
        assert detail.consent is not None
        assert (detail.consent.state, detail.consent.audience_version) == ("pending", None)

    async def test_the_owner_sees_the_latest_with_its_data(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")

        assert await world.served(world.olga) == (1, "ok")


class TestThePublicLink:
    @pytest.mark.security
    async def test_an_unpinned_link_shows_the_audience_s_version_and_refuses_a_pending_pin(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        await world.confirm(world.olga, 1)
        await world.publish("<p>v2</p>", fields=WIDER)
        page_id = published.artifact_id
        detail = await world.service.set_public_link(world.olga, page_id)
        key = (detail.public_url or "").rsplit("/", 1)[1]

        opened = await world.service.public_view(key)

        assert opened.view is not None
        assert opened.view.version.number == 1
        with pytest.raises(BadRequestError):
            await world.service.update_public_link(
                world.olga,
                page_id,
                ArtifactPublicLinkUpdate(pinned_version_id=(await world.version(2)).id),
            )

    async def test_a_page_with_nothing_consented_has_no_public_page(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        detail = await world.service.set_public_link(world.olga, published.artifact_id)

        with pytest.raises(NotFoundError):
            await world.service.public_view((detail.public_url or "").rsplit("/", 1)[1])


class TestPruning:
    async def test_the_version_the_audience_is_served_outlives_the_window(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        with (
            patch.object(artifacts.settings, "ARTIFACT_MAX_VERSIONS", 2),
            patch("app.services.artifact.spawn_after_commit"),
        ):
            published = await world.publish("<p>v1</p>")
            await world.confirm(world.olga, 1)
            for number in range(2, 5):
                await world.publish(f"<p>v{number}</p>", fields=WIDER)

        rows = await db.execute(
            select(ArtifactVersion.number)
            .where(ArtifactVersion.artifact_id == published.artifact_id)
            .order_by(ArtifactVersion.number)
        )
        assert list(rows.scalars()) == [1, 3, 4]


class TestTheConstraint:
    async def test_a_consented_row_must_name_the_membership(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        version = await world.version(1)
        version.consent_state = "consented"

        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_an_unknown_state_is_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        version = await world.version(1)
        version.consent_state = "maybe"

        with pytest.raises(IntegrityError):
            await db.flush()


class TestLockedRowIsFresh:
    async def test_the_lock_returns_what_another_session_just_wrote(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """A withdrawal committed since this session loaded the page is seen under the lock."""
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        page = await db.get(Artifact, published.artifact_id)
        assert page is not None and page.auto_consent is False
        await db.execute(update(Artifact).where(Artifact.id == page.id).values(auto_consent=True))

        locked = await artifact_repo.lock(db, page.id)

        assert locked is page
        assert page.auto_consent is True
