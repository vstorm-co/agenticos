"""Serialization tests for the workflow contracts: results, IO refs, bindings.

AC4 of #1786: contract serialization tests cover nested bindings, errors,
`FileRef` and per-table dynamic IO.
"""

from uuid import uuid4

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.workflows.contracts.io import (
    Binding,
    FileRef,
    LiteralValue,
    NodeOutputRef,
    TableIORef,
)
from app.workflows.contracts.results import (
    Completed,
    Failed,
    NodeResult,
    Uncertain,
    Waiting,
    WorkflowError,
)

_RESULT_ADAPTER: TypeAdapter[object] = TypeAdapter(NodeResult)


class _Echo(BaseModel):
    echoed: str


def test_completed_round_trips_through_the_discriminated_union():
    result = Completed[_Echo](output=_Echo(echoed="hi"))
    dumped = result.model_dump(mode="json")
    restored = _RESULT_ADAPTER.validate_python(dumped)
    assert isinstance(restored, Completed)
    assert restored.status == "completed"
    assert restored.output == {"echoed": "hi"}


def test_waiting_round_trips_and_names_its_reason():
    result = Waiting(reason="approval", resume_token="tok-1")
    restored = _RESULT_ADAPTER.validate_python(result.model_dump(mode="json"))
    assert isinstance(restored, Waiting)
    assert restored.reason == "approval"
    assert restored.resume_token == "tok-1"


def test_failed_carries_a_typed_error_with_details():
    error = WorkflowError(code="TIMEOUT", message="Upstream timed out", details={"seconds": 30})
    result = Failed(error=error)
    restored = _RESULT_ADAPTER.validate_python(result.model_dump(mode="json"))
    assert isinstance(restored, Failed)
    assert restored.error.code == "TIMEOUT"
    assert restored.error.details == {"seconds": 30}
    assert restored.error.retryable is False


def test_uncertain_round_trips():
    result = Uncertain(detail="webhook timed out; outcome unknown")
    restored = _RESULT_ADAPTER.validate_python(result.model_dump(mode="json"))
    assert isinstance(restored, Uncertain)
    assert restored.detail == "webhook timed out; outcome unknown"


def test_workflow_error_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        WorkflowError.model_validate({"code": "X", "message": "m", "extra_field": "nope"})


def test_file_ref_rejects_an_extra_field():
    with pytest.raises(ValidationError):
        FileRef.model_validate(
            {
                "file_id": str(uuid4()),
                "content_type": "text/plain",
                "byte_size": 10,
                "storage_backend": "s3",
            }
        )


def test_file_ref_rejects_a_negative_byte_size():
    with pytest.raises(ValidationError):
        FileRef.model_validate(
            {"file_id": str(uuid4()), "content_type": "text/plain", "byte_size": -1}
        )


def test_file_ref_round_trips():
    ref = FileRef(file_id=uuid4(), content_type="application/pdf", byte_size=1024)
    restored = FileRef.model_validate(ref.model_dump(mode="json"))
    assert restored == ref


def test_table_io_ref_with_no_columns_means_all_live_columns():
    ref = TableIORef(table_id=uuid4(), column_ids=None, schema_version=3)
    restored = TableIORef.model_validate(ref.model_dump(mode="json"))
    assert restored.column_ids is None
    assert restored.schema_version == 3


def test_table_io_ref_with_explicit_columns_round_trips():
    columns = (uuid4(), uuid4())
    ref = TableIORef(table_id=uuid4(), column_ids=columns, schema_version=1)
    restored = TableIORef.model_validate(ref.model_dump(mode="json"))
    assert restored.column_ids == columns


@pytest.mark.parametrize(
    "source",
    [
        LiteralValue(value="hello"),
        LiteralValue(value=42),
        NodeOutputRef(node_id=uuid4(), port="out"),
        NodeOutputRef(node_id=uuid4(), port="out", field_path=("text",)),
        FileRef(file_id=uuid4(), content_type="text/csv", byte_size=0),
        TableIORef(table_id=uuid4(), schema_version=1),
    ],
)
def test_a_binding_round_trips_each_source_variant(source: object):
    binding = Binding(target_node_id=uuid4(), target_field="prompt", source=source)
    restored = Binding.model_validate(binding.model_dump(mode="json"))
    assert restored == binding


def test_node_output_ref_field_path_defaults_to_whole_port():
    ref = NodeOutputRef(node_id=uuid4(), port="out")
    assert ref.field_path == ()


def test_node_output_ref_field_path_walks_a_nested_field():
    ref = NodeOutputRef(node_id=uuid4(), port="out", field_path=("text",))
    restored = NodeOutputRef.model_validate(ref.model_dump(mode="json"))
    assert restored.field_path == ("text",)
