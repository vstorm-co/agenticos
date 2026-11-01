"""Each refusal a table operation can end in has its own status, code and typed details."""

import uuid

from app.services.virtual_tables.exceptions import (
    ArchivedColumnError,
    IdempotencyKeyReuseError,
    InvalidQueryError,
    InvalidRecordError,
    InvalidSchemaError,
    RevisionConflictError,
    RevisionRequiredError,
    SchemaDependencyError,
    SchemaVersionConflictError,
    TableArchivedError,
)


def test_a_revision_conflict_names_both_revisions_and_no_values():
    record_id = uuid.uuid4()
    error = RevisionConflictError(record_id=record_id, expected_revision=2, current_revision=5)
    assert (error.status_code, error.code) == (409, "REVISION_CONFLICT")
    assert error.details == {
        "record_id": record_id,
        "expected_revision": 2,
        "current_revision": 5,
    }


def test_a_missing_precondition_is_a_428_that_carries_the_revision_to_send():
    record_id = uuid.uuid4()
    error = RevisionRequiredError(record_id=record_id, current_revision=3)
    assert (error.status_code, error.code) == (428, "REVISION_REQUIRED")
    assert error.details == {"record_id": record_id, "current_revision": 3}


def test_invalid_values_are_reported_per_field():
    error = InvalidRecordError([("values.a", "Expected text"), ("values.b", "Unknown column")])
    assert (error.status_code, error.code) == (422, "INVALID_RECORD")
    assert error.details == {
        "fields": [
            {"field": "values.a", "message": "Expected text"},
            {"field": "values.b", "message": "Unknown column"},
        ]
    }


def test_an_archived_column_names_the_column_it_refused():
    error = ArchivedColumnError("abc")
    assert (error.status_code, error.code) == (422, "ARCHIVED_COLUMN")
    assert error.details is not None
    assert error.details["fields"][0]["field"] == "values.abc"
    assert error.details["column_id"] == "abc"


def test_query_and_schema_problems_name_their_field():
    query = InvalidQueryError("sort.by", "Unknown column")
    schema = InvalidSchemaError("columns.0.label", "Duplicate label")
    assert (query.status_code, query.code) == (422, "INVALID_QUERY")
    assert (schema.status_code, schema.code) == (422, "INVALID_SCHEMA")
    assert query.details == {"fields": [{"field": "sort.by", "message": "Unknown column"}]}
    assert schema.details == {
        "fields": [{"field": "columns.0.label", "message": "Duplicate label"}]
    }


def test_the_remaining_refusals_have_distinct_codes():
    table_id = uuid.uuid4()
    conflict = SchemaVersionConflictError(expected_version=1, current_version=2)
    dependency = SchemaDependencyError([{"kind": "view", "id": table_id}])
    archived = TableArchivedError(table_id=table_id)
    reused = IdempotencyKeyReuseError(operation="record.create")
    assert (conflict.status_code, conflict.code) == (409, "SCHEMA_VERSION_CONFLICT")
    assert conflict.details == {"expected_version": 1, "current_version": 2}
    assert (dependency.status_code, dependency.code) == (409, "SCHEMA_DEPENDENCY")
    assert dependency.details == {"dependents": [{"kind": "view", "id": table_id}]}
    assert (archived.status_code, archived.code) == (409, "TABLE_ARCHIVED")
    assert (reused.status_code, reused.code) == (422, "IDEMPOTENCY_KEY_REUSED")
    assert reused.details == {"operation": "record.create"}
