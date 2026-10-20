"""A page's live data against a real database: each binding read as the viewer, within the limits.

`ArtifactService.data` reads every binding of a page version with the viewer's own
access, so what one viewer is served says nothing about what another may see. These
prove the refusals (a binding the viewer may not read is `unavailable`, and only an
editor hears why), the payload (named fields and the id, nothing else), the drift
rules, the fair byte split and the deadline, which stops a slow page without ever
cancelling a query from Python.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.artifact import Artifact, ArtifactMediaType, ArtifactVersion
from app.db.models.organization import Organization
from app.db.models.resource_grant import GrantLevel
from app.repositories import artifact_repo, resource_grant_repo, table_view_repo, virtual_table_repo
from app.schemas.artifact import ArtifactBinding, ArtifactData, BindingData, BoundField
from app.schemas.table_view import TableViewConfig, TableViewCreate
from app.schemas.virtual_table import (
    ColumnDef,
    ColumnInput,
    OptionInput,
    RecordFilter,
    SchemaUpdate,
    TableCreate,
    TableRead,
)
from app.services.access import ARTIFACT, TABLE
from app.services.artifact import ArtifactService
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
    views: TableViewService
    table: TableRead
    artifact: Artifact
    numbers: list[int] = field(default_factory=list)

    def col(self, label: str, table: TableRead | None = None) -> UUID:
        return next(c.id for c in (table or self.table).columns if c.label == label)

    def option(self, label: str, choice: str) -> str:
        column_def = next(c for c in self.table.columns if c.label == label)
        return str(next(o.id for o in column_def.options if o.label == choice))

    async def view(
        self,
        *,
        by: AuthContext | None = None,
        table: TableRead | None = None,
        visibility: Literal["private", "shared"] = "shared",
        config: TableViewConfig | None = None,
    ) -> UUID:
        created = await self.views.create_view(
            by or self.owner,
            (table or self.table).id,
            TableViewCreate(
                name=f"View {uuid.uuid4().hex[:6]}",
                kind="table",
                visibility=visibility,
                config=config or TableViewConfig(),
            ),
        )
        return created.id

    def bind(
        self, name: str, view_id: UUID, *, table: TableRead | None = None, **fields: str
    ) -> ArtifactBinding:
        """A stored binding, its fields given by column label."""
        table = table or self.table
        return ArtifactBinding(
            name=name,
            view_id=view_id,
            table_id=table.id,
            fields={key: self.col(label, table) for key, label in fields.items()},
        )

    async def publish(self, *bindings: ArtifactBinding) -> ArtifactVersion:
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
        )

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
        table_grant: GrantLevel | None = None,
        table: TableRead | None = None,
        sees_page: bool = True,
        is_app_admin: bool = False,
    ) -> AuthContext:
        """Another person in the organization, holding the grants asked for."""
        user = await make_user(self.db)
        if sees_page:
            await self._grant(user.id, ARTIFACT.key, self.artifact.id, GrantLevel.READ)
        if table_grant is not None:
            await self._grant(user.id, TABLE.key, (table or self.table).id, table_grant)
        return AuthContext(
            user_id=user.id, organization_id=self.org.id, role=role, is_app_admin=is_app_admin
        )

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

    async def reshape(
        self,
        by: AuthContext | None = None,
        **changes: dict[str, Any] | None,
    ) -> None:
        """Change the table's schema: each label to its column's changes, `None` to archive it."""
        current = await self.tables.describe_table(self.owner, self.table.id)
        columns = [
            _kept(c, **(changes.get(c.label) or {}))
            for c in current.columns
            if not c.archived and not (c.label in changes and changes[c.label] is None)
        ]
        self.table = await self.tables.update_schema(
            by or self.owner,
            current.id,
            SchemaUpdate(expected_version=current.schema_version, columns=columns),
        )


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
    return _Page(db, org, owner, tables, TableViewService(db), table, artifact)


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


def _unavailable(reason: str | None) -> BindingData:
    return BindingData(
        status="unavailable",
        reason=reason,
        truncated=False,
        limit=None,
        count=0,
        filters_dropped=False,
        fields={},
        records=[],
    )


class TestWhoReads:
    @pytest.mark.security
    async def test_a_member_without_the_table_gets_unavailable_and_no_reason(self, db):
        page = await _page(db)
        await _orders(page)
        await page.publish(page.bind("tickets", await page.view(), customer="Customer"))
        member = await page.person()

        data = await page.data(member)

        assert data.bindings == {"tickets": _unavailable(None)}

    @pytest.mark.security
    async def test_an_editor_sees_why_a_binding_is_unavailable(self, db):
        page = await _page(db)
        view_id = await page.view()
        await page.publish(page.bind("tickets", view_id, customer="Customer"))
        await page.views.delete_view(page.owner, page.table.id, view_id)
        reader = await page.person(table_grant=GrantLevel.READ)

        assert (await page.data()).bindings == {"tickets": _unavailable("no_access")}
        assert (await page.data(reader)).bindings == {"tickets": _unavailable(None)}

    @pytest.mark.security
    async def test_another_member_s_private_view_is_unavailable_even_to_an_org_owner(self, db):
        page = await _page(db)
        await _orders(page)
        colleague = await page.person(role="admin")
        view_id = await page.view(by=colleague, visibility="private")
        await page.publish(page.bind("mine", view_id, customer="Customer"))

        assert (await page.data()).bindings == {"mine": _unavailable("no_access")}
        assert (await page.data(colleague)).bindings["mine"].count == 2

    @pytest.mark.security
    async def test_another_member_s_private_view_is_unavailable_to_a_member_app_admin(self, db):
        page = await _page(db)
        await _orders(page)
        colleague = await page.person(role="admin")
        view_id = await page.view(by=colleague, visibility="private")
        await page.publish(page.bind("mine", view_id, customer="Customer"))
        app_admin = await page.person(sees_page=False, is_app_admin=True)

        assert (await page.data(app_admin)).bindings == {"mine": _unavailable("no_access")}

    @pytest.mark.security
    async def test_impersonation_reads_as_the_impersonated_member(self, db):
        """An impersonated session's context is the member's own, so is what it reads."""
        page = await _page(db)
        await _orders(page)
        member = await page.person(role="admin")
        own = await page.view(by=member, visibility="private")
        await page.publish(page.bind("own", own, customer="Customer"))
        impersonated = AuthContext(
            user_id=member.user_id, organization_id=page.org.id, role=member.role
        )

        assert (await page.data(impersonated)).bindings["own"].status == "ok"
        assert (await page.data()).bindings["own"].status == "unavailable"

    @pytest.mark.security
    async def test_a_view_in_another_org_never_answers(self, db):
        page = await _page(db)
        stranger = await make_user(db)
        elsewhere = await make_org(db, owner=stranger)
        theirs = ctx_for(stranger, elsewhere)
        their_table = await orders_table(page.tables, theirs, name="Their orders")
        await insert_rows(db, their_table, [{cid(their_table, "Customer"): "Secret"}])
        their_view = await page.views.create_view(
            theirs,
            their_table.id,
            TableViewCreate(name="All", kind="table", visibility="shared"),
        )
        await page.publish(page.bind("theirs", their_view.id, table=their_table, c="Customer"))

        data = await page.data()

        assert data.bindings == {"theirs": _unavailable("no_access")}
        assert "Secret" not in data.model_dump_json()

    async def test_an_older_version_gets_not_current(self, db):
        page = await _page(db)
        await _orders(page)
        binding = page.bind("tickets", await page.view(), customer="Customer")
        first = await page.publish(binding)
        second = await page.publish(binding)

        older, newest = await page.data(version=first), await page.data(version=second)

        assert older.bindings == {"tickets": _unavailable("not_current")}
        assert older.current is False
        assert newest.bindings["tickets"].count == 2
        assert newest.current is True

    async def test_a_binding_restored_unavailable_keeps_its_stored_reason(self, db):
        page = await _page(db)
        binding = page.bind("tickets", await page.view(), customer="Customer")
        await page.publish(
            binding.model_copy(update={"status": "unavailable", "reason": "table_not_granted"})
        )

        assert (await page.data()).bindings == {"tickets": _unavailable("table_not_granted")}


class TestThePayload:
    @pytest.mark.security
    async def test_only_named_fields_and_the_id_are_sent(self, db):
        page = await _page(db)
        ann, bob = await _orders(page)
        await page.publish(
            page.bind("tickets", await page.view(), customer="Customer", status="Status")
        )

        served = (await page.data()).bindings["tickets"]

        assert served.status == "ok"
        assert served.records == [
            {"id": str(ann), "customer": "Ann", "status": "Open"},
            {"id": str(bob), "customer": "Bob", "status": "Shipped"},
        ]
        for record in served.records:
            assert not FORBIDDEN_KEYS & set(record)
        assert served.fields == {
            "customer": BoundField(label="Customer", type="text", state="ok"),
            "status": BoundField(
                label="Status", type="single_select", options=["Open", "Shipped"], state="ok"
            ),
        }
        assert (served.truncated, served.limit, served.count) == (False, None, 2)
        assert served.filters_dropped is False

    @pytest.mark.security
    async def test_a_link_field_comes_from_links_not_raw_ids(self, db):
        page = await _page(db)
        products = await page.tables.create_table(
            page.owner, TableCreate(name="Products", columns=[column("Name", "text")])
        )
        orders = await page.tables.create_table(
            page.owner,
            TableCreate(
                name="Linked orders",
                columns=[column("Ref", "text"), column("Items", "link", link_table_id=products.id)],
            ),
        )
        [widget] = await insert_rows(db, products, [{cid(products, "Name"): "Widget"}])
        await insert_rows(
            db, orders, [{cid(orders, "Ref"): "A-1", cid(orders, "Items"): [str(widget)]}]
        )
        view_id = await page.view(table=orders)
        await page.publish(page.bind("orders", view_id, table=orders, ref="Ref", items="Items"))
        reader = await page.person(table_grant=GrantLevel.READ, table=orders)

        owned = (await page.data()).bindings["orders"]
        read = (await page.data(reader)).bindings["orders"]

        assert owned.records[0]["items"] == [{"id": str(widget), "label": "Widget"}]
        assert read.status == "ok"
        assert read.records[0]["items"] == []
        assert str(widget) not in json.dumps(read.records)


class TestDrift:
    async def test_a_renamed_column_keeps_its_field_name_with_the_new_label(self, db):
        page = await _page(db)
        await _orders(page)
        await page.publish(page.bind("tickets", await page.view(), customer="Customer"))
        await page.reshape(Customer={"label": "Client"})

        served = (await page.data()).bindings["tickets"]

        assert served.fields["customer"].label == "Client"
        assert [record["customer"] for record in served.records] == ["Ann", "Bob"]

    async def test_an_archived_field_is_null_with_state_archived(self, db):
        page = await _page(db)
        await _orders(page)
        await page.publish(
            page.bind("tickets", await page.view(), customer="Customer", qty="Quantity")
        )
        await page.reshape(Quantity=None)

        served = (await page.data()).bindings["tickets"]

        assert served.fields["qty"].state == "archived"
        assert [record["qty"] for record in served.records] == [None, None]
        assert [record["customer"] for record in served.records] == ["Ann", "Bob"]

    async def test_a_missing_column_is_null_with_state_missing(self, db):
        page = await _page(db)
        await _orders(page)
        binding = page.bind("tickets", await page.view(), customer="Customer")
        gone = uuid.uuid4()
        await page.publish(binding.model_copy(update={"fields": {**binding.fields, "gone": gone}}))

        served = (await page.data()).bindings["tickets"]

        assert served.fields["gone"] == BoundField(label="gone", type="text", state="missing")
        assert [record["gone"] for record in served.records] == [None, None]

    async def test_a_changed_type_is_served_in_the_new_type(self, db):
        page = await _page(db)
        await _orders(page)
        await page.publish(page.bind("tickets", await page.view(), qty="Quantity"))
        await page.reshape(Quantity={"type": "text"})

        served = (await page.data()).bindings["tickets"]

        assert served.fields["qty"].type == "text"
        assert [record["qty"] for record in served.records] == ["3", "1"]

    async def test_an_archived_table_is_unavailable(self, db):
        page = await _page(db)
        await page.publish(page.bind("tickets", await page.view(), customer="Customer"))
        await page.tables.archive_table(page.owner, page.table.id)

        assert (await page.data()).bindings == {"tickets": _unavailable("table_archived")}

    async def test_a_view_broken_by_a_retyped_column_is_unavailable_with_view_invalid(self, db):
        page = await _page(db)
        await _orders(page)
        colleague = await page.person(role="admin")
        quantity = page.col("Quantity")
        view_id = await page.view(
            by=colleague,
            config=TableViewConfig(filters=[RecordFilter(column_id=quantity, op="gt", value=2)]),
        )
        await page.publish(page.bind("big", view_id, customer="Customer"))
        builder = await page.person(role="builder", table_grant=GrantLevel.EDIT)
        await page.reshape(builder, Quantity={"type": "text"})

        assert (await page.data()).bindings == {"big": _unavailable("view_invalid")}

    async def test_a_filter_on_an_archived_column_is_dropped_and_reported(self, db):
        page = await _page(db)
        await _orders(page)
        colleague = await page.person(role="admin")
        status = page.col("Status")
        open_only = TableViewConfig(
            filters=[RecordFilter(column_id=status, op="eq", value=page.option("Status", "Open"))]
        )
        view_id = await page.view(by=colleague, config=open_only)
        await page.publish(page.bind("open", view_id, customer="Customer"))
        assert (await page.data()).bindings["open"].count == 1
        builder = await page.person(role="builder", table_grant=GrantLevel.EDIT)
        await page.reshape(builder, Status=None)

        served = (await page.data()).bindings["open"]

        assert served.filters_dropped is True
        assert [record["customer"] for record in served.records] == ["Ann", "Bob"]


class TestTheByteCap:
    async def test_the_byte_cap_is_shared_fairly_whatever_the_order(self, db, monkeypatch):
        page = await _page(db)
        notes = await page.tables.create_table(
            page.owner,
            TableCreate(name="Notes", columns=[column("Group", "text"), column("Body", "text")]),
        )
        group, body = cid(notes, "Group"), cid(notes, "Body")
        await insert_rows(
            db,
            notes,
            [{group: "small", body: "hi"} for _ in range(2)]
            + [{group: big, body: "x" * 200} for big in ("b1", "b2") for _ in range(30)],
        )
        views = {}
        for name in ("small", "b1", "b2"):
            views[name] = await page.view(
                table=notes,
                config=TableViewConfig(
                    filters=[RecordFilter(column_id=UUID(group), op="eq", value=name)]
                ),
            )
        cap = 4_000
        monkeypatch.setattr(settings, "ARTIFACT_DATA_MAX_BYTES", cap)

        served: list[dict[str, BindingData]] = []
        for names in (
            {"small": "a_small", "b1": "b_big", "b2": "c_big"},
            {"small": "z_small", "b1": "m_big", "b2": "a_big"},
        ):
            await page.publish(
                *(
                    page.bind(names[key], views[key], table=notes, body="Body")
                    for key in ("small", "b1", "b2")
                )
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
                calls.append(kwargs.get("view_id"))
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
        slow_table = await orders_table(page.tables, page.owner, name="Slow orders")
        await insert_rows(db, slow_table, [{cid(slow_table, "Customer"): "Cy"}])
        await page.publish(
            page.bind("a_slow", await page.view(table=slow_table), table=slow_table, c="Customer"),
            page.bind("b_fast", await page.view(), customer="Customer"),
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
        products = await page.tables.create_table(
            page.owner, TableCreate(name="Products", columns=[column("Name", "text")])
        )
        orders = await page.tables.create_table(
            page.owner,
            TableCreate(
                name="Linked orders",
                columns=[column("Ref", "text"), column("Items", "link", link_table_id=products.id)],
            ),
        )
        [widget] = await insert_rows(db, products, [{cid(products, "Name"): "Widget"}])
        await insert_rows(
            db, orders, [{cid(orders, "Ref"): "A-1", cid(orders, "Items"): [str(widget)]}]
        )
        first = await page.view(table=orders)
        second, third = await page.view(), await page.view()
        await page.publish(
            page.bind("a_first", first, table=orders, ref="Ref", items="Items"),
            page.bind("b_second", second, customer="Customer"),
            page.bind("c_third", third, customer="Customer"),
        )
        monkeypatch.setattr(settings, "ARTIFACT_DATA_READ_TIMEOUT_SECONDS", 1)
        viewed: list[Any] = []
        for module, name, calls in (
            (table_view_repo, "get", viewed),
            (virtual_table_repo, "get_table", None),
            (virtual_table_repo, "get_schema_version", None),
            (virtual_table_repo, "list_record_sizes", None),
            (virtual_table_repo, "get_record_sizes_by_ids", None),
            (virtual_table_repo, "get_record_cells_by_ids", None),
        ):
            monkeypatch.setattr(module, name, _sleeping(0.15, calls)(getattr(module, name)))
        prior = await _statement_timeout(db)

        started = time.monotonic()
        data = await page.data()
        elapsed = time.monotonic() - started

        assert data.bindings == {
            "a_first": _unavailable("timeout"),
            "b_second": _unavailable("timeout"),
            "c_third": _unavailable("timeout"),
        }
        # Only the first binding's view was looked up: the deadline ran out in it,
        # and the other two were answered without a query.
        assert viewed == [first]
        assert elapsed < settings.ARTIFACT_DATA_READ_TIMEOUT_SECONDS + 0.5
        assert await _statement_timeout(db) == prior
        await db.commit()
        assert (await db.execute(text("SELECT 1"))).scalar_one() == 1

    @pytest.mark.security
    async def test_a_caught_timeout_logs_no_filter_values(self, db, monkeypatch, caplog):
        page = await _page(db)
        sentinel = f"needle-{uuid.uuid4().hex}"
        await insert_rows(db, page.table, [{cid(page.table, "Customer"): sentinel}])
        view_id = await page.view(
            config=TableViewConfig(
                filters=[RecordFilter(column_id=page.col("Customer"), op="eq", value=sentinel)]
            )
        )
        await page.publish(page.bind("needle", view_id, customer="Customer"))
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
        assert {key: vars(logged)[key] for key in ("binding", "view_id", "reason")} == {
            "binding": "needle",
            "view_id": str(view_id),
            "reason": "timeout",
        }
        for record in caplog.records:
            assert sentinel not in record.getMessage()
            assert sentinel not in repr(record.args)
            assert sentinel not in repr(vars(record))
            assert record.exc_info is None
