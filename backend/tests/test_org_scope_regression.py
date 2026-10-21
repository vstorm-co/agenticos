"""Regression guards for tenant scoping.

Two kinds of check:
  - behavioural - a resource from another organization is not readable;
  - structural - the repository signatures that caused the problem cannot come
    back. `organization_id: UUID | None = None` made the unsafe call (no
    tenant filter, every tenant's rows) look identical to the safe one, so an
    omitted argument silently widened a query. These functions must take the
    tenant as a required keyword.

Queries that legitimately cross tenants are named for it - `get_for_inbound`,
`get_active_polling_bots` - and are listed here as deliberate exceptions.
"""

import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import NotFoundError
from app.repositories import (
    agent_environment_repo,
    agent_repo,
    agent_run_repo,
    case_generation_repo,
    case_score_repo,
    channel_bot_repo,
    conversation_repo,
    credential_repo,
    dataset_repo,
    eval_run_repo,
    eval_suite_repo,
    intercepted_tool_call_repo,
    knowledge_base_repo,
    knowledge_gap_repo,
    personal_data_repo,
    rag_document_repo,
)
from app.services.conversation import ConversationService

# (module, function name) pairs whose tenant argument must be required.
TENANT_REQUIRED = [
    (conversation_repo, "get_conversations_by_user"),
    (conversation_repo, "count_conversations"),
    (conversation_repo, "create_conversation"),
    (conversation_repo, "list_tool_calls_for_run"),
    (conversation_repo, "question_of_run"),
    (channel_bot_repo, "get_for_org"),
    (channel_bot_repo, "get_by_platform"),
    (channel_bot_repo, "list_for_org"),
    (channel_bot_repo, "count"),
    (channel_bot_repo, "create"),
    (channel_bot_repo, "delete"),
    (agent_environment_repo, "list_connections"),
    (agent_environment_repo, "replace_connections"),
    (intercepted_tool_call_repo, "add_many"),
    (intercepted_tool_call_repo, "list_for_run"),
    (dataset_repo, "get"),
    (dataset_repo, "get_by_name"),
    (dataset_repo, "lock"),
    (dataset_repo, "list_visible"),
    (dataset_repo, "create"),
    (dataset_repo, "get_version"),
    (dataset_repo, "list_versions"),
    (dataset_repo, "create_version"),
    (dataset_repo, "list_cases"),
    (dataset_repo, "case_stats"),
    (dataset_repo, "version_rows"),
    (dataset_repo, "find_case"),
    (dataset_repo, "last_position"),
    (dataset_repo, "copy_membership"),
    (conversation_repo, "get_messages_before"),
    (personal_data_repo, "unlink_dataset_cases_from_conversation"),
    (knowledge_gap_repo, "record_searches"),
    (knowledge_gap_repo, "ungrouped_misses"),
    (knowledge_gap_repo, "topics_in_space"),
    (knowledge_gap_repo, "create_topic"),
    (knowledge_gap_repo, "list_topics"),
    (knowledge_gap_repo, "count_ungrouped"),
    (knowledge_gap_repo, "topics_per_knowledge_base"),
    (knowledge_gap_repo, "get_topic"),
    (knowledge_gap_repo, "list_questions"),
    (knowledge_gap_repo, "knowledge_bases_with_misses"),
    (knowledge_gap_repo, "drafting_material"),
    (knowledge_gap_repo, "member_queries"),
    (knowledge_gap_repo, "documents_named"),
    (knowledge_gap_repo, "documents_in"),
    (agent_repo, "get_system"),
    (credential_repo, "oldest_profile"),
    (case_score_repo, "create"),
    (case_score_repo, "get"),
    (case_score_repo, "list_for_dataset"),
    (case_score_repo, "list_pending"),
    (case_score_repo, "pending_counts"),
    (case_generation_repo, "create_generation"),
    (case_generation_repo, "get_generation"),
    (case_generation_repo, "list_generations"),
    (case_generation_repo, "list_proposals"),
    (case_generation_repo, "count_pending"),
    (case_generation_repo, "take_proposals"),
    (case_generation_repo, "count_decisions"),
    (agent_run_repo, "questions_asked"),
    (knowledge_base_repo, "get_in_organization"),
    (rag_document_repo, "indexed_in"),
    (eval_run_repo, "create"),
    (eval_run_repo, "add_cases"),
    (eval_run_repo, "get"),
    (eval_run_repo, "lock"),
    (eval_run_repo, "list_arms"),
    (eval_run_repo, "get_arm"),
    (eval_run_repo, "list_for_agent"),
    (eval_run_repo, "list_recent"),
    (eval_run_repo, "list_cases"),
    (eval_run_repo, "list_arm_cases"),
    (eval_run_repo, "get_case"),
    (eval_run_repo, "claim_next"),
    (eval_run_repo, "count_by_status"),
    (eval_run_repo, "skip_pending"),
    (eval_run_repo, "latest_arm"),
    (eval_run_repo, "referenced_ids"),
    (eval_run_repo, "scores"),
    (eval_run_repo, "revisions"),
    (eval_run_repo, "datasets"),
    (eval_run_repo, "dataset_version_numbers"),
    (agent_repo, "get_version_by_number"),
    (agent_repo, "version_before"),
    (agent_run_repo, "average_cost"),
    (agent_run_repo, "cost_of_runs"),
    (eval_suite_repo, "create"),
    (eval_suite_repo, "get"),
    (eval_suite_repo, "get_by_name"),
    (eval_suite_repo, "lock"),
    (eval_suite_repo, "list_for_agents"),
    (eval_suite_repo, "list_for_organization"),
    (eval_suite_repo, "list_watching"),
    (eval_suite_repo, "list_on_environment"),
    (eval_suite_repo, "add_result"),
    (eval_suite_repo, "get_result"),
    (eval_suite_repo, "discard_pending"),
    (eval_suite_repo, "running_for"),
    (eval_suite_repo, "previous_settled"),
    (eval_suite_repo, "incomparable_since"),
    (eval_suite_repo, "list_results"),
    (eval_suite_repo, "latest_results"),
    (eval_suite_repo, "open_results"),
    (eval_suite_repo, "started_runs"),
]

# Deliberately unscoped, each documented at its definition.
CROSS_TENANT_BY_DESIGN = [
    (channel_bot_repo, "get_for_inbound"),
    (channel_bot_repo, "get_active_polling_bots"),
    (conversation_repo, "get_conversation_by_id"),
    (personal_data_repo, "unlink_dataset_cases_of"),
    (personal_data_repo, "delete_case_proposals_of"),
    (personal_data_repo, "case_proposals_from"),
    (personal_data_repo, "knowledge_searches_of"),
    (personal_data_repo, "purge_knowledge_searches_of"),
    (knowledge_gap_repo, "knowledge_bases_with_ungrouped_misses"),
    (knowledge_gap_repo, "delete_empty_topics"),
    (eval_run_repo, "fail_abandoned"),
    (eval_suite_repo, "claim_due_schedules"),
    (eval_suite_repo, "claim_pending"),
    (eval_suite_repo, "claim_finished"),
]


class TestRepositorySignatures:
    """The audit, executable."""

    @pytest.mark.security
    @pytest.mark.parametrize(("module", "func_name"), TENANT_REQUIRED)
    def test_tenant_argument_has_no_default(self, module, func_name):
        params = inspect.signature(getattr(module, func_name)).parameters
        assert "organization_id" in params, f"{func_name} lost its tenant argument"
        param = params["organization_id"]
        assert param.default is inspect.Parameter.empty, (
            f"{func_name} defaults organization_id - a forgotten tenant would silently "
            "widen the query instead of failing"
        )
        assert param.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"{func_name} takes organization_id positionally - keyword-only keeps call "
            "sites readable and prevents argument-order mistakes"
        )

    @pytest.mark.parametrize(("module", "func_name"), CROSS_TENANT_BY_DESIGN)
    def test_unscoped_functions_say_why(self, module, func_name):
        doc = inspect.getdoc(getattr(module, func_name)) or ""
        assert "unscoped" in doc.lower(), (
            f"{func_name} crosses tenants without saying so - an unscoped query must be "
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
        """Same user, different org - still refused."""
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
