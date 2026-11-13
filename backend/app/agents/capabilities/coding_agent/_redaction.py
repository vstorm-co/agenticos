"""Personal grants are never part of a shared coding report or patch."""

from pydantic import JsonValue, TypeAdapter

from app.agents.capabilities.coding_agent._harness import CodingReport
from app.schemas.coding_task_change import ChangeSet

_JSON = TypeAdapter(JsonValue)


def redact_text(text: str, values: tuple[str, ...]) -> str:
    for value in values:
        if value:
            text = text.replace(value, "[redacted]")
    return text


def _redact(value: JsonValue, values: tuple[str, ...]) -> JsonValue:
    if isinstance(value, str):
        return redact_text(value, values)
    if isinstance(value, list):
        return [_redact(item, values) for item in value]
    if isinstance(value, dict):
        return {redact_text(key, values): _redact(item, values) for key, item in value.items()}
    return value


def redact_report(report: CodingReport, values: tuple[str, ...]) -> CodingReport:
    return CodingReport.model_validate(
        _redact(_JSON.validate_python(report.model_dump(mode="json")), values)
    )


def redact_changes(changes: ChangeSet, values: tuple[str, ...]) -> ChangeSet:
    files = []
    redacted = False
    for index, file in enumerate(changes.files):
        matched = (file.binary and bool(values)) or any(
            value
            and (
                value in file.path or value in (file.old_path or "") or value in (file.patch or "")
            )
            for value in values
        )
        if matched:
            files.append(
                file.model_copy(
                    update={
                        "path": f"redacted-{index}",
                        "old_path": None,
                        "patch": None,
                        "truncated": True,
                    }
                )
            )
            redacted = True
        else:
            files.append(file)
    return changes.model_copy(
        update={
            "files": files,
            "truncated": changes.truncated or redacted,
            "revert_patch": None if redacted else changes.revert_patch,
        }
    )
