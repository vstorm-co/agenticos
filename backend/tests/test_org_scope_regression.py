"""Regression guards for tenant scoping.

Two kinds of check:
  - behavioural — a resource from another organization is not readable;
  - structural — the repository signatures that caused the problem cannot come
    back. ``organization_id: UUID | None = None`` made the unsafe call (no
    tenant filter, every tenant's rows) look identical to the safe one, so an
    omitted argument silently widened a query. These functions must take the
    tenant as a required keyword.

Queries that legitimately cross tenants are named for it — ``get_for_inbound``,
``get_active_polling_bots`` — and are listed here as deliberate exceptions.
"""

import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import NotFoundError
from app.repositories import channel_bot_repo, conversation_repo
from app.services.conversation import ConversationService

# (module, function name) pairs whose tenant argument must be required.
TENANT_REQUIRED = [
    (conversation_repo, "get_conversations_by_user"),
    (conversation_repo, "count_conversations"),
    (conversation_repo, "create_conversation"),
    (channel_bot_repo, "get_for_org"),
    (channel_bot_repo, "get_by_platform"),
    (channel_bot_repo, "list_for_org"),
    (channel_bot_repo, "count"),
    (channel_bot_repo, "create"),
    (channel_bot_repo, "delete"),
]

# Deliberately unscoped, each documented at its definition.
CROSS_TENANT_BY_DESIGN = [
    (channel_bot_repo, "get_for_inbound"),
    (channel_bot_repo, "get_active_polling_bots"),
    (conversation_repo, "get_conversation_by_id"),
]


class TestRepositorySignatures:
    """The audit, executable."""

    @pytest.mark.parametrize(("module", "func_name"), TENANT_REQUIRED)
    def test_tenant_argument_has_no_default(self, module, func_name):
        params = inspect.signature(getattr(module, func_name)).parameters
        assert "organization_id" in params, f"{func_name} lost its tenant argument"
        param = params["organization_id"]
        assert param.default is inspect.Parameter.empty, (
            f"{func_name} defaults organization_id — a forgotten tenant would silently "
            "widen the query instead of failing"
        )
        assert param.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"{func_name} takes organization_id positionally — keyword-only keeps call "
            "sites readable and prevents argument-order mistakes"
        )

    @pytest.mark.parametrize(("module", "func_name"), CROSS_TENANT_BY_DESIGN)
    def test_unscoped_functions_say_why(self, module, func_name):
        doc = inspect.getdoc(getattr(module, func_name)) or ""
        assert "unscoped" in doc.lower(), (
            f"{func_name} crosses tenants without saying so — an unscoped query must be "
            "greppable and explain itself"
        )


class TestConversationTenantBoundary:
    """A conversation is invisible outside its organization."""

    def _conv(self, organization_id, user_id=None):
        conv = MagicMock()
        conv.id = uuid.uuid4()
        conv.organization_id = organization_id
        conv.user_id = user_id
        conv.messages = []
        return conv

    @pytest.mark.anyio
    async def test_foreign_org_conversation_reads_as_missing(self):
        conv = self._conv(uuid.uuid4())

        with (
            patch(
                "app.repositories.conversation_repo.get_conversation_by_id",
                new=AsyncMock(return_value=conv),
            ),
            pytest.raises(NotFoundError),
        ):
            service = ConversationService(MagicMock())
            await service.get_conversation(conv.id, organization_id=uuid.uuid4())

    @pytest.mark.anyio
    async def test_own_org_conversation_is_returned(self):
        org_id = uuid.uuid4()
        conv = self._conv(org_id)

        with patch(
            "app.repositories.conversation_repo.get_conversation_by_id",
            new=AsyncMock(return_value=conv),
        ):
            service = ConversationService(MagicMock())
            result = await service.get_conversation(conv.id, organization_id=org_id)

        assert result is conv

    @pytest.mark.anyio
    async def test_ownership_alone_does_not_grant_access(self):
        """Same user, different org — still refused."""
        user_id = uuid.uuid4()
        conv = self._conv(uuid.uuid4(), user_id=user_id)

        with (
            patch(
                "app.repositories.conversation_repo.get_conversation_by_id",
                new=AsyncMock(return_value=conv),
            ),
            pytest.raises(NotFoundError),
        ):
            service = ConversationService(MagicMock())
            await service.get_conversation(conv.id, organization_id=uuid.uuid4(), user_id=user_id)
