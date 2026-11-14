"use client";

import { useTranslations } from "next-intl";
import { ErrorState } from "@/components/states";
import { getErrorMessage } from "@/lib/api-error";

/** A screen whose read failed says why and offers to read it again, never an empty step. */
export function StepError({ error, retry }: { error: unknown; retry: () => unknown }) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  return (
    <ErrorState
      description={getErrorMessage(error, tErrors)}
      cta={{ label: t("retryRead"), onClick: () => void retry() }}
    />
  );
}
