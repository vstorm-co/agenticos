"""What the AI reviewer reports when it did not review, run as the workflow runs it.

#311: for eleven pull requests the reviewer died about twelve seconds into
`Review the diff` with `codex exited with code 1`, the job concluded `success`,
and the comment said "the reviewer did not produce a result" - a sentence that
reads like a verdict on the diff. A clean diff and a dead reviewer rendered
identically, so the outage was found by accident, three releases later.

The fix is a three-way classification in `Normalize the result` - `reviewed`,
`declined`, `broken` - which decides the heading on the comment and whether the
job fails. Nothing in CI would catch a regression in it: `actionlint` checks the
YAML and `zizmor` the permissions, and neither runs the script. So the step is
extracted from the workflow and executed here, the same way
`test_ai_review_config_guard.py` executes the configuration guard, rather than
asserted about in prose.

Extracting by step name rather than copying the script keeps one copy: rename
the step and this fails loudly instead of testing a stale fork of it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ai-review.yml"
NORMALIZE_STEP = "Normalize the result"
FAIL_STEP = "Fail when the reviewer did not review"
PUBLISH_STEP = "Post the findings"

# Resolved rather than named: the runner and a developer's machine disagree
# about whether bash is /bin or /usr/bin, and a partial path in a subprocess
# call is a finding of its own (ruff S607).
BASH = shutil.which("bash") or "/bin/bash"

# A run where everything worked. Each test names the one thing it changes.
HEALTHY = {
    "REVIEW_DIR": "",  # filled in per run
    "BASE_REF": "main",
    "CONFIG_STATUS": "ok",
    "CONFIG_PROBLEMS": "",
    "STANDARD_STATUS": "ok",
    "DIFF_STATUS": "ok",
    "CHANGED_LINES": "24",
    "MAX_CHANGED_LINES": "2000",
    "CODEX_OUTCOME": "success",
}

# What Codex writes on a run that worked, and the shape `publish` knows how to
# read. An empty findings list is the common answer on a correct pull request.
A_REAL_REVIEW = json.dumps(
    {"summary": "Adds a clock capability. Nothing blocks it.", "findings": []}
)


def workflow() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())
    return loaded


def step(job: str, name: str) -> dict[str, Any]:
    """One step of one job, read out of the workflow itself."""
    for candidate in workflow()["jobs"][job]["steps"]:
        if candidate.get("name") == name:
            found: dict[str, Any] = candidate
            return found
    raise AssertionError(f"No step named {name!r} in the {job!r} job of {WORKFLOW}")


def run_normalize(
    tmp_path: Path, *, codex_wrote: str | bytes | None = None, **overrides: str
) -> tuple[str, str]:
    """Run `Normalize the result` and return its `status` output and the summary it wrote.

    `codex_wrote` is the content of the result file as Codex left it, or None
    for the run where Codex left nothing at all. Bytes, for the run where what
    it left is not text.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    review_dir = tmp_path / "ai-review"
    review_dir.mkdir()
    if isinstance(codex_wrote, bytes):
        (review_dir / "findings.json").write_bytes(codex_wrote)
    elif codex_wrote is not None:
        (review_dir / "findings.json").write_text(codex_wrote)

    output = tmp_path / "github_output"
    output.touch()
    script = tmp_path / "normalize.sh"
    script.write_text(str(step("review", NORMALIZE_STEP)["run"]))

    result = subprocess.run(
        [BASH, str(script)],
        check=False,
        capture_output=True,
        text=True,
        env={
            **HEALTHY,
            "REVIEW_DIR": str(review_dir),
            **overrides,
            "GITHUB_OUTPUT": str(output),
            # The step shells out to `python3`; the interpreter running the
            # suite is the one this repository pins, so use its directory
            # rather than trusting whatever /usr/bin holds.
            "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
        },
    )
    assert result.returncode == 0, f"the step itself failed: {result.stderr}"

    written = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line)
    findings = json.loads((review_dir / "findings.json").read_text())
    summary: str = findings["summary"]
    return written.get("status", ""), summary


def test_a_review_that_happened_is_reviewed_and_is_left_alone(tmp_path: Path) -> None:
    """The normalizer must not rewrite a real review, only classify it."""
    status, summary = run_normalize(tmp_path, codex_wrote=A_REAL_REVIEW)
    assert status == "reviewed"
    assert summary == "Adds a clock capability. Nothing blocks it."


def test_a_failed_codex_step_is_broken_and_says_nothing_was_reviewed(tmp_path: Path) -> None:
    """The #311 regression.

    Before this, the only signal was a missing result file, which rendered as
    "the reviewer did not produce a result" - indistinguishable from a clean
    diff to anybody skimming, and the job concluded `success` besides.
    """
    status, summary = run_normalize(tmp_path, CODEX_OUTCOME="failure")
    assert status == "broken"
    assert "The reviewer failed" in summary
    assert "Codex exited non-zero" in summary


def test_a_cancelled_run_is_declined_rather_than_broken(tmp_path: Path) -> None:
    """A superseded dispatch must not report the reviewer as dead.

    `cancel-in-progress` is on, so asking for a second review of one pull
    request cancels the first - and `Normalize the result` runs anyway, because
    `always()` covers cancellation. Calling that `broken` would put "the
    reviewer failed" on a pull request whose replacement run is in flight.
    """
    status, summary = run_normalize(tmp_path, CODEX_OUTCOME="cancelled")
    assert status == "declined"
    assert "cancelled" in summary


def test_a_step_failing_before_codex_does_not_blame_codex(tmp_path: Path) -> None:
    """`skipped` means something earlier failed, so the causes listed differ.

    Reporting "an expired key, a spend limit, a bad model slug" for a prompt
    that was never composed sends the reader to the wrong place.
    """
    status, summary = run_normalize(tmp_path, CODEX_OUTCOME="skipped")
    assert status == "broken"
    assert "Codex never ran" in summary
    assert "spend limit" not in summary


def test_a_codex_failure_outranks_the_file_it_left_behind(tmp_path: Path) -> None:
    """A crash mid-stream can leave a partial or stale result on disk.

    Reading it would report a review that did not finish - so the step's own
    outcome is checked before the file is trusted.
    """
    status, summary = run_normalize(tmp_path, codex_wrote=A_REAL_REVIEW, CODEX_OUTCOME="failure")
    assert status == "broken"
    assert "Adds a clock capability" not in summary


def test_codex_exiting_cleanly_with_no_result_is_broken(tmp_path: Path) -> None:
    status, summary = run_normalize(tmp_path)
    assert status == "broken"
    assert "wrote no result file" in summary


def test_output_that_is_not_the_review_schema_is_broken_and_carries_the_raw_output(
    tmp_path: Path,
) -> None:
    status, summary = run_normalize(tmp_path, codex_wrote='{"verdict": "looks fine"}')
    assert status == "broken"
    assert '{"verdict": "looks fine"}' in summary


@pytest.mark.parametrize("findings", ["null", '"none"', "{}"])
def test_findings_that_is_not_a_list_is_broken(tmp_path: Path, findings: str) -> None:
    """Present is not enough, and the difference is the whole point of #311.

    A key check passes `{"findings": null}`, `publish` then reads it through
    `Array.isArray(…) ? … : []`, and the comment claims the reviewer read the
    diff and had nothing to report - which it did not.
    """
    status, _ = run_normalize(tmp_path, codex_wrote=f'{{"summary": "x", "findings": {findings}}}')
    assert status == "broken"


def test_a_result_file_that_is_not_utf8_is_reported_rather_than_fatal(tmp_path: Path) -> None:
    """Decoding it outside the guard would fail the step and skip the upload.

    The pull request would then get no comment at all, for exactly the input
    "the reviewer returned something unreadable" is there to report.
    """
    status, summary = run_normalize(tmp_path, codex_wrote=b"\xff\xfe not json")
    assert status == "broken"
    assert "not the review schema" in summary


def test_a_misconfigured_reviewer_is_broken(tmp_path: Path) -> None:
    status, summary = run_normalize(
        tmp_path,
        CONFIG_STATUS="unconfigured",
        CONFIG_PROBLEMS="AI_REVIEW_MODEL is unset",
        STANDARD_STATUS="",
        DIFF_STATUS="",
        CODEX_OUTCOME="skipped",
    )
    assert status == "broken"
    assert "AI_REVIEW_MODEL is unset" in summary


def test_a_base_branch_with_no_prompt_is_broken(tmp_path: Path) -> None:
    status, summary = run_normalize(
        tmp_path, STANDARD_STATUS="no-standard", DIFF_STATUS="", CODEX_OUTCOME="skipped"
    )
    assert status == "broken"
    assert "review-prompt.md" in summary


@pytest.mark.parametrize(
    ("diff_status", "expected"),
    [
        ("empty", "changes nothing outside the excluded paths"),
        ("too-large", "over the 2000 line limit"),
    ],
)
def test_a_declined_diff_is_a_decision_rather_than_a_breakage(
    tmp_path: Path, diff_status: str, expected: str
) -> None:
    """`declined` exists so that these do not fail the job.

    Nothing to review and a diff over the cap are choices this workflow makes
    on purpose. Reporting them the same way as a dead reviewer would train
    everybody to ignore the red mark that matters.
    """
    status, summary = run_normalize(
        tmp_path, DIFF_STATUS=diff_status, CHANGED_LINES="9000", CODEX_OUTCOME="skipped"
    )
    assert status == "declined"
    assert expected in summary


def test_a_broken_run_has_a_step_whose_only_job_is_to_fail_it() -> None:
    """A red job is the whole of the second half of #311.

    The condition is asserted rather than the behaviour because GitHub, not
    bash, decides whether the step runs. It is not the only way this job can go
    red - any earlier step failing does it too, and then this one is skipped by
    the implicit `success()` - but it is the only one that catches a reviewer
    that produced nothing while every step reported fine.
    """
    failing = step("review", FAIL_STEP)
    assert failing["if"] == "steps.result.outputs.status == 'broken'"
    assert "exit 1" in failing["run"]

    steps = workflow()["jobs"]["review"]["steps"]
    assert steps[-1]["name"] == FAIL_STEP, (
        "the failing step has to be last: an earlier one would skip the steps that "
        "write and upload the comment explaining why"
    )


def test_publish_is_gated_on_the_reviewers_verdict_rather_than_its_job_result() -> None:
    """Otherwise failing the `review` job would silence the comment as well.

    That tension is exactly why `Review the diff` carries `continue-on-error`
    and why the job's failure is deferred to its last step.
    """
    condition = workflow()["jobs"]["publish"]["if"]
    assert "needs.review.outputs.status" in condition
    assert "needs.review.result" not in condition


def test_a_broken_run_says_the_comment_is_not_about_the_diff() -> None:
    """The sentence #311 was missing, and it is said in exactly one place.

    Each `broken` path writes its own explanation of what went wrong; the claim
    that none of it is a verdict on the code is uniform, so `publish` adds it
    once rather than every branch of the normalizer repeating it.
    """
    script = str(step("publish", PUBLISH_STEP)["with"]["script"])
    assert "Nothing here was reviewed" in script


def test_every_status_the_normalizer_writes_has_a_heading_in_the_comment(tmp_path: Path) -> None:
    """The two halves live in different jobs and in different languages.

    A fourth status added to the Python without a heading in the JavaScript
    renders as `## AI review — undefined` on somebody's pull request.
    """
    script = str(step("publish", PUBLISH_STEP)["with"]["script"])
    block = re.search(r"const heading = \{(.*?)\n\}", script, re.DOTALL)
    assert block, "the heading table moved; this test is now guarding nothing"
    headings = set(re.findall(r"^\s*(\w+):", block.group(1), re.MULTILINE))

    produced = {
        run_normalize(tmp_path / "reviewed", codex_wrote=A_REAL_REVIEW)[0],
        run_normalize(tmp_path / "declined", DIFF_STATUS="empty", CODEX_OUTCOME="skipped")[0],
        run_normalize(tmp_path / "broken", CODEX_OUTCOME="failure")[0],
    }
    assert produced == headings
