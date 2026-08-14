"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { LoadingState } from "@/components/states";
import { Card, CardContent } from "@/components/ui";
import { useApprovals, useRuns, useSpend } from "@/hooks";
import { periodEnd, periodStart, type Period } from "@/lib/dashboard/period";

/**
 * Money, runs, and what is waiting - the organization's, over one shared window.
 *
 * Read unnarrowed even when the table below carries `?agent=`. Narrowed, the
 * count would be one agent's runs - counted the per-agent way, with delegations
 * included - sitting beside the organization's bill, which is two different
 * questions with one label between them.
 *
 * The window is the whole point of the pair, and it is the page's period
 * control, shared with the table and the Spend tab. Unwindowed the count read
 * *all time*, so an organization three years old showed "8,412 runs" next to
 * "$31.20" and the obvious reading of the two was wrong by three years (#198).
 * Two figures on one row either share a window or each says which window it is;
 * these share the page's, so picking a range re-answers both.
 *
 * The spend figure is summed from the per-agent rows rather than read off a
 * field, because `month_to_date_usd` deliberately ignores the window - it is
 * the invoice figure - and the window's own total has no field of its own. The
 * per-agent rows are top-level runs only, so the sum counts each delegation
 * once, inside its parent.
 *
 * A skeleton until both have answered, because a nought here is a claim. "$0.00"
 * and "0 runs" are what an organization that has never run an agent looks like,
 * and drawing that for a request still in flight tells a new reader their
 * deployment is not working.
 */
export function ActivityFigures({ canDecide, period }: { canDecide: boolean; period: Period }) {
  const t = useTranslations("pages.runs");
  const range = { from: periodStart(period), to: periodEnd(period) };
  const { spend, isLoading: spendLoading, error: spendError } = useSpend(range);
  const {
    total: organizationRuns,
    isLoading: runsLoading,
    error: runsError,
  } = useRuns(undefined, { startedFrom: range.from, startedTo: range.to });
  // `total`, not the length of the page. `GET /approvals` answers fifty rows at
  // a time and nothing here asks for more, so a queue of a hundred and twenty
  // read "50" and went on reading it however long the queue grew - the same
  // page-length-as-a-count defect (#198) the Runs figure beside it was fixed for.
  const { total: waiting, error: approvalsError } = useApprovals({ enabled: canDecide });

  if (spendLoading || runsLoading) {
    return (
      <LoadingState
        variant="stats"
        rows={canDecide ? 3 : 2}
        className="gap-3 sm:grid-cols-3 lg:grid-cols-3"
      />
    );
  }

  return (
    <div className={canDecide ? "grid gap-3 sm:grid-cols-3" : "grid gap-3 sm:grid-cols-2"}>
      <Figure label={t("spendWindow")} caption={t("overTheWindowAbove")} failed={!!spendError}>
        ${(spend?.by_agent ?? []).reduce((sum, row) => sum + Number(row.cost_usd), 0).toFixed(2)}
      </Figure>
      {/* The count the server reports, not the length of one page of fifty -
          top-level runs only, and over the same window, which together are what
          make it agree with the figure beside it. A fan-out turn is one run
          here and one run in that total; it used to be four and one, over all
          time against one month. */}
      <Figure label={t("runs")} caption={t("delegationsCountedInTheir")} failed={!!runsError}>
        {organizationRuns}
      </Figure>
      {canDecide && (
        <Figure label={t("waitingPerson")} failed={!!approvalsError}>
          {waiting}
        </Figure>
      )}
    </div>
  );
}

/**
 * One stat card - or, when its own query failed, the fact that it did.
 *
 * `failed` renders "—" and a "couldn't load" caption in place of the number,
 * because a figure has no honest zero to fall back to: "$0.00" and "0 runs" are
 * what a working, empty deployment looks like, and drawing that for a request
 * that never answered tells the reader something false about their money and
 * their agents. The three figures fetch separately, so one failing must not
 * blank the other two.
 */
function Figure({
  label,
  caption,
  failed,
  children,
}: {
  label: string;
  caption?: string;
  failed: boolean;
  children: ReactNode;
}) {
  const t = useTranslations("pages.runs");
  return (
    <Card>
      <CardContent className="space-y-1 p-5">
        <p className="text-muted-foreground text-xs tracking-wide uppercase">{label}</p>
        {failed ? (
          <>
            <p className="text-muted-foreground font-mono text-2xl" role="alert">
              —
            </p>
            <p className="text-destructive text-xs">{t("figureCouldNotLoad")}</p>
          </>
        ) : (
          <>
            <p className="font-mono text-2xl">{children}</p>
            {caption && <p className="text-muted-foreground text-xs">{caption}</p>}
          </>
        )}
      </CardContent>
    </Card>
  );
}
