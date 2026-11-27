"use client";

import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { useMoney } from "@/components/providers/currency-provider";
import type { ScorerResult } from "@/types/scoring";

/** Keep criterion identity canonical while reporting structured monetary values in the reader's unit. */
export function CostCriterionName({ result }: { result: ScorerResult }) {
  const money = useMoney();
  const locale = useLocale();
  const t = useTranslations("currencies");
  return result.cost_limit_usd != null
    ? t("criterionLimit", { amount: money.cost(result.cost_limit_usd, locale) })
    : result.name;
}

export function CostCriterionReason({
  result,
  fallback,
}: {
  result: ScorerResult;
  fallback: ReactNode;
}) {
  const money = useMoney();
  const locale = useLocale();
  const t = useTranslations("currencies");
  return result.cost_limit_usd != null && result.cost_observed_usd != null
    ? t("criterionObserved", {
        amount: money.cost(result.cost_observed_usd, locale),
        limit: money.cost(result.cost_limit_usd, locale),
      })
    : fallback;
}
