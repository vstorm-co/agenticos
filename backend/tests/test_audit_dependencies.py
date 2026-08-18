"""What `make audit` may and may not conclude from a pip-audit run.

`Security Scan` is a required check, and pip-audit exits 1 both when a locked
dependency is vulnerable and when it never reached the feed at all — a
`ReadTimeout` on one of 254 requests looked exactly like an advisory on #838,
and a re-run of the same commit passed unchanged (#855).

`scripts/audit_dependencies.py` is what keeps those two apart, so the tests here
are about the distinction rather than about pip-audit: a verdict is the JSON
report existing, an incomplete run is retried and exits 75 rather than 1 — never
0, because an unaudited dependency set reported green is the same defect facing
the other way.

Two of them are about how far that distinction actually travels, both from the
review of #877. `make` collapses every failed recipe into its own exit 2, so the
exit code cannot reach the job that runs `make audit` and the verdict has to be a
line of output; and uv fetches pip-audit before pip-audit fetches anything, so a
cold tool cache against an unreachable host fails in a vocabulary pip-audit never
uses. The second is why matching phrases no longer decides whether to retry.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "audit_dependencies.py"
_NAME = "audit_dependencies_under_test"
_spec = importlib.util.spec_from_file_location(_NAME, _SCRIPT)
assert _spec is not None and _spec.loader is not None
audit_dependencies = importlib.util.module_from_spec(_spec)
# `@dataclass` resolves its annotations through `sys.modules[cls.__module__]`, so a
# module executed without being registered there raises rather than defining `Attempt`.
sys.modules[_NAME] = audit_dependencies
_spec.loader.exec_module(audit_dependencies)


TIMEOUT_TRACEBACK = (
    "Traceback (most recent call last):\n"
    "requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='pypi.org', port=443): "
    "Read timed out. (read timeout=15)\n"
)

# What a cold `uv tool run` says when the package host is unreachable. pip-audit
# never runs at all, so none of its own vocabulary appears.
UV_DOWNLOAD_FAILURE = (
    "error: Failed to download `pip-audit==2.10.1`\n"
    "  Caused by: Request failed after 3 retries\n"
    "  Caused by: error sending request for url (https://files.pythonhosted.org/...)\n"
    "  Caused by: client error (Connect)\n"
)


def verdict(captured: pytest.CaptureResult[str]) -> str:
    """The one line every caller can read, whatever mangled the exit code."""
    return captured.out.splitlines()[-1]


def clean_report(*names: str) -> dict[str, Any]:
    return {
        "dependencies": [{"name": name, "version": "1.0.0", "vulns": []} for name in names],
        "fixes": [],
    }


def vulnerable_report() -> dict[str, Any]:
    return {
        "dependencies": [
            {
                "name": "requests",
                "version": "2.19.0",
                "vulns": [
                    {
                        "id": "PYSEC-2018-28",
                        "fix_versions": ["2.20.0"],
                        "aliases": ["CVE-2018-18074"],
                    }
                ],
            }
        ],
        "fixes": [],
    }


class FakePipAudit:
    """A pip-audit that writes the reports it is given, in order, or fails."""

    def __init__(self, *outcomes: dict[str, Any] | str) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, command: list[str], report: Path) -> Any:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, str):
            return audit_dependencies.Attempt(returncode=1, output=outcome, report=None)
        report.write_text(json.dumps(outcome))
        return audit_dependencies.Attempt(returncode=0, output="", report=outcome)


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_dependencies.time, "sleep", lambda _: None)


def run(monkeypatch: pytest.MonkeyPatch, fake: FakePipAudit, *, attempts: int = 3) -> int:
    monkeypatch.setattr(audit_dependencies, "run_pip_audit", fake)
    return audit_dependencies.audit(
        Path("requirements-audit.txt"), attempts=attempts, timeout=30, backoff=5, extra=[]
    )


def test_a_clean_audit_exits_zero(monkeypatch: pytest.MonkeyPatch, no_sleep: None) -> None:
    assert run(monkeypatch, FakePipAudit(clean_report("anyio", "httpx"))) == 0


def test_a_vulnerable_dependency_still_fails_the_audit(
    monkeypatch: pytest.MonkeyPatch, no_sleep: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(monkeypatch, FakePipAudit(vulnerable_report())) == 1
    assert "PYSEC-2018-28" in capsys.readouterr().out


def test_a_timeout_on_one_request_is_retried_rather_than_reported(
    monkeypatch: pytest.MonkeyPatch, no_sleep: None
) -> None:
    """The failure #855 is about: one slow answer, then a run that says nothing is wrong."""
    fake = FakePipAudit(TIMEOUT_TRACEBACK, clean_report("anyio"))
    assert run(monkeypatch, fake) == 0
    assert fake.calls == 2


def test_a_feed_that_never_answers_is_not_reported_as_a_finding(
    monkeypatch: pytest.MonkeyPatch, no_sleep: None, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakePipAudit(TIMEOUT_TRACEBACK, TIMEOUT_TRACEBACK, TIMEOUT_TRACEBACK)
    assert run(monkeypatch, fake) == audit_dependencies.EXIT_UNAVAILABLE
    assert fake.calls == 3

    captured = capsys.readouterr()
    assert (
        verdict(captured)
        == "AUDIT: NETWORK — unreachable (ReadTimeout) after 3 attempts; no audit was performed"
    )
    assert "not a finding" in captured.err


def test_a_cold_uv_cache_against_a_dead_host_is_the_network_too(
    monkeypatch: pytest.MonkeyPatch, no_sleep: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """uv fetches pip-audit first, and fails in reqwest's words rather than requests'.

    A fresh runner or a cache miss makes this the *commonest* way the job meets an
    unreachable host, and it used to skip the retry loop and read `NOT AUDITED`.
    """
    fake = FakePipAudit(UV_DOWNLOAD_FAILURE, clean_report("anyio"))
    assert run(monkeypatch, fake) == 0
    assert fake.calls == 2

    assert audit_dependencies.network_marker(UV_DOWNLOAD_FAILURE) == "Failed to download"


def test_a_failure_nobody_recognised_is_retried_anyway(
    monkeypatch: pytest.MonkeyPatch, no_sleep: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """What happens the next time a phrase is missing: the wording dulls, nothing else.

    Matching strings decides how the verdict reads, never whether to try again —
    the two mistakes are not symmetric. Re-running a deterministic failure costs
    seconds; not re-running a transient one is the false red #855 is about.
    """
    fake = FakePipAudit("segmentation fault", "segmentation fault", clean_report("anyio"))
    assert run(monkeypatch, fake) == 0
    assert fake.calls == 3


def test_a_failure_nobody_recognised_says_so_rather_than_blaming_the_network(
    monkeypatch: pytest.MonkeyPatch, no_sleep: None, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakePipAudit(*["pip-audit: error: unrecognized arguments: --nonsense"] * 3)
    assert run(monkeypatch, fake) == audit_dependencies.EXIT_UNAVAILABLE
    assert verdict(capsys.readouterr()).startswith("AUDIT: FAILED — pip-audit reached no verdict")


def test_the_verdict_is_the_last_line_because_the_exit_code_does_not_survive_make(
    monkeypatch: pytest.MonkeyPatch, no_sleep: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every state ends on one grep-able line, which is what a caller through make gets."""
    assert run(monkeypatch, FakePipAudit(clean_report("anyio"))) == 0
    assert (
        verdict(capsys.readouterr())
        == "AUDIT: CLEAN — no known advisories against 1 locked dependencies"
    )

    assert run(monkeypatch, FakePipAudit(vulnerable_report())) == 1
    assert verdict(capsys.readouterr()) == (
        "AUDIT: VULNERABLE — 1 known advisory in 1 of 1 locked dependencies"
    )


def test_make_cannot_carry_the_exit_code_the_script_returns(tmp_path: Path) -> None:
    """The constraint the verdict line exists for, asserted rather than assumed.

    GNU Make prints `Error 75` and exits 2, so `Security Scan` — which runs
    `make audit` — sees one status for a finding and for a feed that never
    answered. Found reviewing #877.
    """
    (tmp_path / "Makefile").write_text("audit:\n\t@python3 -c 'raise SystemExit(75)'\n")
    make = shutil.which("make")
    assert make is not None
    completed = subprocess.run(
        [make, "-C", str(tmp_path), "audit"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 2


def test_a_job_can_read_the_verdict_without_reading_the_log(
    monkeypatch: pytest.MonkeyPatch, no_sleep: None, tmp_path: Path
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    fake = FakePipAudit(TIMEOUT_TRACEBACK, TIMEOUT_TRACEBACK, TIMEOUT_TRACEBACK)
    assert run(monkeypatch, fake) == audit_dependencies.EXIT_UNAVAILABLE
    assert summary.read_text().startswith("AUDIT: NETWORK —")


def test_nothing_is_written_when_the_run_is_not_inside_a_job(
    monkeypatch: pytest.MonkeyPatch, no_sleep: None
) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert run(monkeypatch, FakePipAudit(clean_report("anyio"))) == 0


def test_an_unauditable_dependency_is_named_rather_than_counted_as_clean(
    monkeypatch: pytest.MonkeyPatch, no_sleep: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """pip-audit skips a distribution PyPI has no record of, and it is not audited."""
    report = clean_report("anyio")
    report["dependencies"].append({"name": "internal-lib", "skip_reason": "not found on PyPI"})
    assert run(monkeypatch, FakePipAudit(report)) == 0

    out = capsys.readouterr().out
    assert "skipped: internal-lib" in out
    assert "against 1 locked dependencies" in out


@pytest.mark.parametrize(
    "output",
    [
        "requests.exceptions.ReadTimeout: Read timed out. (read timeout=15)",
        "requests.exceptions.ConnectionError: Max retries exceeded with url: /pypi/x/json",
        "ERROR:pip_audit._cli:Could not connect to PyPI's vulnerability feed",
        "Tip: your network may be blocking this service.",
        "pip_audit._service.interface.ServiceError",
        "error: Failed to download `pip-audit==2.10.1`",
        "  Caused by: Request failed after 3 retries",
        "  Caused by: error sending request for url (https://pypi.org/simple/pip-audit/)",
        "  Caused by: client error (Connect)",
        "  Caused by: dns error: failed to lookup address information",
    ],
)
def test_the_shapes_a_blocked_host_arrives_in(output: str) -> None:
    assert audit_dependencies.network_marker(output) is not None


def test_a_rejected_flag_is_not_mistaken_for_the_network() -> None:
    assert audit_dependencies.network_marker("error: unrecognized arguments: --nope") is None


def test_the_report_is_written_where_the_command_is_told_to_write_it(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    command = audit_dependencies.build_command(
        Path("requirements-audit.txt"), report, timeout=30, extra=["-s", "osv"]
    )
    assert command[-2:] == ["-s", "osv"]
    assert command[command.index("--output") + 1] == str(report)
    assert command[command.index("--timeout") + 1] == "30"
    assert command[command.index("--format") + 1] == "json"


def test_a_report_that_was_never_written_is_not_a_verdict(tmp_path: Path) -> None:
    """The whole discrimination rests on this: no file, no audit, whatever the exit code."""
    attempt = audit_dependencies.run_pip_audit(
        ["python3", "-c", "raise SystemExit(1)"], tmp_path / "report.json"
    )
    assert attempt.report is None


def test_a_stale_report_from_an_earlier_attempt_is_not_reused(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(json.dumps(clean_report("anyio")))
    attempt = audit_dependencies.run_pip_audit(["python3", "-c", "raise SystemExit(1)"], report)
    assert attempt.report is None
