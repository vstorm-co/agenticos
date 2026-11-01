"use client";

import { useTranslations } from "next-intl";

import { FormField, Input } from "@/components/ui";

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
}: {
  value: string;
  onChange: (value: string) => void;
  error?: string;
}) {
  const t = useTranslations("triggers");
  return (
    <FormField
      label={t("budgetLabel")}
      htmlFor="trigger-budget"
      description={t("budgetHint")}
      error={error}
    >
      <Input
        id="trigger-budget"
        type="number"
        inputMode="decimal"
        min="0"
        step="0.01"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={t("budgetPlaceholder")}
      />
    </FormField>
  );
}

/** The limit as the API takes it: a positive number, or null for none. */
export function parseBudget(value: string): number | null {
  const parsed = Number(value);
  return value.trim() !== "" && Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}
