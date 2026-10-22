"""Whether an agent reaches people its knowledge does not (#2072)."""

import uuid

from app.services.knowledge_reach import _Reach

ALICE, BOB = uuid.uuid4(), uuid.uuid4()
FINANCE = uuid.uuid4()


def _shared(*, groups: tuple[uuid.UUID, ...] = (), people: tuple[uuid.UUID, ...] = ()) -> _Reach:
    return _Reach(everyone=False, group_ids=frozenset(groups), user_ids=frozenset(people))


EVERYONE = _Reach(everyone=True, group_ids=frozenset(), user_ids=frozenset())


def test_people_are_compared_by_who_they_are():
    """Codex on #2062: an agent shared with Alice over a source shared with Bob
    answered Alice from a source she cannot open, and no warning said so."""
    assert _shared(people=(ALICE,)).wider_than(_shared(people=(BOB,)))
    assert not _shared(people=(ALICE,)).wider_than(_shared(people=(ALICE, BOB)))


def test_a_group_the_source_lacks_is_wider():
    assert _shared(groups=(FINANCE,)).wider_than(_shared())
    assert not _shared(groups=(FINANCE,)).wider_than(_shared(groups=(FINANCE,)))


def test_everyone_on_either_side_decides():
    assert EVERYONE.wider_than(_shared(people=(ALICE,)))
    assert not _shared(people=(ALICE,)).wider_than(EVERYONE)
