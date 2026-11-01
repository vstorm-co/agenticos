"""The artifact routes, through the app.

`tests/api/test_platform_routes.py` proves the collection route is gated on
`artifacts:view`, the per-artifact routes delegate to the service, and the two
open routes are declared open. What is left is the handlers themselves: the
shapes they answer, a row from another organization answering 404, and - the
reason the content route exists at all - the headers that isolate the page.

These run the real service with the repository stubbed at the database edge.
"""

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import RateLimitError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.core.security import create_artifact_view_token
from app.db.models.artifact import Artifact, ArtifactMediaType, ArtifactVersion
from app.db.models.artifact_share_request import ShareRequestKind, ShareRequestStatus
from app.db.models.resource_grant import Visibility
from app.main import app
from app.schemas.artifact import (
    ArtifactActionRun,
    ArtifactActionRunStarted,
    ArtifactBinding,
    ArtifactData,
    ArtifactVersionRead,
    BindingReach,
)
from app.schemas.artifact_share_request import (
    ArtifactAccessRequested,
    ArtifactShareRequestList,
    ArtifactShareRequestRead,
    ArtifactVersionReview,
)
from app.schemas.virtual_table import ColumnDef
from app.services import rate_limit
from app.services.artifact import ArtifactService
from app.services.artifact_public_data import ArtifactPublicDataService
from app.services.artifact_request_service import ArtifactRequestService
from app.services.sharing import Deferred, SharingService
from app.services.virtual_tables import BoundRows, TableSource, VirtualTableService

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid.uuid4()

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

PATH = "app.services.artifact"


@pytest.fixture(autouse=True)
def _nobody_follows(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.repositories import artifact as artifact_repo

    monkeypatch.setattr(artifact_repo, "is_following", AsyncMock(return_value=False))
    monkeypatch.setattr(artifact_repo, "follower_ids", AsyncMock(return_value=[]))


@pytest.fixture(autouse=True)
def _shared_with_no_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """The listing names each page's groups; these tests have no database to ask."""

    async def nowhere(*_args: object, resource_ids: list[uuid.UUID], **_kwargs: object):
        return {resource_id: [] for resource_id in resource_ids}

    monkeypatch.setattr(f"{PATH}.groups_sharing", nowhere)


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


def _version(
    artifact: Artifact, *, number: int = 1, bindings: list[dict[str, Any]] | None = None
) -> ArtifactVersion:
    return ArtifactVersion(
        id=uuid.uuid4(),
        artifact_id=artifact.id,
        number=number,
        media_type=ArtifactMediaType.HTML.value,
        size_bytes=20,
        sha256="0" * 64,
        storage_path="artifacts/x/y/z.html",
        run_id=None,
        bindings=bindings or [],
        actions=[],
        consent_state="pending" if bindings else "not_needed",
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
    app.dependency_overrides[deps.get_artifact_request_service] = lambda: ArtifactRequestService(
        MagicMock()
    )
    app.dependency_overrides[deps.get_artifact_public_data_service] = lambda: (
        ArtifactPublicDataService(MagicMock())
    )

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _public_data_edge() -> Iterator[None]:
    """What an editor's page reads of its public data consent, at the database edge: an
    organization with the switch off, no owner membership and no version served to the link.
    A test of the consent itself patches these again."""
    module = "app.services.artifact_public_data"
    with (
        patch(
            f"{module}.organization_repo.get_by_id",
            new=AsyncMock(return_value=MagicMock(public_live_data=False)),
        ),
        patch(f"{module}.owner_membership_id", new=AsyncMock(return_value=None)),
        patch(f"{module}.artifact_repo.get_version_by_number", new=AsyncMock(return_value=None)),
        patch(f"{module}.artifact_repo.latest_served", new=AsyncMock(return_value=None)),
    ):
        yield


def _url(suffix: str = "") -> str:
    return f"{settings.API_V1_STR}/apps{suffix}"


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

    async def test_the_listing_narrows_to_a_project_the_caller_can_see(
        self, client: OpenClient
    ) -> None:
        project_id = uuid.uuid4()
        with (
            patch(f"{PATH}.ProjectService") as projects,
            patch(
                f"{PATH}.artifact_repo.list_visible", new=AsyncMock(return_value=([], 0))
            ) as listing,
            patch(f"{PATH}.artifact_repo.latest_versions", new=AsyncMock(return_value={})),
        ):
            projects.return_value.get = AsyncMock()
            async with client() as http:
                response = await http.get(_url(f"?project_id={project_id}"))
        assert response.status_code == 200
        assert listing.await_args.kwargs["project_id"] == project_id

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
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
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

    async def test_a_view_asks_for_data_only_with_the_flag(self, client: OpenClient) -> None:
        row = _artifact()
        version = _version(row, number=2, bindings=[_binding()])
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.member_context", new=AsyncMock(return_value=object())),
        ):
            async with client() as http:
                plain = await http.get(_url(f"/{row.id}/view"))
                with_data = await http.get(_url(f"/{row.id}/view?data=true"))
        assert plain.json()["injected"] is False
        assert with_data.json()["injected"] is True

    async def test_the_public_link_is_turned_on_and_off(self, client: OpenClient) -> None:
        row = _artifact()

        async def _update(_db: object, *, artifact: Artifact, update_data: dict) -> Artifact:
            for key, value in update_data.items():
                setattr(artifact, key, value)
            return artifact

        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.lock", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.artifact_repo.latest_served", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.artifact_repo.list_versions", new=AsyncMock(return_value=[])),
            patch(f"{PATH}.artifact_repo.update", new=_update),
            patch(f"{PATH}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                on = await http.put(_url(f"/{row.id}/public-link"))
                off = await http.delete(_url(f"/{row.id}/public-link"))
        assert on.json()["public_url"].startswith(f"{settings.FRONTEND_URL.rstrip('/')}/a/")
        assert off.json()["public_url"] is None


class TestActions:
    async def test_starting_an_action_is_created_and_reading_its_run_is_the_projection(
        self, client: OpenClient
    ) -> None:
        run_id = uuid.uuid4()
        started = ArtifactActionRunStarted(run_id=run_id, status="queued")
        state = ArtifactActionRun(
            status="succeeded",
            finished=True,
            paused=False,
            run_path=None,
            output_text="Done",
        )
        page, version, workflow = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        with (
            patch.object(
                ArtifactService, "start_action", new=AsyncMock(return_value=started)
            ) as start,
            patch.object(ArtifactService, "action_run", new=AsyncMock(return_value=state)),
        ):
            async with client() as http:
                created = await http.post(
                    _url(f"/{page}/versions/{version}/actions/{workflow}/runs"),
                    json={"input": {"order": "7"}},
                )
                read = await http.get(_url(f"/{page}/actions/runs/{run_id}"))
        assert created.status_code == 201
        assert created.json() == {"run_id": str(run_id), "status": "queued"}
        assert start.await_args.args[1:5] == (page, version, workflow, start.await_args.args[4])
        assert start.await_args.args[4].input == {"order": "7"}
        assert read.json()["output_text"] == "Done"
        assert set(read.json()) == {
            "status",
            "finished",
            "paused",
            "run_path",
            "output_text",
            "output_structured",
            "error_message",
        }

    async def test_a_start_without_a_body_object_is_refused_at_the_edge(
        self, client: OpenClient
    ) -> None:
        async with client() as http:
            response = await http.post(
                _url(f"/{uuid.uuid4()}/versions/{uuid.uuid4()}/actions/{uuid.uuid4()}/runs"),
                json={"input": "nope"},
            )
        assert response.status_code == 422


class TestStrangers:
    async def test_a_public_link_needs_no_account(self, client: OpenClient) -> None:
        app.dependency_overrides.pop(deps.get_auth_context)
        row = _artifact(public_key="k" * 32)
        with (
            patch(f"{PATH}.artifact_repo.get_by_public_key", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.latest_served", new=AsyncMock(return_value=_version(row))),
            patch(f"{PATH}.artifact_repo.count_public_view", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.get(f"{settings.API_V1_STR}/public/apps/{'k' * 32}")
        assert response.status_code == 200
        assert set(response.json()) == {"password_required", "title", "published_at", "view"}

    @pytest.mark.security
    async def test_a_revoked_link_is_not_found(self, client: OpenClient) -> None:
        with patch(f"{PATH}.artifact_repo.get_by_public_key", new=AsyncMock(return_value=None)):
            async with client() as http:
                response = await http.get(f"{settings.API_V1_STR}/public/apps/gone")
        assert response.status_code == 404

    @pytest.mark.security
    async def test_a_hammered_link_is_refused(self, client: OpenClient) -> None:
        refused = rate_limit.Decision(allowed=False, retry_after_seconds=30)
        with patch.object(
            rate_limit, "public_artifact_allowed", new=AsyncMock(return_value=refused)
        ):
            async with client() as http:
                response = await http.get(f"{settings.API_V1_STR}/public/apps/k")
        assert response.status_code == 429


class TestTheContentRoute:
    @pytest.mark.security
    async def test_the_page_is_served_in_a_sandbox_with_no_network(
        self, client: OpenClient
    ) -> None:
        app.dependency_overrides.pop(deps.get_auth_context)
        row = _artifact(public_key="k")
        version = _version(row)
        token = create_artifact_view_token(
            version.id,
            expires_in=timedelta(minutes=5),
            nonce="n0",
            live=False,
            audience="public",
            public_key="k",
        )
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
    async def test_the_content_never_carries_records(self, client: OpenClient) -> None:
        """The page learns its binding names and its nonce; what they read comes
        later, by message, from a console that checked the viewer."""
        app.dependency_overrides.pop(deps.get_auth_context)
        row = _artifact(public_key="k")
        binding = _binding("open_deals")
        version = _version(row, bindings=[binding])
        token = create_artifact_view_token(
            version.id,
            expires_in=timedelta(minutes=5),
            nonce="nonce-xyz",
            live=True,
            audience="public",
            public_key="k",
        )
        storage = MagicMock()
        storage.load = AsyncMock(return_value=b"<p id=out></p>")
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
        body = response.text
        assert '"names": ["open_deals"]' in body
        assert '"n": "nonce-xyz"' in body
        assert '"live": true' in body
        stage = binding["fields"]["stage"]
        for stored in (binding["table_id"], stage, *binding["reach"]["tables"], "stage"):
            assert stored not in body

    @pytest.mark.security
    async def test_an_address_loaded_on_a_loop_is_refused_before_anything_is_read(
        self, client: OpenClient
    ) -> None:
        app.dependency_overrides.pop(deps.get_auth_context)
        refused = rate_limit.Decision(allowed=False, retry_after_seconds=60)
        token = create_artifact_view_token(
            uuid.uuid4(), expires_in=timedelta(minutes=5), nonce="n0", live=False, audience="public"
        )
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
        token = create_artifact_view_token(
            uuid.uuid4(),
            expires_in=timedelta(seconds=-1),
            nonce="n0",
            live=False,
            audience="public",
        )
        async with client() as http:
            response = await http.get(f"{settings.API_V1_STR}/artifact-content/{token}")
        assert response.status_code == 404
        assert "sandbox" not in response.headers.get("content-security-policy", "")


class TestTheTileRoute:
    @pytest.mark.security
    async def test_a_tile_is_an_image_for_any_page_and_carries_nothing_else(
        self, client: OpenClient
    ) -> None:
        app.dependency_overrides.pop(deps.get_auth_context)
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
        with patch(
            "app.api.routes.v1.artifacts.tile_proxy.tile",
            new=AsyncMock(return_value=(png, "image/png")),
        ) as fetched:
            async with client() as http:
                response = await http.get(f"{settings.API_V1_STR}/artifact-content/tiles/3/4/5")

        assert response.status_code == 200
        assert response.content == png
        assert response.headers["content-type"] == "image/png"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cross-origin-resource-policy"] == "cross-origin"
        assert "set-cookie" not in response.headers
        fetched.assert_awaited_once_with(3, 4, 5)

    async def test_a_tile_path_that_is_not_three_numbers_is_refused(
        self, client: OpenClient
    ) -> None:
        async with client() as http:
            response = await http.get(
                f"{settings.API_V1_STR}/artifact-content/tiles/3/4/secret-from-the-page"
            )
        assert response.status_code == 422

    @pytest.mark.security
    async def test_an_address_fetching_too_many_tiles_is_refused_before_any_fetch(
        self, client: OpenClient
    ) -> None:
        refused = rate_limit.Decision(allowed=False, retry_after_seconds=60)
        fetch = AsyncMock()
        with (
            patch.object(rate_limit, "map_tiles_allowed", new=AsyncMock(return_value=refused)),
            patch("app.api.routes.v1.artifacts.tile_proxy.tile", new=fetch),
        ):
            async with client() as http:
                response = await http.get(f"{settings.API_V1_STR}/artifact-content/tiles/1/0/0")
        assert response.status_code == 429
        fetch.assert_not_awaited()


class TestWhatAPageGained:
    async def test_the_agent_filter_lists_the_publishers(self, client: OpenClient) -> None:
        agent_id = uuid.uuid4()
        with (
            patch(
                f"{PATH}.artifact_repo.publishing_agents",
                new=AsyncMock(
                    return_value=[
                        SimpleNamespace(
                            id=agent_id,
                            slug="reporter",
                            has_avatar=False,
                            avatar_color=None,
                            name="Reporter",
                        )
                    ]
                ),
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
        assert agents.json() == {
            "items": [
                {
                    "id": str(agent_id),
                    "name": "Reporter",
                    "slug": "reporter",
                    "has_avatar": False,
                    "avatar_color": None,
                }
            ]
        }
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
            patch(f"{PATH}.consent_for", new=AsyncMock(return_value=MagicMock())),
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
            patch(f"{PATH}.artifact_repo.latest_served", new=AsyncMock(return_value=_version(row))),
        ):
            async with client() as http:
                asked = await http.get(f"{settings.API_V1_STR}/public/apps/{'k' * 32}")
                wrong = await http.post(
                    f"{settings.API_V1_STR}/public/apps/{'k' * 32}/unlock",
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
                    f"{settings.API_V1_STR}/public/apps/k/unlock", json={"password": "x"}
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
            patch(f"{PATH}.artifact_repo.latest_served", new=AsyncMock(return_value=_version(row))),
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


class TestTheDataRoute:
    def _url(self, artifact: Artifact, version: ArtifactVersion) -> str:
        return _url(f"/{artifact.id}/versions/{version.id}/data")

    async def test_the_data_route_is_not_cached(self, client: OpenClient) -> None:
        row = _artifact()
        version = _version(row)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
        ):
            async with client() as http:
                response = await http.get(self._url(row, version))
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        body = response.json()
        assert body["bindings"] == {}
        assert set(body) == {"bindings", "current", "read_at"}
        assert body["current"] is True

    @pytest.mark.security
    async def test_a_non_member_app_admin_gets_404(self, client: OpenClient) -> None:
        """An app admin outside the organization is refused at its door, as on every route."""
        app.dependency_overrides.pop(deps.get_auth_context)
        app.dependency_overrides[deps.get_current_user] = lambda: MagicMock(
            id=uuid.uuid4(), is_app_admin=True
        )
        app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
        row = _artifact()
        read = AsyncMock(return_value=row)
        with (
            patch(
                "app.api.deps.member_repo.get_with_organization", new=AsyncMock(return_value=None)
            ),
            patch(f"{PATH}.artifact_repo.get", new=read),
        ):
            async with client() as http:
                response = await http.get(
                    self._url(row, _version(row)),
                    headers={"X-Organization-Id": str(_ORGANIZATION_ID)},
                )
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "Organization not found or access denied"
        read.assert_not_awaited()

    @pytest.mark.security
    async def test_data_loads_are_rate_limited_per_viewer(self, client: OpenClient) -> None:
        refused = rate_limit.Decision(allowed=False, retry_after_seconds=60)
        read = AsyncMock()
        row = _artifact()
        with (
            patch.object(
                rate_limit, "consume_with_local_floor", new=AsyncMock(return_value=refused)
            ) as counted,
            patch(f"{PATH}.artifact_repo.get", new=read),
        ):
            async with client() as http:
                response = await http.get(self._url(row, _version(row)))
        assert response.status_code == 429
        assert response.headers["retry-after"] == "60"
        assert response.json()["error"]["message"] == (
            "Too many data loads in the last minute. Wait and try again."
        )
        caller = counted.await_args.kwargs["caller"]
        assert caller.startswith(f"org:{_ORGANIZATION_ID}:user:")
        assert counted.await_args.kwargs["surface"] == "artifact_data"
        read.assert_not_awaited()


def _binding(name: str = "deals") -> dict[str, Any]:
    """A page query as a version stores it: the stage of every record of one table."""
    table_id, stage = uuid.uuid4(), uuid.uuid4()
    return ArtifactBinding(
        name=name,
        table_id=table_id,
        limit=1000,
        fields={"stage": stage},
        reach=BindingReach(tables={table_id: {stage: 0}}),
    ).model_dump(mode="json")


class TestWhoIsServedAPagesData:
    """Everyone served a page's data reads its query as the page's owner (#1974)."""

    async def _load(
        self,
        viewer: AuthContext,
        row: Artifact,
        owner: AuthContext,
        *,
        can_edit: bool,
        state: str = "pending",
    ) -> tuple[Any, AsyncMock]:
        version = _version(row, bindings=[_binding()])
        membership = uuid.uuid4()
        version.consent_state = state
        if state == "consented":
            version.consented_by_membership_id = membership
            version.consented_at = datetime(2026, 10, 1, tzinfo=UTC)
        stage = UUID(version.bindings[0]["fields"]["stage"])
        source = TableSource(
            id=UUID(version.bindings[0]["table_id"]),
            name="Deals",
            archived=False,
            columns=[ColumnDef(id=stage, label="Stage", type="text")],
        )
        read = AsyncMock(
            return_value=BoundRows(
                records=[{"id": "r1", "stage": "Won"}],
                sizes=[24],
                bytes=24,
                columns=source.columns,
                stopped_by=None,
            )
        )

        async def access(_db: Any, _ctx: Any, _row: Any, perm: Perm, **_kw: Any) -> bool:
            return perm is Perm.ARTIFACTS_VIEW or can_edit

        app.dependency_overrides[deps.get_auth_context] = lambda: viewer
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
            patch(
                f"{PATH}.artifact_repo.latest_served",
                new=AsyncMock(return_value=None if state == "pending" else version),
            ),
            patch(
                f"{PATH}.member_repo.get_active",
                new=AsyncMock(return_value=MagicMock(id=membership)),
            ),
            patch(f"{PATH}.resolve_access", new=access),
            patch(f"{PATH}.member_context", new=AsyncMock(return_value=owner)),
            patch(f"{PATH}.virtual_table_repo.statement_timeout", new=AsyncMock()),
            patch(f"{PATH}.virtual_table_repo.restore_statement_timeout", new=AsyncMock()),
            patch(f"{PATH}.page_source", new=AsyncMock(return_value=source)),
            patch.object(VirtualTableService, "read_bound", new=read),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as http:
                response = await http.get(_url(f"/{row.id}/versions/{version.id}/data"))
        if response.status_code != 200:
            return response, read
        return response.json()["bindings"]["deals"], read

    def _owner(self, row: Artifact) -> AuthContext:
        return AuthContext(
            user_id=row.owner_user_id, organization_id=_ORGANIZATION_ID, role=OrgRoleName.MEMBER
        )

    @pytest.mark.security
    async def test_an_admin_reads_the_owner_s_query_not_their_own_access(
        self, client: OpenClient
    ) -> None:
        row = _artifact()
        owner = self._owner(row)
        admin = AuthContext(
            user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.ADMIN
        )

        served, read = await self._load(admin, row, owner, can_edit=True)

        assert (served["status"], served["records"]) == ("ok", [{"id": "r1", "stage": "Won"}])
        assert read.await_args.args[0] is owner

    async def test_a_member_reads_a_version_its_owner_consented_to(
        self, client: OpenClient
    ) -> None:
        row = _artifact()

        served, read = await self._load(
            _member_context(), row, self._owner(row), can_edit=False, state="consented"
        )

        assert served["status"] == "ok"
        read.assert_awaited_once()

    @pytest.mark.security
    async def test_a_member_is_told_the_data_awaits_consent_once_it_is_withdrawn(
        self, client: OpenClient
    ) -> None:
        row = _artifact()
        row.consent_withdrawn_at = datetime(2026, 10, 2, tzinfo=UTC)

        served, read = await self._load(
            _member_context(), row, self._owner(row), can_edit=False, state="consented"
        )

        assert (served["status"], served["reason"], served["records"]) == (
            "unavailable",
            "awaiting_consent",
            [],
        )
        read.assert_not_awaited()

    @pytest.mark.security
    async def test_a_member_never_opens_a_version_waiting_for_consent(
        self, client: OpenClient
    ) -> None:
        row = _artifact()

        response, read = await self._load(_member_context(), row, self._owner(row), can_edit=False)

        assert response.status_code == 404
        read.assert_not_awaited()


def _member_context() -> AuthContext:
    """A Member: they edit only their own pages, unless a grant says otherwise."""
    return AuthContext(
        user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.MEMBER
    )


async def _set(_db: object, *, artifact: Artifact, update_data: dict) -> Artifact:
    for key, value in update_data.items():
        setattr(artifact, key, value)
    return artifact


class TestArchive:
    async def test_archiving_turns_the_public_link_off_and_is_audited(
        self, client: OpenClient
    ) -> None:
        row = _artifact(public_key="k" * 32)
        audit = AsyncMock()
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.lock", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.artifact_repo.update", new=_set),
            patch(f"{PATH}.void_all", new=AsyncMock()) as voided,
            patch(f"{PATH}.record_audit", new=audit),
        ):
            async with client() as http:
                response = await http.post(_url(f"/{row.id}/archive"))
        assert response.status_code == 200
        voided.assert_awaited_once()
        body = response.json()
        assert body["archived_at"] is not None
        assert body["public_url"] is None
        assert row.public_key is None
        assert [call.kwargs["action"] for call in audit.await_args_list] == [
            "artifact.public_link_disabled",
            "artifact.archived",
        ]

    async def test_restoring_a_page_that_is_not_archived_is_a_bad_request(
        self, client: OpenClient
    ) -> None:
        row = _artifact()
        with patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)):
            async with client() as http:
                response = await http.post(_url(f"/{row.id}/unarchive"))
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "BAD_REQUEST"

    async def test_restoring_brings_it_back_with_the_link_still_off(
        self, client: OpenClient
    ) -> None:
        row = _artifact()
        row.archived_at = datetime(2026, 10, 1, tzinfo=UTC)
        audit = AsyncMock()
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.artifact_repo.update", new=_set),
            patch(f"{PATH}.record_audit", new=audit),
        ):
            async with client() as http:
                response = await http.post(_url(f"/{row.id}/unarchive"))
        assert response.status_code == 200
        assert response.json()["archived_at"] is None
        assert response.json()["public_url"] is None
        assert audit.await_args.kwargs["action"] == "artifact.unarchived"

    @pytest.mark.security
    @pytest.mark.parametrize("action", ["archive", "unarchive"])
    async def test_a_member_with_only_a_view_grant_is_told_it_is_not_found(
        self, client: OpenClient, action: str
    ) -> None:
        """No route gate: the service decides, so a view grant reads and never archives."""
        app.dependency_overrides[deps.get_auth_context] = _member_context
        row = _artifact()
        row.archived_at = datetime(2026, 10, 1, tzinfo=UTC) if action == "unarchive" else None
        update = AsyncMock()
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.resource_grant_repo.get_level", new=AsyncMock(return_value="read")),
            patch(f"{PATH}.artifact_repo.update", new=update),
        ):
            async with client() as http:
                response = await http.post(_url(f"/{row.id}/{action}"))
        assert response.status_code == 404
        update.assert_not_awaited()

    async def test_an_edit_grant_lets_a_member_archive_it(self, client: OpenClient) -> None:
        app.dependency_overrides[deps.get_auth_context] = _member_context
        row = _artifact()
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.lock", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.resource_grant_repo.get_level", new=AsyncMock(return_value="edit")),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.artifact_repo.update", new=_set),
            patch(f"{PATH}.void_all", new=AsyncMock()),
            patch(f"{PATH}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.post(_url(f"/{row.id}/archive"))
        assert response.status_code == 200
        assert row.archived_at is not None

    @pytest.mark.security
    async def test_a_page_in_another_organization_is_not_found(self, client: OpenClient) -> None:
        with patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=None)) as get:
            async with client() as http:
                response = await http.post(_url(f"/{uuid.uuid4()}/archive"))
        assert response.status_code == 404
        assert get.await_args.kwargs["organization_id"] == _ORGANIZATION_ID

    @pytest.mark.security
    async def test_an_archived_page_is_not_viewed_and_its_old_address_serves_nothing(
        self, client: OpenClient
    ) -> None:
        row = _artifact()
        row.archived_at = datetime(2026, 10, 1, tzinfo=UTC)
        version = _version(row)
        token = create_artifact_view_token(
            version.id, expires_in=timedelta(minutes=5), nonce="n0", live=False, audience="public"
        )
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(
                f"{PATH}.artifact_repo.get_version_with_artifact",
                new=AsyncMock(return_value=(version, row)),
            ),
        ):
            async with client() as http:
                view = await http.get(_url(f"/{row.id}/view"))
                content = await http.get(f"{settings.API_V1_STR}/artifact-content/{token}")
        assert view.status_code == 404
        assert content.status_code == 404

    async def test_the_listing_asks_for_archived_pages_only_when_told_to(
        self, client: OpenClient
    ) -> None:
        listed = AsyncMock(return_value=([], 0))
        with (
            patch(f"{PATH}.artifact_repo.list_visible", new=listed),
            patch(f"{PATH}.artifact_repo.latest_versions", new=AsyncMock(return_value={})),
        ):
            async with client() as http:
                await http.get(_url())
                await http.get(_url("?include_archived=true"))
        assert [call.kwargs["include_archived"] for call in listed.await_args_list] == [False, True]


class TestConsentRoutes:
    """Confirm data, withdraw and the auto-consent switch: what each answers (#1974).

    The decisions are `tests/test_artifact_consent_actions.py`'s; these prove the routes
    carry them to the status codes the console reads.
    """

    def _bound(self, row: Artifact) -> ArtifactVersion:
        version = _version(row, number=2, bindings=[_binding()])
        version.query_fingerprint = "a" * 64
        return version

    @pytest.mark.security
    async def test_a_confirm_for_page_queries_other_than_shown_is_a_409(
        self, client: OpenClient
    ) -> None:
        row = _artifact()
        version = self._bound(row)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.lock", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.artifact_repo.update_version", new=AsyncMock()) as written,
        ):
            async with client() as http:
                response = await http.post(
                    _url(f"/{row.id}/versions/{version.id}/consent"),
                    json={"fingerprint": "b" * 64},
                )
        assert response.status_code == 409
        written.assert_not_awaited()

    async def test_a_fingerprint_that_is_not_a_digest_is_refused_at_the_edge(
        self, client: OpenClient
    ) -> None:
        async with client() as http:
            response = await http.post(
                _url(f"/{uuid.uuid4()}/versions/{uuid.uuid4()}/consent"),
                json={"fingerprint": "short"},
            )
        assert response.status_code == 422

    @pytest.mark.security
    async def test_an_editor_by_grant_is_refused_the_disclosure_with_a_403(
        self, client: OpenClient
    ) -> None:
        row = _artifact()
        editor = _member_context()
        app.dependency_overrides[deps.get_auth_context] = lambda: editor
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
        ):
            async with client() as http:
                response = await http.get(_url(f"/{row.id}/versions/{uuid.uuid4()}/disclosure"))
        assert response.status_code == 403

    async def test_withdrawing_answers_the_page_with_its_consent_void(
        self, client: OpenClient
    ) -> None:
        row = _artifact()
        version = self._bound(row)
        version.consent_state = "consented"
        version.consented_by_membership_id = uuid.uuid4()
        version.consented_at = datetime(2026, 10, 1, tzinfo=UTC)
        audit = AsyncMock()
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.lock", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.latest_served", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.artifact_repo.update", new=_set),
            patch(
                f"{PATH}.member_repo.get_active",
                new=AsyncMock(return_value=MagicMock(id=version.consented_by_membership_id)),
            ),
            patch(f"{PATH}.user_repo.get_by_id", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.resource_grant_repo.lower_edit_data", new=AsyncMock(return_value=0)),
            patch(f"{PATH}.record_audit", new=audit),
        ):
            async with client() as http:
                response = await http.delete(_url(f"/{row.id}/consent"))
        assert response.status_code == 200
        consent = response.json()["consent"]
        assert (consent["state"], consent["shared"]) == ("withdrawn", False)
        assert consent["withdrawn_at"] is not None
        assert audit.await_args.kwargs["action"] == "artifact.data_withdrawn"

    async def test_auto_consent_on_without_confirming_the_text_is_a_400(
        self, client: OpenClient
    ) -> None:
        row = _artifact()
        owner = AuthContext(
            user_id=row.owner_user_id, organization_id=_ORGANIZATION_ID, role=OrgRoleName.MEMBER
        )
        app.dependency_overrides[deps.get_auth_context] = lambda: owner
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.lock", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.update", new=_set),
        ):
            async with client() as http:
                response = await http.patch(_url(f"/{row.id}/auto-consent"), json={"enabled": True})
        assert response.status_code == 400
        assert row.auto_consent is not True


class TestChangeOwnerRoute:
    """`PUT /artifacts/{id}/owner`: what each caller is answered (#1974). The effects are
    `tests/integration/test_artifact_ownership.py`'s, on real rows."""

    OWNERSHIP = "app.services.artifact_ownership"

    def _as_owner(self, row: Artifact) -> None:
        owner = AuthContext(
            user_id=row.owner_user_id, organization_id=_ORGANIZATION_ID, role=OrgRoleName.MEMBER
        )
        app.dependency_overrides[deps.get_auth_context] = lambda: owner

    async def test_the_owner_hands_the_page_over_and_it_is_audited(
        self, client: OpenClient
    ) -> None:
        row = _artifact()
        self._as_owner(row)
        new_owner = uuid.uuid4()
        audit = AsyncMock()
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{self.OWNERSHIP}.artifact_repo.lock", new=AsyncMock(return_value=row)),
            patch(f"{self.OWNERSHIP}.artifact_repo.update", new=_set),
            patch(f"{self.OWNERSHIP}.void_all", new=AsyncMock()),
            patch(
                f"{self.OWNERSHIP}.resource_grant_repo.lower_edit_data",
                new=AsyncMock(return_value=0),
            ),
            patch(
                f"{self.OWNERSHIP}.member_repo.get_active",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(f"{self.OWNERSHIP}.user_repo.get_by_id", new=AsyncMock()),
            patch(f"{self.OWNERSHIP}.NotificationService") as notifications,
            patch(f"{self.OWNERSHIP}.record_audit", new=audit),
        ):
            notifications.return_value.artifact_owner_changed = AsyncMock()
            async with client() as http:
                response = await http.put(
                    _url(f"/{row.id}/owner"), json={"user_id": str(new_owner)}
                )
        assert response.status_code == 200
        assert response.json()["owner_user_id"] == str(new_owner)
        assert audit.await_args.kwargs["action"] == "artifact.owner_changed"

    @pytest.mark.security
    async def test_an_editor_by_grant_is_a_403(self, client: OpenClient) -> None:
        row = _artifact()
        editor = _member_context()
        app.dependency_overrides[deps.get_auth_context] = lambda: editor
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
        ):
            async with client() as http:
                response = await http.put(
                    _url(f"/{row.id}/owner"), json={"user_id": str(editor.user_id)}
                )
        assert response.status_code == 403
        assert row.owner_user_id != editor.user_id

    async def test_a_new_owner_who_is_not_an_active_member_is_a_400(
        self, client: OpenClient
    ) -> None:
        row = _artifact()
        self._as_owner(row)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{self.OWNERSHIP}.artifact_repo.lock", new=AsyncMock(return_value=row)),
            patch(f"{self.OWNERSHIP}.member_repo.get_active", new=AsyncMock(return_value=None)),
        ):
            async with client() as http:
                response = await http.put(
                    _url(f"/{row.id}/owner"), json={"user_id": str(uuid.uuid4())}
                )
        assert response.status_code == 400


def _request_read(row: Artifact, *, kind: str = "access") -> ArtifactShareRequestRead:
    return ArtifactShareRequestRead(
        id=uuid.uuid4(),
        artifact_id=row.id,
        kind=ShareRequestKind(kind),
        status=ShareRequestStatus.PENDING,
        requester_user_id=uuid.uuid4(),
        created_at=datetime(2026, 10, 22, tzinfo=UTC),
        can_decide=True,
    )


class TestShareRequestRoutes:
    """Requests to share a page, or to confirm a version: what each route answers (#1974).

    The rules are `tests/integration/test_artifact_requests.py`'s, on real rows; these prove
    the routes carry them to the status codes and bodies the console reads.
    """

    SERVICE = "app.services.artifact_request_service"

    async def _as_member(self) -> None:
        app.dependency_overrides[deps.get_auth_context] = _member_context

    @pytest.mark.security
    async def test_a_member_who_cannot_open_a_page_is_told_they_may_ask_and_nothing_else(
        self, client: OpenClient
    ) -> None:
        await self._as_member()
        row = _artifact()
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=False)),
            patch(f"{PATH}.member_repo.get_active", new=AsyncMock(return_value=MagicMock())),
            patch(f"{PATH}.artifact_share_request_repo.pending", new=AsyncMock(return_value=None)),
        ):
            async with client() as http:
                response = await http.get(_url(f"/{row.id}"))
        assert response.status_code == 403
        error = response.json()["error"]
        assert error["code"] == "ACCESS_REQUESTABLE"
        assert error["details"] == {"artifact_id": str(row.id), "requested": False}
        assert row.title not in response.text and row.name not in response.text

    @pytest.mark.security
    async def test_somebody_who_is_no_member_gets_the_plain_not_found(
        self, client: OpenClient
    ) -> None:
        await self._as_member()
        row = _artifact()
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=False)),
            patch(f"{PATH}.member_repo.get_active", new=AsyncMock(return_value=None)),
        ):
            async with client() as http:
                response = await http.get(_url(f"/{row.id}"))
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    async def test_asking_for_access_is_a_201(self, client: OpenClient) -> None:
        row = _artifact()
        answer = ArtifactAccessRequested(
            id=uuid.uuid4(),
            kind=ShareRequestKind.ACCESS,
            status=ShareRequestStatus.PENDING,
            created_at=datetime(2026, 10, 22, tzinfo=UTC),
            note="for Monday",
        )
        with patch.object(
            ArtifactRequestService, "request_access", new=AsyncMock(return_value=answer)
        ) as asked:
            async with client() as http:
                response = await http.post(
                    _url(f"/{row.id}/access-requests"), json={"note": "for Monday"}
                )
        assert response.status_code == 201
        assert set(response.json()) == {"id", "kind", "status", "created_at", "note"}
        assert asked.await_args.args[2].note == "for Monday"

    async def test_a_note_past_its_limit_is_refused_at_the_edge(self, client: OpenClient) -> None:
        async with client() as http:
            response = await http.post(
                _url(f"/{uuid.uuid4()}/access-requests"), json={"note": "x" * 501}
            )
        assert response.status_code == 422

    async def test_listing_deciding_and_reviewing_carry_their_answers(
        self, client: OpenClient
    ) -> None:
        row = _artifact()
        answer = _request_read(row)
        listing = ArtifactShareRequestList(items=[answer], total=1)
        review = ArtifactVersionReview(
            version=ArtifactVersionRead(
                id=uuid.uuid4(),
                number=2,
                media_type="text/html",
                size_bytes=1,
                consent_state="pending",
                created_at=datetime(2026, 10, 22, tzinfo=UTC),
            ),
            bindings=[],
            unchanged=[],
            widens=False,
        )
        with (
            patch.object(
                ArtifactRequestService, "list_requests", new=AsyncMock(return_value=listing)
            ) as listed,
            patch.object(ArtifactRequestService, "approve", new=AsyncMock(return_value=answer)),
            patch.object(ArtifactRequestService, "decline", new=AsyncMock(return_value=answer)),
            patch.object(ArtifactRequestService, "review", new=AsyncMock(return_value=review)),
        ):
            async with client() as http:
                everything = await http.get(
                    _url(f"/{row.id}/share-requests"), params={"include_decided": "true"}
                )
                pending = await http.get(_url(f"/{row.id}/share-requests"))
                approved = await http.post(_url(f"/{row.id}/share-requests/{answer.id}/approve"))
                declined = await http.post(_url(f"/{row.id}/share-requests/{answer.id}/decline"))
                reviewed = await http.get(_url(f"/{row.id}/versions/{uuid.uuid4()}/review"))
        assert [r.status_code for r in (everything, pending, approved, declined, reviewed)] == [
            200,
            200,
            200,
            200,
            200,
        ]
        assert [call.kwargs["pending_only"] for call in listed.await_args_list] == [False, True]
        assert [(call.kwargs["skip"], call.kwargs["limit"]) for call in listed.await_args_list] == [
            (0, 50)
        ] * 2
        assert everything.json()["items"][0]["can_decide"] is True
        assert reviewed.json()["version"]["number"] == 2

    @pytest.mark.security
    async def test_a_share_that_became_a_request_answers_202_with_the_request(
        self, client: OpenClient
    ) -> None:
        row = _artifact()
        body = Deferred(request_id=uuid.uuid4(), waiting_for="Olga")
        service = MagicMock(spec=SharingService)
        service.set_visibility = AsyncMock(return_value=body)
        service.share = AsyncMock(return_value=body)
        service.share_with_group = AsyncMock(return_value=body)
        app.dependency_overrides[deps.get_sharing_service] = lambda: service
        with patch.object(ArtifactService, "load", new=AsyncMock(return_value=row)):
            async with client() as http:
                visibility = await http.patch(
                    _url(f"/{row.id}/sharing/visibility"), json={"visibility": "org"}
                )
                person = await http.put(
                    _url(f"/{row.id}/sharing/grants"),
                    json={"subject_user_id": str(uuid.uuid4()), "level": "read"},
                )
                group = await http.put(
                    _url(f"/{row.id}/sharing/grants"),
                    json={"subject_group_id": str(uuid.uuid4()), "level": "read"},
                )
        for response in (visibility, person, group):
            assert response.status_code == 202
            assert response.json()["status"] == "requested"
            assert response.json()["waiting_for"] == "Olga"
            assert response.json()["request_id"] == str(body.request_id)


class TestReadingDataForItsReasonsAlone:
    @pytest.mark.parametrize(
        ("rows", "surface"), [(True, "artifact_data"), (False, "artifact_data_reasons")]
    )
    async def test_each_kind_of_read_counts_against_an_allowance_of_its_own(
        self, rows: bool, surface: str
    ) -> None:
        ctx = AuthContext(
            user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.MEMBER
        )
        with patch(
            "app.api.deps.rate_limit.consume_with_local_floor",
            new=AsyncMock(return_value=MagicMock(allowed=True)),
        ) as consume:
            await deps.limit_artifact_data(ctx, rows=rows)
        assert consume.await_args.kwargs["surface"] == surface

    async def test_the_reasons_alone_are_refused_past_their_allowance(self) -> None:
        ctx = AuthContext(
            user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.MEMBER
        )
        over = MagicMock(allowed=False, retry_after_seconds=3)
        with (
            patch(
                "app.api.deps.rate_limit.consume_with_local_floor",
                new=AsyncMock(return_value=over),
            ),
            pytest.raises(RateLimitError),
        ):
            await deps.limit_artifact_data(ctx, rows=False)

    @pytest.mark.parametrize(("params", "rows"), [({}, True), ({"rows": "false"}, False)])
    async def test_the_route_asks_the_service_for_the_records_unless_told_not_to(
        self, client: OpenClient, params: dict[str, str], rows: bool
    ) -> None:
        row = _artifact()
        version_id = uuid.uuid4()
        data = ArtifactData(bindings={}, current=True, read_at=datetime.now(UTC))
        with patch.object(ArtifactService, "data", new=AsyncMock(return_value=data)) as read:
            async with client() as http:
                response = await http.get(
                    _url(f"/{row.id}/versions/{version_id}/data"), params=params
                )
        assert response.status_code == 200
        assert read.await_args.kwargs == {"rows": rows}


class TestGrantingEditData:
    @pytest.mark.security
    async def test_the_confirmed_text_travels_with_the_level_to_the_service(
        self, client: OpenClient
    ) -> None:
        row = _artifact()
        person, group = uuid.uuid4(), uuid.uuid4()
        granted = MagicMock(
            id=uuid.uuid4(),
            subject_user_id=person,
            subject_group_id=None,
            resource_type="artifact",
            resource_id=row.id,
            level="edit_data",
        )
        service = MagicMock(spec=SharingService)
        service.share = AsyncMock(return_value=granted)
        service.share_with_group = AsyncMock(return_value=granted)
        app.dependency_overrides[deps.get_sharing_service] = lambda: service
        with patch.object(ArtifactService, "load", new=AsyncMock(return_value=row)):
            async with client() as http:
                one = await http.put(
                    _url(f"/{row.id}/sharing/grants"),
                    json={
                        "subject_user_id": str(person),
                        "level": "edit_data",
                        "confirmed": "edit_data.person.v2",
                    },
                )
                many = await http.put(
                    _url(f"/{row.id}/sharing/grants"),
                    json={
                        "subject_group_id": str(group),
                        "level": "edit_data",
                        "confirmed": "edit_data.group.v2",
                    },
                )
                unknown = await http.put(
                    _url(f"/{row.id}/sharing/grants"),
                    json={"subject_user_id": str(person), "level": "owner"},
                )

        assert (one.status_code, many.status_code, unknown.status_code) == (200, 200, 422)
        assert one.json()["level"] == "edit_data"
        assert service.share.await_args.kwargs["confirmed"] == "edit_data.person.v2"
        assert service.share_with_group.await_args.kwargs["confirmed"] == "edit_data.group.v2"


class TestPublicData:
    """The consent to show a page's data on its public link: what each route answers (#1975).

    The decisions are `tests/integration/test_artifact_public_data.py`'s; these prove the
    routes carry them to the status codes the console reads.
    """

    MODULE = "app.services.artifact_public_data"

    def _consented(self, row: Artifact) -> tuple[ArtifactVersion, uuid.UUID]:
        membership = uuid.uuid4()
        version = _version(row, number=2, bindings=[_binding()])
        version.query_fingerprint = "a" * 64
        version.consent_state = "consented"
        version.consented_by_membership_id = membership
        version.consented_at = datetime(2026, 10, 1, tzinfo=UTC)
        return version, membership

    @pytest.mark.security
    async def test_an_editor_by_grant_is_refused_the_screen_with_a_403(
        self, client: OpenClient
    ) -> None:
        row = _artifact()
        app.dependency_overrides[deps.get_auth_context] = lambda: _member_context()
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
        ):
            async with client() as http:
                response = await http.get(_url(f"/{row.id}/public-data"))
        assert response.status_code == 403

    async def test_a_fingerprint_that_is_not_a_digest_is_refused_at_the_edge(
        self, client: OpenClient
    ) -> None:
        async with client() as http:
            response = await http.post(
                _url(f"/{uuid.uuid4()}/public-data"),
                json={"fingerprint": "short", "audience_digest": "c" * 64, "confirmed": True},
            )
        assert response.status_code == 422

    @pytest.mark.security
    async def test_a_confirm_for_page_queries_other_than_shown_is_a_409(
        self, client: OpenClient
    ) -> None:
        row = _artifact(public_key="k")
        version, membership = self._consented(row)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{self.MODULE}.artifact_repo.lock", new=AsyncMock(return_value=row)),
            patch(
                f"{self.MODULE}.artifact_repo.latest_served", new=AsyncMock(return_value=version)
            ),
            patch(
                f"{self.MODULE}.organization_repo.get_by_id",
                new=AsyncMock(return_value=MagicMock(public_live_data=True)),
            ),
            patch(f"{self.MODULE}.owner_membership_id", new=AsyncMock(return_value=membership)),
            patch(f"{self.MODULE}.artifact_repo.update", new=AsyncMock()) as written,
        ):
            async with client() as http:
                response = await http.post(
                    _url(f"/{row.id}/public-data"),
                    json={"fingerprint": "b" * 64, "audience_digest": "c" * 64, "confirmed": True},
                )
        assert response.status_code == 409
        written.assert_not_awaited()

    async def test_withdrawing_answers_the_page_without_its_public_consent(
        self, client: OpenClient
    ) -> None:
        row = _artifact(public_key="k")
        version, membership = self._consented(row)
        row.auto_consent = False
        row.public_data_fingerprint = "a" * 64
        row.public_data_membership_id = membership
        audit = AsyncMock()
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.latest_served", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.artifact_repo.get_version_by_number", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{self.MODULE}.artifact_repo.lock", new=AsyncMock(return_value=row)),
            patch(f"{self.MODULE}.artifact_repo.update", new=_set),
            patch(
                f"{self.MODULE}.artifact_repo.latest_served", new=AsyncMock(return_value=version)
            ),
            patch(
                f"{self.MODULE}.organization_repo.get_by_id",
                new=AsyncMock(return_value=MagicMock(public_live_data=True)),
            ),
            patch(f"{self.MODULE}.owner_membership_id", new=AsyncMock(return_value=membership)),
            patch(f"{PATH}.member_repo.get_active", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.user_repo.get_by_id", new=AsyncMock(return_value=None)),
            patch(f"{self.MODULE}.record_audit", new=audit),
        ):
            async with client() as http:
                response = await http.delete(_url(f"/{row.id}/public-data"))
        assert response.status_code == 200
        body = response.json()
        assert body["public_data"]["consented"] is False
        assert body["public_data"]["holds"] is False
        assert audit.await_args.kwargs["action"] == "artifact.public_data_withdrawn"


class TestTheOldPaths:
    """Apps were artifacts until #2071; the old paths answer for the v1 policy's 90 days."""

    async def test_a_public_link_still_answers_at_the_old_path(self, client: OpenClient) -> None:
        app.dependency_overrides.pop(deps.get_auth_context)
        row = _artifact(public_key="k" * 32)
        with (
            patch(f"{PATH}.artifact_repo.get_by_public_key", new=AsyncMock(return_value=row)),
            patch(f"{PATH}.artifact_repo.latest_served", new=AsyncMock(return_value=_version(row))),
            patch(f"{PATH}.artifact_repo.count_public_view", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.get(f"{settings.API_V1_STR}/public/artifacts/{'k' * 32}")
        assert response.status_code == 200

    def test_the_old_paths_are_marked_deprecated_and_the_new_ones_are_not(self) -> None:
        paths = app.openapi()["paths"]
        old = [p for p in paths if p.startswith(f"{settings.API_V1_STR}/artifacts")]
        new = [p for p in paths if p.startswith(f"{settings.API_V1_STR}/apps")]

        assert old and len(old) == len(new)
        assert all(op.get("deprecated") for p in old for op in paths[p].values())
        assert not any(op.get("deprecated") for p in new for op in paths[p].values())


class TestTheVisualFrame:
    @pytest.mark.security
    async def test_the_frame_is_the_app_sandbox_and_holds_no_visual(
        self, client: OpenClient
    ) -> None:
        """A drawing is model-written script that may have read hostile input, so
        it gets exactly an app's isolation - from a header, not a meta tag."""
        app.dependency_overrides.pop(deps.get_auth_context)
        async with client() as http:
            response = await http.get(f"{settings.API_V1_STR}/artifact-content/visual-frame")
        assert response.status_code == 200
        policy = response.headers["content-security-policy"]
        assert policy.startswith("sandbox allow-scripts allow-modals;")
        assert "connect-src 'none'" in policy
        assert "frame-ancestors" in policy
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "__agenticosVisualDocument" in response.text

    async def test_a_module_library_answers_cors_for_an_opaque_origin(
        self, client: OpenClient
    ) -> None:
        """three.js imports as a module, fetched in CORS mode with `Origin: null`."""
        app.dependency_overrides.pop(deps.get_auth_context)
        async with client() as http:
            response = await http.get(
                f"{settings.API_V1_STR}/artifact-content/lib/three-0.186.0/addons/controls/OrbitControls.js"
            )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "*"
        assert b"OrbitControls" in response.content
