"""A person's suggestions: reading them, accepting and declining (#2301).

Accepting a profile update writes it, exactly as the profile form would;
accepting a role pack only queues it - the routines are made in the background;
anything else is the console's to carry out, so accepting records the decision.
Nobody reaches a suggestion made to somebody else, or one already decided.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.suggestion import Suggestion, SuggestionStatus
from app.main import app
from app.services.suggestions import SuggestionService

pytestmark = pytest.mark.anyio

SERVICE = "app.services.suggestions"
ORG = uuid.uuid4()
USER = uuid.uuid4()
CTX = AuthContext(user_id=USER, organization_id=ORG, role=OrgRoleName.MEMBER)


def _suggestion(kind: str, payload: dict, *, status: str = "open") -> Suggestion:
    return Suggestion(
        id=uuid.uuid4(),
        organization_id=ORG,
        user_id=USER,
        kind=kind,
        title="t",
        detail=None,
        payload=payload,
        dedupe_key=f"{kind}:x",
        status=status,
        created_at=datetime.now(UTC),
    )


def _decided(suggestion, status):
    suggestion.status = status.value
    return suggestion


class TestDeciding:
    async def test_accepting_a_profile_update_saves_it_to_the_account(self):
        suggestion = _suggestion(
            "profile",
            {
                "job_title": "Head of sales",
                "working_hours": {"days": [1, 2], "start": "09:00", "end": "17:00"},
            },
        )
        user = MagicMock()
        update = AsyncMock()
        with (
            patch(f"{SERVICE}.suggestion_repo.get_own", new=AsyncMock(return_value=suggestion)),
            patch(
                f"{SERVICE}.suggestion_repo.decide",
                new=AsyncMock(
                    side_effect=lambda _db, suggestion, status: _decided(suggestion, status)
                ),
            ),
            patch(f"{SERVICE}.user_repo.get_by_id", new=AsyncMock(return_value=user)),
            patch(f"{SERVICE}.user_repo.update", new=update),
        ):
            accepted = await SuggestionService(MagicMock()).accept(CTX, suggestion.id)

        assert accepted.status == SuggestionStatus.ACCEPTED.value
        assert update.await_args.kwargs["update_data"] == {
            "job_title": "Head of sales",
            "working_hours": {"days": [1, 2], "start": "09:00", "end": "17:00"},
        }

    async def test_a_profile_update_that_no_longer_validates_is_refused(self):
        suggestion = _suggestion(
            "profile", {"working_hours": {"days": [9], "start": "9", "end": "8"}}
        )
        with (
            patch(f"{SERVICE}.suggestion_repo.get_own", new=AsyncMock(return_value=suggestion)),
            pytest.raises(ValidationError),
        ):
            await SuggestionService(MagicMock()).accept(CTX, suggestion.id)

    async def test_accepting_a_role_pack_queues_it_rather_than_installing_it_here(self):
        suggestion = _suggestion("role_pack", {"pack": "sales"})
        queue = AsyncMock()
        with (
            patch(f"{SERVICE}.suggestion_repo.get_own", new=AsyncMock(return_value=suggestion)),
            patch(
                f"{SERVICE}.suggestion_repo.decide",
                new=AsyncMock(
                    side_effect=lambda _db, suggestion, status: _decided(suggestion, status)
                ),
            ),
            patch(f"{SERVICE}.ProactiveService", return_value=MagicMock(queue_role_pack=queue)),
        ):
            await SuggestionService(MagicMock()).accept(CTX, suggestion.id)

        queue.assert_awaited_once_with(ORG, USER, "sales")

    async def test_a_routine_or_an_agent_is_the_consoles_to_carry_out(self):
        suggestion = _suggestion("routine", {"prompt": "p"})
        with (
            patch(f"{SERVICE}.suggestion_repo.get_own", new=AsyncMock(return_value=suggestion)),
            patch(
                f"{SERVICE}.suggestion_repo.decide",
                new=AsyncMock(
                    side_effect=lambda _db, suggestion, status: _decided(suggestion, status)
                ),
            ),
            patch(f"{SERVICE}.user_repo.update", new=AsyncMock()) as update,
            patch(f"{SERVICE}.ProactiveService") as proactive,
        ):
            accepted = await SuggestionService(MagicMock()).accept(CTX, suggestion.id)

        assert accepted.status == SuggestionStatus.ACCEPTED.value
        update.assert_not_awaited()
        proactive.assert_not_called()

    async def test_declining_keeps_it_as_dismissed(self):
        suggestion = _suggestion("agent", {"request": "r"})
        with (
            patch(f"{SERVICE}.suggestion_repo.get_own", new=AsyncMock(return_value=suggestion)),
            patch(
                f"{SERVICE}.suggestion_repo.decide",
                new=AsyncMock(
                    side_effect=lambda _db, suggestion, status: _decided(suggestion, status)
                ),
            ),
        ):
            dismissed = await SuggestionService(MagicMock()).dismiss(CTX, suggestion.id)

        assert dismissed.status == SuggestionStatus.DISMISSED.value

    @pytest.mark.parametrize("found", [None, _suggestion("agent", {}, status="dismissed")])
    async def test_somebody_elses_or_an_already_decided_one_is_not_found(self, found):
        with (
            patch(f"{SERVICE}.suggestion_repo.get_own", new=AsyncMock(return_value=found)),
            pytest.raises(NotFoundError),
        ):
            await SuggestionService(MagicMock()).dismiss(CTX, uuid.uuid4())

    async def test_an_account_gone_since_the_proposal_is_not_found(self):
        suggestion = _suggestion("profile", {"job_title": "CFO"})
        with (
            patch(f"{SERVICE}.suggestion_repo.get_own", new=AsyncMock(return_value=suggestion)),
            patch(f"{SERVICE}.user_repo.get_by_id", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await SuggestionService(MagicMock()).accept(CTX, suggestion.id)

    async def test_suggestions_are_made_to_a_signed_in_person(self):
        ctx = AuthContext(user_id=None, organization_id=ORG, role=OrgRoleName.MEMBER)
        with pytest.raises(AuthenticationError):
            await SuggestionService(MagicMock()).list_mine(ctx)

    async def test_the_list_is_this_persons_open_ones_here(self):
        listed = AsyncMock(return_value=[])
        with patch(f"{SERVICE}.suggestion_repo.list_open", new=listed):
            await SuggestionService(MagicMock()).list_mine(CTX)

        assert listed.await_args.kwargs == {"organization_id": ORG, "user_id": USER}


class TestTheRoutes:
    @pytest.fixture
    def service(self):
        registry = MagicMock()
        app.dependency_overrides[deps.get_auth_context] = lambda: CTX
        app.dependency_overrides[deps.get_suggestion_service] = lambda: registry
        yield registry
        app.dependency_overrides.clear()

    async def _call(self, method: str, path: str):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, f"{settings.API_V1_STR}/me/suggestions{path}")

    async def test_the_list_and_both_answers(self, service):
        open_one = _suggestion("routine", {"prompt": "p", "cron": "0 7 * * 1"})
        service.list_mine = AsyncMock(return_value=[open_one])
        service.accept = AsyncMock(
            return_value=_decided(_suggestion("agent", {}), SuggestionStatus.ACCEPTED)
        )
        service.dismiss = AsyncMock(
            return_value=_decided(_suggestion("agent", {}), SuggestionStatus.DISMISSED)
        )

        listed = await self._call("GET", "")
        accepted = await self._call("POST", f"/{open_one.id}/accept")
        dismissed = await self._call("POST", f"/{open_one.id}/dismiss")

        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["payload"] == {"prompt": "p", "cron": "0 7 * * 1"}
        assert accepted.status_code == 200 and dismissed.status_code == 200
        service.accept.assert_awaited_once_with(CTX, open_one.id)
        service.dismiss.assert_awaited_once_with(CTX, open_one.id)
