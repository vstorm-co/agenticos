"use client";

import { useLocale, useTranslations } from "next-intl";

import { usePeopleUsage, useUsageStats } from "@/hooks";
import { timeAgo } from "@/lib/utils";
import { formatUsd } from "../format";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** What fits a card. The rest are counted, not listed. */
const ROWS = 6;

/**
 * The names under the adoption count - who actually used this, and what it
 * cost them. The one card on the page that answers with people rather than
 * totals, which is why it carries its own disclosure: the gate is `runs:view`,
 * held by builder and operator as well as the stewards, and somebody listed
 * here deserves to know how far the list reaches.
 *
 * Ordered by runs. Sorted by cost the same rows would read as a league table,
 * and the question is adoption.
 */
export function TopPeopleWidget({ title, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.top-people");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const { byUser, isLoading, error, refetch } = usePeopleUsage(
    { from: period.from, to: period.to },
    { limit: ROWS },
  );
  // The composed answer for this window is already in the cache - reading the
  // headcount from it costs no request and keeps this card and the count above
  // it from ever disagreeing.
  const { usage } = useUsageStats({ from: period.from, to: period.to });
  const others = Math.max((usage?.active_users?.active ?? 0) - byUser.length, 0);

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : byUser.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <div className="flex h-full flex-col gap-3">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-muted-foreground border-border border-b text-xs">
                  <th className="py-1.5 text-left font-medium">{t("columns.person")}</th>
                  <th className="py-1.5 text-right font-medium">{t("columns.runs")}</th>
                  <th className="py-1.5 text-right font-medium">{t("columns.cost")}</th>
                  <th className="py-1.5 text-right font-medium">{t("columns.lastRun")}</th>
                </tr>
              </thead>
              <tbody>
                {byUser.map((person) => (
                  <tr key={person.user_id} className="border-border/60 border-b last:border-0">
                    <td className="text-foreground max-w-0 truncate py-1.5 pr-2">
                      {person.full_name ?? person.email}
                    </td>
                    <td className="text-foreground py-1.5 text-right tabular-nums">
                      {person.runs}
                    </td>
                    <td className="text-foreground py-1.5 text-right tabular-nums">
                      {formatUsd(Number(person.cost_usd))}
                    </td>
                    <td className="text-muted-foreground py-1.5 text-right">
                      {timeAgo(person.last_run_at, tTime, locale)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="text-muted-foreground space-y-1 text-xs">
            {others > 0 ? <p>{t("others", { count: others })}</p> : null}
            <p>{t("disclosure")}</p>
          </div>
        </div>
      )}
    </WidgetFrame>
  );
}
