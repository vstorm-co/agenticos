"""Bound model-visible results without truncating contracts or replaying writes.

Large reads expose a navigable result, not an incomplete JSON contract. Detail
reads execute the same authorized read again; nothing is cached across callers.
Large writes retain a receipt and never become failures because of output size.
"""

import base64
import hashlib
import hmac
import inspect
import json
import secrets
import time
from collections.abc import Awaitable, Callable, Sequence
from functools import wraps
from typing import Annotated, Literal, NoReturn
from urllib.parse import urlencode

from fastmcp.exceptions import ToolError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    validate_call,
)

from app.core.config import settings

type Operation = tuple[str, Callable[..., Awaitable[object]], bool]
Limit = Annotated[int, Field(ge=1, le=50)]
Skip = Annotated[int, Field(ge=0)]
Chars = Annotated[int, Field(ge=1, le=2000)]
MAX_RESPONSE_BYTES = 16 * 1024
_JSON = TypeAdapter(JsonValue)


def encoded(value: JsonValue) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def error_envelope(detail: dict[str, JsonValue]) -> str:
    """Keep normal API refusals intact; bound verbose validation/provider diagnostics."""
    original = encoded({"error": detail})
    if len(original.encode()) <= 8192:
        return original
    source = detail.get("details")
    fields: dict[str, JsonValue] = {}
    if isinstance(source, dict):
        for key, item in list(source.items())[:5]:
            if len(key) > 64:
                continue
            if len(encoded(item).encode()) <= 1000:
                fields[key] = item
            elif isinstance(item, list):
                previews = [metadata(row) for row in item[:3]]
                while previews and len(encoded(previews).encode()) > 1000:
                    previews.pop()
                fields[key] = {"items": previews, "total": len(item)}
    message = detail.get("message")
    return encoded(
        {
            "error": {
                "status": detail.get("status"),
                "code": str(detail.get("code", "ERROR"))[:100],
                "message": message[:1000]
                if isinstance(message, str)
                else "The request was refused",
                "details": fields,
                "details_omitted": True,
                "hint": "This is a failed request, not an empty result. Narrow the request or inspect its authoring schema. Do not bypass authorization or blindly repeat a write.",
            }
        }
    )


def fingerprint(value: JsonValue) -> str:
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def page(
    items: Sequence[JsonValue], *, limit: int = 10, skip: int = 0, q: str | None = None
) -> dict[str, JsonValue]:
    """Filter before paging an already authorized, unpaged collection."""
    if q:
        items = [item for item in items if q.casefold() in encoded(item).casefold()]
    end = skip + limit
    return {
        "items": list(items[skip:end]),
        "total": len(items),
        "next_skip": end if end < len(items) else None,
    }


def metadata(value: JsonValue) -> JsonValue:
    """Small identity/state receipt, not a claim that an asynchronous job finished."""
    if not isinstance(value, dict):
        if (
            value is None
            or isinstance(value, (bool, int, float))
            or (isinstance(value, str) and len(value) <= 200)
        ):
            return {"value": value}
        return {"type": type(value).__name__, "size_bytes": len(encoded(value).encode())}
    priority = (
        "id",
        "status",
        "run_id",
        "agent_id",
        "case_id",
        "dataset_id",
        "installation_key",
        "manifest_hash",
        "plan_id",
        "draft_revision",
        "revision",
    )
    ordered = [(key, value[key]) for key in priority if key in value]
    ordered += [(key, item) for key, item in value.items() if key not in priority]
    result: dict[str, JsonValue] = {
        key: item
        for key, item in ordered[:20]
        if len(key) <= 64
        and (
            (item is None or isinstance(item, (bool, int, float)))
            or (
                isinstance(item, str)
                and len(item) <= 200
                and key
                not in {"content", "instructions", "prompt", "input", "output", "answer", "excerpt"}
            )
        )
    }
    for key in (
        "used_by",
        "drafted_by",
        "resources",
        "forks",
        "agents",
        "history",
        "checks",
        "expected_tool_calls",
        "nodes",
        "bindings",
    ):
        item = value.get(key)
        if isinstance(item, list):
            result[key + "_count"] = len(item)
    while len(encoded(result).encode()) > 2500:
        result.popitem()
    return result


def listing(
    value: object,
    *,
    limit: int = 10,
    skip: int = 0,
    q: str | None = None,
    local: bool = False,
    detailed: bool = False,
) -> dict[str, JsonValue]:
    """Project list rows before disclosure; local paging is only for unpaged APIs."""
    parsed = _JSON.validate_python(value)
    if isinstance(parsed, list):
        items = parsed
        outer: dict[str, JsonValue] = {}
    elif isinstance(parsed, dict):
        candidate = parsed.get("items")
        if not isinstance(candidate, list):
            return parsed
        items = candidate
        outer = {key: item for key, item in parsed.items() if key != "items"}
    else:
        raise TypeError("A listing must be an object or an array")
    if local:
        # Search full authorized rows, but never return their bodies in discovery.
        filtered = [item for item in items if not q or q.casefold() in encoded(item).casefold()]
        return page(
            filtered if detailed else [metadata(item) for item in filtered], limit=limit, skip=skip
        )
    end = skip + len(items)
    total = outer.get("total")
    return {
        **outer,
        "items": items if detailed else [metadata(item) for item in items],
        "next_skip": end if isinstance(total, int) and end < total and items else None,
    }


def pointer(value: JsonValue, path: str) -> JsonValue:
    """RFC 6901 path; never a URL or an alternate authorization boundary."""
    if path == "":
        return value
    if not path.startswith("/"):
        raise ToolError("Use an empty pointer for the root or an RFC 6901 pointer starting with /.")
    for part in path[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isdecimal() and int(key) < len(value):
            value = value[int(key)]
        else:
            raise ToolError("Result path not found. Inspect the parent pointer first.")
    return value


def details(
    value: JsonValue,
    *,
    path: str = "",
    mode: Literal["inspect", "content"] = "inspect",
    skip: int = 0,
    limit: int = 10,
    offset: int = 0,
    chars: int = 2000,
    expected_hash: str | None = None,
    q: str | None = None,
) -> dict[str, JsonValue]:
    selected = pointer(value, path)
    digest = fingerprint(selected)
    if expected_hash is not None and expected_hash != digest:
        raise ToolError(
            "The selected value changed. Restart this read; do not combine different revisions."
        )
    base: dict[str, JsonValue] = {"pointer": path, "value_hash": digest}
    if mode == "content" or isinstance(selected, str):
        text = selected if isinstance(selected, str) else encoded(selected)
        end = offset + chars
        return {
            **base,
            "encoding": "text" if isinstance(selected, str) else "json-fragment",
            "content": text[offset:end],
            "total_chars": len(text),
            "next_offset": end if end < len(text) else None,
            "instruction": "Continue with value_hash as expected_hash. Assemble JSON fragments before parsing a contract.",
        }
    if isinstance(selected, (dict, list)):
        entries = (
            sorted(selected.items()) if isinstance(selected, dict) else list(enumerate(selected))
        )
        if q:
            entries = [
                (key, item)
                for key, item in entries
                if q.casefold() in (str(key) + " " + encoded(item)).casefold()
            ]
        rows: list[JsonValue] = [
            {
                "pointer": path + "/" + str(key).replace("~", "~0").replace("/", "~1"),
                "size_bytes": len(encoded(item).encode()),
                "summary": metadata(item),
            }
            for key, item in entries[skip : skip + limit]
        ]
        while len(encoded(rows).encode()) > 8000 and len(rows) > 1:
            rows.pop()
        return {
            **base,
            "items": rows,
            "total": len(entries),
            "next_skip": skip + len(rows) if skip + len(rows) < len(entries) else None,
        }
    return {**base, "value": selected}


class _Continuation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    operation: str
    arguments: dict[str, JsonValue]
    caller: str
    expires: int
    result_hash: str


def _mac(payload: bytes) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(), b"platform-mcp-read-v1:" + payload, hashlib.sha256
    ).hexdigest()


def _handle(name: str, arguments: dict[str, JsonValue], result: JsonValue, caller: str) -> str:
    payload = (
        _Continuation(
            operation=name,
            arguments=arguments,
            caller=caller,
            expires=int(time.time()) + 300,
            result_hash=fingerprint(result),
        )
        .model_dump_json()
        .encode()
    )
    return base64.urlsafe_b64encode(payload).decode() + "." + _mac(payload)


def _invalid_continuation() -> NoReturn:
    raise ToolError("Invalid or expired continuation. Execute the original authorized read again.")


def _open_handle(handle: str, caller: str | None) -> _Continuation:
    if len(handle) > 24000:
        _invalid_continuation()
    try:
        body, signature = handle.rsplit(".", 1)
        payload = base64.b64decode(body, altchars=b"-_", validate=True)
    except ValueError:
        _invalid_continuation()
    if not secrets.compare_digest(signature.encode(), _mac(payload).encode()):
        _invalid_continuation()
    try:
        ticket = _Continuation.model_validate_json(payload)
    except ValidationError:
        _invalid_continuation()
    if (
        caller is None
        or not secrets.compare_digest(ticket.caller, caller)
        or ticket.expires <= int(time.time())
    ):
        _invalid_continuation()
    return ticket


def protect[**P](
    name: str,
    function: Callable[P, Awaitable[object]],
    *,
    writes: bool,
    credential: Callable[[], str | None] = lambda: None,
) -> Callable[P, Awaitable[dict[str, JsonValue]]]:
    @wraps(function)
    async def bounded(*args: P.args, **kwargs: P.kwargs) -> dict[str, JsonValue]:
        result = _JSON.validate_python(await function(*args, **kwargs))
        if isinstance(result, dict) and len(encoded(result).encode()) <= MAX_RESPONSE_BYTES:
            return result
        receipt = metadata(result)
        # Preserve interactive state when it fits; an output allowance never
        # authorizes answering a person's questions or approving an action.
        if writes and isinstance(result, dict) and isinstance(receipt, dict):
            for key in ("workflow", "table", "agent", "record", "run"):
                child = result.get(key)
                if isinstance(child, dict):
                    receipt[key] = metadata(
                        {
                            field: child[field]
                            for field in ("id", "status", "draft_revision", "schema_version")
                            if field in child
                        }
                    )
            for key in ("parked", "questions", "next_actions"):
                item = result.get(key)
                if item is not None and len(encoded({**receipt, key: item}).encode()) <= 10000:
                    receipt[key] = item
                elif key == "parked" and isinstance(item, list):
                    receipt["parked"] = [
                        metadata(
                            {
                                field: call[field]
                                for field in ("id", "tool_name", "tool_call_id")
                                if field in call
                            }
                        )
                        for call in item[:10]
                        if isinstance(call, dict)
                    ]
                    receipt["parked_total"] = len(item)
                    receipt["approval_details_omitted"] = True
                    query = {"tab": "approvals"}
                    run_id = receipt.get("run_id")
                    if isinstance(run_id, str):
                        query["run"] = run_id
                    receipt["approval_review_url"] = (
                        settings.FRONTEND_URL.rstrip("/") + "/runs?" + urlencode(query)
                    )
                    receipt["approval_instruction"] = (
                        "Inspect the full pending calls in the console before deciding. Arguments and possibly additional approvals are omitted here; never approve from this summary."
                    )
        continuation: str | None = None
        if not writes and name != "read_platform_details":
            caller = credential()
            if caller is None:
                raise ToolError("An authenticated caller is required to continue this large read.")
            bound = inspect.signature(function).bind(*args, **kwargs)
            bound.apply_defaults()
            arguments = _JSON.validate_python(
                TypeAdapter(dict[str, object]).dump_python(dict(bound.arguments), mode="json")
            )
            if not isinstance(arguments, dict) or len(encoded(arguments).encode()) > 6000:
                raise ToolError(
                    "Read arguments exceed the continuation allowance. Narrow the original read."
                )
            continuation = _handle(name, arguments, result, caller)
        return {
            "continuation": continuation,
            "operation": name,
            "request_completed": True,
            "summary": receipt,
            "details_available": True,
            "instruction": (
                "The API request completed; inspect status before claiming its job succeeded. "
                "Read the saved resource with its detail tool. Do not repeat a write to retrieve its body."
                if writes
                else "If this is already a detail read, use mode=content on its parent pointer with the existing continuation. Otherwise pass continuation to read_platform_details. "
                "Inspect pointers, then read selected content; this is not a complete contract."
            ),
            "read_tool": ("get_solution_installation" if name == "install_solution" else None)
            if writes
            else "read_platform_details",
        }

    return bounded


def disclosure_operations(
    operations: tuple[Operation, ...], credential: Callable[[], str | None] = lambda: None
) -> tuple[Operation, ...]:
    reads = {name: validate_call(function) for name, function, writes in operations if not writes}

    async def read_platform_details(
        continuation: str,
        pointer: str = "",
        q: str | None = None,
        mode: Literal["inspect", "content"] = "inspect",
        skip: Skip = 0,
        limit: Limit = 10,
        offset: Skip = 0,
        chars: Chars = 2000,
        expected_hash: str | None = None,
    ) -> dict[str, JsonValue]:
        """Inspect or read a bounded part of an authorized platform read, never execute a write.

        Use only the continuation issued by an already authorized oversized read.
        It is bound to that exact call, credential and five-minute snapshot; it
        cannot invoke disabled tools or bypass their approval. inspect lists child JSON pointers;
        content returns text or explicitly labelled JSON fragments (assemble before
        parsing). Follow next_skip/next_offset and pass value_hash as expected_hash
        for subsequent fragments. Access is checked again on every call; changes
        are refused rather than mixing revisions. No result cache crosses callers.
        """
        ticket = _open_handle(continuation, credential())
        function = reads.get(ticket.operation)
        if function is None:
            raise ToolError("The original read is no longer available; authorize it again.")
        result = _JSON.validate_python(await function(**ticket.arguments))
        if fingerprint(result) != ticket.result_hash:
            raise ToolError(
                "The original read changed. Execute and authorize it again before reading fragments."
            )
        return details(
            result,
            path=pointer,
            q=q,
            mode=mode,
            skip=skip,
            limit=limit,
            offset=offset,
            chars=chars,
            expected_hash=expected_hash,
        )

    registered = ((read_platform_details, False),)
    return tuple((function.__name__, function, writes) for function, writes in registered)
