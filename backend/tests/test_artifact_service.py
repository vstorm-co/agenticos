"""The artifact service's decisions, with the database stubbed at the repository edge.

`tests/integration/test_artifacts.py` proves what the rows do. This proves what the
service decides about them: a private or revoked artifact is a 404 and never a
403, a public link is a rotation as well as an enable, a signed address opens
exactly one version and nothing past its expiry, and the content is served as a
document - HTML as written, Markdown rendered with its raw HTML escaped.
"""

import hashlib
import logging
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import jwt
import pytest
from sqlalchemy.exc import DBAPIError

from app.core.exceptions import DatabaseError, NotFoundError, RateLimitError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.core.security import create_artifact_view_token, verify_special_token
from app.db.models.artifact import Artifact, ArtifactMediaType, ArtifactVersion
from app.db.models.resource_grant import Visibility
from app.schemas.artifact import (
    ArtifactBinding,
    ArtifactData,
    ArtifactUpdate,
    BindingReach,
    WorkflowLogBinding,
)
from app.services import artifact as artifacts
from app.services import rate_limit
from app.services.artifact import ArtifactService
from app.services.artifact_bindings import Reason, Unavailable, page_data
from app.services.artifact_consent import Served
from app.services.virtual_tables.exceptions import DeadlineReached, InvalidQueryError

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_public_data_state() -> Any:
    """`_detail` asks the public-data service for the link's state; these tests stub the
    database, so it answers nothing."""
    with patch(
        "app.services.artifact_public_data.ArtifactPublicDataService.state",
        AsyncMock(return_value=None),
    ):
        yield


PATH = "app.services.artifact"


@pytest.fixture(autouse=True)
def _shared_with_no_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """The listing names each page's groups; the session here is a mock."""

    async def nowhere(*_args: object, resource_ids: list[uuid.UUID], **_kwargs: object):
        return {resource_id: [] for resource_id in resource_ids}

    monkeypatch.setattr(f"{PATH}.groups_sharing", nowhere)


@pytest.fixture(autouse=True)
def _nobody_follows(monkeypatch: pytest.MonkeyPatch) -> None:
    """The repository is mocked call by call here, and following is its own
    concern - `TestFollowing` in `test_artifact_followers.py` covers it."""
    from app.repositories import artifact as artifact_repo

    monkeypatch.setattr(artifact_repo, "is_following", AsyncMock(return_value=False))
    monkeypatch.setattr(artifact_repo, "follower_ids", AsyncMock(return_value=[]))


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
        public_view_count=0,
        embed_origins=[],
        auto_consent=False,
        published_at=datetime(2026, 9, 22, tzinfo=UTC),
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def _version(
    artifact: Artifact,
    *,
    number: int = 1,
    media_type: str = ArtifactMediaType.HTML.value,
    bindings: list[dict[str, Any]] | None = None,
    consent_state: str = "not_needed",
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
        bindings=bindings or [],
        actions=[],
        consent_state=consent_state,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
    )


def _service() -> ArtifactService:
    return ArtifactService(MagicMock())


def _binding(name: str = "deals", table_id: uuid.UUID | None = None) -> dict[str, Any]:
    """A page query as a version stores it."""
    table_id = table_id or uuid.uuid4()
    stage = uuid.uuid4()
    return ArtifactBinding(
        name=name,
        table_id=table_id,
        limit=1000,
        fields={"stage": stage},
        reach=BindingReach(tables={table_id: {stage: 0}}),
    ).model_dump(mode="json")


def _claims(url: str) -> dict[str, Any]:
    claims = verify_special_token(
        url.rsplit("/", 1)[1], "artifact_view", audience=("member", "public")
    )
    assert claims is not None
    return claims


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

    async def test_a_run_asks_for_a_share_on_a_session_of_its_own(self) -> None:
        session = MagicMock()
        opened = MagicMock()
        opened.__aenter__ = AsyncMock(return_value=session)
        opened.__aexit__ = AsyncMock(return_value=None)
        expected = MagicMock()
        organization_id, agent_id, run_person = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        with (
            patch(f"{PATH}.get_db_context", return_value=opened),
            patch(f"{PATH}.request_share_with", new=AsyncMock(return_value=expected)) as inner,
        ):
            result = await artifacts.request_share(
                organization_id=organization_id,
                agent_id=agent_id,
                run_person=run_person,
                run_id=None,
                name="r",
                visibility=Visibility.ORG,
                people=["Ada"],
            )
        assert result is expected
        assert inner.await_args.args == (session,)
        assert inner.await_args.kwargs == {
            "organization_id": organization_id,
            "agent_id": agent_id,
            "run_person": run_person,
            "run_id": None,
            "name": "r",
            "visibility": Visibility.ORG,
            "people": ["Ada"],
            "room": False,
        }

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
                environment_id=None,
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
                environment_id=None,
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

    async def test_a_bound_page_reads_as_live_and_shows_its_editor_the_field_names(
        self,
    ) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        table_id = uuid.uuid4()
        status, title = uuid.uuid4(), uuid.uuid4()
        binding = ArtifactBinding(
            name="tickets",
            table_id=table_id,
            limit=1000,
            fields={"status": status, "title": title},
            reach=BindingReach(tables={table_id: {status: 0, title: 2}}),
        ).model_dump(mode="json")
        version = _version(artifact, bindings=[binding], consent_state="pending")
        version.query_fingerprint = "f" * 64
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.artifact_repo.latest_served", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.member_repo.get_active", new=AsyncMock(return_value=MagicMock())),
            patch(
                f"{PATH}.user_repo.get_by_id",
                new=AsyncMock(return_value=MagicMock(full_name="Ada Lovelace")),
            ),
        ):
            read = await _service().read(ctx, artifact.id)
        assert read.live is True
        assert read.consent is not None
        assert (read.consent.state, read.consent.fingerprint) == ("pending", "f" * 64)
        assert (read.consent.audience_version, read.consent.owner_name) == (None, "Ada Lovelace")
        assert read.consent.may_confirm is True
        [shown] = read.bindings
        assert shown.model_dump() == {
            "kind": "table",
            "name": "tickets",
            "table_id": table_id,
            "fields": ["status", "title"],
        }

    async def test_a_page_with_no_version_is_not_live(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=None)),
        ):
            read = await _service().read(ctx, artifact.id)
        assert (read.live, read.bindings) == (False, [])

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

    async def test_a_project_s_apps_are_asked_for_only_once_the_project_is_seen(self) -> None:
        """A project the caller cannot see answers 404, as opening it does, rather
        than an empty list that says it exists and holds nothing."""
        ctx = _ctx()
        project_id = uuid.uuid4()
        seen = AsyncMock()
        with (
            patch(f"{PATH}.ProjectService") as projects,
            patch(f"{PATH}.visible_resource_ids", new=AsyncMock(return_value=None)),
            patch(
                f"{PATH}.artifact_repo.list_visible", new=AsyncMock(return_value=([], 0))
            ) as listing,
            patch(f"{PATH}.artifact_repo.latest_versions", new=AsyncMock(return_value={})),
        ):
            projects.return_value.get = seen
            await _service().list_readable(ctx, project_id=project_id)
        seen.assert_awaited_once_with(ctx, project_id)
        assert listing.await_args.kwargs["project_id"] == project_id

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
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=kept[0])),
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
            patch(f"{PATH}.artifact_repo.latest_served", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.artifact_repo.list_versions", new=AsyncMock(return_value=[])),
            patch(f"{PATH}.artifact_repo.lock", new=AsyncMock(return_value=None)),
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
                f"{PATH}.artifact_repo.latest_version",
                new=AsyncMock(return_value=_version(artifact)),
            ),
        ):
            view = await _service().view(ctx, artifact.id)
        assert view.url.startswith("https://content.example.net/api/v1/artifact-content/")

    async def test_a_pruned_version_is_not_found(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{PATH}.artifact_repo.latest_version",
                new=AsyncMock(return_value=_version(artifact)),
            ),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError, match="no longer kept"),
        ):
            await _service().view(ctx, artifact.id, version_id=uuid.uuid4())

    async def test_the_current_bound_version_mints_a_live_token_with_a_nonce(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        version = _version(artifact, number=4, bindings=[_binding()])
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=version)),
        ):
            current = await _service().view(ctx, artifact.id)
            named = await _service().view(ctx, artifact.id, version_id=version.id)
        for view in (current, named):
            claims = _claims(view.url)
            assert view.live is True
            assert claims["live"] is True
            assert claims["n"] == view.nonce
            assert len(view.nonce) >= 16
        # A nonce per frame, so a late reply for one load cannot reach the next.
        assert current.nonce != named.nonce

    @pytest.mark.security
    async def test_a_view_names_the_member_and_asks_for_data_only_when_told_to(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        version = _version(artifact, number=4, bindings=[_binding()])
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.member_context", new=AsyncMock(return_value=ctx)),
        ):
            plain = await _service().view(ctx, artifact.id)
            with_data = await _service().view(ctx, artifact.id, data=True)
        assert plain.injected is False
        assert with_data.injected is True
        assert (with_data.bindings, with_data.awaiting_consent) == (1, False)
        for view, inject in ((plain, False), (with_data, True)):
            claims = _claims(view.url)
            assert claims["aud"] == "member"
            assert claims["uid"] == str(ctx.user_id)
            assert claims["org"] == str(ctx.organization_id)
            assert claims["inj"] is inject

    @pytest.mark.security
    async def test_a_view_injects_only_for_an_active_member_of_the_pages_organization(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        version = _version(artifact, number=4, bindings=[_binding()])
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.member_context", new=AsyncMock(return_value=None)),
        ):
            view = await _service().view(ctx, artifact.id, data=True)
        assert view.injected is False
        assert view.live is True
        assert _claims(view.url)["inj"] is False

    async def test_a_view_tells_everyone_whether_the_data_waits_for_consent(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        version = _version(artifact, number=4, bindings=[_binding("a"), _binding("b")])
        waiting = Served(version=version, data=False, latest=False)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.member_context", new=AsyncMock(return_value=ctx)),
            patch.object(ArtifactService, "_served", new=AsyncMock(return_value=waiting)),
        ):
            view = await _service().view(ctx, artifact.id, data=True)
        assert (view.bindings, view.awaiting_consent) == (2, True)
        # The page is still served its (empty) data: it says the data waits.
        assert view.injected is True

    @pytest.mark.security
    async def test_a_page_with_nothing_bound_and_an_older_version_never_inject(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        unbound = _version(artifact, number=4)
        older = _version(artifact, number=3, bindings=[_binding()])
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=unbound)),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=older)),
            patch(f"{PATH}.member_context", new=AsyncMock(return_value=None)),
        ):
            current = await _service().view(ctx, artifact.id, data=True)
            history = await _service().view(ctx, artifact.id, version_id=older.id, data=True)
        assert current.injected is False
        assert history.injected is False
        assert _claims(history.url)["inj"] is False

    async def test_an_older_version_mints_a_token_that_is_not_live(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        older = _version(artifact, number=3, bindings=[_binding()])
        latest = _version(artifact, number=4, bindings=[_binding()])
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=latest)),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=older)),
        ):
            view = await _service().view(ctx, artifact.id, version_id=older.id)
        assert view.live is False
        assert _claims(view.url)["live"] is False
        assert _claims(view.url)["n"] == view.nonce

    async def test_a_current_version_with_no_bindings_is_not_live(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        version = _version(artifact)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
        ):
            view = await _service().view(ctx, artifact.id)
        assert view.live is False
        assert _claims(view.url)["live"] is False


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
            patch(f"{PATH}.artifact_repo.latest_served", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await _service().public_view("k")

    async def test_a_live_link_answers_the_title_and_an_address_and_nothing_else(self) -> None:
        artifact = _artifact(_ctx(), public_key="k")
        with (
            patch(f"{PATH}.artifact_repo.get_by_public_key", new=AsyncMock(return_value=artifact)),
            patch(
                f"{PATH}.artifact_repo.latest_served",
                new=AsyncMock(return_value=_version(artifact)),
            ),
            patch(f"{PATH}.artifact_repo.count_public_view", new=AsyncMock()) as counted,
        ):
            public = await _service().public_view("k")
        assert public.title == "Weekly report"
        assert public.password_required is False
        assert set(public.model_dump()) == {"password_required", "title", "published_at", "view"}
        assert counted.await_args.args[1] == artifact.id

    @pytest.mark.security
    async def test_a_public_link_and_an_embed_are_never_live(self) -> None:
        artifact = _artifact(_ctx(), public_key="k")
        artifact.embed_origins = ["https://a.example.com"]
        version = _version(artifact, bindings=[_binding()], consent_state="consented")
        with (
            patch(f"{PATH}.artifact_repo.get_by_public_key", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.artifact_repo.latest_served", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.artifact_repo.count_public_view", new=AsyncMock()),
            patch(
                f"{PATH}.organization_repo.get_by_id",
                new=AsyncMock(return_value=MagicMock(public_live_data=False)),
            ),
            patch(f"{PATH}.owner_membership_id", new=AsyncMock(return_value=None)),
        ):
            public = await _service().public_view("k")
            embed = await _service().embed("k")
        assert public.view is not None
        assert public.view.live is False
        assert public.view.injected is False
        assert _claims(public.view.url)["live"] is False
        assert _claims(public.view.url)["aud"] == "public"
        assert _claims(public.view.url)["inj"] is False
        assert "uid" not in _claims(public.view.url)
        assert _claims(public.view.url)["pk"] == hashlib.sha256(b"k").hexdigest()
        frame = re.search(r'src="([^"]*/artifact-content/[^"]+)"', embed.document.decode())
        assert frame is not None
        assert _claims(frame.group(1))["live"] is False


class TestContent:
    async def test_an_address_opens_its_own_version(self) -> None:
        artifact = _artifact(_ctx(), public_key="k")
        version = _version(artifact)
        token = create_artifact_view_token(
            version.id,
            expires_in=timedelta(minutes=5),
            nonce="n0",
            live=False,
            audience="public",
            public_key="k",
        )
        storage = MagicMock()
        storage.load = AsyncMock(return_value=b"<h1>hi</h1>")
        with (
            patch(
                f"{PATH}.artifact_repo.get_version_with_artifact",
                new=AsyncMock(return_value=(version, artifact)),
            ) as lookup,
            patch(f"{PATH}.get_file_storage", return_value=storage),
        ):
            served = await _service().content(token)
        assert served.document == (
            artifacts.platform_script(nonce="n0", live=False, names=[]).encode() + b"<h1>hi</h1>"
        )
        assert served.embed_origins == []
        assert lookup.await_args.args[1] == version.id

    @pytest.mark.security
    @pytest.mark.parametrize("kind", ["expired", "forged", "wrong-type"])
    async def test_an_address_that_is_not_one_is_not_found(self, kind: str) -> None:
        from app.core.security import create_password_reset_token

        version_id = uuid.uuid4()
        token = {
            "expired": create_artifact_view_token(
                version_id,
                expires_in=timedelta(seconds=-5),
                nonce="n0",
                live=False,
                audience="public",
            ),
            "forged": "not-a-token",
            "wrong-type": create_password_reset_token(str(version_id)),
        }[kind]
        with (
            patch(f"{PATH}.artifact_repo.get_version_with_artifact", new=AsyncMock()) as lookup,
            pytest.raises(NotFoundError),
        ):
            await _service().content(token)
        lookup.assert_not_awaited()

    async def test_an_address_whose_bytes_are_gone_is_not_found(self) -> None:
        """A row whose bytes storage no longer has - a restored database beside an
        older volume - answered 500, and a thumbnail showed a server error."""
        artifact = _artifact(_ctx(), public_key="k")
        version = _version(artifact)
        token = create_artifact_view_token(
            version.id,
            expires_in=timedelta(minutes=5),
            nonce="n0",
            live=False,
            audience="public",
            public_key="k",
        )
        storage = MagicMock()
        storage.load = AsyncMock(side_effect=FileNotFoundError(version.storage_path))
        with (
            patch(
                f"{PATH}.artifact_repo.get_version_with_artifact",
                new=AsyncMock(return_value=(version, artifact)),
            ),
            patch(f"{PATH}.get_file_storage", return_value=storage),
            patch(f"{PATH}.logger") as log,
            pytest.raises(NotFoundError, match="App not found"),
        ):
            await _service().content(token)
        # Said out loud, because it is storage and the database disagreeing.
        assert log.warning.call_args.args[0] == "artifact_bytes_missing"

    @pytest.mark.security
    async def test_a_token_without_a_nonce_serves_a_page_that_is_not_live(self) -> None:
        """A token minted before the nonce existed opens its page, with no data."""
        artifact = _artifact(_ctx(), public_key="k")
        version = _version(artifact, bindings=[_binding()])
        token = jwt.encode(
            {
                "exp": datetime.now(UTC) + timedelta(minutes=5),
                "sub": str(version.id),
                "type": "artifact_view",
                "aud": "public",
                "pk": hashlib.sha256(b"k").hexdigest(),
                "live": True,
            },
            artifacts.settings.SECRET_KEY,
            algorithm=artifacts.settings.ALGORITHM,
        )
        storage = MagicMock()
        storage.load = AsyncMock(return_value=b"<h1>hi</h1>")
        with (
            patch(
                f"{PATH}.artifact_repo.get_version_with_artifact",
                new=AsyncMock(return_value=(version, artifact)),
            ),
            patch(f"{PATH}.get_file_storage", return_value=storage),
        ):
            served = await _service().content(token)
        assert served.document == (
            artifacts.platform_script(nonce="", live=False, names=["deals"]).encode()
            + b"<h1>hi</h1>"
        )

    async def test_an_address_to_a_pruned_version_is_not_found(self) -> None:
        token = create_artifact_view_token(
            uuid.uuid4(), expires_in=timedelta(minutes=5), nonce="n0", live=False, audience="public"
        )
        with (
            patch(
                f"{PATH}.artifact_repo.get_version_with_artifact", new=AsyncMock(return_value=None)
            ),
            pytest.raises(NotFoundError),
        ):
            await _service().content(token)


class TestContentAudience:
    def _served(self, audience: str) -> tuple[Any, Any, str]:
        artifact = _artifact(_ctx(), public_key="k")
        artifact.embed_origins = ["https://a.example.com"]
        version = _version(artifact, bindings=[_binding()])
        kwargs: dict[str, Any] = {}
        if audience == "member":
            kwargs = {"user_id": uuid.uuid4(), "organization_id": artifact.organization_id}
        token = create_artifact_view_token(
            version.id,
            expires_in=timedelta(minutes=5),
            nonce="n0",
            live=True,
            audience=audience,
            public_key="k",
            **kwargs,
        )
        return artifact, version, token

    async def _content(self, artifact: Any, version: Any, token: str) -> Any:
        storage = MagicMock()
        storage.load = AsyncMock(return_value=b"<h1>hi</h1>")
        with (
            patch(
                f"{PATH}.artifact_repo.get_version_with_artifact",
                new=AsyncMock(return_value=(version, artifact)),
            ),
            patch(f"{PATH}.get_file_storage", return_value=storage),
        ):
            return await _service().content(token)

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("audience", "origins"), [("member", []), ("public", ["https://a.example.com"])]
    )
    async def test_member_tokens_name_the_console_and_public_ones_the_embedding_sites(
        self, audience: str, origins: list[str]
    ) -> None:
        artifact, version, token = self._served(audience)
        served = await self._content(artifact, version, token)
        assert served.embed_origins == origins

    @pytest.mark.security
    @pytest.mark.parametrize("audience", ["member", "public"])
    @pytest.mark.parametrize("expired", [False, True])
    async def test_public_link_expiry_cuts_off_existing_public_content_tokens(
        self, audience, expired
    ):
        artifact, version, token = self._served(audience)
        artifact.public_expires_at = datetime.now(UTC) + timedelta(seconds=-1 if expired else 3600)
        if audience == "public" and expired:
            with patch(f"{PATH}._load_version", new_callable=AsyncMock) as load:
                with pytest.raises(NotFoundError, match="App not found"):
                    await self._content(artifact, version, token)
                load.assert_not_awaited()
        else:
            assert await self._content(artifact, version, token)

    @pytest.mark.security
    async def test_a_token_with_no_audience_opens_nothing(self) -> None:
        artifact, version, _ = self._served("public")
        token = jwt.encode(
            {
                "exp": datetime.now(UTC) + timedelta(minutes=5),
                "sub": str(version.id),
                "type": "artifact_view",
                "n": "n0",
                "live": False,
            },
            artifacts.settings.SECRET_KEY,
            algorithm=artifacts.settings.ALGORITHM,
        )
        with pytest.raises(NotFoundError):
            await self._content(artifact, version, token)

    @pytest.mark.security
    async def test_a_public_token_is_never_read_as_a_member_whatever_it_claims(self) -> None:
        artifact, version, _ = self._served("public")
        token = jwt.encode(
            {
                "exp": datetime.now(UTC) + timedelta(minutes=5),
                "sub": str(version.id),
                "type": "artifact_view",
                "aud": "public",
                "pk": hashlib.sha256(b"k").hexdigest(),
                "n": "n0",
                "live": True,
                "inj": True,
                "uid": str(uuid.uuid4()),
                "org": str(artifact.organization_id),
            },
            artifacts.settings.SECRET_KEY,
            algorithm=artifacts.settings.ALGORITHM,
        )
        with patch.object(ArtifactService, "_injection", new=AsyncMock()) as injection:
            served = await self._content(artifact, version, token)
        injection.assert_not_awaited()
        # No `pw` claim: the public gates refuse it, and every binding is unavailable.
        assert b'"status": "ok"' not in served.document
        assert b'"status": "unavailable"' in served.document

    @pytest.mark.security
    @pytest.mark.parametrize("claim", ["missing", "other-key"])
    async def test_a_public_token_for_another_key_is_not_found(self, claim: str) -> None:
        artifact, version, _ = self._served("public")
        token = create_artifact_view_token(
            version.id,
            expires_in=timedelta(minutes=5),
            nonce="n0",
            live=False,
            audience="public",
            public_key="old" if claim == "other-key" else None,
        )
        with pytest.raises(NotFoundError):
            await self._content(artifact, version, token)


class TestViewToken:
    def test_a_member_address_without_the_member_is_refused(self) -> None:
        with pytest.raises(ValueError, match="names the member"):
            create_artifact_view_token(
                uuid.uuid4(),
                expires_in=timedelta(minutes=5),
                nonce="n0",
                live=False,
                audience="member",
            )

    @pytest.mark.security
    def test_a_token_with_an_audience_is_not_another_kind_of_token(self) -> None:
        token = create_artifact_view_token(
            uuid.uuid4(), expires_in=timedelta(minutes=5), nonce="n0", live=False, audience="public"
        )
        assert verify_special_token(token, "artifact_view") is None
        assert verify_special_token(token, "artifact_view", audience=("public",)) is not None


class TestRender:
    def test_html_is_served_as_it_was_written_behind_the_platform_script(self) -> None:
        artifact = _artifact(_ctx())
        page = b"<script>draw()</script>"
        assert (
            artifacts.render(_version(artifact), page, title="t", nonce="n0", live=False)
            == artifacts.platform_script(nonce="n0", live=False, names=[]).encode() + page
        )

    def test_markdown_is_rendered_into_a_page_with_its_raw_html_escaped(self) -> None:
        artifact = _artifact(_ctx())
        version = _version(artifact, media_type=ArtifactMediaType.MARKDOWN.value)
        document = artifacts.render(
            version,
            b"# Sales\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n<script>x()</script>",
            title="Q3 <sales>",
            nonce="n0",
            live=False,
        ).decode()
        assert "<h1>Sales</h1>" in document
        assert "<table>" in document
        assert "<script>x()</script>" not in document
        assert document.count("<script") == 2
        assert 'data-agenticos="platform"' in document
        assert 'data-agenticos="data"' in document
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
        # `connect-src` does not govern navigation, so a popup would be a way
        # out to an address the page chose, and escaping the sandbox a worse one.
        assert "allow-popups" not in directives["sandbox"]
        assert "allow-popups-to-escape-sandbox" not in directives["sandbox"]
        assert directives["connect-src"] == ["'none'"]
        assert directives["default-src"] == ["'none'"]
        assert directives["frame-ancestors"] == [artifacts.settings.FRONTEND_URL.rstrip("/")]
        library = f"{artifacts.settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/artifact-content/lib/"
        for directive in ("script-src", "style-src", "img-src", "font-src"):
            remote = [
                source
                for source in directives[directive]
                if source.startswith(("http", "https:", "*"))
            ]
            # The deployment's own library set, by its path, and nothing else.
            assert remote in ([], [library])
        assert directives["img-src"] == ["data:", "blob:"]

    @pytest.mark.security
    def test_map_tiles_come_from_the_deployment_s_own_tile_path_and_no_remote_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(artifacts.settings, "VISUAL_MAP_TILES", "openstreetmap")
        policy = artifacts.content_security_policy()
        directives = {part.split()[0]: part.split()[1:] for part in policy.split("; ")}
        tiles = f"{artifacts.settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/artifact-content/tiles/"
        assert directives["img-src"] == ["data:", "blob:", tiles]
        assert "openstreetmap" not in policy
        assert directives["connect-src"] == ["'none'"]

    @pytest.mark.security
    def test_an_embeddable_page_may_be_framed_by_its_sites_and_the_embed_document(self) -> None:
        policy = artifacts.content_security_policy(embed_origins=["https://intranet.example.com"])
        ancestors = next(
            part for part in policy.split("; ") if part.startswith("frame-ancestors")
        ).split()[1:]
        assert ancestors == [
            artifacts.settings.FRONTEND_URL.rstrip("/"),
            artifacts.settings.PUBLIC_BASE_URL.rstrip("/"),
            "https://intranet.example.com",
        ]

    @pytest.mark.security
    def test_the_embed_document_runs_only_its_own_script_and_frames_only_content(self) -> None:
        policy = artifacts.embed_security_policy(nonce="n0nce", embed_origins=[])
        directives = {part.split()[0]: part.split()[1:] for part in policy.split("; ")}
        assert directives["script-src"] == ["'nonce-n0nce'"]
        assert directives["frame-src"] == [artifacts.settings.PUBLIC_BASE_URL.rstrip("/")]
        assert directives["connect-src"] == ["'none'"]
        assert directives["frame-ancestors"] == ["'none'"]

    @pytest.mark.security
    def test_the_embed_document_relays_a_link_and_never_a_request_for_data(self) -> None:
        document = artifacts._embed_document(
            nonce="n0nce", title="T", frame_url="https://x/c/t", public_url="https://x/a/k"
        ).decode()
        assert "agenticos:open-link" in document
        assert "agenticos:ready" not in document
        assert "agenticos:data" not in document
        assert "postMessage" not in document


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


def test_the_console_address_is_the_artifact_s_page_in_its_organization() -> None:
    artifact_id, organization_id = uuid.uuid4(), uuid.uuid4()
    assert (
        artifacts.console_url_for(artifact_id, organization_id)
        == f"/apps/{artifact_id}?org={organization_id}"
    )


class _Claims:
    """`SET NX` and compare-and-delete on a dict, standing in for the shared Redis."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def delete_if_equals(self, key: str, value: str) -> bool:
        if self.store.get(key) != value:
            return False
        del self.store[key]
        return True


@pytest.fixture
def claims() -> Iterator[_Claims]:
    shared = _Claims()
    client = MagicMock()
    client.set = shared.set
    client.delete_if_equals = shared.delete_if_equals
    rate_limit.configure(client)
    yield shared
    rate_limit.configure(None)


def _session() -> MagicMock:
    """A session whose savepoint passes an exception on, as a real one does."""
    db = MagicMock()
    db.begin_nested.return_value.__aexit__ = AsyncMock(return_value=False)
    return db


class TestData:
    @pytest.mark.security
    async def test_a_second_load_in_flight_for_the_same_viewer_is_refused(
        self, claims: _Claims
    ) -> None:
        viewer, other = _ctx(), _ctx()
        reading = anyio.Event()
        release = anyio.Event()

        async def get(db: Any, artifact_id: uuid.UUID, *, organization_id: uuid.UUID) -> None:
            if organization_id == viewer.organization_id:
                reading.set()
                await release.wait()

        outcomes: list[BaseException] = []

        async def first() -> None:
            try:
                await _service().data(viewer, uuid.uuid4(), uuid.uuid4())
            except NotFoundError as missing:
                outcomes.append(missing)

        with patch(f"{PATH}.artifact_repo.get", new=AsyncMock(side_effect=get)):
            async with anyio.create_task_group() as group:
                group.start_soon(first)
                await reading.wait()
                with pytest.raises(RateLimitError) as refused:
                    await _service().data(viewer, uuid.uuid4(), uuid.uuid4())
                with pytest.raises(NotFoundError):
                    await _service().data(other, uuid.uuid4(), uuid.uuid4())
                release.set()

        assert refused.value.message == (
            "Your previous data load is still running. Try again in a moment."
        )
        assert refused.value.status_code == 429
        assert len(outcomes) == 1
        assert claims.store == {}

    async def test_a_read_of_the_reasons_alone_does_not_collide_with_the_page_s_own_load(
        self, claims: _Claims
    ) -> None:
        """An editor's strip asks why a source is empty while - or just after - their page
        is served with its data: the two hold different claims, so neither refuses the other."""
        viewer = _ctx()
        reading = anyio.Event()
        release = anyio.Event()

        async def get(db: Any, artifact_id: uuid.UUID, *, organization_id: uuid.UUID) -> None:
            reading.set()
            await release.wait()

        async def full() -> None:
            with pytest.raises(NotFoundError):
                await _service().data(viewer, uuid.uuid4(), uuid.uuid4())

        with patch(f"{PATH}.artifact_repo.get", new=AsyncMock(side_effect=get)):
            async with anyio.create_task_group() as group:
                group.start_soon(full)
                await reading.wait()
                # Not a RateLimitError: it got as far as looking for the page.
                with pytest.raises(NotFoundError):
                    reasons = _service().data(viewer, uuid.uuid4(), uuid.uuid4(), rows=False)
                    release.set()
                    await reasons
        assert claims.store == {}

    @pytest.mark.parametrize("locked", [False, True])
    async def test_a_read_of_the_reasons_alone_reads_no_records_and_passes_the_load_gate(
        self, locked: bool
    ) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        version = _version(artifact, bindings=[_binding()])
        reading: dict[str, Any] = {}
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{PATH}.served",
                new=AsyncMock(
                    return_value=artifacts.Served(version=version, data=True, latest=True)
                ),
            ),
            patch(f"{PATH}.rate_limit.one_in_flight") as claim,
            patch(f"{PATH}._load_gate") as gate,
            patch(
                f"{PATH}.ArtifactService._read_page", new=AsyncMock(return_value=reading)
            ) as read,
        ):
            claim.return_value.__aenter__ = AsyncMock(return_value=None)
            claim.return_value.__aexit__ = AsyncMock(return_value=False)
            gate.return_value.locked.return_value = locked
            gate.return_value.__aenter__ = AsyncMock(return_value=None)
            gate.return_value.__aexit__ = AsyncMock(return_value=False)
            if locked:
                # A process as busy as it may be refuses it, as it refuses a full load.
                with pytest.raises(RateLimitError):
                    await _service().data(ctx, artifact.id, version.id, rows=False)
                read.assert_not_awaited()
                return
            result = await _service().data(ctx, artifact.id, version.id, rows=False)
        assert result.bindings == reading
        assert read.await_args.kwargs["rows"] is False
        assert claim.call_args.args[0] == "artifact_data_reasons"

    async def test_the_reasons_alone_run_the_query_for_no_records(self) -> None:
        service = _service()
        binding = ArtifactBinding.model_validate(_binding())
        table = MagicMock(columns=[])
        ok = artifacts.BindingRows(fields=binding.fields, rows=MagicMock(records=[]))
        with (
            patch.object(service, "_binding_source", AsyncMock(return_value=table)),
            patch.object(service, "_read_rows", AsyncMock(return_value=ok)) as rows,
        ):
            readable = await service._read_reasons(_ctx(), binding, MagicMock())
        assert readable is ok
        assert rows.await_args.kwargs["max_records"] == 0
        gone = Unavailable("creator_lost_access")
        with patch.object(service, "_binding_source", AsyncMock(return_value=gone)):
            assert await service._read_reasons(_ctx(), binding, MagicMock()) is gone

    async def test_a_filter_the_converted_column_no_longer_answers_is_a_reason_here_too(
        self,
    ) -> None:
        """What the page's own load says is what the editor's strip says."""
        binding = ArtifactBinding.model_validate(_binding())
        service = _service()
        with (
            patch(f"{PATH}.virtual_table_repo.statement_timeout", new=AsyncMock(return_value="0")),
            patch.object(
                artifacts.VirtualTableService,
                "read_bound",
                AsyncMock(side_effect=InvalidQueryError("filters.0", "Not a number")),
            ) as read,
            patch.object(
                service,
                "_binding_source",
                AsyncMock(return_value=MagicMock(columns=[], name="Deals")),
            ),
        ):
            found = await service._read_reasons(_ctx(), binding, MagicMock(remaining_ms=lambda: 5))
        assert isinstance(found, Unavailable)
        assert found.reason == "source_changed"
        assert read.await_args.kwargs["max_records"] == 0

    @pytest.mark.security
    async def test_a_database_error_in_the_reasons_alone_is_that_source_failed(self) -> None:
        """As in the page's own load: one source, never a 500 - and never its parameters."""
        ctx = _ctx()
        artifact = _artifact(ctx)
        version = _version(artifact, bindings=[_binding()])
        broken = DBAPIError("SELECT 1", {"needle": "x"}, MagicMock(sqlstate="40001"))
        with (
            patch(f"{PATH}.member_context", new=AsyncMock(return_value=ctx)),
            patch(f"{PATH}.ArtifactService._read_reasons", new=AsyncMock(side_effect=broken)),
        ):
            bindings = await _service()._read_page(
                artifact,
                version,
                artifacts.Served(version=version, data=True, latest=True),
                can_edit=True,
                current=True,
                rows=False,
            )
        assert bindings["deals"].reason == "failed"

    async def test_a_page_read_for_its_reasons_reads_no_binding_s_rows(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        version = _version(artifact, bindings=[_binding()])
        with (
            patch(f"{PATH}.member_context", new=AsyncMock(return_value=ctx)),
            patch(f"{PATH}.ArtifactService._read_binding", new=AsyncMock()) as rows,
            patch(
                f"{PATH}.ArtifactService._read_reasons",
                new=AsyncMock(return_value=Unavailable("creator_lost_access")),
            ) as reasons,
        ):
            bindings = await _service()._read_page(
                artifact,
                version,
                artifacts.Served(version=version, data=True, latest=True),
                can_edit=True,
                current=True,
                rows=False,
            )
        rows.assert_not_awaited()
        reasons.assert_awaited_once()
        assert bindings["deals"].reason == "creator_lost_access"

    @pytest.mark.security
    async def test_the_process_gate_refuses_at_once_when_full(self, monkeypatch) -> None:
        monkeypatch.setattr(artifacts.settings, "ARTIFACT_DATA_MAX_CONCURRENT_LOADS", 2)
        gate = artifacts._load_gate()
        for _ in range(2):
            await gate.acquire()
        read = AsyncMock(return_value=None)
        try:
            with (
                patch(f"{PATH}.artifact_repo.get", new=read),
                pytest.raises(RateLimitError) as refused,
            ):
                await _service().data(_ctx(), uuid.uuid4(), uuid.uuid4())
        finally:
            gate.release()
            gate.release()

        assert refused.value.message == (
            "Too many pages are loading data right now. Try again in a moment."
        )
        read.assert_not_awaited()
        assert artifacts._load_gate() is gate
        with patch(f"{PATH}.artifact_repo.get", new=read), pytest.raises(NotFoundError):
            await _service().data(_ctx(), uuid.uuid4(), uuid.uuid4())

    async def test_a_version_of_another_artifact_is_not_found(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(
                f"{PATH}.artifact_repo.latest_version",
                new=AsyncMock(return_value=_version(artifact)),
            ),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError) as missing,
        ):
            await _service().data(ctx, artifact.id, uuid.uuid4())
        assert missing.value.message == "This version of the app is no longer kept"

    @pytest.mark.parametrize(
        "stopped",
        [
            DBAPIError("SELECT pg_sleep(1)", {"needle": "x"}, MagicMock(sqlstate="57014")),
            DeadlineReached(remaining_ms=0),
        ],
        ids=["statement_timeout", "deadline"],
    )
    async def test_a_stopped_read_is_a_timeout_for_that_binding(self, stopped: Exception) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        version = _version(artifact, bindings=[_binding()])
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.member_context", new=AsyncMock(return_value=ctx)),
            patch(
                f"{PATH}.virtual_table_repo.statement_timeout",
                new=AsyncMock(side_effect=stopped),
            ),
        ):
            data = await ArtifactService(_session()).data(ctx, artifact.id, version.id)
        assert data.bindings["deals"].status == "unavailable"
        assert data.bindings["deals"].reason == "timeout"

    @pytest.mark.parametrize(
        "stopped",
        [
            DBAPIError("SELECT pg_sleep(1)", {"needle": "x"}, MagicMock(sqlstate="57014")),
            DeadlineReached(remaining_ms=0),
        ],
        ids=["statement_timeout", "deadline"],
    )
    async def test_a_read_stopped_after_the_source_is_a_timeout(self, stopped: Exception) -> None:
        service = ArtifactService(_session())
        with (
            patch(f"{PATH}.virtual_table_repo.statement_timeout", new=AsyncMock(return_value="0")),
            patch(f"{PATH}.virtual_table_repo.restore_statement_timeout", new=AsyncMock()),
            patch.object(
                artifacts.VirtualTableService, "read_bound", AsyncMock(side_effect=stopped)
            ),
        ):
            read = await service._read_rows(
                _ctx(),
                ArtifactBinding.model_validate(_binding()),
                MagicMock(columns=[], name="t"),
                MagicMock(remaining_ms=lambda: 5),
            )
        assert read == Unavailable("timeout")

    async def test_a_read_with_no_time_left_is_a_timeout(self) -> None:
        read = await ArtifactService(_session())._read_rows(
            _ctx(),
            ArtifactBinding.model_validate(_binding()),
            MagicMock(),
            MagicMock(remaining_ms=lambda: 0),
        )
        assert read == Unavailable("timeout")

    async def test_a_log_read_with_no_time_left_is_a_timeout(self) -> None:
        read = await ArtifactService(_session())._read_log(
            _ctx(),
            WorkflowLogBinding(name="log", workflow_id=uuid.uuid4(), lines=5),
            MagicMock(remaining_ms=lambda: 0),
            rows=True,
        )
        assert read == Unavailable("timeout")

    @pytest.mark.parametrize(
        "stopped",
        [
            DBAPIError("SELECT pg_sleep(1)", {"needle": "x"}, MagicMock(sqlstate="57014")),
            DeadlineReached(remaining_ms=0),
        ],
        ids=["statement_timeout", "deadline"],
    )
    async def test_a_log_read_stopped_is_a_timeout(self, stopped: Exception) -> None:
        with patch(
            f"{PATH}.virtual_table_repo.statement_timeout", new=AsyncMock(side_effect=stopped)
        ):
            read = await ArtifactService(_session())._read_log(
                _ctx(),
                WorkflowLogBinding(name="log", workflow_id=uuid.uuid4(), lines=5),
                MagicMock(remaining_ms=lambda: 5),
                rows=True,
            )
        assert read == Unavailable("timeout")

    async def test_a_log_read_failing_for_another_reason_is_not_swallowed(self) -> None:
        broken = DBAPIError("SELECT 1", {}, MagicMock(sqlstate="40001"))
        with (
            patch(
                f"{PATH}.virtual_table_repo.statement_timeout", new=AsyncMock(side_effect=broken)
            ),
            pytest.raises(DBAPIError),
        ):
            await ArtifactService(_session())._read_log(
                _ctx(),
                WorkflowLogBinding(name="log", workflow_id=uuid.uuid4(), lines=5),
                MagicMock(remaining_ms=lambda: 5),
                rows=True,
            )

    async def test_a_read_that_is_not_a_timeout_is_not_swallowed_after_the_source(self) -> None:
        broken = DBAPIError("SELECT 1", {}, MagicMock(sqlstate="40001"))
        with (
            patch(f"{PATH}.virtual_table_repo.statement_timeout", new=AsyncMock(return_value="0")),
            patch.object(
                artifacts.VirtualTableService, "read_bound", AsyncMock(side_effect=broken)
            ),
            pytest.raises(DBAPIError),
        ):
            await ArtifactService(_session())._read_rows(
                _ctx(),
                ArtifactBinding.model_validate(_binding()),
                MagicMock(columns=[]),
                MagicMock(remaining_ms=lambda: 5),
            )

    async def test_a_read_that_answers_nothing_is_not_kept(self) -> None:
        shared = MagicMock(lookup=MagicMock(return_value=None), admit=AsyncMock(return_value=True))
        service = ArtifactService(_session())
        timeout = Unavailable("timeout")
        with (
            patch.object(service, "_binding_source", AsyncMock(return_value=MagicMock())),
            patch.object(service, "_read_rows", AsyncMock(return_value=timeout)),
        ):
            read = await service._read_shared(
                shared, _ctx(), ArtifactBinding.model_validate(_binding()), MagicMock()
            )
        assert read is timeout
        shared.store.assert_not_called()

    async def test_a_database_error_that_is_not_a_timeout_is_not_swallowed(self) -> None:
        ctx = _ctx()
        artifact = _artifact(ctx)
        version = _version(artifact, bindings=[_binding()])
        broken = DBAPIError("SELECT 1", {}, MagicMock(sqlstate="40001"))
        service = ArtifactService(_session())
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.member_context", new=AsyncMock(return_value=ctx)),
            patch(
                f"{PATH}.virtual_table_repo.statement_timeout",
                new=AsyncMock(side_effect=broken),
            ),
            pytest.raises(DatabaseError),
        ):
            await service.data(ctx, artifact.id, version.id)

    async def _served(
        self,
        viewer: AuthContext,
        artifact: Artifact,
        *,
        owner: AuthContext | None,
        source: Any,
        can_edit: bool = True,
    ) -> tuple[ArtifactData, AsyncMock]:
        """One page load of a one-binding page, its owner's read stubbed at `page_source`."""
        version = _version(artifact, bindings=[_binding()])
        read = AsyncMock(return_value=source)

        async def access(_db: Any, _ctx: Any, _row: Any, perm: Perm, **_kw: Any) -> bool:
            return perm is Perm.ARTIFACTS_VIEW or can_edit

        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.resolve_access", new=access),
            patch(f"{PATH}.member_context", new=AsyncMock(return_value=owner)),
            patch(f"{PATH}.virtual_table_repo.statement_timeout", new=AsyncMock()),
            patch(f"{PATH}.virtual_table_repo.restore_statement_timeout", new=AsyncMock()),
            patch(f"{PATH}.page_source", new=read),
        ):
            data = await ArtifactService(_session()).data(viewer, artifact.id, version.id)
        return data, read

    @pytest.mark.security
    async def test_a_member_who_is_not_the_owner_awaits_consent_and_nothing_is_read(
        self,
    ) -> None:
        """Until the owner consents, a page's data reaches only them and the roles that
        read every table: a Member opening a page shared with them sees it without."""
        owner = _ctx()
        artifact = _artifact(owner)
        member = _ctx(OrgRoleName.MEMBER, org_id=owner.organization_id)

        data, read = await self._served(member, artifact, owner=owner, source=None)

        assert (data.bindings["deals"].status, data.bindings["deals"].reason) == (
            "unavailable",
            "awaiting_consent",
        )
        read.assert_not_awaited()

    @pytest.mark.parametrize(
        "role", [OrgRoleName.ADMIN, OrgRoleName.BUILDER, OrgRoleName.OPERATOR, OrgRoleName.OWNER]
    )
    async def test_a_role_that_reads_every_table_reads_the_owner_s_query(self, role: str) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        viewer = _ctx(role, org_id=owner.organization_id)

        data, read = await self._served(
            viewer, artifact, owner=owner, source=Unavailable("creator_lost_access")
        )

        assert data.bindings["deals"].reason == "creator_lost_access"
        assert read.await_args.args[1] is owner

    @pytest.mark.security
    async def test_an_owner_who_is_no_longer_a_member_backs_no_data(self) -> None:
        admin = _ctx(OrgRoleName.ADMIN)
        artifact = _artifact(admin)
        artifact.owner_user_id = uuid.uuid4()

        data, read = await self._served(admin, artifact, owner=None, source=None)

        assert data.bindings["deals"].reason == "creator_gone"
        read.assert_not_awaited()

    @pytest.mark.security
    async def test_an_owner_who_was_deleted_backs_no_data(self) -> None:
        admin = _ctx(OrgRoleName.ADMIN)
        artifact = _artifact(admin)
        artifact.owner_user_id = None

        data, _read = await self._served(admin, artifact, owner=admin, source=None)

        assert data.bindings["deals"].reason == "creator_gone"

    async def test_an_editor_is_told_what_changed_and_a_reader_is_not(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        changed = Unavailable("source_changed", "Status")

        told, _ = await self._served(owner, artifact, owner=owner, source=changed)
        untold, _ = await self._served(owner, artifact, owner=owner, source=changed, can_edit=False)

        assert (told.bindings["deals"].reason, told.bindings["deals"].changed) == (
            "source_changed",
            "Status",
        )
        assert (untold.bindings["deals"].reason, untold.bindings["deals"].changed) == (None, None)


class TestInjection:
    """What `content` writes into a member's page, branch by branch, with the reads stubbed."""

    def _claims(self, viewer: AuthContext, *, org: uuid.UUID | None = None) -> dict[str, Any]:
        return {"uid": str(viewer.user_id), "org": str(org or viewer.organization_id)}

    async def _run(
        self,
        *,
        claims: dict[str, Any],
        artifact: Artifact,
        version: ArtifactVersion,
        reader: AuthContext | None,
        found: Artifact | type[NotFoundError] | None = None,
        served_version: ArtifactVersion | None = None,
        allowed: bool = True,
        in_flight: bool = False,
        gate_locked: bool = False,
    ) -> dict[str, Any]:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def claim(*_a: Any, **_k: Any) -> Any:
            if in_flight:
                raise RateLimitError(message="held")
            yield

        gate = MagicMock()
        gate.locked.return_value = gate_locked
        gate.__aenter__ = AsyncMock()
        gate.__aexit__ = AsyncMock(return_value=False)
        read = AsyncMock(return_value={"deals": "READ"})
        with (
            patch(f"{PATH}.member_context", new=AsyncMock(return_value=reader)) as lookup,
            patch(
                f"{PATH}.ArtifactService.get",
                new=AsyncMock(side_effect=NotFoundError(message="x"))
                if found is NotFoundError
                else AsyncMock(return_value=artifact),
            ),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{PATH}.served",
                new=AsyncMock(
                    return_value=artifacts.Served(version=served_version, data=True, latest=True)
                ),
            ),
            patch(
                f"{PATH}.rate_limit.consume_with_local_floor",
                new=AsyncMock(return_value=MagicMock(allowed=allowed)),
            ),
            patch(f"{PATH}.rate_limit.one_in_flight", claim),
            patch(f"{PATH}._load_gate", return_value=gate),
            patch(f"{PATH}.ArtifactService._read_page", new=read),
        ):
            result = await _service()._injection(claims, artifact, version)
        self.looked_up = lookup
        self.read = read
        return {name: getattr(value, "reason", value) for name, value in result.items()}

    def _page(self) -> tuple[AuthContext, Artifact, ArtifactVersion]:
        viewer = _ctx()
        artifact = _artifact(viewer)
        return viewer, artifact, _version(artifact, bindings=[_binding()])

    @pytest.mark.security
    async def test_a_token_for_another_organization_reads_nothing_and_looks_nobody_up(self) -> None:
        viewer, artifact, version = self._page()
        result = await self._run(
            claims=self._claims(viewer, org=uuid.uuid4()),
            artifact=artifact,
            version=version,
            reader=viewer,
        )
        assert result == {"deals": None}
        self.looked_up.assert_not_awaited()

    @pytest.mark.security
    async def test_a_token_naming_nobody_reads_nothing(self) -> None:
        viewer, artifact, version = self._page()
        result = await self._run(claims={}, artifact=artifact, version=version, reader=viewer)
        assert result == {"deals": None}
        self.looked_up.assert_not_awaited()

    @pytest.mark.security
    async def test_a_viewer_who_is_no_longer_a_member_reads_nothing(self) -> None:
        viewer, artifact, version = self._page()
        result = await self._run(
            claims=self._claims(viewer), artifact=artifact, version=version, reader=None
        )
        assert result == {"deals": None}
        self.read.assert_not_awaited()

    @pytest.mark.security
    async def test_a_viewer_who_may_no_longer_open_the_page_reads_nothing(self) -> None:
        viewer, artifact, version = self._page()
        result = await self._run(
            claims=self._claims(viewer),
            artifact=artifact,
            version=version,
            reader=viewer,
            found=NotFoundError,
        )
        assert result == {"deals": None}
        self.read.assert_not_awaited()

    @pytest.mark.security
    @pytest.mark.parametrize("served_version", [None, "another"])
    async def test_a_version_they_are_not_served_reads_nothing(
        self, served_version: str | None
    ) -> None:
        viewer, artifact, version = self._page()
        other = _version(artifact, number=9, bindings=[_binding()]) if served_version else None
        result = await self._run(
            claims=self._claims(viewer),
            artifact=artifact,
            version=version,
            reader=viewer,
            served_version=other,
        )
        # Told to an editor, as on the data route.
        assert result == {"deals": "not_current"}
        self.read.assert_not_awaited()

    @pytest.mark.security
    @pytest.mark.parametrize("how", ["limit", "in_flight", "gate"])
    async def test_a_load_over_the_viewer_s_limits_is_busy_and_reads_nothing(
        self, how: str
    ) -> None:
        viewer, artifact, version = self._page()
        result = await self._run(
            claims=self._claims(viewer),
            artifact=artifact,
            version=version,
            reader=viewer,
            served_version=version,
            allowed=how != "limit",
            in_flight=how == "in_flight",
            gate_locked=how == "gate",
        )
        assert result == {"deals": "busy"}
        self.read.assert_not_awaited()

    async def test_a_viewer_who_is_served_the_version_gets_the_read(self) -> None:
        viewer, artifact, version = self._page()
        result = await self._run(
            claims=self._claims(viewer),
            artifact=artifact,
            version=version,
            reader=viewer,
            served_version=version,
        )
        assert result == {"deals": "READ"}
        assert self.read.await_args.kwargs["isolate_failures"] is True
        assert self.read.await_args.kwargs["current"] is True


class TestReadPageFailures:
    async def _read(self, *, isolate: bool) -> dict[str, Any]:
        ctx = _ctx()
        artifact = _artifact(ctx)
        version = _version(artifact, bindings=[_binding()])
        broken = DBAPIError("SELECT 1", {}, MagicMock(sqlstate="40001"))
        with (
            patch(f"{PATH}.member_context", new=AsyncMock(return_value=ctx)),
            patch(f"{PATH}.ArtifactService._read_binding", new=AsyncMock(side_effect=broken)),
        ):
            return await _service()._read_page(
                artifact,
                version,
                artifacts.Served(version=version, data=True, latest=True),
                can_edit=True,
                current=True,
                isolate_failures=isolate,
            )

    async def test_a_failed_read_is_that_binding_unavailable_when_isolated(self) -> None:
        bindings = await self._read(isolate=True)
        assert bindings["deals"].status == "unavailable"
        assert bindings["deals"].reason == "failed"

    async def test_a_failed_read_is_raised_otherwise(self) -> None:
        with pytest.raises(DatabaseError):
            await self._read(isolate=False)

    @pytest.mark.security
    @pytest.mark.parametrize("isolate", [True, False])
    async def test_a_failed_read_never_logs_the_query_s_filter_values(
        self, isolate: bool, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A database error carries its bound parameters - the page query's filter values -
        and the handler for an unhandled one logs it whole: the route raises a domain error
        that holds none of them instead."""
        secret = "ann@example.com-4242"
        broken = DBAPIError("SELECT 1", {"needle": secret}, MagicMock(sqlstate="40001"))
        ctx = _ctx()
        artifact = _artifact(ctx)
        version = _version(artifact, bindings=[_binding()])
        error: DatabaseError | None = None
        with (
            caplog.at_level(logging.DEBUG),
            patch(f"{PATH}.member_context", new=AsyncMock(return_value=ctx)),
            patch(f"{PATH}.ArtifactService._read_binding", new=AsyncMock(side_effect=broken)),
        ):
            try:
                await _service()._read_page(
                    artifact,
                    version,
                    artifacts.Served(version=version, data=True, latest=True),
                    can_edit=True,
                    current=True,
                    isolate_failures=isolate,
                )
            except DatabaseError as raised:
                error = raised
        assert (error is None) is isolate
        if error is not None:
            assert secret not in f"{error.message} {error.details}"
            assert error.__cause__ is None
            assert error.__suppress_context__
        logged = " ".join(
            f"{record.getMessage()} {record.__dict__} {record.exc_text}"
            for record in caplog.records
        )
        assert secret not in logged
        assert [r.sqlstate for r in caplog.records if hasattr(r, "sqlstate")] == ["40001"]


class TestWhoIsToldWhyABindingIsEmpty:
    @pytest.mark.parametrize(
        ("reason", "reader_told"),
        [
            ("awaiting_consent", True),
            ("not_current", True),
            ("creator_gone", False),
            ("source_changed", False),
        ],
    )
    def test_only_a_reason_that_says_nothing_of_the_tables_reaches_a_reader(
        self, reason: Reason, reader_told: bool
    ) -> None:
        reads = {"deals": Unavailable(reason)}
        reader = page_data(reads, max_bytes=1000, can_edit=False)["deals"]
        editor = page_data(reads, max_bytes=1000, can_edit=True)["deals"]
        assert reader.reason == (reason if reader_told else None)
        assert editor.reason == reason


class TestThePagesOwner:
    async def test_a_page_nobody_owns_has_no_owner_to_read_its_data_as(self) -> None:
        artifact = MagicMock(spec=Artifact, owner_user_id=None, organization_id=uuid.uuid4())
        person = AuthContext(
            user_id=uuid.uuid4(), organization_id=artifact.organization_id, role="member"
        )

        with patch(f"{PATH}.member_context", new=AsyncMock()) as lookup:
            assert await artifacts._owner(MagicMock(), artifact, person) is None

        lookup.assert_not_awaited()
