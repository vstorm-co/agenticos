"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import type { EvalRunStatus } from "@/types/eval-runs";

const VARIANT: Record<EvalRunStatus, "secondary" | "success" | "warning" | "destructive"> = {
  queued: "secondary",
  running: "secondary",
  completed: "success",
  cancelled: "warning",
  failed: "destructive",
  budget_exceeded: "destructive",
};

/** Where an eval run is, in the tone a status list uses elsewhere. */
export function EvalStatusBadge({ status }: { status: EvalRunStatus }) {
  const t = useTranslations("evals.status");
  return <Badge variant={VARIANT[status]}>{t(status)}</Badge>;
}
