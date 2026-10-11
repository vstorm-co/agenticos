"""The Node runner `code.javascript.sandbox` stages, run by a real `node`.

The job protocol is proved against a stand-in host; this proves the runner
itself answers in the shape the protocol reads - the script's return value, its
throw, a value that is no JSON, and the marker written however it ended.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.workflows.nodes.code_javascript_sandbox._handler import RUNNER

NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="needs node on the PATH")


def _run(tmp_path: Path, code: str, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    (tmp_path / "inputs").mkdir()
    (tmp_path / "outputs").mkdir()
    (tmp_path / "inputs" / "00-a.txt").write_text("a")
    (tmp_path / "run.js").write_text(RUNNER)
    (tmp_path / "main.js").write_text(code)
    (tmp_path / "args.json").write_text(json.dumps(args))
    finished = subprocess.run(
        [str(NODE), "run.js"], cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False
    )
    assert (tmp_path / "done").read_text() == "done"
    return json.loads((tmp_path / "result.json").read_text()), finished.stdout


def test_the_returned_value_is_the_result_and_the_folders_are_the_job_s(tmp_path):
    answer, logged = _run(
        tmp_path,
        'const fs = require("node:fs");\n'
        'fs.writeFileSync(`${outputs}/out.txt`, "hi");\n'
        'console.log("counted");\n'
        "await new Promise((resolve) => setTimeout(resolve, 5));\n"
        "return { doubled: args.n * 2, inputs: fs.readdirSync(inputs) };",
        {"n": 21},
    )
    assert answer == {"ok": True, "result": {"doubled": 42, "inputs": ["00-a.txt"]}}
    assert logged == "counted\n"
    assert (tmp_path / "outputs" / "out.txt").read_text() == "hi"


@pytest.mark.parametrize(
    ("code", "answer"),
    [
        ("", {"ok": True, "result": None}),
        ('throw new TypeError("bad input");', {"ok": False, "error": "TypeError: bad input"}),
        ('throw "plain";', {"ok": False, "error": "plain"}),
        ("return 10n;", {"ok": False, "not_json": True, "error": "bigint"}),
        ("return () => 1;", {"ok": False, "not_json": True, "error": "function"}),
    ],
    ids=["nothing-returned", "a-throw", "a-thrown-string", "bigint", "function"],
)
def test_every_ending_answers_in_the_shape_the_job_reads(tmp_path, code, answer):
    assert _run(tmp_path, code, {})[0] == answer


def test_a_script_that_does_not_parse_fails_as_a_syntax_error(tmp_path):
    # The wording is Node's own and moves between versions; the kind does not.
    answer, _logged = _run(tmp_path, "return {", {})
    assert answer["ok"] is False and answer["error"].startswith("SyntaxError: ")
