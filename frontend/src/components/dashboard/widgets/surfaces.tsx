"use client";

import { useTranslations } from "next-intl";

import { BarList } from "../primitives/bar-list";
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
 */
export function SurfacesWidget({ title, hint, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.surfaces");

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll}>
      <UsageBody period={period} emptyKey="surfaces">
        {(usage) => (
          <BarList
            items={(usage.by_surface ?? []).map((row) => ({
              label: KNOWN_SURFACES.has(row.surface) ? t(`names.${row.surface}`) : row.surface,
              value: row.runs,
            }))}
          />
        )}
      </UsageBody>
    </WidgetFrame>
  );
}
