"use client";

import { useTranslations } from "next-intl";

import { completedShare, formatCompletedShare, statusTally } from "@/lib/run-outcomes";
import { seriesColor } from "@/lib/dashboard/system";
import { DonutChart } from "../primitives/donut-chart";
import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

/**
 * What the window's runs came to: a ring of the statuses that happened, and a
 * legend of every status that could have.
 *
 * The ring was two arcs for a while - "completed" against "did not" - because
 * five *status* tones washed to the same lightness measure ΔE 0.8 under
 * deuteranopia, which is to say one colour to about one man in twelve. That
 * measurement was about those five tones, not about five colours: the
 * categorical ramp spreads lightness as well as hue and measures 8.3 on its
 * worst pair under deuteranopia and protanopia (`globals.css`). So a status
 * gets its own arc again, and a card that reported one split now reports the
 * shape of a window.
 *
 * A status with no runs is a legend row at zero, dimmed, and no arc - an arc of
 * nothing is a colour in the key with no ink to match it.
 *
 * The awaiting count is still the same number the approvals card lists: both
 * read the same rows.
 */
export function OutcomesWidget({ title, hint, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.outcomes");

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll}>
      <UsageBody period={period} emptyKey="outcomes">
        {(usage) => {
          const byStatus = usage.by_status ?? [];
          const counts = new Map(byStatus.map((row) => [row.status, row.runs]));
          const of = (status: string) => counts.get(status as never) ?? 0;
          // The same tally, and the same shared formula, the Activity version
          // strip reads - so the two never disagree on what "completed" means
          // over one set of rows (docs/design/activity-plan.md §8a.4).
          const tally = statusTally(byStatus);
          const total = tally.total;
          const failed = of("failed");
          const budget = of("budget_exceeded");
          const awaiting = of("awaiting_approval");
          const other = of("running") + of("cancelled");
          const attention = failed + budget;
          // The order is the ramp's, and it is fixed by status rather than by
          // which statuses this window happens to hold: "failed" is the same
          // colour on a card where nothing failed and on one where everything
          // did, so two periods can be compared without re-reading the key.
          const rows = [
            { name: t("status.completed"), value: tally.completed, color: seriesColor(1) },
            { name: t("status.failed"), value: failed, color: seriesColor(3) },
            { name: t("status.awaiting_approval"), value: awaiting, color: seriesColor(2) },
            { name: t("status.budget_exceeded"), value: budget, color: seriesColor(4) },
            { name: t("status.other"), value: other, color: seriesColor(0) },
          ];
          const legend = rows.map((row) => ({
            ...row,
            share: total > 0 ? row.value / total : 0,
          }));
          return (
            <div className="flex h-full flex-col justify-between gap-3">
              <DonutChart
                segments={rows.filter((row) => row.value > 0)}
                legend={legend}
                centerLabel={formatCompletedShare(completedShare(tally))}
                centerSub={t("completed")}
              />
              {attention > 0 ? (
                <p className="text-muted-foreground border-foreground/8 border-t pt-3 text-center text-xs">
                  {t("attention", { n: Math.max(1, Math.round(total / attention)) })}
                </p>
              ) : null}
            </div>
          );
        }}
      </UsageBody>
    </WidgetFrame>
  );
}
