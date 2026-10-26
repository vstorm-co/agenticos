"use client";

import Link from "next/link";
import { CheckCircle2, UserCheck, XCircle } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, Button, ListCard } from "@/components/ui";
import { useWorkflowApprovals } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { cn, formatDate } from "@/lib/utils";
import type { WorkflowApprovalRead } from "@/lib/workflows/types";

/**
 * The workflow steps waiting on a person: what each asks, from which workflow,
 * and the two buttons that answer it.
 *
 * Beside the tool approvals rather than inside their table: a step asks a
 * question in its own words and has no tool or arguments, and deciding it
 * wakes a workflow run, not an agent. Nothing is drawn while nothing waits, so
 * the tab keeps opening on the tool queue it always did.
 */
export function WorkflowApprovalsCard() {
  const t = useTranslations("pages.runs");
  const locale = useLocale();
  const { approvals, total, decide } = useWorkflowApprovals();

  if (total === 0) return null;

  return (
    <ListCard
      title={t("stepApprovalsTitle")}
      counted={t("stepApprovalsCounted", { count: total })}
      contentClassName="divide-y p-0"
    >
      {approvals.map((approval) => (
        <div
          key={approval.id}
          className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start sm:justify-between"
        >
          <div className="min-w-0 space-y-1.5">
            <div className="flex items-center gap-2">
              <UserCheck className="text-muted-foreground h-4 w-4 shrink-0" />
              <span className="text-sm font-medium">{approval.title}</span>
            </div>
            {approval.details !== null && (
              <p className="text-foreground/80 text-sm whitespace-pre-wrap">{approval.details}</p>
            )}
            <p className="text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
              <Link
                href={ROUTES.WORKFLOW_RUN_DETAIL(approval.workflow_id, approval.workflow_run_id)}
                className="underline underline-offset-2"
              >
                {approval.workflow_name}
              </Link>
              <span>{formatDate(approval.created_at, locale)}</span>
              {approval.expires_at !== null && (
                <span>
                  {t("stepApprovalExpires", { at: formatDate(approval.expires_at, locale) })}
                </span>
              )}
              {approval.approver_user_ids.length > 0 && (
                <Badge variant="outline">
                  {t("stepApprovalNamed", { count: approval.approver_user_ids.length })}
                </Badge>
              )}
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button
              size="sm"
              disabled={decide.isPending}
              onClick={() => decide.mutate({ id: approval.id, approved: true })}
            >
              <CheckCircle2 className="h-4 w-4" />
              {t("approve")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={decide.isPending}
              onClick={() => decide.mutate({ id: approval.id, approved: false })}
            >
              <XCircle className="h-4 w-4" />
              {t("reject")}
            </Button>
          </div>
        </div>
      ))}
    </ListCard>
  );
}

const DECISION_TONE: Record<string, string> = {
  approved: "bg-success/10 text-success",
  rejected: "bg-destructive/10 text-destructive",
};

const DECISION_LABEL: Record<string, string> = {
  approved: "decisionApproved",
  rejected: "decisionRejected",
  expired: "decisionExpired",
};

/** One workflow step's request somebody already answered, or that lapsed, as a line of the record. */
export function DecidedWorkflowApproval({ approval }: { approval: WorkflowApprovalRead }) {
  const t = useTranslations("pages.runs");
  const locale = useLocale();
  const labelKey = DECISION_LABEL[approval.status];

  return (
    <li className="px-5 py-3">
      <div className="flex items-center gap-3">
        <UserCheck className="text-muted-foreground size-5 shrink-0" aria-hidden />
        <Link
          href={ROUTES.WORKFLOW_RUN_DETAIL(approval.workflow_id, approval.workflow_run_id)}
          className="min-w-0 flex-1 truncate text-sm hover:underline"
        >
          <span className="font-medium">{approval.workflow_name}</span>
          <span className="text-muted-foreground"> · </span>
          {approval.title}
        </Link>
        <span
          className={cn(
            "shrink-0 rounded-full px-2 py-0.5 text-xs font-medium",
            DECISION_TONE[approval.status] ?? "bg-muted text-muted-foreground",
          )}
        >
          {labelKey ? t(labelKey) : approval.status}
        </span>
      </div>
      {approval.note !== null && (
        <p className="text-foreground/80 mt-1 truncate pl-8 text-sm" title={approval.note}>
          {approval.note}
        </p>
      )}
      <p className="text-muted-foreground mt-1 pl-8 text-xs">
        {formatDate(approval.decided_at ?? approval.created_at, locale)}
      </p>
    </li>
  );
}
