"use client";

import { useTranslations } from "next-intl";

import { LoadingState } from "@/components/states";
import { Card, CardContent } from "@/components/ui";
import { useApprovals, useRuns, useSpend } from "@/hooks";

/**
 * The first instant of the current calendar month, in UTC.
 *
 * Calendar-aligned rather than a rolling thirty days, because that is what the
 * spend figure beside it reports and what an invoice can be reconciled against.
 * UTC because the backend's own `month_start` is UTC: a browser in Warsaw asking
 * for its local month boundary would ask for a different set of rows than the
 * money was summed over.
 */
function monthStart(): string {
  const now = new Date();
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1)).toISOString();
}

/**
 * Money, runs, and what is waiting - the organization's, over one shared window.
 *
 * Read unnarrowed even when the table below carries `?agent=`. Narrowed, the
 * count would be one agent's runs - counted the per-agent way, with delegations
 * included - sitting beside the organization's bill, which is two different
 * questions with one label between them.
 *
 * The window is the whole point of the pair. Unwindowed the count read *all
 * time*, so an organization three years old showed "8,412 runs" next to "$31.20"
 * and the obvious reading of the two was wrong by three years (#198). Two figures
 * on one row either share a window or each says which window it is; these share,
 * and the caption underneath says so.
 *
 * A skeleton until both have answered, because a nought here is a claim. "$0.00"
 * and "0 runs" are what an organization that has never run an agent looks like,
 * and drawing that for a request still in flight tells a new reader their
 * deployment is not working.
 */
export function ActivityFigures({ canDecide }: { canDecide: boolean }) {
  const t = useTranslations("pages.runs");
  const { spend, isLoading: spendLoading } = useSpend(30);
  const { total: organizationRuns, isLoading: runsLoading } = useRuns(undefined, {
    startedFrom: monthStart(),
  });
  const { approvals } = useApprovals({ enabled: canDecide });

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
      <Card>
        <CardContent className="space-y-1 p-5">
          <p className="text-muted-foreground text-xs tracking-wide uppercase">{t("spendMonth")}</p>
          <p className="font-mono text-2xl">${Number(spend?.month_to_date_usd ?? 0).toFixed(2)}</p>
          <p className="text-muted-foreground text-xs">{t("calendarMonthSoReconciles")}</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="space-y-1 p-5">
          <p className="text-muted-foreground text-xs tracking-wide uppercase">{t("runs")}</p>
          {/* The count the server reports, not the length of one page of fifty -
              top-level runs only, and over the same calendar month, which
              together are what make it agree with the figure beside it. A
              fan-out turn is one run here and one run in that total; it used to
              be four and one, over all time against one month. */}
          <p className="font-mono text-2xl">{organizationRuns}</p>
          <p className="text-muted-foreground text-xs">{t("delegationsCountedInTheir")}</p>
        </CardContent>
      </Card>
      {canDecide && (
        <Card>
          <CardContent className="space-y-1 p-5">
            <p className="text-muted-foreground text-xs tracking-wide uppercase">
              {t("waitingPerson")}
            </p>
            <p className="font-mono text-2xl">{approvals.length}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
