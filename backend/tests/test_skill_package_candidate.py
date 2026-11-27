"""A queued candidate retains binary identity and inert frontmatter on resume."""

import hashlib
import json

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
    from app.schemas.skill_check import CandidateText
    from app.schemas.skill_version import SkillVersionCreate

    body = "\n    meaningful code indentation\n\n"
    assert SkillCreate(name="template", description="Description", content=body).content == body
    assert SkillUpdate(content=body).content == body
    assert CandidateText(description="Description", content=body).content == body
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
