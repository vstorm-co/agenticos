"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Activity, ThumbsDown } from "lucide-react";

import { getErrorMessage } from "@/lib/api-error";
import { FocusedRun } from "@/components/runs/focused-run";
import { RunTable, type RunSort, type RunSortKey } from "@/components/runs/run-table";
import { VersionStrip } from "@/components/runs/version-strip";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { usePermissions, useRuns } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";

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
 * "Rated down" is the one narrowing this tab owns rather than inherits from a
 * query parameter: the highest-signal queue here, the answers real people said
 * were wrong. It is offered only to a caller who may read runs at all - a
 * control that would 403 is not rendered - and a filtered-empty list says it was
 * the filter, not that nothing has ever run.
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
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.runs");
  const { can } = usePermissions();
  const canView = can(Perm.runsView);
  const [ratedDown, setRatedDown] = useState(false);
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
    rated: ratedDown ? "down" : undefined,
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
    <div className="space-y-4">
      {/* Narrowed to an agent, a per-version summary sits above the table - the
          builder's "did v4 behave better than v3" answered where the evidence
          is. Its completed share is the shared `completedShare`, so it reads as
          the same figure the dashboard's Outcomes donut shows (§8a.4). A
          per-version summary makes no sense over a single focused run, so it is
          not drawn when `?run=` has narrowed the card below to one. */}
      {agentId !== null && focusedRunId === null && <VersionStrip agentId={agentId} />}
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1.5">
              <CardTitle>{t("runHistory2")}</CardTitle>
              <CardDescription>
                {t.rich("runHistoryDescription", { em: (chunks) => <em>{chunks}</em> })}
              </CardDescription>
            </div>
            {/* Offered only in list mode and only to a caller who may read runs:
                a filter over a list that is not shown, or one whose request would
                be refused, is a control with nothing to do. */}
            {focusedRunId === null && canView && (
              <Button
                variant={ratedDown ? "default" : "outline"}
                size="sm"
                aria-pressed={ratedDown}
                onClick={() => setRatedDown((on) => !on)}
                className="shrink-0"
              >
                <ThumbsDown className="mr-1.5 h-4 w-4" />
                {t("ratedDown")}
              </Button>
            )}
          </div>
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
                  description={getErrorMessage(error, tErrors, t("theseRunsHappenedThe"))}
                  cta={{ label: t("tryAgain"), onClick: () => void refetch() }}
                />
              ) : runs.length === 0 ? (
                ratedDown ? (
                  <EmptyState
                    icon={ThumbsDown}
                    title={t("noRunsRatedDown")}
                    description={t("nothingHereWasRatedDown")}
                  />
                ) : (
                  <EmptyState
                    icon={Activity}
                    title={t("noRunsYet")}
                    description={t("nothingHasRun")}
                  />
                )
              ) : (
                <RunTable runs={runs} sort={sort} onSort={toggleSort} />
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
