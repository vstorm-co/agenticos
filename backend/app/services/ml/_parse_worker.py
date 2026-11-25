"""One-shot, resource-limited worker for synchronous ML document parsing.

The parent starts this file with isolated Python path handling, passes a trusted
`RAGSettings` JSON document on stdin, and reads one JSON result from stdout.
CPU and address-space limits are installed before importing the application or
any native parser. A host that cannot install either limit refuses to parse
rather than silently starting an unbounded child.
"""

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path
from typing import BinaryIO

_REQUEST_MAX_BYTES = 1024 * 1024


def _bounded_positive(argv: list[str], index: int) -> int:
    try:
        value = int(argv[index])
    except IndexError, ValueError:
        raise RuntimeError("The parser worker did not receive its resource limits") from None
    if value <= 0:
        raise RuntimeError("The parser worker received an invalid resource limit")
    return value


def _apply_limits(cpu_seconds: int, memory_bytes: int) -> None:
    """Install hard CPU/address-space ceilings before loading parser code."""
    try:
        import resource
    except ImportError:
        raise RuntimeError("This host cannot isolate parser resources") from None

    for resource_kind, requested in (
        (resource.RLIMIT_CPU, cpu_seconds),
        (resource.RLIMIT_AS, memory_bytes),
    ):
        _, hard = resource.getrlimit(resource_kind)
        ceiling = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
        try:
            resource.setrlimit(resource_kind, (ceiling, ceiling))
        except ValueError, OSError:
            raise RuntimeError("This host could not install a parser resource limit") from None


def _request(stdin: BinaryIO) -> bytes:
    payload = stdin.read(_REQUEST_MAX_BYTES + 1)
    if not payload or len(payload) > _REQUEST_MAX_BYTES:
        raise ValueError("The parser worker request is missing or oversized")
    return payload


def _error(kind: str, **details: str | int | float) -> bytes:
    return json.dumps({"ok": False, "kind": kind, **details}).encode("utf-8")


def _run(argv: list[str], stdin: BinaryIO) -> bytes:
    cpu_seconds = _bounded_positive(argv, 1)
    memory_bytes = _bounded_positive(argv, 2)
    _apply_limits(cpu_seconds, memory_bytes)

    # `-I` excludes the checkout from sys.path. Add only the backend root
    # resolved from this trusted file, after the resource limits are active.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

    from app.core.office_convert import use_parent_process_group
    from app.services.rag.config import RAGSettings
    from app.services.rag.documents import DocumentLimitExceeded, DocumentProcessor

    try:
        path = Path(argv[3])
        settings = RAGSettings.model_validate_json(_request(stdin))
        with use_parent_process_group():
            document = asyncio.run(DocumentProcessor(settings).process_file(path))
    except DocumentLimitExceeded as exc:
        return _error("limit", budget=exc.budget, maximum=exc.maximum)
    except ValueError:
        return _error("value_error")
    except RuntimeError:
        traceback.print_exc(file=sys.stderr)
        return _error("runtime_error")
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return _error("bad_document")

    # Chunk models keep their page's full text for vector metadata by reference
    # in-process. Across JSON that reference would become one copy per chunk,
    # multiplying the protocol response despite the dedicated chunk-content cap.
    for chunk in document.chunked_pages or []:
        chunk.content = ""
        chunk.images.clear()
    document.metadata.additional_info = None
    serialized = document.model_dump_json().encode("utf-8")
    return b'{"ok":true,"document":' + serialized + b"}"


def main(argv: list[str], stdin: BinaryIO, stdout: BinaryIO) -> int:
    """Write one controlled protocol result, or exit nonzero before parsing."""
    try:
        result = _run(argv, stdin)
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 1
    stdout.write(result)
    stdout.flush()
    return 0


if __name__ == "__main__":
    # Native libraries can write directly to fd 1, bypassing Python redirects.
    # Reserve its original pipe for the protocol before importing any parser.
    with os.fdopen(os.dup(sys.stdout.fileno()), "wb") as protocol:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        sys.stdout = sys.stderr
        raise SystemExit(main(sys.argv, sys.stdin.buffer, protocol))
