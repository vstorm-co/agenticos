"""Every key a delete reaches in the skill tables is indexed.

Deleting a skill, a fork, a version, an agent, a dataset or a check cascades through
these keys or sets them to null. Without an index led by the key, each delete scans the
whole table once per row it removes, while it holds its locks.
"""

import pytest
from sqlalchemy import ForeignKeyConstraint, Table

import app.db.models  # noqa: F401  (registers every table on the metadata)
from app.db.base import Base

_TABLES = (
    "skill_versions",
    "skill_forks",
    "skill_files",
    "skill_checks",
    "skill_check_agents",
    "skill_improvement_runs",
    "skill_improvement_iterations",
    "skill_merges",
    "skill_proposals",
    "spec_proposal_batches",
    "datasets",
)
_DELETED = {
    "skills",
    "skill_forks",
    "skill_versions",
    "skill_checks",
    "skill_proposals",
    "skill_improvement_runs",
    "skill_improvement_iterations",
    "spec_proposal_batches",
    "authoring_requests",
    "agents",
    "datasets",
}
"""The rows the skill epic's deletes remove; users and organizations are left aside."""


def _covered(table: Table, columns: list[str]) -> bool:
    """Whether an index leads with the key: with its own columns, the organization
    beside them or not, since a tenant-scoped key is always deleted with it."""
    wanted = set(columns) - {"organization_id"} or set(columns)
    leads = [list(index.columns.keys()) for index in table.indexes] + [
        list(constraint.columns.keys())
        for constraint in table.constraints
        if not isinstance(constraint, ForeignKeyConstraint)
    ]
    for lead in leads:
        prefix: set[str] = set()
        for column in lead:
            if column not in columns:
                break
            prefix.add(column)
        if wanted <= prefix:
            return True
    return False


@pytest.mark.parametrize("name", _TABLES)
def test_a_key_a_delete_reaches_is_indexed(name: str) -> None:
    table = Base.metadata.tables[name]
    unindexed = [
        constraint.column_keys
        for constraint in table.foreign_key_constraints
        if (constraint.ondelete or "").upper() in ("CASCADE", "SET NULL")
        and constraint.referred_table.name in _DELETED
        and not _covered(table, constraint.column_keys)
    ]
    assert unindexed == []
