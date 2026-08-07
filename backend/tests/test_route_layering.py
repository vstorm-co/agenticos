"""A route may not read a repository, and this is what makes that true.

`CLAUDE.md` and `.claude/rules/architecture.md` both state it plainly - routes call
services only, never a repository - and the rule had drifted in five modules at once
by the time anybody read for it. Nothing was leaking: each handler passed the scope
it happened to know as a keyword argument. That is the cost, though. A scope a
handler fills in itself is a scope no service test can see, and the next filter
added to the entity is added in the service while the route keeps answering its own
way (#197, #232).

The alternative to a test is somebody running `rg 'from app.repositories'` over the
route tree and noticing. That is how these five were found, which is precisely why
it is not a plan.

The allowlist below is checked in both directions: an entry that no longer applies
fails just as loudly as an import that is not on it, so it cannot quietly become a
list of things nobody has looked at since.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
ROUTES = BACKEND_ROOT / "app" / "api" / "routes"

# What a route module may still take from `app.repositories`, and why. A name here
# has to be something other than data access - importing a *function* that reads
# rows is the thing this test exists to refuse.
ALLOWED = {
    # A `Literal` of the sort orders the skill list accepts. It lives beside the
    # query it parameterises and reaches the route as a type, not as a row.
    ("app/api/routes/v1/skills.py", "SkillSort"),
    # Two frozen value objects holding what a caller asked to narrow by - nine
    # fields for run history, four for the approvals queue. They live beside the
    # queries they parameterise because each field becomes a `WHERE` clause, and
    # they exist as one value rather than nine keyword arguments precisely so a
    # filter cannot reach the page and miss the count. Neither reads a row, and
    # the tenant scope is still the service's answer: these can only ever shrink
    # what a caller already had access to.
    ("app/api/routes/v1/runs.py", "RunFilters"),
    ("app/api/routes/v1/runs.py", "ApprovalFilters"),
}


def _repository_imports(path: Path) -> list[str]:
    """Every name a module takes from `app.repositories`, however it asks for it."""
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.repositories"):
            names.extend(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.extend(
                alias.asname or alias.name
                for alias in node.names
                if alias.name.startswith("app.repositories")
            )
    return names


def _found() -> set[tuple[str, str]]:
    return {
        (str(path.relative_to(BACKEND_ROOT)), name)
        for path in sorted(ROUTES.rglob("*.py"))
        for name in _repository_imports(path)
    }


def test_no_route_module_imports_a_repository() -> None:
    unexpected = sorted(_found() - ALLOWED)
    assert not unexpected, (
        f"route modules import repositories: {unexpected}. Routes call services only - "
        "move the read into the service that owns the entity, so the scope is the "
        "service's answer rather than a keyword argument a handler filled in."
    )


def test_the_allowlist_holds_nothing_that_has_already_been_moved() -> None:
    """An exemption for an import that is gone is an exemption nobody is reading."""
    stale = sorted(ALLOWED - _found())
    assert not stale, f"these are no longer imported and the exemption can go: {stale}"
