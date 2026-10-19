"use client";

import { useState } from "react";
import { ChevronRight, FlaskConical, Play } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Pager,
} from "@/components/ui";
import { useDatasets } from "@/hooks/use-datasets";
import { useEvalRuns } from "@/hooks/use-eval-runs";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import type { EvalRun } from "@/types/eval-runs";
import { PassRateChart, passRateLines } from "./pass-rate-chart";
import { EvalRunRow } from "./run-row";
import { StartEvalDialog } from "./start-eval-dialog";

/** As many runs as the trend reads back at once - the API's own ceiling - a page of them. */
const TREND_RUNS = 100;

/** Runs by dataset, each group in the order its newest run came. */
export function byDataset(runs: EvalRun[]): { id: string; name: string; runs: EvalRun[] }[] {
  const groups = new Map<string, { id: string; name: string; runs: EvalRun[] }>();
  for (const run of runs) {
    const group = groups.get(run.dataset_id) ?? {
      id: run.dataset_id,
      name: run.dataset_name,
      runs: [],
    };
    group.runs.push(run);
    groups.set(run.dataset_id, group);
  }
  return [...groups.values()];
}

/**
 * The Evals tab: how the agent's pass rate moved, version after version, on
 * each dataset - then every run, grouped by the dataset it answered, each with
 * its verdict. A run is rare and costs money, so starting one is a button here
 * rather than a control on every screen.
 */
export function EvalsPanel({ agentId, canStart }: { agentId: string; canStart: boolean }) {
  const t = useTranslations("evals");
  const tErrors = useTranslations("errors");
  const tc = useTranslations("common");
  const locale = useLocale();
  const [starting, setStarting] = useState(false);
  const [page, setPage] = useState(0);
  const { runs, total, isLoading, error, refetch } = useEvalRuns(agentId, {
    skip: page * TREND_RUNS,
    limit: TREND_RUNS,
  });
  const { datasets } = useDatasets({ sort: "updated", limit: 1 });
  const start = canStart ? { label: t("start"), onClick: () => setStarting(true) } : undefined;
  const groups = byDataset(runs);

  return (
    <Card data-tour="agent-evals">
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div className="space-y-1.5">
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </div>
        {start && runs.length > 0 && (
          <Button size="sm" onClick={start.onClick}>
            <Play className="h-3.5 w-3.5" aria-hidden />
            {start.label}
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-6">
        {isLoading ? (
          <LoadingState variant="skeleton-list" rows={3} />
        ) : error ? (
          <ErrorState
            description={getErrorMessage(error, tErrors)}
            cta={{ label: tc("retry"), onClick: () => void refetch() }}
          />
        ) : runs.length === 0 ? (
          datasets.length === 0 ? (
            <EmptyState
              icon={FlaskConical}
              title={t("empty.noDatasetTitle")}
              description={t("empty.noDatasetBody")}
              cta={{ label: t("empty.createDataset"), href: ROUTES.DATASETS }}
            />
          ) : (
            <EmptyState
              icon={FlaskConical}
              title={t("empty.title")}
              description={t("empty.body")}
              cta={start}
            />
          )
        ) : (
          <>
            <PassRateChart
              lines={passRateLines(
                runs,
                (run) => ({ key: run.dataset_id, name: run.dataset_name }),
                t,
                locale,
              )}
            />
            {groups.map((group, index) => (
              <details key={group.id} open={index === 0} className="group">
                <summary className="flex cursor-pointer list-none items-center gap-1.5 text-sm font-medium">
                  <ChevronRight
                    className="h-3.5 w-3.5 transition-transform group-open:rotate-90"
                    aria-hidden
                  />
                  {t("group", { name: group.name, count: group.runs.length })}
                </summary>
                <ul className="divide-border mt-2 divide-y">
                  {group.runs.map((run) => (
                    <EvalRunRow key={run.id} run={run} />
                  ))}
                </ul>
              </details>
            ))}
            <Pager
              page={page}
              pageCount={Math.ceil(total / TREND_RUNS)}
              matched={total}
              total={total}
              onPage={setPage}
              counted={t("runCount", { count: total })}
            />
          </>
        )}
      </CardContent>
      {starting && <StartEvalDialog agentId={agentId} onOpenChange={setStarting} />}
    </Card>
  );
}
