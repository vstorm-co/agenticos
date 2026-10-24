"""A public link's page served with its data against a real database (#1975).

A stranger's address carries no identity, so every gate is checked again on each load,
before anything is read: the link's key, expiry and password state, the organization's
switch, the public and members' consents, the version the link serves and the owner.
Expiry cuts the page itself; the other live-data gates cut only its data. These
prove that distinction, that the short cache and the
page's allowance bound what the tables are asked, and that a stranger is told nothing
of why and no record reaches a log.
"""

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.security import create_artifact_view_token, get_password_hash
from app.db.models.organization import OrganizationMember
from app.repositories import artifact_repo, resource_grant_repo
from app.services import artifact_public_data, rate_limit
from app.services.access import TABLE
from app.services.artifact import ArtifactService
from app.services.artifact_bindings import BindingRows
from app.services.artifact_public_data import PublicReads, clear_public_reads
from app.services.rate_limit import Limit
from tests.integration.test_artifact_data import _orders, _Page, _page, _unavailable
from tests.integration.test_artifact_injection import (
    PATH,
    _for_page,
    _initial,
    _open_page,
    _Storage,
)
from tests.integration.virtual_table_support import cid, insert_rows

pytestmark = pytest.mark.anyio

NOTHING = {"orders": _for_page(_unavailable(None))}


@pytest.fixture(autouse=True)
def _fresh_cache() -> Any:
    clear_public_reads()
    yield
    clear_public_reads()


async def _public_page(db: Any, *, key: str | None = None, plain_owner: bool = False) -> _Page:
    """A page whose link is on and whose data is confirmed for it, in a switched-on organization.

    With `plain_owner` the page belongs to a member who reads its table by a grant alone."""
    if plain_owner:
        page = await _page(db)
        await _orders(page)
        await page.give_to(await page.person(page=None, tables=(page.table,)))
        await page.consent(
            await page.publish(await page.bind("orders", page.query(customer="Customer")))
        )
    else:
        page, _ann = await _open_page(db)
    version = await artifact_repo.latest_version(db, page.artifact.id)
    assert version is not None
    membership = await db.scalar(
        select(OrganizationMember.id).where(
            OrganizationMember.organization_id == page.org.id,
            OrganizationMember.user_id == page.artifact.owner_user_id,
        )
    )
    page.artifact.public_key = key or f"public-{uuid.uuid4().hex}"
    page.artifact.public_data_fingerprint = version.query_fingerprint
    page.artifact.public_data_by_user_id = page.artifact.owner_user_id
    page.artifact.public_data_membership_id = membership
    page.artifact.public_data_at = datetime.now(UTC)
    page.org.public_live_data = True
    await db.flush()
    return page


def _kept(size: int) -> BindingRows:
    return BindingRows(fields={}, rows=MagicMock(bytes=size))


def _token(url: str) -> str:
    return url.rsplit("/", 1)[1]


async def _mint(page: _Page, *, password: str | None = None) -> str:
    """The token a visitor of the link is handed now."""
    opened = await ArtifactService(page.db).public_view(
        str(page.artifact.public_key), password=password
    )
    assert opened.view is not None
    return _token(opened.view.url)


async def _load(page: _Page, token: str) -> bytes:
    with patch(f"{PATH}.get_file_storage", return_value=_Storage()):
        return (await ArtifactService(page.db).content(token)).document


def _reads() -> Any:
    """Count the reads that reach the tables."""
    original = ArtifactService._read_rows
    calls: list[str] = []

    async def counted(
        self: ArtifactService, owner: Any, binding: Any, source: Any, deadline: Any
    ) -> Any:
        calls.append(binding.name)
        return await original(self, owner, binding, source, deadline)

    return patch.object(ArtifactService, "_read_rows", counted), calls


class TestWhoIsServedData:
    @pytest.mark.security
    async def test_a_stranger_s_page_carries_the_rows_without_the_editor_s_fields(self, db):
        page = await _public_page(db)

        initial = _initial(await _load(page, await _mint(page)))

        assert initial is not None
        assert initial["orders"]["status"] == "ok"
        assert "reason" not in initial["orders"]
        assert "changed" not in initial["orders"]
        assert sorted(r["customer"] for r in initial["orders"]["records"]) == ["Ann", "Bob"]

    async def test_an_embed_is_framed_by_its_sites_and_carries_the_data_the_same_way(self, db):
        page = await _public_page(db)
        page.artifact.embed_origins = ["https://a.example.com"]
        await db.flush()
        service = ArtifactService(db)
        embed = await service.embed(str(page.artifact.public_key))
        url = re.search(r'src="([^"]*/artifact-content/[^"]+)"', embed.document.decode())
        assert url is not None

        with patch(f"{PATH}.get_file_storage", return_value=_Storage()):
            served = await service.content(_token(url.group(1)))

        initial = _initial(served.document)
        assert initial is not None and initial["orders"]["count"] == 2
        assert served.embed_origins == ["https://a.example.com"]

    async def test_a_link_behind_a_password_carries_data_once_it_was_passed(self, db):
        page = await _public_page(db)
        page.artifact.public_password_hash = get_password_hash("s3cret!!")
        await db.flush()

        initial = _initial(await _load(page, await _mint(page, password="s3cret!!")))

        assert initial is not None and initial["orders"]["count"] == 2

    async def test_a_member_s_address_is_served_as_before(self, db):
        page = await _public_page(db)

        view = await ArtifactService(db).view(page.owner, page.artifact.id, data=True)
        initial = _initial(await _load(page, _token(view.url)))

        assert initial is not None and initial["orders"]["count"] == 2


class TestEveryGateOnEveryLoad:
    @pytest.mark.security
    async def test_a_rotated_key_ends_the_address_with_data_and_without(self, db):
        page = await _public_page(db)
        token = await _mint(page)
        page.artifact.public_key = "rotated-key"
        await db.flush()

        with pytest.raises(NotFoundError):
            await _load(page, token)

    @pytest.mark.security
    async def test_a_link_turned_off_ends_the_address(self, db):
        page = await _public_page(db)
        token = await _mint(page)
        page.artifact.public_key = None
        await db.flush()

        with pytest.raises(NotFoundError):
            await _load(page, token)

    @pytest.mark.security
    async def test_an_address_without_a_key_claim_is_refused(self, db):
        page = await _public_page(db)
        version = await artifact_repo.latest_version(db, page.artifact.id)
        assert version is not None
        token = create_artifact_view_token(
            version.id, expires_in=timedelta(minutes=1), nonce="n", live=False, audience="public"
        )

        with pytest.raises(NotFoundError):
            await _load(page, token)

    @pytest.mark.security
    async def test_an_expired_link_refuses_the_whole_page_even_with_an_existing_token(self, db):
        page = await _public_page(db)
        token = await _mint(page)
        page.artifact.public_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.flush()

        with pytest.raises(NotFoundError):
            await _load(page, token)

    @pytest.mark.security
    async def test_a_password_set_after_the_mint_gives_no_data(self, db):
        page = await _public_page(db)
        token = await _mint(page)
        page.artifact.public_password_hash = get_password_hash("s3cret!!")
        await db.flush()

        assert _initial(await _load(page, token)) == NOTHING

    @pytest.mark.security
    async def test_a_password_changed_after_the_mint_gives_no_data(self, db):
        page = await _public_page(db)
        page.artifact.public_password_hash = get_password_hash("s3cret!!")
        await db.flush()
        token = await _mint(page, password="s3cret!!")
        assert _initial(await _load(page, token)) is not None
        page.artifact.public_password_hash = get_password_hash("another-one")
        await db.flush()

        assert _initial(await _load(page, token)) == NOTHING

    @pytest.mark.security
    async def test_a_password_removed_after_the_mint_gives_no_data(self, db):
        page = await _public_page(db)
        page.artifact.public_password_hash = get_password_hash("s3cret!!")
        await db.flush()
        token = await _mint(page, password="s3cret!!")
        page.artifact.public_password_hash = None
        await db.flush()

        assert _initial(await _load(page, token)) == NOTHING

    @pytest.mark.security
    async def test_the_organization_switch_off_cuts_the_data_at_the_next_load(self, db):
        page = await _public_page(db)
        token = await _mint(page)
        page.org.public_live_data = False
        await db.flush()

        assert _initial(await _load(page, token)) == NOTHING

    @pytest.mark.security
    async def test_a_voided_consent_gives_no_data(self, db):
        page = await _public_page(db)
        token = await _mint(page)
        page.artifact.public_data_fingerprint = None
        await db.flush()

        assert _initial(await _load(page, token)) == NOTHING

    @pytest.mark.security
    async def test_the_members_consent_withdrawn_gives_no_data(self, db):
        page = await _public_page(db)
        token = await _mint(page)
        page.artifact.consent_withdrawn_at = datetime.now(UTC) + timedelta(seconds=5)
        await db.flush()

        assert _initial(await _load(page, token)) == NOTHING

    @pytest.mark.security
    async def test_an_owner_who_left_gives_no_data(self, db):
        page = await _public_page(db)
        token = await _mint(page)
        await db.execute(
            delete(OrganizationMember).where(
                OrganizationMember.organization_id == page.org.id,
                OrganizationMember.user_id == page.artifact.owner_user_id,
            )
        )
        await db.flush()

        assert _initial(await _load(page, token)) == NOTHING

    @pytest.mark.security
    async def test_a_source_that_changed_is_unavailable_without_saying_what(self, db):
        page = await _public_page(db)
        token = await _mint(page)
        await page.reshape(Customer=None)

        assert _initial(await _load(page, token)) == NOTHING

    @pytest.mark.security
    async def test_a_version_the_link_no_longer_serves_gives_no_data(self, db):
        page = await _public_page(db)
        token = await _mint(page)
        # A newer version, consented by the members, is what the audience is served now.
        newer = await page.publish(await page.bind("orders", page.query(customer="Customer")))
        await page.consent(newer)

        assert _initial(await _load(page, token)) == NOTHING

    @pytest.mark.security
    async def test_a_pinned_version_is_the_one_the_gates_follow(self, db):
        page = await _public_page(db)
        pinned = await artifact_repo.latest_version(db, page.artifact.id)
        assert pinned is not None
        page.artifact.public_version_number = pinned.number
        await db.flush()
        # Newer and consented, but the link serves the pin.
        newer = await page.publish(await page.bind("orders", page.query(qty="Quantity")))
        await page.consent(newer)

        initial = _initial(await _load(page, await _mint(page)))

        assert initial is not None and initial["orders"]["count"] == 2

    @pytest.mark.security
    async def test_a_pin_the_consent_is_not_for_gives_no_data(self, db):
        page = await _public_page(db)
        older = await artifact_repo.latest_version(db, page.artifact.id)
        assert older is not None
        newer = await page.publish(await page.bind("orders", page.query(qty="Quantity")))
        await page.consent(newer)
        page.artifact.public_version_number = newer.number
        await db.flush()

        # The gate fails at the mint, so the address is not one that asks for data.
        assert _initial(await _load(page, await _mint(page))) is None

    async def test_a_page_with_no_bindings_gets_no_data_claim(self, db):
        page = await _public_page(db)
        empty = await page.publish()
        page.artifact.public_version_number = empty.number
        await db.flush()

        assert _initial(await _load(page, await _mint(page))) is None


class TestTheCacheAndTheAllowance:
    async def test_a_second_visitor_is_served_from_the_cache_without_a_table_read(self, db):
        page = await _public_page(db)
        counting, calls = _reads()

        with counting:
            first = _initial(await _load(page, await _mint(page)))
            second = _initial(await _load(page, await _mint(page)))

        assert calls == ["orders"]
        assert first == second and first is not None and first["orders"]["count"] == 2

    @pytest.mark.security
    async def test_the_gates_run_before_the_cache(self, db):
        page = await _public_page(db)
        token = await _mint(page)
        await _load(page, token)
        page.org.public_live_data = False
        await db.flush()

        assert _initial(await _load(page, token)) == NOTHING

    @pytest.mark.security
    async def test_an_owner_who_lost_a_table_gets_nothing_from_the_cache(self, db):
        page = await _public_page(db, plain_owner=True)
        token = await _mint(page)
        assert _initial(await _load(page, token)) is not None
        # Still a member of the organization, no longer reading the table.
        await resource_grant_repo.revoke(
            db,
            organization_id=page.org.id,
            subject_user_id=page.artifact.owner_user_id,
            resource_type=TABLE.key,
            resource_id=page.table.id,
        )

        assert _initial(await _load(page, token)) == NOTHING

    @pytest.mark.security
    async def test_a_column_archived_after_a_read_gets_nothing_from_the_cache(self, db):
        page = await _public_page(db)
        token = await _mint(page)
        assert _initial(await _load(page, token)) is not None
        await page.reshape(Customer=None)

        assert _initial(await _load(page, token)) == NOTHING

    async def test_a_binding_that_changed_does_not_take_a_read_of_the_allowance(self, db):
        page = await _public_page(db)
        await page.reshape(Customer=None)
        decisions: list[str] = []
        original = rate_limit.consume_with_local_floor

        async def consume(**kwargs: Any) -> Any:
            decisions.append(kwargs["caller"])
            return await original(**kwargs)

        with patch.object(rate_limit, "consume_with_local_floor", consume):
            assert _initial(await _load(page, await _mint(page))) == NOTHING

        assert decisions == []

    async def test_a_read_older_than_the_cache_lifetime_is_read_again(self, db):
        page = await _public_page(db)
        counting, calls = _reads()
        clock = [1000.0]

        with counting, patch.object(artifact_public_data.time, "monotonic", lambda: clock[0]):
            await _load(page, await _mint(page))
            clock[0] += artifact_public_data.CACHE_SECONDS + 1
            await _load(page, await _mint(page))

        assert calls == ["orders", "orders"]

    async def test_an_unavailable_read_is_never_kept(self, db):
        page = await _public_page(db)
        counting, calls = _reads()
        await page.reshape(Customer=None)

        with counting:
            first = _initial(await _load(page, await _mint(page)))
            second = _initial(await _load(page, await _mint(page)))

        assert first == second == NOTHING
        assert calls == []

    async def test_only_the_oldest_reads_are_kept_past_the_bound(self, db):
        page = await _public_page(db)
        version = await artifact_repo.latest_version(db, page.artifact.id)
        assert version is not None
        reads = PublicReads(page.artifact.id, version, uuid.uuid4())
        with patch.object(artifact_public_data, "CACHE_ENTRIES", 2):
            for name in ("a", "b", "c"):
                reads.store(name, _kept(1))

        assert [reads.lookup(name) is not None for name in ("a", "b", "c")] == [False, True, True]

    async def test_the_least_recently_used_read_goes_first(self, db):
        page = await _public_page(db)
        version = await artifact_repo.latest_version(db, page.artifact.id)
        assert version is not None
        reads = PublicReads(page.artifact.id, version, uuid.uuid4())
        with patch.object(artifact_public_data, "CACHE_ENTRIES", 2):
            reads.store("a", _kept(1))
            reads.store("b", _kept(1))
            assert reads.lookup("a") is not None
            reads.store("c", _kept(1))

        assert [reads.lookup(name) is not None for name in ("a", "b", "c")] == [True, False, True]

    async def test_the_kept_reads_are_bounded_by_their_bytes(self, db):
        page = await _public_page(db)
        version = await artifact_repo.latest_version(db, page.artifact.id)
        assert version is not None
        reads = PublicReads(page.artifact.id, version, uuid.uuid4())
        with patch.object(settings, "ARTIFACT_PUBLIC_DATA_CACHE_BYTES", 10):
            reads.store("a", _kept(6))
            reads.store("b", _kept(6))
            reads.store("huge", _kept(11))

        assert [reads.lookup(name) is not None for name in ("a", "b", "huge")] == [
            False,
            True,
            False,
        ]

    async def test_the_allowance_counts_only_reads_that_reach_the_tables(self, db):
        page = await _public_page(db)
        counting, calls = _reads()
        decisions: list[str] = []
        original = rate_limit.consume_with_local_floor

        async def consume(**kwargs: Any) -> Any:
            decisions.append(kwargs["caller"])
            return await original(**kwargs)

        with counting, patch.object(rate_limit, "consume_with_local_floor", consume):
            for _ in range(3):
                await _load(page, await _mint(page))

        assert calls == ["orders"]
        assert decisions == [f"artifact:{page.artifact.id}"]

    @pytest.mark.security
    async def test_past_the_allowance_a_binding_that_needs_a_read_is_unavailable(self, db):
        page = await _public_page(db)
        counting, calls = _reads()

        with counting, patch.object(rate_limit, "artifact_public_data_limit", lambda: Limit(1)):
            first = _initial(await _load(page, await _mint(page)))
            clear_public_reads()
            second = _initial(await _load(page, await _mint(page)))

        assert first is not None and first["orders"]["status"] == "ok"
        assert second == NOTHING
        assert calls == ["orders"]

    async def test_a_load_reading_several_bindings_takes_one_read_of_the_allowance(self, db):
        page = await _public_page(db)
        two = await page.publish(
            await page.bind("orders", page.query(customer="Customer")),
            await page.bind("qty", page.query(qty="Quantity")),
        )
        await page.consent(two)
        page.artifact.public_data_fingerprint = two.query_fingerprint
        await db.flush()
        counting, calls = _reads()

        with counting, patch.object(rate_limit, "artifact_public_data_limit", lambda: Limit(1)):
            initial = _initial(await _load(page, await _mint(page)))

        assert sorted(calls) == ["orders", "qty"]
        assert initial is not None
        assert {name: binding["status"] for name, binding in initial.items()} == {
            "orders": "ok",
            "qty": "ok",
        }

    async def test_a_cached_binding_is_still_served_past_the_allowance(self, db):
        page = await _public_page(db)

        with patch.object(rate_limit, "artifact_public_data_limit", lambda: Limit(1)):
            await _load(page, await _mint(page))
            second = _initial(await _load(page, await _mint(page)))

        assert second is not None and second["orders"]["status"] == "ok"

    async def test_a_process_serving_as_many_loads_as_it_may_gives_the_page_no_data(self, db):
        page = await _public_page(db)

        class Locked:
            def locked(self) -> bool:
                return True

        with patch(f"{PATH}._load_gate", return_value=Locked()):
            document = await _load(page, await _mint(page))

        assert _initial(document) == NOTHING

    async def test_a_gate_that_filled_while_the_allowance_was_asked_refuses_the_load(self, db):
        page = await _public_page(db)
        gate = asyncio.Semaphore(1)
        counting, calls = _reads()

        async def admit(self: PublicReads) -> bool:
            await gate.acquire()
            return True

        with (
            counting,
            patch(f"{PATH}._load_gate", return_value=gate),
            patch.object(PublicReads, "admit", admit),
        ):
            document = await _load(page, await _mint(page))

        assert _initial(document) == NOTHING
        assert calls == []


class TestNoRecordInALog:
    @pytest.mark.security
    async def test_a_record_served_to_a_stranger_never_reaches_a_log(self, db, caplog):
        page = await _public_page(db)
        needle = f"needle-{uuid.uuid4().hex}"
        await insert_rows(db, page.table, [{cid(page.table, "Customer"): needle}])
        caplog.set_level(logging.DEBUG)

        document = await _load(page, await _mint(page))

        assert needle in document.decode()
        for record in caplog.records:
            assert needle not in record.getMessage()
            assert needle not in repr(vars(record))
