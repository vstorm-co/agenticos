"use client";

import { useTranslations } from "next-intl";

import type { CaseGenerationEstimate } from "@/types/case-generation";

/**
 * What a generation will ask for and roughly cost, shown before anything is spent.
 *
 * Called an estimate because it is one: the budget is enforced when the
 * generator runs, not by this figure.
 */
export function GenerationEstimate({ estimate }: { estimate: CaseGenerationEstimate }) {
  const t = useTranslations("datasets");
  return (
    <div className="bg-muted/50 space-y-2 rounded-md border p-3 text-sm" role="status">
      <p className="font-medium">
        {estimate.estimated_cost_usd === null
          ? t("estimateUnpriced", { count: estimate.count })
          : t("estimate", { count: estimate.count, cost: Number(estimate.estimated_cost_usd) })}
      </p>
      <ul className="text-muted-foreground space-y-0.5 text-xs">
        {estimate.sources.map((plan) => (
          <li key={plan.source}>
            {t(`plan.${plan.source}`, { count: plan.cases, material: plan.material })}
          </li>
        ))}
      </ul>
      {estimate.excluded_collections > 0 && (
        <p className="text-xs text-amber-600 dark:text-amber-500">
          {t("excludedCollections", { count: estimate.excluded_collections })}
        </p>
      )}
    </div>
  );
}
