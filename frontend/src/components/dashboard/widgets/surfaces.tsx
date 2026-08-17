"use client";

import { useLocale, useTranslations } from "next-intl";

import { SurfaceIcon } from "@/components/runs/surface-icon";
import { resolveStyle } from "@/lib/dashboard/registry";
import { runsHref } from "@/lib/runs/filter-params";
import { Breakdown } from "../primitives/breakdown";
import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

const KNOWN_SURFACES = new Set([
  "playground",
  "web",
  "embed",
  "api",
  "slack",
  "telegram",
  "mattermost",
  "schedule",
]);

/**
 * Where runs come from, as recorded on each run. Old periods fold widget
 * runs into `web` and early Mattermost runs into `api` - the recording
 * widened without a backfill, and the chart shows what was recorded.
 *
 * Each row wears the surface's own mark, from the module the run table and the
 * surface filter draw from - one face per surface across the product, never a
 * second mapping (#144's rule).
 */
export function SurfacesWidget({ title, hint, period, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.surfaces");
  const locale = useLocale();
  const style = resolveStyle("surfaces", options?.style);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      <UsageBody period={period} emptyKey="surfaces" options={options}>
        {(usage) => {
          const rows = (usage.by_surface ?? []).map((row) => ({
            label: KNOWN_SURFACES.has(row.surface) ? t(`names.${row.surface}`) : row.surface,
            value: row.runs,
            icon: <SurfaceIcon surface={row.surface} />,
            // The runs behind this bar, over the window this bar counted -
            // the hand-off the p95 figure has had all along, now that
            // Activity's facets travel in the URL (#768).
            href: runsHref({ period, filters: { surface: row.surface } }),
          }));
          const total = rows.reduce((sum, row) => sum + row.value, 0);
          return (
            <Breakdown
              rows={rows}
              style={style === "donut" ? "donut" : "bars"}
              centerLabel={total.toLocaleString(locale)}
              centerSub={t("unit")}
            />
          );
        }}
      </UsageBody>
    </WidgetFrame>
  );
}
