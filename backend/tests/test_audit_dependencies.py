"""What `make audit` may and may not conclude from a pip-audit run.

`Security Scan` is a required check, and pip-audit exits 1 both when a locked
dependency is vulnerable and when it never reached the feed at all — a
`ReadTimeout` on one of 254 requests looked exactly like an advisory on #838,
and a re-run of the same commit passed unchanged (#855).

`scripts/audit_dependencies.py` is what keeps those two apart, so the tests here
are about the distinction rather than about pip-audit: a verdict is the JSON
report existing, a network-shaped failure is retried, and an incomplete run exits
75 rather than 1 — never 0, because an unaudited dependency set reported green is
the same defect facing the other way.
"""

from __future__ import annotations

import importlib.util
import json
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

    err = capsys.readouterr().err
    assert "NETWORK: the vulnerability feed was unreachable (ReadTimeout) after 3 attempts" in err
    assert "not a finding" in err


def test_a_failure_that_is_not_the_network_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, no_sleep: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """Three tries at a rejected flag only delay the same answer, and it is not a blip."""
    fake = FakePipAudit("pip-audit: error: unrecognized arguments: --nonsense")
    assert run(monkeypatch, fake) == audit_dependencies.EXIT_UNAVAILABLE
    assert fake.calls == 1
    assert capsys.readouterr().err.startswith("NOT AUDITED:")


def test_an_unauditable_dependency_is_named_rather_than_counted_as_clean(
    monkeypatch: pytest.MonkeyPatch, no_sleep: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """pip-audit skips a distribution PyPI has no record of; the columns report says so."""
    report = clean_report("anyio")
    report["dependencies"].append({"name": "internal-lib", "skip_reason": "not found on PyPI"})
    assert run(monkeypatch, FakePipAudit(report)) == 0

    out = capsys.readouterr().out
    assert "skipped: internal-lib" in out
    assert "1 locked dependencies" in out


@pytest.mark.parametrize(
    "output",
    [
        "requests.exceptions.ReadTimeout: Read timed out. (read timeout=15)",
        "requests.exceptions.ConnectionError: Max retries exceeded with url: /pypi/x/json",
        "ERROR:pip_audit._cli:Could not connect to PyPI's vulnerability feed",
        "Tip: your network may be blocking this service.",
        "pip_audit._service.interface.ServiceError",
    ],
)
def test_the_shapes_a_blocked_feed_arrives_in(output: str) -> None:
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
