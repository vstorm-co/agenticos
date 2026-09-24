"""What else depends on a table, asked before a change removes something it uses.

A feature that names tables and columns - saved views today, workflows and
triggers later - registers a checker at import time, so archiving a column it
reads is refused instead of silently breaking it:

```python
async def workflow_dependents(db, *, organization_id, table_id, column_ids, subject_id):
    ...
    return [Dependent(kind="workflow", id=workflow.id)]

register_dependency_checker(workflow_dependents)
```

`column_ids` is the set of columns a schema change archives, or `None` when the
whole table is being archived. `subject_id` is the caller making the change: a
checker reports only dependents that caller can see. One it cannot see is not
the caller's to fix, so it neither blocks the change nor is disclosed by id, and
the feature owning it must tolerate the change instead (a saved view drops what
it names of a column that is no longer live when it is read).
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
        subject_id: UUID,
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
    subject_id: UUID,
) -> list[Dependent]:
    """Everything registered checkers say depends on what `subject_id` is about to remove."""
    found: list[Dependent] = []
    for checker in _checkers:
        found.extend(
            await checker(
                db,
                organization_id=organization_id,
                table_id=table_id,
                column_ids=column_ids,
                subject_id=subject_id,
            )
        )
    return found
