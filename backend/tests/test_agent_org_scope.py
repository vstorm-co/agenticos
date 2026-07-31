"""Tests for organization scoping of agent sessions.

Covers the two halves of the WebSocket org boundary:
  - `get_active_organization_ws` - which org a socket runs as
  - `persist_user_turn` - which org a turn is written to, and the refusal to
    resume a conversation belonging to another org
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketException

from app.api.deps import get_active_organization_ws
from app.core.exceptions import AuthorizationError
from app.services.agent import persist_user_turn


def _org(org_id=None):
    org = MagicMock()
    org.id = org_id or uuid.uuid4()
    return org


def _user(user_id=None):
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    return user


@asynccontextmanager
async def _fake_db_context():
    db = MagicMock()
    db.refresh = AsyncMock()
    db.expunge = MagicMock()
    yield db


class TestActiveOrganizationWS:
    """Resolving the organization a WebSocket session runs as."""

    @pytest.mark.anyio
    async def test_falls_back_to_personal_org(self):
        """No organization_id parameter -> the user's Personal org."""
        user = _user()
        personal = _org()

        with (
            patch("app.api.deps.get_db_context", _fake_db_context),
            patch(
                "app.api.deps.organization_repo.get_personal_for_user",
                new=AsyncMock(return_value=personal),
            ),
        ):
            org = await get_active_organization_ws(user, organization_id=None)

        assert org.id == personal.id

    @pytest.mark.anyio
    async def test_missing_personal_org_closes_socket(self):
        """A user without a Personal org cannot open a session."""
        with (
            patch("app.api.deps.get_db_context", _fake_db_context),
            patch(
                "app.api.deps.organization_repo.get_personal_for_user",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(WebSocketException) as exc,
        ):
            await get_active_organization_ws(_user(), organization_id=None)

        assert exc.value.code == 4001

    @pytest.mark.anyio
    async def test_requested_org_returned_for_member(self):
        """A member gets the org they asked for, not their personal one."""
        requested = _org()

        with (
            patch("app.api.deps.get_db_context", _fake_db_context),
            patch("app.api.deps._member_repo.get", new=AsyncMock(return_value=MagicMock())),
            patch(
                "app.api.deps.organization_repo.get_by_id",
                new=AsyncMock(return_value=requested),
            ),
        ):
            org = await get_active_organization_ws(_user(), organization_id=requested.id)

        assert org.id == requested.id

    @pytest.mark.anyio
    async def test_non_member_is_rejected(self):
        """Asking for an org the user does not belong to closes the socket."""
        with (
            patch("app.api.deps.get_db_context", _fake_db_context),
            patch("app.api.deps._member_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(WebSocketException) as exc,
        ):
            await get_active_organization_ws(_user(), organization_id=uuid.uuid4())

        assert exc.value.code == 4003

    @pytest.mark.anyio
    async def test_unknown_org_looks_like_denied_access(self):
        """A non-existent org must not be distinguishable from a forbidden one."""
        with (
            patch("app.api.deps.get_db_context", _fake_db_context),
            patch("app.api.deps._member_repo.get", new=AsyncMock(return_value=MagicMock())),
            patch("app.api.deps.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
            pytest.raises(WebSocketException) as exc,
        ):
            await get_active_organization_ws(_user(), organization_id=uuid.uuid4())

        assert exc.value.code == 4003
        assert exc.value.reason == "Organization access denied"


class TestPersistUserTurnOrgScope:
    """Which organization a turn is written to."""

    def _conv_service(self, conversation=None):
        service = MagicMock()
        service.get_conversation = AsyncMock(return_value=conversation)
        service.create_conversation = AsyncMock(return_value=conversation)
        service.update_conversation = AsyncMock()
        service.add_message = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
        service.link_files_to_message = AsyncMock()
        return service

    @pytest.mark.anyio
    async def test_new_conversation_stamped_with_active_org(self):
        """A new conversation belongs to the session's org, not the personal one."""
        org_id = uuid.uuid4()
        created = MagicMock(id=uuid.uuid4())
        service = self._conv_service(created)

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.get_conversation_service", return_value=service),
        ):
            conversation_id, newly_created = await persist_user_turn(
                _user(),
                "hello",
                [],
                requested_conversation_id=None,
                current_conversation_id=None,
                organization_id=org_id,
            )

        assert newly_created is True
        assert conversation_id == str(created.id)
        assert service.create_conversation.call_args.args[0].organization_id == org_id

    @pytest.mark.anyio
    async def test_resuming_own_org_conversation_is_allowed(self):
        """Same org -> the turn proceeds."""
        org_id = uuid.uuid4()
        conversation_id = uuid.uuid4()
        conv = MagicMock(organization_id=org_id, title="Existing")
        service = self._conv_service(conv)

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.get_conversation_service", return_value=service),
        ):
            resolved, newly_created = await persist_user_turn(
                _user(),
                "hello",
                [],
                requested_conversation_id=str(conversation_id),
                current_conversation_id=None,
                organization_id=org_id,
            )

        assert newly_created is False
        assert resolved == str(conversation_id)
        service.add_message.assert_awaited_once()

    @pytest.mark.anyio
    async def test_resuming_foreign_org_conversation_is_refused(self):
        """Owning the conversation is not enough - it must be in the active org."""
        conv = MagicMock(organization_id=uuid.uuid4(), title="Other org's chat")
        service = self._conv_service(conv)

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.get_conversation_service", return_value=service),
            pytest.raises(AuthorizationError),
        ):
            await persist_user_turn(
                _user(),
                "hello",
                [],
                requested_conversation_id=str(uuid.uuid4()),
                current_conversation_id=None,
                organization_id=uuid.uuid4(),
            )

        service.add_message.assert_not_awaited()

    @pytest.mark.anyio
    async def test_orgless_conversation_is_refused(self):
        """A conversation with no org (legacy row) is not readable from a session."""
        conv = MagicMock(organization_id=None, title="Legacy")
        service = self._conv_service(conv)

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.get_conversation_service", return_value=service),
            pytest.raises(AuthorizationError),
        ):
            await persist_user_turn(
                _user(),
                "hello",
                [],
                requested_conversation_id=str(uuid.uuid4()),
                current_conversation_id=None,
                organization_id=uuid.uuid4(),
            )
