"""A queued candidate retains binary identity and inert frontmatter on resume."""

import hashlib
import json

import pytest
from pydantic import ValidationError

from app.agents.capabilities.skills import SkillBodyFile
from app.db.models.skill_check import SkillCheck
from app.services.skill_check import Candidate, _candidate_of, _resources_json


def test_text_candidate_hash_remains_compatible_with_existing_stored_checks() -> None:
    candidate = Candidate(
        "Description", "Instructions", (SkillBodyFile("references/a.txt", None, "exact\n"),)
    )
    previous = {
        "description": "Description",
        "content": "Instructions",
        "resources": [["references/a.txt", None, "exact\n"]],
    }
    expected = hashlib.sha256(
        json.dumps(previous, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert candidate.digest() == expected
    assert (
        Candidate("Description", "Instructions", candidate.resources, manifest_metadata={}).digest()
        == expected
    )


def test_resume_restores_binary_encoding_and_metadata_in_hash_and_runtime_override() -> None:
    files = (
        SkillBodyFile(name="assets/a.pdf", description=None, content="AP+A", encoding="base64"),
    )
    candidate = Candidate(
        "Description",
        "Instructions",
        files,
        manifest_metadata={"license": "MIT", "allowed-tools": ["execute"]},
    )
    stored = SkillCheck(
        candidate_description=candidate.description,
        candidate_content=candidate.content,
        candidate_resources=_resources_json(files),
        candidate_manifest_metadata=candidate.manifest_metadata,
    )
    resumed = _candidate_of(stored)
    assert resumed.digest() == candidate.digest()
    assert resumed.resources == files
    assert resumed.body().manifest_metadata == candidate.manifest_metadata
    assert (
        Candidate(
            "Description", "Instructions", files, manifest_metadata={"license": "Apache-2.0"}
        ).digest()
        != candidate.digest()
    )
    assert (
        Candidate(
            "Description",
            "Instructions",
            (SkillBodyFile("assets/a.pdf", None, "AP+A"),),
            manifest_metadata=candidate.manifest_metadata,
        ).digest()
        != candidate.digest()
    )


def test_portable_legacy_text_shape_stays_unchanged_and_binary_is_explicit() -> None:
    from app.services.portability.content import SkillContent, SkillFileContent

    text = SkillContent(
        name="template",
        description="Description",
        content="Instructions",
        files=(SkillFileContent(name="refs/a.txt", content="  exact\n"),),
    )
    assert text.model_dump(mode="json") == {
        "name": "template",
        "description": "Description",
        "content": "Instructions",
        "category": None,
        "files": [{"name": "refs/a.txt", "description": None, "content": "  exact\n"}],
    }
    binary = SkillContent(
        name="template",
        description="Description",
        content="Instructions",
        manifest_metadata={"license": "MIT"},
        files=(SkillFileContent(name="a.pdf", content="AP+A", encoding="base64"),),
    )
    dumped = binary.model_dump(mode="json")
    assert dumped["manifest_metadata"] == {"license": "MIT"}
    assert dumped["files"][0]["encoding"] == "base64"
    assert SkillContent.model_validate(dumped).files[0].content == "AP+A"


def test_instruction_whitespace_survives_edit_check_and_read_boundaries() -> None:
    from uuid import uuid4

    from app.schemas.skill import SkillCreate, SkillRead, SkillUpdate
    from app.schemas.skill_check import CandidateText, SkillCheckRequest
    from app.schemas.skill_version import SkillVersionCreate

    body = "\n    meaningful code indentation\n\n"
    assert SkillCreate(name="template", description="Description", content=body).content == body
    assert SkillUpdate(content=body).content == body
    assert CandidateText(description="Description", content=body).content == body
    checked = SkillCheckRequest(
        base_version_id=uuid4(), candidate=CandidateText(description="Description", content=body)
    )
    assert checked.candidate is not None and checked.candidate.content == body
    assert (
        SkillVersionCreate(base_version_id=uuid4(), description="Description", content=body).content
        == body
    )
    assert (
        SkillRead(
            id=uuid4(),
            name="template",
            description="Description",
            content=body,
            version=1,
            latest_version_id=uuid4(),
            visibility="private",
        ).content
        == body
    )


@pytest.mark.security
def test_preserving_markdown_does_not_allow_bidi_candidate_instructions() -> None:
    from uuid import uuid4

    from app.schemas.skill_check import CandidateText, SkillCheckRequest

    with pytest.raises(ValidationError):
        SkillCheckRequest(
            base_version_id=uuid4(),
            candidate=CandidateText(description="Description", content="    visible\u202ehidden\n"),
        )


def test_legacy_queued_check_does_not_inherit_new_live_frontmatter() -> None:
    from app.db.models.skill import Skill
    from app.services.skill_library import split_frontmatter
    from app.services.skill_workspace import render_body

    row = SkillCheck(
        candidate_description="Description",
        candidate_content="Old instructions",
        candidate_resources=None,
        candidate_manifest_metadata=None,
    )
    resumed = _candidate_of(row)
    assert resumed.manifest_metadata == {}
    live = Skill(
        name="template",
        description="New description",
        content="New instructions",
        manifest_metadata={"license": "new-license", "allowed-tools": ["execute"]},
        resources=[],
    )
    metadata, body = split_frontmatter(render_body(live, resumed.body()))
    assert metadata == {"name": "template", "description": "Description"}
    assert body.strip() == "Old instructions"


@pytest.mark.anyio
async def test_empty_served_snapshot_does_not_inherit_later_live_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.models.skill_version import SkillVersion
    from app.services.skill_check import SkillCheckService

    service = SkillCheckService(MagicMock(spec=AsyncSession))
    monkeypatch.setattr(service.versions, "files_of", AsyncMock(return_value={}))
    assert (
        await service._served(Candidate("Description", "Instructions"), SkillVersion(resources={}))
        == ()
    )
    row = SkillCheck(
        candidate_description="Description",
        candidate_content="Instructions",
        candidate_resources={},
        candidate_manifest_metadata={},
    )
    body = await service._stage_body(row)
    assert body.resources == ()


@pytest.mark.anyio
async def test_legacy_snapshot_without_its_authorized_base_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, MagicMock
    from uuid import uuid4

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.exceptions import NotFoundError
    from app.repositories import skill_version_repo
    from app.services.skill_check import SkillCheckService

    service = SkillCheckService(MagicMock(spec=AsyncSession))
    get = AsyncMock(return_value=None)
    monkeypatch.setattr(skill_version_repo, "get_version", get)
    row = SkillCheck(
        organization_id=uuid4(),
        skill_id=uuid4(),
        base_version_id=uuid4(),
        candidate_description="Description",
        candidate_content="Instructions",
        candidate_resources=None,
        candidate_hash="unchanged",
    )
    with pytest.raises(NotFoundError, match="immutable base"):
        await service._stage_body(row)
    get.assert_awaited_once_with(
        service.db, row.base_version_id, organization_id=row.organization_id, skill_id=row.skill_id
    )
    assert row.candidate_resources is None
    assert row.candidate_hash == "unchanged"
