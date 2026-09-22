"""The artifact service's decisions, with the database stubbed at the repository edge.

`tests/integration/test_artifacts.py` proves what the rows do. This proves what the
service decides about them: a private or revoked artifact is a 404 and never a
403, a public link is a rotation as well as an enable, a signed address opens
exactly one version and nothing past its expiry, and the content is served as a
document - HTML as written, Markdown rendered with its raw HTML escaped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.core.security import create_artifact_view_token
from app.db.models.artifact import Artifact, ArtifactMediaType, ArtifactVersion
from app.db.models.resource_grant import Visibility
from app.schemas.artifact import ArtifactUpdate
from app.services import artifact as artifacts
from app.services.artifact import ArtifactService

pytestmark = pytest.mark.anyio

PATH = "app.services.artifact"


def _ctx(role: str = OrgRoleName.OWNER, *, org_id: uuid.UUID | None = None) -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=org_id or uuid.uuid4(), role=role)


def _artifact(ctx: AuthContext, *, public_key: str | None = None) -> Artifact:
    return Artifact(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        visibility=Visibility.PRIVATE.value,
        agent_id=uuid.uuid4(),
        name="weekly-report",
        title="Weekly report",
        public_key=public_key,
        published_at=datetime(2026, 9, 22, tzinfo=UTC),
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def _version(
    artifact: Artifact, *, number: int = 1, media_type: str = ArtifactMediaType.HTML.value
) -> ArtifactVersion:
    return ArtifactVersion(
        id=uuid.uuid4(),
        artifact_id=artifact.id,
        number=number,
        media_type=media_type,
        size_bytes=12,
        sha256="0" * 64,
        storage_path=f"artifacts/{artifact.organization_id}/{artifact.id}/x.html",
        run_id=None,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
    )


def _service() -> ArtifactService:
    return ArtifactService(MagicMock())


class TestPublishProblem:
    @pytest.mark.parametrize("name", ["Weekly", "-lead", "has space", "", "a" * 65, "ünï"])
    def test_a_name_outside_the_pattern_is_refused_with_how_to_fix_it(self, name: str) -> None:
        problem = artifacts.publish_problem(
            name=name, media_type=ArtifactMediaType.HTML, data=b"<p>x</p>"
        )
        assert problem is not None
        assert "weekly-report" in problem

    def test_a_page_over_the_limit_is_refused(self) -> None:
        with patch.object(artifacts.settings, "ARTIFACT_MAX_BYTES", 4):
            problem = artifacts.publish_problem(
                name="r", media_type=ArtifactMediaType.HTML, data=b"<p>x</p>"
            )
        assert problem is not None
        assert "limit" in problem

    def test_an_empty_page_is_refused(self) -> None:
        assert artifacts.publish_problem(
            name="r", media_type=ArtifactMediaType.HTML, data=b"  \n"
        ) == ("The page is empty. Publish the finished document.")

    def test_bytes_that_are_not_text_are_refused(self) -> None:
        problem = artifacts.publish_problem(
            name="r", media_type=ArtifactMediaType.MARKDOWN, data=b"\xff\xfe"
        )
        assert problem == "The md content is not valid UTF-8 text."

    def test_a_good_page_is_accepted(self) -> None:
        assert (
            artifacts.publish_problem(
                name="weekly-report", media_type=ArtifactMediaType.HTML, data=b"<p>x</p>"
            )
            is None
        )


class TestPublishWrapper:
    async def test_a_run_publishes_on_a_session_of_its_own(self) -> None:
        session = MagicMock()
        opened = MagicMock()
        opened.__aenter__ = AsyncMock(return_value=session)
        opened.__aexit__ = AsyncMock(return_value=None)
        expected = MagicMock()
        with (
            patch(f"{PATH}.get_db_context", return_value=opened),
            patch(f"{PATH}.publish_with", new=AsyncMock(return_value=expected)) as publish_with,
        ):
            result = await artifacts.publish(
                organization_id=uuid.uuid4(),
                agent_id=uuid.uuid4(),
                owner_user_id=None,
                run_id=None,
                name="r",
                title="R",
                media_type=ArtifactMediaType.HTML,
                data=b"<p>x</p>",
            )
        assert result is expected
        assert publish_with.await_args.args == (session,)

    async def test_bytes_over_the_limit_never_reach_storage(self) -> None:
        with (
            patch.object(artifacts.settings, "ARTIFACT_MAX_BYTES", 2),
            pytest.raises(ValueError, match="ARTIFACT_MAX_BYTES"),
        ):
            await artifacts.publish_with(
                MagicMock(),
                organization_id=uuid.uuid4(),
                agent_id=uuid.uuid4(),
                owner_user_id=None,
                run_id=None,
                name="r",
                title="R",
                media_type=ArtifactMediaType.HTML,
                data=b"<p>x</p>",
            )


class TestTheRaceForAFirstPublication:
    async def test_the_loser_of_a_create_race_takes_the_winner_s_row(self) -> None:
        from sqlalchemy.exc import IntegrityError

        ctx = _ctx()
        winner = _artifact(ctx)
        db = MagicMock()
        nested = MagicMock()
        nested.__aenter__ = AsyncMock(return_value=None)
        nested.__aexit__ = AsyncMock(return_value=None)
        db.begin_nested.return_value = nested
        with (
            patch(
                f"{PATH}.artifact_repo.get_for_update",
                new=AsyncMock(side_effect=[None, winner]),
            ),
            patch(
                f"{PATH}.artifact_repo.create",
                new=AsyncMock(side_effect=IntegrityError("insert", {}, Exception("dup"))),
            ),
        ):
            found, created = await artifacts._locked_artifact(
                db,
                organization_id=ctx.organization_id,
                agent_id=uuid.uuid4(),
                owner_user_id=ctx.user_id,
                name="r",
                title="R",
            )
        assert (found, created) == (winner, False)

    async def test_an_integrity_error_with_no_winner_is_not_swallowed(self) -> None:
        from sqlalchemy.exc import IntegrityError

        db = MagicMock()
        nested = MagicMock()
        nested.__aenter__ = AsyncMock(return_value=None)
        nested.__aexit__ = AsyncMock(return_value=None)
        db.begin_nested.return_value = nested
        with (
            patch(f"{PATH}.artifact_repo.get_for_update", new=AsyncMock(return_value=None)),
            patch(
                f"{PATH}.artifact_repo.create",
                new=AsyncMock(side_effect=IntegrityError("insert", {}, Exception("fk"))),
            ),
            pytest.raises(IntegrityError),
        ):
            await artifacts._locked_artifact(
                db,
                organization_id=uuid.uuid4(),
                agent_id=uuid.uuid4(),
                owner_user_id=None,
                name="r",
                title="R",
            )


class TestGet:
    async def test_a_missing_artifact_is_not_found(self) -> None:
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await _service().get(_ctx(), uuid.uuid4())

    @pytest.mark.security
    async def test_an_artifact_the_caller_cannot_reach_is_not_found_rather_than_forbidden(
        self,
    ) -> None:
        """A revoked member and a stranger get the same answer as a missing row."""
        ctx = _ctx(OrgRoleName.VIEWER)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=_artifact(ctx))),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=False)),
            pytest.raises(NotFoundError),
        ):
            await _service().get(ctx, uuid.uuid4())

    async def test_management_asks_for_edit(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)) as access,
            patch(f"{PATH}.artifact_repo.update", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=None)),
        ):
            await _service().update(ctx, artifact.id, ArtifactUpdate(title="New"))
        assert access.await_args.args[3] is Perm.ARTIFACTS_EDIT


class TestRead:
    async def test_a_read_carries_the_current_version_and_the_public_address(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx, public_key="k" * 32)
        version = _version(artifact, number=3)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
        ):
            read = await _service().read(ctx, artifact.id)
        assert read.can_edit is True
        assert read.current_version is not None
        assert read.current_version.number == 3
        assert read.public_url == f"{artifacts.settings.FRONTEND_URL.rstrip('/')}/a/{'k' * 32}"

    @pytest.mark.security
    async def test_a_reader_is_told_they_may_not_manage_it(self) -> None:
        """Decided with the grants, so the page hides what the server would refuse."""
        ctx = _ctx(OrgRoleName.VIEWER)
        artifact = _artifact(ctx)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(side_effect=[True, False])) as access,
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=None)),
        ):
            read = await _service().read(ctx, artifact.id)
        assert read.can_edit is False
        assert access.await_args_list[1].args[3] is Perm.ARTIFACTS_EDIT

    async def test_an_untitled_update_changes_nothing(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.artifact_repo.update", new=AsyncMock()) as update,
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=None)),
        ):
            read = await _service().update(ctx, artifact.id, ArtifactUpdate())
        update.assert_not_awaited()
        assert read.current_version is None


class TestListing:
    async def test_a_role_that_reaches_everything_skips_the_grant_filter(self) -> None:
        ctx = _ctx()
        with (
            patch(f"{PATH}.visible_resource_ids", new=AsyncMock(return_value=None)),
            patch(
                f"{PATH}.artifact_repo.list_visible", new=AsyncMock(return_value=([], 0))
            ) as listing,
            patch(f"{PATH}.artifact_repo.latest_versions", new=AsyncMock(return_value={})),
        ):
            result = await _service().list_readable(ctx)
        assert result.total == 0
        assert listing.await_args.kwargs["see_all"] is True

    async def test_shared_with_me_asks_for_grants_even_when_the_role_reaches_everything(
        self,
    ) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        with (
            patch(f"{PATH}.visible_resource_ids", new=AsyncMock(return_value=None)),
            patch(
                f"{PATH}.resource_grant_repo.list_shared_ids",
                new=AsyncMock(return_value=[artifact.id]),
            ),
            patch(
                f"{PATH}.artifact_repo.list_visible", new=AsyncMock(return_value=([artifact], 1))
            ) as listing,
            patch(
                f"{PATH}.artifact_repo.latest_versions",
                new=AsyncMock(return_value={artifact.id: _version(artifact)}),
            ),
        ):
            result = await _service().list_readable(ctx, shared_with_me=True)
        assert listing.await_args.kwargs["shared_ids"] == [artifact.id]
        assert result.items[0].current_version is not None

    async def test_versions_are_listed_newest_first(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        kept = [_version(artifact, number=2), _version(artifact, number=1)]
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.artifact_repo.list_versions", new=AsyncMock(return_value=kept)),
        ):
            result = await _service().versions(ctx, artifact.id)
        assert [item.number for item in result.items] == [2, 1]
        assert result.total == 2


class TestPublicLink:
    async def _call(self, method: str, artifact: Artifact, ctx: AuthContext) -> MagicMock:
        audit = AsyncMock()

        async def _update(_db: object, *, artifact: Artifact, update_data: dict) -> Artifact:
            for key, value in update_data.items():
                setattr(artifact, key, value)
            return artifact

        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.artifact_repo.update", new=_update),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.record_audit", new=audit),
        ):
            await getattr(_service(), method)(ctx, artifact.id)
        return audit

    async def test_turning_the_link_on_mints_an_unguessable_key(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        audit = await self._call("set_public_link", artifact, ctx)
        assert artifact.public_key is not None
        assert len(artifact.public_key) >= 32
        assert audit.await_args.kwargs["action"] == "artifact.public_link_enabled"

    async def test_asking_again_rotates_the_key(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx, public_key="old-key")
        audit = await self._call("set_public_link", artifact, ctx)
        assert artifact.public_key not in (None, "old-key")
        assert audit.await_args.kwargs["action"] == "artifact.public_link_rotated"

    async def test_turning_it_off_clears_the_key(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx, public_key="old-key")
        audit = await self._call("clear_public_link", artifact, ctx)
        assert artifact.public_key is None
        assert audit.await_args.kwargs["action"] == "artifact.public_link_disabled"

    async def test_turning_off_a_link_that_is_off_records_nothing(self) -> None:
        ctx = _ctx()
        audit = await self._call("clear_public_link", _artifact(ctx), ctx)
        audit.assert_not_awaited()


class TestDelete:
    async def test_a_delete_takes_the_grants_and_the_bytes_after_the_commit(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.resource_grant_repo.delete_for_resource", new=AsyncMock()) as grants,
            patch(f"{PATH}.artifact_repo.delete_artifact", new=AsyncMock()) as delete,
            patch(f"{PATH}.record_audit", new=AsyncMock()),
            patch(f"{PATH}.spawn_after_commit") as after_commit,
        ):
            await _service().delete(ctx, artifact.id)
        assert grants.await_args.kwargs["resource_type"] == "artifact"
        delete.assert_awaited_once()
        after_commit.call_args.args[1].close()
        assert after_commit.call_args.kwargs["name"] == "artifact-delete"


class TestView:
    async def test_the_address_opens_the_current_version(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        version = _version(artifact, number=4)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
        ):
            view = await _service().view(ctx, artifact.id)
        assert view.version.number == 4
        assert "/artifact-content/" in view.url
        assert view.url.startswith(artifacts.settings.PUBLIC_BASE_URL.rstrip("/"))

    async def test_a_configured_content_origin_is_where_the_frame_loads_from(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        with (
            patch.object(artifacts.settings, "ARTIFACT_ORIGIN", "https://content.example.net/"),
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{PATH}.artifact_repo.get_version",
                new=AsyncMock(return_value=_version(artifact)),
            ),
        ):
            view = await _service().view(ctx, artifact.id, version_id=uuid.uuid4())
        assert view.url.startswith("https://content.example.net/api/v1/artifact-content/")

    async def test_a_pruned_version_is_not_found(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError, match="no longer kept"),
        ):
            await _service().view(ctx, artifact.id, version_id=uuid.uuid4())


class TestPublicView:
    @pytest.mark.security
    async def test_an_unknown_or_revoked_key_is_not_found(self) -> None:
        with (
            patch(f"{PATH}.artifact_repo.get_by_public_key", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await _service().public_view("nope")

    async def test_a_link_to_an_artifact_with_no_version_left_is_not_found(self) -> None:
        artifact = _artifact(_ctx(), public_key="k")
        with (
            patch(f"{PATH}.artifact_repo.get_by_public_key", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await _service().public_view("k")

    async def test_a_live_link_answers_the_title_and_an_address_and_nothing_else(self) -> None:
        artifact = _artifact(_ctx(), public_key="k")
        with (
            patch(f"{PATH}.artifact_repo.get_by_public_key", new=AsyncMock(return_value=artifact)),
            patch(
                f"{PATH}.artifact_repo.latest_version",
                new=AsyncMock(return_value=_version(artifact)),
            ),
        ):
            public = await _service().public_view("k")
        assert public.title == "Weekly report"
        assert set(public.model_dump()) == {"title", "published_at", "view"}


class TestContent:
    async def test_an_address_opens_its_own_version(self) -> None:
        artifact = _artifact(_ctx())
        version = _version(artifact)
        token = create_artifact_view_token(version.id, expires_in=timedelta(minutes=5))
        storage = MagicMock()
        storage.load = AsyncMock(return_value=b"<h1>hi</h1>")
        with (
            patch(
                f"{PATH}.artifact_repo.get_version_with_artifact",
                new=AsyncMock(return_value=(version, artifact)),
            ) as lookup,
            patch(f"{PATH}.get_file_storage", return_value=storage),
        ):
            document = await _service().content(token)
        assert document == b"<h1>hi</h1>"
        assert lookup.await_args.args[1] == version.id

    @pytest.mark.security
    @pytest.mark.parametrize("kind", ["expired", "forged", "wrong-type"])
    async def test_an_address_that_is_not_one_is_not_found(self, kind: str) -> None:
        from app.core.security import create_password_reset_token

        version_id = uuid.uuid4()
        token = {
            "expired": create_artifact_view_token(version_id, expires_in=timedelta(seconds=-5)),
            "forged": "not-a-token",
            "wrong-type": create_password_reset_token(str(version_id)),
        }[kind]
        with (
            patch(f"{PATH}.artifact_repo.get_version_with_artifact", new=AsyncMock()) as lookup,
            pytest.raises(NotFoundError),
        ):
            await _service().content(token)
        lookup.assert_not_awaited()

    async def test_an_address_to_a_pruned_version_is_not_found(self) -> None:
        token = create_artifact_view_token(uuid.uuid4(), expires_in=timedelta(minutes=5))
        with (
            patch(
                f"{PATH}.artifact_repo.get_version_with_artifact", new=AsyncMock(return_value=None)
            ),
            pytest.raises(NotFoundError),
        ):
            await _service().content(token)


class TestRender:
    def test_html_is_served_as_it_was_written(self) -> None:
        artifact = _artifact(_ctx())
        page = b"<script>draw()</script>"
        assert artifacts.render(_version(artifact), page, title="t") == page

    def test_markdown_is_rendered_into_a_page_with_its_raw_html_escaped(self) -> None:
        artifact = _artifact(_ctx())
        version = _version(artifact, media_type=ArtifactMediaType.MARKDOWN.value)
        document = artifacts.render(
            version,
            b"# Sales\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n<script>x()</script>",
            title="Q3 <sales>",
        ).decode()
        assert "<h1>Sales</h1>" in document
        assert "<table>" in document
        assert "<script>" not in document
        assert "<title>Q3 &lt;sales&gt;</title>" in document


class TestThePolicy:
    @pytest.mark.security
    def test_the_page_gets_an_opaque_origin_and_no_network(self) -> None:
        policy = artifacts.content_security_policy()
        directives = {part.split()[0]: part.split()[1:] for part in policy.split("; ")}
        assert "allow-scripts" in directives["sandbox"]
        assert "allow-same-origin" not in directives["sandbox"]
        assert "allow-top-navigation" not in directives["sandbox"]
        assert "allow-forms" not in directives["sandbox"]
        assert directives["connect-src"] == ["'none'"]
        assert directives["default-src"] == ["'none'"]
        assert directives["frame-ancestors"] == [artifacts.settings.FRONTEND_URL.rstrip("/")]
        for directive in ("script-src", "style-src", "img-src", "font-src"):
            assert not any(
                source.startswith(("http", "https:", "*")) for source in directives[directive]
            )


class TestUnlinking:
    async def test_a_failed_unlink_is_logged_not_raised(self) -> None:
        storage = MagicMock()
        storage.delete = AsyncMock(side_effect=[OSError("gone"), None])
        with patch(f"{PATH}.get_file_storage", return_value=storage):
            await artifacts._unlink_best_effort(["a", "b"])
        assert storage.delete.await_count == 2

    async def test_a_failed_prefix_removal_is_logged_not_raised(self) -> None:
        storage = MagicMock()
        storage.delete_prefix = AsyncMock(side_effect=OSError("gone"))
        with patch(f"{PATH}.get_file_storage", return_value=storage):
            await artifacts._remove_prefix_best_effort("artifacts/x/")
        storage.delete_prefix.assert_awaited_once_with("artifacts/x/")


def test_the_console_address_is_the_artifact_s_page() -> None:
    artifact_id = uuid.uuid4()
    assert artifacts.console_url_for(artifact_id) == f"/artifacts/{artifact_id}"
