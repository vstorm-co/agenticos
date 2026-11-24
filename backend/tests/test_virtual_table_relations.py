"""Relationship classification and guards preserve edges, evidence and read limits."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.core.permissions import AuthContext
from app.db.models.virtual_table import VirtualTable
from app.db.models.virtual_table_relation import (
    VirtualTableLinkEvidence,
    VirtualTableRecordLink,
    VirtualTableRelation,
)
from app.repositories import virtual_table_relation as relation_repo
from app.repositories import virtual_table_repo
from app.repositories.virtual_table_relation import LinkEvidence, LinkPlan, plan_links
from app.schemas.virtual_table import ColumnDef, ColumnInput
from app.schemas.virtual_table_relation import BacklinkQuery
from app.services.virtual_tables.computed import LinkedTable
from app.services.virtual_tables.records import _BoundWalk

FIRST = UUID("00000000-0000-4000-8000-000000000001")
SECOND = UUID("00000000-0000-4000-8000-000000000002")


@pytest.mark.parametrize("value", [None, []])
def test_empty_cell_has_no_edges_or_evidence(value):
    assert plan_links(value, {FIRST}) == LinkPlan((), ())


@pytest.mark.parametrize("value", ["broken", 1, False, {"id": str(FIRST)}])
def test_invalid_whole_cell_is_retained_intact(value):
    assert plan_links(value, {FIRST}) == LinkPlan((), (LinkEvidence(-1, "invalid_cell", value),))


def test_keeps_order_and_records_each_rejected_position():
    value = [str(SECOND), "broken", str(FIRST), str(SECOND), 3, None]
    plan = plan_links(value, {SECOND})
    assert plan.links == ((0, SECOND),)
    assert plan.evidence == (
        LinkEvidence(1, "invalid_id", "broken"),
        LinkEvidence(2, "missing_target", str(FIRST)),
        LinkEvidence(3, "duplicate_target", str(SECOND)),
        LinkEvidence(4, "invalid_id", 3),
        LinkEvidence(5, "invalid_id", None),
    )
    assert value == [str(SECOND), "broken", str(FIRST), str(SECOND), 3, None]


def test_uuid_spellings_share_identity_and_over_limit_cells_are_not_partially_cut_over():
    assert plan_links([SECOND.hex, str(FIRST)], {FIRST, SECOND}).links == ((0, SECOND), (1, FIRST))
    value = [str(FIRST), str(SECOND)]
    assert plan_links(value, {FIRST, SECOND}, max_links=1) == LinkPlan(
        (), (LinkEvidence(-1, "limit_exceeded", value),)
    )
    assert plan_links([str(FIRST), str(FIRST)], set()).evidence == (
        LinkEvidence(0, "missing_target", str(FIRST)),
        LinkEvidence(1, "duplicate_target", str(FIRST)),
    )


def test_active_positions_are_dense_while_repair_evidence_keeps_original_positions():
    plan = plan_links(["bad", str(SECOND), str(FIRST)], {FIRST, SECOND})
    assert plan.links == ((0, SECOND), (1, FIRST))
    assert plan.evidence == (LinkEvidence(0, "invalid_id", "bad"),)


@pytest.mark.parametrize("limit", [0, 101])
def test_link_cardinality_has_bounded_request_schema(limit):
    with pytest.raises(ValidationError):
        ColumnInput(label="Customer", type="link", link_table_id=FIRST, link_limit=limit)


def test_backlinks_do_not_accept_write_fields_or_unbounded_paging():
    with pytest.raises(ValidationError):
        BacklinkQuery(source_table_id=FIRST, column_id=SECOND, values={})
    with pytest.raises(ValidationError):
        BacklinkQuery(source_table_id=FIRST, column_id=SECOND, limit=101)


def test_relationship_reprs_never_include_retained_sensitive_cell_values():
    definition = VirtualTableRelation(source_table_id=FIRST, column_id=SECOND)
    edge = VirtualTableRecordLink(source_record_id=FIRST, column_id=SECOND)
    evidence = VirtualTableLinkEvidence(
        source_record_id=FIRST, reason="invalid_cell", value="private content"
    )
    assert str(FIRST) in repr(definition)
    assert str(SECOND) in repr(edge)
    assert "invalid_cell" in repr(evidence)
    assert "private content" not in repr(evidence)


@pytest.mark.anyio
async def test_relationship_schema_requires_an_existing_source_table():
    db = AsyncMock()
    db.scalar.return_value = None

    with pytest.raises(ValueError, match="requires an existing source table"):
        await relation_repo.sync_schema(db, table_id=FIRST, columns=[])

    db.execute.assert_not_awaited()
    db.flush.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.security
@pytest.mark.parametrize("target_state", ["missing", "archived"])
async def test_unavailable_canonical_destinations_add_no_read_cost(target_state, monkeypatch):
    record_id, linked_id = uuid4(), uuid4()
    link = ColumnDef(id=uuid4(), label="Related", type="link", link_table_id=SECOND)
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    target = (
        None
        if target_state == "missing"
        else VirtualTable(id=SECOND, archived_at=datetime.now(UTC))
    )
    monkeypatch.setattr(
        relation_repo,
        "linked_ids",
        AsyncMock(return_value={record_id: {link.id: [str(linked_id)]}}),
    )
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=target))
    sizes = AsyncMock(return_value={linked_id: 100})
    monkeypatch.setattr(virtual_table_repo, "get_record_sizes_by_ids", sizes)
    walk = _BoundWalk(
        MagicMock(),
        ctx,
        FIRST,
        [link],
        tables={SECOND: LinkedTable(table_id=SECOND, columns=[], named_by=None)},
        targets={SECOND: frozenset()},
        reached=frozenset({link.id}),
        deadline=MagicMock(arm=AsyncMock()),
    )

    assert await walk.fitting([(record_id, 5)], room=5) == ([record_id], 5)
    sizes.assert_not_awaited()
