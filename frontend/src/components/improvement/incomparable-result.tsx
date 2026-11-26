"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { InvalidReason } from "@/components/evals/invalid-reason";
import type { EvalComparison } from "@/types/eval-runs";

export function IncomparableResult({
  agentId,
  runId,
  comparison,
}: {
  agentId: string;
  runId: string;
  comparison: Pick<
    EvalComparison,
    "invalid_reason" | "invalid_reason_code" | "invalid_reason_params"
  >;
}) {
  const t = useTranslations("improvement");
  return (
    <div className="space-y-2 rounded-lg border p-3 text-sm">
      <p role="alert" className="font-medium">
        {t("comparisonInvalid")}
      </p>
      <InvalidReason comparison={comparison} className="text-muted-foreground" />
      <Link className="underline underline-offset-4" href={`/agents/${agentId}/evals/${runId}`}>
        {t("openCheck")}
      </Link>
    </div>
  );
}
