"use client";

import { type ReactNode, useState } from "react";
import { FlaskConical, Play } from "lucide-react";
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
import { EvalTrend } from "./eval-trend";
import { passRateLines } from "./pass-rate-chart";
import { RunsTable } from "./runs-table";
import { StartEvalDialog } from "./start-eval-dialog";

/** As many runs as the trend reads back at once - the API's own ceiling - a page of them. */
const TREND_RUNS = 100;

export function EvalsPanel({
  agentId,
  canStart,
  actions,
}: {
  agentId: string;
  canStart: boolean;
  actions?: ReactNode;
}) {
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
  const anyDataset = useDatasets({ sort: "updated", limit: 1 });
  const start = canStart ? { label: t("start"), onClick: () => setStarting(true) } : undefined;
  // With no runs, which empty state is right depends on whether a dataset exists,
  // so the datasets' read decides as much as the runs'.
  const waiting = isLoading || (runs.length === 0 && anyDataset.isLoading);
  const failed = error ?? (runs.length === 0 ? anyDataset.error : null);

  return (
    <Card data-tour="agent-evals" className="flex flex-1 flex-col">
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-4 space-y-0">
        <div className="space-y-1.5">
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          {actions}
          {start && runs.length > 0 && (
            <Button size="sm" onClick={start.onClick}>
              <Play className="h-3.5 w-3.5" aria-hidden />
              {start.label}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-6">
        {waiting ? (
          <LoadingState variant="skeleton-list" rows={3} />
        ) : failed ? (
          <ErrorState
            description={getErrorMessage(failed, tErrors)}
            cta={{
              label: tc("retry"),
              onClick: () => void (error ? refetch() : anyDataset.refetch()),
            }}
          />
        ) : runs.length === 0 ? (
          anyDataset.datasets.length === 0 ? (
            <EmptyState
              className="flex-1 border-0 bg-transparent"
              icon={FlaskConical}
              title={t("empty.noDatasetTitle")}
              description={t("empty.noDatasetBody")}
              cta={{ label: t("empty.createDataset"), href: ROUTES.DATASETS }}
            />
          ) : (
            <EmptyState
              className="flex-1 border-0 bg-transparent"
              icon={FlaskConical}
              title={t("empty.title")}
              description={t("empty.body")}
              cta={start}
            />
          )
        ) : (
          <>
            <EvalTrend
              className="px-0 pt-0 sm:px-0 sm:pt-0"
              lines={passRateLines(
                runs,
                (run) => ({ key: run.dataset_id, name: run.dataset_name }),
                t,
                locale,
              )}
            />
            <RunsTable runs={runs} />
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
