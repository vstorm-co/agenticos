"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Activity, ThumbsDown } from "lucide-react";

import { getErrorMessage } from "@/lib/api-error";
import { ExportMenu } from "@/components/runs/export-menu";
import { RunFilterBar } from "@/components/runs/run-filter-bar";
import { RunTable, type RunSort } from "@/components/runs/run-table";
import { VersionStrip } from "@/components/runs/version-strip";
import { ErrorState, LoadingState } from "@/components/states";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  ListCardControlsRow,
  ListCardEmpty,
  ListCardFootRow,
  PaginationBar,
} from "@/components/ui";
import { useAgents, useMembers, usePermissions, useRuns } from "@/hooks";
import { useOrgStore } from "@/stores";
import { formatPeriodParam, periodEnd, periodStart, type Period } from "@/lib/dashboard/period";
import { isNarrowed, type RunFilters } from "@/lib/runs/filter-params";
import { setUrlParam } from "@/lib/utils";
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
 * A failed request is said out loud. A row click hands the run to `onFocusRun`;
 * the drawer that answers is the page's, because the approvals tab opens runs
 * through the same door.
 */
export function RunHistoryTab({
  agentId,
  period,
  filters,
  onFiltersChange,
  onAgentChange,
  onFocusRun,
  focusedRunId = null,
  initialDurationSort = false,
}: {
  agentId: string | null;
  period: Period;
  /** Which narrowing is in force. The page's, because it is the URL's. */
  filters: RunFilters;
  onFiltersChange: (filters: RunFilters) => void;
  onAgentChange: (agentId: string | null) => void;
  onFocusRun: (runId: string | null) => void;
  /** Which run the detail panel is showing, so its row reads as the open one. */
  focusedRunId?: string | null;
  initialDurationSort?: boolean;
}) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.runs");
  const { can } = usePermissions();
  const canView = can(Perm.runsView);
  // Names and faces for the table's Agent and User columns. The agent list
  // takes agents:view, so it is only asked for by a holder - withheld, the
  // column is too. The member list is any member's to read.
  const canAgents = can(Perm.agentsView);
  const { agents: agentRows } = useAgents({ enabled: canAgents });
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { members } = useMembers(activeOrgId ?? "");
  const agentsById = useMemo(
    () => new Map(agentRows.map((agent) => [agent.id, agent])),
    [agentRows],
  );
  const membersById = useMemo(
    () => new Map(members.map((member) => [member.user_id, member])),
    [members],
  );
  const [sort, setSort] = useState<RunSort>(
    initialDurationSort ? { by: "duration", dir: "desc" } : { by: "started_at", dir: "desc" },
  );
  // Independent of the sort: "slow runs" is a filter, and the reader can still
  // re-sort the slow set by start time without it ceasing to be the slow set.
  const [minDurationMs, setMinDurationMs] = useState<number | null>(null);

  // The version narrowing belongs to one agent's history: carried across a
  // change of agent it would silently empty the next agent's list.
  const changeAgent = (next: string | null) => {
    onFiltersChange({ ...filters, versionId: "all" });
    onAgentChange(next);
  };
  // The same reset for an `?agent=` that changes without `changeAgent` - a
  // navigation rewrites the prop directly (the useUrlState navigation-wins
  // path), so the narrowing is keyed on the prop like the paging below.
  const [seenAgentId, setSeenAgentId] = useState(agentId);
  if (seenAgentId !== agentId) {
    setSeenAgentId(agentId);
    if (filters.versionId !== "all") onFiltersChange({ ...filters, versionId: "all" });
  }

  // The `?sort=` in the URL is the dashboard's hand-off, not state this tab
  // mirrors: left standing after the reader re-sorts, a copied link reasserts
  // the duration sort over whatever they chose.
  const changeSort = (next: RunSort) => {
    setSort(next);
    setUrlParam("sort", null);
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
    modelLabel: filters.model === "all" ? undefined : filters.model,
    userId: filters.userId === "all" ? undefined : filters.userId,
    agentVersionId: filters.versionId === "all" ? undefined : filters.versionId,
    skip: page * PAGE_SIZE,
    // Not asked without the permission: `GET /runs` refuses that caller, so the
    // request would be a predictable 403 drawn as a failure card below.
    enabled: canView,
  });
  const narrowed = isNarrowed(filters);

  const showSlow = () => {
    changeSort({ by: "duration", dir: "desc" });
    setMinDurationMs(SLOW_RUN_THRESHOLD_MS);
  };
  const showAll = () => {
    changeSort({ by: "started_at", dir: "desc" });
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
  if (filters.model !== "all") exportParams.model_label = filters.model;
  if (filters.rated !== "all") exportParams.rated = filters.rated;
  if (filters.userId !== "all") exportParams.user_id = filters.userId;
  if (filters.versionId !== "all") exportParams.agent_version_id = filters.versionId;
  if (minDurationMs !== null) exportParams.took_over_ms = String(minDurationMs);

  return (
    // A column that fills the height its caller gives it: the filters and the
    // pager stay put and the rows scroll under pinned headers, because the
    // alternative - scrolling the page - takes all three off screen and leaves a
    // wall of unlabelled numbers beside the run detail.
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {/* Narrowed to an agent, a per-version summary sits above the table - the
          builder's "did v4 behave better than v3" answered where the evidence
          is. Its completed share is the shared `completedShare`, so it reads as
          the same figure the dashboard's Outcomes donut shows (§8a.4). */}
      {agentId !== null && canView && <VersionStrip agentId={agentId} period={period} />}
      <Card className="flex min-h-0 flex-1 flex-col">
        {/* The shared list-card header dialect - border-b, px-5 py-4, text-sm
            title - so this card reads as the same container as the vault's or
            the workspaces'. The export sits in the header's right, where every
            list card keeps its primary control. */}
        <CardHeader className="shrink-0 flex-row items-start justify-between space-y-0 border-b px-5 py-4">
          <div className="space-y-1">
            <CardTitle className="text-sm">{t("runHistory2")}</CardTitle>
            <CardDescription className="text-xs">
              {t.rich("runHistoryDescription", { em: (chunks) => <em>{chunks}</em> })}
            </CardDescription>
            {/* Said out loud, with the way out beside it. A narrowed table
                that does not mention the filter is a table somebody reads as
                the whole history, and then wonders where the rest went. The
                way out is an action that clears the state the page shares - a
                plain link to /runs would rewrite the URL and leave it standing. */}
            {agentId !== null && (
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
            )}
          </div>
          {canView && (
            <ExportMenu
              permission={Perm.runsView}
              endpoint="/runs/export"
              kind="runs"
              params={Object.keys(exportParams).length > 0 ? exportParams : undefined}
              rangeParams={{ from: "started_from", to: "started_to" }}
              range={{ from: periodStart(period), to: periodEnd(period) }}
            />
          )}
        </CardHeader>
        <CardContent className="flex min-h-0 flex-1 flex-col p-0">
          {
            <>
              {/* The filters live inside the container they narrow, like every
                  list card's. Offered only to a caller who may read runs: a
                  filter over a list whose request would be refused is a
                  control with nothing to do. */}
              {canView && (
                <ListCardControlsRow className="shrink-0">
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
                    period={period}
                    onChange={onFiltersChange}
                    agentId={agentId}
                    onAgentChange={changeAgent}
                  />
                </ListCardControlsRow>
              )}
              {!canView ? (
                // Whose decision the absence is - nothing above asked, so
                // nothing below failed, and the window's empty state would
                // read as a history that never happened.
                <ListCardEmpty
                  icon={Activity}
                  title={t("noAccessToRuns")}
                  description={t("runsViewIsMissing")}
                />
              ) : isLoading ? (
                <LoadingState variant="skeleton-table" columns={7} rows={6} className="m-5" />
              ) : error ? (
                <ErrorState
                  title={t("runHistoryCouldNot")}
                  description={getErrorMessage(error, tErrors, t("theseRunsHappenedThe"))}
                  cta={{ label: t("tryAgain"), onClick: () => void refetch() }}
                  className="m-5"
                />
              ) : runs.length === 0 ? (
                filters.rated === "down" ? (
                  <ListCardEmpty
                    icon={ThumbsDown}
                    title={t("noRunsRatedDown")}
                    description={t("nothingHereWasRatedDown")}
                  />
                ) : narrowed ? (
                  // The filters emptied it, not the organization: "no runs"
                  // over a narrowed list reads as a history that never happened.
                  <ListCardEmpty
                    icon={Activity}
                    title={t("noRunsMatch")}
                    description={t("loosenAFilterAbove")}
                  />
                ) : (
                  // The window is always a narrowing too - an organization
                  // whose runs are all older than it must not be told nothing
                  // has ever run.
                  <ListCardEmpty
                    icon={Activity}
                    title={t("noRunsInWindow")}
                    description={t("widenTheWindowAbove")}
                  />
                )
              ) : (
                <>
                  <RunTable
                    fillHeight
                    runs={runs}
                    sort={sort}
                    onSort={changeSort}
                    // The open row closes rather than reopening itself: a row
                    // that is already the panel's subject is the one somebody
                    // clicks to put the panel away.
                    onOpen={(run) => onFocusRun(run.id === focusedRunId ? null : run.id)}
                    openRunId={focusedRunId}
                    agentsById={canAgents ? agentsById : undefined}
                    membersById={membersById}
                  />
                  <ListCardFootRow className="shrink-0">
                    <PaginationBar
                      page={page}
                      pageSize={PAGE_SIZE}
                      total={total}
                      isLoading={isLoading}
                      onPage={(next) => setPaging({ key: narrowingKey, page: next })}
                    />
                  </ListCardFootRow>
                </>
              )}
            </>
          }
        </CardContent>
      </Card>
    </div>
  );
}
