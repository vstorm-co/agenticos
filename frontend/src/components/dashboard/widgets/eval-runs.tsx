"use client";

import { FlaskConical } from "lucide-react";
import { useTranslations } from "next-intl";

import { EvalRunRow } from "@/components/evals/run-row";
import { useAgents } from "@/hooks";
import { useRecentEvalRuns } from "@/hooks/use-eval-runs";
import { usePermissions } from "@/hooks/use-permissions";
import type { EvalRunStatus } from "@/types/eval-runs";
import { Perm } from "@/types/permissions";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many a card lists; each agent's Evals tab has the rest. */
const SHOWN = 6;

/** The statuses the breakdown counts, in the order a reader scans them. */
const COUNTED: EvalRunStatus[] = ["running", "completed", "failed", "budget_exceeded"];

/**
 * The organization's latest eval runs: how many are running, finished or
 * stopped, and for each the agent, what was tested against what, its verdict
 * and its pass rate - one click from the run's own page.
 */
export function EvalRunsWidget({ title, hint, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.eval-runs");
  const { can } = usePermissions();
  const { runs, isLoading, error, refetch } = useRecentEvalRuns(SHOWN);
  // Names need agents:view; without it a row starts at what was tested.
  const { agents } = useAgents({ enabled: can(Perm.agentsView) });
  const names = new Map(agents.map((agent) => [agent.id, agent.name]));
  const counts = COUNTED.map((status) => ({
    status,
    count: runs.filter((run) => run.status === status).length,
  })).filter(({ count }) => count > 0);

  return (
    <WidgetFrame title={title} hint={hint} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : runs.length === 0 ? (
        <WidgetEmptyBody
          icon={FlaskConical}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <div className="space-y-2">
          <p className="text-muted-foreground flex flex-wrap gap-x-3 text-xs">
            {counts.map(({ status, count }) => (
              <span key={status}>{t(`count.${status}`, { count })}</span>
            ))}
          </p>
          <ul className="divide-border divide-y">
            {runs.map((run) => (
              <EvalRunRow key={run.id} run={run} agentName={names.get(run.agent_id)} />
            ))}
          </ul>
        </div>
      )}
    </WidgetFrame>
  );
}
