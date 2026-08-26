"""Code-execution tool backed by the Monty sandbox."""

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic_monty import (
    AsyncMonty,
    CollectString,
    MontyConversionError,
    MontyError,
    MontyRuntimeError,
    MontySyntaxError,
    MontyTypingError,
    ResourceLimits,
)

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 8000

# What one call may cost when the binding does not say. The agent's own
# capability config is the place to raise them - see `CodeExecutionConfig`.
DEFAULT_TIMEOUT_SECS = 10.0
DEFAULT_MAX_MEMORY_MB = 256


MODEL_ERRORS = (MontySyntaxError, MontyRuntimeError, MontyTypingError, MontyConversionError)
"""Failures that are the program's, and so the model's to fix.

A `NameError`, a syntax error, a value the sandbox could not hand back - the
`code` argument is what the model composed, so these are malformed arguments
rather than results. `MontyRuntimeError` also carries the resource limits, which
report as `TimeoutError` and `MemoryError` and are fixable the same way: by
writing something cheaper.

What is left - `MontyCrashedError`, `MontyDisconnectError`, anything else - is
the sandbox itself failing, which no rewrite of the code addresses.
"""


@dataclass(frozen=True)
class RunOutcome:
    """What one `run_python` call produced, and whose problem a failure is."""

    text: str
    """Output, or the failure, as the model should read it."""

    fixable: bool = False
    """Whether a different `code` argument is a plausible fix.

    Read by the toolset, which turns it into a retry prompt rather than an
    answer. Decided here rather than there because which exception means what is
    the sandbox's knowledge, not the prompt layer's.
    """


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
) -> RunOutcome:
    """Execute model-written Python in the Monty sandbox and return its output.

    Args:
        code: The Python source to run. A restricted stdlib subset (`math`,
            `asyncio`, `json`, `datetime`, `re`) works, but modules like
            `statistics`/`random`/`itertools` are unavailable.
        timeout_secs: Wall-clock budget for this one call.
        max_memory_mb: Memory cap for this one call.

    Returns:
        The captured stdout plus the value of the final expression, or the
        failure - with `fixable` saying whether the program was the problem.
    """
    limits: ResourceLimits = {
        "max_duration_secs": timeout_secs,
        "max_memory": max_memory_mb * 1024 * 1024,
    }
    collector = CollectString()
    try:
        async with AsyncMonty() as monty, monty.checkout(limits=limits) as session:
            output = await session.feed_run(code, print_callback=collector)
    except MODEL_ERRORS as e:
        # Not logged: a `NameError` in code the model wrote is not a defect in
        # this deployment, and an error log full of them hides the ones that are.
        return RunOutcome(_clip(f"Execution failed: {e}"), fixable=True)
    except MontyError as e:  # pragma: no cover - what is left is the sandbox
        # process dying, which cannot be provoked from a test.
        logger.exception("run_python sandbox failed")
        return RunOutcome(_clip(f"Execution failed: {e}"))
    except Exception as e:
        logger.exception("run_python execution failed")
        return RunOutcome(_clip(f"Execution failed: {e}"))

    return RunOutcome(_format_result(collector.output, output))
