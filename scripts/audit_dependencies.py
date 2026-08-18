#!/usr/bin/env python3
"""Audit the locked dependency set, and tell a network failure from a finding.

`pip-audit` issues one request per locked distribution and exits 1 whether it
found a vulnerability or never reached the feed at all — a `ReadTimeout` on one
of 254 requests ends the run with a traceback and the same exit code a real
advisory produces. `Security Scan` is a required check, so that reads as "a
locked dependency is vulnerable" until somebody opens the log (#855).

Three things fix that, and this script is all of them:

**A verdict is a file, not an exit code.** `--format json` is a *manifest*
format, so pip-audit writes it on both the clean and the vulnerable path, and
only after every dependency has been queried. The report existing therefore means
the audit completed; the report missing means it did not, whatever the exit code
said. Nothing here parses a summary line.

**An audit that did not complete is tried again.** The feed answering slowly once
is not information about the dependency set. Every incomplete run is retried —
*every* one, not only those whose output matches a phrase — because the two
mistakes are not symmetric: re-running a deterministic failure costs seconds and
the same answer, while not re-running a transient one puts a false red on a
required check, which is the whole of #855. `NETWORK_MARKERS` therefore chooses
the **wording** of the verdict and nothing else; a failure phrased in words the
list does not hold is still retried, and merely reads `FAILED` rather than
`NETWORK`. That distinction has to hold for two vocabularies, not one: uv fetches
pip-audit before pip-audit fetches anything, so `Failed to download` is as much a
network failure here as `ReadTimeout` is.

**The verdict is a line, because the exit code does not survive the caller.**
GNU Make turns any failed recipe into its own exit 2, so a caller reaching this
through `make audit` — which is what the `Security Scan` job does — cannot tell
75 from 1. The last line of stdout is therefore always
`AUDIT: <STATE> — <detail>`, with `STATE` one of `CLEAN`, `VULNERABLE`, `NETWORK`
or `FAILED`, and it is mirrored into `$GITHUB_STEP_SUMMARY` when the run is inside
a job. The exit codes below are still the contract for anything invoking this
script directly, which is where they are readable.

It never exits 0 on an audit that did not run: an unaudited dependency set
reported green is the same defect facing the other way.

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
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXIT_CLEAN = 0
EXIT_VULNERABLE = 1
# EX_TEMPFAIL. Distinct from 1 for a caller that can see it; the verdict line is
# what says the same thing to one that cannot.
EXIT_UNAVAILABLE = 75

# The token every caller can read, whatever mangled the exit code on the way.
VERDICT_PREFIX = "AUDIT:"

# `--no-deps --disable-pip` skips the resolution round-trip pip-audit would
# otherwise do in a throwaway virtualenv; the export is already fully pinned.
PIP_AUDIT = ("uv", "tool", "run", "pip-audit")
BASE_FLAGS = ("--no-deps", "--disable-pip", "--progress-spinner=off", "--desc", "off")

# Substrings that mean the run ended on the way to a feed rather than on what it
# found there. Two vocabularies, because two programs reach for the network: uv,
# fetching pip-audit itself on a cold tool cache, and then pip-audit, fetching the
# advisories. Neither list is exhaustive and neither has to be — an unmatched
# failure is retried exactly the same, and only reads `FAILED` instead.
NETWORK_MARKERS = (
    # pip-audit: exception names as it lets them escape, plus its own messages.
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
    # uv, which speaks reqwest rather than requests.
    "Failed to download",
    "Failed to fetch",
    "Request failed after",
    "error sending request",
    "client error (Connect)",
    "dns error",
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
    """The first marker in `output` naming this failure as the network, if any."""
    for marker in NETWORK_MARKERS:
        if marker in output:
            return marker
    return None


def announce(state: str, detail: str) -> None:
    """Emit the verdict where a caller can read it without an exit code."""
    line = f"{VERDICT_PREFIX} {state} — {detail}"
    print(line)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")


def report_findings(report: dict[str, Any]) -> int:
    """Print what the completed audit found, and return the exit code it earns."""
    dependencies = report.get("dependencies", [])
    skipped = [dep for dep in dependencies if "skip_reason" in dep]
    vulnerable = [dep for dep in dependencies if dep.get("vulns")]

    for dep in skipped:
        print(f"skipped: {dep['name']} — {dep['skip_reason']}")

    audited = len(dependencies) - len(skipped)
    if not vulnerable:
        announce("CLEAN", f"no known advisories against {audited} locked dependencies")
        return EXIT_CLEAN

    count = sum(len(dep["vulns"]) for dep in vulnerable)
    plural = "advisory" if count == 1 else "advisories"
    for dep in vulnerable:
        for vuln in dep["vulns"]:
            fixes = ", ".join(vuln["fix_versions"]) or "none"
            aliases = " ".join(vuln.get("aliases", []))
            print(f"  {dep['name']} {dep['version']}  {vuln['id']}  fix: {fixes}  {aliases}")
    announce(
        "VULNERABLE",
        f"{count} known {plural} in {len(vulnerable)} of {audited} locked dependencies",
    )
    return EXIT_VULNERABLE


def report_unavailable(attempt: Attempt, marker: str | None, tries: int) -> int:
    """Print why no audit happened, in terms nobody can read as a finding."""
    plural = "attempt" if tries == 1 else "attempts"
    if marker is None:
        state = "FAILED"
        detail = (
            f"pip-audit reached no verdict in {tries} {plural} and did not say why; "
            "no audit was performed"
        )
    else:
        state = "NETWORK"
        detail = f"unreachable ({marker}) after {tries} {plural}; no audit was performed"

    print(
        "No audit was performed, so this is not a finding: no locked dependency has "
        "been reported vulnerable, and none has been cleared either.",
        file=sys.stderr,
    )
    print(f"\npip-audit exited {attempt.returncode}:\n{attempt.output}", file=sys.stderr)
    announce(state, detail)
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
            if tries >= attempts:
                return report_unavailable(attempt, marker, tries)

            delay = backoff * tries
            print(
                f"attempt {tries}/{attempts} reached no verdict "
                f"({marker or 'cause not recognised'}); retrying in {delay}s",
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
