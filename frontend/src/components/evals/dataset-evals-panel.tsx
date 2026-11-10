"use client";

import { useState } from "react";
import { ArrowRight, ClipboardCheck, FlaskConical, Play } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, ListCard, Pager } from "@/components/ui";
import { useDataset } from "@/hooks/use-datasets";
import { useDatasetEvalRuns, useEveryAgent } from "@/hooks/use-eval-runs";
import { getErrorMessage } from "@/lib/api-error";
import type { Agent } from "@/types/agents";
import type { EvalRun } from "@/types/eval-runs";
import { NeedsRunsView } from "./needs-runs-view";
import { EvalTrend } from "./eval-trend";
import { passRateLines } from "./pass-rate-chart";
import { RunsTable } from "./runs-table";
import { StartEvalDialog } from "./start-eval-dialog";

/**
 * Starting a run from a dataset: the dialog opens on this dataset and asks
 * which agent to test. Offered to who may run this dataset - a run grant on it
 * counts as much as the role - and shown disabled, saying why, to one who
 * lacks only permission to read runs.
 */
export function DatasetRunEvalsButton({ datasetId }: { datasetId: string }) {
  const t = useTranslations("evals");
  const { dataset } = useDataset(datasetId);
  const [open, setOpen] = useState(false);
  if (dataset === undefined) return null;
  if (!dataset.can_run) {
    // Disabled with a reason only where reading runs alone is missing: a reader
    // who may not run the dataset either has nothing to be told about.
    if (dataset.run_needs.join() !== "runs:view") return null;
    return (
      <NeedsRunsView size="sm">
        <Play className="h-3.5 w-3.5" aria-hidden />
        {t("start")}
      </NeedsRunsView>
    );
  }
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

/** As many runs as one page of the tab reads - the API's own ceiling. */
const RUN_PAGE = 100;

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
export function DatasetEvalsPanel({
  datasetId,
  title,
  onReview,
}: {
  datasetId: string;
  title: string;
  onReview?: () => void;
}) {
  const t = useTranslations("evals");
  const [page, setPage] = useState(0);
  const { runs, total, isLoading, error, refetch } = useDatasetEvalRuns(datasetId, {
    skip: page * RUN_PAGE,
    limit: RUN_PAGE,
  });
  const { agents } = useEveryAgent();
  const known = new Map(agents.map((agent) => [agent.id, agent]));
  const groups = byAgent(runs);
  // Past one page the agents on it are not every agent measured, so only the runs are counted.
  const counted = isLoading
    ? null
    : error
      ? ""
      : total > RUN_PAGE
        ? t("runCount", { count: total })
        : t("dataset.counted", { runs: total, agents: groups.length });
  return (
    <ListCard
      fill
      namedByPage
      title={title}
      counted={counted}
      contentClassName="p-0"
      controls={
        onReview && runs.some((run) => run.status === "completed") ? (
          <ReviewResultsButton onClick={onReview} />
        ) : undefined
      }
    >
      {isLoading ? (
        <LoadingState variant="skeleton-list" rows={3} />
      ) : (
        <Groups
          datasetId={datasetId}
          groups={groups}
          known={known}
          error={error}
          onRetry={() => void refetch()}
        />
      )}
      {!isLoading && !error && (
        <Pager
          page={page}
          pageCount={Math.ceil(total / RUN_PAGE)}
          matched={total}
          total={total}
          onPage={setPage}
          counted={t("runCount", { count: total })}
        />
      )}
    </ListCard>
  );
}

/** The card's body once the runs are read: why they could not be, none yet, or each agent's. */
function Groups({
  datasetId,
  groups,
  known,
  error,
  onRetry,
}: {
  datasetId: string;
  groups: { id: string; runs: EvalRun[] }[];
  known: Map<string, Agent>;
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
      <div className="flex flex-1 flex-col justify-center gap-3">
        <EmptyState
          className="border-0 bg-transparent"
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
    <div className="min-w-0" data-tour="dataset-evals">
      <EvalTrend
        rangeKey={`dataset-${datasetId}`}
        lines={passRateLines(
          groups.flatMap((group) => group.runs),
          (run) => ({
            key: run.agent_id,
            name: known.get(run.agent_id)?.name ?? t("dataset.unnamedAgent"),
          }),
          t,
          locale,
        )}
      />
      <RunsTable
        runs={groups
          .flatMap((group) => group.runs)
          .sort((a, b) => b.created_at.localeCompare(a.created_at))}
        agentName={(id) => known.get(id)?.name ?? t("dataset.unnamedAgent")}
      />
    </div>
  );
}

function ReviewResultsButton({ onClick }: { onClick: () => void }) {
  const t = useTranslations("datasets.journey");
  return (
    <Button size="sm" variant="outline" onClick={onClick}>
      <ClipboardCheck className="size-4" aria-hidden />
      {t("reviewAction")}
      <ArrowRight className="size-3.5" aria-hidden />
    </Button>
  );
}
