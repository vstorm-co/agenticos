"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Activity, ThumbsDown } from "lucide-react";

import { FocusedRun } from "@/components/runs/focused-run";
import { RunTable } from "@/components/runs/run-table";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { usePermissions, useRuns } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { getErrorMessage } from "@/lib/utils";
import { Perm } from "@/types/permissions";

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
  const { can } = usePermissions();
  const canView = can(Perm.runsView);
  const [ratedDown, setRatedDown] = useState(false);
  const { runs, isLoading, error, refetch } = useRuns(agentId ?? undefined, {
    rated: ratedDown ? "down" : undefined,
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1.5">
            <CardTitle>{t("runHistory2")}</CardTitle>
            <CardDescription>
              Every run records the agent <em>{t("version")}</em>
              {t("executedSoWhatHappened")}
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
        ) : isLoading ? (
          <LoadingState variant="skeleton-table" columns={6} rows={6} />
        ) : error ? (
          <ErrorState
            title={t("runHistoryCouldNot")}
            description={getErrorMessage(error, t("theseRunsHappenedThe"))}
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
            <EmptyState icon={Activity} title={t("noRunsYet")} description={t("nothingHasRun")} />
          )
        ) : (
          <RunTable runs={runs} />
        )}
      </CardContent>
    </Card>
  );
}
