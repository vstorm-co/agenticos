"use client";

import { useTranslations } from "next-intl";

import { formatMs } from "../format";
import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

/** Started-to-finished percentiles. Null latency means nothing finished yet. */
export function LatencyWidget({ title, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.latency");

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      <UsageBody period={period} emptyKey="latency">
        {(usage) => (
          <div className="flex h-full flex-col justify-between gap-2">
            <div className="grid flex-1 grid-cols-2 content-center gap-4">
              <div>
                <p className="text-muted-foreground text-xs">{t("p50")}</p>
                <p className="text-foreground text-2xl font-semibold tabular-nums">
                  {formatMs(usage.latency_ms?.p50 ?? null)}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground text-xs">{t("p95")}</p>
                <p className="text-foreground text-2xl font-semibold tabular-nums">
                  {formatMs(usage.latency_ms?.p95 ?? null)}
                </p>
              </div>
            </div>
            <p className="text-muted-foreground text-xs">{t("subline")}</p>
          </div>
        )}
      </UsageBody>
    </WidgetFrame>
  );
}
