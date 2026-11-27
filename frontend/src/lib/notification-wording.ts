import type { Translate } from "@/lib/agent-step-captions";
import { formatCostUsd } from "@/lib/utils";

/** The routine sentences the server names by code; any other keeps the English summary. */
const ROUTINE_DETAILS = [
  "run_failed",
  "run_budget",
  "run_guardrail",
  "trigger_auto_stopped",
  "computer_start_failed",
  "review_sources",
  "desktop_review",
  "computer_waiting",
  "source_changed",
  "agent_misconfigured",
  "chat_unavailable",
  "needs_agent",
  "access_revoked",
  "source_unavailable",
  "not_completed",
  "budget_paused",
  "delivery_unavailable",
  "watch_auto_stopped",
];

/** Audited actions with a sentence of their own; the rest are named by their action. */
const SECURITY_ACTIONS: Record<string, string> = {
  "admin.user.impersonate": "admin_user_impersonate",
  "admin.user.impersonation_ended": "admin_user_impersonation_ended",
  "admin.user.update": "admin_user_update",
  "admin.user.delete": "admin_user_delete",
  "secret.created": "secret_created",
  "secret.rotated": "secret_rotated",
  "secret.updated": "secret_updated",
  "secret.deleted": "secret_deleted",
  "sandbox_connection.created": "sandbox_connection_created",
  "sandbox_connection.deleted": "sandbox_connection_deleted",
};

const COALESCED = {
  security_event: "securityEvent",
  configuration_changed: "configurationChanged",
  background_task_paused: "backgroundTaskPaused",
} as const;

const VERDICTS = ["passed", "failed", "inconclusive", "baseline_set"];

interface Reason {
  code: string;
  value?: number | null;
  limit?: number | null;
  detail?: string | null;
}

/** Dollars to the cent, or to the place spend is shown at when the cent would read as nothing. */
export function usd(value: string): string {
  const amount = Number(value);
  return amount > 0 && amount < 0.01 ? formatCostUsd(amount) : `$${amount.toFixed(2)}`;
}

/** A row's value by name; the server serves a wording only with every value it requires. */
type Values = (key: string) => string;

const named = (value: string) => (value ? "yes" : "no");

/** One threshold reason, in words. */
function reasonText(reason: Reason, t: Translate): string {
  const value = reason.value ?? 0;
  const fromZero = reason.detail === "zero_baseline";
  switch (reason.code) {
    case "pass_rate_below":
      return t("kind.evalReason.passRateBelow", { value, limit: reason.limit ?? 0 });
    case "nothing_graded":
      return t("kind.evalReason.nothingGraded");
    case "regressions":
      return t("kind.evalReason.regressions", { count: Math.trunc(value) });
    case "cost_per_pass_rise":
      return fromZero
        ? t("kind.evalReason.costRiseFromZero")
        : t("kind.evalReason.costRise", { value });
    case "p95_rise":
      return fromZero
        ? t("kind.evalReason.latencyRiseFromZero")
        : t("kind.evalReason.latencyRise", { value });
    case "ungraded":
      return t("kind.evalReason.ungraded", { count: Math.trunc(value) });
    case "incomplete":
      return t("kind.evalReason.incomplete", { count: Math.trunc(value) });
    case "crashed":
      return t("kind.evalReason.crashed", { count: Math.trunc(value) });
    default:
      return t("kind.evalReason.invalid");
  }
}

function suiteSummary(v: Values, t: Translate): string | null {
  let reasons: Reason[];
  try {
    reasons = JSON.parse(v("reasons")) as Reason[];
  } catch {
    return null;
  }
  if (!Array.isArray(reasons)) return null;
  const failed = v("status") === "failed" ? "yes" : "no";
  const said = reasons.length
    ? reasons.map((reason) => reasonText(reason, t)).join("; ")
    : t("kind.evalReason.belowThreshold");
  const line = t("kind.evalSuiteFailed", {
    suite: v("suite_name"),
    failed,
    versioned: named(v("version")),
    agent: v("agent_name"),
    version: v("version"),
    reasons: said,
  });
  if (!v("cases")) return line;
  const cases = t("kind.evalSuiteCases", {
    failed,
    cases: v("cases"),
    more: Number(v("more_cases")),
  });
  return `${line} ${cases}`;
}

function logAlert(v: Values, t: Translate): string {
  const minutes = Number(v("window_minutes"));
  return t("kind.workflowLogAlert", {
    rule: v("rule_name"),
    count: Number(v("count")),
    workflow: v("workflow_name"),
    unit: minutes >= 120 ? "hours" : "minutes",
    hours: Math.floor(minutes / 60),
    minutes,
  });
}

/**
 * A row the server names a `wording` for, in the reader's language, from the values it
 * kept; `null` for a wording or a code this console does not know, which keeps the
 * English summary.
 */
export function wordedSummary(params: Record<string, string>, t: Translate): string | null {
  const v: Values = (key) => params[key] ?? "";
  switch (params.wording) {
    case "run_completed":
      return t("kind.runCompleted", { agent: v("agent_name") });
    case "routine_finished":
      return v("excerpt")
        ? t("kind.routineFinishedExcerpt", { routine: v("routine_name"), excerpt: v("excerpt") })
        : t("kind.routineFinished", { routine: v("routine_name") });
    case "answered_while_away":
      return t("kind.answeredWhileAway", { agent: v("agent_name") });
    case "answer_failed":
      return t("kind.answerFailed", { agent: v("agent_name"), error: v("error") });
    case "run_failed":
      return v("error")
        ? t("kind.runFailedError", { agent: v("agent_name"), error: v("error") })
        : t("kind.runFailed", { agent: v("agent_name") });
    case "routine_budget_paused":
      return t("kind.routineBudgetPaused", {
        named: named(v("routine_name")),
        routine: v("routine_name"),
        kind: v("routine_kind"),
        limit: usd(v("limit")),
        spent: usd(v("spent")),
      });
    case "routine_blocked": {
      const code = v("routine_detail");
      if (!ROUTINE_DETAILS.includes(code)) return null;
      return t("kind.routineBlocked", {
        named: named(v("routine_name")),
        routine: v("routine_name"),
        detail: t(`kind.routineDetail.${code}`, { failures: Number(v("failures")) }),
      });
    }
    case "capability_requested":
      return t("kind.capabilityRequested", {
        requester: v("requester_name"),
        capability: v("capability_name"),
        agent: v("agent_name"),
        reason: v("reason"),
      });
    case "suggestions_ready":
      return t("kind.suggestionsReady", { count: Number(v("count")) });
    case "briefing":
      return t("kind.briefing", { count: Number(v("count")) });
    case "ingestion_failed":
      return t("kind.ingestionFailed", { file: v("filename"), error: v("error_message") });
    case "sync_completed":
      return t("kind.syncCompleted", {
        collection: v("collection_name"),
        ingested: Number(v("ingested")),
        updated: Number(v("updated")),
        skipped: Number(v("skipped")),
        removed: Number(v("removed")),
        failed: Number(v("failed")),
      });
    case "sync_failed":
      return t("kind.syncFailed", {
        named: named(v("collection_name")),
        collection: v("collection_name"),
        error: v("error"),
      });
    case "artifact_version_published":
      return t("kind.artifactVersionPublished", {
        title: v("artifact_title"),
        version: v("version"),
      });
    case "artifact_owner_given":
      return t("kind.artifactOwnerGiven", { by: v("by_name"), title: v("title") });
    case "artifact_owner_taken":
      return t("kind.artifactOwnerTaken", {
        by: v("by_name"),
        owner: v("new_owner_name"),
        title: v("title"),
      });
    case "resource_shared":
      return t("kind.resourceShared", { name: v("resource_name"), group: v("group_name") });
    case "invitation_received":
      return t("kind.invitationReceived", {
        inviter: v("inviter_name"),
        organization: v("organization_name"),
        role: v("role"),
      });
    case "conversation_shared":
      return t("kind.conversationShared", {
        by: v("shared_by"),
        titled: named(v("conversation_title")),
        title: v("conversation_title"),
      });
    case "room_mention":
      return t("roomMention", { sender: v("sender"), title: v("title") });
    case "room_thread_reply":
      return t("roomThreadReply", { sender: v("sender"), title: v("title") });
    case "mcp_server_down":
      return t("kind.mcpServerDown", { server: v("server_name") });
    case "mcp_server_recovered":
      return t("kind.mcpServerRecovered", { server: v("server_name") });
    case "eval_suite_reevaluated": {
      const verdict = (value: string) =>
        VERDICTS.includes(value) ? t(`kind.verdict.${value}`) : value;
      return t("kind.evalSuiteReevaluated", {
        suite: v("suite_name"),
        agent: v("agent_name"),
        previous: verdict(v("previous_verdict")),
        status: verdict(v("status")),
      });
    }
    case "eval_suite_failed":
      return suiteSummary(v, t);
    case "promotion_overridden":
      return t("kind.promotionOverridden", {
        version: v("version"),
        agent: v("agent_name"),
        environment: v("environment_name"),
        suites: v("suite_names"),
        reason: v("reason"),
      });
    case "shared_change_applied":
      return t("kind.sharedChangeApplied", {
        named: named(v("name")),
        kind: v("kind"),
        name: v("name"),
        agent: v("agent_name"),
      });
    case "security_event": {
      const action = v("action");
      const key = SECURITY_ACTIONS[action];
      return key ? t(`kind.securityEvent.${key}`) : t("kind.securityEventOther", { action });
    }
    case "background_task_paused":
      return t("kind.backgroundTaskPaused", {
        kind: v("kind"),
        scoped: named(v("organization_name")),
        organization: v("organization_name"),
        reason: v("reason"),
      });
    case "configuration_changed":
      return t("kind.configurationChanged");
    case "usage_report":
      return t("kind.usageReport", { name: v("org_name") });
    case "agent_usage_report":
      return t("kind.usageReport", { name: v("agent_name") });
    case "workflow_log_alert":
      return logAlert(v, t);
    case "coalesced": {
      const key = COALESCED[v("coalesced") as keyof typeof COALESCED];
      return key ? t(`kind.coalesced.${key}`) : null;
    }
    default:
      return null;
  }
}
