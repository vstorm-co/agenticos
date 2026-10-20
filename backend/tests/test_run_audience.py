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

from app.agents.audience import (
    RunAudience,
    acting_for_no_person,
    derive_audience,
    for_no_person,
    run_person_for,
)
from app.db.models.agent_run import RunSurface

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


# Every kind of run and whether a member is behind it (D18, D18a). `public_origin`
# is what the runner has already worked out from the door the run came through;
# this function only combines it with the publisher-fallback rule.
_RUN_PERSON_TABLE = [
    pytest.param(RunSurface.WEB, False, False, PERSON, id="web chat"),
    pytest.param(RunSurface.API, False, False, PERSON, id="HTTP API, a signed-in member"),
    pytest.param(
        RunSurface.SLACK, False, False, PERSON, id="Slack / Telegram / Mattermost, linked sender"
    ),
    pytest.param(RunSurface.EMBED, True, False, None, id="widget, embed, unlinked channel sender"),
    pytest.param(
        RunSurface.SCHEDULE, True, False, PERSON, id='schedule, or "Run now" of any trigger'
    ),
    pytest.param(
        RunSurface.SCHEDULE,
        True,
        True,
        None,
        id="event trigger fired by a GitHub or GitHub App delivery",
    ),
    pytest.param(
        RunSurface.SCHEDULE, True, True, None, id="event trigger fired by an email delivery"
    ),
    pytest.param(
        RunSurface.SCHEDULE,
        True,
        True,
        None,
        id="event trigger fired by a webhook-relay delivery",
    ),
    pytest.param(
        RunSurface.WORKFLOW,
        False,
        False,
        PERSON,
        id="workflow agent.run, admitted by API, WebSocket, chat, schedule or a private chain",
    ),
    pytest.param(
        RunSurface.WORKFLOW,
        False,
        False,
        PERSON,
        id="workflow agent.run, admitted by run_workflow from a run with a person",
    ),
    pytest.param(
        RunSurface.WORKFLOW, False, True, None, id="workflow agent.run, admitted by a webhook"
    ),
    pytest.param(
        RunSurface.WORKFLOW, False, True, None, id="workflow agent.run, admitted by a form"
    ),
    pytest.param(
        RunSurface.WORKFLOW,
        False,
        True,
        None,
        id="workflow agent.run, admitted by a channel message",
    ),
    pytest.param(
        RunSurface.WORKFLOW, False, True, None, id="workflow agent.run, admitted by Gmail"
    ),
    pytest.param(
        RunSurface.WORKFLOW, False, True, None, id="workflow agent.run, admitted by GitHub"
    ),
    pytest.param(
        RunSurface.WORKFLOW,
        False,
        True,
        None,
        id="workflow agent.run in any run of a public chain",
    ),
    pytest.param(
        RunSurface.WORKFLOW,
        False,
        True,
        None,
        id="workflow agent.run in a table run fired by a record a no-person run wrote",
    ),
    pytest.param(
        RunSurface.WORKFLOW,
        False,
        True,
        None,
        id="any workflow run with no active dispatch",
    ),
]


class TestTheRunPerson:
    @pytest.mark.security
    @pytest.mark.parametrize(
        ("surface", "fallback", "public_origin", "expected"), _RUN_PERSON_TABLE
    )
    def test_run_person_for(self, surface, fallback, public_origin, expected):
        """A member is behind a run only when one wrote its input or set it up.

        A schedule's creator counts even though they stand in as a publisher
        fallback - they set the run up and answer for it. An outsider's input
        never does, whoever the run executes as."""
        assert (
            run_person_for(
                user_id=PERSON,
                subject_is_publisher_fallback=fallback,
                surface=surface,
                public_origin=public_origin,
            )
            == expected
        )

    def test_no_subject_is_no_person(self):
        assert (
            run_person_for(
                user_id=None,
                subject_is_publisher_fallback=False,
                surface=RunSurface.WEB,
                public_origin=False,
            )
            is None
        )

    def test_the_no_person_flag_is_scoped_to_its_block(self):
        """Read by a record write to mark what a run with no person wrote, so it
        must not outlive the run that set it - not even one that raised."""
        assert for_no_person() is False

        with acting_for_no_person(True):
            assert for_no_person() is True
            with acting_for_no_person(False):
                assert for_no_person() is False
            assert for_no_person() is True
        assert for_no_person() is False

        with pytest.raises(RuntimeError), acting_for_no_person(True):
            raise RuntimeError("the run failed")
        assert for_no_person() is False
