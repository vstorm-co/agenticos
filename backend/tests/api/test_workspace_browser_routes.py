"""Browsing the workspaces a caller can see.

Who sees which is the service's answer, proven in
`tests/test_sandbox_workspace.py::TestWorkspacesAreScopedToTheirReader` - these
routes carry no gate precisely because a role gate refused a member their own
files. What is left here is the shape, and two properties behind it: the listing
carries no files, because a deployment can hold one per warm conversation and
reading each to render a table would be a round trip per row; and the flat view
says what it left out, because a shorter list is otherwise indistinguishable from
fewer files.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services.sandbox_workspace import FlatEntry, MeasuredWorkspaces, WorkspaceContents

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid.uuid4()
_WORKSPACE_ID = uuid.uuid4()
_AGENT_ID = uuid.uuid4()


def _row(**overrides: Any) -> MagicMock:
    row = MagicMock(
        id=_WORKSPACE_ID,
        agent_id=_AGENT_ID,
        conversation_id=uuid.uuid4(),
        scope="conversation",
        backend="state",
        bytes_total=2048,
        version=3,
        last_used_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _overview(**overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "row": _row(),
        "agent_name": "Analyst",
        "agent_has_avatar": True,
        "conversation_title": "Refund policy",
        "conversation_is_callers": True,
        "conversations": 1,
        "access_label": "Whoever is in that conversation",
    }
    return SimpleNamespace(**{**fields, **overrides})


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.visible_to = AsyncMock(return_value=[_overview()])
    # The route counts files as well as listing rows, and a `MagicMock` returns
    # something no `await` accepts - which surfaced as an asyncpg error, because the
    # failing request's session tried to roll back against a database these tests
    # do not have.
    stub.measured = AsyncMock(
        return_value=MeasuredWorkspaces(counts={}, measured=0, unreadable=0, truncated=False)
    )
    stub.flat_files = AsyncMock(
        return_value=SimpleNamespace(
            files=[
                FlatEntry(
                    overview=_overview(),
                    info={"path": "/report.csv", "size": 12, "is_dir": False},
                    preview=None,
                    thumbnail=None,
                )
            ],
            workspaces_read=1,
            unreadable=0,
            truncated=False,
        )
    )
    stub.files_of = AsyncMock(
        return_value=(
            _row(),
            WorkspaceContents(
                entries=[{"path": "/uploads/report.csv", "size": 128, "is_dir": False}]
            ),
        )
    )
    stub.read_file_of = AsyncMock(return_value="month,total")
    stub.read_bytes_of = AsyncMock(return_value=b"month,total")
    return stub


@pytest.fixture
def client(service: MagicMock, mock_redis: MagicMock) -> Iterator[Any]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_sandbox_workspace_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(tail: str) -> str:
    return f"{settings.API_V1_STR}/sandbox-workspaces{tail}"


class TestListing:
    async def test_a_workspace_is_named_by_its_agent_and_who_shares_it(self, client) -> None:
        async with client() as opened:
            response = await opened.get(_url(""))

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["agent_name"] == "Analyst"
        assert body["items"][0]["owner_label"] == "This conversation"
        assert body["items"][0]["bytes_total"] == 2048
        # What the table needs beside a row: the chat these files came from, named
        # rather than left as an id, and who can see them - plus the face and the
        # ownership flag the row draws its avatar and chat link from.
        assert body["items"][0]["conversation_title"] == "Refund policy"
        assert body["items"][0]["access_label"] == "Whoever is in that conversation"
        assert body["items"][0]["agent_has_avatar"] is True
        assert body["items"][0]["conversation_is_mine"] is True

    async def test_the_listing_carries_no_files(self, client) -> None:
        """One per warm conversation, and reading each would be a round trip per
        row for a page nobody has asked a question of yet."""
        async with client() as opened:
            response = await opened.get(_url(""))

        assert "items" in response.json()
        assert "files" not in response.json()["items"][0]

    async def test_an_organization_with_none_says_zero_rather_than_failing(
        self, client, service
    ) -> None:
        service.visible_to = AsyncMock(return_value=[])

        async with client() as opened:
            response = await opened.get(_url(""))

        assert response.status_code == 200
        assert response.json() == {
            "items": [],
            "total": 0,
            # What the count cost, which is nothing when there is nothing to count.
            "measured": 0,
            "unreadable": 0,
            "truncated": False,
        }


class TestServingBytes:
    """A download and a preview, and the disposition rule behind both.

    Almost everything is an attachment. Raster images and PDFs are served for
    display - a raster cannot execute, and a PDF is rendered by the browser's own
    viewer, which never gets the embedding page's DOM. An SVG served inline from
    this origin is stored cross-site scripting written by whatever the agent decided
    to save, and "the agent wrote it" is not a trust boundary.
    """

    async def test_a_png_is_served_for_display(self, client, service) -> None:
        service.read_bytes_of = AsyncMock(return_value=b"\x89PNG\r\n")

        async with client() as opened:
            response = await opened.get(
                _url(f"/{_WORKSPACE_ID}/raw"), params={"path": "/chart.png"}
            )

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["content-disposition"].startswith("inline")
        assert response.content == b"\x89PNG\r\n"

    async def test_a_pdf_is_served_for_display(self, client, service) -> None:
        """The one format people already read in a browser. Without this the viewer
        could only offer to download a report the agent had just written."""
        service.read_bytes_of = AsyncMock(return_value=b"%PDF-1.7")

        async with client() as opened:
            response = await opened.get(
                _url(f"/{_WORKSPACE_ID}/raw"), params={"path": "/report.pdf"}
            )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"].startswith("inline")

    async def test_nothing_is_left_for_a_browser_to_sniff(self, client, service) -> None:
        """Everything off the inline list is typed `application/octet-stream`, and
        sniffing would hand back the inline-script hole that list refuses."""
        service.read_bytes_of = AsyncMock(return_value=b"<script>alert(1)</script>")

        async with client() as opened:
            response = await opened.get(_url(f"/{_WORKSPACE_ID}/raw"), params={"path": "/x.html"})

        assert response.headers["x-content-type-options"] == "nosniff"

    async def test_an_svg_is_downloadable_and_never_displayable(self, client, service) -> None:
        """It carries script. Inline, from this origin, that is a hole with the
        agent as its author."""
        service.read_bytes_of = AsyncMock(return_value=b"<svg onload=alert(1)>")

        async with client() as opened:
            response = await opened.get(_url(f"/{_WORKSPACE_ID}/raw"), params={"path": "/x.svg"})

        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-disposition"].startswith("attachment")

    async def test_html_is_treated_the_same_way(self, client, service) -> None:
        service.read_bytes_of = AsyncMock(return_value=b"<script>alert(1)</script>")

        async with client() as opened:
            response = await opened.get(_url(f"/{_WORKSPACE_ID}/raw"), params={"path": "/x.html"})

        assert response.headers["content-type"] == "application/octet-stream"

    async def test_a_download_is_forced_when_asked_even_for_an_image(self, client, service) -> None:
        service.read_bytes_of = AsyncMock(return_value=b"\x89PNG")

        async with client() as opened:
            response = await opened.get(
                _url(f"/{_WORKSPACE_ID}/raw"), params={"path": "/chart.png", "download": "true"}
            )

        assert response.headers["content-disposition"].startswith("attachment")

    async def test_the_filename_is_encoded_rather_than_quoted(self, client, service) -> None:
        """A workspace path can hold any UTF-8, and the bare `filename` form has no
        way to say so - a quote or a newline in it is header injection."""
        service.read_bytes_of = AsyncMock(return_value=b"a,b")

        async with client() as opened:
            response = await opened.get(
                _url(f"/{_WORKSPACE_ID}/raw"), params={"path": "/raport wrzesień.csv"}
            )

        assert (
            "filename*=UTF-8''raport%20wrzesie%C5%84.csv"
            in (response.headers["content-disposition"])
        )

    async def test_a_path_that_names_no_file_still_gets_a_name(self, client, service) -> None:
        service.read_bytes_of = AsyncMock(return_value=b"")

        async with client() as opened:
            response = await opened.get(_url(f"/{_WORKSPACE_ID}/raw"), params={"path": "/"})

        assert "filename*=UTF-8''file" in response.headers["content-disposition"]

    async def test_asking_for_bytes_without_naming_a_file_is_refused(self, client, service) -> None:
        async with client() as opened:
            response = await opened.get(_url(f"/{_WORKSPACE_ID}/raw"))

        assert response.status_code == 422
        service.read_bytes_of.assert_not_called()


class TestAHostThatCannotBeRead:
    async def test_the_reason_is_part_of_the_answer(self, client, service) -> None:
        """Rather than a 500, which reads as "something went wrong" beside an empty
        folder, which reads as "there are no files"."""
        service.files_of = AsyncMock(
            return_value=(
                _row(backend="service"),
                WorkspaceContents(entries=[], unreadable_reason="No workspace root on that host."),
            )
        )

        async with client() as opened:
            response = await opened.get(_url(f"/{_WORKSPACE_ID}/files"))

        assert response.status_code == 200
        assert response.json()["unreadable_reason"] == "No workspace root on that host."


class TestOneFlatList:
    """The simple view, and the reason `files` is declared before `{workspace_id}`."""

    async def test_every_file_carries_the_workspace_it_came_from(self, client) -> None:
        async with client() as opened:
            response = await opened.get(_url("/files"))

        assert response.status_code == 200
        body = response.json()
        assert body["items"][0]["path"] == "/report.csv"
        assert body["items"][0]["agent_name"] == "Analyst"
        assert body["items"][0]["access_label"] == "Whoever is in that conversation"

    async def test_the_literal_path_is_not_read_as_a_workspace_id(self, client, service) -> None:
        """Starlette matches in declaration order, so `files` under `{workspace_id}`
        would answer as a 422 about a malformed UUID before any handler ran."""
        async with client() as opened:
            response = await opened.get(_url("/files"))

        assert response.status_code == 200
        service.files_of.assert_not_called()

    async def test_what_a_tile_can_draw_travels_and_an_absence_stays_null(
        self, client, service
    ) -> None:
        """The tile shows the first lines or the picture only when the listing
        carried them (#138, #827): a stored text file has an excerpt, a stored image
        has a scaled data URI, and a container-backed file honestly has neither -
        never a second read against the host to invent one."""
        service.flat_files = AsyncMock(
            return_value=SimpleNamespace(
                files=[
                    FlatEntry(
                        overview=_overview(),
                        info={"path": "/report.md", "size": 12, "is_dir": False},
                        preview="# Findings",
                        thumbnail=None,
                    ),
                    FlatEntry(
                        overview=_overview(),
                        info={"path": "/chart.png", "size": 900, "is_dir": False},
                        preview=None,
                        thumbnail="data:image/webp;base64,UklGRg==",
                    ),
                    FlatEntry(
                        overview=_overview(),
                        info={"path": "/host.csv", "size": 5, "is_dir": False},
                        preview=None,
                        thumbnail=None,
                    ),
                ],
                workspaces_read=1,
                unreadable=0,
                truncated=False,
            )
        )

        async with client() as opened:
            response = await opened.get(_url("/files"))

        items = {item["path"]: item for item in response.json()["items"]}
        assert items["/report.md"]["preview"] == "# Findings"
        assert items["/report.md"]["thumbnail"] is None
        assert items["/chart.png"]["thumbnail"] == "data:image/webp;base64,UklGRg=="
        assert items["/host.csv"]["preview"] is None
        assert items["/host.csv"]["thumbnail"] is None

    async def test_what_the_answer_left_out_travels_with_it(self, client, service) -> None:
        """A shorter list is indistinguishable from fewer files."""
        service.flat_files = AsyncMock(
            return_value=SimpleNamespace(files=[], workspaces_read=25, unreadable=2, truncated=True)
        )

        async with client() as opened:
            response = await opened.get(_url("/files"))

        body = response.json()
        assert (body["truncated"], body["unreadable"], body["workspaces_read"]) == (True, 2, 25)


class TestOpeningOne:
    async def test_the_files_come_with_whose_workspace_it_is(self, client) -> None:
        async with client() as opened:
            response = await opened.get(_url(f"/{_WORKSPACE_ID}/files"))

        assert response.status_code == 200
        body = response.json()
        assert body["items"][0]["path"] == "/uploads/report.csv"
        assert body["owner_label"] == "This conversation"

    async def test_another_organizations_workspace_is_a_404(self, client, service) -> None:
        """Reported as missing rather than refused, so an id cannot be used to
        find out which workspaces exist elsewhere."""
        service.files_of = AsyncMock(side_effect=NotFoundError(message="Workspace not found"))

        async with client() as opened:
            response = await opened.get(_url(f"/{uuid.uuid4()}/files"))

        assert response.status_code == 404

    async def test_one_file_comes_back_as_text(self, client) -> None:
        async with client() as opened:
            response = await opened.get(
                _url(f"/{_WORKSPACE_ID}/file"), params={"path": "/uploads/report.csv"}
            )

        assert response.status_code == 200
        assert response.json()["content"] == "month,total"

    async def test_a_path_that_is_not_there_is_a_404_in_the_platforms_own_shape(
        self, client, service
    ) -> None:
        """The envelope, not only the status.

        This route raised `HTTPException` while its twin on the conversation
        raised `NotFoundError` for the identical condition, so the same missing
        file answered `{"detail": ...}` here and `{"error": {"code": ...}}` there
        - and a client reading `error.code` worked against one and broke against
        the other. Asserting the status alone is what let the two drift.
        """
        service.read_file_of = AsyncMock(return_value=None)

        async with client() as opened:
            response = await opened.get(_url(f"/{_WORKSPACE_ID}/file"), params={"path": "/nope"})

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
        assert response.json()["error"]["details"]["path"] == "/nope"

    async def test_the_path_is_a_query_parameter_because_paths_have_slashes(self, client) -> None:
        """A path parameter would need escaping the client has to get right, or a
        catch-all route that swallows the ones beside it."""
        async with client() as opened:
            response = await opened.get(
                _url(f"/{_WORKSPACE_ID}/file"), params={"path": "/a/b/c.txt"}
            )

        assert response.status_code == 200
        assert response.json()["path"] == "/a/b/c.txt"

    async def test_asking_for_a_file_without_naming_one_is_refused(self, client, service) -> None:
        async with client() as opened:
            response = await opened.get(_url(f"/{_WORKSPACE_ID}/file"))

        assert response.status_code == 422
        service.read_file_of.assert_not_called()


class TestCountingTheFiles:
    """How many files, and what they weigh, per workspace.

    Free for a stored workspace - its files are a column of the row the listing
    already read - and a round trip per workspace for a container, which is why the
    default listing does not pay for those and says so when it stops.
    """

    async def test_a_measured_workspace_carries_its_count_and_its_bytes(
        self, client, service
    ) -> None:
        service.measured = AsyncMock(
            return_value=MeasuredWorkspaces(
                counts={_WORKSPACE_ID: (4, 2048)}, measured=1, unreadable=0, truncated=False
            )
        )

        async with client() as opened:
            response = await opened.get(_url(""))

        row = response.json()["items"][0]
        assert row["file_count"] == 4
        assert row["measured_bytes"] == 2048

    async def test_a_workspace_nobody_counted_says_nothing_rather_than_zero(self, client) -> None:
        """Zero files is an answer about a workspace; `null` is the absence of one,
        and a size column claiming a container is empty is the defect this replaced."""
        async with client() as opened:
            response = await opened.get(_url(""))

        row = response.json()["items"][0]
        assert row["file_count"] is None
        assert row["measured_bytes"] is None

    async def test_asking_for_hosts_is_the_callers_decision(self, client, service) -> None:
        """A round trip per workspace, so the default listing does not make it."""
        async with client() as opened:
            await opened.get(_url(""))
            await opened.get(_url("?measure=true"))

        assert [call.kwargs["hosts"] for call in service.measured.await_args_list] == [False, True]

    async def test_the_answer_says_what_it_left_out(self, client, service) -> None:
        service.measured = AsyncMock(
            return_value=MeasuredWorkspaces(counts={}, measured=25, unreadable=2, truncated=True)
        )

        async with client() as opened:
            response = await opened.get(_url("?measure=true"))

        assert response.json()["measured"] == 25
        assert response.json()["unreadable"] == 2
        assert response.json()["truncated"] is True
