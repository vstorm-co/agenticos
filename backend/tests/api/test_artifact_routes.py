"""The artifact routes, through the app.

`tests/api/test_platform_routes.py` proves the collection route is gated on
`artifacts:view`, the per-artifact routes delegate to the service, and the two
open routes are declared open. What is left is the handlers themselves: the
shapes they answer, a row from another organization answering 404, and - the
reason the content route exists at all - the headers that isolate the page.

These run the real service with the repository stubbed at the database edge.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.core.security import create_artifact_view_token
from app.db.models.artifact import Artifact, ArtifactMediaType, ArtifactVersion
from app.db.models.resource_grant import Visibility
from app.main import app
from app.services import rate_limit
from app.services.artifact import ArtifactService

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid.uuid4()

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

PATH = "app.services.artifact"


@pytest.fixture(autouse=True)
def _nobody_follows(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.repositories import artifact as artifact_repo

    monkeypatch.setattr(artifact_repo, "is_following", AsyncMock(return_value=False))
    monkeypatch.setattr(artifact_repo, "follower_ids", AsyncMock(return_value=[]))


def _artifact(*, public_key: str | None = None) -> Artifact:
    return Artifact(
        id=uuid.uuid4(),
        organization_id=_ORGANIZATION_ID,
        owner_user_id=uuid.uuid4(),
        visibility=Visibility.PRIVATE.value,
        agent_id=uuid.uuid4(),
        name="weekly-report",
        title="Weekly report",
        public_key=public_key,
        public_view_count=0,
        embed_origins=[],
        published_at=datetime(2026, 9, 22, tzinfo=UTC),
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def _version(artifact: Artifact, *, number: int = 1) -> ArtifactVersion:
    return ArtifactVersion(
        id=uuid.uuid4(),
        artifact_id=artifact.id,
        number=number,
        media_type=ArtifactMediaType.HTML.value,
        size_bytes=20,
        sha256="0" * 64,
        storage_path="artifacts/x/y/z.html",
        run_id=None,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
    )


@pytest.fixture
def client(mock_redis: MagicMock) -> Iterator[OpenClient]:
    # An Owner reaches every artifact on role scope alone, so no grant lookup
    # touches the stubbed session.
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_artifact_service] = lambda: ArtifactService(MagicMock())

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(suffix: str = "") -> str:
    return f"{settings.API_V1_STR}/artifacts{suffix}"


class TestFollowing:
    async def test_following_and_unfollowing_answer_with_the_page(self, client: OpenClient) -> None:
        row = _artifact()
        follow = AsyncMock()
        unfollow = AsyncMock()
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.artifact_repo.follow", new=follow),
            patch(f"{PATH}.artifact_repo.unfollow", new=unfollow),
            patch(f"{PATH}.artifact_repo.is_following", new=AsyncMock(side_effect=[True, False])),
        ):
            async with client() as http:
                followed = await http.put(_url(f"/{row.id}/follow"))
                unfollowed = await http.delete(_url(f"/{row.id}/follow"))
        assert followed.status_code == 200
        assert followed.json()["following"] is True
        assert unfollowed.status_code == 200
        assert unfollowed.json()["following"] is False
        assert follow.await_args.kwargs["artifact_id"] == row.id
        assert unfollow.await_args.kwargs["artifact_id"] == row.id

    @pytest.mark.security
    async def test_a_page_the_caller_cannot_open_cannot_be_followed(
        self, client: OpenClient
    ) -> None:
        """Following is not a way to learn that a page exists."""
        follow = AsyncMock()
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.artifact_repo.follow", new=follow),
        ):
            async with client() as http:
                response = await http.put(_url(f"/{uuid.uuid4()}/follow"))
        assert response.status_code == 404
        follow.assert_not_called()


class TestMembers:
    async def test_the_listing_carries_each_artifact_s_current_version(
        self, client: OpenClient
    ) -> None:
        row = _artifact()
        with (
            patch(f"{PATH}.artifact_repo.list_visible", new=AsyncMock(return_value=([row], 1))),
            patch(
                f"{PATH}.artifact_repo.latest_versions",
                new=AsyncMock(return_value={row.id: _version(row, number=3)}),
            ),
        ):
            async with client() as http:
                response = await http.get(_url())
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["current_version"]["number"] == 3
        assert body["items"][0]["public_url"] is None

    @pytest.mark.security
    async def test_an_artifact_in_another_organization_is_not_found(
        self, client: OpenClient
    ) -> None:
        """The repository is scoped by the caller's organization, so another
        tenant's id finds nothing - the same 404 a missing one gets."""
        with patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=None)) as get:
            async with client() as http:
                response = await http.get(_url(f"/{uuid.uuid4()}"))
        assert response.status_code == 404
        assert get.await_args.kwargs["organization_id"] == _ORGANIZATION_ID

    async def test_reading_retitling_and_deleting(self, client: OpenClient) -> None:
        row = _artifact()
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.artifact_repo.update", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.resource_grant_repo.delete_for_resource", new=AsyncMock()),
            patch(f"{PATH}.artifact_repo.delete_artifact", new=AsyncMock()),
            patch(f"{PATH}.record_audit", new=AsyncMock()),
            patch(f"{PATH}.spawn_after_commit") as after_commit,
        ):
            async with client() as http:
                read = await http.get(_url(f"/{row.id}"))
                retitled = await http.patch(_url(f"/{row.id}"), json={"title": "New"})
                deleted = await http.delete(_url(f"/{row.id}"))
        after_commit.call_args.args[1].close()
        assert read.status_code == 200
        assert read.json()["name"] == "weekly-report"
        assert retitled.status_code == 200
        assert deleted.status_code == 204

    async def test_an_empty_title_is_refused_at_the_edge(self, client: OpenClient) -> None:
        async with client() as http:
            response = await http.patch(_url(f"/{uuid.uuid4()}"), json={"title": ""})
        assert response.status_code == 422

    async def test_the_versions_and_a_signed_view(self, client: OpenClient) -> None:
        row = _artifact()
        version = _version(row, number=2)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.list_versions", new=AsyncMock(return_value=[version])),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=version)),
        ):
            async with client() as http:
                versions = await http.get(_url(f"/{row.id}/versions"))
                view = await http.get(_url(f"/{row.id}/view?version_id={version.id}"))
        assert versions.json()["items"][0]["number"] == 2
        assert view.status_code == 200
        assert "/artifact-content/" in view.json()["url"]
        assert view.json()["version"]["id"] == str(version.id)

    async def test_the_public_link_is_turned_on_and_off(self, client: OpenClient) -> None:
        row = _artifact()

        async def _update(_db: object, *, artifact: Artifact, update_data: dict) -> Artifact:
            for key, value in update_data.items():
                setattr(artifact, key, value)
            return artifact

        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.artifact_repo.update", new=_update),
            patch(f"{PATH}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                on = await http.put(_url(f"/{row.id}/public-link"))
                off = await http.delete(_url(f"/{row.id}/public-link"))
        assert on.json()["public_url"].startswith(f"{settings.FRONTEND_URL.rstrip('/')}/a/")
        assert off.json()["public_url"] is None


class TestStrangers:
    async def test_a_public_link_needs_no_account(self, client: OpenClient) -> None:
        app.dependency_overrides.pop(deps.get_auth_context)
        row = _artifact(public_key="k" * 32)
        with (
            patch(f"{PATH}.artifact_repo.get_by_public_key", new=AsyncMock(return_value=row)),
            patch(
                f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=_version(row))
            ),
            patch(f"{PATH}.artifact_repo.count_public_view", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.get(f"{settings.API_V1_STR}/public/artifacts/{'k' * 32}")
        assert response.status_code == 200
        assert set(response.json()) == {"password_required", "title", "published_at", "view"}

    @pytest.mark.security
    async def test_a_revoked_link_is_not_found(self, client: OpenClient) -> None:
        with patch(f"{PATH}.artifact_repo.get_by_public_key", new=AsyncMock(return_value=None)):
            async with client() as http:
                response = await http.get(f"{settings.API_V1_STR}/public/artifacts/gone")
        assert response.status_code == 404

    @pytest.mark.security
    async def test_a_hammered_link_is_refused(self, client: OpenClient) -> None:
        refused = rate_limit.Decision(allowed=False, retry_after_seconds=30)
        with patch.object(
            rate_limit, "public_artifact_allowed", new=AsyncMock(return_value=refused)
        ):
            async with client() as http:
                response = await http.get(f"{settings.API_V1_STR}/public/artifacts/k")
        assert response.status_code == 429


class TestTheContentRoute:
    @pytest.mark.security
    async def test_the_page_is_served_in_a_sandbox_with_no_network(
        self, client: OpenClient
    ) -> None:
        app.dependency_overrides.pop(deps.get_auth_context)
        row = _artifact()
        version = _version(row)
        token = create_artifact_view_token(version.id, expires_in=timedelta(minutes=5))
        storage = MagicMock()
        storage.load = AsyncMock(return_value=b"<script>document.title='x'</script>")
        with (
            patch(
                f"{PATH}.artifact_repo.get_version_with_artifact",
                new=AsyncMock(return_value=(version, row)),
            ),
            patch(f"{PATH}.get_file_storage", return_value=storage),
        ):
            async with client() as http:
                response = await http.get(f"{settings.API_V1_STR}/artifact-content/{token}")

        assert response.status_code == 200
        assert response.text.endswith("<script>document.title='x'</script>")
        assert response.text.startswith('<script data-agenticos="platform">')
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        policy = response.headers["content-security-policy"]
        assert policy.startswith("sandbox allow-scripts")
        assert "allow-same-origin" not in policy
        assert "connect-src 'none'" in policy
        assert f"frame-ancestors {settings.FRONTEND_URL.rstrip('/')}" in policy
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "set-cookie" not in response.headers

    @pytest.mark.security
    async def test_an_address_loaded_on_a_loop_is_refused_before_anything_is_read(
        self, client: OpenClient
    ) -> None:
        app.dependency_overrides.pop(deps.get_auth_context)
        refused = rate_limit.Decision(allowed=False, retry_after_seconds=60)
        token = create_artifact_view_token(uuid.uuid4(), expires_in=timedelta(minutes=5))
        read = AsyncMock()
        with (
            patch.object(
                rate_limit, "artifact_content_allowed", new=AsyncMock(return_value=refused)
            ) as counted,
            patch(f"{PATH}.artifact_repo.get_version_with_artifact", new=read),
        ):
            async with client() as http:
                response = await http.get(f"{settings.API_V1_STR}/artifact-content/{token}")
        assert response.status_code == 429
        counted.assert_awaited_once_with(token)
        read.assert_not_awaited()

    @pytest.mark.security
    async def test_an_expired_address_is_not_found(self, client: OpenClient) -> None:
        token = create_artifact_view_token(uuid.uuid4(), expires_in=timedelta(seconds=-1))
        async with client() as http:
            response = await http.get(f"{settings.API_V1_STR}/artifact-content/{token}")
        assert response.status_code == 404
        assert "sandbox" not in response.headers.get("content-security-policy", "")


class TestWhatAPageGained:
    async def test_the_agent_filter_lists_the_publishers(self, client: OpenClient) -> None:
        agent_id = uuid.uuid4()
        with (
            patch(
                f"{PATH}.artifact_repo.publishing_agents",
                new=AsyncMock(return_value=[(agent_id, "Reporter")]),
            ),
            patch(
                f"{PATH}.artifact_repo.list_visible", new=AsyncMock(return_value=([], 0))
            ) as listing,
            patch(f"{PATH}.artifact_repo.latest_versions", new=AsyncMock(return_value={})),
        ):
            async with client() as http:
                agents = await http.get(_url("/agents"))
                filtered = await http.get(_url(f"?agent_id={agent_id}"))
        assert agents.status_code == 200
        assert agents.json() == {"items": [{"id": str(agent_id), "name": "Reporter"}]}
        assert filtered.status_code == 200
        assert listing.await_args.kwargs["agent_id"] == agent_id

    async def test_a_kept_version_is_restored(self, client: OpenClient) -> None:
        row = _artifact()
        kept, current = _version(row, number=1), _version(row, number=2)
        current.sha256 = "1" * 64
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.lock", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=kept)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=current)),
            patch(
                f"{PATH}._append_version", new=AsyncMock(return_value=_version(row, number=3))
            ) as append,
            patch(f"{PATH}.record_audit", new=AsyncMock()),
            patch(
                f"{PATH}.get_file_storage",
                return_value=MagicMock(exists=AsyncMock(return_value=True)),
            ),
        ):
            async with client() as http:
                response = await http.post(_url(f"/{row.id}/versions/{kept.id}/restore"))
        assert response.status_code == 200
        assert append.await_args.kwargs["storage_path"] == kept.storage_path

    async def test_the_public_link_settings_are_changed_and_read_back(
        self, client: OpenClient
    ) -> None:
        row = _artifact(public_key="k" * 32)

        async def _update(_db: object, *, artifact: Artifact, update_data: dict) -> Artifact:
            for key, value in update_data.items():
                setattr(artifact, key, value)
            return artifact

        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.artifact_repo.update", new=_update),
            patch(f"{PATH}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.patch(
                    _url(f"/{row.id}/public-link"),
                    json={"password": "hunter22", "embed_origins": ["https://a.example.com"]},
                )
        assert response.status_code == 200
        link = response.json()["public_link"]
        assert link["password_protected"] is True
        assert link["embed_origins"] == ["https://a.example.com"]
        assert "hunter22" not in response.text
        assert "public_password_hash" not in response.text

    async def test_a_password_too_short_is_refused_at_the_edge(self, client: OpenClient) -> None:
        async with client() as http:
            response = await http.patch(
                _url(f"/{uuid.uuid4()}/public-link"), json={"password": "abc"}
            )
        assert response.status_code == 422


class TestStrangersWithAPassword:
    @pytest.mark.security
    async def test_a_wrong_password_is_forbidden_and_says_nothing_else(
        self, client: OpenClient
    ) -> None:
        app.dependency_overrides.pop(deps.get_auth_context)
        from app.core.security import get_password_hash

        row = _artifact(public_key="k" * 32)
        row.public_password_hash = get_password_hash("right-one")
        with (
            patch(f"{PATH}.artifact_repo.get_by_public_key", new=AsyncMock(return_value=row)),
            patch(
                f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=_version(row))
            ),
        ):
            async with client() as http:
                asked = await http.get(f"{settings.API_V1_STR}/public/artifacts/{'k' * 32}")
                wrong = await http.post(
                    f"{settings.API_V1_STR}/public/artifacts/{'k' * 32}/unlock",
                    json={"password": "wrong-one"},
                )
        assert asked.json() == {
            "password_required": True,
            "title": None,
            "published_at": None,
            "view": None,
        }
        assert wrong.status_code == 403
        assert "Weekly report" not in wrong.text

    @pytest.mark.security
    async def test_guessing_counts_against_the_link_s_limit(self, client: OpenClient) -> None:
        refused = rate_limit.Decision(allowed=False, retry_after_seconds=30)
        with patch.object(
            rate_limit, "public_artifact_allowed", new=AsyncMock(return_value=refused)
        ):
            async with client() as http:
                response = await http.post(
                    f"{settings.API_V1_STR}/public/artifacts/k/unlock", json={"password": "x"}
                )
        assert response.status_code == 429


class TestTheLibraryRoute:
    async def test_a_library_file_is_served_for_a_year_to_any_page(
        self, client: OpenClient
    ) -> None:
        app.dependency_overrides.pop(deps.get_auth_context)
        async with client() as http:
            response = await http.get(
                f"{settings.API_V1_STR}/artifact-content/lib/chart-4.5.1.umd.min.js"
            )
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/javascript; charset=utf-8"
        assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert response.headers["cross-origin-resource-policy"] == "cross-origin"
        assert response.content.startswith(b"/*!\n * Chart.js v4.5.1")

    @pytest.mark.security
    async def test_nothing_outside_the_set_is_served(self, client: OpenClient) -> None:
        async with client() as http:
            response = await http.get(f"{settings.API_V1_STR}/artifact-content/lib/README.md")
        assert response.status_code == 404


class TestTheEmbedRoute:
    @pytest.mark.security
    async def test_the_embed_is_framed_only_by_the_artifact_s_sites(
        self, client: OpenClient
    ) -> None:
        app.dependency_overrides.pop(deps.get_auth_context)
        row = _artifact(public_key="k" * 32)
        row.embed_origins = ["https://intranet.example.com"]
        with (
            patch(f"{PATH}.artifact_repo.get_by_public_key", new=AsyncMock(return_value=row)),
            patch(
                f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=_version(row))
            ),
            patch(f"{PATH}.artifact_repo.count_public_view", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.get(f"{settings.API_V1_STR}/artifact-embed/{'k' * 32}")
        assert response.status_code == 200
        policy = response.headers["content-security-policy"]
        assert "frame-ancestors https://intranet.example.com" in policy
        assert "connect-src 'none'" in policy
        assert response.headers["cache-control"] == "private, no-store"
        assert 'sandbox="allow-scripts allow-modals"' in response.text

    async def test_a_link_that_opens_nothing_embeds_a_page_saying_so(
        self, client: OpenClient
    ) -> None:
        with patch(f"{PATH}.artifact_repo.get_by_public_key", new=AsyncMock(return_value=None)):
            async with client() as http:
                response = await http.get(f"{settings.API_V1_STR}/artifact-embed/gone")
        assert response.status_code == 404
        assert "not available" in response.text
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
