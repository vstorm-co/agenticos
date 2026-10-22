"""A page's live data against a real database: each page query read as the page's owner.

`ArtifactService.data` reads every binding's page query with the access of the page's
owner, as the member they are now, so everyone served the data reads the same records
whatever their own access to the tables. These prove who is served it (the owner and
the roles that read every table always, anyone else once the owner consented), that
the owner is checked again on
every load, that a query whose source changed since it was published reads nothing
(and only that query), the payload (named fields and the id, nothing else), the fair
byte split and the deadline, which stops a slow page without ever cancelling a query
from Python.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.artifact import Artifact, ArtifactMediaType, ArtifactVersion
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel
from app.repositories import artifact_repo, resource_grant_repo, virtual_table_repo
from app.schemas.artifact import (
    ArtifactBinding,
    ArtifactData,
    BindingData,
    BindingFilter,
    BindingRequest,
    BoundField,
)
from app.schemas.table_view import TableViewConfig, TableViewCreate, TableViewUpdate
from app.schemas.virtual_table import (
    ColumnDef,
    ColumnInput,
    OptionInput,
    RecordFilter,
    RecordQuery,
    SchemaUpdate,
    TableCreate,
    TableRead,
)
from app.services.access import ARTIFACT, TABLE
from app.services.artifact import ArtifactService
from app.services.artifact_bindings import check_bindings, fingerprint
from app.services.virtual_tables import TableViewService, VirtualTableService
from tests.integration.virtual_table_support import (
    cid,
    column,
    ctx_for,
    insert_rows,
    make_org,
    make_user,
    orders_table,
    shaped_size,
)

pytestmark = pytest.mark.anyio

FORBIDDEN_KEYS = {"external_id", "created_by", "updated_by", "revision", "values", "links"}
READ = frozenset({"read"})


def _kept(existing: ColumnDef, **changes: Any) -> ColumnInput:
    """A live column sent back as it is, or with `changes`."""
    return ColumnInput(
        **{
            "id": existing.id,
            "label": existing.label,
            "type": existing.type,
            "options": [OptionInput(id=o.id, label=o.label) for o in existing.options],
            "link_table_id": existing.link_table_id,
            "link_column_id": existing.link_column_id,
            "target_column_id": existing.target_column_id,
            "aggregate": existing.aggregate,
            "formula": existing.formula,
            **changes,
        }
    )


@dataclass
class _Page:
    """An organization, its owner, an orders table and a page to bind to it."""

    db: AsyncSession
    org: Organization
    owner: AuthContext
    tables: VirtualTableService
    table: TableRead
    artifact: Artifact
    known: list[UUID] = field(default_factory=list)
    numbers: list[int] = field(default_factory=list)

    def option(self, label: str, choice: str) -> str:
        column_def = next(c for c in self.table.columns if c.label == label)
        return str(next(o.id for o in column_def.options if o.label == choice))

    async def new_table(self, data: TableCreate) -> TableRead:
        table = await self.tables.create_table(self.owner, data)
        self.known.append(table.id)
        return table

    async def bind(self, name: str, request: BindingRequest) -> ArtifactBinding:
        """The page query `request` resolves to, as the organization's owner publishes it."""
        [check] = await check_bindings(
            self.db,
            requested={name: request},
            previous=[],
            person=self.owner,
            owner=self.owner,
            grants=dict.fromkeys(self.known, READ),
        )
        assert check.problem is None, check.problem
        assert check.binding is not None
        return check.binding

    def query(self, table: TableRead | None = None, **fields: str) -> BindingRequest:
        return BindingRequest(table=(table or self.table).id, fields=fields)

    async def publish(self, *bindings: ArtifactBinding) -> ArtifactVersion:
        """A version reading `bindings`, waiting for the owner's consent as a publish leaves it."""
        number = len(self.numbers) + 1
        self.numbers.append(number)
        return await artifact_repo.create_version(
            self.db,
            artifact_id=self.artifact.id,
            number=number,
            media_type=ArtifactMediaType.HTML.value,
            size_bytes=1,
            sha256=f"{number:064d}",
            storage_path=f"artifacts/{self.artifact.id}/{number}.html",
            run_id=None,
            bindings=[binding.model_dump(mode="json") for binding in bindings],
            consent={
                "query_fingerprint": fingerprint(bindings),
                "consent_state": "pending" if bindings else "not_needed",
            },
        )

    async def consent(self, version: ArtifactVersion) -> None:
        """The owner's consent to `version`, under the membership they hold now."""
        membership = await self.db.scalar(
            select(OrganizationMember.id).where(
                OrganizationMember.organization_id == self.org.id,
                OrganizationMember.user_id == self.artifact.owner_user_id,
            )
        )
        version.consent_state = "consented"
        version.consented_at = datetime.now(UTC)
        version.consented_by_membership_id = membership
        await self.db.flush()

    async def data(
        self, viewer: AuthContext | None = None, version: ArtifactVersion | None = None
    ) -> ArtifactData:
        if version is None:
            version = await artifact_repo.latest_version(self.db, self.artifact.id)
            assert version is not None
        return await ArtifactService(self.db).data(
            viewer or self.owner, self.artifact.id, version.id
        )

    async def person(
        self,
        *,
        role: str = "member",
        page: GrantLevel | None = GrantLevel.READ,
        tables: tuple[TableRead, ...] = (),
    ) -> AuthContext:
        """Another member of the organization, holding the grants asked for."""
        user = await make_user(self.db)
        self.db.add(OrganizationMember(organization_id=self.org.id, user_id=user.id, role=role))
        await self.db.flush()
        if page is not None:
            await self._grant(user.id, ARTIFACT.key, self.artifact.id, page)
        for table in tables:
            await self._grant(user.id, TABLE.key, table.id, GrantLevel.READ)
        return AuthContext(user_id=user.id, organization_id=self.org.id, role=role)

    async def _grant(
        self, user_id: UUID, resource_type: str, resource_id: UUID, level: GrantLevel
    ) -> None:
        await resource_grant_repo.upsert(
            self.db,
            organization_id=self.org.id,
            subject_user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            level=level,
        )

    async def give_to(self, owner: AuthContext) -> None:
        self.artifact.owner_user_id = owner.user_id
        await self.db.flush()

    async def reshape(
        self, table: TableRead | None = None, **changes: dict[str, Any] | None
    ) -> TableRead:
        """Change a table's schema: each label to its column's changes, `None` to archive it."""
        current = await self.tables.describe_table(self.owner, (table or self.table).id)
        columns = [
            _kept(c, **(changes.get(c.label) or {}))
            for c in current.columns
            if not c.archived and not (c.label in changes and changes[c.label] is None)
        ]
        updated = await self.tables.update_schema(
            self.owner,
            current.id,
            SchemaUpdate(expected_version=current.schema_version, columns=columns),
        )
        if table is None:
            self.table = updated
        return updated


async def _page(db: AsyncSession) -> _Page:
    owner_user = await make_user(db)
    org = await make_org(db, owner=owner_user)
    owner = ctx_for(owner_user, org)
    tables = VirtualTableService(db)
    table = await orders_table(tables, owner)
    agent = Agent(
        organization_id=org.id,
        name="Reporter",
        created_by_user_id=owner_user.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
    )
    db.add(agent)
    await db.flush()
    artifact = await artifact_repo.create(
        db,
        organization_id=org.id,
        owner_user_id=owner_user.id,
        agent_id=agent.id,
        environment_id=None,
        name="live-report",
        title="Live report",
    )
    return _Page(db, org, owner, tables, table, artifact, known=[table.id])


async def _orders(page: _Page) -> list[UUID]:
    return await insert_rows(
        page.db,
        page.table,
        [
            {
                cid(page.table, "Customer"): "Ann",
                cid(page.table, "Quantity"): 3,
                cid(page.table, "Status"): page.option("Status", "Open"),
            },
            {
                cid(page.table, "Customer"): "Bob",
                cid(page.table, "Quantity"): 1,
                cid(page.table, "Status"): page.option("Status", "Shipped"),
            },
        ],
    )


def _open_only(page: _Page, **fields: str) -> BindingRequest:
    return BindingRequest(
        table=page.table.id,
        fields=fields,
        filters=[BindingFilter(column="Status", op="eq", value="Open")],
    )


async def _linked(page: _Page) -> tuple[TableRead, TableRead, UUID]:
    """Products, orders linking to them with a lookup, and one widget ordered as A-1."""
    products = await page.new_table(
        TableCreate(name="Products", columns=[column("Code", "integer"), column("Name", "text")])
    )
    orders = await page.new_table(
        TableCreate(
            name="Linked orders",
            columns=[column("Ref", "text"), column("Items", "link", link_table_id=products.id)],
        )
    )
    orders = await page.tables.update_schema(
        page.owner,
        orders.id,
        SchemaUpdate(
            expected_version=orders.schema_version,
            columns=[
                *(_kept(c) for c in orders.columns),
                column(
                    "Names",
                    "lookup",
                    link_column_id=UUID(cid(orders, "Items")),
                    target_column_id=UUID(cid(products, "Name")),
                ),
            ],
        ),
    )
    [widget] = await insert_rows(
        page.db, products, [{cid(products, "Code"): 7, cid(products, "Name"): "Widget"}]
    )
    await insert_rows(
        page.db, orders, [{cid(orders, "Ref"): "A-1", cid(orders, "Items"): [str(widget)]}]
    )
    return products, orders, widget


def _unavailable(reason: str | None, changed: str | None = None) -> BindingData:
    return BindingData(
        status="unavailable",
        reason=reason,
        changed=changed,
        truncated=False,
        limit=None,
        count=0,
        fields={},
        records=[],
    )


class TestWhoReads:
    @pytest.mark.security
    async def test_an_admin_is_served_the_page_query_and_nothing_more(self, db):
        page = await _page(db)
        ann, _bob = await _orders(page)
        await page.publish(await page.bind("open", _open_only(page, customer="Customer")))
        admin = await page.person(role="admin", page=None)

        served = (await page.data(admin)).bindings["open"]

        assert served.records == [{"id": str(ann), "customer": "Ann"}]

    @pytest.mark.security
    async def test_once_served_a_viewer_reads_the_query_whatever_their_own_access(self, db):
        """Q1: the owner's access backs the data, so a member who reads no table at all is
        served exactly the query's rows and columns - and still nothing through the tables."""
        page = await _page(db)
        ann, _bob = await _orders(page)
        await page.consent(
            await page.publish(await page.bind("open", _open_only(page, customer="Customer")))
        )
        member = await page.person()

        served = (await page.data(member)).bindings["open"]

        assert served.records == [{"id": str(ann), "customer": "Ann"}]
        assert set(served.fields) == {"customer"}
        with pytest.raises(NotFoundError):
            await page.tables.list_records(member, page.table.id, RecordQuery())
        with pytest.raises(NotFoundError):
            await page.tables.describe_table(member, page.table.id)

    @pytest.mark.security
    async def test_a_member_awaits_the_owner_s_consent(self, db):
        """Until consent lands, a page's data reaches only its owner and the roles that
        read every table: an editor is served the version and told why its data waits,
        a reader is not served the version at all - their own table access aside."""
        page = await _page(db)
        await _orders(page)
        await page.publish(await page.bind("open", _open_only(page, customer="Customer")))
        reader = await page.person(tables=(page.table,))
        editor = await page.person(page=GrantLevel.EDIT, tables=(page.table,))

        with pytest.raises(NotFoundError):
            await page.data(reader)
        assert (await page.data(editor)).bindings == {"open": _unavailable("awaiting_consent")}

    @pytest.mark.security
    @pytest.mark.parametrize("how", ["removed", "deactivated"])
    async def test_an_owner_who_is_no_longer_a_member_backs_no_data(self, db, how):
        page = await _page(db)
        await _orders(page)
        await page.publish(await page.bind("open", _open_only(page, customer="Customer")))
        admin = await page.person(role="admin", page=None)
        if how == "removed":
            await db.execute(
                delete(OrganizationMember).where(
                    OrganizationMember.user_id == page.owner.user_id,
                    OrganizationMember.organization_id == page.org.id,
                )
            )
        else:
            await db.execute(
                text("UPDATE users SET is_active = false WHERE id = :id"),
                {"id": page.owner.user_id},
            )

        assert (await page.data(admin)).bindings == {"open": _unavailable("creator_gone")}

    @pytest.mark.security
    async def test_an_owner_who_lost_read_on_a_table_backs_no_data(self, db):
        page = await _page(db)
        await _orders(page)
        member = await page.person(page=None, tables=(page.table,))
        await page.give_to(member)
        await page.publish(await page.bind("open", _open_only(page, customer="Customer")))
        assert (await page.data(member)).bindings["open"].count == 1
        await resource_grant_repo.revoke(
            db,
            organization_id=page.org.id,
            subject_user_id=member.user_id,
            resource_type=TABLE.key,
            resource_id=page.table.id,
        )

        assert (await page.data()).bindings == {"open": _unavailable("creator_lost_access")}

    async def test_an_older_version_gets_not_current(self, db):
        page = await _page(db)
        await _orders(page)
        binding = await page.bind("tickets", page.query(customer="Customer"))
        first = await page.publish(binding)
        second = await page.publish(binding)

        older, newest = await page.data(version=first), await page.data(version=second)

        assert older.bindings == {"tickets": _unavailable("not_current")}
        assert older.current is False
        assert newest.bindings["tickets"].count == 2
        assert newest.current is True


class TestThePayload:
    @pytest.mark.security
    async def test_only_named_fields_and_the_id_are_sent(self, db):
        """The filter's column is read to filter by, and never served."""
        page = await _page(db)
        ann, _bob = await _orders(page)
        await page.publish(
            await page.bind(
                "big",
                BindingRequest(
                    table=page.table.id,
                    fields={"customer": "Customer", "status": "Status"},
                    filters=[BindingFilter(column="Quantity", op="gt", value=2)],
                ),
            )
        )

        served = (await page.data()).bindings["big"]

        assert served.records == [{"id": str(ann), "customer": "Ann", "status": "Open"}]
        for record in served.records:
            assert not FORBIDDEN_KEYS & set(record)
        assert served.fields == {
            "customer": BoundField(label="Customer", type="text", state="ok"),
            "status": BoundField(
                label="Status", type="single_select", options=["Open", "Shipped"], state="ok"
            ),
        }
        assert (served.truncated, served.limit, served.count) == (False, None, 1)

    @pytest.mark.security
    async def test_a_link_field_serves_labels_and_a_lookup_only_values(self, db):
        page = await _page(db)
        _products, orders, widget = await _linked(page)
        await page.publish(
            await page.bind("linked", page.query(orders, ref="Ref", items="Items")),
            await page.bind("looked", page.query(orders, ref="Ref", names="Names")),
        )

        data = (await page.data()).bindings

        assert data["linked"].records[0]["items"] == [{"id": str(widget), "label": "Widget"}]
        assert data["looked"].records[0]["names"] == ["Widget"]
        assert str(widget) not in data["looked"].model_dump_json()

    async def test_a_limit_serves_that_many_records(self, db):
        page = await _page(db)
        await _orders(page)
        await page.publish(
            await page.bind(
                "one",
                BindingRequest(table=page.table.id, fields={"customer": "Customer"}, limit=1),
            )
        )

        served = (await page.data()).bindings["one"]

        assert (served.count, served.truncated, served.limit) == (1, True, "records")

    async def test_a_view_edited_after_publishing_changes_nothing(self, db):
        """The view's filters were copied, never linked."""
        page = await _page(db)
        ann, _bob = await _orders(page)
        views = TableViewService(db)
        open_only = RecordFilter(
            column_id=UUID(cid(page.table, "Status")), op="eq", value=page.option("Status", "Open")
        )
        view = await views.create_view(
            page.owner,
            page.table.id,
            TableViewCreate(
                name="Open",
                kind="table",
                visibility="shared",
                config=TableViewConfig(filters=[open_only]),
            ),
        )
        await page.publish(
            await page.bind("open", BindingRequest(view=view.id, fields={"customer": "Customer"}))
        )
        await views.update_view(
            page.owner, page.table.id, view.id, TableViewUpdate(config=TableViewConfig())
        )
        await views.delete_view(page.owner, page.table.id, view.id)

        served = (await page.data()).bindings["open"]

        assert served.records == [{"id": str(ann), "customer": "Ann"}]


class TestSourceChanged:
    """A query reads nothing once what it reaches changed, and only that query."""

    async def _two(self, page: _Page) -> None:
        await _orders(page)
        await page.publish(
            await page.bind("qty", page.query(customer="Customer", qty="Quantity")),
            await page.bind("names", page.query(customer="Customer")),
        )

    async def test_a_column_that_changed_meaning_reads_nothing_naming_it(self, db):
        page = await _page(db)
        await self._two(page)
        await page.reshape(Quantity={"type": "text"})

        data = (await page.data()).bindings

        assert data["qty"] == _unavailable("source_changed", "Quantity")
        assert [record["customer"] for record in data["names"].records] == ["Ann", "Bob"]

    async def test_an_archived_column_reads_nothing(self, db):
        page = await _page(db)
        await self._two(page)
        await page.reshape(Quantity=None)

        data = (await page.data()).bindings

        assert data["qty"] == _unavailable("source_changed", "Quantity")
        assert data["names"].count == 2

    async def test_a_filter_column_that_changed_reads_nothing(self, db):
        page = await _page(db)
        await _orders(page)
        await page.publish(await page.bind("open", _open_only(page, customer="Customer")))
        await page.reshape(Status=None)

        assert (await page.data()).bindings == {"open": _unavailable("source_changed", "Status")}

    async def test_a_renamed_column_still_reads_with_its_new_label(self, db):
        page = await _page(db)
        await self._two(page)
        await page.reshape(Customer={"label": "Client"})

        served = (await page.data()).bindings["names"]

        assert served.fields["customer"].label == "Client"
        assert [record["customer"] for record in served.records] == ["Ann", "Bob"]

    async def test_an_archived_table_reads_nothing(self, db):
        page = await _page(db)
        await self._two(page)
        await page.tables.archive_table(page.owner, page.table.id)

        assert (await page.data()).bindings == {
            "qty": _unavailable("source_changed", "Orders"),
            "names": _unavailable("source_changed", "Orders"),
        }

    async def test_an_archived_linked_table_reads_nothing(self, db):
        """Archiving a linked table bumps no column, so the table itself is checked."""
        page = await _page(db)
        await _orders(page)
        products, orders, _widget = await _linked(page)
        await page.publish(
            await page.bind("linked", page.query(orders, ref="Ref", items="Items")),
            await page.bind("plain", page.query(customer="Customer")),
        )
        await page.tables.archive_table(page.owner, products.id)

        data = (await page.data()).bindings

        assert data["linked"] == _unavailable("source_changed", "Products")
        assert data["plain"].count == 2

    async def test_a_link_naming_its_records_by_another_column_reads_nothing(self, db):
        """`Code` turned to text comes before `Name`, so the links would be labelled by it."""
        page = await _page(db)
        products, orders, _widget = await _linked(page)
        await page.publish(await page.bind("linked", page.query(orders, ref="Ref", items="Items")))
        await page.reshape(products, Code={"type": "text"})

        assert (await page.data()).bindings == {
            "linked": _unavailable("source_changed", "Products")
        }

    async def test_a_query_whose_filter_the_table_no_longer_answers_reads_nothing(self, db):
        """Its reach matches - say a restore re-read it - but `Quantity gt 2` cannot be asked
        of text: that one binding reads nothing, and the page load still answers."""
        page = await _page(db)
        await self._two(page)
        stale = await page.bind(
            "big",
            BindingRequest(
                table=page.table.id,
                fields={"customer": "Customer", "qty": "Quantity"},
                filters=[BindingFilter(column="Quantity", op="gt", value=2)],
            ),
        )
        await page.reshape(Quantity={"type": "text"})
        fresh = await page.bind("big", page.query(customer="Customer", qty="Quantity"))
        names = await page.bind("names", page.query(customer="Customer"))
        await page.publish(stale.model_copy(update={"reach": fresh.reach}), names)

        data = (await page.data()).bindings

        assert data["big"] == _unavailable("source_changed", "Orders")
        assert data["names"].count == 2

    async def test_publishing_again_reads_again(self, db):
        page = await _page(db)
        await self._two(page)
        await page.reshape(Quantity={"type": "text"})
        await page.publish(await page.bind("qty", page.query(customer="Customer", qty="Quantity")))

        served = (await page.data()).bindings["qty"]

        assert [record["qty"] for record in served.records] == ["3", "1"]


class TestTheByteCap:
    async def test_the_byte_cap_is_shared_fairly_whatever_the_order(self, db, monkeypatch):
        page = await _page(db)
        notes = await page.new_table(
            TableCreate(name="Notes", columns=[column("Group", "text"), column("Body", "text")])
        )
        group, body = cid(notes, "Group"), cid(notes, "Body")
        await insert_rows(
            db,
            notes,
            [{group: "small", body: "hi"} for _ in range(2)]
            + [{group: big, body: "x" * 200} for big in ("b1", "b2") for _ in range(30)],
        )

        def notes_of(name: str) -> BindingRequest:
            return BindingRequest(
                table=notes.id,
                fields={"body": "Body"},
                filters=[BindingFilter(column="Group", op="eq", value=name)],
            )

        cap = 4_000
        monkeypatch.setattr(settings, "ARTIFACT_DATA_MAX_BYTES", cap)

        served: list[dict[str, BindingData]] = []
        for names in (
            {"small": "a_small", "b1": "b_big", "b2": "c_big"},
            {"small": "z_small", "b1": "m_big", "b2": "a_big"},
        ):
            await page.publish(
                *[await page.bind(names[key], notes_of(key)) for key in ("small", "b1", "b2")]
            )
            data = (await page.data()).bindings
            served.append({key: data[names[key]] for key in ("small", "b1", "b2")})

        first, second = served
        assert {key: item.count for key, item in first.items()} == {
            key: item.count for key, item in second.items()
        }
        for by_group in served:
            small = sum(shaped_size(record) for record in by_group["small"].records)
            assert (by_group["small"].count, by_group["small"].limit) == (2, None)
            for big in ("b1", "b2"):
                sizes = [shaped_size(record) for record in by_group[big].records]
                assert by_group[big].limit == "bytes"
                assert by_group[big].truncated is True
                assert by_group[big].count == len(sizes)
                assert sum(sizes) <= (cap - small) // 2 + 1
                assert sum(sizes) + sizes[0] > (cap - small) // 2
            total = sum(shaped_size(r) for item in by_group.values() for r in item.records)
            assert total <= cap


SleepFactory = Callable[..., Callable[..., Awaitable[Any]]]


def _sleeping(seconds: float, calls: list[Any] | None = None) -> SleepFactory:
    """Wrap a repository read so `pg_sleep` runs first, under the statement limit just armed."""

    def wrap(original: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        async def call(db: AsyncSession, *args: Any, **kwargs: Any) -> Any:
            if calls is not None:
                calls.append(args[0] if args else kwargs.get("table_id"))
            await db.execute(text("SELECT pg_sleep(:seconds)"), {"seconds": seconds})
            return await original(db, *args, **kwargs)

        return call

    return wrap


async def _statement_timeout(db: AsyncSession) -> str:
    return (await db.execute(text("SELECT current_setting('statement_timeout')"))).scalar_one()


class TestTheDeadline:
    async def test_one_slow_binding_times_out_alone(self, db, monkeypatch):
        page = await _page(db)
        await _orders(page)
        slow_table = await page.new_table(
            TableCreate(name="Slow orders", columns=[column("Customer", "text")])
        )
        await insert_rows(db, slow_table, [{cid(slow_table, "Customer"): "Cy"}])
        await page.publish(
            await page.bind("a_slow", page.query(slow_table, c="Customer")),
            await page.bind("b_fast", page.query(customer="Customer")),
        )
        monkeypatch.setattr(settings, "ARTIFACT_DATA_STATEMENT_TIMEOUT_MS", 200)
        original = virtual_table_repo.list_record_sizes

        async def sizes(db: AsyncSession, *, table_id: UUID, **kwargs: Any) -> Any:
            if table_id == slow_table.id:
                await db.execute(text("SELECT pg_sleep(1)"))
            return await original(db, table_id=table_id, **kwargs)

        monkeypatch.setattr(virtual_table_repo, "list_record_sizes", sizes)
        prior = await _statement_timeout(db)

        data = await page.data()

        assert data.bindings["a_slow"] == _unavailable("timeout")
        assert data.bindings["b_fast"].status == "ok"
        assert data.bindings["b_fast"].count == 2
        assert await _statement_timeout(db) == prior

    async def test_a_page_past_its_budget_answers_timeout_and_commits(self, db, monkeypatch):
        page = await _page(db)
        products, orders, _widget = await _linked(page)
        await page.publish(
            await page.bind("a_first", page.query(orders, ref="Ref", items="Items")),
            await page.bind("b_second", page.query(customer="Customer")),
            await page.bind("c_third", page.query(customer="Customer")),
        )
        monkeypatch.setattr(settings, "ARTIFACT_DATA_READ_TIMEOUT_SECONDS", 1)
        looked_up: list[Any] = []
        for name, calls in (
            ("get_table", looked_up),
            ("get_schema_version", None),
            ("list_record_sizes", None),
            ("get_record_sizes_by_ids", None),
            ("get_record_cells_by_ids", None),
        ):
            monkeypatch.setattr(
                virtual_table_repo,
                name,
                _sleeping(0.15, calls)(getattr(virtual_table_repo, name)),
            )
        prior = await _statement_timeout(db)

        started = time.monotonic()
        data = await page.data()
        elapsed = time.monotonic() - started

        assert data.bindings == {
            "a_first": _unavailable("timeout"),
            "b_second": _unavailable("timeout"),
            "c_third": _unavailable("timeout"),
        }
        # Only the first binding's tables were looked up: the deadline ran out in it,
        # and the other two were answered without a query.
        assert looked_up
        assert set(looked_up) <= {orders.id, products.id}
        assert elapsed < settings.ARTIFACT_DATA_READ_TIMEOUT_SECONDS + 0.5
        assert await _statement_timeout(db) == prior
        await db.commit()
        assert (await db.execute(text("SELECT 1"))).scalar_one() == 1

    @pytest.mark.security
    async def test_a_caught_timeout_logs_no_filter_values(self, db, monkeypatch, caplog):
        page = await _page(db)
        sentinel = f"needle-{uuid.uuid4().hex}"
        await insert_rows(db, page.table, [{cid(page.table, "Customer"): sentinel}])
        await page.publish(
            await page.bind(
                "needle",
                BindingRequest(
                    table=page.table.id,
                    fields={"customer": "Customer"},
                    filters=[BindingFilter(column="Customer", op="eq", value=sentinel)],
                ),
            )
        )
        monkeypatch.setattr(settings, "ARTIFACT_DATA_STATEMENT_TIMEOUT_MS", 200)

        async def sizes(db: AsyncSession, **kwargs: Any) -> Any:
            # Carries the filter value as a bound parameter, as the real query does.
            await db.execute(
                text("SELECT pg_sleep(1), CAST(:needle AS text)"), {"needle": sentinel}
            )
            raise AssertionError("pg_sleep should have been cancelled")

        monkeypatch.setattr(virtual_table_repo, "list_record_sizes", sizes)
        caplog.set_level(logging.DEBUG, logger="app")

        data = await page.data()

        assert data.bindings["needle"] == _unavailable("timeout")
        [logged] = [r for r in caplog.records if r.msg == "artifact_data_binding_unavailable"]
        assert {key: vars(logged)[key] for key in ("binding", "table_id", "reason")} == {
            "binding": "needle",
            "table_id": str(page.table.id),
            "reason": "timeout",
        }
        for record in caplog.records:
            assert sentinel not in record.getMessage()
            assert sentinel not in repr(record.args)
            assert sentinel not in repr(vars(record))
            assert record.exc_info is None
