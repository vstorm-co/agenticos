"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/dashboard/page-header";
import { PeriodControl } from "@/components/dashboard/period-control";
import { ApprovalsTab } from "@/components/runs/approvals-tab";
import { RunDetailPanel } from "@/components/runs/run-detail-panel";
import { RunHistoryTab } from "@/components/runs/run-history-tab";
import { SpendTab } from "@/components/runs/spend-tab";
import { LoadingState } from "@/components/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { useApprovals, usePermissions, useRuns, useSpend, useUrlState } from "@/hooks";
import { periodEnd, periodStart } from "@/lib/dashboard/period";
import { formatPeriodParam, parsePeriodParam, type Period } from "@/lib/dashboard/period";
import { PAGE_CLEARANCE } from "@/lib/page-clearance";
import { parseRunFilters, writeRunFilters, type RunFilters } from "@/lib/runs/filter-params";
import { cn, setUrlParam } from "@/lib/utils";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

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
    <span className="bg-foreground/10 text-foreground/80 ml-2 rounded-full px-2 py-0.5 text-[11px] font-medium tabular-nums">
      {children}
    </span>
  );
}

export default function RunsPage() {
  const t = useTranslations("pages.runs");
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
  const [focusedRunId, focusRun] = useUrlState("run");
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
  const { total: waiting } = useApprovals({ enabled: canDecide });
  // The two figures that were three cards above the strip. On the tab they name
  // instead: a card of one number is a lot of the page's height for something a
  // badge says, and the height mattered - the three of them cost about 380px, so
  // a 900px viewport left the table three rows deep under them.
  const range = { from: periodStart(period), to: periodEnd(period) };
  const { total: runCount } = useRuns(undefined, {
    startedFrom: range.from,
    startedTo: range.to,
    enabled: canView,
  });
  const { spend } = useSpend(range, { enabled: canView });
  const spent = (spend?.by_agent ?? []).reduce((sum, row) => sum + Number(row.cost_usd), 0);

  return (
    // An ordinary page that scrolls, not a full-height column with panes that
    // scroll apart. That arrangement bought sticky column headers and cost the
    // table its rows: the figures and the period control took about 380px, so a
    // 900px viewport left a run history three rows deep inside its own scroll
    // box - a second scrollbar to reach what the page had room for all along.
    <div className="flex flex-col">
      {/* `mb-4` rather than the header's own `mb-6 md:mb-8`: the window control
          belongs *to* the heading above it - everything below is what it filters -
          and two centimetres of white between a title and its own filter reads as
          two unrelated bands. The room goes below the dates instead, where the
          break actually is. */}
      <PageHeader title={t("activity2")} description={t("whatYourAgentsDid2")} className="mb-4" />

      <div className="mb-6">
        <PeriodControl period={period} onChange={changePeriod} />
      </div>

      {/* Not until the permission set has answered. `Tabs` is uncontrolled, so
          Radix captures `defaultValue` on first mount and never reads it again -
          mounted while `can()` still answers `false` for everything, the strip
          opens on Runs and stays there even once the Approvals tab appears
          beside it. The strip's *shape* depends on this permission, so drawing
          it before the answer arrives is guessing at it. The badges wait with
          it: mounted early they would count against a `can()` that simply has
          not answered yet. */}
      {permissionsLoading ? (
        <LoadingState variant="skeleton-table" columns={6} rows={6} />
      ) : (
        <>
          <Tabs
            defaultValue="runs"
            className="flex min-h-0 flex-1 flex-col"
            onValueChange={() => focusRun(null)}
          >
            <TabsList className="shrink-0" data-tour="activity-overview">
              {/* Runs first: the page's main question is what ran. The queue
                  keeps its count badge, so what is waiting is visible from the
                  strip without opening it. */}
              <TabsTrigger value="runs" data-tour="activity-tab-runs">
                {t("runs2")}
                {runCount > 0 && <TabCount>{runCount.toLocaleString()}</TabCount>}
              </TabsTrigger>
              {canDecide && (
                <TabsTrigger value="approvals" data-tour="activity-tab-approvals">
                  {t("approvals")}
                  {waiting > 0 && <TabCount>{waiting}</TabCount>}
                </TabsTrigger>
              )}
              <TabsTrigger value="spend" data-tour="activity-tab-spend">
                {t("spend")}
                {spent > 0 && <TabCount>{`$${spent.toFixed(2)}`}</TabCount>}
              </TabsTrigger>
            </TabsList>

            {/* Two columns above `lg`: the tab's own panel narrows and the run
                detail takes the right-hand side. Inside the tabs rather than
                around them, and the row owns the gap under the strip while each
                panel gives up the `mt-2` `TabsContent` applies - otherwise the
                card starts eight pixels below the panel beside it. Below `lg`
                there is room for one column, so the focused run replaces the
                list rather than squeezing beside it.

                `items-start`, so the shorter of the two columns is its own
                height rather than stretched to match the other: a run detail
                beside a three-row table used to be a card of white space. */}
            <div className="mt-2 flex items-start gap-4">
              <div
                className={cn(
                  // `overflow-hidden` is load-bearing: the run table carries a
                  // minimum width of its own, and without a clip here it ran on
                  // underneath the detail panel rather than scrolling inside its
                  // own column.
                  "min-w-0 flex-1 overflow-hidden",
                  // The room under this page, declared here rather than by
                  // `PageTransition` - which is where every other page gets it.
                  // Padding on the box *around* this row shortens what the
                  // sticky panel beside it may pin in, because a sticky box is
                  // clamped to its containing block: 64px of it put the panel's
                  // top at -48px at maximum scroll, cutting its own header off
                  // by 56px. Inside the column it lands under the last row and
                  // the row still ends at the viewport (#1206).
                  PAGE_CLEARANCE,
                  focusedRunId !== null && "hidden lg:block",
                )}
              >
                {canDecide && (
                  <TabsContent
                    value="approvals"
                    data-tour="activity-approvals"
                    className="mt-0 min-h-0 flex-1 overflow-y-auto"
                  >
                    <ApprovalsTab period={period} onFocusRun={focusRun} />
                  </TabsContent>
                )}

                <TabsContent value="runs" data-tour="activity-runs" className="mt-0">
                  {/* The export lives on the tab's control row, beside the
                      filters it exports the result of - see RunHistoryTab. */}
                  <RunHistoryTab
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
                  <SpendTab period={period} />
                </TabsContent>
              </div>

              {/* The panel belongs to the page rather than to one tab: a run row
                  and an approval row are both doors to the same view. `?run=`
                  still deep-links here - the page opens with it already out. */}
              {focusedRunId !== null && (
                // Sticky *and* bounded to the scrollport, which has to be both:
                // sticky alone left a panel taller than the window hanging past
                // it, so its own header - the agent, the status, the cost - was
                // scrolled off above and the timeline had to be scrolled back up
                // to read. A sticky element taller than the viewport pins at its
                // top edge and no more.
                //
                // A definite height rather than a cap, because `RunDetailPanel`
                // is `h-full` over `FocusedRun`'s one scrolling column: with only
                // a `max-height` the percentage resolves against auto, the chain
                // grows past the cap and `overflow-hidden` clips the timeline
                // instead of scrolling it. `dvh` so mobile browser chrome is not
                // counted twice.
                //
                // The offset is negative, and the arithmetic is the point: a
                // sticky top is measured from the scroll container's *padding*
                // edge, and `main` carries `pt-4 sm:pt-8`. So a plain `top-4`
                // pinned the panel 48px down the window while the table's rows
                // scrolled past above it - the panel read as hanging in the
                // middle of a moving column. Cancelling that padding and adding
                // 8px back puts its top edge 8px from the window at either
                // breakpoint, with nothing scrolling above it.
                //
                // `-mr-4` is the same trick sideways, and only where there are two
                // columns: `main`'s `sm:px-6` plus its scrollbar left about forty
                // pixels of nothing to the right of the panel while the table ran
                // flush to the left edge. Sixteen of those are given back, which
                // matches the eight above and below.
                //
                // The height counts the mobile tab bar below `lg`, where the
                // list column is hidden and this is the only column: the bar is
                // `fixed bottom-0`, `min-h-[56px]` plus the safe-area inset, so
                // a flat `100dvh-1rem` put the panel's last 56px behind it -
                // measured at 390x780. Above `lg` the bar is `lg:hidden` and the
                // full height is right.
                <div className="sticky top-[calc(0.5rem-1rem)] h-[calc(100dvh-1rem-3.5rem-env(safe-area-inset-bottom))] self-start sm:top-[calc(0.5rem-2rem)] lg:-mr-4 lg:h-[calc(100dvh-1rem)]">
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
