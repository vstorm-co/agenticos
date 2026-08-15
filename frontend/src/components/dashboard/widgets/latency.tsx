"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

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
  const locale = useLocale();

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll}>
      <UsageBody period={period} emptyKey="latency">
        {(usage) => {
          const p50 = usage.latency_ms?.p50 ?? null;
          const p95 = usage.latency_ms?.p95 ?? null;
          return (
            <div className="flex flex-1 flex-col gap-5">
              <div className="grid grid-cols-2 gap-4">
                <Figure label={t("p50")} value={formatMs(p50)} />
                {/* The number *and its evidence*: p95 links to the runs behind
                    it, sorted by duration over the same window. A null p95 is
                    "nothing finished", so there is nothing to reach - it stays a
                    plain figure rather than a link to an empty list. */}
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
              {/* The two numbers against each other, which is the question a
                  pair of percentiles is asking: a tail three times the median
                  is a different deployment from one a hair above it, and two
                  figures side by side leave that arithmetic to the reader.
                  A sentence rather than a second chart - the card is two rows
                  tall in most arrangements, and a chart that does not fit is
                  worse than the ratio written out. */}
              {p50 !== null && p95 !== null && p50 > 0 ? (
                <p className="text-muted-foreground border-foreground/8 mt-auto border-t pt-3 text-xs">
                  {t("tail", {
                    ratio: (p95 / p50).toLocaleString(locale, { maximumFractionDigits: 1 }),
                  })}
                </p>
              ) : null}
            </div>
          );
        }}
      </UsageBody>
    </WidgetFrame>
  );
}
