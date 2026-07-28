"""Where the money went: which provider, and through which key.

A run recorded `model_label` — a display name somebody chose, like "GPT-4.1
(prod)". Two questions an invoice raises could not be answered from it at all:
what did we spend at OpenAI versus Anthropic, and which key is costing the most.

The property worth pinning is not the sum, it is the *attribution*: it is taken
from what the run actually used and frozen there, so repointing a model profile
or rotating a key never rewrites what last month appears to have cost.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret
from app.services.agent_runner import AgentRunnerService

RUNNER = "app.services.agent_runner"


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


def _model_spec(credential_id: uuid.UUID | None) -> ModelRequestSpec:
    return ModelRequestSpec(
        profile_id=uuid.uuid4(),
        label="GPT-4.1 (prod)",
        provider="openai",
        model="gpt-4.1",
        params={},
        credential=ResolvedCredential(provider="openai", secret=ApiKeySecret(api_key="sk-x")),
        credential_id=credential_id,
        fallbacks=[],
    )


class TestWhatARunRecords:
    def test_the_resolver_carries_which_key_it_resolved(self):
        """Without it the run has a provider and no way to say whose key paid."""
        credential_id = uuid.uuid4()
        assert _model_spec(credential_id).credential_id == credential_id

    def test_a_keyless_provider_records_no_key(self):
        """A self-hosted server has no key to attribute spend to, and inventing
        one would put a row under a credential that does not exist."""
        assert _model_spec(None).credential_id is None


class TestAggregation:
    @pytest.mark.anyio
    async def test_spend_is_grouped_by_the_provider_the_run_used(self):
        rows = [("openai", Decimal("12.50"), 40), ("anthropic", Decimal("3.00"), 5)]
        with patch(
            f"{RUNNER}.agent_run_repo.spend_by_provider", new=AsyncMock(return_value=rows)
        ) as query:
            result = await AgentRunnerService(MagicMock()).spend_by_provider(_ctx(), days=7)

        assert result == rows
        # The window is a window, not "everything": a monthly bill is not
        # answered by a total since the beginning of time.
        assert isinstance(query.call_args.kwargs["since"], datetime)
        assert query.call_args.kwargs["since"].tzinfo is UTC

    @pytest.mark.anyio
    async def test_spend_is_grouped_by_the_key_that_paid(self):
        credential_id = uuid.uuid4()
        rows = [(credential_id, "OpenAI production", Decimal("9.00"), 12)]
        with patch(
            f"{RUNNER}.agent_run_repo.spend_by_credential", new=AsyncMock(return_value=rows)
        ):
            result = await AgentRunnerService(MagicMock()).spend_by_credential(_ctx(), days=30)

        assert result[0][0] == credential_id
        assert result[0][1] == "OpenAI production"

    @pytest.mark.anyio
    async def test_a_deleted_key_keeps_its_spend_under_a_null_label(self):
        """The money was spent whether or not the key still exists. Dropping the
        row would make a month's total quietly stop adding up."""
        rows = [(None, None, Decimal("4.20"), 3)]
        with patch(
            f"{RUNNER}.agent_run_repo.spend_by_credential", new=AsyncMock(return_value=rows)
        ):
            result = await AgentRunnerService(MagicMock()).spend_by_credential(_ctx(), days=30)

        assert result[0][2] == Decimal("4.20")
