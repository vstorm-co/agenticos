"""Bounded, symlink-free copies for a personal coding task's private container."""

import base64
import binascii
import hashlib
import json
import logging
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import PurePosixPath
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import anyio
from pydantic import TypeAdapter, ValidationError
from pydantic_ai.workspaces import Workspace

from app.core.exceptions import BadRequestError
from app.services.sandbox_workspace import TOOLING_DIRS

logger = logging.getLogger(__name__)

MAX_FILES = 500
MAX_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024
_EXCLUDED = sorted(
    TOOLING_DIRS | {".agenticos", "skills", "tool_output", ".codex", ".claude", "coding-results"}
)
_COPY = """
import base64,json,os,stat
result={};total=0
excluded=set(json.loads(os.environ['EXCLUDED']))
for root,dirs,names,fd in os.fwalk('.',follow_symlinks=False):
    dirs[:]=[name for name in dirs if name not in excluded]
    for name in sorted(names):
        if name in excluded: continue
        info=os.stat(name,dir_fd=fd,follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode): continue
        if info.st_size>1048576: raise RuntimeError('A source file exceeds the personal-task limit')
        with os.fdopen(os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd),'rb') as stream:
            data=stream.read(1048577)
        if len(data)>1048576: raise RuntimeError('A source file grew beyond the personal-task limit')
        total+=len(data)
        if total>16777216 or len(result)>=500: raise RuntimeError('The personal-task snapshot is too large')
        path=os.path.relpath(os.path.join(root,name),'.')
        result[path]=[base64.b64encode(data).decode('ascii'),bool(info.st_mode & 0o111)]
os.makedirs('.agenticos/personal-coding',exist_ok=True)
with open(os.environ['SNAPSHOT'],'w') as target: json.dump(result,target)
"""
_FILES = TypeAdapter(dict[str, tuple[str, bool]])


@dataclass(frozen=True)
class CodingSnapshot:
    files: dict[str, bytes]
    revision: str
    executables: frozenset[str] = field(default_factory=frozenset)

    def archive(self, forbidden: tuple[str, ...]) -> bytes:
        target = BytesIO()
        with ZipFile(target, "w", ZIP_DEFLATED) as archive:
            for path, data in self.files.items():
                if any(value and (value.encode() in data or value in path) for value in forbidden):
                    raise BadRequestError(
                        message="A coding result contains credential material; export was refused"
                    )
                info = ZipInfo(path)
                info.compress_type = ZIP_DEFLATED
                info.external_attr = (0o100755 if path in self.executables else 0o100644) << 16
                archive.writestr(info, data)
        return target.getvalue()


def decode_snapshot(raw: bytes) -> CodingSnapshot:
    if len(raw) > MAX_BYTES * 2:
        raise BadRequestError(message="The coding snapshot exceeds its transfer limit")
    try:
        encoded = _FILES.validate_json(raw)
    except ValidationError:
        raise BadRequestError(message="The coding snapshot is invalid") from None
    if len(encoded) > MAX_FILES:
        raise BadRequestError(message="The coding snapshot has too many files")
    files: dict[str, bytes] = {}
    executables: set[str] = set()
    total = 0
    digest = hashlib.sha256()
    for path, (text, executable) in sorted(encoded.items()):
        path_bytes = path.encode("utf-8")
        parsed = PurePosixPath(path)
        if (
            not path
            or parsed.is_absolute()
            or any(part in (".", "..", *_EXCLUDED) for part in parsed.parts)
            or str(parsed) != path
            or "\\" in path
            or "\x00" in path
        ):
            raise BadRequestError(message="The coding snapshot contains an unsafe path")
        if len(text) > 2 * MAX_FILE_BYTES:
            raise BadRequestError(message="A coding snapshot file is too large")
        try:
            data = base64.b64decode(text, validate=True)
        except binascii.Error, ValueError:
            raise BadRequestError(message="A coding snapshot file is invalid") from None
        total += len(data)
        if total > MAX_BYTES or len(data) > MAX_FILE_BYTES:
            raise BadRequestError(message="The coding snapshot exceeds its content limit")
        files[path] = data
        if executable:
            executables.add(path)
        digest.update(path_bytes)
        digest.update(b"x" if executable else b"-")
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
    return CodingSnapshot(
        files=files, revision=digest.hexdigest(), executables=frozenset(executables)
    )


async def snapshot(workspace: Workspace) -> CodingSnapshot:
    path = f".agenticos/personal-coding/{uuid4().hex}.json"
    failed = True
    try:
        result = await workspace.run(
            ["python3", "-c", _COPY],
            env={"EXCLUDED": json.dumps(_EXCLUDED), "SNAPSHOT": path},
            timeout=120,
        )
        if result.exit_code != 0:
            raise BadRequestError(
                message="The workspace could not be copied within the personal-task limits. Use a smaller workspace or the local coding agent."
            )
        copied = decode_snapshot(await workspace.read_bytes(path))
        failed = False
        return copied
    finally:
        with anyio.CancelScope(shield=True):
            try:
                removed = await workspace.run(["rm", "-f", path], timeout=15)
            except Exception:
                if not failed:
                    raise
                logger.error("personal_coding_snapshot_cleanup_failed")
            else:
                if removed.exit_code != 0:
                    if not failed:
                        raise RuntimeError("The temporary coding snapshot could not be removed")
                    logger.error("personal_coding_snapshot_cleanup_failed")


async def populate(workspace: Workspace, source: CodingSnapshot) -> None:
    for path, data in source.files.items():
        await workspace.write_bytes(path, data)
    if source.executables:
        result = await workspace.run(
            ["chmod", "+x", *(f"./{path}" for path in sorted(source.executables))], timeout=30
        )
        if result.exit_code != 0:
            raise BadRequestError(
                message="The personal coding copy could not preserve executable files"
            )
