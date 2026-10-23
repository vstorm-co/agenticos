"""What `preview_artifact` is handed by the service: the page as served, and data read as whom.

The repository edge is stubbed; `tests/integration/test_artifact_listing.py`
proves the listing's rows and `tests/test_artifact_render.py` what the renderer
does with what is decided here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import DatabaseError, NotFoundError, RateLimitError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.artifact import Artifact, ArtifactMediaType, ArtifactVersion
from app.schemas.artifact import ArtifactData, BindingData
from app.services import artifact as artifacts

pytestmark = pytest.mark.anyio

PATH = "app.services.artifact"
PAGE = b"<!doctype html><p>Hi</p>"


def _artifact() -> Artifact:
    return Artifact(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        name="weekly-report",
        title="Weekly report",
        visibility="private",
    )


def _version(artifact: Artifact, *, bound: bool = True) -> ArtifactVersion:
    return ArtifactVersion(
        id=uuid.uuid4(),
        artifact_id=artifact.id,
        number=3,
        media_type=ArtifactMediaType.HTML.value,
        bindings=[{"name": "tickets", "table_id": str(uuid.uuid4()), "fields": {}}]
        if bound
        else [],
    )


def _opened(db: MagicMock) -> MagicMock:
    opened = MagicMock()
    opened.__aenter__ = AsyncMock(return_value=db)
    opened.__aexit__ = AsyncMock(return_value=None)
    return opened


def _read(binding: BindingData) -> ArtifactData:
    return ArtifactData(bindings={"tickets": binding}, current=True, read_at=datetime.now(UTC))


_OK = BindingData(status="ok", truncated=False, count=0, fields={}, records=[])


async def _preview(
    version_bound: bool = True,
    *,
    room: bool = False,
    person: AuthContext | None = None,
    data: ArtifactData | Exception | None = None,
    has_person: bool = True,
    limiter: AsyncMock | None = None,
) -> tuple[artifacts.ArtifactPreview, AsyncMock, AsyncMock]:
    artifact = _artifact()
    version = _version(artifact, bound=version_bound)
    member = AsyncMock(return_value=person)
    reads = AsyncMock(side_effect=data if isinstance(data, Exception) else None, return_value=data)
    with (
        patch(f"{PATH}.get_db_context", return_value=_opened(MagicMock())),
        patch(f"{PATH}._open_current", new=AsyncMock(return_value=(artifact, version, PAGE))),
        patch(f"{PATH}.member_context", new=member),
        patch.object(artifacts.ArtifactService, "data", new=reads),
        patch(
            f"{PATH}.rate_limit.consume_with_local_floor",
            new=limiter or AsyncMock(return_value=MagicMock(allowed=True)),
        ),
    ):
        preview = await artifacts.preview_source(
            organization_id=artifact.organization_id,
            agent_id=uuid.uuid4(),
            reader_user_id=uuid.uuid4(),
            run_id=None,
            name="weekly-report",
            room=room,
            has_person=has_person,
        )
    return preview, member, reads


def _person() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.MEMBER)


class TestThePageAsServed:
    async def test_it_is_the_document_a_frame_gets_and_says_how_many_lines_were_added(
        self,
    ) -> None:
        preview, _, _ = await _preview(version_bound=False)
        assert preview.source == PAGE
        assert preview.document.endswith(b"<p>Hi</p>")
        assert b'data-agenticos="data"' in preview.document
        assert preview.nonce.encode() in preview.document
        head = preview.document[: preview.document.index(b"<p>Hi</p>")].decode()
        assert preview.injected_lines == head.count("\n")
        assert (preview.version_number, preview.media_type) == (3, ArtifactMediaType.HTML)

    async def test_a_page_with_no_bindings_is_posted_nothing(self) -> None:
        preview, member, _ = await _preview(version_bound=False)
        assert (preview.bindings, preview.data_note, preview.binding_names) == (None, None, [])
        member.assert_not_awaited()


@pytest.mark.security
class TestWhoseDataItIs:
    async def test_the_data_is_read_as_the_run_s_person(self) -> None:
        person = _person()
        preview, member, reads = await _preview(person=person, data=_read(_OK))
        assert reads.await_args is not None
        assert reads.await_args.args[0] is person
        assert member.await_args is not None
        assert preview.bindings == {"tickets": _OK}
        assert preview.binding_names == ["tickets"]
        assert preview.data_note is None

    async def test_in_a_group_chat_the_page_gets_no_data_at_all(self) -> None:
        preview, member, reads = await _preview(room=True, person=_person())
        assert preview.bindings == {}
        assert preview.data_note is not None
        assert "group chat" in preview.data_note
        member.assert_not_awaited()
        reads.assert_not_awaited()

    async def test_a_run_nobody_answers_for_gets_no_data_even_for_a_member_reader(self) -> None:
        """A run an outsider supplied the input of executes as a principal, not for a person:
        the page's rows - read as its owner - must not reach what the outsider may read back."""
        preview, member, reads = await _preview(has_person=False, person=_person(), data=_read(_OK))
        assert preview.bindings == {}
        assert preview.data_note is not None
        assert "Nobody this run is for" in preview.data_note
        assert preview.binding_names == ["tickets"]
        member.assert_not_awaited()
        reads.assert_not_awaited()

    async def test_a_read_counts_against_the_members_data_allowance(self) -> None:
        person = _person()
        limiter = AsyncMock(return_value=MagicMock(allowed=True))
        await _preview(person=person, data=_read(_OK), limiter=limiter)
        assert limiter.await_args is not None
        assert limiter.await_args.kwargs["surface"] == "artifact_data"
        assert limiter.await_args.kwargs["caller"] == (
            f"org:{person.organization_id}:user:{person.subject_id}"
        )

    async def test_a_member_over_the_allowance_is_drawn_without_data_and_nothing_is_read(
        self,
    ) -> None:
        limiter = AsyncMock(return_value=MagicMock(allowed=False))
        preview, _, reads = await _preview(person=_person(), data=_read(_OK), limiter=limiter)
        assert preview.bindings == {}
        assert preview.data_note is not None
        assert "too many data loads" in preview.data_note
        reads.assert_not_awaited()

    async def test_a_reader_who_is_no_longer_a_member_reads_nothing(self) -> None:
        preview, _, reads = await _preview(person=None)
        assert preview.bindings == {}
        assert preview.data_note is not None
        assert "may read" in preview.data_note
        reads.assert_not_awaited()

    @pytest.mark.parametrize(
        "refused",
        [
            RateLimitError(message="Your previous data load is still running."),
            NotFoundError(),
            DatabaseError(message="A binding's data could not be read"),
        ],
    )
    async def test_a_refused_load_is_drawn_without_data_and_says_why(
        self, refused: RateLimitError | NotFoundError | DatabaseError
    ) -> None:
        preview, _, _ = await _preview(person=_person(), data=refused)
        assert preview.bindings == {}
        assert preview.data_note is not None
        assert refused.message in preview.data_note


class TestListingFromARun:
    async def test_it_opens_a_session_of_its_own(self) -> None:
        db = MagicMock()
        listing = artifacts.ArtifactListing(items=[], total=0)
        with (
            patch(f"{PATH}.get_db_context", return_value=_opened(db)),
            patch(f"{PATH}.list_for_run_with", new=AsyncMock(return_value=listing)) as inner,
        ):
            got = await artifacts.list_for_run(
                organization_id=uuid.uuid4(),
                agent_id=uuid.uuid4(),
                reader_user_id=uuid.uuid4(),
                editor_user_id=None,
                run_id=None,
                room=True,
            )
        assert got is listing
        assert inner.await_args is not None
        assert inner.await_args.args == (db,)
        assert inner.await_args.kwargs["room"] is True
        assert inner.await_args.kwargs["limit"] == artifacts.LIST_LIMIT


def test_a_content_address_is_on_the_content_origin() -> None:
    assert artifacts.content_address("lib/x.js").endswith("/api/v1/artifact-content/lib/x.js")
