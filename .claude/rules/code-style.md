---
description: Code style, formatting, naming, imports, and type hints
globs: ["backend/**/*.py", "*.py"]
---

# Code Style

## Formatting

- Use `ruff` for linting and formatting: `ruff check . --fix && ruff format .`
- Line length: 120 characters

## Type Hints

- Type hints on ALL function signatures — parameters and return types
- Use modern syntax: `str | None` not `Optional[str]`, `list[User]` not `List[User]`
- Use `Annotated[Type, Depends(...)]` for DI (defined as aliases in `deps.py`)
- Use `dict[str, Any]` for generic dicts
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

Comments are scarce and earn their place. **The default is no comment.** The
reference docs are generated from docstrings, so what reasoning a piece of code
needs lives in a docstring, not in a running commentary of `#` lines.

The bar for a comment is one question: **would a competent reader make a mistake,
or be genuinely misled, without it?** If not, delete it. Clear names and small
functions carry the meaning; a comment is for the thing the code cannot say.

Delete a comment that:

- **Restates what the code does.** `# increment i`, `# loop over users`.
- **Labels a section.** `# the owner's side`, `# sending`, `# internals`,
  `# what the agent may ask` — the class, the method and their names already mark
  the structure. (ASCII-banner form — `# --- sending ---` — is rejected outright
  by `scripts/check_comments.py`; the plain-label form is the same slop without
  the dashes, so it goes too.)
- **Narrates an optimisation or a mechanism a reader already sees.** "In one
  query rather than an `EXISTS` per row." "Skipped when the page is empty —
  nothing to do." "Two queries, deduplicated on ids." The code says this; the
  comment is a second, staler copy.
- **Grows into a paragraph.** A multi-line essay is a docstring in the wrong
  place — move it, or cut it to the single clause that carries the *why*, or drop
  it. Most drop.

Keep a comment only when it prevents a real mistake: a footgun, a non-obvious
constraint, a security or correctness invariant that the code cannot express, or
a decision that looks wrong until you know the reason — ideally with the issue
number (`# … (#417)`). One tight sentence, not a paragraph.

**No commented-out code.** Git remembers it; delete it.

When in doubt, delete. A comment removed is cheap to bring back; a wall of
comments is what makes real code hard to find.

## Dead code

- No unused function, parameter, branch or import. `make lint` runs `vulture` as
  a gate on what it is certain of (unused variables, parameters); `make dead-code`
  is the deeper, human-read scan for unused functions and methods — noisier,
  because the codebase is registry-driven, so read each finding before deleting.
- False positives that are genuinely reachable (a dynamic dispatch vulture cannot
  follow) go in `ignore_names` under `[tool.vulture]` in `backend/pyproject.toml`,
  each with a comment saying what uses it.

## Other Conventions

- `datetime.now(UTC)` not `datetime.utcnow()`
- `secrets.compare_digest()` for constant-time comparisons
- `__repr__` on all DB models
- Async I/O throughout (PostgreSQL via asyncpg)
- Keyword-only args in repo functions after `db` parameter
