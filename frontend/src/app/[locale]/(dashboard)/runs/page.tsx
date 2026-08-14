"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/dashboard/page-header";
import { PeriodControl } from "@/components/dashboard/period-control";
import { ActivityFigures } from "@/components/runs/activity-figures";
import { ApprovalsTab } from "@/components/runs/approvals-tab";
import { ExportMenu } from "@/components/runs/export-menu";
import { RunHistoryTab } from "@/components/runs/run-history-tab";
import { SpendTab } from "@/components/runs/spend-tab";
import { LoadingState } from "@/components/states";
import { Badge, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { useApprovals, usePermissions } from "@/hooks";
import {
  formatPeriodParam,
  parsePeriodParam,
  periodEnd,
  periodStart,
  type Period,
} from "@/lib/dashboard/period";
import { setUrlParam } from "@/lib/utils";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

/**
 * What the agents did: three figures, and three tabs that each answer separately.
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
  const agentParam = searchParams.get("agent");
  // A navigation can change `?agent=` under the state - the focused-run notice
  // links to a bare /runs - and the two must not disagree about the narrowing,
  // so the param seen last is stored beside the value and a fresh param wins
  // (the render-time adjustment React documents, not an effect).
  const [agent, setAgent] = useState<{ seenParam: string | null; value: string | null }>({
    seenParam: agentParam,
    value: agentParam,
  });
  if (agent.seenParam !== agentParam) {
    setAgent({ seenParam: agentParam, value: agentParam });
  }
  const agentId = agent.seenParam === agentParam ? agent.value : agentParam;
  const changeAgent = (next: string | null) => {
    setAgent({ seenParam: agentParam, value: next });
    setUrlParam("agent", next);
  };
  // `?run=` is how a delegation panel in a chat hands over. A delegated run is
  // deliberately not in the top-level list - see `useRuns` - so the only way to
  // reach one is to name it, and `FocusedRun` is what answers.
  const focusedRunId = searchParams.get("run");
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
  const { can, isLoading: permissionsLoading } = usePermissions();
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

      <ActivityFigures canDecide={canDecide} period={period} />

      {/* Not until the permission set has answered. `Tabs` is uncontrolled, so
          Radix captures `defaultValue` on first mount and never reads it again -
          mounted while `can()` still answers `false` for everything, the strip
          opens on Runs and stays there even once the Approvals tab appears
          beside it. The strip's *shape* depends on this permission, so drawing
          it before the answer arrives is guessing at it. */}
      {permissionsLoading ? (
        <LoadingState variant="skeleton-table" columns={6} rows={6} />
      ) : (
        <Tabs defaultValue={sortParam ? "runs" : canDecide ? "approvals" : "runs"}>
          <TabsList>
            {canDecide && (
              <TabsTrigger value="approvals">
                {t("approvals")}
                {waiting > 0 && (
                  <Badge variant="secondary" className="ml-2">
                    {waiting}
                  </Badge>
                )}
              </TabsTrigger>
            )}
            <TabsTrigger value="runs">{t("runs2")}</TabsTrigger>
            <TabsTrigger value="spend">{t("spend")}</TabsTrigger>
          </TabsList>

          {canDecide && (
            <TabsContent value="approvals">
              {/* Export the record for whatever window, gated on the same
                  permission the tab is - absent, not disabled, without it. */}
              <div className="mb-3 flex justify-end">
                <ExportMenu
                  permission={Perm.approvalsDecide}
                  endpoint="/approvals/export"
                  kind="approvals"
                  rangeParams={{ from: "created_from", to: "created_to" }}
                  range={{ from: periodStart(period), to: periodEnd(period) }}
                />
              </div>
              <ApprovalsTab />
            </TabsContent>
          )}

          <TabsContent value="runs">
            {/* The export lives inside the history card, beside the filters it
                exports the result of - see RunHistoryTab. */}
            <RunHistoryTab
              agentId={agentId}
              focusedRunId={focusedRunId}
              period={period}
              onAgentChange={changeAgent}
              initialDurationSort={sortParam === "duration"}
            />
          </TabsContent>

          <TabsContent value="spend">
            <div className="mb-3 flex justify-end">
              <ExportMenu
                permission={Perm.runsView}
                endpoint="/spend/export"
                kind="spend"
                rangeParams={{ from: "from", to: "to" }}
                range={{ from: periodStart(period), to: periodEnd(period) }}
              />
            </div>
            <SpendTab period={period} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
