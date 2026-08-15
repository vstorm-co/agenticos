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
        // One grid holds the labels, the cells and the axis, so a day name sits
        // on the row it names and an hour tick under the column it names -
        // rather than three boxes lined up by a `pl-8` that was right at one
        // card width. `min-h-40` is the floor a week of rectangles needs to
        // still be readable; above it the cells take whatever the card has.
        <div
          className="grid min-h-40 flex-1 gap-x-2.5 gap-y-1.5"
          style={{
            // i18n-exempt: CSS grid templates, not words on screen
            gridTemplateColumns: "auto minmax(0, 1fr)",
            gridTemplateRows: "minmax(0, 1fr) auto",
          }}
        >
          {/* The day names. `weekday` is Postgres' `dow`, so index 0 is Sunday
              and the catalog is keyed the same way - the mapping stays in one
              place rather than being undone here and redone in a translation. */}
          <div
            className="text-muted-foreground grid text-[10px] leading-none"
            // i18n-exempt: a CSS grid template, not words on screen
            style={{ gridTemplateRows: "repeat(7, minmax(0, 1fr))" }}
          >
            {Array.from({ length: 7 }, (_, day) => (
              <span key={day} className="flex items-center">
                {t(`weekdays.${day}`)}
              </span>
            ))}
          </div>
          <Heatmap
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
          <div aria-hidden />
          <div
            className="text-muted-foreground grid text-[10px] leading-none tabular-nums"
            // i18n-exempt: a CSS grid template, not words on screen
            style={{ gridTemplateColumns: "repeat(24, minmax(0, 1fr))" }}
          >
            {HOUR_TICKS.map((hour) => (
              // Each label starts on the column its hour is, spanning to the
              // next tick - so "12" sits over midday rather than at whatever
              // fraction of the width `justify-between` left it.
              <span key={hour} style={{ gridColumn: `${hour + 1} / span 3` }}>
                {t("hourTick", { hour })}
              </span>
            ))}
          </div>
        </div>
      )}
    </WidgetFrame>
  );
}
