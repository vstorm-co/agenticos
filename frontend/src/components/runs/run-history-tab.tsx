"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Activity, ThumbsDown } from "lucide-react";

import { getErrorMessage } from "@/lib/api-error";
import { ExportMenu } from "@/components/runs/export-menu";
import { FocusedRun } from "@/components/runs/focused-run";
import {
  DEFAULT_RUN_FILTERS,
  RunFilterBar,
  type RunFilters,
} from "@/components/runs/run-filter-bar";
import { RunTable, type RunSort } from "@/components/runs/run-table";
import { VersionStrip } from "@/components/runs/version-strip";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  PaginationBar,
} from "@/components/ui";
import { usePermissions, useRuns } from "@/hooks";
import { formatPeriodParam, periodEnd, periodStart, type Period } from "@/lib/dashboard/period";
import { Perm } from "@/types/permissions";
import type { RunStatus } from "@/types/runs";

/**
 * The "slow runs" preset's threshold, in milliseconds.
 *
 * Thirty seconds is the example the design gives for the query somebody actually
 * types - "everything slower than 30 seconds" - and the canned view is that query
 * as one click. The number is a starting point a reader narrows from, not a
 * definition of slow; the sort beside it is what finds the genuine outliers.
 */
const SLOW_RUN_THRESHOLD_MS = 30_000;

/** "What went wrong" as one choice - the query the two statuses exist apart for. */
const PROBLEM_STATUSES: RunStatus[] = ["failed", "budget_exceeded"];

/** One server page - `GET /runs`' own default, so an unpaged call reads the same. */
const PAGE_SIZE = 50;

/**
 * Run history, and whichever sentence says what it has been narrowed to.
 *
 * `agentId` and `focusedRunId` come in as props rather than being read here: they
 * are query parameters, and a component that reaches for the URL itself can only
 * ever be used on the page whose URL it knows. Nothing in here is aware of the
 * Activity page.
 *
 * The filters live in `RunFilterBar` and this tab owns their state: which
 * statuses, which surface, which rating, whose runs, which version. They are
 * offered only to a caller who may read runs at all - a control that would 403
 * is not rendered - and a filtered-empty list says it was the filter, not that
 * nothing has ever run.
 *
 * `period` is the page's window - the one control every tab shares - and
 * `initialDurationSort` is how the dashboard's p95 figure hands over: it links
 * here sorted by duration with the window already in the URL, so this tab opens
 * on *those runs* rather than on the feed. The sort is then the reader's to
 * change through the Took header or the canned views.
 *
 * A failed request is said out loud. `?run=` is delegated to `FocusedRun`, which
 * has its own two answers for a run that is gone versus a request that did not
 * arrive - and the difference matters more there, because a link brought somebody
 * to that run on purpose.
 */
export function RunHistoryTab({
  agentId,
  focusedRunId,
  period,
  onAgentChange,
  onFocusRun,
  initialDurationSort = false,
}: {
  agentId: string | null;
  focusedRunId: string | null;
  period: Period;
  onAgentChange: (agentId: string | null) => void;
  onFocusRun: (runId: string | null) => void;
  initialDurationSort?: boolean;
}) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.runs");
  const { can } = usePermissions();
  const canView = can(Perm.runsView);
  const [filters, setFilters] = useState<RunFilters>(DEFAULT_RUN_FILTERS);
  const [sort, setSort] = useState<RunSort>(
    initialDurationSort ? { by: "duration", dir: "desc" } : { by: "started_at", dir: "desc" },
  );
  // Independent of the sort: "slow runs" is a filter, and the reader can still
  // re-sort the slow set by start time without it ceasing to be the slow set.
  const [minDurationMs, setMinDurationMs] = useState<number | null>(null);

  // The version narrowing belongs to one agent's history: carried across a
  // change of agent it would silently empty the next agent's list.
  const changeAgent = (next: string | null) => {
    setFilters((current) => ({ ...current, versionId: "all" }));
    onAgentChange(next);
  };

  // Which page, keyed on everything that redefines the set being paged: page
  // three of the failed runs is not page three of everything, so any change of
  // window, narrowing or order snaps back to the first page (the render-time
  // adjustment pattern - the key covers props and sibling state alike).
  const narrowingKey = [
    formatPeriodParam(period),
    agentId,
    sort.by,
    sort.dir,
    minDurationMs,
    JSON.stringify(filters),
  ].join("|");
  const [paging, setPaging] = useState({ key: narrowingKey, page: 0 });
  if (paging.key !== narrowingKey) {
    setPaging({ key: narrowingKey, page: 0 });
  }
  const page = paging.key === narrowingKey ? paging.page : 0;

  const { runs, total, isLoading, error, refetch } = useRuns(agentId ?? undefined, {
    startedFrom: periodStart(period),
    startedTo: periodEnd(period),
    orderBy: sort.by,
    descending: sort.dir === "desc",
    tookOverMs: minDurationMs ?? undefined,
    rated: filters.rated === "all" ? undefined : filters.rated,
    statuses:
      filters.status === "all"
        ? undefined
        : filters.status === "problems"
          ? PROBLEM_STATUSES
          : [filters.status],
    surface: filters.surface === "all" ? undefined : filters.surface,
    userId: filters.userId === "all" ? undefined : filters.userId,
    agentVersionId: filters.versionId === "all" ? undefined : filters.versionId,
    skip: page * PAGE_SIZE,
  });
  const narrowed =
    filters.rated !== "all" ||
    filters.status !== "all" ||
    filters.surface !== "all" ||
    filters.userId !== "all" ||
    filters.versionId !== "all";

  const showSlow = () => {
    setSort({ by: "duration", dir: "desc" });
    setMinDurationMs(SLOW_RUN_THRESHOLD_MS);
  };
  const showAll = () => {
    setSort({ by: "started_at", dir: "desc" });
    setMinDurationMs(null);
  };
  const slowActive = minDurationMs !== null;

  // Exactly what the table was asked with, in the export route's own names -
  // the file is what is on screen, and a filter dropped here is the #763
  // defect: a CSV read as "the failed Slack runs" that is neither.
  const exportParams: Record<string, string> = {};
  if (agentId !== null) {
    exportParams.agent_id = agentId;
    exportParams.include_delegations = "true";
  }
  if (filters.status !== "all") {
    exportParams.status =
      filters.status === "problems" ? PROBLEM_STATUSES.join(",") : filters.status;
  }
  if (filters.surface !== "all") exportParams.surface = filters.surface;
  if (filters.rated !== "all") exportParams.rated = filters.rated;
  if (filters.userId !== "all") exportParams.user_id = filters.userId;
  if (filters.versionId !== "all") exportParams.agent_version_id = filters.versionId;
  if (minDurationMs !== null) exportParams.took_over_ms = String(minDurationMs);

  return (
    <div className="space-y-4">
      {/* Narrowed to an agent, a per-version summary sits above the table - the
          builder's "did v4 behave better than v3" answered where the evidence
          is. Its completed share is the shared `completedShare`, so it reads as
          the same figure the dashboard's Outcomes donut shows (§8a.4). A
          per-version summary makes no sense over a single focused run, so it is
          not drawn when `?run=` has narrowed the card below to one. */}
      {agentId !== null && focusedRunId === null && (
        <VersionStrip agentId={agentId} period={period} />
      )}
      {/* The tab's one control row, LangSmith's grammar: canned views, then the
          filters, export on the right - above the card, so the card is the
          table and nothing else. Offered only in list mode and only to a
          caller who may read runs: a filter over a list that is not shown, or
          one whose request would be refused, is a control with nothing to do.
          The export carries exactly these filters, so they share the row. */}
      {focusedRunId === null && canView && (
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
          <RunFilterBar
            filters={filters}
            onChange={setFilters}
            agentId={agentId}
            onAgentChange={changeAgent}
          />
          <div className="ml-auto">
            <ExportMenu
              permission={Perm.runsView}
              endpoint="/runs/export"
              kind="runs"
              params={Object.keys(exportParams).length > 0 ? exportParams : undefined}
              rangeParams={{ from: "started_from", to: "started_to" }}
              range={{ from: periodStart(period), to: periodEnd(period) }}
            />
          </div>
        </div>
      )}
      <Card>
        <CardHeader>
          <div className="space-y-1.5">
            <CardTitle>{t("runHistory2")}</CardTitle>
            <CardDescription>
              {t.rich("runHistoryDescription", { em: (chunks) => <em>{chunks}</em> })}
            </CardDescription>
          </div>
          {/* Said out loud, with the way out beside it. A filtered table that
              does not mention the filter is a table somebody reads as the
              whole history, and then wonders where the rest of the runs went.
              `?run=` narrows harder than `?agent=` and so says so first. Both
              ways out are actions that clear the state the page shares - a
              plain link to /runs would rewrite the URL and leave it standing. */}
          {focusedRunId !== null ? (
            <p className="text-muted-foreground text-xs">
              {t("narrowedToOneRun")}{" "}
              <button
                type="button"
                onClick={() => onFocusRun(null)}
                className="underline underline-offset-4"
              >
                {t("showEveryRun")}
              </button>
            </p>
          ) : (
            agentId !== null && (
              <p className="text-muted-foreground text-xs">
                {t("narrowedToOneAgent")}{" "}
                <button
                  type="button"
                  onClick={() => changeAgent(null)}
                  className="underline underline-offset-4"
                >
                  {t("showEveryAgent")}
                </button>
              </p>
            )
          )}
        </CardHeader>
        <CardContent>
          {focusedRunId !== null ? (
            <FocusedRun runId={focusedRunId} onFocusRun={onFocusRun} />
          ) : (
            <div className="space-y-3">
              {isLoading ? (
                <LoadingState variant="skeleton-table" columns={7} rows={6} />
              ) : error ? (
                <ErrorState
                  title={t("runHistoryCouldNot")}
                  description={getErrorMessage(error, tErrors, t("theseRunsHappenedThe"))}
                  cta={{ label: t("tryAgain"), onClick: () => void refetch() }}
                />
              ) : runs.length === 0 ? (
                filters.rated === "down" ? (
                  <EmptyState
                    icon={ThumbsDown}
                    title={t("noRunsRatedDown")}
                    description={t("nothingHereWasRatedDown")}
                  />
                ) : narrowed ? (
                  // The filters emptied it, not the organization: "no runs"
                  // over a narrowed list reads as a history that never happened.
                  <EmptyState
                    icon={Activity}
                    title={t("noRunsMatch")}
                    description={t("loosenAFilterAbove")}
                  />
                ) : (
                  // The window is always a narrowing too - an organization
                  // whose runs are all older than it must not be told nothing
                  // has ever run.
                  <EmptyState
                    icon={Activity}
                    title={t("noRunsInWindow")}
                    description={t("widenTheWindowAbove")}
                  />
                )
              ) : (
                <>
                  <RunTable
                    runs={runs}
                    sort={sort}
                    onSort={setSort}
                    onOpen={(run) => onFocusRun(run.id)}
                  />
                  <PaginationBar
                    page={page}
                    pageSize={PAGE_SIZE}
                    total={total}
                    isLoading={isLoading}
                    onPage={(next) => setPaging({ key: narrowingKey, page: next })}
                  />
                </>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
