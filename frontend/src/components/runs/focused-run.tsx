"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Activity, ExternalLink } from "lucide-react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useDelegatedRuns, useRun } from "@/hooks";
import { ApiError } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { RunFeedback } from "./run-feedback";
import { RunTable } from "./run-table";

/**
 * One run and the delegations it made - where a link from elsewhere lands.
 *
 * It exists because a delegated run is not in run history: the list is top-level
 * only, so that its count and cost column agree with the month-to-date figure
 * beside them. A delegation panel in a chat holds the run id its terminal frame
 * carried, and this is the surface that id reaches.
 *
 * Both directions, because both are asked. Downwards it answers "what did this
 * run delegate", which is the query `agent_runs_parent_run_id_idx` was created
 * for. Upwards a delegated run links to the run it came from, so arriving at a
 * specialist's row is not a dead end - the parent is where its cost was charged.
 *
 * A refusal is said out loud rather than drawn as an empty table. Every other
 * page here renders its empty state when a query fails, which makes "this run
 * was deleted" and "the request answered 502" the same pixels.
 */
export function FocusedRun({ runId }: { runId: string }) {
  const t = useTranslations("pages.runs");
  const { run, isLoading, error } = useRun(runId);
  const { runs: delegated } = useDelegatedRuns(runId);

  if (isLoading) return <LoadingState variant="skeleton-table" columns={6} rows={2} />;
  if (run === undefined) {
    // Absent once the wait is over means the request did not answer, and the two
    // reasons do not read the same. A run that is gone - or in another tenant,
    // which the API answers identically and on purpose - is a fact about the
    // link. Anything else is a fact about the request, and saying "no such run"
    // for a refused permission sends somebody looking for a run that is there.
    return error instanceof ApiError && error.status === 404 ? (
      <EmptyState icon={Activity} title={t("noSuchRun")} description={t("theRunNamedIn")} />
    ) : (
      <ErrorState title={t("runCouldNotBeRead")} />
    );
  }

  return (
    <div className="space-y-3">
      {run.parent_run_id !== null && (
        <p className="text-muted-foreground text-xs">
          {t("thisRunWasDelegated")}{" "}
          <Link
            href={`${ROUTES.RUNS}?run=${run.parent_run_id}`}
            className="underline underline-offset-4"
          >
            {t("openTheRunItCame")}
          </Link>
        </p>
      )}

      {/* The trace, where one can be read. The URL is the single-run read's
          own field, resolved server-side because an agent may redirect its
          traces to a client's Logfire project - so this is a link only when
          there is genuinely somewhere to land, never a guess from the id. */}
      {run.logfire_url != null && (
        <p className="text-muted-foreground text-xs">
          <a
            href={run.logfire_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 underline underline-offset-4"
          >
            {t("openTheTraceInLogfire")}
            <ExternalLink className="h-3 w-3" aria-hidden />
          </a>
        </p>
      )}

      <RunTable runs={[run, ...delegated]} />

      {delegated.length > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("delegationsAlreadyCounted", { count: delegated.length })}
        </p>
      )}

      {/* Where the 👎 on the row above becomes readable: the answers people
          rated down in this run, and the words they left. */}
      <RunFeedback runId={runId} />
    </div>
  );
}
