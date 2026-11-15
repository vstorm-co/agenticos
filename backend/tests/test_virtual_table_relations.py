"""Classification preserves every invalid value and never manufactures a valid edge."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from app.db.models.virtual_table_relation import (
    VirtualTableLinkEvidence,
    VirtualTableRecordLink,
    VirtualTableRelation,
)
from app.repositories.virtual_table_relation import LinkEvidence, LinkPlan, plan_links
from app.schemas.virtual_table import ColumnInput
from app.schemas.virtual_table_relation import BacklinkQuery

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
