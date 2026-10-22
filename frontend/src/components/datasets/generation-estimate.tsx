"use client";

import { useTranslations } from "next-intl";

import type { CaseGenerationEstimate } from "@/types/case-generation";

// Dollars are shown to the cent, so a cheaper paid generation would read as free.
const CENT = 0.01;

/**
 * What a generation will ask for and roughly cost, shown before anything is spent.
 *
 * Called an estimate because it is one: the budget is enforced when the
 * generator runs, not by this figure.
 */
export function GenerationEstimate({ estimate }: { estimate: CaseGenerationEstimate }) {
  const t = useTranslations("datasets");
  const cost = estimate.estimated_cost_usd === null ? null : Number(estimate.estimated_cost_usd);
  return (
    <div className="bg-muted/50 space-y-2 rounded-md border p-3 text-sm" role="status">
      <p className="font-medium">
        {cost === null
          ? t("estimateUnpriced", { count: estimate.count })
          : cost > 0 && cost < CENT
            ? t("estimateUnderCent", { count: estimate.count })
            : t("estimate", { count: estimate.count, cost })}
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
