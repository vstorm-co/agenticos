"""What else depends on a table, asked before a change removes something it uses.

Workflows, views and triggers will name tables and columns. None exists yet, so
nothing is registered and every change is allowed; the hook is here so that the
day one does, archiving a column it reads is refused instead of silently breaking
it. A feature that depends on tables registers a checker at import time:

```python
async def workflow_dependents(db, *, organization_id, table_id, column_ids):
    ...
    return [Dependent(kind="workflow", id=workflow.id)]

register_dependency_checker(workflow_dependents)
```

`column_ids` is the set of columns a schema change archives, or `None` when the
whole table is being archived.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class Dependent:
    """One thing that names the table or a column of it."""

    kind: str
    id: UUID


class DependencyChecker(Protocol):
    """A feature's answer to "does anything of mine use this?"."""

    async def __call__(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        table_id: UUID,
        column_ids: frozenset[UUID] | None,
    ) -> list[Dependent]: ...


_checkers: list[DependencyChecker] = []


def register_dependency_checker(checker: DependencyChecker) -> None:
    """Add a feature's checker. Called once, when the feature's module is imported."""
    _checkers.append(checker)


async def find_dependents(
    db: AsyncSession,
    *,
    organization_id: UUID,
    table_id: UUID,
    column_ids: frozenset[UUID] | None,
) -> list[Dependent]:
    """Everything registered checkers say depends on what is about to be removed."""
    found: list[Dependent] = []
    for checker in _checkers:
        found.extend(
            await checker(
                db, organization_id=organization_id, table_id=table_id, column_ids=column_ids
            )
        )
    return found
