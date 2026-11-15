"""Babysit a pull request through CI and review bots (#7).

Theo's tstack `babysit-pr` skill, T3OS-ised as pure logic: the watcher
classifies one snapshot of a PR's checks at a time, reports only what
changed since the last snapshot, and says when to stop. It never merges,
comments, or takes any other action on the PR — watching and reporting
only. The agent obtains snapshots itself (`gh pr checks` under the
monitor capability) and hands them to the `babysit_pr` capability's
tools; this module is what those tools call.

Rules carried over from the skill, enforced here rather than left to
prompt:

- Only the current commit's checks count: a snapshot for a new head
  re-opens the question, and green on an old head is never green.
- A wake is news, not a merge decision. When nothing changed, the
  report is empty — the agent stays quiet, never "still waiting".
- Real failures and infrastructure flakes are different things. A
  flake is named with its reason so the agent can dismiss it with a
  written reason; a real failure is named so the agent can fix it.
  The classification is a heuristic over the check's own failure
  text, and the agent verifies every finding against the source
  before acting on it.
- One watcher per PR, and only the thread that owns the PR watches
  it. A delegated child never watches.
- Never watch in a tight loop: polls are floored at
  :data:`MIN_POLL_SECONDS`, and when the GitHub rate limit is nearly
  used up the watcher waits for its reset instead of polling.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

#: The shortest gap between two polls. A watcher that polls faster is a
#: tight loop, and tight loops are what burn the shared rate limit.
MIN_POLL_SECONDS = 60
#: The poll gap an operator gets without saying otherwise: five minutes
#: is frequent enough to hear about a failed check promptly and slow
#: enough to share one account's rate limit with other watchers.
DEFAULT_POLL_SECONDS = 300
#: The longest gap the configuration allows; beyond half an hour the
#: watcher is not watching, it is forgetting.
MAX_POLL_SECONDS = 1800
#: How few GraphQL calls may remain before the watcher waits for the
#: reset instead of watching again. `gh pr checks` uses GraphQL, and
#: the REST limit it falls back to is separate.
RATE_LIMIT_FLOOR = 10
#: How long one watch may run before it stops and reports blocked.
DEFAULT_MAX_WATCH_MINUTES = 240

CheckState = Literal["passed", "failed", "pending", "cancelled", "skipped", "unknown"]
FailureKind = Literal["real", "flake", "unknown"]
WatchDecision = Literal[
    "continue", "green", "needs_attention", "head_moved", "rate_limited", "expired", "no_watch"
]

#: Substrings in a failed check's own failure text that mark it an
#: infrastructure flake rather than a real failure. Heuristic, not a
#: verdict: the agent verifies the finding against the source before
#: dismissing it, and a check whose text matches nothing here is real
#: until proven otherwise.
FLAKE_SIGNALS: tuple[str, ...] = (
    "timed out",
    "timeout",
    "connection reset",
    "connection refused",
    "lost communication",
    "runner lost",
    "no runner",
    "service unavailable",
    "bad gateway",
    "http 502",
    "http 503",
    "http 504",
    "rate limit",
    "rate_limit",
    "no space left on device",
    "disk quota exceeded",
    "failed to fetch",
    "network unreachable",
    "network error",
    "infrastructure",
    "internal server error",
    "econnreset",
    "socket hang up",
    "temporary failure",
)


def clamp_poll_seconds(seconds: int) -> int:
    """A poll gap inside the allowed band, floored, never a tight loop."""
    return max(MIN_POLL_SECONDS, min(MAX_POLL_SECONDS, seconds))


def check_state(status: str, conclusion: str | None) -> CheckState:
    """One check's state from its GitHub status and conclusion.

    Anything not finished is pending. A finished check is passed,
    failed, cancelled, or skipped by its conclusion; a conclusion
    that says nothing about the outcome (`action_required`,
    `stale`, none) is unknown rather than a pass.
    """
    if status != "completed":
        return "pending"
    match conclusion:
        case "success" | "neutral":
            return "passed"
        case "failure" | "timed_out":
            return "failed"
        case "cancelled":
            return "cancelled"
        case "skipped":
            return "skipped"
        case _:
            return "unknown"


@dataclass(frozen=True)
class BabysitCheck:
    """One check run on a PR, as `gh pr checks` reports it."""

    name: str
    status: str = "queued"
    conclusion: str | None = None
    detail: str = ""
    url: str = ""

    @property
    def state(self) -> CheckState:
        """The check's state: only the current commit's checks count."""
        return check_state(self.status, self.conclusion)

    def to_dict(self) -> dict[str, Any]:
        """The check as JSON, for the tool result and the manifest."""
        return {
            "name": self.name,
            "status": self.status,
            "conclusion": self.conclusion,
            "detail": self.detail,
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BabysitCheck:
        """A check from tool input, refusing a nameless one."""
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("a check needs a name")
        conclusion = raw.get("conclusion")
        return cls(
            name=name.strip(),
            status=str(raw.get("status") or "queued"),
            conclusion=conclusion if isinstance(conclusion, str) else None,
            detail=str(raw.get("detail") or ""),
            url=str(raw.get("url") or ""),
        )


def parse_checks(raw: Any) -> tuple[list[BabysitCheck], int]:
    """Tool input into checks, counting the entries dropped, not crashing.

    A snapshot with a malformed entry is still a snapshot: the entry
    is dropped and counted, and the caller says so, rather than the
    whole watch failing on one bad line.
    """
    checks: list[BabysitCheck] = []
    dropped = 0
    if not isinstance(raw, list):
        return checks, 1
    for entry in raw:
        if not isinstance(entry, dict):
            dropped += 1
            continue
        try:
            checks.append(BabysitCheck.from_dict(entry))
        except ValueError:
            dropped += 1
    return checks, dropped


def classify_failure(check: BabysitCheck) -> tuple[FailureKind, str]:
    """A failed check as real or flake, with the reason, or unknown.

    Only a failed check is classified. A timed-out check is a flake
    — the run never finished, so there is no failure to fix.
    Otherwise the check's own failure text decides: a matching
    infrastructure signal is a flake, anything else is real until
    the agent proves otherwise from the source. A cancelled or
    undecided check never reaches here: its state is not failed, and
    the watch decision handles it instead.
    """
    if check.state != "failed":
        return "unknown", ""
    if check.conclusion == "timed_out":
        return "flake", "the check timed out"
    detail = check.detail.casefold()
    for signal in FLAKE_SIGNALS:
        if signal in detail:
            return "flake", f"failure text matches an infrastructure signal: {signal!r}"
    return "real", "no infrastructure signal in the failure text"


@dataclass(frozen=True)
class BabysitEvent:
    """One check's change since the last snapshot — the only news."""

    check_name: str
    previous_state: CheckState | None
    state: CheckState
    failure_kind: FailureKind | None
    reason: str
    head_sha: str

    def to_dict(self) -> dict[str, Any]:
        """The event as JSON, for the tool result and the manifest."""
        return {
            "check": self.check_name,
            "previous_state": self.previous_state,
            "state": self.state,
            "failure_kind": self.failure_kind,
            "reason": self.reason,
            "head_sha": self.head_sha,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BabysitEvent:
        """An event back from the manifest."""
        state = raw.get("state")
        if state not in (
            "passed",
            "failed",
            "pending",
            "cancelled",
            "skipped",
            "unknown",
        ):
            raise ValueError(f"unknown check state: {state!r}")
        return cls(
            check_name=str(raw["check"]),
            previous_state=raw.get("previous_state"),
            state=state,
            failure_kind=raw.get("failure_kind"),
            reason=str(raw.get("reason") or ""),
            head_sha=str(raw.get("head_sha") or ""),
        )


def diff_checks(
    previous: dict[str, BabysitCheck],
    current: list[BabysitCheck],
    head_sha: str,
) -> list[BabysitEvent]:
    """The checks that changed since the last snapshot — nothing else.

    A check that only moved into pending is not news: a re-run on the
    same head says nothing until it lands. A check that appears
    already decided is news, because the watcher started late and
    must not silently miss a failure. A check that vanished from the
    suite is not reported: the suite changed, the PR did not fail.
    """
    events: list[BabysitEvent] = []
    for check in current:
        before = previous.get(check.name)
        if before is None:
            if check.state == "pending":
                continue
            events.append(_event(check, None, head_sha))
        elif before.state != check.state:
            if check.state == "pending":
                continue
            events.append(_event(check, before.state, head_sha))
    return events


def _event(check: BabysitCheck, previous_state: CheckState | None, head_sha: str) -> BabysitEvent:
    kind, reason = classify_failure(check)
    return BabysitEvent(
        check_name=check.name,
        previous_state=previous_state,
        state=check.state,
        failure_kind=kind if check.state == "failed" else None,
        reason=reason if check.state == "failed" else "",
        head_sha=head_sha,
    )


def decide_watch(
    checks: list[BabysitCheck],
    *,
    head_moved: bool,
    started_at: datetime | None,
    now: datetime,
    max_watch_minutes: int,
) -> tuple[WatchDecision, str]:
    """What the watcher does next, and why, in one place.

    The order is the priority: a failure needs a person or a fix,
    green on the commit in this snapshot ends the watch, and only
    then does a moved head matter — the snapshot's checks are for
    the new head, so green here is green on this commit, while
    pending checks on a new head must not inherit the old head's
    green. Budget end is not approval.
    """
    failed = [check for check in checks if check.state == "failed"]
    if failed:
        real = sum(1 for check in failed if classify_failure(check)[0] == "real")
        flakes = len(failed) - real
        names = ", ".join(check.name for check in failed)
        return (
            "needs_attention",
            f"{len(failed)} check(s) failed ({names}): {real} real, "
            f"{flakes} flake — fix the real ones, dismiss the flakes "
            "with a written reason",
        )
    blocked = [check for check in checks if check.state in ("cancelled", "unknown")]
    if blocked:
        names = ", ".join(check.name for check in blocked)
        return (
            "needs_attention",
            f"{len(blocked)} check(s) cancelled or undecided ({names}) — "
            "needs a human look, not a code fix",
        )
    if checks and all(check.state in ("passed", "skipped") for check in checks):
        return "green", "all checks green on the latest commit"
    if head_moved:
        return (
            "head_moved",
            "the PR head moved; the checks above are for the new head, "
            "so wait for green on this commit, not the last one",
        )
    if not checks:
        return "continue", "no checks reported yet"
    if started_at is not None:
        elapsed = (now - started_at).total_seconds() / 60
        if elapsed > max_watch_minutes:
            return (
                "expired",
                f"the watch ran past {max_watch_minutes} minutes without "
                "green; stop and report blocked",
            )
    pending = sum(1 for check in checks if check.state == "pending")
    return "continue", f"{pending} check(s) still pending"


def rate_limit_decision(
    remaining: int, reset_epoch: int, now_epoch: int, poll_seconds: int
) -> tuple[str, int]:
    """Watch again, or wait for the rate-limit reset — never a tight loop.

    Returns `("watch", poll_seconds)` while calls remain, and
    `("wait", seconds)` when the GraphQL budget is nearly used up.
    A reset that already passed is not a wait: the budget is back.
    """
    if remaining > RATE_LIMIT_FLOOR:
        return "watch", clamp_poll_seconds(poll_seconds)
    wait = reset_epoch - now_epoch
    if wait <= 0:
        return "watch", clamp_poll_seconds(poll_seconds)
    return "wait", wait


def render_report(events: list[BabysitEvent], decision: WatchDecision, reason: str) -> str:
    """The watch's news as the text the agent reads — empty when none.

    When nothing changed and the watch continues, this is the empty
    string: the agent ends its turn without a message, never posting
    or saying "still waiting".
    """
    if decision == "continue" and not events:
        return ""
    lines = [f"Babysit: {decision} — {reason}"]
    for event in events:
        before = event.previous_state or "new"
        line = f"- {event.check_name}: {before} → {event.state}"
        if event.failure_kind is not None:
            line += f" ({event.failure_kind}: {event.reason})"
        lines.append(line)
    return "\n".join(lines)


@dataclass
class BabysitWatcher:
    """One watch on one PR, held by the capability for one run.

    The watcher is state, not a loop: the agent hands it a snapshot
    whenever the monitor wakes it, and the watcher says what changed
    and what to do next. Only the thread that owns the PR watches it —
    a second watch on another PR is refused, and a delegated child
    must never start one.
    """

    repo: str = ""
    pr_number: int = 0
    head_sha: str = ""
    started_at: datetime | None = None
    last_checks: dict[str, BabysitCheck] = field(default_factory=dict)
    active: bool = False

    def start(self, repo: str, pr_number: int, head_sha: str, now: datetime) -> str | None:
        """Claim this watch, or refuse it with the reason.

        Starting the same PR again is a no-op — a resume re-claims
        its own watch. Starting another PR while one is active is
        refused: one watcher per PR, and one watch per run.
        """
        if self.active and (self.repo, self.pr_number) != (repo, pr_number):
            return (
                f"Already watching {self.repo}#{self.pr_number}; stop it "
                "before watching another PR. One watcher per PR, and only "
                "the thread that owns the PR watches it."
            )
        if not self.active:
            self.repo = repo
            self.pr_number = pr_number
            self.head_sha = head_sha
            self.started_at = now
            self.last_checks = {}
            self.active = True
        return None

    def check(
        self,
        head_sha: str,
        checks: list[BabysitCheck],
        *,
        now: datetime,
        poll_interval_seconds: int,
        max_watch_minutes: int,
    ) -> dict[str, Any]:
        """One snapshot in, the news and the decision out.

        Green and expiry end the watch here: the agent reports and
        stops, it does not keep polling a finished PR.
        """
        head_moved = self.active and self.head_sha not in ("", head_sha)
        events = diff_checks(self.last_checks, checks, head_sha)
        decision, reason = decide_watch(
            checks,
            head_moved=head_moved,
            started_at=self.started_at,
            now=now,
            max_watch_minutes=max_watch_minutes,
        )
        self.head_sha = head_sha
        self.last_checks = {check.name: check for check in checks}
        if decision in ("green", "expired"):
            self.active = False
        return {
            "repo": self.repo,
            "pr_number": self.pr_number,
            "head_sha": head_sha,
            "head_moved": head_moved,
            "events": [event.to_dict() for event in events],
            "decision": decision,
            "reason": reason,
            "report": render_report(events, decision, reason),
            "next_poll_seconds": (
                clamp_poll_seconds(poll_interval_seconds)
                if decision in ("continue", "head_moved")
                else 0
            ),
        }

    def stop(self, reason: str) -> dict[str, Any]:
        """End the watch: ready, blocked, or asking the user.

        A merge or close ends the watch on its own; this is for the
        agent stopping first, so the thread does not stay in Working
        out of the user's inbox.
        """
        was_active = self.active
        self.active = False
        return {
            "stopped": was_active,
            "repo": self.repo,
            "pr_number": self.pr_number,
            "reason": reason or "stopped watching",
        }


def now_utc() -> datetime:
    """The current time, for watch starts and rate-limit math."""
    return datetime.now(UTC)
