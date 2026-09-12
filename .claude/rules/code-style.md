---
description: Code style, formatting, naming, imports, and type hints
paths: ["backend/**/*.py", "scripts/**/*.py", "*.py"]
---

# Code Style

## Formatting

- Use `ruff` for linting and formatting: `ruff check . --fix && ruff format .`
- Line length: 120 characters

## Type Hints

- Type hints on ALL function signatures — parameters and return types
- Use modern syntax: `str | None` not `Optional[str]`, `list[User]` not `List[User]`
- Use `Annotated[Type, Depends(...)]` for DI (defined as aliases in `deps.py`)
- Use a model or `TypedDict` for known structures and a precise value type for mappings.
  Use `Any` only at a boundary that genuinely requires it, not as a generic shortcut.
- Use `Literal["value1", "value2"]` for string enums in schemas
- Use `TYPE_CHECKING` block for circular import resolution:
  ```python
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from app.db.models.session import Session
  ```

## Naming

| Element | Convention | Example |
|---------|-----------|---------|
| Files | snake_case | `user_repo.py`, `conversation_service.py` |
| Classes | PascalCase | `UserService`, `ConversationRead` |
| Functions/variables | snake_case | `get_by_id`, `user_service` |
| Constants | UPPER_CASE | `DEFAULT_SYSTEM_PROMPT` |
| Private | _leading_underscore | `_create_agent` |
| DB tables | snake_case plural | `users`, `conversations` |
| API URLs | kebab-case | `/api/v1/conversations` |

## Imports — strictly ordered, separated by blank lines

```python
# 1. Standard library
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

# 2. Third-party
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# 3. Local application
from app.api.deps import CurrentUser, UserSvc
from app.core.exceptions import NotFoundError
from app.schemas.user import UserCreate, UserRead
```

## Comments

Explain non-obvious constraints, invariants and decisions that are not apparent
from the code. Keep comments proportional to the explanation needed; do not force
all reasoning into a one-line comment or a function docstring.

Put API contracts and generated reference documentation in docstrings. Avoid
comments that merely repeat the code, section labels and ASCII banners (checked by
`scripts/check_comments.py`). Remove commented-out code. Apply these conventions
to code being changed rather than sweeping unrelated files.

## Dead code

- No unused function, parameter, branch or import. `make lint` runs `vulture` as
  a gate on what it is certain of (unused variables, parameters); `make dead-code`
  is the deeper, human-read scan for unused functions and methods — noisier,
  because the codebase is registry-driven, so read each finding before deleting.
- False positives that are genuinely reachable (a dynamic dispatch vulture cannot
  follow) go in `ignore_names` under `[tool.vulture]` in `backend/pyproject.toml`,
  each with a comment saying what uses it.
- The same question about the manifest: `make lint` runs `deptry`, which fails on a
  distribution declared in `backend/pyproject.toml` that nothing under `app/` imports.
  A dependency that is genuinely required and genuinely unimported — a driver a URL
  scheme selects, a server run as a process — goes in `per_rule_ignores.DEP002` under
  `[tool.deptry]`, each with a comment saying who needs it.

## Other Conventions

- `datetime.now(UTC)` not `datetime.utcnow()`
- `secrets.compare_digest()` for constant-time comparisons
- `__repr__` on all DB models
- Async I/O throughout (PostgreSQL via asyncpg)
- Keyword-only args in repo functions after `db` parameter
