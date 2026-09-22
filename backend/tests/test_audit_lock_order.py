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
convention no type can express, so this reads the source: a module that writes a
mandatory notification after an audit entry must hold the audience first, as
many times as it audits.

Static, for the reason `test_security_marker.py` is: a runtime check would need
two concurrent transactions and a deadlock to observe, and would pass vacuously
whenever it did not get one.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"

# The notification each pairing writes, and the hold that must precede it.
PAIRS = {
    "security_event": "hold_security_audience",
    "configuration_changed": "hold_configuration_audience",
}


def _method_calls(tree: ast.AST, name: str) -> int:
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == name
    )


def _modules_writing(notification: str) -> list[Path]:
    """Every module that calls that notification on a service instance.

    `notifications.py` itself defines it and is skipped: a definition is not a
    call site, and it is the module the hold lives in.
    """
    found = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if path.name == "notifications.py":
            continue
        tree = ast.parse(path.read_text())
        if _method_calls(tree, notification):
            found.append(path)
    return found


@pytest.mark.parametrize("notification,hold", sorted(PAIRS.items()))
class TestEveryAuditedNotificationHoldsItsAudienceFirst:
    def test_some_module_writes_it(self, notification: str, hold: str) -> None:
        """Guards the sweep itself: no call sites would pass everything."""
        assert _modules_writing(notification)

    def test_each_module_holds_the_audience_as_often_as_it_audits(
        self, notification: str, hold: str
    ) -> None:
        for path in _modules_writing(notification):
            tree = ast.parse(path.read_text())
            writes = _method_calls(tree, notification)
            holds = _method_calls(tree, hold)
            assert holds >= writes, (
                f"{path.relative_to(APP_ROOT.parent)}: {writes} {notification} write(s) "
                f"and {holds} {hold}() call(s). Take the audience's row locks before "
                "`record_audit`, not after it - see app/core/audit.py (#1763)."
            )

    def test_the_hold_comes_before_the_audit_entry(self, notification: str, hold: str) -> None:
        """Holding it afterwards serializes nothing: the chain lock is already
        taken, which is the whole of the cycle."""
        for path in _modules_writing(notification):
            source = path.read_text()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "record_audit"
                ):
                    continue
                before = [
                    call.lineno
                    for call in ast.walk(tree)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == hold
                    and call.lineno < node.lineno
                ]
                assert before, (
                    f"{path.relative_to(APP_ROOT.parent)}:{node.lineno}: `record_audit` with "
                    f"no {hold}() before it in this module (#1763)."
                )
