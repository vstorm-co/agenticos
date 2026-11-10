"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import type { EvalRunStatus } from "@/types/eval-runs";

/** Execution status stays neutral; the evaluation verdict carries the outcome. */
export function EvalStatusBadge({ status }: { status: EvalRunStatus }) {
  const t = useTranslations("evals.status");
  return <Badge variant="secondary">{t(status)}</Badge>;
}
