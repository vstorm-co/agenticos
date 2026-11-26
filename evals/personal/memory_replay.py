"""Run selected enterprise memory cases against the disposable PostgreSQL test database.

The suite exercises real PostgreSQL, job admission and ledger changes with synthetic
events. It never calls a provider or a model. Listing cases does not open a database.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
REPLAY = "tests/integration/test_memory_enterprise.py"
CASES = {
    "memory-headcount-as-of": "test_memory_headcount_as_of_and_retro_correction",
    "memory-retro-correction": "test_memory_headcount_as_of_and_retro_correction",
    "memory-relevance-after-noise": "test_memory_relevance_after_noise",
    "memory-share-preserves-time": "test_project_no_workspace_and_group_revocation",
    "agenticos-project-no-workspace": "test_project_no_workspace_and_group_revocation",
    "context-ambiguous-alias": "test_same_named_people_require_separate_external_identity",
    "enterprise-group-and-tenant-isolation": "test_project_no_workspace_and_group_revocation",
    "enterprise-room-isolation": "test_group_claim_recall_keeps_private_audience_boundaries",
    "enterprise-history-pagination": "test_object_versions_use_stable_cursors_and_amend_legacy_rows",
    "enterprise-source-reconnect": "test_mail_rule_reconnect_removes_old_history_and_proofs",
    "enterprise-reviewer-revocation": "test_reviewers_losing_edit_scope_stop_polling_admission_and_apply",
    "briefing-deadline-changed": "test_gmail_deadline_change_is_single_and_revocable",
    "briefing-late-correction": "test_late_email_fills_its_interval_without_another_alert",
    "enterprise-duplicate-delivery": "test_gmail_deadline_change_is_single_and_revocable",
    "enterprise-revoked-in-queue": "test_gmail_shadow_and_revoked_while_queued",
    "enterprise-shadow-is-silent": "test_gmail_shadow_and_revoked_while_queued",
    "enterprise-erase-and-replay": "test_erasure_removes_shared_copy_and_old_job_cannot_restore_it",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, action="append", help="Default: all cases.")
    parser.add_argument("--list", action="store_true", help="List case IDs without running.")
    args = parser.parse_args()
    if args.list:
        print("\n".join(CASES))
        return 0
    selectors = (
        [f"{REPLAY}::{node}" for node in dict.fromkeys(CASES[case] for case in args.case)]
        if args.case
        else [REPLAY]
    )
    # Integration fixtures create and drop a fresh per-process database. CI makes
    # an unavailable database a hard failure rather than a skipped replay.
    # The executable and node IDs are fixed; argparse only selects a known case.
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "-q", *selectors],
        cwd=BACKEND,
        env={**os.environ, "CI": "1"},
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
