"use client";

import { useTranslations } from "next-intl";

import { useUsageByHour } from "@/hooks";
import { Heatmap } from "../primitives/heatmap";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** Every third hour, so the axis reads without the labels colliding. */
const HOUR_TICKS = [0, 3, 6, 9, 12, 15, 18, 21];

/**
 * When the organization actually works - a week by an hour, shaded by runs.
 *
 * The trend card answers how much and the outcomes card answers how well; this
 * answers *when*, which is the question behind "why did that batch time out at
 * nine on a Monday" and behind whether a maintenance window is a quiet one.
 *
 * Its own request, because a hundred and sixty-eight cells do not belong in
 * every dashboard load and only this card asks.
 *
 * The grid is UTC, like every other bucket the stats endpoint answers. An
 * organization spread across timezones reads its own rhythm shifted, which is
 * the honest answer until a run records the zone it arrived from - the card's
 * axis says UTC rather than leaving a reader to assume it is theirs.
 */
export function ActivityRhythmWidget({ title, hint, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.activity-rhythm");
  const { byHour, isLoading, error, refetch } = useUsageByHour({
    from: period.from,
    to: period.to,
  });

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : byHour.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col justify-center gap-2">
          <div className="flex gap-2">
            {/* The day names, on the rows they label. `weekday` is Postgres'
                `dow`, so index 0 is Sunday and the catalog is keyed the same
                way - the mapping stays in one place rather than being undone
                here and redone in a translation. */}
            <div className="text-muted-foreground grid shrink-0 gap-0.5 text-[10px]">
              {Array.from({ length: 7 }, (_, day) => (
                <span key={day} className="flex aspect-square items-center">
                  {t(`weekdays.${day}`)}
                </span>
              ))}
            </div>
            <Heatmap
              className="min-w-0 flex-1"
              rows={7}
              columns={24}
              cells={byHour.map((cell) => ({
                row: cell.weekday,
                column: cell.hour,
                value: cell.runs,
                caption: t("cell", {
                  day: t(`weekdays.${cell.weekday}`),
                  hour: cell.hour,
                  count: cell.runs,
                }),
              }))}
            />
          </div>
          <div className="text-muted-foreground flex justify-between pl-8 text-[10px] tabular-nums">
            {HOUR_TICKS.map((hour) => (
              <span key={hour}>{t("hourTick", { hour })}</span>
            ))}
          </div>
        </div>
      )}
    </WidgetFrame>
  );
}
