"""Code-execution tool backed by the Monty sandbox."""

import json
import logging
from typing import Any

from pydantic_monty import AsyncMonty, CollectString, MontyError, ResourceLimits

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 8000

# What one call may cost when the binding does not say. The agent's own
# capability config is the place to raise them - see `CodeExecutionConfig`.
DEFAULT_TIMEOUT_SECS = 10.0
DEFAULT_MAX_MEMORY_MB = 256


def _clip(text: str) -> str:
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + "\n…(output truncated)"
    return text


def _format_result(stdout: str, output: Any) -> str:
    parts: list[str] = []
    if stdout.strip():
        parts.append(f"stdout:\n{stdout.rstrip()}")
    if output is not None:
        try:
            rendered = json.dumps(output, default=str)
        except (TypeError, ValueError):
            rendered = str(output)
        parts.append(f"result: {rendered}")
    text = "\n\n".join(parts) if parts else "(code ran successfully with no output)"
    return _clip(text)


async def run_python(
    code: str,
    *,
    timeout_secs: float = DEFAULT_TIMEOUT_SECS,
    max_memory_mb: int = DEFAULT_MAX_MEMORY_MB,
) -> str:
    """Execute model-written Python in the Monty sandbox and return its output.

    Args:
        code: The Python source to run. A restricted stdlib subset (`math`,
            `asyncio`, `json`, `datetime`, `re`) works, but modules like
            `statistics`/`random`/`itertools` are unavailable.
        timeout_secs: Wall-clock budget for this one call.
        max_memory_mb: Memory cap for this one call.

    Returns:
        The captured stdout plus the value of the final expression, or an error
        message the model can read and recover from.
    """
    limits: ResourceLimits = {
        "max_duration_secs": timeout_secs,
        "max_memory": max_memory_mb * 1024 * 1024,
    }
    collector = CollectString()
    try:
        async with AsyncMonty() as monty, monty.checkout(limits=limits) as session:
            output = await session.feed_run(code, print_callback=collector)
    except MontyError as e:  # pragma: no cover - MontyError is Rust-backed and
        # cannot be constructed from Python, so this branch is unreachable from a
        # test. It exists to keep an expected sandbox failure (timeout, memory
        # cap) out of the error log, which the generic handler below would fill
        # with a stack trace for something that is not a bug.
        return _clip(f"Execution failed: {e}")
    except Exception as e:
        logger.exception("run_python execution failed")
        return _clip(f"Execution failed: {e}")

    return _format_result(collector.output, output)
