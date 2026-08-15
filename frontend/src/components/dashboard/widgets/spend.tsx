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
export function SpendWidget({ title, hint, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.spend");
  const { spend } = useSpend();

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll}>
      <UsageBody period={period} emptyKey="spend">
        {(usage) => {
          const cost = usage.cost;
          const current = Number(cost?.period_usd ?? 0);
          const previous = Number(cost?.previous_period_usd ?? 0);
          const delta = deltaPercent(current, previous);
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
                // The two halves of the bill, and only when indexing spent
                // anything: a deployment with no knowledge base should not
                // read a line about a subsystem it does not use. The bars
                // below break down the model half, so the split rides the
                // headline rather than joining them - two denominators in one
                // list read as one.
                caption={
                  Number(cost?.ingestion_usd ?? 0) > 0
                    ? t("split", {
                        models: formatUsd(cost?.model_usd),
                        ingestion: formatUsd(cost?.ingestion_usd),
                      })
                    : undefined
                }
              />
              <BarList
                items={(cost?.by_provider ?? []).map((row) => ({
                  label: row.provider ?? t("notRecorded"),
                  value: Number(row.cost_usd),
                  display: formatUsd(row.cost_usd),
                }))}
              />
              {spend ? (
                <p className="text-muted-foreground border-border border-t border-dashed pt-2 text-xs">
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
