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
    authoring_repo,
    case_generation_repo,
    case_score_repo,
    channel_bot_repo,
    context_proposal_repo,
    context_repo,
    conversation_repo,
    conversation_share_repo,
    credential_repo,
    dataset_repo,
    eval_run_repo,
    eval_suite_repo,
    improvement_repo,
    intercepted_tool_call_repo,
    knowledge_base_repo,
    knowledge_gap_repo,
    message_rating_repo,
    personal_data_repo,
    promotion_gate_repo,
    rag_document_repo,
    skill_check_repo,
    skill_improvement_repo,
    skill_merge_repo,
    skill_proposal_repo,
    skill_repo,
    skill_usage_repo,
    skill_version_repo,
)
from app.repositories import workflow_run as workflow_run_repo
from app.services.conversation import ConversationService

# (module, function name) pairs whose tenant argument must be required.
TENANT_REQUIRED = [
    (conversation_repo, "get_conversations_by_user"),
    (conversation_repo, "count_conversations"),
    (conversation_repo, "create_conversation"),
    (conversation_repo, "list_tool_calls_for_run"),
    (authoring_repo, "create_request"),
    (authoring_repo, "get_request"),
    (authoring_repo, "requests_of_improvement"),
    (authoring_repo, "list_requests"),
    (authoring_repo, "get_batch"),
    (authoring_repo, "get_open_batch"),
    (authoring_repo, "latest_batch"),
    (authoring_repo, "create_batch"),
    (authoring_repo, "add_hunks"),
    (authoring_repo, "list_hunks"),
    (authoring_repo, "get_hunk"),
    (authoring_repo, "decide_hunk"),
    (authoring_repo, "pending_counts"),
    (authoring_repo, "evidence_runs"),
    (authoring_repo, "agents_with_pending"),
    (authoring_repo, "skills_with_pending"),
    (authoring_repo, "count_pending_new_skills"),
    (improvement_repo, "create_run"),
    (improvement_repo, "get_run"),
    (improvement_repo, "get_active"),
    (improvement_repo, "list_for_agent"),
    (improvement_repo, "create_iteration"),
    (improvement_repo, "get_iteration"),
    (improvement_repo, "list_iterations"),
    (conversation_repo, "question_of_run"),
    (channel_bot_repo, "get_for_org"),
    (channel_bot_repo, "get_by_platform"),
    (channel_bot_repo, "list_for_org"),
    (channel_bot_repo, "count"),
    (channel_bot_repo, "create"),
    (channel_bot_repo, "delete"),
    (agent_environment_repo, "list_connections"),
    (agent_environment_repo, "replace_connections"),
    (agent_environment_repo, "served_mentioning"),
    (intercepted_tool_call_repo, "add_many"),
    (intercepted_tool_call_repo, "list_for_run"),
    (dataset_repo, "get"),
    (dataset_repo, "get_by_name"),
    (dataset_repo, "lock_revision"),
    (message_rating_repo, "get_down_rating_notes_for_messages"),
    (message_rating_repo, "noter_of"),
    (personal_data_repo, "asker_of"),
    (conversation_share_repo, "has_edit_share"),
    (dataset_repo, "lock"),
    (dataset_repo, "list_visible"),
    (dataset_repo, "testing_agent"),
    (dataset_repo, "for_agent"),
    (dataset_repo, "create"),
    (dataset_repo, "get_version"),
    (dataset_repo, "list_versions"),
    (dataset_repo, "create_version"),
    (dataset_repo, "list_cases"),
    (dataset_repo, "case_stats"),
    (dataset_repo, "stored_revisions"),
    (dataset_repo, "find_case"),
    (dataset_repo, "last_position"),
    (dataset_repo, "close_revisions"),
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
    (knowledge_gap_repo, "classification_candidates"),
    (knowledge_gap_repo, "count_unchecked"),
    (knowledge_gap_repo, "classifications_of"),
    (knowledge_gap_repo, "last_document_added"),
    (knowledge_gap_repo, "record_classifications"),
    (knowledge_gap_repo, "still_asked"),
    (agent_repo, "get_system"),
    (agent_repo, "lock"),
    (agent_run_repo, "recent_usage"),
    (context_repo, "lock"),
    (context_proposal_repo, "get"),
    (context_proposal_repo, "get_pending_for_context"),
    (context_proposal_repo, "list_for_organization"),
    (context_proposal_repo, "files_with_pending"),
    (context_proposal_repo, "create"),
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
    (agent_run_repo, "failed_by_agent"),
    (message_rating_repo, "down_rated_by_agent"),
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
    (eval_suite_repo, "settled_on_version"),
    (eval_suite_repo, "open_on_version"),
    (promotion_gate_repo, "guards_for"),
    (promotion_gate_repo, "replace_guards"),
    (promotion_gate_repo, "guarded_by"),
    (promotion_gate_repo, "guarded_by_dataset"),
    (promotion_gate_repo, "guarding_through"),
    (promotion_gate_repo, "guarded_following_latest"),
    (promotion_gate_repo, "add_override"),
    (promotion_gate_repo, "overrides_for_versions"),
    (agent_run_repo, "agents_of_runs"),
    (agent_run_repo, "conversations_of_runs"),
    (authoring_repo, "create_skill_batch"),
    (skill_improvement_repo, "create_run"),
    (skill_improvement_repo, "get_run"),
    (skill_improvement_repo, "list_runs"),
    (skill_improvement_repo, "list_for_person"),
    (skill_improvement_repo, "create_iteration"),
    (skill_improvement_repo, "get_iteration"),
    (skill_improvement_repo, "list_iterations"),
    (skill_improvement_repo, "spent"),
    (skill_improvement_repo, "iteration_for_check"),
    (skill_improvement_repo, "sessions_of_checks"),
    (skill_improvement_repo, "check_cost"),
    (skill_improvement_repo, "timeline"),
    (skill_usage_repo, "record_uses"),
    (skill_check_repo, "create"),
    (skill_check_repo, "add_agents"),
    (skill_check_repo, "get"),
    (skill_check_repo, "list_for_skill"),
    (skill_check_repo, "open_for_proposal"),
    (skill_check_repo, "list_agents"),
    (skill_check_repo, "agent_for_run"),
    (skill_check_repo, "loaded_cases"),
    (skill_check_repo, "checked_versions"),
    (skill_merge_repo, "create"),
    (skill_merge_repo, "for_run"),
    (skill_proposal_repo, "from_source"),
    (skill_proposal_repo, "lock"),
    (dataset_repo, "for_skill"),
    (conversation_repo, "last_answers_of_runs"),
    (skill_usage_repo, "mark_recorded"),
    (skill_usage_repo, "mark_unrecorded"),
    (skill_usage_repo, "usage_by_agent"),
    (skill_usage_repo, "usage_by_version"),
    (skill_usage_repo, "uses_in_runs"),
    (skill_usage_repo, "skills_in_runs"),
    (skill_usage_repo, "unknown_runs"),
    (skill_usage_repo, "agents_involved"),
    (agent_repo, "drafts_mentioning"),
    (skill_repo, "hold"),
    (skill_version_repo, "create_version"),
    (skill_version_repo, "get_version"),
    (skill_version_repo, "get_versions"),
    (skill_version_repo, "latest_number"),
    (skill_version_repo, "get_by_numbers"),
    (skill_version_repo, "list_versions"),
    (skill_version_repo, "main_digests"),
    (skill_version_repo, "put_files"),
    (skill_version_repo, "get_files"),
    (skill_version_repo, "create_fork"),
    (skill_version_repo, "get_fork"),
    (skill_version_repo, "get_forks"),
    (skill_version_repo, "hold_forks"),
    (skill_version_repo, "get_fork_by_name"),
    (skill_version_repo, "list_forks"),
    (skill_version_repo, "count_versions"),
    (skill_version_repo, "count_active_forks"),
    (skill_version_repo, "forks_served_since"),
    (workflow_run_repo, "try_lock_run"),
    (workflow_run_repo, "list_called_run_ids"),
]

# Deliberately unscoped, each documented at its definition.
CROSS_TENANT_BY_DESIGN = [
    (channel_bot_repo, "get_for_inbound"),
    (channel_bot_repo, "get_active_polling_bots"),
    (channel_bot_repo, "get_active_polling_bot_ids"),
    (conversation_repo, "get_conversation_by_id"),
    (personal_data_repo, "unlink_dataset_cases_of"),
    (personal_data_repo, "delete_case_proposals_of"),
    (personal_data_repo, "case_proposals_from"),
    (personal_data_repo, "knowledge_searches_of"),
    (personal_data_repo, "purge_knowledge_searches_of"),
    (personal_data_repo, "clear_gap_reasons_of"),
    (knowledge_gap_repo, "knowledge_bases_with_ungrouped_misses"),
    (knowledge_gap_repo, "delete_empty_topics"),
    (eval_run_repo, "fail_abandoned"),
    (eval_run_repo, "close_orphaned_attempts"),
    (eval_suite_repo, "claim_due_schedules"),
    (eval_suite_repo, "claim_pending"),
    (eval_suite_repo, "claim_finished"),
    (improvement_repo, "list_active"),
    (improvement_repo, "list_deciding"),
    (skill_improvement_repo, "list_active"),
    (skill_improvement_repo, "list_resting"),
    (promotion_gate_repo, "guarded_followers"),
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
