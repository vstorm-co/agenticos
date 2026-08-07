"use client";

import { useTranslations } from "next-intl";
import { CheckCircle2, XCircle } from "lucide-react";

import { ApprovalDelegate } from "@/components/runs/approval-delegate";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { useApprovals } from "@/hooks";
import { formatDate, getErrorMessage } from "@/lib/utils";

/**
 * The queue of tool calls waiting on a person, and the two buttons that settle one.
 *
 * Only ever rendered for a caller holding `approvals:decide`. That is not this
 * component's decision and deliberately not its check: reading the queue takes
 * the same permission as deciding one, so the tab is withheld whole - see the
 * page - rather than shown with its buttons removed. A queue somebody can read
 * and cannot act on is a worse answer than no queue.
 *
 * A failed request says so. Every other shape here would draw the empty state
 * for it, and "nothing is waiting for you" is the one sentence this queue must
 * not say when it does not know.
 *
 * The queue is one page of the endpoint's fifty, and says so when there are more.
 * The figure above and the tab badge both report the server's `total`, so without
 * that line a badge reading 120 sits over 50 cards with nothing explaining the
 * gap - and the reading available to somebody working down the queue is that
 * seventy calls went missing.
 */
export function ApprovalsTab() {
  const t = useTranslations("pages.runs");
  const { approvals, total, isLoading, error, decide, refetch } = useApprovals();

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("waitingDecision")}</CardTitle>
        <CardDescription>{t("argumentsAreShownFull")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <LoadingState variant="skeleton-table" columns={2} rows={2} />
        ) : error ? (
          <ErrorState
            title={t("queueCouldNotBeRead")}
            description={getErrorMessage(error, t("aParkedRunIsStill"))}
            cta={{ label: t("tryAgain"), onClick: () => void refetch() }}
          />
        ) : approvals.length === 0 ? (
          <EmptyState
            icon={CheckCircle2}
            title={t("nothingWaiting")}
            description={t("agentsAreRunningWithout")}
          />
        ) : (
          <>
            {total > approvals.length && (
              <p className="text-muted-foreground text-xs" role="note">
                {t("showingTheOldestOf", { shown: approvals.length, total })}
              </p>
            )}
            {approvals.map((approval) => (
              <div key={approval.id} className="space-y-3 rounded-md border p-4">
                <div className="flex items-start justify-between gap-3">
                  {/* The tool and its actor together. Two rows queued from two
                    different delegates are the same tool name twice, so the
                    delegate is what tells them apart - and it is the fact that
                    decides the answer, not a detail a click away. */}
                  <div className="min-w-0 space-y-1">
                    <span className="block font-mono text-sm">{approval.tool_id}</span>
                    <ApprovalDelegate approval={approval} />
                  </div>
                  <span className="text-muted-foreground shrink-0 text-xs">
                    {approval.created_at ? formatDate(approval.created_at) : ""}
                  </span>
                </div>
                <pre className="bg-muted/40 overflow-x-auto rounded p-3 text-xs">
                  {JSON.stringify(approval.tool_args, null, 2)}
                </pre>
                {/* Disabled while any decision is settling. The mutation is one
                  instance shared across the queue, so a second click - on this
                  row or another - before the first POST returns would decide
                  twice; the backend refuses the second, but not sending it is
                  better than surfacing that refusal as a toast. */}
                <div className="flex gap-2">
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
          </>
        )}
      </CardContent>
    </Card>
  );
}
