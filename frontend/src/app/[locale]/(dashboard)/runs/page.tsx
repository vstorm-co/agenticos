"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/dashboard/page-header";
import { PeriodControl } from "@/components/dashboard/period-control";
import { ActivityFigures } from "@/components/runs/activity-figures";
import { ApprovalsTab } from "@/components/runs/approvals-tab";
import { FocusedRun } from "@/components/runs/focused-run";
import { RunHistoryTab } from "@/components/runs/run-history-tab";
import { SpendTab } from "@/components/runs/spend-tab";
import { LoadingState } from "@/components/states";
import {
  Badge,
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { useApprovals, usePermissions, useUrlState } from "@/hooks";
import { formatPeriodParam, parsePeriodParam, type Period } from "@/lib/dashboard/period";
import { parseRunFilters, writeRunFilters, type RunFilters } from "@/lib/runs/filter-params";
import { setUrlParam } from "@/lib/utils";
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

  return (
    <div className="space-y-6">
      <PageHeader title={t("activity2")} description={t("whatYourAgentsDid2")} />

      <PeriodControl period={period} onChange={changePeriod} />

      {/* Not until the permission set has answered. `Tabs` is uncontrolled, so
          Radix captures `defaultValue` on first mount and never reads it again -
          mounted while `can()` still answers `false` for everything, the strip
          opens on Runs and stays there even once the Approvals tab appears
          beside it. The strip's *shape* depends on this permission, so drawing
          it before the answer arrives is guessing at it. The figures wait with
          it: mounted early they would draw their no-access state at a holder
          whose `can()` simply has not answered yet. */}
      {permissionsLoading ? (
        <LoadingState variant="skeleton-table" columns={6} rows={6} />
      ) : (
        <>
          <div data-tour="activity-overview">
            <ActivityFigures canView={canView} canDecide={canDecide} period={period} />
          </div>
          <Tabs defaultValue="runs">
            <TabsList>
              {/* Runs first: the page's main question is what ran. The queue
                keeps its count badge, so what is waiting is visible from the
                strip without opening it. */}
              <TabsTrigger value="runs" data-tour="activity-tab-runs">
                {t("runs2")}
              </TabsTrigger>
              {canDecide && (
                <TabsTrigger value="approvals" data-tour="activity-tab-approvals">
                  {t("approvals")}
                  {waiting > 0 && (
                    <Badge variant="secondary" className="ml-2">
                      {waiting}
                    </Badge>
                  )}
                </TabsTrigger>
              )}
              <TabsTrigger value="spend" data-tour="activity-tab-spend">
                {t("spend")}
              </TabsTrigger>
            </TabsList>

            {canDecide && (
              <TabsContent value="approvals" data-tour="activity-approvals">
                <ApprovalsTab period={period} onFocusRun={focusRun} />
              </TabsContent>
            )}

            <TabsContent value="runs" data-tour="activity-runs">
              {/* The export lives on the tab's control row, beside the filters it
                exports the result of - see RunHistoryTab. */}
              <RunHistoryTab
                agentId={agentId}
                period={period}
                filters={filters}
                onFiltersChange={changeFilters}
                onAgentChange={changeAgent}
                onFocusRun={focusRun}
                initialDurationSort={sortParam === "duration"}
              />
            </TabsContent>

            <TabsContent value="spend" data-tour="activity-spend">
              <SpendTab period={period} />
            </TabsContent>
          </Tabs>
        </>
      )}

      {/* The run detail, in a drawer over whichever tab opened it: a run row
          and an approval row are both doors to the same view, so the drawer
          belongs to the page rather than to one tab. `?run=` still deep-links
          here - the page opens with the drawer already out. */}
      <Sheet
        open={focusedRunId !== null}
        onOpenChange={(open) => {
          if (!open) focusRun(null);
        }}
      >
        <SheetContent side="right" className="w-full sm:max-w-3xl">
          <SheetHeader className="px-5">
            <SheetTitle className="text-sm">{t("runDetail")}</SheetTitle>
            <SheetClose onClick={() => focusRun(null)} />
          </SheetHeader>
          <div className="flex-1 overflow-y-auto p-5">
            {focusedRunId !== null && <FocusedRun runId={focusedRunId} onFocusRun={focusRun} />}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
