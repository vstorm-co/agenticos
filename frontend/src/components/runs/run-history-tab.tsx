"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Activity } from "lucide-react";

import { FocusedRun } from "@/components/runs/focused-run";
import { RunTable, type RunSort, type RunSortKey } from "@/components/runs/run-table";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { useRuns } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { getErrorMessage } from "@/lib/utils";

/**
 * The "slow runs" preset's threshold, in milliseconds.
 *
 * Thirty seconds is the example the design gives for the query somebody actually
 * types - "everything slower than 30 seconds" - and the canned view is that query
 * as one click. The number is a starting point a reader narrows from, not a
 * definition of slow; the sort beside it is what finds the genuine outliers.
 */
const SLOW_RUN_THRESHOLD_MS = 30_000;

/**
 * Run history, and whichever sentence says what it has been narrowed to.
 *
 * `agentId` and `focusedRunId` come in as props rather than being read here: they
 * are query parameters, and a component that reaches for the URL itself can only
 * ever be used on the page whose URL it knows. Nothing in here is aware of the
 * Activity page.
 *
 * `initialDurationSort`, `startedFrom` and `startedTo` are how the dashboard's
 * p95 figure hands over: it links here sorted by duration over the same window,
 * so the sort and the window arrive already chosen and this tab opens on *those
 * runs* rather than on the feed. The sort is then the reader's to change through
 * the Took header or the canned views.
 *
 * A failed request is said out loud. `?run=` is delegated to `FocusedRun`, which
 * has its own two answers for a run that is gone versus a request that did not
 * arrive - and the difference matters more there, because a link brought somebody
 * to that run on purpose.
 */
export function RunHistoryTab({
  agentId,
  focusedRunId,
  initialDurationSort = false,
  startedFrom = null,
  startedTo = null,
}: {
  agentId: string | null;
  focusedRunId: string | null;
  initialDurationSort?: boolean;
  startedFrom?: string | null;
  startedTo?: string | null;
}) {
  const t = useTranslations("pages.runs");
  const [sort, setSort] = useState<RunSort>(
    initialDurationSort ? { by: "duration", dir: "desc" } : { by: "started_at", dir: "desc" },
  );
  // Independent of the sort: "slow runs" is a filter, and the reader can still
  // re-sort the slow set by start time without it ceasing to be the slow set.
  const [minDurationMs, setMinDurationMs] = useState<number | null>(null);

  const { runs, isLoading, error, refetch } = useRuns(agentId ?? undefined, {
    startedFrom: startedFrom ?? undefined,
    startedTo: startedTo ?? undefined,
    orderBy: sort.by,
    descending: sort.dir === "desc",
    tookOverMs: minDurationMs ?? undefined,
  });

  const toggleSort = (key: RunSortKey) =>
    setSort((current) =>
      current.by === key
        ? { by: key, dir: current.dir === "asc" ? "desc" : "asc" }
        : { by: key, dir: "desc" },
    );

  const showSlow = () => {
    setSort({ by: "duration", dir: "desc" });
    setMinDurationMs(SLOW_RUN_THRESHOLD_MS);
  };
  const showAll = () => {
    setSort({ by: "started_at", dir: "desc" });
    setMinDurationMs(null);
  };
  const slowActive = minDurationMs !== null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("runHistory2")}</CardTitle>
        <CardDescription>
          Every run records the agent <em>{t("version")}</em>
          {t("executedSoWhatHappened")}
        </CardDescription>
        {/* Said out loud, with the way out beside it. A filtered table that
            does not mention the filter is a table somebody reads as the
            whole history, and then wonders where the rest of the runs went.
            `?run=` narrows harder than `?agent=` and so says so first. */}
        {focusedRunId !== null ? (
          <p className="text-muted-foreground text-xs">
            {t("narrowedToOneRun")}{" "}
            <Link href={ROUTES.RUNS} className="underline underline-offset-4">
              {t("showEveryRun")}
            </Link>
          </p>
        ) : (
          agentId !== null && (
            <p className="text-muted-foreground text-xs">
              {t("narrowedToOneAgent")}{" "}
              <Link href={ROUTES.RUNS} className="underline underline-offset-4">
                {t("showEveryAgent")}
              </Link>
            </p>
          )
        )}
      </CardHeader>
      <CardContent>
        {focusedRunId !== null ? (
          <FocusedRun runId={focusedRunId} />
        ) : (
          <div className="space-y-3">
            {/* Canned views: the common questions as one click each. "Slow runs"
                is duration descending over a threshold - the gap the dashboard's
                p95 figure points at - and "All runs" is the way back to the feed. */}
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant={slowActive ? "outline" : "secondary"}
                size="sm"
                aria-pressed={!slowActive}
                onClick={showAll}
              >
                {t("allRuns")}
              </Button>
              <Button
                variant={slowActive ? "secondary" : "outline"}
                size="sm"
                aria-pressed={slowActive}
                onClick={showSlow}
              >
                {t("slowRuns")}
              </Button>
            </div>
            {isLoading ? (
              <LoadingState variant="skeleton-table" columns={7} rows={6} />
            ) : error ? (
              <ErrorState
                title={t("runHistoryCouldNot")}
                description={getErrorMessage(error, t("theseRunsHappenedThe"))}
                cta={{ label: t("tryAgain"), onClick: () => void refetch() }}
              />
            ) : runs.length === 0 ? (
              <EmptyState icon={Activity} title={t("noRunsYet")} description={t("nothingHasRun")} />
            ) : (
              <RunTable runs={runs} sort={sort} onSort={toggleSort} />
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
