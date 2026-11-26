"""Preserve stored cron cadences when upgrading croniter from 6 to 7.

croniter 6 expanded a step starting at a field's maximum over its whole range;
7 treats it as the maximum alone. Spell the old cadence explicitly before new
code reads it. Normalize the Unicode digits and separators 6 also accepted.
Every executable expression is checked with 7; an unrepresentable schedule refuses
the transaction and names its owning row, without exposing its contents.

Include frozen workflow definitions and test snapshots: restoring or publishing
one must not silently resurrect the old spelling under the new interpreter.
Unfinished drafts may remain invalid. Only schedule-node configuration changes;
version ids, inputs, run results,
timezones and next-fire instants are preserved. Stop API and workers first.

Downgrade spells 7's maximum-only steps as single values before 6 reads them.
Canonical expressions from upgrade work in both versions and stay canonical.
"""

from collections.abc import Sequence
from unicodedata import decimal

import sqlalchemy as sa
from croniter import CroniterBadDateError, croniter

from alembic import op

revision: str = "0376_croniter7_schedules"
down_revision: str | None = "0375_merge_service_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MAXIMA = ({"59"}, {"23"}, {"31"}, {"12", "dec"}, {"6", "sat"})


def _canonical(expression: str, *, upgrading: bool, validate: bool = True) -> str:
    normalized = "".join(str(decimal(char)) if char.isdecimal() else char for char in expression)
    fields = normalized.split()
    if len(fields) != 5:
        if not validate:
            return expression
        raise ValueError("Expected a five-field schedule")
    for index, field in enumerate(fields):
        terms = field.split(",")
        for position, term in enumerate(terms):
            start, separator, step = term.partition("/")
            lower = str(int(start)) if start.isascii() and start.isdecimal() else start.lower()
            if separator and lower in _MAXIMA[index] and step.isascii() and step.isdecimal():
                terms[position] = f"*/{step}" if upgrading else start
        fields[index] = ",".join(terms)
    result = " ".join(fields)
    if not validate:
        return result
    if not croniter.is_valid(result):
        raise ValueError("Schedule is not representable under croniter 7")
    try:
        croniter(result).get_next()
    except CroniterBadDateError as exc:
        raise ValueError("Schedule has no future occurrence") from exc
    return result


def _migrate(*, upgrading: bool) -> None:
    connection = op.get_bind()
    for table, column in (
        ("agent_triggers", "cron_expression"),
        ("workflow_exposures", "cron_expression"),
        ("eval_suites", "schedule_cron"),
    ):
        rows = connection.execute(
            sa.text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")
        )
        for row in rows:
            original = row[1]
            if not isinstance(original, str):
                raise TypeError(f"Invalid stored schedule in {table} row {row[0]}")
            try:
                converted = _canonical(original, upgrading=upgrading)
            except ValueError as exc:
                raise ValueError(
                    f"Repair the schedule in {table} row {row[0]} before upgrading"
                ) from exc
            if converted != original:
                connection.execute(
                    sa.text(f"UPDATE {table} SET {column} = :expression WHERE id = :id"),
                    {"id": row[0], "expression": converted},
                )
    for table, column in (
        ("workflows", "draft_graph"),
        ("workflow_versions", "graph"),
        ("workflow_runs", "draft_graph_snapshot"),
    ):
        rows = connection.execute(
            sa.text(
                f"SELECT source.id, node.ordinality - 1, node.value #>> '{{config,cron_expression}}' "
                f"FROM {table} AS source CROSS JOIN LATERAL "
                f"jsonb_array_elements(CASE WHEN jsonb_typeof({column}->'nodes') = 'array' "
                f"THEN {column}->'nodes' ELSE '[]'::jsonb END) WITH ORDINALITY AS node(value, ordinality) "
                "WHERE node.value->>'definition_id' = 'trigger.schedule' "
                "AND jsonb_typeof(node.value #> '{config,cron_expression}') = 'string'"
            )
        )
        for row in rows:
            original = row[2]
            if not isinstance(original, str):
                raise TypeError(f"Invalid stored schedule in {table} row {row[0]}")
            try:
                converted = _canonical(original, upgrading=upgrading, validate=table != "workflows")
            except ValueError as exc:
                raise ValueError(
                    f"Repair the schedule in {table} row {row[0]} before upgrading"
                ) from exc
            if converted != original:
                connection.execute(
                    sa.text(
                        f"UPDATE {table} SET {column} = jsonb_set({column}, "
                        "ARRAY['nodes', CAST(:index AS text), 'config', 'cron_expression'], "
                        "to_jsonb(CAST(:expression AS text)), false) WHERE id = :id"
                    ),
                    {"id": row[0], "index": row[1], "expression": converted},
                )


def upgrade() -> None:
    _migrate(upgrading=True)


def downgrade() -> None:
    _migrate(upgrading=False)
