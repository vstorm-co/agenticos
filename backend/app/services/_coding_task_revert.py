"""Reverse one complete task patch after checking every affected file.

Git applies the reverse patch to a private index first. Its entire resulting
tree must equal the recorded pre-task manifest before it may touch the workspace.
The real apply uses that same index's post-task state, so changes elsewhere in an
affected file are conflicts too. The user's repository and index are never used.
"""

import json
import logging
from pathlib import PurePosixPath
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError
from pydantic_ai.exceptions import UserError
from pydantic_ai.workspaces import Workspace, WorkspaceError

from app.core.exceptions import AlreadyExistsError, BadRequestError, ExternalServiceError
from app.schemas.coding_task_change import MAX_REVERT_BYTES, MAX_REVERT_FILE_BYTES, ChangedFile
from app.services.sandbox_workspace import NOT_BROWSABLE, TOOLING_DIRS

logger = logging.getLogger(__name__)

PAYLOAD_ENV = "AGENTICOS_REVERT"

# The payload goes through the environment: the workspace audit records commands.
SCRIPT = r"""
import base64
import fcntl
import json
import os
import stat
import subprocess
import tempfile

payload = json.loads("".join(os.environ["AGENTICOS_REVERT_" + str(index)]
                             for index in range(int(os.environ["AGENTICOS_REVERT_COUNT"]))))
before, after = payload["before"], payload["after"]
patch = base64.b64decode(payload["patch"], validate=True)
paths = sorted(after)

def answer(status, conflicts=None):
    print(json.dumps({"status": status, "paths": conflicts or []}))
    raise SystemExit

def read(path):
    global remaining
    descriptor = os.open(".", os.O_RDONLY | os.O_DIRECTORY)
    try:
        parts = path.split("/")
        for part in parts[:-1]:
            parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = parent
        file = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        try:
            info = os.fstat(file)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > file_limit:
                raise ValueError("unsupported file")
            if info.st_size > remaining:
                raise ValueError("verification byte limit exceeded")
            read_limit = min(file_limit, remaining)
            with os.fdopen(os.dup(file), "rb") as stream:
                content = stream.read(read_limit + 1)
            remaining -= len(content)
            if len(content) > read_limit:
                raise ValueError("oversized file")
            return "100755" if info.st_mode & stat.S_IXUSR else "100644", content
        finally:
            os.close(file)
    except FileNotFoundError:
        return None
    finally:
        os.close(descriptor)

root = os.getcwd()
file_limit = payload["file_limit"]
remaining = payload["byte_limit"]
# Every attempt uses the same inode. Never unlink it: an old, timed-out
# command might still hold its lock when a worker tries to reconcile it.
try:
    try:
        os.mkdir(".agenticos", 0o700)
    except FileExistsError:
        pass
    directory = os.open(".agenticos", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        lock = os.open("task-revert.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                       0o600, dir_fd=directory)
    finally:
        os.close(directory)
    info = os.fstat(lock)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        answer("unavailable")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    answer("unavailable")
with tempfile.TemporaryDirectory(prefix="agenticos-revert-") as store:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_DIR=store + "/git", GIT_INDEX_FILE=store + "/index", GIT_WORK_TREE=root,
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_OPTIONAL_LOCKS="0",
               GIT_ATTR_NOSYSTEM="1",
               GIT_CONFIG_COUNT="4", GIT_CONFIG_KEY_0="core.fsmonitor", GIT_CONFIG_VALUE_0="false",
               GIT_CONFIG_KEY_1="core.hooksPath", GIT_CONFIG_VALUE_1=os.devnull,
               GIT_CONFIG_KEY_2="core.autocrlf", GIT_CONFIG_VALUE_2="false",
               GIT_CONFIG_KEY_3="core.filemode", GIT_CONFIG_VALUE_3="true")

    def git(*args, data=None, preview=False):
        selected = dict(env, GIT_INDEX_FILE=store + "/preview") if preview else env
        return subprocess.run(["git", *args], input=data, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=selected, check=False)

    if git("init", "-q").returncode:
        answer("unavailable")
    # Restore bytes, without applying the workspace's Git checkout conversions.
    with open(env["GIT_DIR"] + "/info/attributes", "w", encoding="ascii") as attributes:
        attributes.write("* -text -filter -ident -working-tree-encoding\n")
    if git("read-tree", "--empty").returncode:
        answer("unavailable")
    conflicts, index, states = [], [], {}
    for path in paths:
        try:
            current = read(path)
        except (OSError, ValueError):
            conflicts.append(path)
            continue
        expected = after[path]
        if current is None:
            states[path] = None
            if expected is not None:
                conflicts.append(path)
            continue
        mode, content = current
        hashed = git("hash-object", "-w", "--no-filters", "--stdin", data=content)
        oid = hashed.stdout.decode("ascii").strip()
        if not hashed.returncode:
            states[path] = [mode, oid]
        if hashed.returncode or expected != [mode, oid]:
            conflicts.append(path)
            continue
        index.append((mode + " " + oid + "\t" + path).encode("utf-8") + b"\0")
    if payload["reconcile"] and states == before:
        answer("ok")
    if conflicts:
        answer("unknown" if payload["reconcile"] else "conflict", conflicts)
    if git("update-index", "-z", "--index-info", data=b"".join(index)).returncode:
        answer("unavailable")
    if git("update-index", "--refresh").returncode:
        answer("conflict", paths)
    import shutil
    shutil.copyfile(env["GIT_INDEX_FILE"], store + "/preview")
    if git("apply", "--reverse", "--cached", "--whitespace=nowarn", "-", data=patch, preview=True).returncode:
        answer("invalid_patch")
    restored = {}
    listing = git("ls-files", "--stage", "-z", preview=True)
    if listing.returncode:
        answer("unavailable")
    for entry in listing.stdout.split(b"\0")[:-1]:
        metadata, path = entry.split(b"\t", 1)
        mode, oid, stage = metadata.decode("ascii").split(" ")
        if stage != "0":
            answer("invalid_patch")
        restored[path.decode("utf-8")] = [mode, oid]
    if restored != {path: state for path, state in before.items() if state is not None}:
        answer("invalid_patch")
    # Git checks every path before applying; --reject would permit partial writes.
    applied = git("apply", "--reverse", "--index", "--whitespace=nowarn", "-", data=patch)
    if applied.returncode:
        answer("unavailable")
    answer("ok")
"""


class RevertAnswer(BaseModel):
    status: Literal["ok", "conflict", "invalid_patch", "unavailable", "unknown"]
    paths: list[str] = []


def _safe_path(path: str) -> bool:
    return (
        bool(path)
        and "\x00" not in path
        and not path.startswith("/")
        and str(PurePosixPath(path)) == path
        and ".." not in path.split("/")
        and not set(path.split("/")) & TOOLING_DIRS
        and not f"{path}/".startswith(NOT_BROWSABLE)
    )


def manifests(
    files: list[ChangedFile],
) -> tuple[dict[str, list[str] | None], dict[str, list[str] | None]]:
    """The exact before and after states, including absent rename destinations."""
    before: dict[str, list[str] | None] = {}
    after: dict[str, list[str] | None] = {}
    for file in files:
        for path in (file.path, file.old_path):
            if path is not None:
                if not _safe_path(path):
                    raise BadRequestError(
                        message="This task contains a path that cannot be reverted", details={}
                    )
                before.setdefault(path, None)
                after.setdefault(path, None)
    for file in files:
        for target, path, mode, blob in (
            (before, file.old_path or file.path, file.before_mode, file.before_blob),
            (after, file.path, file.after_mode, file.after_blob),
        ):
            if (
                mode not in ("000000", "100644", "100755")
                or blob is None
                or len(blob) != 40
                or any(char not in "0123456789abcdef" for char in blob)
            ):
                raise BadRequestError(
                    message="This task has no complete regular-file snapshot to revert", details={}
                )
            if mode != "000000":
                if target[path] is not None:
                    raise BadRequestError(
                        message="This task's file snapshot is inconsistent", details={}
                    )
                target[path] = [mode, blob]
    return before, after


async def revert(
    workspace: Workspace, files: list[ChangedFile], patch: str, *, reconcile: bool = False
) -> None:
    """Refuse every conflict before restoring exactly the task's affected files."""
    before, after = manifests(files)
    payload = json.dumps(
        {
            "before": before,
            "after": after,
            "patch": patch,
            "reconcile": reconcile,
            "file_limit": MAX_REVERT_FILE_BYTES,
            "byte_limit": MAX_REVERT_BYTES,
        }
    )
    # Linux limits each individual argument/environment value to 128 KiB.
    chunks = [payload[index : index + 32_000] for index in range(0, len(payload), 32_000)]
    env = {f"{PAYLOAD_ENV}_{index}": chunk for index, chunk in enumerate(chunks)}
    env[f"{PAYLOAD_ENV}_COUNT"] = str(len(chunks))
    try:
        result = await workspace.run(
            ["python3", "-I", "-S", "-c", SCRIPT],
            env=env,
            timeout=120,
        )
    except (WorkspaceError, UserError, httpx.HTTPError, OSError, TimeoutError) as failed:
        logger.warning("A coding task could not be reverted: %s", type(failed).__name__)
        raise ExternalServiceError(
            message="The workspace could not complete the revert", details={}
        ) from None
    try:
        answer = RevertAnswer.model_validate_json(result.stdout)
    except ValidationError:
        raise ExternalServiceError(
            message="The workspace could not complete the revert", details={}
        ) from None
    if result.exit_code != 0 or answer.status == "unavailable":
        raise ExternalServiceError(
            message="The workspace could not complete the revert", details={}
        )
    if answer.status == "unknown":
        raise ExternalServiceError(
            message="The previous revert's outcome could not be established. The workspace remains reserved.",
            details={},
        )
    if answer.status == "conflict":
        # Never return paths supplied by a sandbox that were not in the recorded set.
        conflicts = sorted(set(answer.paths) & after.keys())
        raise AlreadyExistsError(
            message="Files changed after this task. The task was not reverted.",
            details={"conflicting_files": conflicts},
        )
    if answer.status == "invalid_patch":
        raise BadRequestError(
            message="This task's patch cannot restore its complete snapshot", details={}
        )
