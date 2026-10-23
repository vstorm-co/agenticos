"""The morning briefing of what a person's watches found (#2301).

What is asserted is what the person receives: one notification and one direct
message listing what is new, in their language, never the same finding twice,
and nothing at all for somebody who left or has nothing waiting.
"""

import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.proactive import _briefing
from app.services.proactive._briefing import LISTED, _message, brief
from app.services.proactive.facade import ProactiveService
from app.worker.tasks import proactive_tasks

pytestmark = pytest.mark.anyio

BRIEFING = "app.services.proactive._briefing"
ORG = uuid.uuid4()
USER = uuid.uuid4()
NOW = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)


class TestTheMessage:
    def test_it_lists_what_is_new_and_where_the_rest_is(self):
        text = _message("pl", ["Review #12", "ENG-412"], "https://os.example/inbox")
        assert text.splitlines() == [
            "Znaleziska z twoich obserwacji (2):",
            "• Review #12",
            "• ENG-412",
            "Wszystko w twoim inboksie: https://os.example/inbox",
        ]

    def test_a_long_list_is_cut_and_says_how_many_more(self):
        titles = [f"Item {n}" for n in range(LISTED + 2)]
        text = _message("de", titles, "u")
        assert text.count("•") == LISTED
        assert "…und 2 weitere." in text

    def test_a_language_it_was_not_written_in_reads_english(self):
        assert _message("ja", ["x"], "u").startswith("1 new from your watches:")
        assert _message(None, ["x"], "u").startswith("1 new from your watches:")


class TestSendingIt:
    @staticmethod
    def _patches(*, user=True, member=True, findings=None):
        person = MagicMock(id=USER, is_active=True, locale="en", email="ada@acme.test")
        if user == "inactive":
            person.is_active = False
        return (
            patch(
                f"{BRIEFING}.user_repo.get_by_id",
                new=AsyncMock(return_value=person if user else None),
            ),
            patch(
                f"{BRIEFING}.member_repo.get_active",
                new=AsyncMock(return_value=MagicMock() if member else None),
            ),
            patch(
                f"{BRIEFING}.suggestion_repo.unbriefed_findings",
                new=AsyncMock(return_value=findings or []),
            ),
        )

    async def test_what_waits_is_announced_messaged_and_never_sent_again(self):
        findings = [MagicMock(id=uuid.uuid4(), title=f"Finding {n}") for n in range(2)]
        briefing = AsyncMock()
        direct = AsyncMock(return_value=1)
        mark = AsyncMock()
        with ExitStack() as stack:
            for each in (
                *self._patches(findings=findings),
                patch(f"{BRIEFING}.NotificationService", return_value=MagicMock(briefing=briefing)),
                patch(f"{BRIEFING}.direct_message", new=direct),
                patch(f"{BRIEFING}.suggestion_repo.mark_briefed", new=mark),
            ):
                stack.enter_context(each)
            assert await brief(MagicMock(), ORG, USER, now=NOW) == 2

        assert briefing.await_args.kwargs == {
            "organization_id": ORG,
            "user_id": USER,
            "count": 2,
            "now": NOW,
        }
        (_db, org, email, text_for) = direct.await_args.args
        assert (org, email) == (ORG, "ada@acme.test")
        assert "• Finding 0" in text_for(MagicMock()) and "/inbox" in text_for(MagicMock())
        assert mark.await_args.kwargs == {
            "suggestion_ids": [finding.id for finding in findings],
            "at": NOW,
        }

    @pytest.mark.parametrize("case", ["no-account", "inactive", "left", "nothing-waiting"])
    async def test_nothing_is_sent_to_whoever_should_not_get_one(self, case):
        direct = AsyncMock()
        with ExitStack() as stack:
            for each in (
                *self._patches(
                    user={"no-account": False, "inactive": "inactive"}.get(case, True),
                    member=case != "left",
                ),
                patch(f"{BRIEFING}.direct_message", new=direct),
            ):
                stack.enter_context(each)
            assert await brief(MagicMock(), ORG, USER, now=NOW) == 0
        direct.assert_not_awaited()

    async def test_the_facade_and_the_worker_hand_it_on(self):
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=MagicMock())
        context.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(_briefing, "brief", new=AsyncMock(return_value=3)) as briefed,
            patch.object(proactive_tasks, "get_db_context", return_value=context),
        ):
            assert await ProactiveService(MagicMock()).brief(ORG, USER) == 3
            payload = MagicMock(organization_id=ORG, user_id=USER)
            assert await proactive_tasks.brief_person(payload) == 3
        assert briefed.await_args.args[1:] == (ORG, USER)
