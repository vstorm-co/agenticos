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

**And the refusal, not the server** - in `message` as much as in `details`, since
the envelope carries both and the handler logs both on one line. `str(exc)` from a
vendor SDK is not a controlled string - provider clients put the failing request
URL in the message and a URL carries a key in its query string - and an absolute
path says where the container keeps its files. Neither is deleted: it goes in the
`logger.exception` line beside the raise, and the refusal names what the reader
can act on (#342). A URL the refusal is *about* is named by its field rather than
repeated - `refused_field("base_url", ...)`, never the endpoint with the password
still in it. An audit entry is `details` with a longer life and takes the same
rule: `{"fields": sorted(update_data)}`, not the body that was submitted (#412).

**A refusal that names a field says so in one shape, and `app/core/field_errors.py`
is the only place it is built.** `details={"fields": [{"field", "message"}]}` is
what `fieldProblems` in `frontend/src/lib/api-error.ts` reads, and it is the
whole reason for naming a field at all - a form marks the input rather than
showing a sentence somebody has to re-scan the page for. Three entry points:

```python
# A rule stated in prose. The sentence is the envelope's and the field's - one
# argument, so they cannot drift apart. Returns the exception; you raise it.
raise refused_field("base_url", "A model endpoint must include a host")

# A pydantic model a service validated itself, below what the form calls it.
raise BadRequestError(message=..., details={"fields": field_problems(exc.errors(), root="yaml")})
```

`request_field_problems` is the third and belongs to
`validation_exception_handler` alone. `field_details` builds the same `details`
without the exception, for a raiser that needs another status or that may have
no field to name.

**Name a field only when the caller sent it in that request.** A refusal about a
value nobody submitted - a remote file's name chosen by whoever shares the synced
folder, a stored row a worker read back - names none. Nor does a conflict:
`AlreadyExistsError` reports a fact about a row that exists, and which of a
form's inputs produced the taken value is the form's to say, through
`submitFailure`'s `identifiedBy` on the client. A singular `details={"field": ...}`
is the shape #891 removed; do not bring it back.

Exception handlers in `api/exception_handlers.py` automatically:
- Map to HTTP status codes
- Log with structured context (path, method, error code)
- Return consistent JSON error format, `details` included
- Add `WWW-Authenticate: Bearer` header on 401

**A column that holds a failure takes the same rule, and takes it harder.**
`rag_documents.error_message`, `sync_logs.error_message` and
`sync_sources.last_error` are rendered in the product to everyone who can see
the collection, and a body is read once where a row is read weeks later. So
`error_message=str(exc)` is the same defect as `details={"error": str(e)}`, and
`app/services/rag/failures.py` is the answer to it: what the stage was, what
class of thing raised, and what the reader can do - with the client's own text
in the `logger.exception` beside the call, never in the column (#423). Our own
refusals - an `AppException`, a `BudgetExceeded` - are passed through whole,
because their messages are written in this repository. A bare `RuntimeError`
we raised is not: one of them interpolates the absolute path of a temporary
file.

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
`CurrentSuperuser` no longer exist - the `users.role` column was dropped before
the migration chain was squashed, so `0001_baseline` simply creates `users`
without it. Do not reintroduce them.
