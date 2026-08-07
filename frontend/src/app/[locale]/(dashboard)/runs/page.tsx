"use client";

import { useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/dashboard/page-header";
import { ActivityFigures } from "@/components/runs/activity-figures";
import { ApprovalsTab } from "@/components/runs/approvals-tab";
import { RunHistoryTab } from "@/components/runs/run-history-tab";
import { SpendTab } from "@/components/runs/spend-tab";
import { LoadingState } from "@/components/states";
import { Badge, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { useApprovals, usePermissions } from "@/hooks";
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
  // link a dead end dressed as a filter.
  const searchParams = useSearchParams();
  const agentId = searchParams.get("agent");
  // `?run=` is how a delegation panel in a chat hands over. A delegated run is
  // deliberately not in the top-level list - see `useRuns` - so the only way to
  // reach one is to name it, and `FocusedRun` is what answers.
  const focusedRunId = searchParams.get("run");
  const { can, isLoading: permissionsLoading } = usePermissions();
  // Reading the queue takes the same permission as deciding one - both routes
  // carry `require(Perm.APPROVALS_DECIDE)` - so for a caller without it there is
  // no queue to show, not an empty one. Asked anyway, the 403 arrived as `[]` and
  // the tab drew "Nothing waiting": a refusal rendered as reassurance, on the one
  // page whose job is to distinguish those.
  const canDecide = can(Perm.approvalsDecide);
  // Only for the count on the tab. The queue itself is `ApprovalsTab`'s, and both
  // read one query key, so this is the same request rather than a second one.
  const { approvals } = useApprovals({ enabled: canDecide });

  return (
    <div className="space-y-6">
      <PageHeader title={t("activity2")} description={t("whatYourAgentsDid2")} />

      <ActivityFigures canDecide={canDecide} />

      {/* Not until the permission set has answered. `Tabs` is uncontrolled, so
          Radix captures `defaultValue` on first mount and never reads it again -
          mounted while `can()` still answers `false` for everything, the strip
          opens on Runs and stays there even once the Approvals tab appears
          beside it. The strip's *shape* depends on this permission, so drawing
          it before the answer arrives is guessing at it. */}
      {permissionsLoading ? (
        <LoadingState variant="skeleton-table" columns={6} rows={6} />
      ) : (
        <Tabs defaultValue={canDecide ? "approvals" : "runs"}>
          <TabsList>
            {canDecide && (
              <TabsTrigger value="approvals">
                {t("approvals")}
                {approvals.length > 0 && (
                  <Badge variant="secondary" className="ml-2">
                    {approvals.length}
                  </Badge>
                )}
              </TabsTrigger>
            )}
            <TabsTrigger value="runs">{t("runs2")}</TabsTrigger>
            <TabsTrigger value="spend">{t("spend")}</TabsTrigger>
          </TabsList>

          {canDecide && (
            <TabsContent value="approvals">
              <ApprovalsTab />
            </TabsContent>
          )}

          <TabsContent value="runs">
            <RunHistoryTab agentId={agentId} focusedRunId={focusedRunId} />
          </TabsContent>

          <TabsContent value="spend">
            <SpendTab />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
