"use client";

import { useState } from "react";
import { ChevronRight, FlaskConical, Play } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, ListCard } from "@/components/ui";
import { useAgents } from "@/hooks";
import { useDatasetEvalRuns } from "@/hooks/use-eval-runs";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import type { EvalRun } from "@/types/eval-runs";
import { Perm } from "@/types/permissions";
import { PassRateChart, passRateLines } from "./pass-rate-chart";
import { EvalRunRow } from "./run-row";
import { StartEvalDialog } from "./start-eval-dialog";

/**
 * Starting a run from a dataset: the dialog opens on this dataset and asks
 * which agent to test. Offered to who may run a dataset.
 */
export function DatasetRunEvalsButton({ datasetId }: { datasetId: string }) {
  const t = useTranslations("evals");
  const { can } = usePermissions();
  const [open, setOpen] = useState(false);
  if (!can(Perm.datasetsRun)) return null;
  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)} data-tour="dataset-run-evals">
        <Play className="h-3.5 w-3.5" aria-hidden />
        {t("start")}
      </Button>
      {open && <StartEvalDialog agentId={null} datasetId={datasetId} onOpenChange={setOpen} />}
    </>
  );
}

/** Runs by agent, each group in the order its newest run came. */
function byAgent(runs: EvalRun[]): { id: string; runs: EvalRun[] }[] {
  const groups = new Map<string, EvalRun[]>();
  for (const run of runs) groups.set(run.agent_id, [...(groups.get(run.agent_id) ?? []), run]);
  return [...groups.entries()].map(([id, grouped]) => ({ id, runs: grouped }));
}

/**
 * A dataset's Evals tab: every agent measured on it, each folded to its own
 * pass-rate trend and its runs with their verdicts, in a card whose header
 * counts them once they are read.
 */
export function DatasetEvalsPanel({ datasetId, title }: { datasetId: string; title: string }) {
  const t = useTranslations("evals");
  const { runs, isLoading, error, refetch } = useDatasetEvalRuns(datasetId);
  const { agents } = useAgents();
  const names = new Map(agents.map((agent) => [agent.id, agent.name]));
  const groups = byAgent(runs);
  const counted = isLoading
    ? null
    : error
      ? ""
      : t("dataset.counted", { runs: runs.length, agents: groups.length });
  return (
    <ListCard title={title} counted={counted}>
      {isLoading ? (
        <LoadingState variant="skeleton-list" rows={3} />
      ) : (
        <Groups
          datasetId={datasetId}
          groups={groups}
          names={names}
          error={error}
          onRetry={() => void refetch()}
        />
      )}
    </ListCard>
  );
}

/** The card's body once the runs are read: why they could not be, none yet, or each agent's. */
function Groups({
  datasetId,
  groups,
  names,
  error,
  onRetry,
}: {
  datasetId: string;
  groups: { id: string; runs: EvalRun[] }[];
  names: Map<string, string>;
  error: Error | null;
  onRetry: () => void;
}) {
  const t = useTranslations("evals");
  const tErrors = useTranslations("errors");
  const tc = useTranslations("common");
  const locale = useLocale();
  if (error) {
    return (
      <ErrorState
        description={getErrorMessage(error, tErrors)}
        cta={{ label: tc("retry"), onClick: onRetry }}
      />
    );
  }
  if (groups.length === 0) {
    return (
      <div className="space-y-3">
        <EmptyState
          icon={FlaskConical}
          title={t("dataset.emptyTitle")}
          description={t("dataset.emptyBody")}
        />
        <div className="flex justify-center">
          <DatasetRunEvalsButton datasetId={datasetId} />
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-4" data-tour="dataset-evals">
      {groups.map((group, index) => {
        const name = names.get(group.id) ?? t("dataset.unnamedAgent");
        return (
          <details key={group.id} open={index === 0} className="group rounded-lg border p-3">
            <summary className="flex cursor-pointer list-none items-center gap-1.5 text-sm font-medium">
              <ChevronRight
                className="h-3.5 w-3.5 transition-transform group-open:rotate-90"
                aria-hidden
              />
              {t("group", { name, count: group.runs.length })}
            </summary>
            <div className="mt-3 space-y-3">
              <PassRateChart
                compact
                lines={passRateLines(group.runs, () => ({ key: group.id, name }), t, locale)}
              />
              <ul className="divide-border divide-y">
                {group.runs.map((run) => (
                  <EvalRunRow key={run.id} run={run} />
                ))}
              </ul>
            </div>
          </details>
        );
      })}
    </div>
  );
}
