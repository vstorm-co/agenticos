"use client";

import { Activity, ShieldCheck, Wallet } from "lucide-react";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/dashboard/page-header";
import { PeriodControl } from "@/components/dashboard/period-control";
import { ApprovalsTab } from "@/components/runs/approvals-tab";
import { WorkflowApprovalsCard } from "@/components/runs/workflow-approvals-card";
import { RunDetailPanel } from "@/components/runs/run-detail-panel";
import { RunHistoryTab } from "@/components/runs/run-history-tab";
import { SpendTab } from "@/components/runs/spend-tab";
import { LoadingState } from "@/components/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import {
  useApprovals,
  usePermissions,
  useRuns,
  useSpend,
  useUrlState,
  useWorkflowApprovals,
} from "@/hooks";
import { useUrlOverlay } from "@/hooks/use-url-state";
import { periodEnd, periodStart } from "@/lib/dashboard/period";
import { formatPeriodParam, parsePeriodParam, type Period } from "@/lib/dashboard/period";
import { PAGE_CLEARANCE } from "@/lib/page-clearance";
import {
  parseRunFilters,
  parseRunsTab,
  writeRunFilters,
  type RunFilters,
} from "@/lib/runs/filter-params";
import { cn, setUrlParam } from "@/lib/utils";
import { Perm } from "@/types/permissions";
import { useLocale, useTranslations } from "next-intl";

/**
 * What the agents did: three figures, and the tabs that each answer separately -
 * the run history, the approvals queue when the caller may decide one, and spend.
 *
 * The page owns only what is genuinely shared - which query parameters narrowed
 * it, and the permission that decides whether there is an approvals queue at all.
 * Everything else fetches its own rows and draws its own loading, empty and
 * failed states, which is the only arrangement in which "nothing is waiting" and
 * "we could not ask" stay different sentences. A page holding every query has one
 * loading flag and one empty state to spend across four concerns, and the
 * reassuring reading is the one that wins by default.
 */
/**
 * A figure on a tab: how many runs, how much spent, how many are waiting.
 *
 * Its own pill rather than a bare number, because a bare one reads as part of
 * the tab's label - "Runs 189" is a tab called Runs 189 - and its own ground
 * rather than `bg-secondary`, which is the *active* tab's background too and so
 * disappeared on whichever tab was open. Tabular figures so switching windows
 * does not shuffle the strip sideways.
 */
function TabCount({ children }: { children: React.ReactNode }) {
  return (
    <span className="bg-foreground/10 text-foreground/80 ml-2 rounded-full px-2 py-0.5 text-xs font-medium tabular-nums">
      {children}
    </span>
  );
}

export default function RunsPage() {
  const t = useTranslations("pages.runs");
  const locale = useLocale();
  // `?agent=` is how the Builder hands over. Its Recent runs panel answers the
  // summary question and links here for the detail, and arriving at the whole
  // organization's history after clicking through from one agent would make the
  // link a dead end dressed as a filter. The filter bar can change it too, so
  // it is state mirrored into the URL, like the period below.
  const searchParams = useSearchParams();
  const [agentId, changeAgent] = useUrlState("agent");
  // `?run=` is how a delegation panel in a chat hands over. A delegated run is
  // deliberately not in the top-level list - see `useRuns` - so the only way to
  // reach one is to name it, and `FocusedRun` is what answers. A row in the
  // table opens the same view, which is why this too is state and not only a
  // parameter somebody arrives with.
  const [focusedRunId, runView] = useUrlOverlay("run");
  const focusRun = (id: string | null) => (id === null ? runView.close() : runView.open(id));
  // The dashboard's p95 figure links here sorted by duration over the same
  // window - the number and the runs behind it, one click apart. The sort
  // arrives as `?sort=`, the window as `?period=` below.
  const sortParam = searchParams.get("sort");
  // The page's one window, shared by the figures, all three tabs and the
  // exports - the same `?period=` vocabulary the dashboard round-trips, so a
  // narrowed view survives a reload and travels in a pasted link.
  const [period, setPeriod] = useState<Period>(() => parsePeriodParam(searchParams.get("period")));
  const changePeriod = (next: Period) => {
    setPeriod(next);
    setUrlParam("period", formatPeriodParam(next));
  };
  // Every narrowing the run history offers, mirrored into the URL like the
  // window above it. It is the page's rather than the tab's for the reason
  // `agent` and `run` are: a component that reaches for the URL itself can only
  // be used on the page whose URL it knows. And it is in the URL at all so that
  // a card counting one slice can link to *those runs* - the dashboard says
  // Mattermost 31 and used to be able to offer only all 58 (#768).
  const [filters, setFilters] = useState<RunFilters>(() =>
    parseRunFilters(new URLSearchParams(searchParams.toString())),
  );
  const changeFilters = (next: RunFilters) => {
    setFilters(next);
    writeRunFilters(next);
  };
  // Which tab is open, mirrored into `?tab=` like everything else the page
  // narrows itself with. Addressable at all for the first time here: the alert
  // that says a run is parked has to send somebody to the decision, and until
  // the queue had a URL the only honest link was the agent's Builder page
  // (#935). Resolved against the permission below rather than trusted, so a
  // link naming a tab the reader may not open lands on one they may.
  const [tabParam, changeTab] = useUrlState("tab");
  const { can, isLoading: permissionsLoading } = usePermissions();
  // Run history and spend take `runs:view` - `GET /runs` and `GET /spend` both
  // carry it - so a caller without it is not asked for: the figures and the
  // history tab disable their queries and say whose decision the absence is,
  // instead of firing two predictable 403s and drawing them as failures.
  const canView = can(Perm.runsView);
  // Reading the queue takes the same permission as deciding one - both routes
  // carry `require(Perm.APPROVALS_DECIDE)` - so for a caller without it there is
  // no queue to show, not an empty one. Asked anyway, the 403 arrived as `[]` and
  // the tab drew "Nothing waiting": a refusal rendered as reassurance, on the one
  // page whose job is to distinguish those.
  const canDecide = can(Perm.approvalsDecide);
  // Only for the count on the tab. The queue itself is `ApprovalsTab`'s, and both
  // read one query key, so this is the same request rather than a second one.
  // `total` rather than the page's length: the endpoint answers fifty rows at a
  // time, and a badge that stops at fifty is a badge that stops being a count.
  const { total: toolsWaiting } = useApprovals({ enabled: canDecide });
  // Workflow steps waiting on a person are the same queue to the reader.
  const { total: stepsWaiting } = useWorkflowApprovals({ enabled: canDecide });
  const waiting = toolsWaiting + stepsWaiting;
  // The two figures that were three cards above the strip. On the tab they name
  // instead: a card of one number is a lot of the page's height for something a
  // badge says, and the height mattered - the three of them cost about 380px, so
  // a 900px viewport left the table three rows deep under them.
  const range = { from: periodStart(period), to: periodEnd(period) };
  // One control, drawn first among the open tab's filters: the window narrows
  // every tab, so each carries it where its other filters are.
  const periodControl = <PeriodControl period={period} onChange={changePeriod} variant="menu" />;
  const { total: runCount } = useRuns(undefined, {
    startedFrom: range.from,
    startedTo: range.to,
    enabled: canView,
  });
  const { spend } = useSpend(range, { enabled: canView });
  const listColumn = useRef<HTMLDivElement>(null);
  // The list scrolls inside its own column while a run is open, so the row
  // that opened it is brought into that column's view rather than left where
  // the page's scroll had it.
  useEffect(() => {
    if (focusedRunId === null) return;
    listColumn.current
      ?.querySelector('[aria-selected="true"]')
      ?.scrollIntoView?.({ block: "nearest" });
  }, [focusedRunId]);
  const spent = (spend?.by_agent ?? []).reduce((sum, row) => sum + Number(row.cost_usd), 0);

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col", PAGE_CLEARANCE)}>
      <PageHeader
        className="mb-4 shrink-0"
        title={t("activity2")}
        description={t("whatYourAgentsDid2")}
      />

      {/* Not until the permission set has answered. The strip's *shape* depends
          on this permission - whether there is an Approvals tab at all - so
          drawing it before the answer arrives is guessing at it, and a link
          carrying `?tab=approvals` would resolve against a `can()` that has
          simply not answered yet and open the run history instead. The badges
          wait with it, for the second half of that reason. */}
      {permissionsLoading ? (
        <LoadingState variant="pending" />
      ) : (
        <>
          <Tabs
            value={parseRunsTab(tabParam, canDecide)}
            className="flex min-h-0 flex-1 flex-col"
            onValueChange={(next) => {
              // `null` for the default, so switching back to Runs leaves no
              // `?tab=runs` behind: an unset narrowing writes nothing on this
              // page, which is what makes a pasted link carry only what it
              // actually narrows.
              changeTab(next === "runs" ? null : next);
              // A focused run belongs to the tab that opened it. Left alone it
              // sat beside a queue it has nothing to do with, and below `lg`
              // it *replaced* the list - so the strip was live while every
              // tab's content stayed hidden and switching appeared to do
              // nothing at all (#934).
              runView.replace(null);
            }}
          >
            <TabsList className="shrink-0" data-tour="activity-overview">
              {/* Runs first: the page's main question is what ran. The queue
                  keeps its count badge, so what is waiting is visible from the
                  strip without opening it. */}
              <TabsTrigger value="runs" data-tour="activity-tab-runs">
                <Activity className="size-4 shrink-0" aria-hidden />
                {t("runs2")}
                {runCount > 0 && <TabCount>{runCount.toLocaleString(locale)}</TabCount>}
              </TabsTrigger>
              {canDecide && (
                <TabsTrigger value="approvals" data-tour="activity-tab-approvals">
                  <ShieldCheck className="size-4 shrink-0" aria-hidden />
                  {t("approvals")}
                  {waiting > 0 && <TabCount>{waiting}</TabCount>}
                </TabsTrigger>
              )}
              <TabsTrigger value="spend" data-tour="activity-tab-spend">
                <Wallet className="size-4 shrink-0" aria-hidden />
                {t("spend")}
                {spent > 0 && <TabCount>{`$${spent.toFixed(2)}`}</TabCount>}
              </TabsTrigger>
            </TabsList>

            {/* Both panes fill the available viewport. Rows keep their natural
                height while the table's scroll region absorbs spare space. */}
            <div className="mt-2 flex min-h-0 flex-1 items-stretch gap-4">
              <div
                className={cn(
                  "flex min-h-0 min-w-0 flex-1 scrollbar-thin flex-col overflow-auto",
                  focusedRunId !== null && "hidden lg:flex",
                )}
                ref={listColumn}
              >
                {canDecide && (
                  <TabsContent
                    value="approvals"
                    data-tour="activity-approvals"
                    className="mt-0 min-h-0 flex-1 flex-col data-[state=active]:flex"
                  >
                    <div className="space-y-4">
                      <WorkflowApprovalsCard />
                      <ApprovalsTab
                        period={period}
                        onFocusRun={focusRun}
                        periodControl={periodControl}
                      />
                    </div>
                  </TabsContent>
                )}

                <TabsContent
                  value="runs"
                  data-tour="activity-runs"
                  className="mt-0 min-h-0 flex-1 flex-col data-[state=active]:flex"
                >
                  {/* The export lives on the tab's control row, beside the
                      filters it exports the result of - see RunHistoryTab. */}
                  <RunHistoryTab
                    periodControl={periodControl}
                    agentId={agentId}
                    period={period}
                    filters={filters}
                    onFiltersChange={changeFilters}
                    onAgentChange={changeAgent}
                    onFocusRun={focusRun}
                    focusedRunId={focusedRunId}
                    initialDurationSort={sortParam === "duration"}
                  />
                </TabsContent>

                <TabsContent value="spend" data-tour="activity-spend" className="mt-0">
                  <SpendTab period={period} periodControl={periodControl} />
                </TabsContent>
              </div>

              {/* The panel belongs to the page rather than to one tab: a run row
                  and an approval row are both doors to the same view. `?run=`
                  still deep-links here - the page opens with it already out. */}
              {focusedRunId !== null && (
                <div className="h-full min-h-0 w-full shrink-0 lg:w-auto">
                  <RunDetailPanel runId={focusedRunId} onFocusRun={focusRun} />
                </div>
              )}
            </div>
          </Tabs>
        </>
      )}
    </div>
  );
}
