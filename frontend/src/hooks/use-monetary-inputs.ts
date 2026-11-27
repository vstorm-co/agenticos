"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useTenantId } from "@/hooks/use-organizations";
import { useChanged } from "@/hooks/use-changed";
import { useMoney } from "@/components/providers/currency-provider";
import { ApiError } from "@/lib/api-error";
import type { CurrencyAmount, MonetaryWrite } from "@/lib/money";

export interface MonetaryInputs {
  readonly revision: number;
  reset(): void;
  has(field: string): boolean;
  change(field: string, write: MonetaryWrite | null, valid: boolean): void;
  payload<T extends object>(
    value: T,
    activeFields?: readonly string[],
  ): T & { monetary_inputs: Record<string, CurrencyAmount> };
}

/** Explicit declarations belong to this form, never to a global currency store. */
export function useMonetaryInputs(identity: string = ""): MonetaryInputs {
  const money = useMoney();
  const tenant = useTenantId();
  const t = useTranslations("currencies");
  const [draft, setDraft] = useState<{
    revision: number;
    fields: Record<string, { input: CurrencyAmount | null; valid: boolean }>;
  }>({ revision: 0, fields: {} });
  const reset = () => setDraft((current) => ({ revision: current.revision + 1, fields: {} }));
  if (useChanged(`${tenant}|${identity}|${money.currency}|${money.quote}`)) reset();
  const fields = draft.fields;
  return {
    revision: draft.revision,
    reset,
    has: (field) =>
      fields[field] !== undefined && (fields[field].input !== null || !fields[field].valid),
    change(field, write, valid) {
      setDraft((previous) => ({
        ...previous,
        fields: { ...previous.fields, [field]: { input: write?.input ?? null, valid } },
      }));
    },
    payload(value, activeFields) {
      const selected = Object.entries(fields).filter(
        ([field]) => !activeFields || activeFields.includes(field),
      );
      const invalid = selected.filter(([, entry]) => !entry.valid);
      if (invalid.length) {
        const message = t("amountInvalid");
        throw new ApiError(422, message, {
          error: {
            code: "VALIDATION_ERROR",
            message,
            details: {
              fields: invalid.map(([field]) => ({ field, message })),
            },
          },
        });
      }
      const inputs: Record<string, CurrencyAmount> = {};
      for (const [field, entry] of selected) {
        if (entry.input !== null) inputs[field] = entry.input;
      }
      return { ...value, monetary_inputs: inputs };
    },
  };
}
