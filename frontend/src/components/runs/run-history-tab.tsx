"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Activity } from "lucide-react";

import { FocusedRun } from "@/components/runs/focused-run";
import { RunTable } from "@/components/runs/run-table";
import { VersionStrip } from "@/components/runs/version-strip";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { useRuns } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { getErrorMessage } from "@/lib/utils";

/**
 * Run history, and whichever sentence says what it has been narrowed to.
 *
 * `agentId` and `focusedRunId` come in as props rather than being read here: they
 * are query parameters, and a component that reaches for the URL itself can only
 * ever be used on the page whose URL it knows. Nothing in here is aware of the
 * Activity page.
 *
 * A failed request is said out loud. `?run=` is delegated to `FocusedRun`, which
 * has its own two answers for a run that is gone versus a request that did not
 * arrive - and the difference matters more there, because a link brought somebody
 * to that run on purpose.
 */
export function RunHistoryTab({
  agentId,
  focusedRunId,
}: {
  agentId: string | null;
  focusedRunId: string | null;
}) {
  const t = useTranslations("pages.runs");
  const { runs, isLoading, error, refetch } = useRuns(agentId ?? undefined);

  return (
    <div className="space-y-4">
      {/* Narrowed to an agent, a per-version summary sits above the table - the
          builder's "did v4 behave better than v3" answered where the evidence
          is. Its completed share is the shared `completedShare`, so it reads as
          the same figure the dashboard's Outcomes donut shows (§8a.4). */}
      {agentId !== null && <VersionStrip agentId={agentId} />}
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
          ) : isLoading ? (
            <LoadingState variant="skeleton-table" columns={6} rows={6} />
          ) : error ? (
            <ErrorState
              title={t("runHistoryCouldNot")}
              description={getErrorMessage(error, t("theseRunsHappenedThe"))}
              cta={{ label: t("tryAgain"), onClick: () => void refetch() }}
            />
          ) : runs.length === 0 ? (
            <EmptyState icon={Activity} title={t("noRunsYet")} description={t("nothingHasRun")} />
          ) : (
            <RunTable runs={runs} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
