"""`code.javascript.sandbox`: JavaScript on Node, with files, as a durable job on a sandbox host.

The same job as `code.python.sandbox` - launch once, check on every later
dispatch, collect what it left (`app.workflows.nodes._sandbox_job`) - with a
Node runner. The script is the body of an async function: it reads the bound
values as `args`, input files from the `inputs` folder, writes files to
`outputs`, may `await`, and what it `return`s is the step's `result`.
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

# What runs the script: the body of an async function over `args`, `inputs`,
# `outputs` and `require`, its return value read back as JSON, and a marker
# written however it ends, so a check can tell a finished job from a running
# one. `undefined` - a script that returns nothing - answers `null`.
RUNNER = """const fs = require("node:fs");
const path = require("node:path");
const root = __dirname;
const finish = (answer) => {
  fs.writeFileSync(path.join(root, "result.json"), JSON.stringify(answer));
  fs.writeFileSync(path.join(root, "done"), "done");
};
(async () => {
  let answer;
  try {
    const args = JSON.parse(fs.readFileSync(path.join(root, "args.json"), "utf8"));
    const source = fs.readFileSync(path.join(root, "main.js"), "utf8");
    const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
    const script = new AsyncFunction("args", "inputs", "outputs", "require", source);
    const value = await script(args, path.join(root, "inputs"), path.join(root, "outputs"), require);
    let encoded;
    try {
      encoded = value === undefined ? "null" : JSON.stringify(value);
    } catch {
      encoded = undefined;
    }
    answer = encoded === undefined
      ? { ok: false, not_json: true, error: typeof value }
      : { ok: true, result: JSON.parse(encoded) };
  } catch (error) {
    answer = { ok: false, error: error instanceof Error ? `${error.name}: ${error.message}` : String(error) };
  }
  finish(answer);
})();
"""

JAVASCRIPT = ScriptLanguage(
    code_prefix="JAVASCRIPT",
    script="main.js",
    runner_name="run.js",
    runner=RUNNER,
    interpreter="node",
)


class JavaScriptSandboxConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(
        min_length=1,
        max_length=200_000,
        json_schema_extra={
            "x-textarea": True,
            "x-placeholder": (
                'const fs = require("node:fs");\nreturn fs.readdirSync(inputs).length;'
            ),
        },
        description=(
            "The body of an async function: read the bound values as `args`, input files "
            "from the `inputs` folder, write files to `outputs`, and `return` the answer."
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
        description="The host's runtime to run in, one with Node. The connection's default when empty.",
    )


class JavaScriptSandboxInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    args: dict[str, Any] = Field(default_factory=dict)
    files: tuple[FileRef, ...] = Field(default=(), max_length=MAX_INPUT_FILES)


class JavaScriptSandboxOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    result: Any = None
    stdout_tail: str = Field(description="The end of what the script logged")
    log_file: FileRef = Field(description="Everything it logged, as a file")
    output_files: tuple[FileRef, ...] = ()


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a sandbox host the graph's author cannot use, or one that is not `sandboxd`."""
    if not isinstance(config, JavaScriptSandboxConfig):
        return []
    return await check_connection(db, ctx, config.connection_id)


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, JavaScriptSandboxConfig):
        return files.failed("JAVASCRIPT_NOT_CONFIGURED", "This step has no script")
    node_input = (
        node_input if isinstance(node_input, JavaScriptSandboxInput) else JavaScriptSandboxInput()
    )
    outcome = await run_job(
        JAVASCRIPT,
        code=config.code,
        timeout_seconds=config.timeout_seconds,
        connection_id=config.connection_id,
        runtime=config.runtime,
        args=node_input.args,
        input_files=node_input.files,
    )
    if not isinstance(outcome, JobResult):
        return outcome
    return Completed[JavaScriptSandboxOutput](
        output=JavaScriptSandboxOutput(
            result=outcome.result,
            stdout_tail=outcome.stdout_tail,
            log_file=outcome.log_file,
            output_files=outcome.output_files,
        )
    )
