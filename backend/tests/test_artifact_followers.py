"""Following an artifact: who is told about a new version, and who still sees it (#1977)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.artifact import Artifact, ArtifactFollower, ArtifactMediaType, ArtifactVersion
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.resource_grant import Visibility
from app.services import artifact as artifacts
from app.services.notification_center import NotificationCenterService

pytestmark = pytest.mark.anyio

PATH = "app.services.artifact"
CENTER = "app.services.notification_center"


def _artifact(**overrides: Any) -> Artifact:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "owner_user_id": uuid.uuid4(),
        "visibility": Visibility.PRIVATE.value,
        "agent_id": uuid.uuid4(),
        "name": "weekly-report",
        "title": "Weekly report",
        "public_view_count": 0,
        "embed_origins": [],
        "published_at": datetime(2026, 9, 22, tzinfo=UTC),
        "created_at": datetime(2026, 9, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return Artifact(**values)


def _version(artifact: Artifact, *, number: int = 1, sha: str = "0") -> ArtifactVersion:
    return ArtifactVersion(
        id=uuid.uuid4(),
        artifact_id=artifact.id,
        number=number,
        media_type=ArtifactMediaType.HTML.value,
        size_bytes=20,
        sha256=sha * 64,
        storage_path="artifacts/x.html",
        run_id=None,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
    )


async def _apply(_db: object, *, artifact: Artifact, update_data: dict[str, Any]) -> Artifact:
    for key, value in update_data.items():
        setattr(artifact, key, value)
    return artifact


class TestWhoIsTold:
    async def test_followers_who_can_still_read_it_are_told_and_the_actor_is_not(self) -> None:
        artifact = _artifact()
        actor, reader, other_reader, lost_access = (uuid.uuid4() for _ in range(4))

        async def may(_db: object, _artifact: Artifact, user_id: uuid.UUID, perm: Perm) -> bool:
            assert perm is Perm.ARTIFACTS_VIEW
            return user_id != lost_access

        told = AsyncMock()
        with (
            patch(
                f"{PATH}.artifact_repo.follower_ids",
                new=AsyncMock(return_value=[reader, actor, lost_access, other_reader]),
            ),
            patch(f"{PATH}._may", new=may),
            patch(f"{PATH}.NotificationService.artifact_version_published", new=told),
        ):
            await artifacts._notify_followers(
                MagicMock(), artifact, _version(artifact, number=4), actor_user_id=actor
            )

        kwargs = told.await_args.kwargs
        assert kwargs["recipients"] == [reader, other_reader]
        assert kwargs["version_number"] == 4
        assert kwargs["artifact_id"] == artifact.id
        assert kwargs["organization_id"] == artifact.organization_id

    async def test_the_notice_is_one_per_version_and_links_the_page(self) -> None:
        artifact = _artifact()
        recipient = uuid.uuid4()
        write = AsyncMock()
        with patch(f"{CENTER}.NotificationCenterService.write", new=write):
            from app.services.notifications import NotificationService

            await NotificationService(MagicMock()).artifact_version_published(
                recipients=[recipient],
                organization_id=artifact.organization_id,
                artifact_id=artifact.id,
                title="Weekly report",
                version_number=7,
                actor_user_id=None,
            )

        kwargs = write.await_args.kwargs
        assert kwargs["event_type"] is NotificationEventType.ARTIFACT_VERSION_PUBLISHED
        assert kwargs["occurrence_id"] == f"{artifact.id}:7"
        assert kwargs["context_url"].startswith(f"/artifacts/{artifact.id}")
        assert kwargs["render_context"]["artifact_id"] == str(artifact.id)
        assert "v7" in kwargs["summary"]

    async def test_nobody_to_tell_writes_nothing(self) -> None:
        write = AsyncMock()
        with patch(f"{CENTER}.NotificationCenterService.write", new=write):
            from app.services.notifications import NotificationService

            await NotificationService(MagicMock()).artifact_version_published(
                recipients=[],
                organization_id=uuid.uuid4(),
                artifact_id=uuid.uuid4(),
                title="Weekly report",
                version_number=1,
                actor_user_id=None,
            )

        write.assert_not_called()


class TestWhatIsANewVersion:
    async def _publish(
        self, artifact: Artifact, *, latest: ArtifactVersion, data: bytes
    ) -> AsyncMock:
        storage = MagicMock()
        storage.save_at = AsyncMock()
        told = AsyncMock()
        with (
            patch(f"{PATH}._environment_of_run", new=AsyncMock(return_value=None)),
            patch(f"{PATH}._locked_artifact", new=AsyncMock(return_value=(artifact, False))),
            patch(f"{PATH}._may", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=latest)),
            patch(f"{PATH}.artifact_repo.update", new=_apply),
            patch(
                f"{PATH}.artifact_repo.create_version",
                new=AsyncMock(
                    side_effect=lambda _db, **kw: _version(artifact, number=kw["number"])
                ),
            ),
            patch(f"{PATH}._prune", new=AsyncMock()),
            patch(f"{PATH}.record_audit", new=AsyncMock()),
            patch(f"{PATH}.get_file_storage", return_value=storage),
            patch(f"{PATH}.artifact_repo.follower_ids", new=AsyncMock(return_value=[uuid.uuid4()])),
            patch(f"{PATH}.NotificationService.artifact_version_published", new=told),
        ):
            await artifacts.publish_with(
                MagicMock(),
                organization_id=artifact.organization_id,
                agent_id=artifact.agent_id or uuid.uuid4(),
                owner_user_id=artifact.owner_user_id,
                run_id=uuid.uuid4(),
                name=artifact.name,
                title=None,
                media_type=ArtifactMediaType.HTML,
                data=data,
            )
        return told

    async def test_a_republish_with_new_bytes_tells_the_followers(self) -> None:
        artifact = _artifact()
        told = await self._publish(artifact, latest=_version(artifact), data=b"<p>new</p>")

        told.assert_awaited_once()
        assert told.await_args.kwargs["version_number"] == 2

    async def test_an_unchanged_republish_tells_nobody(self) -> None:
        """A schedule that found nothing new republishes the same page; that is not
        a version anybody needs to hear about."""
        import hashlib

        artifact = _artifact()
        data = b"<p>same</p>"
        latest = _version(artifact)
        latest.sha256 = hashlib.sha256(data).hexdigest()

        told = await self._publish(artifact, latest=latest, data=data)

        told.assert_not_called()


def _notice(artifact_id: object) -> Notification:
    return Notification(
        id=uuid.uuid4(),
        recipient_user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        event_type=NotificationEventType.ARTIFACT_VERSION_PUBLISHED.value,
        occurrence_id="x",
        summary="'Weekly report' has a new version (v2).",
        render_context={"artifact_id": artifact_id},
    )


class TestTheInboxChecksAgain:
    """Following grants nothing: the notice is the page's title and link, so a
    reader who can no longer open the page no longer sees it."""

    def _ctx(self) -> AuthContext:
        return AuthContext(
            user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.MEMBER
        )

    async def _visible(
        self, notice: Notification, *, artifact: Artifact | None, readable: bool
    ) -> bool:
        with (
            patch(f"{CENTER}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{CENTER}.resolve_access", new=AsyncMock(return_value=readable)),
        ):
            gate = await NotificationCenterService(MagicMock()).gate_for(self._ctx(), notice)
        return gate.visible

    async def test_a_reader_who_still_has_access_sees_it(self) -> None:
        artifact = _artifact()
        assert await self._visible(_notice(str(artifact.id)), artifact=artifact, readable=True)

    @pytest.mark.security
    async def test_a_reader_who_lost_access_does_not(self) -> None:
        artifact = _artifact()
        assert not await self._visible(_notice(str(artifact.id)), artifact=artifact, readable=False)

    async def test_a_deleted_page_takes_its_notices_with_it(self) -> None:
        assert not await self._visible(_notice(str(uuid.uuid4())), artifact=None, readable=True)

    async def test_a_malformed_artifact_id_hides_the_row(self) -> None:
        assert not await self._visible(_notice("not-a-uuid"), artifact=None, readable=True)


def test_a_follower_row_names_the_page_and_the_person() -> None:
    artifact_id, user_id = uuid.uuid4(), uuid.uuid4()

    shown = repr(ArtifactFollower(artifact_id=artifact_id, user_id=user_id))

    assert str(artifact_id) in shown and str(user_id) in shown
