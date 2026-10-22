"use client";

import { useTranslations } from "next-intl";

import { SuiteCheckVerdict } from "@/components/evals/suite-check-verdict";
import { useEvalRun } from "@/hooks/use-eval-runs";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";

/** How many of a batch's latest checks are read for a suite's verdict. */
const LATEST_CHECKS = 3;

/**
 * Beside a batch's checks, what each suite a check ran on would have said of it -
 * for the latest few, since each is a read of its run and a batch keeps them all.
 * A check is an eval run, read only by a reader of runs, as its link is.
 */
export function CheckRunVerdicts({ agentId, runIds }: { agentId: string; runIds: string[] }) {
  const { can } = usePermissions();
  if (!can(Perm.runsView)) return null;
  const first = Math.max(runIds.length - LATEST_CHECKS, 0);
  return (
    <div className="space-y-2">
      {runIds.slice(first).map((runId, offset) => (
        <CheckRunVerdict key={runId} agentId={agentId} runId={runId} index={first + offset} />
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
