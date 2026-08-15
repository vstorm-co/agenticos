"use client";

import { useTranslations } from "next-intl";

import { BarList } from "../primitives/bar-list";
import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

/** Which models did the work, as recorded on each run (`model_label`). */
export function ModelMixWidget({ title, hint, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.model-mix");

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll}>
      <UsageBody period={period} emptyKey="model-mix">
        {(usage) => (
          <div className="flex h-full flex-col justify-between gap-2">
            <BarList
              items={(usage.by_model ?? []).map((row) => ({
                label: row.model_label ?? t("notRecorded"),
                value: row.runs,
              }))}
            />
            <p className="text-muted-foreground text-xs">{t("subline")}</p>
          </div>
        )}
      </UsageBody>
    </WidgetFrame>
  );
}
