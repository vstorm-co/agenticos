"""The refusals a table operation can end in, each with its own code.

A client building on these (the public API, a workflow node) branches on `code`,
so every outcome the issue names has one: a revision conflict, an invalid value,
an archived column or table, a schema conflict, a reused idempotency key. The
messages are written for the person reading them; `details` carries the ids and
numbers a program needs and never a row or the caller's own values.
"""

from typing import Any
from uuid import UUID

from app.core.exceptions import AppException, ValidationError
from app.core.field_errors import field_details


class InvalidRecordError(ValidationError):
    """A value does not fit its column: wrong type, unknown column, null where forbidden (422)."""

    message = "The record does not match the table's schema"
    code = "INVALID_RECORD"

    def __init__(self, problems: list[tuple[str, str]]) -> None:
        fields = [{"field": field, "message": message} for field, message in problems]
        super().__init__(
            message="; ".join(f"{field}: {message}" for field, message in problems),
            details={"fields": fields},
        )


class ArchivedColumnError(ValidationError):
    """A write named a column that has been archived (422)."""

    message = "The column is archived and cannot be written"
    code = "ARCHIVED_COLUMN"

    def __init__(self, column_id: str) -> None:
        text = "This column is archived, so it can no longer be written"
        super().__init__(
            message=text, details=field_details(f"values.{column_id}", text, column_id=column_id)
        )


class InvalidQueryError(ValidationError):
    """A filter, sort or page parameter cannot be answered (422)."""

    message = "The query is not valid for this table"
    code = "INVALID_QUERY"

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message=message, details=field_details(field, message))


class InvalidSchemaError(ValidationError):
    """A schema change is inconsistent: duplicate labels, a bad default, a changed type (422)."""

    message = "The schema change is not valid"
    code = "INVALID_SCHEMA"

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message=message, details=field_details(field, message))


class RevisionConflictError(AppException):
    """The record changed since the caller read it (409). Nothing was written."""

    message = "The record was changed by someone else. Read it again and retry."
    code = "REVISION_CONFLICT"
    status_code = 409

    def __init__(self, *, record_id: UUID, expected_revision: int, current_revision: int) -> None:
        super().__init__(
            details={
                "record_id": record_id,
                "expected_revision": expected_revision,
                "current_revision": current_revision,
            }
        )


class RevisionRequiredError(AppException):
    """An upsert found the record but was not told which revision it is replacing (428)."""

    message = "The record already exists. Send expected_revision to update it."
    code = "REVISION_REQUIRED"
    status_code = 428

    def __init__(self, *, record_id: UUID, current_revision: int) -> None:
        super().__init__(
            details={"record_id": record_id, "current_revision": current_revision},
        )


class SchemaVersionConflictError(AppException):
    """The schema changed since the caller read it (409). Nothing was written."""

    message = "The table's schema was changed by someone else. Read it again and retry."
    code = "SCHEMA_VERSION_CONFLICT"
    status_code = 409

    def __init__(self, *, expected_version: int, current_version: int) -> None:
        super().__init__(
            details={"expected_version": expected_version, "current_version": current_version}
        )


class SchemaDependencyError(AppException):
    """Something still depends on what the change would remove (409)."""

    message = "Other resources depend on this and must be changed first"
    code = "SCHEMA_DEPENDENCY"
    status_code = 409

    def __init__(self, dependents: list[dict[str, Any]]) -> None:
        super().__init__(details={"dependents": dependents})


class TableArchivedError(AppException):
    """A write was attempted on an archived table (409)."""

    message = "The table is archived and cannot be written to"
    code = "TABLE_ARCHIVED"
    status_code = 409

    def __init__(self, *, table_id: UUID) -> None:
        super().__init__(details={"table_id": table_id})


class IdempotencyKeyReuseError(ValidationError):
    """An operation key was reused for a different request (422)."""

    message = "This operation key was already used for a different request"
    code = "IDEMPOTENCY_KEY_REUSED"

    def __init__(self, *, operation: str) -> None:
        super().__init__(details={"operation": operation})
