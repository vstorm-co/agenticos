"""Redact secrets in retained eval answers and tool-call evidence.

Use the same harness detector as Review, keeping this traversal local to the
revision so future application refactors cannot break historical upgrades.
Reads are streamed and only changed rows are written. Redaction is idempotent;
downgrade cannot and must not restore the secrets removed here.

Revision ID: 0191_eval_evidence_redaction
Revises: 0190_case_generation_api_key
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pydantic import JsonValue, TypeAdapter
from pydantic_ai_harness.guardrails.detectors import redact_secrets
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0191_eval_evidence_redaction"
down_revision: str | None = "0190_case_generation_api_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = TypeAdapter(JsonValue)


def _redact(value: JsonValue) -> JsonValue:
    if isinstance(value, str):
        verdict = redact_secrets(value)
        if verdict.action == "replace" and isinstance(verdict.replacement, str):
            return verdict.replacement
        return value
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    return value


def upgrade() -> None:
    evidence = sa.table(
        "eval_run_cases",
        sa.column("id", sa.Uuid()),
        sa.column("answer", sa.Text()),
        sa.column("calls", JSONB()),
        sa.column("error", sa.Text()),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(evidence).execution_options(stream_results=True, yield_per=200)
    ).mappings()
    for batch in rows.partitions(200):
        for row in batch:
            changed = {
                field: redacted
                for field in ("answer", "calls", "error")
                if (redacted := _redact(_JSON.validate_python(row[field]))) != row[field]
            }
            if changed:
                connection.execute(
                    evidence.update().where(evidence.c.id == row["id"]).values(**changed)
                )


def downgrade() -> None:
    pass
