"""A nudge that keeps the `security` marker honest as the suite grows.

The `security` marker names the platform's refusal tests as a set, so the
security report can *show* the refusals rather than assert they exist (#1417).
A marker only stays a faithful index if new refusal tests actually carry it, and
nothing makes that automatic - a `tenant`-named test written next month would
quietly sit outside `-m security` and outside the report.

So this file draws a keyword net over the suite: any test whose function name or
module name contains `tenant`, `permission`, `budget`, `approval`, `secret` or
`plaintext` must either carry the marker or be named, with a reason, in
`EXEMPT` below. It is a nudge, not a gate on wording - a coincidental match (a
budget *shown* on a dashboard, an approval *notification*) is exempted rather
than mislabelled a refusal, and the exemption records why.

The check is static: it reads the decorators, the class and the module-level
`pytestmark`, rather than collecting the suite. That is deliberate - a
collection-based check sees only the tests collected in the same run, so it
would pass vacuously when this file is run on its own. Static analysis holds
whether the file runs alone or inside `make test`. The trade is that a marker
applied any way other than a literal `pytest.mark.security` decorator or
`pytestmark` assignment is invisible here; the suite applies them exactly those
two ways, and the assertion in `TestTheMarkerIsLive` fails loudly if that stops
being true.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path
from typing import NamedTuple

BACKEND_ROOT = Path(__file__).resolve().parent.parent
TESTS_ROOT = BACKEND_ROOT / "tests"

# The net, fixed by #1417. A test whose function or module name contains one of
# these must carry the marker or be exempted.
KEYWORDS = ("tenant", "permission", "budget", "approval", "secret", "plaintext")

# Keyword matches that are not refusal tests: the word is coincidental. Each
# entry is a pytest nodeid mapped to the reason it is not a security test. Kept
# honest by `TestNoStaleExemptions`, which fails if an entry no longer exists or
# no longer matches the net.
EXEMPT: dict[str, str] = {
    "tests/api/test_platform_routes.py::TestEveryPlatformRouteIsGuarded::test_every_gated_route_is_named_in_the_permission_table": "meta test that the CALLS gate fixture is complete, no runtime refusal",
    "tests/api/test_platform_routes.py::TestEveryPlatformRouteIsGuarded::test_the_permission_table_has_no_stale_entries": "meta test of gate-fixture hygiene, no runtime refusal",
    "tests/api/test_platform_routes.py::TestPermissionIntrospectionIsOpenToEveryMember::test_every_role_can_read_its_own_permissions": "permission introspection is open to every role, no refusal",
    "tests/api/test_platform_routes.py::TestReadingWhatARunIsParkedOn::test_the_parked_calls_come_back_with_the_approval_to_decide": "reads parked approvals for an authorized caller, display/read",
    "tests/api/test_run_export_routes.py::TestTheFiltersReachTheService::test_approval_filters_arrive_as_named": "query filters reach the service, plumbing, no refusal",
    "tests/integration/test_agent_trigger_schema.py::TestTheEventShapeRejectsABadRow::test_a_polled_event_trigger_with_no_secret_is_accepted": "the valid polled shape is accepted, schema accept-complement",
    "tests/integration/test_deletion_reconciliation.py::TestDeletingAUser::test_deleting_a_member_promotes_their_private_secret_to_the_org": "deleting a member promotes their private secret to the org, reconciliation, no refusal",
    "tests/integration/test_platform_flows.py::TestTheListingCarriesThePublishedCap::test_a_version_with_no_budget_block_answers_null": "a version with no budget block reports a null cap, listing, no refusal",
    "tests/integration/test_platform_flows.py::TestTheOrganizationsSecrets::test_a_deleted_secret_is_gone_and_a_second_delete_says_so": "delete is idempotent (a second delete returns False), CRUD, no refusal",
    "tests/integration/test_platform_flows.py::TestTheOrganizationsSecrets::test_deleting_the_organization_takes_its_secrets_with_it": "deleting the organization cascades its secrets, lifecycle, no refusal",
    "tests/integration/test_platform_flows.py::TestTheOrganizationsSecrets::test_several_secrets_resolve_in_one_query": "batch resolves several secrets for a run, query feature, no refusal",
    "tests/integration/test_admin_org_owner.py::TestTheDetail::test_it_carries_the_members_owner_budget_and_size": "reads the budget onto an admin's page, display, no refusal",
    "tests/test_media_offload.py::TestTheBytesHaveALifetime::test_the_tenant_s_media_is_removed_with_the_tenant": "a teardown removing a prefix, not a refusal - the isolation case beside it carries the marker",
    "tests/test_capability_contracts.py::TestDocumentationSecret::test_a_capability_needing_no_secret_gets_none": "picks a stand-in value for a documentation stub, no runtime secret",
    "tests/test_capability_contracts.py::TestDocumentationSecret::test_a_conditional_secret_the_default_config_does_not_need_gets_none": "picks a stand-in value for a documentation stub, no runtime secret",
    "tests/test_capability_contracts.py::TestDocumentationSecret::test_a_non_api_key_secret_gets_no_stand_in": "picks a stand-in value for a documentation stub, no runtime secret",
    "tests/integration/test_notification_center.py::TestMandatoryEvents::test_a_metered_mandatory_write_within_budget_still_writes": "'budget' names the rate-limit allowance, not a spend cap; a write within it succeeds, no refusal",
    "tests/integration/test_notification_center.py::TestListInboxPagination::test_a_fully_gated_backlog_exhausts_its_fetch_budget": "'budget' names the pagination fetch-round bound, not a spend cap; no refusal",
    "tests/integration/test_notification_delivery.py::TestRenderDispatch::test_budget_exceeded_renders_its_own_key_unchanged": "'budget' names the notification event type (budget_exceeded), not a spend cap; renders successfully, no refusal",
    "tests/test_capability_contracts.py::TestDocumentationSecret::test_an_unconditional_api_key_secret_gets_a_probe_value": "picks a stand-in value for a documentation stub, no runtime secret",
    "tests/test_embedding_resolution.py::TestCredentialDegradation::test_a_deleted_secret_degrades_to_no_key": "a missing secret degrades to no key rather than refusing, availability",
    "tests/test_embedding_resolution.py::TestCredentialDegradation::test_a_secret_of_the_wrong_kind_degrades": "a wrong-kind secret degrades to no key rather than refusing, availability",
    "tests/test_mcp_connections.py::TestMcpConnectionService::test_a_pre_registered_public_client_needs_no_secret": "a public client with no secret is the accepted path, accept-complement",
    "tests/integration/test_usage_stats_sql.py::TestPendingApprovals::test_counts_the_callers_parked_runs_not_their_approvals": "counts the caller's parked runs for the dashboard, reporting, no refusal",
    "tests/integration/test_vault_usage_batch.py::test_it_groups_agents_by_the_secret_their_draft_binds": "groups agents using each secret, usage query, no refusal",
    "tests/integration/test_vault_usage_batch.py::test_no_secret_ids_asks_nothing": "empty secret-id input returns empty, edge case, no refusal",
    "tests/integration/test_vault_usage_batch.py::test_the_same_secret_bound_twice_counts_the_agent_once": "dedups an agent that binds a secret twice, usage query, no refusal",
    "tests/test_agent_chat.py::TestWhatTheTurnCost::test_an_agent_whose_budget_block_names_no_amount_has_no_cap": "reports no cap when the budget names no amount, reporting, no refusal",
    "tests/test_agent_chat.py::TestWhatTheTurnCost::test_an_agent_with_no_budget_block_reports_no_cap_of_its_own": "reports no agent cap when the budget block is absent, reporting, no refusal",
    "tests/test_agent_observability.py::TestInstrumentation::test_a_secret_deleted_after_publish_leaves_the_agent_running": "a deleted tracing secret degrades gracefully, resilience, no refusal/masking",
    "tests/test_agent_session.py::TestATurnThatDidNotFinish::test_a_budget_stop_says_why_the_answer_stopped": "surfaces an error frame explaining the budget stop, display, no enforcement",
    "tests/test_agent_spec_and_factory.py::TestBudgetComposition::test_an_agent_with_no_budget_under_an_uncapped_org_is_unlimited": "no budget under an uncapped org yields no limit, config, no refusal",
    "tests/test_agent_spec_and_factory.py::TestBudgetComposition::test_budgets_are_decimal_not_float": "budgets are stored as exact Decimal, precision, no refusal",
    "tests/test_agent_templates.py::TestWhatAManifestMayCarry::test_a_budget_that_is_not_a_number_is_dropped_rather_than_guessed": "a non-numeric template budget is dropped, manifest parsing, no security refusal",
    "tests/test_capability_edges.py::TestFactoryHelpers::test_a_float_budget_becomes_an_exact_decimal": "a float budget becomes an exact Decimal, precision helper, no refusal",
    "tests/test_channel_live_reply.py::TestAnEmptyAnswerTellsItsReasonsApart::test_a_budget_stop_says_the_ceiling_was_hit_not_approval": "picks the budget-stop message over approval wording, display, no enforcement",
    "tests/test_channel_live_reply.py::TestAnEmptyAnswerTellsItsReasonsApart::test_an_answer_empty_for_any_other_reason_does_not_claim_approval": "an empty answer does not falsely claim approval or budget, message text, no enforcement",
    "tests/test_config.py::TestStoreTls::test_a_plaintext_redis_url_carries_no_tls_parameters": "a plaintext redis URL carries no TLS params, config, keyword coincidental",
    "tests/test_config.py::TestStoreTls::test_both_urls_are_plaintext_by_default": "store URLs are plaintext by default, config default, keyword coincidental",
    "tests/test_conversation_search.py::TestWhatARenderedTranscriptCosts::test_the_first_turn_is_written_even_when_it_alone_blows_the_budget": "the first turn is written past the character budget, text limit, not spend",
    "tests/test_conversation_search.py::TestWhatARenderedTranscriptCosts::test_the_window_stops_at_the_budget_and_reports_where": "a character budget bounds transcript rendering, text limit, not a spend budget",
    "tests/test_coverage_edges.py::TestRunNotifications::test_a_budget_stop_is_reported_with_the_reason_it_gave": "a budget-stop notification carries reason and scope, notification, no enforcement",
    "tests/test_email_smtp_provider.py::test_tls_off_is_plaintext_whatever_the_mode_says": "TLS-off SMTP is plaintext regardless of mode, config, keyword coincidental",
    "tests/test_email_smtp_provider.py::test_tls_off_sends_plaintext_and_never_upgrades": "TLS-off SMTP stays plaintext and never upgrades, config, keyword coincidental",
    "tests/test_embed_frames.py::TestATurnThatProducedNoWords::test_a_run_stopped_by_its_budget_says_so": "the embed shows a usage-limit message for a budget stop, display, no enforcement",
    "tests/test_ingestion_embedding_key.py::TestWhenTheChosenKeyCannotBeUsed::test_a_secret_of_the_wrong_kind_says_which_collection_chose_it": "a wrong-kind ingestion key raises a config error naming the collection, diagnostics, no security boundary",
    "tests/test_mcp_connection_repo.py::TestListOauthConnections::test_the_sweep_reads_the_whole_deployment_rather_than_one_tenant": "the OAuth sweep is intentionally deployment-wide, not tenant-scoped, health query",
    "tests/test_mcp_connections.py::TestGithubPortalOAuth::test_a_start_without_a_stored_secret_is_a_clean_4xx_not_a_500": "a missing secret yields a clean 4xx and no row, error robustness, no security boundary",
    "tests/test_model_profiles.py::TestAnEndpointOfItsOwn::test_a_keyless_profile_resolves_with_no_secret_at_all": "a keyless model profile resolves with no secret, feature, no refusal",
    "tests/test_notifications.py::TestApprovalRequested::test_an_agent_can_send_approvals_only_to_whoever_asked": "the approval alert routes to the initiator only, audience routing, no refusal",
    "tests/test_notifications.py::TestApprovalRequested::test_the_occurrence_id_is_the_approval_not_the_run": "the notification dedup key is keyed on the approval id, occurrence-id correctness, no refusal",
    "tests/test_notifications.py::TestBudgetExceeded::test_an_agent_can_silence_its_own_budget_alert": "a disabled budget alert sends nothing, alert config, no refusal",
    "tests/test_notifications.py::TestEveryLinkNamesItsOrganization::test_the_approval_alert_names_the_runs_organization": "the approval alert link names the run's org, deep-link feature, no refusal",
    "tests/test_notifications.py::TestEveryLinkNamesItsOrganization::test_the_budget_alert_names_the_runs_organization": "the budget alert link names the org, deep-link feature, no refusal",
    "tests/test_notifications.py::TestWhereAnAlertSends::test_the_approval_alert_addresses_the_queue_not_the_builder": "the approval alert links to the queue not the agent editor, link correctness, no refusal",
    "tests/test_sandbox_workspace.py::TestContainerBackedWorkspaces::test_a_docker_workspace_labels_its_tenant_and_reattaches": "a docker workspace labels its tenant for accounting and reattaches, feature, no isolation refusal",
    "tests/test_sandbox_workspace.py::TestDrawingAHostsImages::test_the_budget_bounds_a_page_of_photographs": "a thumbnail budget bounds image reads, resource limit, not a spend budget",
    "tests/test_services_organizations.py::TestOrganizationService::test_a_new_team_org_starts_with_the_default_monthly_budget": "a new team org gets the default monthly budget, default config, no refusal",
    "tests/test_services_organizations.py::TestOrganizationService::test_a_personal_org_starts_with_the_default_monthly_budget": "a personal org gets the default monthly budget, default config, no refusal",
    "tests/test_services_organizations.py::TestOrganizationService::test_the_default_budget_can_be_disabled": "the default budget can be disabled, config, no refusal",
    "tests/test_stats.py::TestTheComposedAnswer::test_org_scope_carries_active_users_and_no_approvals_count": "org-scope stats carry active users, not the approvals count, reporting, no refusal",
    "tests/test_stats.py::TestTheComposedAnswer::test_own_scope_carries_the_approvals_count_and_no_member_table": "own-scope stats carry the approvals count, reporting, no refusal",
    "tests/test_subagent_nested_resume.py::TestWhatADelegateSpentBeforeItParked::test_an_unpriced_segment_before_the_approval_still_marks_the_row": "cost accounting marks a partial floor when a delegate parked at an approval, accounting precision, no refusal",
    "tests/test_transcription.py::TestEveryFailureIsHarmless::test_a_profile_whose_secret_is_gone_is_skipped_for_the_next": "a profile with a missing secret is skipped and the next tried, failover, no refusal",
    "tests/test_usage_report.py::TestHowMuchOfTheMonthIsGone::test_the_share_of_the_budget_spent": "computes the budget percent for the report, reporting, no refusal",
    "tests/test_usage_report.py::TestTheFrameAChatReads::test_the_budget_share_travels_with_it": "the usage frame carries the budget percent, display, no refusal",
    "tests/test_usage_report.py::TestTheLineAChannelCarries::test_no_cap_means_no_budget_clause_rather_than_a_zero": "no cap means no budget clause in the footer, display, no refusal",
    "tests/test_usage_report.py::TestTheLineAChannelCarries::test_the_budget_share_is_named_when_there_is_a_cap": "the footer names the budget share, display, no refusal",
    "tests/test_usage_report.py::TestWhenAChannelSaysIt::test_near_limit_speaks_once_the_budget_is_close": "near-limit reporting threshold, reporting, no refusal",
    "tests/test_vault.py::TestRotation::test_a_secret_sealed_under_the_old_master_key_survives_a_real_rotation": "a secret survives a real master-key rotation, rotation correctness, no refusal",
    "tests/test_vault.py::TestRotation::test_rewrap_preserves_the_secret": "rewrap preserves the secret across a version bump, rotation round-trip, no refusal",
    "tests/test_web_search.py::TestConfiguration::test_a_keyless_method_publishes_without_a_secret": "a keyless web-search method needs no secret, conditional requirement, no refusal",
}


def _mentions_security(node: ast.AST) -> bool:
    """Whether an AST expression applies `pytest.mark.security`.

    Covers the two forms the suite uses - a `@pytest.mark.security` decorator and
    a `pytestmark = [..., pytest.mark.security]` assignment (single value or a
    list). Unparsing and matching the attribute path is enough because no marker
    here is built dynamically.
    """

    return "mark.security" in ast.unparse(node)


def _pytestmark_is_security(body: list[ast.stmt]) -> bool:
    """Whether a module or class body assigns a `security` marker to `pytestmark`."""

    for node in body:
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
            if any(t.id == "pytestmark" for t in targets) and _mentions_security(node.value):
                return True
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "pytestmark"
            and node.value is not None
            and _mentions_security(node.value)
        ):
            return True
    return False


def _decorated_security(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_mentions_security(dec) for dec in node.decorator_list)


class _TestFn(NamedTuple):
    nodeid: str
    keyword: str
    marked: bool


def _keyword_for(module_stem: str, func_name: str) -> str | None:
    hay = f"{module_stem} {func_name}".lower()
    for kw in KEYWORDS:
        if kw in hay:
            return kw
    return None


def _iter_test_functions() -> list[_TestFn]:
    """Every collected test function, its keyword match and whether it is marked.

    Walks the same files pytest collects (`test_*.py`, `*_test.py`) and resolves
    the effective marker from the module, the class and the function together.
    """

    results: list[_TestFn] = []
    files = sorted(
        p
        for p in TESTS_ROOT.rglob("*.py")
        if p.name.startswith("test_") or p.name.endswith("_test.py")
    )
    for path in files:
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        stem = path.stem
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_marked = _pytestmark_is_security(tree.body)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
                "test_"
            ):
                keyword = _keyword_for(stem, node.name)
                if keyword is not None:
                    marked = module_marked or _decorated_security(node)
                    results.append(_TestFn(f"{rel}::{node.name}", keyword, marked))
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                class_marked = _decorated_security(node) or _pytestmark_is_security(node.body)
                for sub in node.body:
                    if not (
                        isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and sub.name.startswith("test_")
                    ):
                        continue
                    keyword = _keyword_for(stem, sub.name)
                    if keyword is not None:
                        marked = module_marked or class_marked or _decorated_security(sub)
                        results.append(_TestFn(f"{rel}::{node.name}::{sub.name}", keyword, marked))
    return results


class TestEveryRefusalTestIsMarked:
    def test_keyword_matching_tests_carry_the_marker_or_are_exempt(self) -> None:
        violations: list[str] = []
        for fn in _iter_test_functions():
            if fn.marked or fn.nodeid in EXEMPT:
                continue
            violations.append(f"{fn.nodeid}  (matched '{fn.keyword}')")
        assert not violations, (
            "These tests match the security keyword net but neither carry "
            "@pytest.mark.security nor appear in EXEMPT. Mark the refusals; add a "
            "coincidental match to EXEMPT with a one-line reason:\n  " + "\n  ".join(violations)
        )


class TestNoStaleExemptions:
    def test_every_exemption_still_exists_and_still_matches(self) -> None:
        live = {fn.nodeid for fn in _iter_test_functions()}
        stale = sorted(nodeid for nodeid in EXEMPT if nodeid not in live)
        assert not stale, (
            "EXEMPT names tests that no longer exist or no longer match the "
            "keyword net - remove them:\n  " + "\n  ".join(stale)
        )


class TestTheMarkerIsLive:
    def test_the_marker_is_registered(self) -> None:
        with (BACKEND_ROOT / "pyproject.toml").open("rb") as handle:
            config = tomllib.load(handle)
        markers = config["tool"]["pytest"]["ini_options"]["markers"]
        assert any(m.startswith("security:") for m in markers), (
            "the `security` marker must be registered in [tool.pytest.ini_options]"
        )

    def test_the_marker_selects_a_non_empty_set(self) -> None:
        marked = [fn.nodeid for fn in _iter_test_functions() if fn.marked]
        assert marked, "no test carries @pytest.mark.security - the marker is dead"
