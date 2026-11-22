"use client";

import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { RunStatusBadge } from "@/components/agents/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useRuns } from "@/hooks/use-runs";
import { ROUTES } from "@/lib/constants";
import { formatDateTime, timeAgo } from "@/lib/utils";
import type { RunStatus } from "@/types/runs";

const NEEDS_ATTENTION: ReadonlySet<RunStatus> = new Set([
  "awaiting_approval",
  "awaiting_answer",
  "failed",
  "budget_exceeded",
  "guardrail_blocked",
  "loop_stopped",
]);

/** The latest work before configuration; the caller must hold runs:view. */
export function AgentRecentWork({ agentId }: { agentId: string }) {
  const t = useTranslations("pages.runs");
  const common = useTranslations("common");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const { runs, isLoading, error, refetch } = useRuns(agentId);
  // Keep the scope honest: only the latest three runs, with problems first inside that set.
  const recent = runs
    .slice(0, 3)
    .toSorted(
      (a, b) => Number(NEEDS_ATTENTION.has(b.status)) - Number(NEEDS_ATTENTION.has(a.status)),
    );

  return (
    <section aria-label={t("recentWork")} className="space-y-2 border-b pb-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-medium">{t("recentWork")}</h2>
        <Link
          href={`${ROUTES.RUNS}?agent=${encodeURIComponent(agentId)}`}
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline-offset-4 hover:underline"
        >
          {t("runHistory2")}
          <ArrowUpRight className="size-3.5" aria-hidden />
        </Link>
      </div>
      {isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : error ? (
        <div className="flex items-center gap-3 text-sm">
          <p className="text-muted-foreground">{t("runHistoryCouldNot")}</p>
          <button
            type="button"
            className="underline underline-offset-4"
            onClick={() => void refetch()}
          >
            {common("retry")}
          </button>
        </div>
      ) : recent.length === 0 ? (
        <p className="text-muted-foreground py-2 text-sm">{t("nobodyHasRunAnything")}</p>
      ) : (
        <ul className="divide-border divide-y">
          {recent.map((run) => (
            <li key={run.id}>
              <Link
                href={`${ROUTES.RUNS}?agent=${encodeURIComponent(agentId)}&run=${encodeURIComponent(run.id)}`}
                className="hover:bg-muted/40 focus-visible:ring-ring -mx-2 flex items-center gap-3 rounded-md px-2 py-2 text-sm focus-visible:ring-2 focus-visible:outline-none"
              >
                <RunStatusBadge status={run.status} />
                <span className="min-w-0 flex-1 truncate">
                  {run.preview || run.error || t("runDetail")}
                </span>
                {run.started_at && (
                  <time
                    dateTime={run.started_at}
                    title={formatDateTime(run.started_at, locale)}
                    className="text-muted-foreground shrink-0 text-xs"
                  >
                    {timeAgo(run.started_at, tTime, locale)}
                  </time>
                )}
                <ArrowUpRight className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
