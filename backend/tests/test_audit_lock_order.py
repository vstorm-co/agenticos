"""`users` rows first, the audit chain last - in every transaction (#1763).

`record_audit` takes a transaction-scoped lock on an organization's audit chain,
and holds it to the end of the request. A caller that reaches for a `users` row
*after* it closes an ABBA cycle against `UserService.admin_delete`, which locks
every app admin's row exclusively first and takes the chain second:

    A  impersonation start   chain lock ──▶ key-share on each recipient's row
    B  an admin deleting     every admin's row ──▶ chain lock

Postgres detects it and aborts one side. Either the delete fails and is retried,
or - inside `write()`'s per-recipient savepoint - the mandatory security-event
notification for the surviving transaction is silently discarded while its audit
entry and the rest of that transaction commit. The second is the one worth the
guard: a lost mandatory notification is a lost side effect, not a retried
request.

The fix is an order rather than a lock: `hold_security_audience` /
`hold_configuration_audience` take the key-share locks the notification is about
to need, immediately before `record_audit` rather than after it. That is a
convention no type can express, so this reads the source - per function, because
a hold belonging to the function above would otherwise vouch for an audit below
it, which is exactly the regression this exists to catch.

Static, for the reason `test_security_marker.py` is: a runtime check would need
two concurrent transactions and a deadlock to observe, and would pass vacuously
whenever it did not get one.
"""

from __future__ import annotations

import ast
from functools import cache
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"

# The notification each pairing writes, and the hold that must precede it.
PAIRS = {
    "security_event": "hold_security_audience",
    "configuration_changed": "hold_configuration_audience",
}


@cache
def _parsed() -> tuple[tuple[Path, ast.Module], ...]:
    """Every application module, parsed once for the whole session.

    `notifications.py` is skipped: it defines these methods, and a definition is
    not a call site.
    """
    return tuple(
        (path, ast.parse(path.read_text()))
        for path in sorted(APP_ROOT.rglob("*.py"))
        if path.name != "notifications.py"
    )


def _functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _method_calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        call
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == name
    ]


def _plain_calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        call
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == name
    ]


def _functions_writing(
    notification: str,
) -> list[tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Every function that writes that notification, with the file it is in."""
    return [
        (path, function)
        for path, tree in _parsed()
        for function in _functions(tree)
        if _method_calls(function, notification)
    ]


@pytest.mark.parametrize("notification,hold", sorted(PAIRS.items()))
class TestEveryAuditedNotificationHoldsItsAudienceFirst:
    def test_some_function_writes_it(self, notification: str, hold: str) -> None:
        """Guards the sweep itself: no call sites would pass everything."""
        assert _functions_writing(notification)

    def test_each_one_holds_the_audience_in_the_same_function(
        self, notification: str, hold: str
    ) -> None:
        for path, function in _functions_writing(notification):
            assert _method_calls(function, hold), (
                f"{path.relative_to(APP_ROOT.parent)}:{function.lineno} writes {notification} "
                f"and never calls {hold}(). Take the audience's row locks before "
                "`record_audit`, not after it - see app/core/audit.py (#1763)."
            )

    def test_the_hold_comes_before_the_audit_entry_it_notifies_about(
        self, notification: str, hold: str
    ) -> None:
        """Per function, and by line: holding it afterwards serializes nothing,
        because the chain lock is already taken - which is the whole cycle."""
        for path, function in _functions_writing(notification):
            first_hold = min(call.lineno for call in _method_calls(function, hold))
            for audit in _plain_calls(function, "record_audit"):
                assert first_hold < audit.lineno, (
                    f"{path.relative_to(APP_ROOT.parent)}:{audit.lineno}: `record_audit` runs "
                    f"before this function's {hold}() (#1763)."
                )

    def test_the_write_takes_the_audience_that_was_locked(
        self, notification: str, hold: str
    ) -> None:
        """Resolving the audience a second time inside the write is how an admin
        promoted between the two arrives as a recipient whose row nothing
        holds - the cycle, reopened one row wide."""
        for path, function in _functions_writing(notification):
            for call in _method_calls(function, notification):
                assert any(keyword.arg == "recipients" for keyword in call.keywords), (
                    f"{path.relative_to(APP_ROOT.parent)}:{call.lineno}: {notification} is "
                    f"written without the set {hold}() locked (#1763)."
                )
