"use client";

import { useTranslations } from "next-intl";
import { canonicalUsd, compareUsd } from "@/lib/money";

import { MonetaryInput } from "@/components/money/monetary-input";
import { useMoney } from "@/components/providers/currency-provider";
import type { MonetaryInputs } from "@/hooks/use-monetary-inputs";
import { FormField } from "@/components/ui";

/**
 * A routine's own monthly limit (#2575): what its runs may cost in a calendar month.
 *
 * Blank is no limit of its own. The agent's and the organization's limits apply either
 * way - this only ever narrows them - and a spent routine starts again on the first.
 */
export function BudgetField({
  value,
  onChange,
  error,
  monetary,
}: {
  monetary: MonetaryInputs;
  value: string;
  onChange: (value: string) => void;
  error?: string;
}) {
  const money = useMoney();
  const t = useTranslations("triggers");
  return (
    <FormField
      label={t("budgetLabel", { currency: money.currency ?? "—" })}
      htmlFor="trigger-budget"
      description={t("budgetHint")}
      error={error ?? (parseBudget(value) === undefined ? t("budgetInvalid") : undefined)}
    >
      <MonetaryInput
        id="trigger-budget"
        monetary={monetary}
        field="monthly_budget_usd"
        value={value}
        onValueChange={onChange}
        onInvalidValueChange={onChange}
        positive
        placeholder={t("budgetPlaceholder")}
      />
    </FormField>
  );
}

/** Whether `parsed` raises or removes the cap `stored`; no cap stored means any cap tightens. */
export function raisesBudget(parsed: string | null | undefined, stored: string | null): boolean {
  if (stored === null || parsed === undefined) return false;
  return parsed === null || compareUsd(parsed, stored) === 1;
}

/** Blank explicitly clears a cap; malformed or nonpositive input is refused. */
export function parseBudget(value: string): string | null | undefined {
  const text = value.trim();
  if (text === "") return null;
  return /^(?:\d+\.?\d*|\.\d+)$/.test(text) && compareUsd(text, "0") === 1
    ? canonicalUsd(text)
    : undefined;
}
