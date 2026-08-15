"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Figure } from "@/components/ui";

import { ROUTES } from "@/lib/constants";
import { formatPeriodParam, type Period } from "@/lib/dashboard/period";
import { formatMs } from "../format";
import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

/**
 * Run history sorted by duration over this widget's window - where the p95
 * figure points. The window travels as `?period=`, the same form the Activity
 * page round-trips its own control through, so the link lands with the picker
 * already set to the window the figure was computed over.
 */
function slowestRunsHref(period: Period): string {
  const params = new URLSearchParams({
    sort: "duration",
    period: formatPeriodParam(period),
  });
  return `${ROUTES.RUNS}?${params.toString()}`;
}

/** Started-to-finished percentiles. Null latency means nothing finished yet. */
export function LatencyWidget({ title, hint, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.latency");

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll}>
      <UsageBody period={period} emptyKey="latency">
        {(usage) => {
          const p95 = usage.latency_ms?.p95 ?? null;
          return (
            <div className="grid flex-1 grid-cols-2 content-center gap-4">
              <Figure label={t("p50")} value={formatMs(usage.latency_ms?.p50 ?? null)} />
              {/* The number *and its evidence*: p95 links to the runs behind it,
                  sorted by duration over the same window. A null p95 is "nothing
                  finished", so there is nothing to reach - it stays a plain
                  figure rather than a link to an empty list. */}
              <Figure
                label={t("p95")}
                value={
                  p95 === null ? (
                    formatMs(null)
                  ) : (
                    <Link
                      href={slowestRunsHref(period)}
                      aria-label={t("viewSlowest")}
                      className="hover:text-primary underline-offset-4 hover:underline"
                    >
                      {formatMs(p95)}
                    </Link>
                  )
                }
              />
            </div>
          );
        }}
      </UsageBody>
    </WidgetFrame>
  );
}
