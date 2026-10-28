"use client";

import type { ReactNode } from "react";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { CheckCircle2 } from "lucide-react";

import { DecidedApproval, PendingApproval } from "@/components/runs/approval-cards";
import { ExportMenu } from "@/components/runs/export-menu";
import { EmptyState, ErrorState } from "@/components/states";
import { ListCard, ListCardFootRow, Pager, Skeleton } from "@/components/ui";
import { useApprovalHistory, useApprovals } from "@/hooks";
import { periodEnd, periodStart, type Period } from "@/lib/dashboard/period";
import { Perm } from "@/types/permissions";

/**
 * Every approval, one card: what is waiting on a person at the top, as
 * requests - who wants to do what, for whom, with what - and the record of
 * what was decided under it, as lines.
 *
 * A pending request keeps its arguments *open*: approving a tool name without
 * seeing what it will do is a rubber stamp, not approval. A decided line folds
 * them - the decision has been made, the arguments are the record's detail.
 * Deciding the last outstanding call also resumes the run (see `useApprovals`);
 * the buttons disable while any decision settles, so a double-click cannot
 * decide twice.
 *
 * Each opens the run it belongs to - the panel is where the surrounding
 * conversation is read, which is usually what an approver wants before saying
 * yes.
 *
 * Only ever rendered for a caller holding `approvals:decide`; that is the
 * page's decision, not this component's. A failed queue read says so rather
 * than drawing "nothing waiting" - the one sentence this table must not say
 * when it does not know.
 */
/** One server page of the queue - `GET /approvals`' own default. */
const APPROVALS_PAGE = 50;

export function ApprovalsTab({
  period,
  onFocusRun,
  periodControl,
}: {
  period: Period;
  onFocusRun: (runId: string | null) => void;
  /**
   * The page's window, drawn first among this tab's own filters: it narrows
   * the same table they do, so it sits with them rather than in a band above.
   */
  periodControl?: ReactNode;
}) {
  const t = useTranslations("pages.runs");
  const range = { from: periodStart(period), to: periodEnd(period) };
  // Which page of the queue. Not keyed on the window the way the history below
  // is: `/approvals` does not narrow the pending queue by date, so the page's
  // period selector does not redefine what is being paged.
  const [page, setPage] = useState(0);

  const { approvals, total, isLoading, error, decide, refetch } = useApprovals({
    skip: page * APPROVALS_PAGE,
  });
  const history = useApprovalHistory(range);

  // A decision removes a row, so the last page can empty under the reader. Step
  // back rather than leaving them on a page that says nothing is waiting while
  // the badge says otherwise (the render-time adjustment pattern).
  const pageCount = Math.max(1, Math.ceil(total / APPROVALS_PAGE));
  if (page >= pageCount) setPage(pageCount - 1);

  return (
    <ListCard
      fill
      title={t("approvalsTitle")}
      counted={
        isLoading || history.isLoading
          ? null
          : t("approvalsCounted", { waiting: total, decided: history.total })
      }
      controls={
        <div className="flex flex-wrap items-center gap-2">
          {periodControl}
          <ExportMenu
            permission={Perm.approvalsDecide}
            endpoint="/approvals/export"
            kind="approvals"
            // Every status the table shows, queue and record alike - absent, the
            // route exports the pending queue alone. Pairs, because the
            // parameter repeats.
            params={[
              ["status", "pending"],
              ["status", "approved"],
              ["status", "rejected"],
              ["status", "expired"],
            ]}
            rangeParams={{ from: "created_from", to: "created_to" }}
            range={range}
          />
        </div>
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
          {/* What is waiting first, as requests a person reads, then the record
              of what was answered, as lines - one card for both, because they
              are the same calls in two states. */}
          {isLoading ? (
            <div className="space-y-3 p-5">
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : approvals.length === 0 && history.approvals.length > 0 ? (
            <div className="flex items-center gap-3 px-5 py-5" role="status">
              <CheckCircle2 className="text-muted-foreground h-5 w-5 shrink-0" aria-hidden />
              <div>
                <p className="text-sm font-medium">{t("nothingWaiting")}</p>
                <p className="text-muted-foreground mt-0.5 text-xs">
                  {t("agentsAreRunningWithout")}
                </p>
              </div>
            </div>
          ) : approvals.length === 0 ? (
            <EmptyState
              className="flex-1 rounded-none border-0 bg-transparent shadow-none"
              icon={CheckCircle2}
              title={t("nothingWaiting")}
              description={t("agentsAreRunningWithout")}
            />
          ) : (
            <section aria-label={t("waitingSection")}>
              <ul className="divide-y">
                {approvals.map((approval) => (
                  <PendingApproval
                    key={approval.id}
                    approval={approval}
                    deciding={decide.isPending}
                    onDecide={(approved) => decide.mutate({ id: approval.id, approved })}
                    onOpenRun={() => onFocusRun(approval.run_id)}
                  />
                ))}
              </ul>
            </section>
          )}
          {history.approvals.length > 0 && (
            <section aria-label={t("decidedSection")} className="border-t">
              <h3 className="text-muted-foreground px-5 pt-4 pb-1 text-xs font-medium">
                {t("decidedSection")}
              </h3>
              <ul className="divide-y">
                {history.approvals.map((approval) => (
                  <DecidedApproval
                    key={approval.id}
                    approval={approval}
                    onOpenRun={() => onFocusRun(approval.run_id)}
                  />
                ))}
              </ul>
            </section>
          )}
          {/* The queue is server-paged. It used to be one page of fifty with a
              line explaining the gap, which left the newest request - the one an
              alert is about - unreachable until enough older calls were decided
              (#1336). The pager is the way to it, and the decide controls stay
              on the row where they belong. */}
          {total > APPROVALS_PAGE && (
            <ListCardFootRow>
              <Pager
                page={page}
                pageCount={pageCount}
                matched={approvals.length}
                total={total}
                onPage={setPage}
                counted={t("approvalCount", { count: total })}
              />
            </ListCardFootRow>
          )}
          {/* The record is one page of the same fifty, newest first - the
              counted line above reports the window's total, so without this
              the gap between "214 decided" and fifty rows goes unexplained. */}
          {history.total > history.approvals.length && (
            <ListCardFootRow>
              <p className="text-muted-foreground text-xs" role="note">
                {t("showingTheNewestOf", {
                  shown: history.approvals.length,
                  total: history.total,
                })}
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
