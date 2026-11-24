"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";

import { formulaRefusal } from "@/lib/api-error";

/**
 * Says why the service refused a formula, in the reader's language: the refusal's
 * stable reason picks the message, and an unknown one falls back to the service's
 * own sentence. Null when `error` is not a refused formula.
 */
export function useFormulaProblem(): (error: unknown) => { field: string; text: string } | null {
  const t = useTranslations("tables.formula");
  return useCallback(
    (error: unknown) => {
      const refusal = formulaRefusal(error);
      if (refusal === null || !t.has(`problem.${refusal.reason}`)) return null;
      return { field: refusal.field, text: t(`problem.${refusal.reason}`, refusal.params) };
    },
    [t],
  );
}
