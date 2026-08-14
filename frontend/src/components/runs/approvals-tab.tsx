"use client";

import { useLocale, useTranslations } from "next-intl";
import { CheckCircle2, XCircle } from "lucide-react";

import { ApprovalDelegate } from "@/components/runs/approval-delegate";
import { ErrorState } from "@/components/states";
import {
  Badge,
  Button,
  DataTable,
  ListCard,
  ListCardEmpty,
  ListCardFootRow,
  type Column,
} from "@/components/ui";
import { useApprovalHistory, useApprovals } from "@/hooks";
import { periodEnd, periodStart, type Period } from "@/lib/dashboard/period";
import { formatDate } from "@/lib/utils";
import type { ToolApproval } from "@/types/runs";

const DECISION_LABEL: Record<string, string> = {
  pending: "decisionPending",
  approved: "decisionApproved",
  rejected: "decisionRejected",
  expired: "decisionExpired",
};

const DECISION_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "default",
  approved: "secondary",
  rejected: "destructive",
  expired: "outline",
};

/**
 * Every approval, one table: what is waiting on a person at the top, the
 * record of what was decided under it - the same rows in two states, so two
 * different cards for them was one container too many.
 *
 * A pending row keeps its arguments *expanded*: approving a tool name without
 * seeing what it will do is a rubber stamp, not approval. A decided row folds
 * them - the decision has been made, the arguments are the record's detail.
 * Deciding the last outstanding call also resumes the run (see `useApprovals`);
 * the buttons disable while any decision settles, so a double-click cannot
 * decide twice.
 *
 * Every row opens the run it belongs to - the drawer is where the surrounding
 * conversation is read, which is usually what an approver wants before saying
 * yes.
 *
 * Only ever rendered for a caller holding `approvals:decide`; that is the
 * page's decision, not this component's. A failed queue read says so rather
 * than drawing "nothing waiting" - the one sentence this table must not say
 * when it does not know.
 */
export function ApprovalsTab({
  period,
  onFocusRun,
}: {
  period: Period;
  onFocusRun: (runId: string | null) => void;
}) {
  const t = useTranslations("pages.runs");
  const locale = useLocale();
  const { approvals, total, isLoading, error, decide, refetch } = useApprovals();
  const history = useApprovalHistory({ from: periodStart(period), to: periodEnd(period) });

  const rows: ToolApproval[] = [...approvals, ...history.approvals];

  const columns: Column<ToolApproval>[] = [
    {
      key: "tool",
      header: t("toolColumn"),
      className: "pl-5",
      cell: (approval) => (
        <div className="max-w-xl space-y-2">
          <div className="space-y-1">
            <span className="block font-mono text-xs">{approval.tool_id}</span>
            <ApprovalDelegate approval={approval} />
          </div>
          {approval.status === "pending" ? (
            <pre className="bg-muted/40 overflow-x-auto rounded p-2 text-xs">
              {JSON.stringify(approval.tool_args, null, 2)}
            </pre>
          ) : (
            <details>
              {/* Toggling the disclosure must not also open the run the row
                  would - the reader asked to see the arguments, not to leave. */}
              <summary
                onClick={(event) => event.stopPropagation()}
                className="text-muted-foreground cursor-pointer text-xs select-none"
              >
                {t("showArguments")}
              </summary>
              <pre className="bg-muted/40 mt-1 overflow-x-auto rounded p-2 text-xs">
                {JSON.stringify(approval.tool_args, null, 2)}
              </pre>
            </details>
          )}
        </div>
      ),
    },
    {
      key: "decision",
      header: t("decisionColumn"),
      cell: (approval) => (
        <Badge variant={DECISION_VARIANT[approval.status] ?? "outline"}>
          {t(DECISION_LABEL[approval.status] ?? "decisionExpired")}
        </Badge>
      ),
    },
    {
      key: "askedBy",
      header: t("askedByColumn"),
      cell: (approval) => (
        <span className="text-muted-foreground text-xs">{approval.triggered_by_email ?? "-"}</span>
      ),
    },
    {
      key: "decidedBy",
      header: t("decidedBy"),
      cell: (approval) => (
        <span className="text-muted-foreground text-xs">{approval.decided_by_email ?? "-"}</span>
      ),
    },
    {
      key: "parked",
      header: t("parkedColumn"),
      cell: (approval) => (
        <span className="text-muted-foreground text-xs whitespace-nowrap">
          {approval.created_at ? formatDate(approval.created_at, locale) : "-"}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      className: "w-0 pr-5",
      cell: (approval) =>
        approval.status === "pending" ? (
          <div className="flex justify-end gap-2">
            <Button
              size="sm"
              disabled={decide.isPending}
              onClick={(event) => {
                event.stopPropagation();
                decide.mutate({ id: approval.id, approved: true });
              }}
            >
              <CheckCircle2 className="h-4 w-4" />
              {t("approve")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={decide.isPending}
              onClick={(event) => {
                event.stopPropagation();
                decide.mutate({ id: approval.id, approved: false });
              }}
            >
              <XCircle className="h-4 w-4" />
              {t("reject")}
            </Button>
          </div>
        ) : null,
    },
  ];

  return (
    <ListCard
      title={t("approvalsTitle")}
      counted={
        isLoading || history.isLoading
          ? null
          : t("approvalsCounted", { waiting: total, decided: history.total })
      }
      contentClassName="p-0"
    >
      {error ? (
        <ErrorState
          title={t("queueCouldNotBeRead")}
          description={t("aParkedRunIsStill")}
          cta={{ label: t("tryAgain"), onClick: () => void refetch() }}
          className="m-5"
        />
      ) : (
        <>
          <DataTable<ToolApproval>
            columns={columns}
            rows={rows}
            getRowKey={(approval) => approval.id}
            loading={isLoading}
            onRowClick={(approval) => onFocusRun(approval.run_id)}
            empty={
              <ListCardEmpty
                icon={CheckCircle2}
                title={t("nothingWaiting")}
                description={t("agentsAreRunningWithout")}
              />
            }
            className="rounded-none border-0 bg-transparent"
          />
          {/* The queue is one page of the endpoint's fifty; the figure above
              and the tab badge both report the server's total, so without this
              line a badge reading 120 sits over 50 rows with nothing
              explaining the gap. */}
          {total > approvals.length && (
            <ListCardFootRow>
              <p className="text-muted-foreground text-xs" role="note">
                {t("showingTheOldestOf", { shown: approvals.length, total })}
              </p>
            </ListCardFootRow>
          )}
          {history.error != null && (
            <ListCardFootRow>
              <p className="text-muted-foreground text-xs" role="note">
                {t("decisionsCouldNotBeRead")}
              </p>
            </ListCardFootRow>
          )}
        </>
      )}
    </ListCard>
  );
}
