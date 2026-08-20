"use client";

import { useTranslations } from "next-intl";

import { DeltaChip, Figure } from "@/components/ui";

import { useSpend } from "@/hooks";
import { deltaPercent, formatUsd } from "../format";
import { BarList } from "../primitives/bar-list";
import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

/**
 * Two truths about money, deliberately both. The headline, the split and the
 * providers are the period's, from the composed stats response, and move with
 * the filter. The fine-print line is the calendar month-to-date from GET
 * /spend - it reconciles against an invoice and must not move with a dashboard
 * filter. The delta's tone is inverted: rising spend is the red direction.
 *
 * The headline is the **whole** bill: model requests plus what the worker spent
 * indexing documents. It was model spend alone while the month-to-date line
 * under it was both, so a deployment doing any ingestion had two different
 * definitions of cost on one card and nothing saying which was which. The split
 * is here rather than on a card of its own because a reader asking where the
 * money went is already looking at this one; two money cards is one answer in
 * two places.
 */
export function SpendWidget({ title, hint, period, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.spend");
  const { spend } = useSpend();

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      <UsageBody period={period} emptyKey="spend" options={options}>
        {(usage) => {
          const cost = usage.cost;
          const current = Number(cost?.period_usd ?? 0);
          const previous = Number(cost?.previous_period_usd ?? 0);
          const delta = deltaPercent(current, previous);
          // The bill's parts, shown only where they spent: models always, then
          // indexing and search when a knowledge base was used. A deployment
          // with none reads no split at all, and the parts join rather than
          // sitting in the provider bars below, which break down the model half.
          const splitParts = [t("splitModels", { amount: formatUsd(cost?.model_usd) })];
          if (Number(cost?.ingestion_usd ?? 0) > 0) {
            splitParts.push(t("splitIndexing", { amount: formatUsd(cost?.ingestion_usd) }));
          }
          if (Number(cost?.retrieval_usd ?? 0) > 0) {
            splitParts.push(t("splitSearch", { amount: formatUsd(cost?.retrieval_usd) }));
          }
          return (
            <div className="flex h-full flex-col justify-between gap-3">
              <Figure
                value={formatUsd(cost?.period_usd)}
                unit={t("unit")}
                delta={
                  delta !== null ? (
                    <DeltaChip delta={delta} label={t("delta")} rising="bad" />
                  ) : undefined
                }
                // The parts of the bill, shown only once something beyond model
                // spend was billed: a deployment with no knowledge base should
                // not read a line about a subsystem it does not use.
                caption={splitParts.length > 1 ? splitParts.join(" · ") : undefined}
              />
              <BarList
                items={(cost?.by_provider ?? []).map((row) => ({
                  label: row.provider ?? t("notRecorded"),
                  value: Number(row.cost_usd),
                  display: formatUsd(row.cost_usd),
                }))}
              />
              {spend ? (
                <p className="text-muted-foreground border-foreground/8 border-t pt-3 text-xs">
                  {t("monthToDate", { amount: formatUsd(spend.month_to_date_usd) })}
                </p>
              ) : null}
            </div>
          );
        }}
      </UsageBody>
    </WidgetFrame>
  );
}
