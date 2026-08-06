---
description: Exception handling patterns and security conventions
globs: ["backend/app/core/**/*.py", "backend/app/services/**/*.py"]
---

# Exceptions & Security

## Domain Exceptions (`app/core/exceptions.py`)

All extend `AppException`. Always pass `message` and `details`:

```python
raise NotFoundError(message="User not found", details={"user_id": user_id})
raise AlreadyExistsError(message="Email already registered", details={"email": email})
raise AuthenticationError(message="Invalid or expired token")
raise AuthorizationError(message="Role 'admin' required for this action")
```

**Put the value in `details`, not a string of it.** The handler encodes with
`jsonable_encoder`, the same one `response_model` uses, so a `UUID`, `datetime`,
`Enum` or nested structure reaches the wire the way it does everywhere else. This
example used to say `str(user_id)` while the code said `user_id`, and the code was
right: stringifying is a rule only review can enforce, and the call site that forgets
turns a clean 404 into a bodiless 500 (#307). Money is the one exception - a `Decimal`
encodes to a float, so a cost or a cap is stringified deliberately by the raiser.

**A value, not a row.** `details` is serialized into the response body, and
`jsonable_encoder` reaches an object it does not recognise through `vars()` - so
`details={"user": user}` puts `hashed_password` on the wire, where `details={"user_id":
user.id}` puts an id. Name the field that explains the refusal; never hand it a
SQLAlchemy row, a settings object, an upstream client or an exception instance. The
same applies to the caller's own input: `exc.errors(include_url=False,
include_input=False)` - a form needs to know which field is wrong, not to be sent a
copy of what it posted.

**And the refusal, not the server.** `str(exc)` from a vendor SDK is not a
controlled string - provider clients put the failing request URL in the message and
a URL carries a key in its query string - and an absolute path says where the
container keeps its files. Neither is deleted: it goes in the `logger.exception`
line beside the raise, and `details` names what the reader can act on (#342). A URL
the refusal is *about* is named by its field rather than repeated, because the
handler logs `details` too - `{"field": "base_url"}`, never the endpoint with the
password still in it. An audit entry is `details` with a longer life and takes the
same rule: `{"fields": sorted(update_data)}`, not the body that was submitted.

Exception handlers in `api/exception_handlers.py` automatically:
- Map to HTTP status codes
- Log with structured context (path, method, error code)
- Return consistent JSON error format, `details` included
- Add `WWW-Authenticate: Bearer` header on 401

## Security Patterns

JWT auth (`core/security.py`):
- `create_access_token(subject)` / `create_refresh_token(subject)` — encode with `jwt.encode()`
- `verify_token(token)` → `dict | None` — decode with `jwt.decode()`
- Token payload: `{"exp": ..., "sub": user_id, "type": "access"|"refresh"}`

Password hashing:
- `get_password_hash(password)` — bcrypt
- `verify_password(plain, hashed)` — bcrypt `checkpw`
- NEVER store plain passwords

API keys:
- `secrets.compare_digest()` for constant-time comparison
- `APIKeyHeader(name=settings.API_KEY_HEADER, auto_error=False)`

## Authorization

There is no role column on the user and no role-based dependency. Two aliases,
and only two:

```python
CurrentUser = Annotated[User, Depends(get_current_user)]      # any signed-in user
CurrentAppAdmin = Annotated[User, Depends(_require_app_admin)] # the deployment's superadmin
```

Everything inside an organization is a permission from
`app/core/permissions.py`:

```python
# A permission, on a collection route.
@router.post("/agents", dependencies=[Depends(require(Perm.AGENTS_EDIT))])
async def create_agent(...) -> Any: ...

# A permission on one row - in the service, never as a route gate.
if not await resolve_access(db, ctx, agent, Perm.AGENTS_EDIT, resource_type=AGENT):
    raise AuthorizationError(message="...")
```

`require(...)` belongs on collection routes only. A role gate cannot see the
grants on a row, so on a per-resource route it refuses a Viewer holding an
explicit `edit` grant before `resolve_access` can widen their access.

`UserRole`, `User.has_role()`, `RoleChecker`, `CurrentAdmin` and
`CurrentSuperuser` no longer exist - the `users.role` column was dropped in
migration `0066`. Do not reintroduce them.
