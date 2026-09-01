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

import hashlib
from enum import IntEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class LockScope(IntEnum):
    """What a lock is about. The value is half of the advisory key."""

    #: How many organizations one account may own.
    ORGANIZATIONS_PER_USER = 1
    #: How many agents one organization may hold.
    AGENTS_PER_ORGANIZATION = 2
    #: Which teardown gets to decide whether a physical vector table is still
    #: referenced. `collection_name` is not tenant-unique (#913), so two
    #: teardowns can be about one table.
    COLLECTION_NAME = 3
    #: Which of a member's accounts on one service is the default. The partial
    #: unique index allows one, and the write is read-then-clear-then-set - so
    #: two nominations racing each found no sibling to clear and both set it.
    MCP_DEFAULT_ACCOUNT = 4


def _key(subject: UUID) -> int:
    """A UUID as the signed 32-bit integer `pg_advisory_xact_lock` takes.

    A hash, so a collision is possible: two subjects sharing a key serialize
    against each other, which costs a moment of waiting and cannot produce a wrong
    answer. The low bits of a v4 UUID are random, which is what makes that rare.
    """
    return (subject.int & 0xFFFFFFFF) - 0x80000000


def _name_key(subject: str) -> int:
    """A name as the integer the lock takes, with the same collision bargain.

    `blake2b` rather than `hash()`, which is salted per process: two workers
    would key one collection differently and the lock would serialize nothing.
    """
    digest = hashlib.blake2b(subject.encode(), digest_size=4).digest()
    return int.from_bytes(digest, "big") - 0x80000000


async def hold_name(db: AsyncSession, scope: LockScope, subject: str) -> None:
    """Take the lock for one named subject, until this transaction ends.

    The string half of :func:`hold_subject`, for a subject that is a name rather
    than a row - a collection name, which several rows can claim.
    """
    await db.execute(select(func.pg_advisory_xact_lock(scope.value, _name_key(subject))))


async def hold_subject(db: AsyncSession, scope: LockScope, subject: UUID) -> None:
    """Take the lock for one subject, until this transaction ends.

    Blocks while another transaction holds the same one. Call it *before* reading
    the count it protects: taken afterwards it serializes nothing, because the
    count both callers read is already stale.
    """
    await db.execute(select(func.pg_advisory_xact_lock(scope.value, _key(subject))))
