"""What an artifact page gained in #1965-#1973, decided by the service.

The environment a run publishes into, restoring a kept version, the public
link's settings, the embed document, the library set, reading a page back, and
the platform script that turns a link into a question. The database is stubbed
at the repository edge; `tests/integration/test_artifacts.py` proves the rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.core.security import create_artifact_view_token, get_password_hash
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.artifact import Artifact, ArtifactMediaType, ArtifactVersion
from app.db.models.resource_grant import Visibility
from app.schemas.artifact import ArtifactPublicLinkUpdate
from app.services import artifact as artifacts
from app.services.artifact import ArtifactService

pytestmark = pytest.mark.anyio

PATH = "app.services.artifact"


def _ctx(role: str = OrgRoleName.OWNER) -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)


def _artifact(ctx: AuthContext, **overrides: Any) -> Artifact:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "organization_id": ctx.organization_id,
        "owner_user_id": ctx.user_id,
        "visibility": Visibility.PRIVATE.value,
        "agent_id": uuid.uuid4(),
        "environment_id": None,
        "name": "weekly-report",
        "title": "Weekly report",
        "public_key": None,
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
        size_bytes=12,
        sha256=sha * 64,
        storage_path=f"artifacts/{artifact.organization_id}/{artifact.id}/{sha * 64}.html",
        run_id=None,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
    )


def _service() -> ArtifactService:
    return ArtifactService(MagicMock())


async def _apply(_db: object, *, artifact: Artifact, update_data: dict[str, Any]) -> Artifact:
    for key, value in update_data.items():
        setattr(artifact, key, value)
    return artifact


class TestTheEnvironmentOfARun:
    async def _environment_of(
        self, run: Any, environment: AgentEnvironment | None, agent_id: uuid.UUID
    ) -> uuid.UUID | None:
        with (
            patch(f"{PATH}.agent_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{PATH}.agent_environment_repo.get", new=AsyncMock(return_value=environment)),
        ):
            return await artifacts._environment_of_run(
                MagicMock(), run_id=uuid.uuid4(), organization_id=uuid.uuid4(), agent_id=agent_id
            )

    def _environment(self, agent_id: uuid.UUID, *, is_default: bool) -> AgentEnvironment:
        return AgentEnvironment(
            id=uuid.uuid4(), agent_id=agent_id, name="staging", is_default=is_default
        )

    async def test_no_run_is_the_default_environment(self) -> None:
        assert (
            await artifacts._environment_of_run(
                MagicMock(), run_id=None, organization_id=uuid.uuid4(), agent_id=uuid.uuid4()
            )
            is None
        )

    async def test_a_run_that_is_gone_or_named_no_environment_is_the_default(self) -> None:
        agent_id = uuid.uuid4()
        assert await self._environment_of(None, None, agent_id) is None
        assert await self._environment_of(MagicMock(environment_id=None), None, agent_id) is None

    async def test_a_run_in_a_named_environment_publishes_into_it(self) -> None:
        agent_id = uuid.uuid4()
        environment = self._environment(agent_id, is_default=False)
        run = MagicMock(environment_id=environment.id)
        assert await self._environment_of(run, environment, agent_id) == environment.id

    async def test_the_default_environment_named_explicitly_is_still_the_default_slot(
        self,
    ) -> None:
        agent_id = uuid.uuid4()
        environment = self._environment(agent_id, is_default=True)
        run = MagicMock(environment_id=environment.id)
        assert await self._environment_of(run, environment, agent_id) is None

    @pytest.mark.security
    async def test_an_environment_of_another_agent_or_one_deleted_is_not_used(self) -> None:
        agent_id = uuid.uuid4()
        foreign = self._environment(uuid.uuid4(), is_default=False)
        assert (
            await self._environment_of(MagicMock(environment_id=foreign.id), foreign, agent_id)
            is None
        )
        assert (
            await self._environment_of(MagicMock(environment_id=foreign.id), None, agent_id) is None
        )


class TestPublishingWithAnEnvironmentAndATitle:
    async def _publish(
        self,
        artifact: Artifact,
        *,
        created: bool,
        latest: ArtifactVersion | None,
        title: str | None,
        expected_version: int | None = None,
        data: bytes = b"<p>new</p>",
    ) -> tuple[Any, AsyncMock, AsyncMock]:
        storage = MagicMock()
        storage.save_at = AsyncMock()
        with (
            patch(f"{PATH}._environment_of_run", new=AsyncMock(return_value=None)) as environment,
            patch(
                f"{PATH}._locked_artifact", new=AsyncMock(return_value=(artifact, created))
            ) as locked,
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
        ):
            result = await artifacts.publish_with(
                MagicMock(),
                organization_id=artifact.organization_id,
                agent_id=artifact.agent_id or uuid.uuid4(),
                owner_user_id=artifact.owner_user_id,
                run_id=uuid.uuid4(),
                name=artifact.name,
                title=title,
                media_type=ArtifactMediaType.HTML,
                data=data,
                expected_version=expected_version,
            )
        return result, environment, locked

    async def test_a_new_page_without_a_title_is_titled_with_its_name(self) -> None:
        artifact = _artifact(_ctx())
        _result, environment, locked = await self._publish(
            artifact, created=True, latest=None, title=None
        )
        assert locked.await_args.kwargs["title"] == "weekly-report"
        assert locked.await_args.kwargs["environment_id"] is None
        environment.assert_awaited_once()

    async def test_a_republish_without_a_title_keeps_the_one_it_had(self) -> None:
        artifact = _artifact(_ctx(), title="Kept")
        result, _environment, _locked = await self._publish(
            artifact, created=False, latest=_version(artifact), title=None
        )
        assert result.title == "Kept"
        assert result.version_number == 2

    async def test_an_unchanged_republish_without_a_title_keeps_it_too(self) -> None:
        artifact = _artifact(_ctx(), title="Kept")
        latest = _version(artifact)
        latest.sha256 = artifacts.hashlib.sha256(b"<p>same</p>").hexdigest()
        result, _environment, _locked = await self._publish(
            artifact, created=False, latest=latest, title=None, data=b"<p>same</p>"
        )
        assert (result.unchanged, result.title) == (True, "Kept")

    async def test_an_edit_made_against_an_older_version_is_refused(self) -> None:
        artifact = _artifact(_ctx())
        with pytest.raises(ConcurrentChangeError, match="read_artifact"):
            await self._publish(
                artifact,
                created=False,
                latest=_version(artifact, number=4),
                title=None,
                expected_version=3,
            )

    async def test_an_edit_of_a_page_with_no_version_left_is_refused(self) -> None:
        artifact = _artifact(_ctx())
        with pytest.raises(ConcurrentChangeError):
            await self._publish(
                artifact, created=False, latest=None, title=None, expected_version=1
            )

    async def test_an_edit_against_the_current_version_is_published(self) -> None:
        artifact = _artifact(_ctx())
        result, _environment, _locked = await self._publish(
            artifact,
            created=False,
            latest=_version(artifact, number=3),
            title="T",
            expected_version=3,
        )
        assert result.version_number == 4


class TestMay:
    async def test_the_owner_may(self) -> None:
        ctx = _ctx()
        assert await artifacts._may(MagicMock(), _artifact(ctx), ctx.user_id, Perm.ARTIFACTS_VIEW)

    @pytest.mark.security
    async def test_nobody_reaches_somebody_s_page(self) -> None:
        assert not await artifacts._may(MagicMock(), _artifact(_ctx()), None, Perm.ARTIFACTS_VIEW)

    @pytest.mark.security
    async def test_a_departed_member_reaches_nothing(self) -> None:
        with patch(f"{PATH}.member_repo.get_active", new=AsyncMock(return_value=None)):
            assert not await artifacts._may(
                MagicMock(), _artifact(_ctx()), uuid.uuid4(), Perm.ARTIFACTS_VIEW
            )

    @pytest.mark.security
    async def test_a_member_is_decided_by_resolve_access_with_the_permission_asked(self) -> None:
        with (
            patch(
                f"{PATH}.member_repo.get_active",
                new=AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER)),
            ),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)) as access,
        ):
            assert await artifacts._may(
                MagicMock(), _artifact(_ctx()), uuid.uuid4(), Perm.ARTIFACTS_VIEW
            )
        assert access.await_args.args[3] is Perm.ARTIFACTS_VIEW


def _opened(db: MagicMock) -> MagicMock:
    opened = MagicMock()
    opened.__aenter__ = AsyncMock(return_value=db)
    opened.__aexit__ = AsyncMock(return_value=None)
    return opened


class TestReadingAPageBack:
    async def _read(
        self,
        artifact: Artifact | None,
        *,
        may: bool = True,
        version: ArtifactVersion | None = None,
        stored: bytes | Exception = "<h1>Café</h1>".encode(),
    ) -> artifacts.ArtifactSource:
        storage = MagicMock()
        storage.load = AsyncMock(
            side_effect=stored if isinstance(stored, Exception) else None, return_value=stored
        )
        with (
            patch(f"{PATH}.get_db_context", return_value=_opened(MagicMock())),
            patch(f"{PATH}._environment_of_run", new=AsyncMock(return_value=None)),
            patch(
                f"{PATH}.artifact_repo.get_by_identity", new=AsyncMock(return_value=artifact)
            ) as identity,
            patch(f"{PATH}._may", new=AsyncMock(return_value=may)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=version)),
            patch(f"{PATH}.get_file_storage", return_value=storage),
        ):
            source = await artifacts.read_source(
                organization_id=uuid.uuid4(),
                agent_id=uuid.uuid4(),
                reader_user_id=uuid.uuid4(),
                run_id=uuid.uuid4(),
                name="weekly-report",
            )
        assert identity.await_args.kwargs["environment_id"] is None
        return source

    async def test_a_page_is_read_as_it_was_written(self) -> None:
        artifact = _artifact(_ctx())
        source = await self._read(artifact, version=_version(artifact, number=5))
        assert (source.version_number, source.text) == (5, "<h1>Café</h1>")
        assert source.media_type is ArtifactMediaType.HTML

    async def test_a_page_whose_bytes_are_gone_says_so_instead_of_crashing_the_tool(
        self,
    ) -> None:
        artifact = _artifact(_ctx())
        with pytest.raises(NotFoundError, match="lost its content; publish it again"):
            await self._read(artifact, version=_version(artifact), stored=FileNotFoundError("gone"))

    async def test_a_page_that_does_not_exist_is_not_found(self) -> None:
        with pytest.raises(NotFoundError, match="weekly-report"):
            await self._read(None)

    @pytest.mark.security
    async def test_a_page_the_person_may_not_open_is_not_found_in_the_same_words(self) -> None:
        artifact = _artifact(_ctx())
        with pytest.raises(NotFoundError, match="that this run may open"):
            await self._read(artifact, may=False, version=_version(artifact))


class TestRestore:
    async def _restore(
        self,
        artifact: Artifact,
        source: ArtifactVersion | None,
        latest: ArtifactVersion | None,
        *,
        stored: bool = True,
    ) -> tuple[AsyncMock, AsyncMock]:
        ctx = _ctx()
        audit = AsyncMock()
        storage = MagicMock()
        storage.exists = AsyncMock(return_value=stored)
        with (
            patch(f"{PATH}.get_file_storage", return_value=storage),
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)) as access,
            patch(f"{PATH}.artifact_repo.lock", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=source)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=latest)),
            patch(
                f"{PATH}._append_version",
                new=AsyncMock(return_value=_version(artifact, number=9)),
            ) as append,
            patch(f"{PATH}.record_audit", new=audit),
        ):
            await _service().restore_version(ctx, artifact.id, uuid.uuid4())
        assert access.await_args_list[0].args[3] is Perm.ARTIFACTS_EDIT
        return append, audit

    async def test_restoring_adds_a_version_with_the_kept_one_s_bytes(self) -> None:
        artifact = _artifact(_ctx())
        source = _version(artifact, number=2, sha="a")
        append, audit = await self._restore(artifact, source, _version(artifact, number=8))
        assert append.await_args.kwargs["storage_path"] == source.storage_path
        assert append.await_args.kwargs["sha256"] == source.sha256
        assert append.await_args.kwargs["run_id"] is None
        assert audit.await_args.kwargs["action"] == "artifact.version_restored"
        assert audit.await_args.kwargs["details"] == {"version": 9, "restored": 2}

    async def test_restoring_the_current_version_changes_nothing(self) -> None:
        artifact = _artifact(_ctx())
        current = _version(artifact, number=8)
        append, audit = await self._restore(artifact, current, current)
        append.assert_not_awaited()
        audit.assert_not_awaited()

    async def test_a_version_whose_bytes_are_gone_is_not_restored(self) -> None:
        """Restored, it would be a current version that 404s the moment it is opened."""
        artifact = _artifact(_ctx())
        source = _version(artifact, number=2)
        with pytest.raises(NotFoundError, match="gone from storage"):
            await self._restore(artifact, source, _version(artifact, number=8), stored=False)

    async def test_a_version_that_is_not_kept_is_not_found(self) -> None:
        artifact = _artifact(_ctx())
        with pytest.raises(NotFoundError, match="no longer kept"):
            await self._restore(artifact, None, None)


class TestAppendingAVersion:
    async def test_the_next_number_the_publication_time_and_a_prune(self) -> None:
        artifact = _artifact(_ctx())
        with (
            patch(
                f"{PATH}.artifact_repo.create_version",
                new=AsyncMock(return_value=_version(artifact, number=3)),
            ) as create,
            patch(f"{PATH}.artifact_repo.update", new=_apply),
            patch(f"{PATH}._prune", new=AsyncMock()) as prune,
        ):
            await artifacts._append_version(
                MagicMock(),
                artifact,
                _version(artifact, number=2),
                media_type="text/html",
                size_bytes=1,
                sha256="a" * 64,
                storage_path="p",
                run_id=None,
            )
        assert create.await_args.kwargs["number"] == 3
        assert artifact.published_at > datetime(2026, 9, 22, tzinfo=UTC)
        prune.assert_awaited_once()

    async def test_pruning_keeps_the_pinned_version(self) -> None:
        artifact = _artifact(_ctx(), public_version_number=2)
        with patch(
            f"{PATH}.artifact_repo.versions_beyond", new=AsyncMock(return_value=[])
        ) as beyond:
            await artifacts._prune(MagicMock(), artifact)
        assert beyond.await_args.kwargs["pinned"] == 2


class TestPublicLinkSettings:
    async def _update(
        self, artifact: Artifact, data: ArtifactPublicLinkUpdate, *, lock: AsyncMock | None = None
    ) -> AsyncMock:
        audit = AsyncMock()
        with (
            patch(f"{PATH}.artifact_repo.get", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.artifact_repo.lock", new=lock or AsyncMock()),
            patch(
                f"{PATH}.get_file_storage",
                return_value=MagicMock(exists=AsyncMock(return_value=True)),
            ),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.artifact_repo.update", new=_apply),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=None)),
            patch(
                f"{PATH}.artifact_repo.get_version",
                new=AsyncMock(return_value=_version(artifact, number=4)),
            ),
            patch(
                f"{PATH}.artifact_repo.get_version_by_number",
                new=AsyncMock(return_value=_version(artifact, number=4)),
            ),
            patch(f"{PATH}.record_audit", new=audit),
        ):
            detail = await _service().update_public_link(_ctx(), artifact.id, data)
        self.detail = detail
        return audit

    async def test_every_setting_is_stored_and_the_audit_names_fields_not_values(self) -> None:
        artifact = _artifact(_ctx(), public_key="k" * 32)
        expires = datetime.now(UTC) + timedelta(days=14)
        audit = await self._update(
            artifact,
            ArtifactPublicLinkUpdate(
                expires_at=expires,
                pinned_version_id=uuid.uuid4(),
                password="hunter22",
                embed_origins=["https://Intranet.Example.com/", "https://intranet.example.com"],
            ),
        )
        assert artifact.public_expires_at == expires
        assert artifact.public_version_number == 4
        assert artifact.public_password_hash is not None
        assert artifact.public_password_hash != "hunter22"
        assert artifact.embed_origins == ["https://intranet.example.com"]
        assert audit.await_args.kwargs["details"] == {
            "fields": ["embed_origins", "expires_at", "password", "pinned_version_id"]
        }
        assert "hunter22" not in repr(audit.await_args)
        link = self.detail.public_link
        assert link.password_protected is True
        assert link.pinned_version == 4
        assert link.embed_url is not None
        assert link.embed_url.endswith(f"/api/v1/artifact-embed/{'k' * 32}")

    async def test_null_clears_the_expiry_the_pin_and_the_password(self) -> None:
        artifact = _artifact(
            _ctx(),
            public_expires_at=datetime.now(UTC) + timedelta(days=1),
            public_version_number=2,
            public_password_hash="x",
        )
        await self._update(
            artifact,
            ArtifactPublicLinkUpdate(expires_at=None, pinned_version_id=None, password=None),
        )
        assert artifact.public_expires_at is None
        assert artifact.public_version_number is None
        assert artifact.public_password_hash is None
        assert self.detail.public_link.embed_url is None

    async def test_a_null_list_of_sites_is_not_written_to_a_column_that_refuses_it(self) -> None:
        artifact = _artifact(_ctx(), embed_origins=["https://a.example.com"])
        audit = await self._update(artifact, ArtifactPublicLinkUpdate(embed_origins=None))
        assert artifact.embed_origins == ["https://a.example.com"]
        audit.assert_not_awaited()

    async def test_an_expiry_in_the_past_is_refused_naming_the_field(self) -> None:
        with pytest.raises(BadRequestError) as refused:
            await self._update(
                _artifact(_ctx()),
                ArtifactPublicLinkUpdate(expires_at=datetime.now(UTC) - timedelta(minutes=1)),
            )
        assert refused.value.details["fields"][0]["field"] == "expires_at"

    async def test_an_expiry_without_an_offset_is_refused_at_the_door(self) -> None:
        """Naive, it failed the comparison with now() as a 500."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ArtifactPublicLinkUpdate.model_validate({"expires_at": "2030-01-01T00:00:00"})

    async def test_a_pin_is_checked_under_the_lock_a_publish_prunes_under(self) -> None:
        """A publish pruning the version between the check and the write would
        leave the link pinned to one that is gone."""
        artifact = _artifact(_ctx(), public_key="k" * 32)
        order: list[str] = []
        with patch.object(
            artifacts.ArtifactService,
            "_pinned_number",
            new=AsyncMock(side_effect=lambda *_a, **_k: order.append("check") or 4),
        ):
            await self._update(
                artifact,
                ArtifactPublicLinkUpdate(pinned_version_id=uuid.uuid4()),
                lock=AsyncMock(side_effect=lambda *_a, **_k: order.append("lock")),
            )
        assert order == ["lock", "check"]

    async def test_a_pin_to_a_version_whose_bytes_are_gone_is_refused(self) -> None:
        """It would pin the link to a page that 404s."""
        artifact = _artifact(_ctx())
        storage = MagicMock(exists=AsyncMock(return_value=False))
        with (
            patch(
                f"{PATH}.artifact_repo.get_version",
                new=AsyncMock(return_value=_version(artifact, number=2)),
            ),
            patch(f"{PATH}.get_file_storage", return_value=storage),
            pytest.raises(BadRequestError, match="gone from storage") as refused,
        ):
            await _service()._pinned_number(artifact, uuid.uuid4())
        assert refused.value.details["fields"][0]["field"] == "pinned_version_id"

    async def test_a_pin_to_a_version_that_is_not_kept_is_refused(self) -> None:
        artifact = _artifact(_ctx())
        with (
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=None)),
            pytest.raises(BadRequestError) as refused,
        ):
            await _service()._pinned_number(artifact, uuid.uuid4())
        assert refused.value.details["fields"][0]["field"] == "pinned_version_id"


class TestEmbedOrigins:
    @pytest.mark.parametrize(
        ("given", "kept"),
        [
            ("https://intranet.example.com", "https://intranet.example.com"),
            ("  HTTPS://Docs.Example.com/ ", "https://docs.example.com"),
            ("https://*.example.com", "https://*.example.com"),
            ("https://example.com:8443", "https://example.com:8443"),
            ("https://example.com:65535", "https://example.com:65535"),
            ("http://localhost:3000", "http://localhost:3000"),
        ],
    )
    def test_an_origin_is_kept_as_frame_ancestors_names_it(self, given: str, kept: str) -> None:
        assert artifacts.normalise_embed_origins([given]) == [kept]

    @pytest.mark.security
    @pytest.mark.parametrize(
        "given",
        [
            "http://intranet.example.com",
            "https://example.com/path",
            "https://*",
            "*",
            "https://a.*.example.com",
            "javascript:alert(1)",
            "https://exa mple.com",
            "'self'",
            "https://example.com:99999",
            "https://example.com:0",
            "http://localhost:70000",
        ],
    )
    def test_anything_else_is_refused_naming_the_field(self, given: str) -> None:
        with pytest.raises(BadRequestError) as refused:
            artifacts.normalise_embed_origins([given])
        assert refused.value.details["fields"][0]["field"] == "embed_origins"


class TestThePublicLinkOpens:
    def _patches(self, artifact: Artifact | None, *, latest: ArtifactVersion | None = None) -> Any:
        return (
            patch(f"{PATH}.artifact_repo.get_by_public_key", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=latest)),
            patch(f"{PATH}.artifact_repo.count_public_view", new=AsyncMock()),
        )

    @pytest.mark.security
    async def test_an_expired_link_is_not_found(self) -> None:
        artifact = _artifact(
            _ctx(), public_key="k", public_expires_at=datetime.now(UTC) - timedelta(seconds=1)
        )
        first, second, third = self._patches(artifact, latest=_version(artifact))
        with first, second, third, pytest.raises(NotFoundError):
            await _service().public_view("k")

    async def test_a_pinned_link_shows_its_version_and_not_the_newest(self) -> None:
        artifact = _artifact(_ctx(), public_key="k", public_version_number=2)
        pinned = _version(artifact, number=2)
        first, second, third = self._patches(artifact, latest=_version(artifact, number=7))
        with (
            first,
            second,
            third,
            patch(
                f"{PATH}.artifact_repo.get_version_by_number", new=AsyncMock(return_value=pinned)
            ),
        ):
            public = await _service().public_view("k")
        assert public.view is not None
        assert public.view.version.number == 2

    @pytest.mark.security
    async def test_behind_a_password_nothing_is_said_until_it_is_given(self) -> None:
        artifact = _artifact(_ctx(), public_key="k", public_password_hash="hash")
        first, second, third = self._patches(artifact, latest=_version(artifact))
        with first, second, third as counted:
            public = await _service().public_view("k")
        assert public.password_required is True
        assert (public.title, public.published_at, public.view) == (None, None, None)
        counted.assert_not_awaited()

    @pytest.mark.security
    async def test_a_wrong_password_is_refused(self) -> None:
        artifact = _artifact(
            _ctx(), public_key="k", public_password_hash=get_password_hash("right-one")
        )
        first, second, third = self._patches(artifact, latest=_version(artifact))
        with first, second, third as counted, pytest.raises(AuthorizationError):
            await _service().public_view("k", password="wrong-one")
        counted.assert_not_awaited()

    async def test_the_right_password_opens_the_page_and_counts_a_view(self) -> None:
        artifact = _artifact(
            _ctx(), public_key="k", public_password_hash=get_password_hash("right-one")
        )
        first, second, third = self._patches(artifact, latest=_version(artifact))
        with first, second, third as counted:
            public = await _service().public_view("k", password="right-one")
        assert public.title == "Weekly report"
        counted.assert_awaited_once()


class TestTheEmbed:
    async def _embed(self, artifact: Artifact | None) -> tuple[artifacts.EmbedDocument, AsyncMock]:
        counted = AsyncMock()
        latest = _version(artifact) if artifact is not None else None
        with (
            patch(f"{PATH}.artifact_repo.get_by_public_key", new=AsyncMock(return_value=artifact)),
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=latest)),
            patch(f"{PATH}.artifact_repo.count_public_view", new=counted),
        ):
            return await _service().embed("k"), counted

    async def test_a_link_that_opens_nothing_is_a_document_saying_so(self) -> None:
        embed, counted = await self._embed(None)
        assert embed.available is False
        assert b"not available" in embed.document
        assert "frame-ancestors 'none'" in embed.policy
        counted.assert_not_awaited()

    async def test_a_public_page_is_framed_in_a_sandbox_for_its_sites(self) -> None:
        artifact = _artifact(
            _ctx(), public_key="k", title="Q3 <sales>", embed_origins=["https://a.example.com"]
        )
        embed, counted = await self._embed(artifact)
        document = embed.document.decode()
        assert embed.available is True
        assert 'sandbox="allow-scripts allow-modals"' in document
        assert "/artifact-content/" in document
        assert "<title>Q3 &lt;sales&gt;</title>" in document
        assert "frame-ancestors https://a.example.com" in embed.policy
        nonce = embed.policy.split("'nonce-")[1].split("'")[0]
        assert f'<script nonce="{nonce}">' in document
        counted.assert_awaited_once()

    @pytest.mark.security
    async def test_a_page_behind_a_password_is_not_framed_and_says_where_to_open_it(
        self,
    ) -> None:
        artifact = _artifact(
            _ctx(),
            public_key="k",
            public_password_hash="hash",
            embed_origins=["https://a.example.com"],
        )
        artifact.title = "Acme acquisition - board pack"
        embed, counted = await self._embed(artifact)
        document = embed.document.decode()
        assert "<iframe" not in document
        assert "/artifact-content/" not in document
        assert "/a/k" in document
        counted.assert_not_awaited()
        # The embed address answers anyone holding the key, so a title the
        # password was meant to keep must not be in it either.
        assert "Acme" not in document
        assert "<title>Protected page</title>" in document

    @pytest.mark.security
    async def test_the_link_bar_keeps_the_address_it_is_asking_about(self) -> None:
        """While the bar asks about one address, a page posting another must not
        swap what the reader is checking for what they then click."""
        artifact = _artifact(_ctx(), public_key="k", embed_origins=["https://a.example.com"])
        embed, _ = await self._embed(artifact)
        script = embed.document.decode()
        assert script.index("if (!bar.hidden) return;") < script.index("open.href = url.href;")


class TestContentFraming:
    async def _served(self, artifact: Artifact) -> artifacts.ServedArtifact:
        version = _version(artifact)
        storage = MagicMock()
        storage.load = AsyncMock(return_value=b"<p>x</p>")
        token = create_artifact_view_token(version.id, expires_in=timedelta(minutes=5))
        with (
            patch(
                f"{PATH}.artifact_repo.get_version_with_artifact",
                new=AsyncMock(return_value=(version, artifact)),
            ),
            patch(f"{PATH}.get_file_storage", return_value=storage),
        ):
            return await _service().content(token)

    async def test_a_public_page_names_its_embedding_sites(self) -> None:
        artifact = _artifact(_ctx(), public_key="k", embed_origins=["https://a.example.com"])
        assert (await self._served(artifact)).embed_origins == ["https://a.example.com"]

    @pytest.mark.security
    @pytest.mark.parametrize(
        "overrides",
        [{"public_key": None}, {"public_key": "k", "public_password_hash": "hash"}],
        ids=["link-off", "behind-a-password"],
    )
    async def test_a_page_that_cannot_be_embedded_names_none(
        self, overrides: dict[str, Any]
    ) -> None:
        artifact = _artifact(_ctx(), embed_origins=["https://a.example.com"], **overrides)
        assert (await self._served(artifact)).embed_origins == []


class TestTheLibrarySet:
    async def test_every_listed_file_is_shipped_and_served_with_its_type(self) -> None:
        for name, media_type in artifacts.ARTIFACT_LIBRARY.items():
            data, served_type = await artifacts.library_file(name)
            assert data
            assert served_type == media_type

    async def test_a_file_is_read_once(self) -> None:
        artifacts._library_bytes.pop("agenticos-1.css", None)
        with patch(f"{PATH}.asyncio.to_thread", new=AsyncMock(return_value=b"css")) as read:
            await artifacts.library_file("agenticos-1.css")
            await artifacts.library_file("agenticos-1.css")
        read.assert_awaited_once()
        artifacts._library_bytes.pop("agenticos-1.css", None)

    @pytest.mark.security
    @pytest.mark.parametrize("name", ["../../config.py", "README.md", "chart.js"])
    async def test_a_name_that_is_not_in_the_set_is_not_found(self, name: str) -> None:
        with pytest.raises(NotFoundError):
            await artifacts.library_file(name)


class TestThePlatformScript:
    def test_it_goes_right_after_the_doctype_before_the_html_tag(self) -> None:
        # Before <html>, the parser opens the head for it; the page's own <html>
        # attributes still land on that element.
        document = artifacts.with_platform_script(b"<!doctype html><HTML lang=x><Head><title>")
        assert document.startswith(b"<!doctype html><script data-agenticos")
        assert document.endswith(b"</script><HTML lang=x><Head><title>")

    def test_without_a_doctype_it_goes_first(self) -> None:
        document = artifacts.with_platform_script(b"<html lang=en><body>")
        assert document.startswith(b"<script data-agenticos")

    def test_a_doctype_after_a_mark_whitespace_and_comments_is_kept_first(self) -> None:
        # A doctype that is not first is ignored, and the page renders in quirks mode.
        document = artifacts.with_platform_script(
            b"\xef\xbb\xbf\n<!-- built by an agent --><!DOCTYPE html><p>x</p>"
        )
        assert document.startswith(
            b"\xef\xbb\xbf\n<!-- built by an agent --><!DOCTYPE html><script data-agenticos"
        )
        assert document.endswith(b"</script><p>x</p>")

    @pytest.mark.security
    def test_a_tag_inside_a_comment_or_a_script_cannot_move_it(self) -> None:
        """Found by pattern, `<head>` inside a comment took the script into the
        comment, where it never ran and links bypassed the confirmation."""
        page = b"<!doctype html><!-- <head> --><script>var s = '<html>'</script><p>x</p>"
        document = artifacts.with_platform_script(page)
        assert document.startswith(b"<!doctype html><script data-agenticos")
        assert document.endswith(b"</script>" + page[len(b"<!doctype html>") :])

    def test_a_doctype_later_in_the_page_is_not_the_one_it_looks_for(self) -> None:
        document = artifacts.with_platform_script(b"<p>x</p><pre><!doctype html></pre>")
        assert document.startswith(b"<script data-agenticos")

    def test_a_fragment_gets_it_first(self) -> None:
        assert artifacts.with_platform_script(b"<p>x</p>").endswith(b"</script><p>x</p>")

    @pytest.mark.security
    def test_it_asks_the_parent_and_never_opens_anything_itself(self) -> None:
        script = artifacts.PLATFORM_SCRIPT
        assert "agenticos:open-link" in script
        assert "parent.postMessage" in script
        assert "location.assign" not in script
        assert "window.open = function" in script
        assert 'url.protocol === "http:" || url.protocol === "https:"' in script


class TestAgentFilter:
    async def test_the_filter_offers_the_publishers_of_what_the_caller_can_see(self) -> None:
        ctx = _ctx(OrgRoleName.MEMBER)
        agent_id = uuid.uuid4()
        shared = [uuid.uuid4()]
        with (
            patch(f"{PATH}.visible_resource_ids", new=AsyncMock(return_value=shared)),
            patch(
                f"{PATH}.artifact_repo.publishing_agents",
                new=AsyncMock(return_value=[(agent_id, "Reporter")]),
            ) as agents,
        ):
            result = await _service().publishing_agents(ctx)
        assert [(item.id, item.name) for item in result.items] == [(agent_id, "Reporter")]
        assert agents.await_args.kwargs["see_all"] is False
        assert agents.await_args.kwargs["shared_ids"] == shared

    async def test_the_listing_passes_the_agent_and_names_each_environment(self) -> None:
        ctx = _ctx()
        environment_id = uuid.uuid4()
        artifact = _artifact(ctx, environment_id=environment_id)
        agent_id = uuid.uuid4()
        with (
            patch(f"{PATH}.visible_resource_ids", new=AsyncMock(return_value=None)),
            patch(
                f"{PATH}.artifact_repo.list_visible", new=AsyncMock(return_value=([artifact], 1))
            ) as listing,
            patch(f"{PATH}.artifact_repo.latest_versions", new=AsyncMock(return_value={})),
            patch(
                f"{PATH}.artifact_repo.environment_names",
                new=AsyncMock(return_value={environment_id: "staging"}),
            ),
        ):
            result = await _service().list_readable(ctx, agent_id=agent_id)
        assert listing.await_args.kwargs["agent_id"] == agent_id
        assert result.items[0].environment_name == "staging"


class TestTheBundledSkill:
    """`artifact-pages` is how an agent learns the library set exists."""

    def _skill(self) -> Any:
        from app.services import skill_library

        skill = skill_library.get("artifact-pages")
        assert skill is not None
        return skill

    def test_it_ships_with_its_templates_on_the_design_shelf(self) -> None:
        skill = self._skill()
        assert skill.category == "design"
        assert {resource.name for resource in skill.resources} == {
            "templates/dashboard.html",
            "templates/report.html",
        }

    def test_every_library_file_it_names_is_one_the_deployment_serves(self) -> None:
        """A renamed or upgraded library would otherwise leave the skill teaching
        an address that answers 404 - and the page would draw nothing."""
        import re

        skill = self._skill()
        texts = [skill.content, *(resource.content for resource in skill.resources)]
        named = {name for text in texts for name in re.findall(r"lib/([\w.-]+\.(?:js|css))", text)}
        assert named
        assert named <= set(artifacts.ARTIFACT_LIBRARY)

    def test_the_tool_text_names_the_same_set(self) -> None:
        from app.agents.capabilities.artifacts._toolset import build_artifacts_toolset

        tool = build_artifacts_toolset().tools["publish_artifact"]
        for name in artifacts.ARTIFACT_LIBRARY:
            assert f"lib/{name}" in (tool.description or "")
