"""`code.python.sandbox`: full Python with files, as a durable job on a sandbox host.

For a script Monty cannot run - one that needs packages or reads the run's
files. The job protocol - launch once, check on every later dispatch, collect
what it left - is `app.workflows.nodes._sandbox_job`'s; this step names the
runner that executes the script and reads `result` back as JSON.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._sandbox_job import (
    MAX_INPUT_FILES,
    JobResult,
    ScriptLanguage,
    check_connection,
    run_job,
)

# What runs the script: its arguments and file folders as globals, `result`
# read back as JSON, and a marker written however it ends, so a check can tell
# a finished job from a running one.
RUNNER = """import json, pathlib
root = pathlib.Path(__file__).parent
scope = {
    "args": json.loads((root / "args.json").read_text()),
    "inputs": str(root / "inputs"),
    "outputs": str(root / "outputs"),
}
try:
    exec(compile((root / "main.py").read_text(), "main.py", "exec"), scope)
    value = scope.get("result")
    try:
        answer = {"ok": True, "result": json.loads(json.dumps(value, allow_nan=False))}
    except (TypeError, ValueError):
        answer = {"ok": False, "not_json": True, "error": type(value).__name__}
except BaseException as exc:
    answer = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
(root / "result.json").write_text(json.dumps(answer))
(root / "done").write_text("done")
"""

PYTHON = ScriptLanguage(
    code_prefix="PYTHON",
    script="main.py",
    runner_name="run.py",
    runner=RUNNER,
    interpreter="python3",
)


class PythonSandboxConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(
        min_length=1,
        max_length=200_000,
        json_schema_extra={
            "x-textarea": True,
            "x-placeholder": "import csv, os\nresult = len(os.listdir(inputs))",
        },
        description=(
            "Read the bound values as `args`, input files from the `inputs` folder, and "
            "write files to `outputs`. Set `result` to the answer."
        ),
    )
    timeout_seconds: float = Field(default=300.0, gt=0, le=1800, title="Time limit (seconds)")
    connection_id: UUID | None = Field(
        default=None,
        title="Sandbox host",
        description="The sandbox host to run on. The organization's default when empty.",
        json_schema_extra={"x-resource": "sandbox_connection"},
    )
    runtime: str | None = Field(
        default=None,
        max_length=64,
        title="Runtime",
        description="The host's runtime to run in. The connection's default when empty.",
    )


class PythonSandboxInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    args: dict[str, Any] = Field(default_factory=dict)
    files: tuple[FileRef, ...] = Field(default=(), max_length=MAX_INPUT_FILES)


class PythonSandboxOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    result: Any = None
    stdout_tail: str = Field(description="The end of what the script printed")
    log_file: FileRef = Field(description="Everything it printed, as a file")
    output_files: tuple[FileRef, ...] = ()


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a sandbox host the graph's author cannot use, or one that is not `sandboxd`."""
    if not isinstance(config, PythonSandboxConfig):
        return []
    return await check_connection(db, ctx, config.connection_id)


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, PythonSandboxConfig):
        return files.failed("PYTHON_NOT_CONFIGURED", "This step has no script")
    node_input = node_input if isinstance(node_input, PythonSandboxInput) else PythonSandboxInput()
    outcome = await run_job(
        PYTHON,
        code=config.code,
        timeout_seconds=config.timeout_seconds,
        connection_id=config.connection_id,
        runtime=config.runtime,
        args=node_input.args,
        input_files=node_input.files,
    )
    if not isinstance(outcome, JobResult):
        return outcome
    return Completed[PythonSandboxOutput](
        output=PythonSandboxOutput(
            result=outcome.result,
            stdout_tail=outcome.stdout_tail,
            log_file=outcome.log_file,
            output_files=outcome.output_files,
        )
    )
