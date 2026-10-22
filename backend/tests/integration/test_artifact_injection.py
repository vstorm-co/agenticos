"""A page served with its data against a real database: what `content` writes into it.

The content route authenticates only a token, so the data a member's page is served
with is read from the viewer the token names, as they are served now: the consent
rules of `served`, the owner's access, the per-viewer limit and the deadline. These
prove who gets rows, who is told the data waits, that nothing is replayable past the
viewer and version the token names, that a slow binding costs itself alone, and that
no record reaches a log.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.permissions import AuthContext
from app.core.security import create_artifact_view_token
from app.db.models.resource_grant import GrantLevel
from app.repositories import virtual_table_repo
from app.schemas.artifact import ArtifactView
from app.schemas.virtual_table import TableCreate
from app.services.artifact import ArtifactService
from tests.integration.test_artifact_data import _orders, _Page, _page, _unavailable
from tests.integration.virtual_table_support import cid, column, insert_rows

pytestmark = pytest.mark.anyio

PATH = "app.services.artifact"
CONFIG = re.compile(r"\(window, document, (\{.*?\})\);</script>", re.DOTALL)


class _Storage:
    async def load(self, path: str) -> bytes:
        return b"<h1>report</h1>"


def _initial(document: bytes) -> dict[str, dict[str, Any]] | None:
    """The data written into a served page, by binding name, or `None` when there is none."""
    config = json.loads(CONFIG.findall(document.decode())[0])
    if "initial" not in config:
        return None
    return dict(config["initial"])


def _for_page(binding: Any) -> dict[str, Any]:
    """A binding as a served page holds it: without what only the editor's strip is told."""
    return dict(binding.model_dump(mode="json", exclude={"reason", "changed"}))


async def _served(page: _Page, viewer: Any, *, data: bool = True, **named: Any) -> bytes:
    service = ArtifactService(page.db)
    view: ArtifactView = await service.view(viewer, page.artifact.id, data=data, **named)
    with patch(f"{PATH}.get_file_storage", return_value=_Storage()):
        return (await service.content(view.url.rsplit("/", 1)[1])).document


async def _open_page(db: AsyncSession) -> tuple[_Page, Any]:
    page = await _page(db)
    ann, _bob = await _orders(page)
    version = await page.publish(await page.bind("orders", page.query(customer="Customer")))
    await page.consent(version)
    return page, ann


class TestWhoIsServedRows:
    @pytest.mark.security
    async def test_the_owner_s_page_carries_the_rows_on_load(self, db):
        page, _ann = await _open_page(db)

        initial = _initial(await _served(page, page.owner))

        assert initial is not None
        assert initial["orders"]["status"] == "ok"
        assert "reason" not in initial["orders"]
        assert "changed" not in initial["orders"]
        assert sorted(r["customer"] for r in initial["orders"]["records"]) == ["Ann", "Bob"]

    @pytest.mark.security
    async def test_a_consented_audience_is_served_the_rows(self, db):
        page, _ann = await _open_page(db)
        member = await page.person()

        initial = _initial(await _served(page, member))

        assert initial is not None
        assert initial["orders"]["count"] == 2

    @pytest.mark.security
    async def test_an_audience_whose_consent_no_longer_holds_gets_awaiting_consent(self, db):
        page, _ann = await _open_page(db)
        member = await page.person()
        page.artifact.consent_withdrawn_at = datetime.now(UTC) + timedelta(seconds=5)
        await db.flush()

        initial = _initial(await _served(page, member))

        assert initial == {"orders": _for_page(_unavailable("awaiting_consent"))}

    @pytest.mark.security
    async def test_an_editor_on_a_pending_version_gets_awaiting_consent(self, db):
        page, _ann = await _open_page(db)
        await page.publish(await page.bind("orders", page.query(customer="Customer")))
        editor = await page.person(page=GrantLevel.EDIT)

        initial = _initial(await _served(page, editor))

        assert initial == {"orders": _for_page(_unavailable("awaiting_consent"))}

    @pytest.mark.security
    @pytest.mark.parametrize("who", ["owner", "admin"])
    async def test_the_owner_and_the_roles_that_read_every_table_get_rows_on_a_pending_version(
        self, db, who
    ):
        page, _ann = await _open_page(db)
        await page.publish(await page.bind("orders", page.query(customer="Customer")))
        viewer = page.owner if who == "owner" else await page.person(role="admin", page=None)

        initial = _initial(await _served(page, viewer))

        assert initial is not None
        assert initial["orders"]["count"] == 2


class TestWhatGetsNoData:
    async def test_a_view_asked_without_data_serves_none(self, db):
        page, _ann = await _open_page(db)

        assert _initial(await _served(page, page.owner, data=False)) is None

    async def test_an_older_version_serves_none(self, db):
        page, _ann = await _open_page(db)
        older = await page.publish(await page.bind("orders", page.query(customer="Customer")))
        await page.consent(older)
        await page.consent(await page.publish(await page.bind("orders", page.query())))
        latest_number = older.number + 1

        document = await _served(page, page.owner, version_id=older.id)

        assert _initial(document) is None
        assert latest_number > older.number

    @pytest.mark.security
    async def test_a_public_link_and_an_embed_serve_none(self, db):
        page, _ann = await _open_page(db)
        page.artifact.public_key = "public-key-1"
        page.artifact.embed_origins = ["https://a.example.com"]
        await db.flush()
        service = ArtifactService(db)

        public = await service.public_view("public-key-1")
        embed = await service.embed("public-key-1")

        assert public.view is not None
        urls = [
            public.view.url,
            re.search(r'src="([^"]*/artifact-content/[^"]+)"', embed.document.decode()).group(1),
        ]
        for url in urls:
            with patch(f"{PATH}.get_file_storage", return_value=_Storage()):
                served = await service.content(url.rsplit("/", 1)[1])
            assert _initial(served.document) is None
            assert served.embed_origins == ["https://a.example.com"]

    @pytest.mark.security
    async def test_a_member_s_address_is_framed_by_the_console_alone(self, db):
        page, _ann = await _open_page(db)
        page.artifact.public_key = "public-key-2"
        page.artifact.embed_origins = ["https://a.example.com"]
        await db.flush()
        service = ArtifactService(db)
        view = await service.view(page.owner, page.artifact.id, data=True)

        with patch(f"{PATH}.get_file_storage", return_value=_Storage()):
            served = await service.content(view.url.rsplit("/", 1)[1])

        assert served.embed_origins == []


class TestTheMintedSummary:
    async def test_the_view_says_how_many_bindings_and_whether_the_data_waits(self, db):
        page, _ann = await _open_page(db)
        member = await page.person()
        await page.publish(await page.bind("orders", page.query(customer="Customer")))
        service = ArtifactService(db)

        owner_view = await service.view(page.owner, page.artifact.id, data=True)
        audience_view = await service.view(member, page.artifact.id, data=True)

        assert (owner_view.bindings, owner_view.awaiting_consent) == (1, False)
        # The audience is still served the consented version, so its data does not wait.
        assert (audience_view.bindings, audience_view.awaiting_consent) == (1, False)
        page.artifact.consent_withdrawn_at = datetime.now(UTC) + timedelta(seconds=5)
        await db.flush()
        waiting = await service.view(member, page.artifact.id, data=True)
        assert (waiting.bindings, waiting.awaiting_consent) == (1, True)

    @pytest.mark.security
    async def test_an_app_admin_who_is_not_a_member_is_not_served_data(self, db):
        page, _ann = await _open_page(db)
        outsider = AuthContext(
            user_id=uuid.uuid4(),
            organization_id=page.org.id,
            role="owner",
            is_app_admin=True,
        )

        view = await ArtifactService(db).view(outsider, page.artifact.id, data=True)

        assert view.injected is False
        assert view.live is True


class TestReplay:
    def _token(self, version_id: uuid.UUID, *, user_id: uuid.UUID, org_id: uuid.UUID) -> str:
        return create_artifact_view_token(
            version_id,
            expires_in=timedelta(minutes=5),
            nonce="n0",
            live=True,
            audience="member",
            user_id=user_id,
            organization_id=org_id,
            inject=True,
        )

    async def _content(self, page: _Page, token: str) -> bytes:
        with patch(f"{PATH}.get_file_storage", return_value=_Storage()):
            return (await ArtifactService(page.db).content(token)).document

    @pytest.mark.security
    async def test_a_token_naming_another_organization_reads_nothing(self, db):
        page, _ann = await _open_page(db)
        version = await page.publish(await page.bind("orders", page.query(customer="Customer")))
        other = await _page(db)

        token = self._token(version.id, user_id=page.owner.user_id, org_id=other.org.id)

        assert _initial(await self._content(page, token)) == {
            "orders": _for_page(_unavailable(None))
        }

    @pytest.mark.security
    async def test_a_token_naming_someone_who_is_not_a_member_reads_nothing(self, db):
        page, _ann = await _open_page(db)
        version = await page.publish(await page.bind("orders", page.query(customer="Customer")))
        stranger = (await _page(db)).owner

        token = self._token(version.id, user_id=stranger.user_id, org_id=page.org.id)

        assert _initial(await self._content(page, token)) == {
            "orders": _for_page(_unavailable(None))
        }

    @pytest.mark.security
    async def test_a_member_who_may_not_open_the_page_reads_nothing(self, db):
        page, _ann = await _open_page(db)
        outsider = await page.person(page=None)
        version = await page.publish(await page.bind("orders", page.query(customer="Customer")))
        await page.consent(version)

        token = self._token(version.id, user_id=outsider.user_id, org_id=page.org.id)

        assert _initial(await self._content(page, token)) == {
            "orders": _for_page(_unavailable(None))
        }

    @pytest.mark.security
    async def test_a_version_the_viewer_is_no_longer_served_reads_nothing(self, db):
        page, _ann = await _open_page(db)
        older = await page.publish(await page.bind("orders", page.query(customer="Customer")))
        await page.consent(older)
        await page.consent(await page.publish(await page.bind("orders", page.query())))
        member = await page.person()

        token = self._token(older.id, user_id=member.user_id, org_id=page.org.id)

        # The page is never told why, whoever it is served to.
        assert _initial(await self._content(page, token)) == {
            "orders": _for_page(_unavailable(None))
        }
        owner_token = self._token(older.id, user_id=page.owner.user_id, org_id=page.org.id)
        assert _initial(await self._content(page, owner_token)) == {
            "orders": _for_page(_unavailable("not_current"))
        }


class TestTheBudget:
    async def test_a_slow_binding_is_unavailable_and_the_page_still_renders(self, db, monkeypatch):
        page = await _page(db)
        await _orders(page)
        slow_table = await page.new_table(
            TableCreate(name="Slow orders", columns=[column("Customer", "text")])
        )
        await insert_rows(db, slow_table, [{cid(slow_table, "Customer"): "Cy"}])
        await page.consent(
            await page.publish(
                await page.bind("a_slow", page.query(slow_table, c="Customer")),
                await page.bind("b_fast", page.query(customer="Customer")),
            )
        )
        monkeypatch.setattr(settings, "ARTIFACT_DATA_STATEMENT_TIMEOUT_MS", 200)
        original = virtual_table_repo.list_record_sizes

        async def sizes(db: AsyncSession, *, table_id: uuid.UUID, **kwargs: Any) -> Any:
            if table_id == slow_table.id:
                await db.execute(text("SELECT pg_sleep(1)"))
            return await original(db, table_id=table_id, **kwargs)

        monkeypatch.setattr(virtual_table_repo, "list_record_sizes", sizes)

        document = await _served(page, page.owner)

        initial = _initial(document)
        assert initial is not None
        assert initial["a_slow"] == _for_page(_unavailable("timeout"))
        assert initial["b_fast"]["status"] == "ok"
        assert b"<h1>report</h1>" in document

    async def test_a_binding_the_database_fails_is_failed_and_the_page_renders(
        self, db, monkeypatch
    ):
        page, _ann = await _open_page(db)

        async def broken(*args: Any, **kwargs: Any) -> Any:
            await db.execute(text("SELECT 1/0"))

        monkeypatch.setattr(virtual_table_repo, "list_record_sizes", broken)

        document = await _served(page, page.owner)

        assert _initial(document) == {"orders": _for_page(_unavailable("failed"))}
        assert b"<h1>report</h1>" in document


class TestAFailureIsLogged:
    @pytest.mark.security
    async def test_a_database_error_is_logged_by_type_and_state_never_by_message(
        self, db, monkeypatch, caplog
    ):
        page, _ann = await _open_page(db)

        async def broken(*args: Any, **kwargs: Any) -> Any:
            await db.execute(text("SELECT 1/0 + length('needle-secret')"))

        monkeypatch.setattr(virtual_table_repo, "list_record_sizes", broken)
        caplog.set_level(logging.WARNING)

        await _served(page, page.owner)

        failed = [r for r in caplog.records if r.getMessage() == "artifact_data_binding_failed"]
        assert len(failed) == 1
        assert failed[0].binding == "orders"
        assert failed[0].error_type.endswith("Error")
        assert failed[0].sqlstate == "22012"
        for record in caplog.records:
            assert "needle-secret" not in record.getMessage()
            assert "needle-secret" not in repr(vars(record))


class TestTheViewerLimit:
    @pytest.mark.security
    async def test_injected_loads_count_against_the_viewer_s_data_limit(self, db, monkeypatch):
        page, _ann = await _open_page(db)
        monkeypatch.setattr(settings, "RATE_LIMIT_ARTIFACT_DATA_PER_MINUTE", 2)

        loads = [_initial(await _served(page, page.owner)) for _ in range(3)]

        assert [load["orders"]["status"] for load in loads if load] == [
            "ok",
            "ok",
            "unavailable",
        ]
        assert loads[2] == {"orders": _for_page(_unavailable("busy"))}

    async def test_a_load_already_in_flight_is_busy_and_the_page_renders(self, db):
        page, _ann = await _open_page(db)
        from contextlib import asynccontextmanager

        from app.core.exceptions import RateLimitError

        @asynccontextmanager
        async def held(*args: Any, **kwargs: Any) -> Any:
            raise RateLimitError(message="held")
            yield

        with patch(f"{PATH}.rate_limit.one_in_flight", held):
            document = await _served(page, page.owner)

        assert _initial(document) == {"orders": _for_page(_unavailable("busy"))}

    async def test_a_process_serving_as_many_loads_as_it_may_is_busy(self, db):
        page, _ann = await _open_page(db)
        gate = MagicMock()
        gate.locked.return_value = True

        with patch(f"{PATH}._load_gate", return_value=gate):
            document = await _served(page, page.owner)

        assert _initial(document) == {"orders": _for_page(_unavailable("busy"))}


class TestNoRecordInALog:
    @pytest.mark.security
    async def test_an_injected_record_never_reaches_a_log(self, db, caplog):
        page = await _page(db)
        sentinel = f"needle-{uuid.uuid4().hex}"
        await insert_rows(db, page.table, [{cid(page.table, "Customer"): sentinel}])
        await page.consent(
            await page.publish(await page.bind("orders", page.query(customer="Customer")))
        )
        caplog.set_level(logging.DEBUG)

        document = await _served(page, page.owner)

        assert sentinel in document.decode()
        for record in caplog.records:
            assert sentinel not in record.getMessage()
            assert sentinel not in repr(vars(record))
