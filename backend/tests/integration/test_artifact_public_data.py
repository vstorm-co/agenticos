"""The owner's consent to show a page's data to anyone with its link, on real rows (#1975).

The consent suite's world (`test_artifact_consent`): Olga's page, bound to the orders table,
whose members' consent is confirmed and whose public link is on, in an organization that
has switched public live data on. These prove who may give and take back the public
consent, what each refusal is, and every way it is voided - on rows, with the audit trail.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import set_impersonator
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.artifact import Artifact
from app.db.models.organization import OrganizationMember
from app.db.models.resource_grant import GrantLevel
from app.repositories import artifact_repo
from app.schemas.artifact import (
    ArtifactDetail,
    ArtifactOwnerUpdate,
    ArtifactPublicDataCreate,
    ArtifactPublicLinkUpdate,
)
from app.services.artifact_consent import owner_membership_id
from app.services.artifact_public_data import (
    ArtifactPublicDataService,
    audience_digest,
    public_data_holds,
    public_version,
)
from app.services.file_storage import LocalFileStorage
from tests.integration.test_artifact_consent import _actions, _World, _world, storage

pytestmark = pytest.mark.anyio

__all__ = ["storage"]

PASSWORD = "correct horse battery"
SITE = "https://docs.example.com"


@contextmanager
def impersonated() -> Iterator[None]:
    set_impersonator(uuid.uuid4())
    try:
        yield
    finally:
        set_impersonator(None)


class _Ready:
    """A world whose page is ready to be confirmed for its public link."""

    def __init__(self, world: _World, page_id: uuid.UUID) -> None:
        self.world = world
        self.page_id = page_id
        self.db = world.db

    @property
    def public(self) -> ArtifactPublicDataService:
        return ArtifactPublicDataService(self.db)

    async def page(self) -> Artifact:
        page = await artifact_repo.get(self.db, self.page_id, organization_id=self.world.org.id)
        assert page is not None
        return page

    async def fingerprint(self) -> str:
        version = await public_version(self.db, await self.page())
        assert version is not None and version.query_fingerprint is not None
        return version.query_fingerprint

    async def confirm(
        self, ctx: AuthContext, *, confirmed: bool = True, audience: str | None = None
    ) -> ArtifactDetail:
        return await self.public.confirm(
            ctx,
            self.page_id,
            ArtifactPublicDataCreate(
                fingerprint=await self.fingerprint(),
                audience_digest=audience or audience_digest(await self.page()),
                confirmed=confirmed,
            ),
        )

    async def holds(self) -> bool:
        page = await self.page()
        await self.db.refresh(self.world.org)
        return public_data_holds(
            page,
            await public_version(self.db, page),
            await owner_membership_id(self.db, page),
            self.world.org,
        )

    async def actions(self) -> list[str]:
        return [action for action, _ in await _actions(self.db, self.page_id)]

    async def voided(self) -> list[str]:
        return [
            str(details["reason"])
            for action, details in await _actions(self.db, self.page_id)
            if action == "artifact.public_data_voided"
        ]

    async def consented(self) -> bool:
        return (await self.page()).public_data_fingerprint is not None


async def _ready(db: AsyncSession, *, confirmed: bool = True) -> _Ready:
    world = await _world(db)
    published = await world.publish("<p>v1</p>")
    await world.confirm(world.olga, 1)
    await world.service.set_public_link(world.olga, published.artifact_id)
    world.org.public_live_data = True
    await db.flush()
    ready = _Ready(world, published.artifact_id)
    if confirmed:
        await ready.confirm(world.olga)
    return ready


class TestConfirming:
    async def test_the_owner_confirms_and_the_audit_names_tables_and_columns_never_rows(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db, confirmed=False)
        await ready.world.service.update_public_link(
            ready.world.olga,
            ready.page_id,
            ArtifactPublicLinkUpdate(password=PASSWORD),
        )
        await ready.world.service.update_public_link(
            ready.world.olga, ready.page_id, ArtifactPublicLinkUpdate(embed_origins=[SITE])
        )

        detail = await ready.confirm(ready.world.olga)

        assert detail.public_data is not None
        assert detail.public_data.consented and detail.public_data.holds
        assert detail.public_data.version == 1
        assert detail.may_confirm_public_data is True
        page = await ready.page()
        assert page.public_data_by_user_id == ready.world.olga.user_id
        assert page.public_data_membership_id == await owner_membership_id(db, page)
        [(_, details)] = [
            entry
            for entry in await _actions(db, ready.page_id)
            if entry[0] == "artifact.public_data_consented"
        ]
        assert details["version"] == 1
        assert details["embed_origins"] == [SITE]
        assert details["password_protected"] is True
        assert details["tables"] and any(
            column.endswith(".Customer") for column in details["columns"]
        )
        assert "for_owner" not in details
        assert "Ann" not in json.dumps(details)
        assert PASSWORD not in json.dumps(details)

    @pytest.mark.security
    async def test_an_admin_confirms_for_the_owner(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db, confirmed=False)
        admin = await ready.world.member(role="admin")

        await ready.confirm(admin)

        assert (await ready.page()).public_data_by_user_id == admin.user_id
        [(_, details)] = [
            entry
            for entry in await _actions(db, ready.page_id)
            if entry[0] == "artifact.public_data_consented"
        ]
        assert details["for_owner"] == str(ready.world.olga.user_id)
        assert await ready.holds()

    @pytest.mark.security
    async def test_an_editor_by_grant_is_refused_and_so_is_a_stranger(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db, confirmed=False)
        editor = await ready.world.member(page=GrantLevel.EDIT)
        data_editor = await ready.world.member(page=GrantLevel.EDIT_DATA)

        for caller in (editor, data_editor):
            with pytest.raises(AuthorizationError):
                await ready.confirm(caller)
            with pytest.raises(AuthorizationError):
                await ready.public.disclosure(caller, ready.page_id)
        assert not await ready.consented()

    @pytest.mark.security
    async def test_somebody_acting_for_the_owner_or_an_admin_is_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db, confirmed=False)
        admin = await ready.world.member(role="admin")

        with impersonated():
            for caller in (ready.world.olga, admin):
                with pytest.raises(AuthorizationError):
                    await ready.confirm(caller)

        assert not await ready.consented()

    async def test_each_refusal(self, db: AsyncSession, storage: LocalFileStorage) -> None:
        ready = await _ready(db, confirmed=False)
        olga = ready.world.olga

        with pytest.raises(BadRequestError):
            await ready.confirm(olga, confirmed=False)

        with pytest.raises(ConcurrentChangeError):
            await ready.public.confirm(
                olga,
                ready.page_id,
                ArtifactPublicDataCreate(
                    fingerprint="0" * 64, audience_digest="0" * 64, confirmed=True
                ),
            )

        ready.world.org.public_live_data = False
        await db.flush()
        with pytest.raises(BadRequestError, match="Live data on public pages is off"):
            await ready.confirm(olga)
        ready.world.org.public_live_data = True

        await ready.world.service.withdraw_consent(olga, ready.page_id)
        with pytest.raises(BadRequestError, match="Confirm this version"):
            await ready.confirm(olga)
        await ready.world.confirm(olga, 1)

        admin = await ready.world.member(role="admin")
        await db.execute(
            delete(OrganizationMember).where(
                OrganizationMember.user_id == olga.user_id,
                OrganizationMember.organization_id == ready.world.org.id,
            )
        )
        with pytest.raises(BadRequestError, match="no longer an active member"):
            await ready.confirm(admin)
        assert not await ready.consented()

    async def test_an_origin_added_after_the_disclosure_refuses_the_confirm(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db, confirmed=False)
        olga = ready.world.olga
        shown = await ready.public.disclosure(olga, ready.page_id)
        await ready.world.service.update_public_link(
            olga, ready.page_id, ArtifactPublicLinkUpdate(embed_origins=[SITE])
        )

        with pytest.raises(ConcurrentChangeError):
            await ready.confirm(olga, audience=shown.audience_digest)

        assert not await ready.consented()

    async def test_a_password_removed_after_the_disclosure_refuses_the_confirm(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db, confirmed=False)
        olga, service = ready.world.olga, ready.world.service
        await service.update_public_link(
            olga, ready.page_id, ArtifactPublicLinkUpdate(password=PASSWORD)
        )
        shown = await ready.public.disclosure(olga, ready.page_id)
        await service.update_public_link(
            olga, ready.page_id, ArtifactPublicLinkUpdate(password=None)
        )

        with pytest.raises(ConcurrentChangeError):
            await ready.confirm(olga, audience=shown.audience_digest)

        assert not await ready.consented()

    async def test_a_page_with_its_link_off_or_no_data_cannot_be_confirmed(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db, confirmed=False)
        await ready.world.service.clear_public_link(ready.world.olga, ready.page_id)
        with pytest.raises(BadRequestError, match="no public link"):
            await ready.confirm(ready.world.olga)

        bare = await _ready(db, confirmed=False)
        await bare.world.publish("<p>v2</p>", fields=None)
        with pytest.raises(BadRequestError, match="reads no data"):
            await bare.public.confirm(
                bare.world.olga,
                bare.page_id,
                ArtifactPublicDataCreate(
                    fingerprint="0" * 64, audience_digest="0" * 64, confirmed=True
                ),
            )

    async def test_confirming_what_already_holds_changes_nothing(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db)
        at = (await ready.page()).public_data_at

        await ready.confirm(ready.world.olga)

        assert (await ready.page()).public_data_at == at
        assert (await ready.actions()).count("artifact.public_data_consented") == 1


class TestTheDisclosure:
    async def test_it_names_the_public_audience_and_the_served_version(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db, confirmed=False)
        await ready.world.service.update_public_link(
            ready.world.olga,
            ready.page_id,
            ArtifactPublicLinkUpdate(password=PASSWORD, embed_origins=[SITE]),
        )

        shown = await ready.public.disclosure(ready.world.olga, ready.page_id)

        assert shown.switch_on and shown.link_on and shown.password_protected
        assert shown.embed_origins == [SITE]
        assert (shown.version, shown.member_consent, shown.confirmable) == (1, True, True)
        assert shown.fingerprint == await ready.fingerprint()
        assert shown.audience_digest == audience_digest(await ready.page())
        assert shown.data is not None and "orders" in shown.data.parts

    async def test_it_says_why_it_cannot_be_confirmed(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db, confirmed=False)
        ready.world.org.public_live_data = False
        await db.flush()

        shown = await ready.public.disclosure(ready.world.olga, ready.page_id)

        assert (shown.switch_on, shown.confirmable) == (False, False)
        assert shown.problem is not None and "Live data on public pages is off" in shown.problem

    async def test_a_page_that_reads_no_data_has_no_parts(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db, confirmed=False)
        await ready.world.publish("<p>v2</p>", fields=None)

        shown = await ready.public.disclosure(ready.world.olga, ready.page_id)

        assert shown.data is None and shown.member_consent is False and shown.version == 2


class TestWithdrawing:
    async def test_any_editor_withdraws_and_it_is_audited(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db)
        editor = await ready.world.member(page=GrantLevel.EDIT)

        detail = await ready.public.withdraw(editor, ready.page_id)

        assert detail.public_data is not None and not detail.public_data.consented
        assert not await ready.consented()
        assert "artifact.public_data_withdrawn" in await ready.actions()
        assert detail.may_confirm_public_data is False

    async def test_withdrawing_with_no_consent_changes_nothing(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db, confirmed=False)

        await ready.public.withdraw(ready.world.olga, ready.page_id)

        assert "artifact.public_data_withdrawn" not in await ready.actions()

    @pytest.mark.security
    async def test_somebody_acting_for_an_editor_and_a_reader_are_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db)
        reader = await ready.world.member(page=GrantLevel.READ)

        with impersonated(), pytest.raises(AuthorizationError):
            await ready.public.withdraw(ready.world.olga, ready.page_id)
        with pytest.raises(NotFoundError):
            await ready.public.withdraw(reader, ready.page_id)

        assert await ready.consented()


class TestWhatVoidsIt:
    async def test_turning_the_link_off(self, db: AsyncSession, storage: LocalFileStorage) -> None:
        ready = await _ready(db)

        await ready.world.service.clear_public_link(ready.world.olga, ready.page_id)

        assert not await ready.consented()
        assert await ready.voided() == ["link_off"]

    async def test_a_consent_written_behind_the_services_back_does_not_survive_link_off(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """A confirm that committed after the page was read is seen once the lock is held."""
        ready = await _ready(db, confirmed=False)
        page = await ready.page()  # loaded before the consent lands, so it reads stale
        assert page.public_data_fingerprint is None
        await db.execute(
            update(Artifact)
            .where(Artifact.id == ready.page_id)
            .values(
                public_data_fingerprint=await ready.fingerprint(),
                public_data_membership_id=uuid.uuid4(),
                public_data_at=datetime.now(UTC),
            )
            .execution_options(synchronize_session=False)
        )

        await ready.world.service.clear_public_link(ready.world.olga, ready.page_id)

        assert not await ready.consented()
        assert await ready.voided() == ["link_off"]

    async def test_removing_the_password_but_not_setting_one(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db)
        service, olga = ready.world.service, ready.world.olga

        await service.update_public_link(
            olga, ready.page_id, ArtifactPublicLinkUpdate(password=PASSWORD)
        )
        assert await ready.consented()
        await service.update_public_link(
            olga, ready.page_id, ArtifactPublicLinkUpdate(password=None)
        )

        assert not await ready.consented()
        assert await ready.voided() == ["password_removed"]

    async def test_a_new_embedding_site_but_not_a_removed_or_repeated_one(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db, confirmed=False)
        service, olga = ready.world.service, ready.world.olga
        await service.update_public_link(
            olga, ready.page_id, ArtifactPublicLinkUpdate(embed_origins=[SITE])
        )
        await ready.confirm(olga)

        await service.update_public_link(
            olga, ready.page_id, ArtifactPublicLinkUpdate(embed_origins=[SITE])
        )
        await service.update_public_link(
            olga, ready.page_id, ArtifactPublicLinkUpdate(embed_origins=[])
        )
        assert await ready.consented()
        await service.update_public_link(
            olga, ready.page_id, ArtifactPublicLinkUpdate(embed_origins=[SITE])
        )

        assert not await ready.consented()
        assert await ready.voided() == ["origin_added"]

    async def test_a_new_owner(self, db: AsyncSession, storage: LocalFileStorage) -> None:
        ready = await _ready(db)
        bea = await ready.world.member(reads_table=True)
        assert bea.user_id is not None

        await ready.world.service.change_owner(
            ready.world.olga, ready.page_id, ArtifactOwnerUpdate(user_id=bea.user_id)
        )

        assert not await ready.consented()
        assert await ready.voided() == ["owner_changed"]

    async def test_the_members_consent_being_withdrawn(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db)

        await ready.world.service.withdraw_consent(ready.world.olga, ready.page_id)

        assert not await ready.consented()
        assert await ready.voided() == ["consent_withdrawn"]

    async def test_archiving(self, db: AsyncSession, storage: LocalFileStorage) -> None:
        ready = await _ready(db)

        await ready.world.service.archive(ready.world.olga, ready.page_id)

        assert not await ready.consented()
        assert await ready.voided() == ["archived"]

    async def test_rotating_the_key_and_the_expiry_and_a_password_being_set_keep_it(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db)
        service, olga = ready.world.service, ready.world.olga

        await service.set_public_link(olga, ready.page_id)
        await service.update_public_link(
            olga,
            ready.page_id,
            ArtifactPublicLinkUpdate(expires_at=datetime.now(UTC) + timedelta(days=1)),
        )
        await service.update_public_link(
            olga, ready.page_id, ArtifactPublicLinkUpdate(password=PASSWORD)
        )

        assert await ready.consented() and await ready.holds()
        assert await ready.voided() == []

    async def test_the_switch_going_off_hides_it_without_voiding_and_on_restores_it(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db)

        ready.world.org.public_live_data = False
        await db.flush()
        assert await ready.consented() and not await ready.holds()
        detail = await ready.world.service.read(ready.world.olga, ready.page_id)
        assert detail.public_data is not None
        assert (detail.public_data.switch_on, detail.public_data.holds) == (False, False)
        assert detail.public_data.not_holding == "switch_off"

        ready.world.org.public_live_data = True
        await db.flush()
        assert await ready.holds()
        assert await ready.voided() == []

    async def test_a_new_version_with_other_queries_stops_it_holding(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db)

        await ready.world.publish(
            "<p>v2</p>", fields={"customer": "Customer", "quantity": "Quantity"}
        )
        await ready.world.confirm(ready.world.olga, 2)

        assert await ready.consented() and not await ready.holds()
        detail = await ready.world.service.read(ready.world.olga, ready.page_id)
        assert detail.public_data is not None
        assert detail.public_data.not_holding == "queries_changed"


class TestTheDetail:
    async def test_only_an_editor_reads_it(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db)
        reader = await ready.world.member(page=GrantLevel.READ)

        detail = await ready.world.service.read(reader, ready.page_id)

        assert detail.public_data is None
        assert detail.may_confirm_public_data is False


class TestThePinnedVersion:
    async def test_the_link_serves_the_pinned_version_and_pinning_does_not_void_it(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        ready = await _ready(db)
        first = await ready.world.version(1)
        await ready.world.publish(
            "<p>v2</p>", fields={"customer": "Customer", "quantity": "Quantity"}
        )

        await ready.world.service.update_public_link(
            ready.world.olga, ready.page_id, ArtifactPublicLinkUpdate(pinned_version_id=first.id)
        )

        served = await public_version(db, await ready.page())
        assert served is not None and served.number == 1
        assert await ready.consented() and await ready.holds()
        assert await ready.voided() == []
