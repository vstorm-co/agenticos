"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEvalComparison } from "@/hooks/use-eval-runs";
import { ChangedAnswers } from "./changed-answers";
import { StepError } from "./step-error";

/** Concrete answer changes; an unavailable or invalid comparison is never a success. */
export function ResultEvidence({ agentId, runId }: { agentId: string; runId: string }) {
  const t = useTranslations("improvement");
  const { comparison, error, refetch } = useEvalComparison(runId);
  if (error) return <StepError error={error} retry={refetch} />;
  if (!comparison) return <p role="status">{t("loading")}</p>;
  const flips = comparison.cases
    .filter((item) => item.flip === "regression" || item.flip === "fixed")
    .sort((a, b) => Number(b.flip === "regression") - Number(a.flip === "regression"));
  return comparison.verdict !== "invalid" && comparison.baseline && flips.length > 0 ? (
    <ChangedAnswers
      runId={runId}
      agentId={agentId}
      flips={flips}
      baselineRunId={comparison.baseline.run_id}
      baselineId={comparison.baseline.arm_id}
      candidateId={comparison.candidate.arm_id}
      attributions={{}}
      preview
    />
  ) : (
    <div className="space-y-3">
      <p className="text-muted-foreground text-sm">
        {t(comparison.verdict === "invalid" ? "workspace.invalid" : "workspace.noExamples")}
      </p>
      <Link
        href={`/agents/${agentId}/evals/${runId}`}
        className="text-sm underline underline-offset-4"
      >
        {t("openCheck")}
      </Link>
    </div>
  );
}
