"use client";

import { useTranslations } from "next-intl";

import { SuiteCheckVerdict } from "@/components/evals/suite-check-verdict";
import { useEvalRun } from "@/hooks/use-eval-runs";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";

/**
 * Beside a batch's checks, what each suite a check ran on would have said of it.
 * A check is an eval run, read only by a reader of runs, as its link is.
 */
export function CheckRunVerdicts({ agentId, runIds }: { agentId: string; runIds: string[] }) {
  const { can } = usePermissions();
  if (!can(Perm.runsView)) return null;
  return (
    <div className="space-y-2">
      {runIds.map((runId, index) => (
        <CheckRunVerdict key={runId} agentId={agentId} runId={runId} index={index} />
      ))}
    </div>
  );
}

function CheckRunVerdict({
  agentId,
  runId,
  index,
}: {
  agentId: string;
  runId: string;
  index: number;
}) {
  const t = useTranslations("authoring.batch");
  const { run } = useEvalRun(runId);
  if (!run?.suite_check || run.suite_check.status === null) return null;
  return (
    <div className="space-y-1">
      <p className="text-muted-foreground text-xs">{t("checkRun", { index: index + 1 })}</p>
      <SuiteCheckVerdict agentId={agentId} check={run.suite_check} />
    </div>
  );
}
