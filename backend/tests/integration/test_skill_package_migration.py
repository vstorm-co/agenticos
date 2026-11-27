"""The binary/frontmatter migration cannot silently discard imported information."""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Literal

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.services.skills import SkillService
from tests.integration.test_authoring import _owner

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def migration() -> ModuleType:
    path = Path(__file__).parents[2] / "alembic/versions/0376_skill_binary_resources.py"
    spec = importlib.util.spec_from_file_location("skill_package_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def step(session: Session, operation: Literal["upgrade", "downgrade"]) -> None:
    action: object = getattr(migration(), operation)
    assert callable(action)
    with Operations.context(MigrationContext.configure(session.connection())):
        action()


async def test_text_only_rows_roundtrip_without_changing_version_hashes(db: AsyncSession) -> None:
    ctx = await _owner(db)
    service = SkillService(db)
    skill = await service.create(
        ctx, name="text-only", description="A legacy text skill.", content="Instructions"
    )
    await service.put_resources(ctx, skill.id, [("references/exact.txt", b"  exact text\n")])
    assert skill.latest_version_id is not None
    version = await service.versions.export_version_by_id(ctx, skill.id, skill.latest_version_id)
    before = dict(version.resources)
    skill_id, version_id = skill.id, version.id
    await db.run_sync(step, "downgrade")
    names = await db.run_sync(
        lambda session: {
            item["name"] for item in inspect(session.connection()).get_columns("skill_resources")
        }
    )
    assert "encoding" not in names
    await db.run_sync(step, "upgrade")
    db.expire_all()
    restored = await service.versions.export_version_by_id(ctx, skill_id, version_id)
    assert restored.resources == before
    assert restored.manifest_metadata == {}
    resource = await service.versions.read_resource(
        ctx, skill_id, restored.id, "references/exact.txt"
    )
    assert resource.content == "  exact text\n"
    assert resource.encoding == "utf8"


@pytest.mark.parametrize("kind", ["binary", "metadata"])
async def test_downgrade_refuses_data_loss_without_dropping_columns(
    db: AsyncSession, kind: str
) -> None:
    ctx = await _owner(db)
    service = SkillService(db)
    skill = await service.create(
        ctx,
        name="protected",
        description="A protected skill.",
        content="Instructions",
        manifest_metadata={"license": "MIT"} if kind == "metadata" else {},
    )
    if kind == "binary":
        await service.put_resources(ctx, skill.id, [("assets/template.xlsx", b"PK\0\xff")])
    with pytest.raises(RuntimeError, match="cannot be discarded"):
        await db.run_sync(step, "downgrade")
    names = await db.run_sync(
        lambda session: {
            item["name"] for item in inspect(session.connection()).get_columns("skills")
        }
    )
    assert "manifest_metadata" in names
