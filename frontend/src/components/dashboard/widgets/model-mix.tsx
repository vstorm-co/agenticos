"use client";

import { useLocale, useTranslations } from "next-intl";

import { resolveStyle } from "@/lib/dashboard/registry";
import { runsHref } from "@/lib/runs/filter-params";
import { Breakdown } from "../primitives/breakdown";
import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

/** Which models did the work, as recorded on each run (`model_label`). */
export function ModelMixWidget({ title, hint, period, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.model-mix");
  const locale = useLocale();
  const style = resolveStyle("model-mix", options?.style);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      <UsageBody period={period} emptyKey="model-mix" options={options}>
        {(usage) => {
          const rows = (usage.by_model ?? []).map((row) => ({
            label: row.model_label ?? t("notRecorded"),
            value: row.runs,
            // A run that recorded no label cannot be asked for by one: the
            // filter matches the column, and "not recorded" is its absence.
            href: row.model_label
              ? runsHref({ period, filters: { model: row.model_label } })
              : undefined,
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
