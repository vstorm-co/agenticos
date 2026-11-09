"""The bounded JSON protocol of the isolated trigger-input validator."""

import json
import sys
from typing import BinaryIO, TypedDict, cast

from pydantic import JsonValue

MAX_REQUEST_BYTES = 1_048_576
MAX_RESPONSE_BYTES = 262_144


class ValidationRequest(TypedDict):
    schema: dict[str, JsonValue]
    input: dict[str, JsonValue]


def validation_limit() -> list[dict[str, str]]:
    """A controlled refusal when evaluating the contract exceeds its allowance."""
    return [
        {
            "field": "",
            "message": "Input validation exceeded its resource limit; simplify the input or contract",
            "type": "validation_limit",
        }
    ]


_RESOURCE_LIMIT_RESPONSE = json.dumps(validation_limit()).encode()


def main(stdin: BinaryIO, stdout: BinaryIO) -> None:
    """Validate the parent's JSON request without emitting submitted values."""
    try:
        from app.workflows.contracts.input_schema import check_input_schema, schema_input_problems

        request_bytes = stdin.read(MAX_REQUEST_BYTES + 1)
        if len(request_bytes) > MAX_REQUEST_BYTES:
            problems = validation_limit()
        else:
            # Only the trusted parent writes this protocol. JSON values remain JSON
            # values, including deep input the validator will refuse with a field error.
            request = cast(ValidationRequest, json.loads(request_bytes))
            check_input_schema(request["schema"])
            problems = schema_input_problems(request["schema"], request["input"])
        response = json.dumps(problems, ensure_ascii=False, separators=(",", ":")).encode()
        if len(response) > MAX_RESPONSE_BYTES:
            response = _RESOURCE_LIMIT_RESPONSE
    except MemoryError:
        # Allocate the refusal before validation, when the child still has room.
        response = _RESOURCE_LIMIT_RESPONSE
    stdout.write(response)


if __name__ == "__main__":  # pragma: no cover - exercised through the child-process adapter
    main(sys.stdin.buffer, sys.stdout.buffer)
