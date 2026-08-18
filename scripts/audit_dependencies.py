#!/usr/bin/env python3
"""Audit the locked dependency set, and tell a network failure from a finding.

`pip-audit` issues one request per locked distribution and exits 1 whether it
found a vulnerability or never reached the feed at all — a `ReadTimeout` on one
of 254 requests ends the run with a traceback and the same exit code a real
advisory produces. `Security Scan` is a required check, so that reads as "a
locked dependency is vulnerable" until somebody opens the log (#855).

Two things fix that, and this script is both of them:

**A verdict is a file, not an exit code.** `--format json` is a *manifest*
format, so pip-audit writes it on both the clean and the vulnerable path, and
only after every dependency has been queried. The report existing therefore means
the audit completed; the report missing means it did not, whatever the exit code
said. Nothing here parses a summary line.

**A failure that names the network is retried.** The feed answering slowly once
is not information about the dependency set, so a network-shaped failure is tried
again, twice, with a backoff. A failure that is *not* network-shaped — a flag the
tool rejects, a requirements file it cannot read — is not retried, because trying
it three times only delays the same answer.

Whichever way that ends, an incomplete audit exits `EXIT_UNAVAILABLE` (75,
`EX_TEMPFAIL`) and says so in its first line. Only a completed audit that found
something exits 1. It never exits 0 on an audit that did not run: an unaudited
dependency set reported green is the same defect facing the other way.

Usage::

    python3 scripts/audit_dependencies.py backend/requirements-audit.txt
    python3 scripts/audit_dependencies.py backend/requirements-audit.txt \
        --attempts 3 --timeout 30

Arguments after `--` are passed to pip-audit, which is how the failure path is
exercised for real: the PyPI service hardcodes its URL, but the OSV service takes
one, so pointing it at a closed port makes the feed unreachable without touching
the network the rest of the run needs::

    python3 scripts/audit_dependencies.py backend/requirements-audit.txt \
        -- -s osv --osv-url http://127.0.0.1:9/v1/query
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXIT_CLEAN = 0
EXIT_VULNERABLE = 1
# EX_TEMPFAIL. Distinct from 1 on purpose: the whole point is that a red job
# whose cause is the network cannot be mistaken for one whose cause is a finding.
EXIT_UNAVAILABLE = 75

# `--no-deps --disable-pip` skips the resolution round-trip pip-audit would
# otherwise do in a throwaway virtualenv; the export is already fully pinned.
PIP_AUDIT = ("uv", "tool", "run", "pip-audit")
BASE_FLAGS = ("--no-deps", "--disable-pip", "--progress-spinner=off", "--desc", "off")

# Substrings that mean the run ended on the way to the feed rather than on what
# it found there. Exception names as pip-audit lets them escape (`ReadTimeout`,
# `ConnectionError`, `ServiceError` wrapping a 5xx) plus the two messages it
# raises itself. Matched against stdout and stderr together, because a traceback
# and pip-audit's own logging do not share a stream.
NETWORK_MARKERS = (
    "ConnectionError",
    "ConnectTimeout",
    "ReadTimeout",
    "Timeout",
    "TooManyRedirects",
    "HTTPError",
    "ServiceError",
    "Max retries exceeded",
    "Could not connect",
    "not redirecting properly",
    "network may be blocking",
    "Name or service not known",
    "Temporary failure in name resolution",
)


@dataclass(frozen=True)
class Attempt:
    """One pip-audit invocation: what it printed, and whether it reached a verdict."""

    returncode: int
    output: str
    report: dict[str, Any] | None


def build_command(requirements: Path, report: Path, timeout: int, extra: list[str]) -> list[str]:
    """The pip-audit invocation, writing its verdict to `report`."""
    return [
        *PIP_AUDIT,
        "-r",
        str(requirements),
        *BASE_FLAGS,
        "--timeout",
        str(timeout),
        "--format",
        "json",
        "--output",
        str(report),
        *extra,
    ]


def run_pip_audit(command: list[str], report: Path) -> Attempt:
    """Run pip-audit and read back the report, which exists only if it finished."""
    report.unlink(missing_ok=True)
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    output = completed.stdout + completed.stderr

    try:
        parsed = json.loads(report.read_text())
    except (OSError, json.JSONDecodeError):
        return Attempt(completed.returncode, output, None)
    return Attempt(completed.returncode, output, parsed)


def network_marker(output: str) -> str | None:
    """The first marker in `output` saying this failure was the network, if any."""
    for marker in NETWORK_MARKERS:
        if marker in output:
            return marker
    return None


def report_findings(report: dict[str, Any]) -> int:
    """Print what the completed audit found, and return the exit code it earns."""
    dependencies = report.get("dependencies", [])
    skipped = [dep for dep in dependencies if "skip_reason" in dep]
    vulnerable = [dep for dep in dependencies if dep.get("vulns")]

    for dep in skipped:
        print(f"skipped: {dep['name']} — {dep['skip_reason']}")

    audited = len(dependencies) - len(skipped)
    if not vulnerable:
        print(f"No known vulnerabilities in {audited} locked dependencies.")
        return EXIT_CLEAN

    count = sum(len(dep["vulns"]) for dep in vulnerable)
    plural = "vulnerability" if count == 1 else "vulnerabilities"
    print(f"Found {count} known {plural} in {len(vulnerable)} of {audited} locked dependencies:")
    for dep in vulnerable:
        for vuln in dep["vulns"]:
            fixes = ", ".join(vuln["fix_versions"]) or "none"
            aliases = " ".join(vuln.get("aliases", []))
            print(f"  {dep['name']} {dep['version']}  {vuln['id']}  fix: {fixes}  {aliases}")
    return EXIT_VULNERABLE


def report_unavailable(attempt: Attempt, marker: str | None, tries: int) -> int:
    """Print why no audit happened, in terms nobody can read as a finding."""
    if marker is None:
        headline = "NOT AUDITED: pip-audit failed before reaching the vulnerability feed."
        advice = "Read its output below; re-running will not change it."
    else:
        plural = "attempt" if tries == 1 else "attempts"
        headline = (
            f"NETWORK: the vulnerability feed was unreachable ({marker}) after {tries} {plural}."
        )
        advice = "Re-run the job."

    print(headline, file=sys.stderr)
    print(
        "No audit was performed, so this is not a finding: no locked dependency has "
        f"been reported vulnerable, and none has been cleared either. {advice}",
        file=sys.stderr,
    )
    print(f"\npip-audit exited {attempt.returncode}:\n{attempt.output}", file=sys.stderr)
    return EXIT_UNAVAILABLE


def audit(requirements: Path, attempts: int, timeout: int, backoff: int, extra: list[str]) -> int:
    with tempfile.TemporaryDirectory() as workdir:
        report = Path(workdir) / "pip-audit.json"
        command = build_command(requirements, report, timeout, extra)

        tries = 0
        while True:
            tries += 1
            attempt = run_pip_audit(command, report)
            if attempt.report is not None:
                return report_findings(attempt.report)

            marker = network_marker(attempt.output)
            if marker is None or tries >= attempts:
                return report_unavailable(attempt, marker, tries)

            delay = backoff * tries
            print(
                f"attempt {tries}/{attempts} did not reach the feed ({marker}); "
                f"retrying in {delay}s",
                file=sys.stderr,
            )
            time.sleep(delay)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit the locked dependency set for known vulnerabilities."
    )
    parser.add_argument("requirements", type=Path, help="the exported, fully pinned requirements")
    parser.add_argument(
        "--attempts", type=int, default=3, help="how many times to try the feed (default: 3)"
    )
    parser.add_argument(
        "--timeout", type=int, default=30, help="socket timeout in seconds (default: 30)"
    )
    parser.add_argument(
        "--backoff", type=int, default=5, help="seconds before the second attempt (default: 5)"
    )
    parser.add_argument("extra", nargs="*", help="arguments passed through to pip-audit")
    args = parser.parse_args()

    return audit(args.requirements, args.attempts, args.timeout, args.backoff, args.extra)


if __name__ == "__main__":
    sys.exit(main())
