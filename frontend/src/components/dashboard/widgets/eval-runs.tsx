"use client";

import Link from "next/link";
import { FlaskConical } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { EvalStatusBadge } from "@/components/evals/eval-status-badge";
import { percent } from "@/components/evals/format";
import { useRecentEvalRuns } from "@/hooks/use-eval-runs";
import { ROUTES } from "@/lib/constants";
import type { EvalRun, EvalRunStatus } from "@/types/eval-runs";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many a card lists; each agent's Evals tab has the rest. */
const SHOWN = 6;

/** The statuses the breakdown counts, in the order a reader scans them. */
const COUNTED: EvalRunStatus[] = ["running", "completed", "failed", "budget_exceeded"];

function passRate(run: EvalRun): number | null {
  return run.arms.find((arm) => arm.role === "candidate")?.summary.pass_rate ?? null;
}

/**
 * The organization's latest eval runs: how many are running, finished or
 * stopped, and for each its dataset, its pass rate and its status - one click
 * from the run's own page.
 */
export function EvalRunsWidget({ title, hint, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.eval-runs");
  const locale = useLocale();
  const { runs, isLoading, error, refetch } = useRecentEvalRuns(SHOWN);
  const counts = COUNTED.map((status) => ({
    status,
    count: runs.filter((run) => run.status === status).length,
  })).filter(({ count }) => count > 0);

  return (
    <WidgetFrame title={title} hint={hint} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : runs.length === 0 ? (
        <WidgetEmptyBody
          icon={FlaskConical}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <div className="space-y-2">
          <p className="text-muted-foreground flex flex-wrap gap-x-3 text-xs">
            {counts.map(({ status, count }) => (
              <span key={status}>{t(`count.${status}`, { count })}</span>
            ))}
          </p>
          <ul className="divide-border divide-y">
            {runs.map((run) => (
              <li key={run.id}>
                <Link
                  href={`${ROUTES.AGENTS}/${run.agent_id}/evals/${run.id}`}
                  className="hover:bg-accent/40 flex items-center justify-between gap-3 rounded-md px-1 py-2"
                >
                  <span className="text-foreground truncate text-sm">
                    {t("run", { dataset: run.dataset_name, version: run.dataset_version })}
                  </span>
                  <span className="flex shrink-0 items-center gap-2 text-xs">
                    <span className="tabular-nums">{percent(passRate(run), locale)}</span>
                    <EvalStatusBadge status={run.status} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </WidgetFrame>
  );
}
