"""Serializing a check-then-write that no constraint can express.

A ceiling read as `count(...) >= limit` and then acted on is two statements, and
under the default isolation two requests can both pass the count before either
inserts - so a deployment allowing five agents ends up with six, deterministically,
by clicking twice. A unique constraint cannot say "at most five rows like this",
and a table lock would serialize every organization against every other.

So the subject of the ceiling is locked instead: an advisory lock keyed on the
account or the organization the count is about. Two requests about the same subject
queue; requests about different subjects do not meet. It is **transaction-scoped**,
so it is released by the commit or the rollback and there is nothing to unlock -
which matters here because these are held across a create that can raise.

Advisory locks are Postgres-wide rather than per-table, which is why the key
carries a namespace: two unrelated ceilings must not block each other because a
UUID happened to hash the same way.
"""

from enum import IntEnum
from uuid import UUID

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession


class LockScope(IntEnum):
    """What a lock is about. The value is half of the advisory key."""

    #: How many organizations one account may own.
    ORGANIZATIONS_PER_USER = 1
    #: How many agents one organization may hold.
    AGENTS_PER_ORGANIZATION = 2
    #: A collection name's claim-and-create against its vector-table drop (#1355).
    COLLECTION_TEARDOWN = 3
    #: Which of a member's accounts on one service is the default. The partial
    #: unique index allows one, and the write is read-then-clear-then-set - so
    #: two nominations racing each found no sibling to clear and both set it.
    MCP_DEFAULT_ACCOUNT = 4
    #: One organization's audit hash chain. `record_audit` reads the chain head
    #: and appends under this lock, so two audited writes for the same org cannot
    #: read the same head and fork the chain (#1622).
    AUDIT_CHAIN_PER_ORG = 5
    #: Everything held *about* one person, against their erasure. A note is keyed
    #: by the string `person:<id>` with no foreign key, so a run writing one while
    #: the account is being deleted commits after the purge has read the table and
    #: recreates personal data about somebody who asked to be forgotten. The write
    #: and the purge take this, so one waits for the other and the write that loses
    #: finds no account to write about (#1421).
    PERSONAL_DATA_PER_USER = 6
    #: The live table names of one organization. A name is unique among live
    #: tables, and "is this name free" followed by an insert is two statements:
    #: without this two creates of one name both pass the check and the second
    #: dies on the unique index with a 500 instead of a 409 (#1782).
    VIRTUAL_TABLE_NAMES_PER_ORG = 7


def _key(subject: UUID) -> int:
    """A UUID as the signed 32-bit integer `pg_advisory_xact_lock` takes.

    A hash, so a collision is possible: two subjects sharing a key serialize
    against each other, which costs a moment of waiting and cannot produce a wrong
    answer. The low bits of a v4 UUID are random, which is what makes that rare.
    """
    return (subject.int & 0xFFFFFFFF) - 0x80000000


async def hold_subject(db: AsyncSession, scope: LockScope, subject: UUID) -> None:
    """Take the lock for one subject, until this transaction ends.

    Blocks while another transaction holds the same one. Call it *before* reading
    the count it protects: taken afterwards it serializes nothing, because the
    count both callers read is already stale.

    Both keys are cast to `Integer`, which is what selects the two-argument
    `pg_advisory_xact_lock(int, int)` overload. Without it a key of exactly
    `-2147483648` - the value `_key` returns for a subject whose low 32 bits are
    zero, which the deployment-wide audit chain hits deterministically - binds as
    `bigint`, and `(int, bigint)` matches no overload (#1622).
    """
    await db.execute(
        select(func.pg_advisory_xact_lock(cast(scope.value, Integer), cast(_key(subject), Integer)))
    )


async def hold_name(db: AsyncSession, scope: LockScope, name: str) -> None:
    """Take the lock for a string subject - a collection name - until this tx ends.

    The subject here is not a row's id but a name in the deployment-global vector
    namespace, so the key is `hashtext(name)` rather than a UUID's low bits. Same
    contract as :func:`hold_subject`: call it *before* the check it protects, so a
    claim that reads "this name is free" and a teardown that reads "no base holds
    this name" cannot both act - one drops the table the other just created (#1355).
    Collisions cost a moment of waiting against an unrelated name, never a wrong
    answer, because `hashtext` and the scope are the whole key.
    """
    await db.execute(select(func.pg_advisory_xact_lock(scope.value, func.hashtext(name))))


async def try_hold_name(db: AsyncSession, scope: LockScope, name: str) -> bool:
    """Take the lock for a string subject if it is free, without ever waiting.

    :func:`hold_name` for a caller that already holds a lock the other side takes
    *second*. Waiting there is the ABBA deadlock the lock order exists to avoid,
    so the only answer such a caller can act on is "free, and now mine" or "held
    by somebody, right now" - never "held, and I will wait to find out".

    True means this transaction holds it until it ends, exactly as `hold_name`
    would. False means another transaction does, and the caller has to decide
    what to do about that rather than block.
    """
    result = await db.execute(
        select(func.pg_try_advisory_xact_lock(scope.value, func.hashtext(name)))
    )
    return bool(result.scalar_one())
