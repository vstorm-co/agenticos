"""What a coding task changed: the snapshot, the diff, the bounds and the read (#2480).

The snapshot scripts run for real here, against a temporary directory through a
local workspace, so the `find`, `git update-index` and `diff-tree` they are made
of are what is tested - not a string compared with itself.
"""

import base64
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import anyio
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.workspaces import (
    CommandResult,
    LocalWorkspaceBackend,
    Workspace,
    WorkspaceError,
    WrapperWorkspace,
)

from app.agents.capabilities.coding_agent import _changes
from app.api import deps
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.coding_task_change import ChangeSet
from app.services import coding_task_changes as service_module
from app.services.coding_task_changes import CodingTaskChangeService

pytestmark = pytest.mark.anyio

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _ctx(workspace: Workspace) -> Any:
    return SimpleNamespace(workspace=workspace)


@pytest.fixture
def store_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "stores"
    monkeypatch.setattr(_changes, "CHANGES_ROOT", str(root))
    return root


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def total(a, b):\n    return a - b\n")
    (root / "README.md").write_text("# Demo\n")
    (root / "notes.txt").write_text("unchanged\n")
    return root


async def _task(project: Path, edit: Any) -> ChangeSet | None:
    ctx = _ctx(Workspace(LocalWorkspaceBackend(project)))
    baseline = await _changes.begin(ctx)
    assert baseline is not None
    edit(project)
    return await _changes.finish(ctx, baseline)


@needs_git
class TestTheSnapshot:
    async def test_a_task_that_edits_two_files_shows_exactly_those_two(
        self, project: Path, store_root: Path
    ) -> None:
        def edit(root: Path) -> None:
            (root / "src" / "app.py").write_text("def total(a, b):\n    return a + b\n")
            (root / "README.md").write_text("# Demo\n\nAdds numbers.\n")

        changes = await _task(project, edit)

        assert changes is not None and not changes.truncated
        assert [(entry.path, entry.status) for entry in changes.files] == [
            ("README.md", "modified"),
            ("src/app.py", "modified"),
        ]
        app_py = changes.files[1]
        assert (app_py.additions, app_py.deletions) == (1, 1)
        assert app_py.patch is not None
        assert app_py.patch.startswith("diff --git a/src/app.py b/src/app.py\n")
        assert "-    return a - b\n+    return a + b\n" in app_py.patch
        # The store is gone once the diff is read.
        assert list(store_root.iterdir()) == []

    async def test_a_task_that_changes_nothing_has_no_files(
        self, project: Path, store_root: Path
    ) -> None:
        changes = await _task(project, lambda root: None)
        assert changes == ChangeSet()

    async def test_new_deleted_renamed_and_binary_files_are_named(
        self, project: Path, store_root: Path
    ) -> None:
        def edit(root: Path) -> None:
            (root / "notes.txt").unlink()
            (root / "src" / "app.py").rename(root / "src" / "maths.py")
            (root / "logo.png").write_bytes(b"\x89PNG\x00\x01\x02")
            (root / "CHANGES.md").write_text("one\ntwo\n")

        changes = await _task(project, edit)

        assert changes is not None
        by_path = {entry.path: entry for entry in changes.files}
        assert by_path["notes.txt"].status == "deleted"
        assert by_path["CHANGES.md"].status == "added" and by_path["CHANGES.md"].additions == 2
        assert by_path["logo.png"].binary and by_path["logo.png"].status == "added"
        renamed = by_path["src/maths.py"]
        assert (renamed.status, renamed.old_path) == ("renamed", "src/app.py")

    async def test_a_clone_inside_is_diffed_file_by_file_and_toolchain_folders_are_not(
        self, project: Path, store_root: Path
    ) -> None:
        """`git add` would record a nested repository as one commit id, and a
        virtualenv or the task's own files would bury the edit."""
        clone = project / "clone"
        (clone / ".git").mkdir(parents=True)
        (clone / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        (clone / "lib.py").write_text("x = 1\n")
        (project / "node_modules" / "pkg").mkdir(parents=True)
        (project / ".agenticos" / "coding-agent").mkdir(parents=True)

        def edit(root: Path) -> None:
            (root / "clone" / "lib.py").write_text("x = 2\n")
            (root / "clone" / ".git" / "HEAD").write_text("ref: refs/heads/other\n")
            (root / "node_modules" / "pkg" / "index.js").write_text("module.exports = 1\n")
            (root / ".agenticos" / "coding-agent" / "t.jsonl").write_text("{}\n")

        changes = await _task(project, edit)

        assert changes is not None
        assert [entry.path for entry in changes.files] == ["clone/lib.py"]

    async def test_a_file_past_the_ceiling_is_left_out(
        self, project: Path, store_root: Path
    ) -> None:
        def edit(root: Path) -> None:
            (root / "dump.bin").write_bytes(b"a" * (_changes.MAX_FILE_BYTES + 1))
            (root / "small.txt").write_text("fits\n")

        changes = await _task(project, edit)

        assert changes is not None
        assert [entry.path for entry in changes.files] == ["small.txt"]


@needs_git
class TestWhatTheSnapshotSurvives:
    async def test_a_file_become_a_link_keeps_every_later_file_on_its_own_hunks(
        self, project: Path, store_root: Path
    ) -> None:
        """Git writes a type change as two parts of the patch for one file."""

        def edit(root: Path) -> None:
            (root / "README.md").unlink()
            (root / "README.md").symlink_to("notes.txt")
            (root / "src" / "app.py").write_text("def total(a, b):\n    return a + b\n")

        changes = await _task(project, edit)

        assert changes is not None and not changes.truncated
        readme, app_py = changes.files
        assert readme.path == "README.md" and readme.patch is not None
        assert readme.patch.count("diff --git ") == 2
        assert app_py.path == "src/app.py" and app_py.patch is not None
        assert "+    return a + b\n" in app_py.patch

    async def test_content_cannot_open_a_section_of_its_own(
        self, project: Path, store_root: Path
    ) -> None:
        def edit(root: Path) -> None:
            (root / "a.txt").write_text("x\x0cdiff --git a/evil b/evil\nmore\n")
            (root / "src" / "app.py").write_text("def total(a, b):\n    return a + b\n")

        changes = await _task(project, edit)

        assert changes is not None
        a_txt, app_py = changes.files
        assert a_txt.patch is not None
        assert sum(line.startswith("diff --git ") for line in a_txt.patch.split("\n")) == 1
        assert app_py.patch is not None and app_py.patch.startswith("diff --git a/src/app.py")

    async def test_the_platforms_own_files_are_never_in_a_diff(
        self, project: Path, store_root: Path
    ) -> None:
        """A spill in a shared workspace is somebody else's tool result."""
        (project / "skills" / "x").mkdir(parents=True)
        (project / "skills" / "x" / "SKILL.md").write_text("v1\n")

        def edit(root: Path) -> None:
            (root / "tool_output").mkdir()
            (root / "tool_output" / "call_abc").write_text("somebody else's search result\n")
            (root / "skills" / "x" / "SKILL.md").write_text("v2\n")

        assert await _task(project, edit) == ChangeSet()

    async def test_a_diff_git_could_not_make_is_none_not_no_changes(
        self, project: Path, store_root: Path
    ) -> None:
        ctx = _ctx(Workspace(LocalWorkspaceBackend(project)))
        baseline = await _changes.begin(ctx)
        assert baseline is not None
        gone = _changes.Baseline(store=baseline.store, tree="f" * 40)

        assert await _changes.finish(ctx, gone) is None

    @pytest.mark.skipif(
        subprocess.run(
            [shutil.which("find") or "find", ".", "-maxdepth", "0", "-readable"],
            capture_output=True,
            check=False,
        ).returncode
        != 0,
        reason="needs a find with -readable",
    )
    async def test_a_file_nobody_can_read_does_not_cost_the_whole_diff(
        self, project: Path, store_root: Path
    ) -> None:
        secret = project / "secret"
        secret.write_text("x\n")
        secret.chmod(0)
        try:
            changes = await _task(
                project, lambda root: (root / "README.md").write_text("# Changed\n")
            )
        finally:
            secret.chmod(0o600)
        assert changes is not None
        assert [entry.path for entry in changes.files] == ["README.md"]


_SHA = "0" * 40


def _raw(status: str, *paths: str) -> str:
    """One `--raw -z` record: the metadata field, then its path or paths."""
    return f":100644 100644 {_SHA} {_SHA} {status}\0" + "".join(f"{path}\0" for path in paths)


def _finish_output(listing: str, patch: str) -> str:
    """What `FINISH` prints for a listing and a patch, cut where the shell would cut them."""
    listed, patched = listing.encode(), patch.encode()
    shown = base64.b64encode(listed[: _changes.MAX_LIST_BYTES]).decode()
    kept = patched[: _changes.MAX_PATCH_BYTES].decode("utf-8", errors="replace")
    files = listing.count(":100644 ")
    return f"{len(listed)}\n{len(patched)}\n{files}\n{shown}\n{kept}"


def _patch(path: str, lines: int) -> str:
    body = "".join(f"+line {index}\n" for index in range(lines))
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{lines} @@\n{body}"
    )


class TestTheBounds:
    def test_a_patch_past_its_ceiling_is_cut_at_a_line_and_says_so(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_changes, "MAX_PATCH_BYTES", 300)
        patch = _patch("a.txt", 5) + _patch("b.txt", 50) + _patch("c.txt", 5)
        output = _finish_output(
            _raw("A", "a.txt")
            + _raw("A", "b.txt")
            + _raw("A", "c.txt")
            + "5\t0\ta.txt\0"
            + "50\t0\tb.txt\0"
            + "5\t0\tc.txt\0",
            patch,
        )

        changes = _changes.parse(output)

        assert changes is not None and changes.truncated
        first, second, third = changes.files
        assert first.patch == _patch("a.txt", 5) and not first.truncated
        assert second.truncated and second.patch is not None
        assert second.patch.endswith("\n" + _changes.TRUNCATED_MARKER)
        assert (third.patch, third.additions) == (None, 5)

    def test_undecodable_bytes_do_not_make_a_whole_patch_look_cut(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The sandbox hands back U+FFFD for each byte it cannot decode - three
        bytes for one. The cut is the size git wrote, not the size of that text."""
        monkeypatch.setattr(_changes, "MAX_PATCH_BYTES", 300)
        latin = "diff --git a/l.txt b/l.txt\n@@ -0,0 +1 @@\n+" + "\ufffd" * 150 + "\n"
        small = _patch("z.txt", 1)
        listing = _raw("A", "l.txt") + _raw("A", "z.txt") + "1\t0\tl.txt\0" + "1\t0\tz.txt\0"
        # 150 raw bytes of Latin-1 - well under the ceiling, as git wrote them.
        raw_size = len(latin.encode()) - 150 * 2 + len(small.encode())
        output = (
            f"{len(listing.encode())}\n{raw_size}\n2\n"
            f"{base64.b64encode(listing.encode()).decode()}\n{latin}{small}"
        )

        changes = _changes.parse(output)

        assert changes is not None and not changes.truncated
        assert [entry.patch for entry in changes.files] == [latin, small]

    def test_files_past_the_ceiling_are_counted_not_listed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_changes, "MAX_FILES", 1)
        output = _finish_output(
            _raw("M", "a.txt") + _raw("M", "b.txt") + "1\t1\ta.txt\0" + "2\t0\tb.txt\0",
            "diff --git a/a.txt b/a.txt\n@@ -1 +1 @@\n-a\n+A\n"
            "diff --git a/b.txt b/b.txt\n@@ -1 +1,2 @@\n b\n+c\n",
        )

        changes = _changes.parse(output)

        assert changes is not None
        assert [entry.path for entry in changes.files] == ["a.txt"]
        assert changes.files[0].patch is not None and not changes.files[0].truncated
        assert (changes.omitted, changes.truncated) == (1, True)

    def test_a_list_too_long_to_read_back_is_only_counted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_changes, "MAX_LIST_BYTES", 60)
        listing = "".join(_raw("A", f"f{index}.txt") for index in range(3))
        listing += "".join(f"1\t0\tf{index}.txt\0" for index in range(3))

        changes = _changes.parse(_finish_output(listing, ""))

        assert changes == ChangeSet(omitted=3, truncated=True)

    def test_a_renamed_files_counts_line_up_with_the_file_after_it(self) -> None:
        output = _finish_output(
            _raw("R090", "old.py", "new.py")
            + _raw("D", "gone.bin")
            + "3\t1\t\0old.py\0new.py\0"
            + "-\t-\tgone.bin\0",
            "diff --git a/old.py b/new.py\nsimilarity index 90%\n"
            "diff --git a/gone.bin b/gone.bin\nBinary files a/gone.bin and /dev/null differ\n",
        )

        changes = _changes.parse(output)

        assert changes is not None and not changes.truncated
        renamed, gone = changes.files
        assert (renamed.path, renamed.old_path, renamed.additions, renamed.deletions) == (
            "new.py",
            "old.py",
            3,
            1,
        )
        assert (gone.status, gone.binary, gone.additions) == ("deleted", True, 0)

    def test_a_patch_that_does_not_line_up_gives_no_file_anothers_hunks(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        output = _finish_output(
            _raw("M", "a.txt") + "1\t1\ta.txt\0",
            "diff --git a/a.txt b/a.txt\n-a\n+A\ndiff --git a/b.txt b/b.txt\n-b\n+B\n",
        )

        changes = _changes.parse(output)

        assert changes is not None and changes.truncated
        assert changes.files[0].patch is None
        assert "did not line up" in caplog.text

    @pytest.mark.parametrize(
        "output",
        [
            "x\n0\n0\n\n",
            "0\n0\n0\nnot base64!\n",
            _finish_output(":100644 100644 a b M\0", ""),
            _finish_output(_raw("M", "a.txt"), ""),
        ],
        ids=["no-sizes", "garbled", "a-status-with-no-path", "a-file-with-no-counts"],
    )
    def test_output_that_is_not_a_change_set_is_none(self, output: str) -> None:
        assert _changes.parse(output) is None


class _Answering(WrapperWorkspace):
    """A sandbox answering each script with a canned result, or raising."""

    def __init__(self, answers: dict[str, CommandResult | BaseException]) -> None:
        super().__init__(Workspace(LocalWorkspaceBackend(Path.cwd())))
        self.answers = answers
        self.ran: list[str] = []

    async def run(self, command: Any, **_: Any) -> CommandResult:
        self.ran.append(command)
        answer = self.answers.get(command, CommandResult(exit_code=0, stdout="", stderr=""))
        if isinstance(answer, BaseException):
            raise answer
        return answer


class TestWhenItCannotBeTaken:
    async def test_a_runtime_without_git_runs_the_task_without_a_diff(self) -> None:
        shell = _Answering({_changes.BEGIN: CommandResult(exit_code=97, stdout="", stderr="")})
        assert await _changes.begin(_ctx(shell)) is None
        assert shell.ran == [_changes.BEGIN, _changes.DISCARD]

    async def test_a_snapshot_that_failed_is_logged_and_the_store_removed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        shell = _Answering({_changes.BEGIN: CommandResult(exit_code=1, stdout="", stderr="no")})
        assert await _changes.begin(_ctx(shell)) is None
        assert "could not be snapshotted (exit 1): no" in caplog.text
        assert shell.ran[-1] == _changes.DISCARD

    async def test_a_sandbox_that_refused_the_snapshot_costs_only_the_diff(self) -> None:
        shell = _Answering({_changes.BEGIN: WorkspaceError("gone")})
        assert await _changes.begin(_ctx(shell)) is None
        assert shell.ran == [_changes.BEGIN, _changes.DISCARD]

    async def test_a_run_stopped_while_snapshotting_still_removes_the_store(self) -> None:
        shell = _Answering({_changes.BEGIN: anyio.get_cancelled_exc_class()()})
        with pytest.raises(anyio.get_cancelled_exc_class()):
            await _changes.begin(_ctx(shell))
        assert shell.ran == [_changes.BEGIN, _changes.DISCARD]

    @pytest.mark.parametrize(
        "answer",
        [WorkspaceError("gone"), CommandResult(exit_code=1, stdout="", stderr="bad object")],
        ids=["raised", "failed"],
    )
    async def test_a_diff_that_cannot_be_read_is_none_and_the_store_still_goes(
        self, answer: CommandResult | BaseException
    ) -> None:
        shell = _Answering({_changes.FINISH: answer})
        baseline = _changes.Baseline(store="/tmp/agenticos-changes/x", tree="a" * 40)  # noqa: S108
        assert await _changes.finish(_ctx(shell), baseline) is None
        assert shell.ran == [_changes.FINISH, _changes.DISCARD]

    async def test_a_run_stopped_while_diffing_still_removes_the_store(self) -> None:
        shell = _Answering({_changes.FINISH: anyio.get_cancelled_exc_class()()})
        baseline = _changes.Baseline(store="/tmp/agenticos-changes/x", tree="a" * 40)  # noqa: S108
        with pytest.raises(anyio.get_cancelled_exc_class()):
            await _changes.finish(_ctx(shell), baseline)
        assert shell.ran == [_changes.FINISH, _changes.DISCARD]

    async def test_a_store_that_cannot_be_removed_is_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        shell = _Answering({_changes.DISCARD: WorkspaceError("gone")})
        await _changes.discard(_ctx(shell), "/tmp/agenticos-changes/x")  # noqa: S108
        assert "was not removed" in caplog.text


CTX = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="viewer")


class TestReadingIt:
    """The service: tenant first, then the transcript's own reader check."""

    @pytest.fixture
    def repo(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        repo = AsyncMock()
        monkeypatch.setattr(service_module, "change_repo", repo)
        return repo

    @pytest.fixture
    def conversations(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        reader = AsyncMock()
        monkeypatch.setattr(service_module, "ConversationService", MagicMock(return_value=reader))
        return reader

    async def test_a_reader_of_the_conversation_reads_its_tasks_changes(
        self, repo: AsyncMock, conversations: AsyncMock
    ) -> None:
        change = SimpleNamespace(conversation_id=uuid4())
        repo.get_in_organization.return_value = change
        change_id = uuid4()

        assert await CodingTaskChangeService(MagicMock()).get(CTX, change_id) is change

        assert repo.get_in_organization.await_args.args[1:] == (change_id,)
        assert repo.get_in_organization.await_args.kwargs == {
            "organization_id": CTX.organization_id
        }
        conversations.get_conversation.assert_awaited_once()
        kwargs = conversations.get_conversation.await_args.kwargs
        assert (kwargs["user_id"], kwargs["organization_id"], kwargs["ctx"]) == (
            CTX.user_id,
            CTX.organization_id,
            CTX,
        )

    @pytest.mark.security
    async def test_one_in_another_organization_is_missing(
        self, repo: AsyncMock, conversations: AsyncMock
    ) -> None:
        repo.get_in_organization.return_value = None
        with pytest.raises(NotFoundError):
            await CodingTaskChangeService(MagicMock()).get(CTX, uuid4())
        conversations.get_conversation.assert_not_awaited()

    @pytest.mark.security
    async def test_one_in_a_conversation_the_caller_may_not_read_is_missing(
        self, repo: AsyncMock, conversations: AsyncMock
    ) -> None:
        repo.get_in_organization.return_value = SimpleNamespace(conversation_id=uuid4())
        conversations.get_conversation.side_effect = NotFoundError(message="Conversation not found")
        with pytest.raises(NotFoundError) as refused:
            await CodingTaskChangeService(MagicMock()).get(CTX, uuid4())
        # The change set's own refusal: nothing says a conversation is behind it.
        assert refused.value.message == "Change set not found"

    @pytest.mark.security
    async def test_a_caller_who_is_no_person_reads_none(
        self, repo: AsyncMock, conversations: AsyncMock
    ) -> None:
        """With no `user_id` the conversation check asks nothing at all."""
        nobody = AuthContext(user_id=None, organization_id=CTX.organization_id, role="viewer")
        with pytest.raises(NotFoundError):
            await CodingTaskChangeService(MagicMock()).get(nobody, uuid4())
        repo.get_in_organization.assert_not_awaited()

    async def test_recording_keeps_each_file_with_its_patch(self, repo: AsyncMock) -> None:
        changes = _changes.parse(
            _finish_output(
                _raw("M", "a.txt") + "1\t1\ta.txt\0", "diff --git a/a.txt b/a.txt\n-a\n+A\n"
            )
        )
        assert changes is not None
        organization, conversation = uuid4(), uuid4()

        await CodingTaskChangeService(MagicMock()).record(
            changes,
            organization_id=organization,
            conversation_id=conversation,
            tool_call_id="call-1",
            harness="claude_code",
        )

        kwargs = repo.create.await_args.kwargs
        assert kwargs["files"][0]["patch"] == "diff --git a/a.txt b/a.txt\n-a\n+A\n"
        assert (kwargs["organization_id"], kwargs["conversation_id"]) == (
            organization,
            conversation,
        )


class TestTheRoute:
    @pytest.fixture
    async def service(self) -> Any:
        changes = AsyncMock()
        app.dependency_overrides[deps.get_auth_context] = lambda: CTX
        app.dependency_overrides[deps.get_coding_task_change_service] = lambda: changes
        app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
        try:
            yield changes
        finally:
            app.dependency_overrides.clear()

    async def test_it_reads_through_the_service_with_the_callers_authority(
        self, service: AsyncMock
    ) -> None:
        change_id = uuid4()
        service.get.return_value = {
            "id": change_id,
            "conversation_id": uuid4(),
            "harness": "codex",
            "files": [{"path": "a.txt", "status": "added", "additions": 1, "patch": "+a\n"}],
            "omitted": 0,
            "truncated": False,
            "created_at": "2026-11-04T00:00:00Z",
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"{settings.API_V1_STR}/conversations/coding-changes/{change_id}"
            )
        assert response.status_code == 200
        assert response.json()["files"][0]["patch"] == "+a\n"
        service.get.assert_awaited_once_with(CTX, change_id)

    @pytest.mark.security
    async def test_one_the_caller_may_not_read_is_a_404(self, service: AsyncMock) -> None:
        service.get.side_effect = NotFoundError(message="Change set not found")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"{settings.API_V1_STR}/conversations/coding-changes/{uuid4()}"
            )
        assert response.status_code == 404
