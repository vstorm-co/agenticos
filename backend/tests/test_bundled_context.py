"""Bundled Context discovery respects access and never overwrites local edits."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.context import ContextFile
from app.db.models.context_proposal import ContextProposal
from app.services import context_proposal as module

pytestmark = pytest.mark.anyio


def _context() -> tuple[AuthContext, ContextFile]:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    file = ContextFile(
        id=uuid4(),
        organization_id=ctx.organization_id,
        name="platform-context",
        content="Local edits",
        description="Local description",
        library_revision="old",
        updated_at=datetime.now(UTC),
    )
    return ctx, file


@pytest.mark.parametrize("allowed", [True, False])
async def test_read_only_discovery_does_not_disclose_an_unreadable_context(
    monkeypatch: pytest.MonkeyPatch, allowed: bool
) -> None:
    ctx, file = _context()
    monkeypatch.setattr(module.context_repo, "get_by_library_key", AsyncMock(return_value=file))
    monkeypatch.setattr(module, "resolve_access", AsyncMock(return_value=allowed))
    assert await module.ContextProposalService(MagicMock()).bundled_product_context(
        ctx, synchronize=False
    ) is (file if allowed else None)


async def test_a_missing_bundled_definition_is_an_explicit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx, _ = _context()
    monkeypatch.setattr(module.context_repo, "get_by_library_key", AsyncMock(return_value=None))
    monkeypatch.setattr(module.skill_library, "get", lambda _key: None)
    with pytest.raises(NotFoundError, match="shipped product Context is missing"):
        await module.ContextProposalService(MagicMock()).bundled_product_context(
            ctx, synchronize=True
        )


@pytest.mark.parametrize("deleted", [True, False])
async def test_installation_respects_deletion_and_an_unmanaged_name_collision(
    monkeypatch: pytest.MonkeyPatch, deleted: bool
) -> None:
    ctx, file = _context()
    monkeypatch.setattr(module.context_repo, "get_by_library_key", AsyncMock(return_value=None))
    monkeypatch.setattr(
        module.audit_log_repo, "has_bundled_context_installation", AsyncMock(return_value=deleted)
    )
    by_name = AsyncMock(return_value=file)
    monkeypatch.setattr(module.context_repo, "get_by_name", by_name)
    create = AsyncMock()
    monkeypatch.setattr(module.ContextService, "create", create)
    assert (
        await module.ContextProposalService(MagicMock()).bundled_product_context(
            ctx, synchronize=True
        )
        is None
    )
    create.assert_not_awaited()
    if deleted:
        by_name.assert_not_awaited()
    else:
        by_name.assert_awaited_once()


@pytest.mark.parametrize("rewritten", [True, False])
async def test_a_pending_library_proposal_is_rewritten_or_replaced_after_a_decision_race(
    monkeypatch: pytest.MonkeyPatch, rewritten: bool
) -> None:
    ctx, file = _context()
    proposal = ContextProposal(id=uuid4(), context_id=file.id, organization_id=ctx.organization_id)
    monkeypatch.setattr(module.context_repo, "get_by_library_key", AsyncMock(return_value=file))
    monkeypatch.setattr(
        module.context_proposal_repo, "has_library_revision", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        module.context_proposal_repo, "get_pending_for_context", AsyncMock(return_value=proposal)
    )
    rewrite = AsyncMock(return_value=proposal if rewritten else None)
    create = AsyncMock()
    monkeypatch.setattr(module.context_proposal_repo, "rewrite", rewrite)
    monkeypatch.setattr(module.context_proposal_repo, "create", create)
    service = module.ContextProposalService(MagicMock())
    assert await service.bundled_product_context(ctx, synchronize=True) is file
    values = rewrite.call_args.kwargs["values"]
    assert values["base_updated_at"] == file.updated_at
    assert len(values["library_revision"]) == 64
    assert values["content"] != file.content
    assert file.content == "Local edits"
    if rewritten:
        create.assert_not_awaited()
    else:
        create.assert_awaited_once_with(
            service.db,
            organization_id=ctx.organization_id,
            context_id=file.id,
            values=values,
        )
