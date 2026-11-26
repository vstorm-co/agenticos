"""Filesystem ACKs follow authoritative flushes, including byte/mode/time metadata."""

import base64
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConcurrentChangeError, NotFoundError
from app.db.models.project import Project
from app.repositories import agent_workspace as workspace_repo
from app.repositories import project_filesystem as filesystem_repo
from app.schemas.project import ProjectCreate
from app.schemas.project_filesystem import FsRequest
from app.services.project import ProjectService
from app.services.project_filesystem import ProjectFilesystemService
from tests.integration.test_workflow_exposures import _ctx, _org, _user

pytestmark = [pytest.mark.anyio, pytest.mark.security]
_REQUEST = TypeAdapter(FsRequest)


async def test_fresh_operations_persist_binary_modes_dates_and_never_cross_tenants(
    db: AsyncSession,
):
    user = await _user(db)
    org = await _org(db, owner=user)
    ctx = _ctx(user, org)
    created = await ProjectService(db).create(
        ctx, ProjectCreate(name="Live files", backend="state")
    )
    project = await db.get(Project, created.id)
    assert project is not None
    generation = project.workspace_generation
    service = ProjectFilesystemService(db)

    async def call(op, path=".", **fields):
        response = await service.perform(
            ctx,
            project.id,
            generation,
            _REQUEST.validate_python({"op": op, "path": path, **fields}),
            writable=True,
        )
        await db.commit()
        return response

    await call("mkdir", "docs", mode=0o700)
    await call("mkdir", "docs/empty", mode=0o701)
    await call("create", "docs/result", mode=0o640)
    await call("write", "docs/result", offset=2, data=base64.b64encode(b"\x00\xff").decode())
    stamp = datetime(2025, 1, 1, tzinfo=UTC)
    await call("setattr", "docs/result", modified_at=stamp.isoformat())
    await call("rename", "docs", destination="published")
    read = await call("read", "published/result")
    assert base64.b64decode(read.data) == b"\x00\x00\x00\xff"
    stat = await call("stat", "published/result")
    assert stat.entry.mode == 0o640 and stat.entry.modified_at == stamp
    assert (await call("stat", "published/empty")).entry.mode == 0o701
    # The ordinary UI editor must not be masked by a stale mount mtime override.
    import hashlib

    await call("create", "text", mode=0o600)
    await call("write", "text", data=base64.b64encode(b"old").decode())
    await call("setattr", "text", modified_at=stamp.isoformat())
    await ProjectService(db).edit_file(
        ctx, project.id, path="text", content="new", revision=hashlib.sha256(b"old").hexdigest()
    )
    await db.commit()
    current = await call("stat", "text")
    assert current.entry.modified_at != stamp and current.entry.mode == 0o600
    other_org = await _org(db, owner=user)
    with pytest.raises(NotFoundError):
        await service.perform(
            _ctx(user, other_org),
            project.id,
            generation,
            _REQUEST.validate_python({"op": "stat"}),
            writable=True,
        )
    with pytest.raises(ConcurrentChangeError):
        await service.perform(
            ctx, project.id, uuid4(), _REQUEST.validate_python({"op": "stat"}), writable=True
        )

    # A retransmitted exclusive CREATE is durable across commits and does not truncate.
    verifier = base64.b64encode(b"12345678").decode()
    await call("create", "exclusive", exclusive=True, verifier=verifier)
    await call("write", "exclusive", data=base64.b64encode(b"kept").decode())
    assert (await call("create", "exclusive", exclusive=True, verifier=verifier)).ok
    assert base64.b64decode((await call("read", "exclusive")).data) == b"kept"
    before = (await call("stat", "exclusive")).entry
    await call(
        "setattr",
        "exclusive",
        size=2,
        mode=0o600,
        modified_at=stamp.isoformat(),
        guard_modified_at=before.modified_at.isoformat(),
    )
    assert base64.b64decode((await call("read", "exclusive")).data) == b"ke"
    assert (await call("stat", "exclusive")).entry.modified_at == stamp
    # Even writing the same payload changes the durable POSIX mtime.
    await call("write", "exclusive", data=base64.b64encode(b"ke").decode())
    assert (await call("stat", "exclusive")).entry.modified_at != stamp

    workspace = await workspace_repo.get_for_project(
        db, organization_id=org.id, project_id=project.id
    )
    assert workspace is not None
    with pytest.raises(FileNotFoundError):
        await filesystem_repo.metadata(db, workspace.id, organization_id=other_org.id)
    with pytest.raises(FileNotFoundError):
        await filesystem_repo.metadata(db, uuid4(), organization_id=org.id)
