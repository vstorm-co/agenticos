"use client";

import { useLocale, useTranslations } from "next-intl";

import { StackedBars, type StackedSeries } from "@/components/dashboard/primitives/stacked-bars";
import { formatMs, formatShare } from "@/components/dashboard/format";
import { Figure } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { BackgroundJobsActivity, KindActivity } from "@/types/background-jobs";

/** Seconds as the queue's own scale: milliseconds and seconds, then minutes, then hours. */
export function formatSeconds(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return formatMs(seconds * 1000);
  if (seconds < 3600)
    return `${(seconds / 60).toLocaleString(undefined, { maximumFractionDigits: 1 })} min`;
  return `${(seconds / 3600).toLocaleString(undefined, { maximumFractionDigits: 1 })} h`;
}

function totals(activity: BackgroundJobsActivity) {
  let finished = 0;
  let dead = 0;
  for (const bucket of activity.buckets) {
    finished += bucket.succeeded + bucket.dead + bucket.cancelled;
    dead += bucket.dead;
  }
  return { finished, dead };
}

/** The kind whose due jobs waited longest for a worker, the figure that says a pool is short. */
function slowestPickup(kinds: KindActivity[]): KindActivity | null {
  let slowest: KindActivity | null = null;
  for (const kind of kinds) {
    if (kind.wait_p95_seconds === null) continue;
    if (slowest === null || kind.wait_p95_seconds > (slowest.wait_p95_seconds ?? 0)) slowest = kind;
  }
  return slowest;
}

/** Four numbers over the window: what finished, what died, the wait now, the slowest pickup. */
export function ActivityFigures({
  activity,
  compact = false,
}: {
  activity: BackgroundJobsActivity;
  /** Two figures rather than four, stacked beside the chart on a wide dashboard card. */
  compact?: boolean;
}) {
  const t = useTranslations("pages.backgroundJobs");
  const locale = useLocale();
  const { finished, dead } = totals(activity);
  const slowest = slowestPickup(activity.kinds);
  return (
    <div className={cn("grid grid-cols-2 gap-5", compact ? "lg:grid-cols-1" : "lg:grid-cols-4")}>
      <Figure
        label={t("finishedFigure")}
        value={finished.toLocaleString(locale)}
        caption={t("perSlice", {
          window: activity.window,
          count: Math.round(finished / activity.buckets.length).toLocaleString(locale),
        })}
      />
      <Figure
        label={t("deadFigure")}
        value={dead.toLocaleString(locale)}
        caption={
          dead === 0
            ? t("noneDead")
            : t("deadShare", { share: formatShare(dead / finished, locale) })
        }
        captionTone={dead === 0 ? "muted" : "destructive"}
      />
      {!compact && (
        <>
          <Figure
            label={t("waitFigure")}
            value={formatSeconds(activity.oldest_wait_seconds)}
            caption={activity.oldest_wait_seconds === null ? t("waitNone") : t("waitCaption")}
          />
          <Figure
            label={t("slowestFigure")}
            value={formatSeconds(slowest?.wait_p95_seconds ?? null)}
            caption={slowest?.kind}
          />
        </>
      )}
    </div>
  );
}

/** Each slice's finished jobs, stacked by how they ended. */
export function ActivityChart({
  activity,
  className,
}: {
  activity: BackgroundJobsActivity;
  className?: string;
}) {
  const t = useTranslations("pages.backgroundJobs");
  const locale = useLocale();
  // An hour reads as its time of day; a six-hour slice of a week needs its day too.
  const label = new Intl.DateTimeFormat(
    locale,
    activity.window === "day" ? { hour: "numeric" } : { weekday: "short", hour: "numeric" },
  );
  const series: StackedSeries[] = [
    { key: "succeeded", label: t("status.succeeded"), color: "var(--color-chart-fill)" },
    { key: "dead", label: t("status.dead"), color: "var(--color-destructive)" },
    {
      key: "cancelled",
      label: t("status.cancelled"),
      color: "oklch(from var(--color-muted-foreground) l c h / 0.45)",
    },
  ];
  const data = activity.buckets.map((bucket) => ({
    label: label.format(new Date(bucket.start)),
    succeeded: bucket.succeeded,
    dead: bucket.dead,
    cancelled: bucket.cancelled,
  }));
  return <StackedBars data={data} series={series} className={className} />;
}

/** One row per kind that finished something: how much, how much died, how long it ran and waited. */
export function KindActivityTable({ kinds }: { kinds: KindActivity[] }) {
  const t = useTranslations("pages.backgroundJobs");
  const locale = useLocale();
  if (kinds.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("noActivity")}</p>;
  }
  const busiest = Math.max(...kinds.map((kind) => kind.finished));
  return (
    <div className="-mx-1 overflow-x-auto">
      <table className="w-full min-w-[40rem] text-sm">
        <thead>
          <tr className="text-muted-foreground text-left text-xs">
            <th className="px-1 pb-2 font-medium">{t("kind")}</th>
            <th className="px-1 pb-2 font-medium">{t("columns.finished")}</th>
            <th className="px-1 pb-2 text-right font-medium">{t("columns.dead")}</th>
            <th className="px-1 pb-2 text-right font-medium">{t("columns.run")}</th>
            <th className="px-1 pb-2 text-right font-medium">{t("columns.wait")}</th>
          </tr>
        </thead>
        <tbody className="divide-border divide-y">
          {kinds.map((kind) => (
            <tr key={kind.kind}>
              <td className="px-1 py-2.5">
                <p className="truncate font-mono text-xs font-medium">{kind.kind}</p>
                <p className="text-muted-foreground text-xs">{t(`pools.${kind.pool}`)}</p>
              </td>
              <td className="w-1/3 px-1 py-2.5">
                <div className="flex items-center gap-2">
                  <div className="bg-track h-1.5 flex-1 overflow-hidden rounded-full">
                    <div
                      className="bg-chart-fill h-full rounded-full"
                      style={{ width: `${(kind.finished / busiest) * 100}%` }}
                    />
                  </div>
                  <span className="w-12 text-right tabular-nums">
                    {kind.finished.toLocaleString(locale)}
                  </span>
                </div>
              </td>
              <td
                className={cn(
                  "px-1 py-2.5 text-right tabular-nums",
                  kind.dead > 0 ? "text-destructive font-medium" : "text-muted-foreground",
                )}
              >
                {kind.dead.toLocaleString(locale)}
              </td>
              <td className="px-1 py-2.5 text-right tabular-nums">
                {formatSeconds(kind.run_p50_seconds)}
                <span className="text-muted-foreground">
                  {" "}
                  / {formatSeconds(kind.run_p95_seconds)}
                </span>
              </td>
              <td className="px-1 py-2.5 text-right tabular-nums">
                {formatSeconds(kind.wait_p95_seconds)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
