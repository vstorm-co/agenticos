"""Approval defaults for this deployment's own MCP tools, independent of transports.

These are tool identities, not remote annotations or permissions. Every operation
still checks the caller's live authorization before changing a resource.
"""

UNGATED: frozenset[str] = frozenset(
    {
        "set_my_language",
        "set_my_preferences",
        "set_my_console_experience",
    }
)
"""Self-only console preferences; no binding can make these wait."""

ALWAYS_ASKS: frozenset[str] = frozenset(
    {
        "accept_improvement",
        "accept_skill_improvement",
        "add_document",
        "change_deployment",
        "change_organization",
        "change_skill_version",
        "create_agent_environment",
        "create_app_public_link",
        "create_embedding_endpoint",
        "create_eval_suite",
        "create_knowledge_source",
        "create_model_profile",
        "create_routine",
        "create_watch",
        "delete_routine",
        "delete_virtual_table_record",
        "delete_watch",
        "discard_agent_draft",
        "draft_knowledge_topic",
        "end_improvement",
        "end_skill_improvement",
        "improve_again",
        "install_solution",
        "invite_member",
        "publish_agent",
        "publish_workflow",
        "retry_skill_improvement_step",
        "return_skill_fork_to_main",
        "run_agent",
        "run_next_improvement_step",
        "run_next_skill_improvement_step",
        "run_promotion_gate",
        "run_routine_now",
        "run_workflow",
        "set_my_profile",
        "settle_inbox_case",
        "start_eval_run",
        "start_improvement",
        "start_skill_catch_up",
        "start_skill_improvement",
        "start_skill_update_check",
        "sync_knowledge_source",
        "test_agent_draft",
        "test_my_connection",
        "test_workflow_draft",
        "update_agent_environment",
        "update_eval_suite",
        "update_model_profile",
        "update_proactivity_settings",
        "update_routine",
        "update_virtual_table_schema",
        "update_watch",
        "use_attempt",
    }
)
"""A fresh human answer is required for every call, including under standing consent."""

DEFAULT_APPROVAL_FREE: frozenset[str] = frozenset(
    {
        "add_dataset_case",
        "add_skill_resource",
        "add_virtual_table_record",
        "answer_agent_questions",
        "create_agent_draft",
        "create_context_file",
        "create_conversation",
        "create_dataset",
        "create_knowledge_base",
        "create_project",
        "create_skill",
        "create_task",
        "create_virtual_table",
        "create_workflow_draft",
        "ensure_task_board",
        "prepare_solution",
        "publish_inbox_finding",
        "prepare_workflow_draft",
        "update_agent_draft",
        "update_context_file",
        "update_skill",
        "update_task",
        "update_virtual_table_record",
        "update_workflow_draft",
        "upsert_virtual_table_record",
    }
)
"""Authorized draft/record writes run by default; explicit required/all policies still ask."""

CONDITIONAL_EXECUTION: frozenset[str] = frozenset(
    {
        "create_task",
        "update_task",
        "add_virtual_table_record",
        "update_virtual_table_record",
        "upsert_virtual_table_record",
    }
)
"""Default-free writes that still ask when they may schedule fresh agent work."""
