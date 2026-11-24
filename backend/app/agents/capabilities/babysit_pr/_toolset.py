"""The three tools of babysit-pr: check a snapshot, read the rate limit, stop."""

import json
from typing import Any

from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.babysit_pr import (
    BabysitWatcher,
    now_utc,
    parse_checks,
    rate_limit_decision,
)
from app.agents.manifest import MAX_RECORDED_BABYSIT_PR_EVENTS, RunRecorder


def build_babysit_pr_toolset(
    watcher: BabysitWatcher,
    recorder: RunRecorder,
    poll_interval_seconds: int,
    max_watch_minutes: int,
) -> FunctionToolset[Any]:
    """The babysit-pr toolset, bound to this run's watcher and recorder."""
    toolset: FunctionToolset[Any] = FunctionToolset()

    @toolset.tool
    async def babysit_pr_check(
        ctx: RunContext[Any],
        repo: str,
        pr_number: int,
        head_sha: str,
        checks: list[dict[str, Any]],
    ) -> str:
        """Classify one snapshot of a pull request's checks.

        Use it when a watch wakes you with new check output: pass the
        repo, PR number, head SHA, and the checks as `gh pr checks`
        reports them. It reports only what changed since the last
        snapshot, names each failed check real or flake with its
        reason, and says what to do next — keep watching, act on a
        failure, or stop because the bots are green on the latest
        commit. When nothing changed and the watch continues, the
        report is empty: end your turn without a message, never post
        or say "still waiting". It never merges, comments, or takes
        any other action on the PR.

        Args:
            repo: The repository as `owner/name`.
            pr_number: The pull request number.
            head_sha: The commit the checks ran on. A new head
                re-opens the question: green on the last commit is
                never green on this one.
            checks: One entry per check run, with `name`, `status`,
                `conclusion`, and the failure text as `detail` when
                it failed. Entries without a name are dropped and
                counted, not fatal.

        Returns:
            A JSON string with the repo, PR number, head SHA, whether
            the head moved, the events (only the checks that changed),
            the decision, the reason, the report text, and how many
            seconds until the next poll — 0 when the watch has ended.
            A refusal string instead when the repo, PR number, or
            head is missing, or when another PR is already being
            watched.
        """
        parts = repo.split("/") if isinstance(repo, str) else []
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            return "Babysit needs a repo as `owner/name`."
        if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number < 1:
            return "Babysit needs a pull request number of 1 or more."
        if not isinstance(head_sha, str) or not head_sha.strip():
            return "Babysit needs the head SHA the checks ran on."
        refused = watcher.start(repo, pr_number, head_sha.strip(), now_utc())
        if refused is not None:
            return refused
        parsed, dropped = parse_checks(checks)
        result = watcher.check(
            head_sha.strip(),
            parsed,
            now=now_utc(),
            poll_interval_seconds=poll_interval_seconds,
            max_watch_minutes=max_watch_minutes,
        )
        if dropped and result["decision"] == "green":
            result["decision"] = "needs_attention"
            result["reason"] = (
                f"{dropped} malformed check(s) were dropped; their state is unknown, "
                "so this snapshot cannot be green"
            )
        for event in result["events"]:
            recorder.babysit_pr_events.append(
                {
                    **event,
                    "repo": repo,
                    "pr_number": pr_number,
                    "decision": result["decision"],
                }
            )
        del recorder.babysit_pr_events[:-MAX_RECORDED_BABYSIT_PR_EVENTS]
        result["dropped_checks"] = dropped
        return json.dumps(result)

    @toolset.tool
    async def babysit_pr_rate_limit(ctx: RunContext[Any], remaining: int, reset_epoch: int) -> str:
        """Decide whether to watch again, from `gh api rate_limit`.

        Use it before watching again when the GraphQL budget may be
        nearly used up: pass `remaining` and `reset` from
        `gh api rate_limit --jq .resources.graphql`. It answers
        `watch` with the poll gap while calls remain, and `wait` with
        the seconds until the reset when they do not — never a tight
        loop.

        Args:
            remaining: GraphQL calls remaining.
            reset_epoch: The reset time as a Unix epoch.

        Returns:
            A JSON string with the action (`watch` or `wait`), the
            seconds to wait or to poll after, and the reason. A
            refusal string instead when either number is missing or
            negative.
        """
        if (
            not isinstance(remaining, int)
            or isinstance(remaining, bool)
            or remaining < 0
            or not isinstance(reset_epoch, int)
            or isinstance(reset_epoch, bool)
            or reset_epoch < 0
        ):
            return "Babysit needs the remaining calls and the reset epoch, both 0 or more."
        action, seconds = rate_limit_decision(
            remaining, reset_epoch, int(now_utc().timestamp()), poll_interval_seconds
        )
        note = (
            f"Wait {seconds} seconds for the rate-limit reset, then watch again."
            if action == "wait"
            else f"Calls remain; poll again in {seconds} seconds."
        )
        return json.dumps({"action": action, "seconds": seconds, "note": note})

    @toolset.tool
    async def babysit_pr_stop(ctx: RunContext[Any], reason: str = "") -> str:
        """Stop watching the pull request.

        Use it when you stop — the bots are green, the PR is blocked,
        or you are asking the user a question — so the thread does not
        stay in Working out of the user's inbox. A merge or close
        ends the watch on its own.

        Args:
            reason: Why the watch is stopping, in a few words.

        Returns:
            A confirmation string naming the PR stopped, or that no
            watch was active.
        """
        stopped = watcher.stop(reason)
        if not stopped["stopped"]:
            return "No watch is active."
        return f"Stopped watching {stopped['repo']}#{stopped['pr_number']}: {stopped['reason']}."

    return toolset
