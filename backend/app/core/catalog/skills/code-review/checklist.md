# Review checklist

Work through this once, at the end, on the whole change.

## Correctness
- [ ] Every new behaviour has a test that fails without it.
- [ ] Every bug fix has a regression test naming the bug.
- [ ] Edge cases: empty collection, single element, duplicate, missing row.
- [ ] Errors are raised with a message that says what to do next.

## Data
- [ ] Migrations have a working `downgrade`.
- [ ] A destructive migration is separate from the code that needs it.
- [ ] Queries that take an id also take the tenant.

## Security
- [ ] No secret in the diff, including fixtures and snapshots.
- [ ] Anything user-supplied that reaches SQL, a shell or a path is validated.
- [ ] A new endpoint states which permission it needs.

## Readability
- [ ] Names say what the thing is, not what type it has.
- [ ] Comments explain why, never restate what.
- [ ] No commented-out code, no unused parameters.
