"""What every table tool does before and after the service: who, which table, which cells.

A tool's arguments are the model's and so untrusted; everything that decides
what the model may reach is resolved here from what it cannot write.

- **Who.** The member the run acts for, rebuilt from their *current* membership
  on every call - `AgentDeps` carries only the organization and user ids, and a
  role narrowed, or a membership removed, while a run waits hours on an approval
  must stop the next call rather than riding the role the run started with.
- **Which table.** The binding's grants, frozen in the spec: a table id the model
  names that is not granted, or an operation the grant does not include, is
  refused before the service runs. The service's own access check still runs on
  every call - the grant narrows, it never grants.
- **Which cells.** The model may key values by column id or by column label; a
  label is mapped to its id against the table's live schema, and one that names
  nothing is the model's mistake to correct.

Refusals come back as text the model reasons about; a malformed call steers it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.repositories import member as member_repo
from app.repositories import user as user_repo
from app.schemas.virtual_table import TableRead
from app.services.virtual_tables.presentation import UnknownColumnError, column_keyed


class TableOperation(StrEnum):
    """What a grant lets an agent do with one table."""

    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class Refused(Exception):
    """A call the grant, the membership or the table refuses - said to the model as text."""


class Mistake(Exception):
    """A call the model composed wrongly - steered, so it can send it again corrected."""


async def acting_as(
    db: AsyncSession, organization_id: UUID | None, user_id: str | None
) -> AuthContext:
    """The member this run acts for, with the role they hold now.

    Raises:
        Refused: The run has no member behind it, or they are no longer an
            active member of the organization.
    """
    if organization_id is None or user_id is None:
        raise Refused("Tables can only be used by a run acting for a member of an organization.")
    try:
        member_id = UUID(user_id)
    except ValueError:
        raise Refused("Tables can only be used by a run acting for a member.") from None
    member = await member_repo.get_active(db, organization_id=organization_id, user_id=member_id)
    user = await user_repo.get_by_id(db, member_id) if member is not None else None
    if member is None or user is None:
        raise Refused("The member this agent acts for is no longer in the organization.")
    return AuthContext(
        user_id=member_id,
        organization_id=organization_id,
        role=member.role,
        is_app_admin=user.is_app_admin,
    )


def require(
    grants: Mapping[UUID, frozenset[TableOperation]],
    table_id: UUID,
    *operations: TableOperation,
) -> None:
    """Refuse a table this binding does not grant, or an operation it does not include."""
    granted = grants.get(table_id)
    if granted is None:
        raise Refused(
            f"This agent has no access to table {table_id}. Call list_tables to see the "
            "tables it may use."
        )
    missing = [operation.value for operation in operations if operation not in granted]
    if missing:
        raise Refused(
            f"This agent may not {' or '.join(missing)} records in table {table_id}; "
            f"it may {', '.join(sorted(op.value for op in granted))}."
        )


def cell_values(table: TableRead, values: Mapping[str, Any]) -> dict[str, Any]:
    """`values` keyed by column id, whether the model used ids or labels.

    Raises:
        Mistake: A key names no live column, or a label names more than one.
    """
    try:
        return column_keyed(table, values)
    except UnknownColumnError as unknown:
        raise Mistake(str(unknown)) from None


def refusal_text(exc: AppException) -> str:
    """A domain refusal, as a sentence the model can act on."""
    hint = {
        "REVISION_CONFLICT": " Read the record again and retry with its current revision.",
        "REVISION_REQUIRED": " Read the record first and send its revision.",
        "NOT_FOUND": " Check the id with list_records or get_record.",
    }.get(exc.code, "")
    return f"Refused ({exc.code}): {exc.message}.{hint}"


def is_mistake(exc: AppException) -> bool:
    """Whether a refusal is about the arguments, which the model can correct and resend."""
    return exc.code in {"INVALID_RECORD", "INVALID_QUERY", "VALIDATION_ERROR", "INVALID_SCHEMA"}


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
