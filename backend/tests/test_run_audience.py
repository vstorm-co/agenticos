"""Who a run is being heard by, and how that is derived.

One fact, read by everything that must not say a personal thing out loud: memory
decides which store it may touch from it, conversation search decides whether it
has a corpus at all. So the derivation is tested on its own rather than inside
either of them - a mistake here is a mistake in both at once.

The trap it exists for is `user_id` on a hosted or embedded surface, where it is
the *publisher* standing in for whoever is typing. Keying on it there collapses
every visitor onto the owner, which is a cross-person leak rather than a missing
feature.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from app.agents.audience import RunAudience, derive_audience

PERSON = uuid4()
ROOM = "room:slack:C1"


class TestDeriving:
    def test_a_real_subject_is_the_person_this_run_answers(self):
        audience = derive_audience(
            user_id=PERSON, subject_is_publisher_fallback=False, room_key=None
        )

        assert audience == RunAudience(user_id=PERSON, room_key=None)

    def test_a_publisher_standing_in_for_a_visitor_is_nobody(self):
        """The whole reason this is a function rather than a constructor. On an
        embed the run carries the publisher's id, and treating that as the asker
        hands every visitor the owner's memory and the owner's conversations."""
        audience = derive_audience(
            user_id=PERSON, subject_is_publisher_fallback=True, room_key=None
        )

        assert audience.user_id is None

    def test_a_publisher_in_a_room_still_has_the_room(self):
        """The room is a fact about where the answer is going, not about who asked,
        so it survives an anonymous speaker."""
        audience = derive_audience(
            user_id=PERSON, subject_is_publisher_fallback=True, room_key=ROOM
        )

        assert audience == RunAudience(user_id=None, room_key=ROOM)

    def test_no_subject_at_all_is_nobody(self):
        assert (
            derive_audience(
                user_id=None, subject_is_publisher_fallback=False, room_key=None
            ).user_id
            is None
        )

    def test_a_direct_message_is_the_same_audience_as_web_chat(self):
        """A linked chat account already runs as its own app user, so both surfaces
        derive one person and no room - which is what makes an agent remember the
        same person across their browser and their DMs."""
        web = derive_audience(user_id=PERSON, subject_is_publisher_fallback=False, room_key=None)
        direct = derive_audience(user_id=PERSON, subject_is_publisher_fallback=False, room_key=None)

        assert web == direct


class TestPrivacy:
    def test_one_person_and_no_room_is_private(self):
        assert RunAudience(user_id=PERSON).private

    def test_a_room_is_never_private_even_though_the_speaker_is_known(self):
        """The answer is posted where the whole channel reads it, so knowing who
        asked is not the same as being alone with them."""
        assert not RunAudience(user_id=PERSON, room_key=ROOM).private

    def test_nobody_at_all_is_private_and_still_reaches_nothing(self):
        """Private is about who else is listening, not about whether there is
        anything to read - an anonymous run is alone with a visitor it cannot
        name, and every caller checks for the person separately."""
        anonymous = RunAudience()

        assert anonymous.private
        assert anonymous.user_id is None

    def test_it_cannot_be_edited_mid_run(self):
        """Frozen because a tool that could rewrite the audience could widen what
        it may read - the field is the security boundary, not a scratch pad."""
        audience = RunAudience(user_id=PERSON)

        with pytest.raises(FrozenInstanceError):
            audience.user_id = uuid4()  # ty: ignore[invalid-assignment]
