"""Personal coding copies only project files and never publishes a credential."""

import base64
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from pydantic_ai.workspaces import Workspace
from pydantic_ai.workspaces.local import LocalWorkspaceBackend

from app.agents.capabilities.coding_agent._harness import CodingReport
from app.agents.capabilities.coding_agent._redaction import redact_changes, redact_report
from app.core.exceptions import BadRequestError
from app.schemas.coding_task_change import ChangedFile, ChangeSet
from app.services import personal_coding_snapshot as snapshots

pytestmark = pytest.mark.anyio


async def test_copy_is_independent_and_excludes_platform_credentials_and_symlinks(
    tmp_path: Path,
) -> None:
    source, private = tmp_path / "source", tmp_path / "private"
    source.mkdir()
    private.mkdir()
    (source / "app.py").write_text("print('old')")
    (source / "app.py").chmod(0o755)
    (source / ".agenticos").mkdir()
    (source / ".agenticos" / "credential").write_text("private")
    outside = tmp_path / "outside"
    outside.write_text("other person's secret")
    (source / "link").symlink_to(outside)
    origin = Workspace(LocalWorkspaceBackend(source))
    target = Workspace(LocalWorkspaceBackend(private))
    before = await snapshots.snapshot(origin)
    assert list(before.files) == ["app.py"]
    await snapshots.populate(target, before)
    assert (private / "app.py").stat().st_mode & 0o111
    (private / "app.py").write_text("print('new')")
    after = await snapshots.snapshot(target)
    assert before.revision != after.revision
    assert (source / "app.py").read_text() == "print('old')"
    with ZipFile(BytesIO(after.archive(()))) as archive:
        assert archive.namelist() == ["app.py"]
        assert archive.read("app.py") == b"print('new')"


@pytest.mark.parametrize(
    "path",
    ["../secret", "/secret", "dir/../secret", ".agenticos/key", "a\\b", "a//b", "", "\ud800"],
)
def test_a_snapshot_cannot_escape_or_copy_platform_files(path: str) -> None:
    with pytest.raises(BadRequestError):
        snapshots.decode_snapshot(
            json.dumps({path: [base64.b64encode(b"x").decode(), False]}).encode()
        )


@pytest.mark.parametrize("raw", [b"not json", b'{"a": 1}', b'{"a": ["@@@", false]}'])
def test_invalid_transfer_is_explicit(raw: bytes) -> None:
    with pytest.raises(BadRequestError):
        snapshots.decode_snapshot(raw)


def test_a_result_containing_the_account_credential_is_not_archived() -> None:
    value = snapshots.decode_snapshot(
        json.dumps({"app.py": [base64.b64encode(b"secret-token").decode(), False]}).encode()
    )
    with pytest.raises(BadRequestError):
        value.archive(("secret-token",))


def test_reports_and_diff_rows_do_not_retain_personal_tokens() -> None:
    report = CodingReport(
        harness="codex",
        access="edit",
        outcome="completed",
        answer="token=private-token",
        files_changed=["private-token.txt"],
    )
    assert "private-token" not in redact_report(report, ("private-token",)).model_dump_json()
    changes = ChangeSet(
        files=[
            ChangedFile(path="a.py", status="modified", patch="+private-token"),
            ChangedFile(path="b.py", status="added", patch="+safe"),
        ]
    )
    safe = redact_changes(changes, ("private-token",))
    assert "private-token" not in safe.model_dump_json()
    assert safe.truncated and safe.files[0].patch is None
    assert safe.files[1].patch == "+safe"


def test_snapshot_limits_are_checked_before_export(monkeypatch: pytest.MonkeyPatch) -> None:
    def raw(data: bytes) -> bytes:
        return json.dumps({"a": [base64.b64encode(data).decode(), False]}).encode()

    monkeypatch.setattr(snapshots, "MAX_BYTES", 100)
    with pytest.raises(BadRequestError):
        snapshots.decode_snapshot(b" " * 201)
    monkeypatch.setattr(snapshots, "MAX_FILES", 0)
    with pytest.raises(BadRequestError):
        snapshots.decode_snapshot(raw(b"a"))
    monkeypatch.setattr(snapshots, "MAX_FILES", 500)
    monkeypatch.setattr(snapshots, "MAX_FILE_BYTES", 2)
    with pytest.raises(BadRequestError):
        snapshots.decode_snapshot(raw(b"abcde"))
    with pytest.raises(BadRequestError):
        snapshots.decode_snapshot(raw(b"abc"))


@pytest.mark.parametrize("where", ["copy", "cleanup", "cleanup_exception", "chmod"])
async def test_snapshot_transport_failures_are_explicit(where: str) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    workspace = AsyncMock(spec=Workspace)
    okay = SimpleNamespace(exit_code=0)
    failed = SimpleNamespace(exit_code=1)
    workspace.read_bytes.return_value = b"{}"
    workspace.run.side_effect = (
        [failed, okay]
        if where == "copy"
        else [okay, RuntimeError("lost cleanup")]
        if where == "cleanup_exception"
        else [okay, failed]
    )
    if where == "chmod":
        workspace.run.side_effect = [failed]
        with pytest.raises(BadRequestError):
            await snapshots.populate(
                workspace, snapshots.CodingSnapshot({"x": b"x"}, "hash", frozenset({"x"}))
            )
    else:
        with pytest.raises(BadRequestError if where == "copy" else RuntimeError):
            await snapshots.snapshot(workspace)


async def test_a_cleanup_failure_preserves_the_original_copy_error() -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    workspace = AsyncMock(spec=Workspace)
    workspace.run.side_effect = [SimpleNamespace(exit_code=1), RuntimeError("cleanup failed")]
    with pytest.raises(BadRequestError):
        await snapshots.snapshot(workspace)


async def test_nonzero_cleanup_preserves_an_existing_copy_error() -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    workspace = AsyncMock(spec=Workspace)
    workspace.run.return_value = SimpleNamespace(exit_code=1)
    with pytest.raises(BadRequestError):
        await snapshots.snapshot(workspace)


@pytest.mark.security
def test_credential_whitespace_is_rejected_without_changing_the_secret() -> None:
    from pydantic import SecretStr, ValidationError

    from app.schemas.coding_account import CodingAccountCreate

    with pytest.raises(ValidationError):
        CodingAccountCreate(
            harness="codex", label="Mine", api_key=SecretStr(" key-with-whitespace ")
        )


def test_empty_redaction_values_do_not_erase_the_report() -> None:
    from app.agents.capabilities.coding_agent._redaction import redact_text

    assert redact_text("A private-token result", ("", "private-token")) == "A [redacted] result"
