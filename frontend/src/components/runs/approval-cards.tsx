"use client";

import { useLocale, useTranslations } from "next-intl";
import { CheckCircle2, ExternalLink, XCircle } from "lucide-react";

import { AgentFace } from "@/components/dashboard/agent-face";
import { ApprovalDelegate } from "@/components/runs/approval-delegate";
import { AccountBadge, ApprovalDetails, useActionPhrase } from "@/components/runs/approval-request";
import { Button, SwipeToDecide } from "@/components/ui";
import { callSummary } from "@/lib/approval-view";
import { cn, formatDateTime, timeAgo } from "@/lib/utils";
import type { ToolApproval } from "@/types/runs";

/** Who is asking: the delegate when one is, else the run's own agent. */
function useActor(approval: ToolApproval): string {
  const t = useTranslations("pages.runs");
  return approval.subagent_name ?? approval.agent_name ?? t("anAgent");
}

/**
 * One call waiting on a person: who wants to do what, for whom, with what -
 * and the two answers.
 *
 * A sentence leads rather than a tool id: "Architect wants to Save to memory"
 * is a request somebody can weigh; `write_memory` in a table cell is one they
 * stamp. The arguments are open, because approving without them is the same
 * stamp.
 */
export function PendingApproval({
  approval,
  deciding,
  onDecide,
  onOpenRun,
}: {
  approval: ToolApproval;
  deciding: boolean;
  onDecide: (approved: boolean) => void;
  onOpenRun: () => void;
}) {
  const t = useTranslations("pages.runs");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const actor = useActor(approval);
  const phrase = useActionPhrase();
  const ago = approval.created_at ? timeAgo(approval.created_at, tTime, locale) : null;
  const summary = callSummary(approval.tool_args);

  return (
    <li>
      <SwipeToDecide
        onApprove={() => onDecide(true)}
        onReject={() => onDecide(false)}
        approveLabel={t("approve")}
        rejectLabel={t("reject")}
        disabled={deciding}
        className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start"
      >
        <div className="flex min-w-0 flex-1 gap-3">
          <AgentFace agentId={approval.agent_id} className="size-9 shrink-0" />
          <div className="min-w-0 flex-1 space-y-2">
            <div>
              <p className="text-sm">
                {t.rich("wantsTo", {
                  actor,
                  tool: lowerFirst(phrase(approval.tool_id)),
                  strong: (chunks) => <span className="text-foreground font-medium">{chunks}</span>,
                })}
              </p>
              {summary !== null && (
                <p className="text-foreground/80 mt-1 truncate text-sm" title={summary}>
                  {summary}
                </p>
              )}
              <p className="text-muted-foreground mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                <AccountBadge account={approval.account} />
                {approval.triggered_by_email && (
                  <span>{t("askedFor", { email: approval.triggered_by_email })}</span>
                )}
                {ago !== null && (
                  <span title={formatDateTime(approval.created_at as string, locale)}>{ago}</span>
                )}
                <button
                  type="button"
                  onClick={onOpenRun}
                  className="hover:text-foreground inline-flex items-center gap-1 underline underline-offset-4"
                >
                  {t("openTheRun")}
                  <ExternalLink className="h-3 w-3" aria-hidden />
                </button>
              </p>
            </div>
            <ApprovalDelegate approval={approval} />
            <ApprovalDetails toolName={approval.tool_id} args={approval.tool_args} />
          </div>
        </div>
        <div className="flex shrink-0 gap-2 sm:flex-col">
          <Button size="sm" disabled={deciding} onClick={() => onDecide(true)}>
            <CheckCircle2 className="h-4 w-4" aria-hidden />
            {t("approve")}
          </Button>
          <Button size="sm" variant="outline" disabled={deciding} onClick={() => onDecide(false)}>
            <XCircle className="h-4 w-4" aria-hidden />
            {t("reject")}
          </Button>
        </div>
      </SwipeToDecide>
    </li>
  );
}

const DECISION_TONE: Record<string, string> = {
  approved: "bg-success/10 text-success",
  rejected: "bg-destructive/10 text-destructive",
};

const DECISION_LABEL: Record<string, string> = {
  pending: "decisionPending",
  approved: "decisionApproved",
  rejected: "decisionRejected",
  expired: "decisionExpired",
};

/** One call somebody already answered, as a line of the record. */
export function DecidedApproval({
  approval,
  onOpenRun,
}: {
  approval: ToolApproval;
  onOpenRun: () => void;
}) {
  const t = useTranslations("pages.runs");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const actor = useActor(approval);
  const phrase = useActionPhrase();
  // A status this build does not know is shown as the data it is - labelling it
  // "Expired" would put a specific claim on a row the backend said something
  // newer about.
  const labelKey = DECISION_LABEL[approval.status];

  return (
    <li className="px-5 py-3">
      <div className="flex items-center gap-3">
        <AgentFace agentId={approval.agent_id} className="size-7 shrink-0" />
        <button
          type="button"
          onClick={onOpenRun}
          className="min-w-0 flex-1 text-left text-sm hover:underline"
        >
          <span className="font-medium">{actor}</span>
          <span className="text-muted-foreground"> · </span>
          {phrase(approval.tool_id)}
        </button>
        <span
          className={cn(
            "shrink-0 rounded-full px-2 py-0.5 text-xs font-medium",
            DECISION_TONE[approval.status] ?? "bg-muted text-muted-foreground",
          )}
        >
          {labelKey ? t(labelKey) : approval.status}
        </span>
      </div>
      <div className="text-muted-foreground mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 pl-10 text-xs">
        <AccountBadge account={approval.account} />
        {approval.triggered_by_email && (
          <span>{t("askedFor", { email: approval.triggered_by_email })}</span>
        )}
        {approval.decided_by_email && (
          <span>{t("decidedByWhom", { email: approval.decided_by_email })}</span>
        )}
        {/* Who, and how. A call granted by a conversation that had waived
            approvals is `approved` like any other, and nobody read these
            arguments before they ran - so the line says so (#925). */}
        {approval.decided_via === "standing" && <span>{t("decidedByStandingConsent")}</span>}
        {approval.created_at && (
          <span title={formatDateTime(approval.created_at, locale)}>
            {timeAgo(approval.created_at, tTime, locale)}
          </span>
        )}
        <div className="w-full pt-1">
          <ApprovalDetails toolName={approval.tool_id} args={approval.tool_args} />
        </div>
      </div>
    </li>
  );
}

/** "Search in Notion" read inside a sentence: "wants to search in Notion". */
function lowerFirst(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1);
}
