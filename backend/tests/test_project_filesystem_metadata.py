"""Metadata is locked to one tenant's Project row and never rewrites stored file bytes."""

import errno
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai_backends import FileData
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_workspace import AgentWorkspace
from app.repositories import project_filesystem as repo
from app.schemas.project_filesystem import FsStoredAttributes

pytestmark = pytest.mark.anyio


@pytest.mark.security
async def test_metadata_query_requires_the_workspace_tenant_and_project_scope_under_lock() -> None:
    db = MagicMock(spec=AsyncSession)
    row = AgentWorkspace(
        id=uuid4(), organization_id=uuid4(), scope="project", filesystem_metadata=None
    )
    db.scalar.return_value = row
    loaded, attributes = await repo.metadata(db, row.id, organization_id=row.organization_id)
    assert loaded is row and attributes == {}
    statement = db.scalar.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert set(compiled.params.values()) == {row.id, row.organization_id, "project"}
    assert "FOR UPDATE" in str(compiled)
    assert statement.get_execution_options()["populate_existing"] is True
    row.filesystem_metadata = {"docs/file": {"mode": 0o600, "modified_at": "2026-11-26T12:00:00Z"}}
    _, attributes = await repo.metadata(db, row.id, organization_id=row.organization_id)
    assert attributes == {
        "docs/file": FsStoredAttributes(
            mode=0o600, modified_at=datetime(2026, 11, 26, 12, tzinfo=UTC)
        )
    }


@pytest.mark.security
async def test_missing_or_cross_tenant_workspace_is_a_missing_file_not_an_empty_document() -> None:
    db = MagicMock(spec=AsyncSession)
    db.scalar.return_value = None
    with pytest.raises(FileNotFoundError) as refused:
        await repo.metadata(db, uuid4(), organization_id=uuid4())
    assert refused.value.errno == errno.ENOENT
    db.flush.assert_not_awaited()


@pytest.mark.parametrize(
    "stored",
    [
        {"file": {"mode": 0o1000}},
        {"file": {"mode": "invalid"}},
        {"file": {"mode": 0o600, "modified_at": "invalid-date"}},
    ],
)
async def test_corrupt_stored_metadata_is_rejected_instead_of_silently_defaulted(
    stored: dict[str, object],
) -> None:
    db = MagicMock(spec=AsyncSession)
    row = AgentWorkspace(
        id=uuid4(), organization_id=uuid4(), scope="project", filesystem_metadata=stored
    )
    db.scalar.return_value = row
    with pytest.raises(ValidationError):
        await repo.metadata(db, row.id, organization_id=row.organization_id)
    db.flush.assert_not_awaited()


async def test_metadata_save_keeps_json_safe_modes_times_and_durable_exclusive_markers() -> None:
    db = MagicMock(spec=AsyncSession)
    row = AgentWorkspace(id=uuid4())
    values = {
        "file": FsStoredAttributes(
            mode=0,
            modified_at=datetime(2026, 11, 26, 12, tzinfo=UTC),
            creation_verifier="MTIzNDU2Nzg=",
            creation_marker="durable-file-identity",
        )
    }
    await repo.save_metadata(db, row, values)
    stored = json.loads(json.dumps(row.filesystem_metadata))
    assert stored == {
        "file": {
            "mode": 0,
            "modified_at": "2026-11-26T12:00:00Z",
            "creation_verifier": "MTIzNDU2Nzg=",
            "creation_marker": "durable-file-identity",
        }
    }
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()
    db.flush.side_effect = RuntimeError("storage transaction failed")
    with pytest.raises(RuntimeError, match="storage transaction failed"):
        await repo.save_metadata(db, row, {})


async def test_timestamp_save_preserves_binary_content_creation_date_encoding_and_other_files() -> (
    None
):
    db = MagicMock(spec=AsyncSession)
    binary: FileData = {
        "content": ["AP8="],
        "encoding": "base64",
        "created_at": "2025-01-01T00:00:00+00:00",
        "modified_at": "2025-02-01T00:00:00+00:00",
    }
    text: FileData = {
        "content": ["unmodified"],
        "created_at": "2025-01-01T00:00:00+00:00",
        "modified_at": "2025-02-01T00:00:00+00:00",
    }
    row = AgentWorkspace(id=uuid4(), files={"/binary": binary, "/text": text}, version=7)
    timestamp = datetime(2026, 11, 26, 12, 34, 56, tzinfo=UTC)
    await repo.save_file_timestamp(db, row, "/binary", timestamp)
    assert row.files == {"/binary": {**binary, "modified_at": timestamp.isoformat()}, "/text": text}
    assert row.files["/binary"]["content"] == ["AP8="]
    assert row.files["/binary"]["created_at"] == binary["created_at"]
    assert row.files["/binary"]["encoding"] == "base64"
    assert row.version == 8
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(row)
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("files", [None, {}])
async def test_timestamp_save_cannot_invent_a_missing_file(
    files: dict[str, FileData] | None,
) -> None:
    db = MagicMock(spec=AsyncSession)
    row = AgentWorkspace(id=uuid4(), files=files, version=1)
    with pytest.raises(KeyError):
        await repo.save_file_timestamp(db, row, "/missing", datetime.now(UTC))
    assert row.files == files and row.version == 1
    db.flush.assert_not_awaited()
    db.refresh.assert_not_awaited()


async def test_timestamp_save_refuses_corrupt_file_data_before_mutating_the_row() -> None:
    db = MagicMock(spec=AsyncSession)
    row = AgentWorkspace(
        id=uuid4(),
        files={
            "/corrupt": {
                "content": "not-a-list",
                "created_at": "unchanged",
                "modified_at": "unchanged",
            }
        },
        version=4,
    )
    with pytest.raises(ValidationError):
        await repo.save_file_timestamp(db, row, "/corrupt", datetime.now(UTC))
    assert row.files["/corrupt"]["content"] == "not-a-list" and row.version == 4
    db.flush.assert_not_awaited()
    db.refresh.assert_not_awaited()
