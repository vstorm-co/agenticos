"""Fresh, authorized operations on the authoritative Project filesystem.

No document survives a request. Mutations flush before returning; the request's
DBSession must commit before acknowledging an RPC to the mount broker.
"""

import base64
import binascii
import errno
import json
import os
import posixpath
from datetime import UTC, datetime
from uuid import UUID

from pydantic import TypeAdapter
from pydantic_ai.workspaces import SupportsCommands
from pydantic_ai_backends import FileData
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.sandbox._capped import CappedStateBackend, document_size
from app.core.config import settings
from app.core.exceptions import BadRequestError, ConcurrentChangeError, ExternalServiceError
from app.core.permissions import AuthContext
from app.repositories import project_filesystem as repo
from app.schemas.project_filesystem import (
    CHUNK_BYTES,
    MAX_FILE_BYTES,
    FsCreate,
    FsEntry,
    FsFailure,
    FsList,
    FsMkdir,
    FsRead,
    FsRemove,
    FsRename,
    FsRequest,
    FsResponse,
    FsSetattr,
    FsStat,
    FsStoredAttributes,
    FsSuccess,
    FsTruncate,
    FsWrite,
)
from app.services.project import project_path
from app.services.project_workspace_guard import project_for_workspace
from app.services.sandbox_workspace import NOT_BROWSABLE, OpenWorkspace, SandboxWorkspaceService

_RESPONSE = TypeAdapter(FsResponse)
_NATIVE_ARG_CHARS = 32 * 1024


def _path(path: str) -> str:
    if path == ".":
        return path
    if path.startswith("/") or "\\" in path or any(p in ("", ".", "..") for p in path.split("/")):
        raise PermissionError(errno.EACCES, "Choose a relative Project path")
    try:
        normalized = project_path(path)
    except BadRequestError as error:
        raise PermissionError(errno.EACCES, "Choose an accessible Project path") from error
    if normalized != path:
        raise PermissionError(errno.EACCES, "Choose an exact Project path")
    return normalized


def _visible(path: str) -> bool:
    try:
        _path(path)
    except PermissionError:
        return False
    else:
        return True


def _prepare(request: FsRequest) -> bytes:
    _path(request.path)
    if isinstance(request, FsRename):
        _path(request.destination)
        reserved = [prefix.strip("/") for prefix in NOT_BROWSABLE]
        if any(
            prefix.startswith(f"{name}/")
            for name in (request.path, request.destination)
            for prefix in reserved
        ):
            raise PermissionError(errno.EACCES, "A platform directory ancestor cannot be moved")
        if request.destination == ".":
            raise OSError(errno.EBUSY, "The mount root cannot be replaced")
    if request.path == "." and not isinstance(request, FsStat | FsList | FsRead | FsSetattr):
        raise OSError(errno.EBUSY, "The mount root cannot be replaced")
    data = b""
    if isinstance(request, FsWrite):
        try:
            data = base64.b64decode(request.data.encode("ascii"), validate=True)
        except (binascii.Error, UnicodeEncodeError) as error:
            raise OSError(errno.EINVAL, "Invalid base64") from error
        if len(data) > CHUNK_BYTES or request.offset + len(data) > MAX_FILE_BYTES:
            raise OSError(errno.EFBIG, "Write exceeds the filesystem limit")
    return data


class ProjectFilesystemService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.workspaces = SandboxWorkspaceService(db)

    async def perform(
        self,
        ctx: AuthContext,
        project_id: UUID,
        expected_generation: UUID | None,
        request: FsRequest,
        *,
        writable: bool,
    ) -> FsResponse:
        project = await project_for_workspace(self.db, ctx, project_id)
        if project.workspace_generation != expected_generation:
            raise ConcurrentChangeError(message="The Project filesystem generation changed")
        if not writable and not isinstance(request, FsStat | FsList | FsRead):
            return FsFailure(errno=errno.EROFS, message=os.strerror(errno.EROFS))
        try:
            data = _prepare(request)
            opened = await self.workspaces.open_project(ctx, project)
            try:
                if opened.kind == "state":
                    document = opened.document
                    if document is None or opened.row_id is None:
                        raise RuntimeError(
                            "A stored Project filesystem requires its document and row"
                        )
                    files_before = dict(document.files)
                    dirs_before = set(document.directories)
                    try:
                        result = await self._state(ctx, document, opened.row_id, request, data)
                    except OSError:
                        document.files.clear()
                        document.files.update(files_before)
                        document.directories.clear()
                        document.directories.update(dirs_before)
                        raise
                else:
                    result = await self._native(opened, request)
            finally:
                failure = await self.workspaces.close(opened)
                if failure is not None:
                    raise failure.error
        except OSError as error:
            number = error.errno or errno.EIO
            return FsFailure(
                errno=number,
                message="File attributes changed" if number == 10002 else os.strerror(number),
            )
        else:
            return result

    async def _state(
        self,
        ctx: AuthContext,
        document: CappedStateBackend,
        workspace_id: UUID,
        request: FsRequest,
        data: bytes,
    ) -> FsSuccess:
        row, metadata = await repo.metadata(
            self.db, workspace_id, organization_id=ctx.organization_id
        )
        path = request.path
        absolute = "/" if path == "." else f"/{path}"
        baseline_file = document.files.get(absolute)

        def exists(name: str) -> bool:
            return document.exists(name)

        def info(name: str) -> FsEntry:
            for index in range(1, len(name.split("/"))):
                ancestor = "/".join(name.split("/")[:index])
                if document.is_file(ancestor):
                    raise NotADirectoryError(errno.ENOTDIR, "Parent is a file")
            if not exists(name):
                raise FileNotFoundError(errno.ENOENT, "Missing entry")
            directory = document.is_dir(name)
            attrs = metadata.get(name)
            modified = None
            if not directory:
                modified = datetime.fromisoformat(document.files[f"/{name}"]["modified_at"])
            return FsEntry(
                path=name,
                is_dir=directory,
                size=0 if directory else len(document.read_bytes(name)),
                mode=attrs.mode if attrs else 0o755 if directory else 0o644,
                modified_at=attrs.modified_at if directory and attrs else modified,
            )

        def parent(name: str) -> None:
            directory = posixpath.dirname(name) or "."
            if not exists(directory):
                raise FileNotFoundError(errno.ENOENT, "Missing parent")
            if not document.is_dir(directory):
                raise NotADirectoryError(errno.ENOTDIR, "Parent is a file")

        def regular() -> bytes:
            current = info(path)
            if current.is_dir:
                raise IsADirectoryError(errno.EISDIR, "Not a regular file")
            return document.read_bytes(path)

        def changed(name: str, *, mode: int | None = None) -> None:
            before = metadata.get(name)
            directory = document.is_dir(name)
            metadata[name] = (
                before or FsStoredAttributes(mode=0o755 if directory else 0o644)
            ).model_copy(
                update={
                    "mode": mode
                    if mode is not None
                    else before.mode
                    if before
                    else 0o755
                    if directory
                    else 0o644,
                    "modified_at": datetime.now(UTC),
                }
            )

        if isinstance(request, FsStat):
            return FsSuccess(entry=info(path))
        if isinstance(request, FsList):
            if not info(path).is_dir:
                raise NotADirectoryError(errno.ENOTDIR, "Not a directory")
            names = [
                posixpath.join(path, name).removeprefix("./") for name, _ in document.list_dir(path)
            ]
            return FsSuccess(entries=[info(name) for name in names if _visible(name)])
        if isinstance(request, FsRead):
            content = regular()
            part = content[request.offset : request.offset + request.count]
            return FsSuccess(
                data=base64.b64encode(part).decode(), eof=request.offset + len(part) >= len(content)
            )
        if isinstance(request, FsWrite | FsTruncate):
            content = regular()
            size = (
                request.size
                if isinstance(request, FsTruncate)
                else max(len(content), request.offset + len(data))
            )
            if size > settings.SANDBOX_STATE_MAX_BYTES:
                raise OSError(errno.ENOSPC, "Project storage is full")
            if isinstance(request, FsTruncate):
                updated = content[:size].ljust(size, b"\x00")
            elif not data:
                return FsSuccess(written=0, entry=info(path))
            else:
                updated = (
                    content[: request.offset].ljust(request.offset, b"\x00")
                    + data
                    + content[request.offset + len(data) :]
                )
            document.write_bytes(path, updated)
            changed(path)
        elif isinstance(request, FsCreate):
            parent(path)
            present = exists(path)
            existing_mode = info(path).mode if present else request.mode
            if present:
                if request.exclusive:
                    previous = metadata.get(path)
                    stored = document.files.get(absolute)
                    if (
                        request.verifier is not None
                        and previous is not None
                        and stored is not None
                        and previous.creation_verifier == request.verifier
                        and previous.creation_marker == stored["created_at"]
                    ):
                        return FsSuccess(entry=info(path))
                    raise FileExistsError(errno.EEXIST, "Entry already exists")
                regular()
                if request.size is None and request.modified_at is None:
                    return FsSuccess(entry=info(path))
            else:
                document.write_bytes(path, b"")
            if request.size is not None:
                content = regular()
                if request.size > settings.SANDBOX_STATE_MAX_BYTES:
                    raise OSError(errno.ENOSPC, "Project storage is full")
                document.write_bytes(path, content[: request.size].ljust(request.size, b"\x00"))
            if request.modified_at is not None:
                document.files[absolute] = {
                    **document.files[absolute],
                    "modified_at": request.modified_at.isoformat(),
                }
                if (
                    document_size(document.files, document.directories)
                    > settings.SANDBOX_STATE_MAX_BYTES
                ):
                    raise OSError(errno.ENOSPC, "Project storage is full")
            changed(path, mode=existing_mode)
            if not present:
                metadata[path] = metadata[path].model_copy(
                    update={
                        "creation_verifier": request.verifier,
                        "creation_marker": document.files[absolute]["created_at"]
                        if request.verifier is not None
                        else None,
                    }
                )
                changed(posixpath.dirname(path) or ".")
        elif isinstance(request, FsMkdir):
            parent(path)
            if exists(path):
                raise FileExistsError(errno.EEXIST, "Entry already exists")
            document.make_dir(path)
            changed(path, mode=request.mode)
            if request.modified_at is not None:
                metadata[path] = metadata[path].model_copy(
                    update={"modified_at": request.modified_at}
                )
            changed(posixpath.dirname(path) or ".")
        elif isinstance(request, FsRemove):
            current = info(path)
            if current.is_dir != request.directory:
                raise OSError(
                    errno.ENOTDIR if request.directory else errno.EISDIR, "Wrong entry type"
                )
            if current.is_dir and document.list_dir(path):
                raise OSError(errno.ENOTEMPTY, "Directory is not empty")
            document.remove(path)
            metadata.pop(path, None)
            changed(posixpath.dirname(path) or ".")
        elif isinstance(request, FsRename):
            destination = request.destination
            current = info(path)
            parent(destination)
            if destination == path:
                return FsSuccess(entry=current)
            if destination == "." or destination.startswith(f"{path}/"):
                raise OSError(errno.EINVAL, "Invalid rename destination")
            if exists(destination):
                other = info(destination)
                if current.is_dir != other.is_dir:
                    raise OSError(
                        errno.ENOTDIR if current.is_dir else errno.EISDIR, "Wrong destination type"
                    )
                if other.is_dir and document.list_dir(destination):
                    raise OSError(errno.ENOTEMPTY, "Destination directory is not empty")
            target = f"/{destination}"
            files = {name: body for name, body in document.files.items() if name != target}
            directories = {name for name in document.directories if name != target}

            def moved(name: str) -> str:
                return (
                    target + name[len(absolute) :]
                    if name == absolute or name.startswith(absolute + "/")
                    else name
                )

            files = {moved(name): body for name, body in files.items()}
            directories = {moved(name) for name in directories}
            if document_size(files, directories) > settings.SANDBOX_STATE_MAX_BYTES:
                raise OSError(errno.ENOSPC, "Project storage is full")
            document.files.clear()
            document.files.update(files)
            document.directories.clear()
            document.directories.update(directories)
            metadata = {
                (
                    destination + name[len(path) :]
                    if name == path or name.startswith(path + "/")
                    else name
                ): attrs
                for name, attrs in metadata.items()
                if name != destination
            }
            changed(posixpath.dirname(path) or ".")
            changed(posixpath.dirname(destination) or ".")
            await repo.save_metadata(self.db, row, metadata)
            return FsSuccess(entry=info(destination))
        else:
            before = info(path)
            if (
                request.guard_modified_at is not None
                and before.modified_at != request.guard_modified_at
            ):
                raise OSError(10002, "File attributes changed")
            if request.size is not None:
                content = regular()
                if request.size > settings.SANDBOX_STATE_MAX_BYTES:
                    raise OSError(errno.ENOSPC, "Project storage is full")
                document.write_bytes(path, content[: request.size].ljust(request.size, b"\x00"))
            if not before.is_dir and request.modified_at is not None:
                candidate: FileData = {
                    **document.files[absolute],
                    "modified_at": request.modified_at.isoformat(),
                }
                after = {**document.files, absolute: candidate}
                ceiling = max(
                    settings.SANDBOX_STATE_MAX_BYTES,
                    document_size(document.files, document.directories),
                )
                if document_size(after, document.directories) > ceiling:
                    raise OSError(errno.ENOSPC, "Project storage is full")
                document.files[absolute] = candidate
            metadata[path] = (
                metadata.get(path) or FsStoredAttributes(mode=before.mode)
            ).model_copy(
                update={
                    "mode": request.mode if request.mode is not None else before.mode,
                    "modified_at": request.modified_at
                    if request.modified_at is not None
                    else before.modified_at,
                }
            )
        after_file = document.files.get(absolute)
        if (
            baseline_file is not None
            and after_file is not None
            and after_file["content"] == baseline_file["content"]
            and after_file.get("encoding") == baseline_file.get("encoding")
            and after_file["modified_at"] != baseline_file["modified_at"]
        ):
            await repo.save_file_timestamp(
                self.db, row, absolute, datetime.fromisoformat(after_file["modified_at"])
            )
        await repo.save_metadata(self.db, row, metadata)
        return FsSuccess(
            entry=info(path) if not isinstance(request, FsRemove) else None,
            written=len(data) if isinstance(request, FsWrite) else None,
        )

    async def exclusive_create_support(
        self,
        ctx: AuthContext,
        project_id: UUID,
        expected_generation: UUID | None,
        *,
        writable: bool,
    ) -> FsResponse:
        """Probe trusted native staging without publishing a user-visible file."""
        project = await project_for_workspace(self.db, ctx, project_id)
        if project.workspace_generation != expected_generation:
            raise ConcurrentChangeError(message="The Project filesystem generation changed")
        if not writable:
            return FsFailure(errno=errno.EROFS, message=os.strerror(errno.EROFS))
        opened = await self.workspaces.open_project(ctx, project)
        try:
            if opened.kind == "state":
                return FsSuccess()
            return await self._native_payload(opened, {"op": "probe", "path": "."})
        finally:
            failure = await self.workspaces.close(opened)
            if failure is not None:
                raise failure.error

    async def _native(self, opened: OpenWorkspace, request: FsRequest) -> FsResponse:
        return await self._native_payload(opened, request.model_dump(mode="json"))

    async def _native_payload(
        self, opened: OpenWorkspace, payload: dict[str, object]
    ) -> FsResponse:
        workspace = opened.workspace
        if not isinstance(workspace.backend, SupportsCommands):
            return FsFailure(
                errno=errno.EOPNOTSUPP, message="This filesystem needs a command-capable backend"
            )
        root = await workspace.working_dir()
        payload["reserved"] = [prefix.strip("/") for prefix in NOT_BROWSABLE]
        encoded = json.dumps(payload)
        parts = [
            encoded[index : index + _NATIVE_ARG_CHARS]
            for index in range(0, len(encoded), _NATIVE_ARG_CHARS)
        ]
        result = await workspace.run(["python3", "-c", _NATIVE, root, *parts], timeout=30)
        if result.exit_code != 0:
            raise ExternalServiceError(message="The Project filesystem worker failed")
        return _RESPONSE.validate_json(result.stdout)


_NATIVE = r"""
import os,sys,json,stat,base64,errno,hashlib,secrets
from datetime import datetime,timezone
os.umask(0)
root=None
r=json.loads(''.join(sys.argv[2:]))
fd=None

def parent(path):
    current=os.dup(root)
    parts=path.split('/')
    try:
        for part in parts[:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=current)
            os.close(current)
            current=child
        return current,parts[-1]
    except BaseException:
        os.close(current)
        raise

def inspect(path):
    p,n=parent(path)
    try:
        s=os.stat(n,dir_fd=p,follow_symlinks=False)
        if stat.S_ISLNK(s.st_mode): raise OSError(errno.ELOOP,'Links are not supported')
        if not (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)): raise OSError(errno.EOPNOTSUPP,'Special files are not supported')
        return {'path':path,'is_dir':stat.S_ISDIR(s.st_mode),'size':0 if stat.S_ISDIR(s.st_mode) else s.st_size,'mode':stat.S_IMODE(s.st_mode)&511,'modified_at':datetime.fromtimestamp(s.st_mtime,timezone.utc).isoformat()}
    finally: os.close(p)

def regular(path,flags):
    p,n=parent(path)
    try:
        result=os.open(n,flags|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=p)
        kind=os.fstat(result).st_mode
        if not stat.S_ISREG(kind):
            os.close(result)
            raise OSError(errno.EISDIR if stat.S_ISDIR(kind) else errno.EOPNOTSUPP,'Not a regular file')
        return result
    finally: os.close(p)


def stage_directory():
    current=os.dup(root)
    try:
        for component in ('.agenticos','projectfs-create'):
            try: os.mkdir(component,0o700,dir_fd=current)
            except FileExistsError: pass
            child=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=current)
            os.fsync(current)
            os.close(current)
            current=child
        return current
    except BaseException:
        os.close(current)
        raise

def apply_create_attrs(descriptor):
    if r.get('size') is not None: os.ftruncate(descriptor,r['size'])
    if r.get('modified_at') is not None:
        value=datetime.fromisoformat(r['modified_at'].replace('Z','+00:00')).timestamp()
        os.utime(descriptor,ns=(os.fstat(descriptor).st_atime_ns,int(value*1000000000)))

_MARKER='user.agenticos.projectfs.create'

def existing_creation(directory,name,marker):
    try: existing=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
    except FileNotFoundError: return False
    try:
        if not stat.S_ISREG(os.fstat(existing).st_mode): raise OSError(errno.EEXIST,'Entry exists')
        try: stored=os.getxattr(existing,_MARKER)
        except OSError as error:
            if error.errno in (getattr(errno,'ENODATA',61),getattr(errno,'ENOATTR',93),errno.ENOTSUP):
                raise OSError(errno.EEXIST,'Entry exists without this verifier') from error
            raise
        if stored!=marker: raise OSError(errno.EEXIST,'Entry exists with another verifier')
        os.fsync(existing)
        os.fsync(directory)
        return True
    finally: os.close(existing)

def exclusive_create(directory,name,path,probe=False):
    if not hasattr(os,'setxattr') or not hasattr(os,'getxattr'): raise OSError(errno.ENOTSUP,'Extended attributes are unavailable')
    marker=hashlib.sha256(path.encode()).digest()+base64.b64decode(r.get('verifier') or 'AAAAAAAAAAA=')
    if not probe and existing_creation(directory,name,marker): return
    staging=stage_directory()
    temporary=secrets.token_hex(16)
    staged=None
    try:
        staged=os.open(temporary,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=staging)
        os.setxattr(staged,_MARKER,marker)
        if os.getxattr(staged,_MARKER)!=marker: raise OSError(errno.EIO,'Creation marker did not persist')
        if not probe:
            apply_create_attrs(staged)
            os.fchmod(staged,r['mode'])
        os.fsync(staged)
        if probe:
            probe_name=secrets.token_hex(16)
            os.link(temporary,probe_name,src_dir_fd=staging,dst_dir_fd=staging,follow_symlinks=False)
            try: os.fsync(staging)
            finally: os.unlink(probe_name,dir_fd=staging)
        else:
            try: os.link(temporary,name,src_dir_fd=staging,dst_dir_fd=directory,follow_symlinks=False)
            except FileExistsError:
                if not existing_creation(directory,name,marker): raise OSError(errno.EEXIST,'Entry exists')
            os.fsync(directory)
    finally:
        if staged is not None:
            os.close(staged)
            os.unlink(temporary,dir_fd=staging)
            os.fsync(staging)
        os.close(staging)

try:
    root=os.open(sys.argv[1],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    op=r['op']; path=r['path']; result={'ok':True}
    if op=='probe': exclusive_create(root,'','.',probe=True)
    elif op=='stat': result['entry']=inspect(path)
    elif op=='list':
        p,n=parent(path)
        try: fd=os.open(n,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=p)
        finally: os.close(p)
        names=[(path+'/' if path!='.' else '')+name for name in sorted(os.listdir(fd))]
        result['entries']=[inspect(name) for name in names if not any(name==prefix or name.startswith(prefix+'/') for prefix in r['reserved'])]
    elif op=='read':
        fd=regular(path,os.O_RDONLY)
        content=os.pread(fd,r['count'],r['offset'])
        result.update(data=base64.b64encode(content).decode(),eof=r['offset']+len(content)>=os.fstat(fd).st_size)
    elif op=='write':
        fd=regular(path,os.O_RDWR)
        content=base64.b64decode(r['data'],validate=True)
        result['written']=os.pwrite(fd,content,r['offset'])
        os.fsync(fd)
        result['entry']=inspect(path)
    elif op=='truncate':
        fd=regular(path,os.O_RDWR)
        os.ftruncate(fd,r['size']); os.fsync(fd)
        result['entry']=inspect(path)
    elif op in ('create','mkdir','remove','rename','setattr'):
        p,n=parent(path)
        try:
            if op=='create':
                if r['verifier'] is not None:
                    exclusive_create(p,n,path)
                else:
                    flags=os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK
                    if r['exclusive']: flags|=os.O_EXCL
                    try: inspect(path)
                    except FileNotFoundError: pass
                    fd=os.open(n,flags,r['mode'],dir_fd=p)
                    if not stat.S_ISREG(os.fstat(fd).st_mode): raise OSError(errno.EOPNOTSUPP,'Not a regular file')
                    apply_create_attrs(fd)
                    os.fsync(fd)
            elif op=='mkdir':
                os.mkdir(n,r['mode'],dir_fd=p)
                if r['modified_at'] is not None:
                    fd=os.open(n,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=p)
                    value=datetime.fromisoformat(r['modified_at'].replace('Z','+00:00')).timestamp()
                    os.utime(fd,ns=(os.fstat(fd).st_atime_ns,int(value*1000000000)))
                    os.fsync(fd)
            elif op=='remove':
                entry=inspect(path)
                if entry['is_dir']!=r['directory']: raise OSError(errno.ENOTDIR if r['directory'] else errno.EISDIR,'Wrong entry type')
                (os.rmdir if r['directory'] else os.unlink)(n,dir_fd=p)
            elif op=='rename':
                inspect(path)
                q,m=parent(r['destination'])
                try:
                    try: inspect(r['destination'])
                    except FileNotFoundError: pass
                    os.replace(n,m,src_dir_fd=p,dst_dir_fd=q); os.fsync(q)
                finally: os.close(q)
            elif op=='setattr':
                inspect(path)
                fd=os.open(n,(os.O_RDWR if r['size'] is not None else os.O_RDONLY)|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=p)
                kind=os.fstat(fd).st_mode
                if not (stat.S_ISREG(kind) or stat.S_ISDIR(kind)): raise OSError(errno.EOPNOTSUPP,'Special files are not supported')
                if r['guard_modified_at'] is not None:
                    guard=datetime.fromisoformat(r['guard_modified_at'].replace('Z','+00:00'))
                    if datetime.fromtimestamp(os.fstat(fd).st_mtime,timezone.utc)!=guard: raise OSError(10002,'File attributes changed')
                if r['size'] is not None: os.ftruncate(fd,r['size'])
                if r['mode'] is not None: os.fchmod(fd,r['mode'])
                if r['modified_at'] is not None:
                    value=datetime.fromisoformat(r['modified_at'].replace('Z','+00:00')).timestamp()
                    os.utime(fd,ns=(os.fstat(fd).st_atime_ns,int(value*1000000000)))
                os.fsync(fd)
            os.fsync(p)
        finally: os.close(p)
        if op!='remove': result['entry']=inspect(r['destination'] if op=='rename' else path)
    print(json.dumps(result))
except OSError as error:
    number=error.errno or errno.EIO
    print(json.dumps({'ok':False,'errno':number,'message':'File attributes changed' if number==10002 else os.strerror(number)}))
finally:
    if fd is not None: os.close(fd)
    if root is not None: os.close(root)
"""
