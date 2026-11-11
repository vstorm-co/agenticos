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
      error={error ?? (parseBudget(value) === undefined ? t("budgetInvalid") : undefined)}
    >
      <Input
        id="trigger-budget"
        type="text"
        inputMode="decimal"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={t("budgetPlaceholder")}
      />
    </FormField>
  );
}

/** Whether `parsed` raises or removes the cap `stored`; no cap stored means any cap tightens. */
export function raisesBudget(parsed: number | null | undefined, stored: number | null): boolean {
  if (stored === null || parsed === undefined) return false;
  return parsed === null || parsed > stored;
}

/** Blank explicitly clears a cap; malformed or nonpositive input is refused. */
export function parseBudget(value: string): number | null | undefined {
  const text = value.trim();
  if (text === "") return null;
  const parsed = Number(text);
  return /^(?:\d+\.?\d*|\.\d+)$/.test(text) && Number.isFinite(parsed) && parsed > 0
    ? parsed
    : undefined;
}
