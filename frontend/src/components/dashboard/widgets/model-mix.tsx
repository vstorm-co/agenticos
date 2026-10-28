"use client";

import { useLocale, useTranslations } from "next-intl";

import { ProviderIcon } from "@/components/vault/provider-icon";
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
      <UsageBody period={period} emptyKey="model-mix" loadingVariant="bars" options={options}>
        {(usage) => {
          const rows = (usage.by_model ?? []).map((row) => ({
            // How often this model sent broken JSON that had to be repaired - a
            // signal for picking models, said only where it happened. In the
            // label, which the bars and the donut's legend both show, rather
            // than in the bars' narrow value column.
            label: row.tool_args_repaired
              ? t("modelRepaired", {
                  model: row.model_label ?? t("notRecorded"),
                  repaired: row.tool_args_repaired.toLocaleString(locale),
                })
              : (row.model_label ?? t("notRecorded")),
            value: row.runs,
            // The provider's mark beside the model, as Spend draws it, so
            // `claude-sonnet-4-5` and `google/gemini-2.5-flash` read at a glance.
            icon: row.provider ? (
              <ProviderIcon provider={row.provider} className="size-4" />
            ) : undefined,
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
