"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { CircleAlert, Workflow } from "lucide-react";

import { Figure } from "@/components/ui";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import { formatUsd } from "../format";
import type { DashboardWidgetProps } from "./types";
import { useWorkflowsSummary } from "@/hooks";
import { ROUTES } from "@/lib/constants";

/**
 * What the workflows the reader may see did over the page's window: how many
 * real runs, how many failed, what they cost, and the busiest five - plus, ahead
 * of all of it, how many runs are waiting on a person right now. That last count
 * ignores the window on purpose: an approval asked for last month still blocks
 * its run today.
 */
export function WorkflowsWidget({ title, hint, period, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.workflows");
  const { summary, isLoading, error, refetch } = useWorkflowsSummary(period.from, period.to);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error || !summary ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : summary.runs === 0 && summary.needs_you === 0 ? (
        <WidgetEmptyBody
          icon={Workflow}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <div className="flex flex-1 flex-col gap-4">
          {summary.needs_you > 0 ? (
            <Link
              href={ROUTES.WORKFLOW_ALL_RUNS}
              className="bg-warning/10 text-warning hover:bg-warning/15 flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium"
            >
              <CircleAlert className="size-4 shrink-0" aria-hidden />
              {t("needsYou", { count: summary.needs_you })}
            </Link>
          ) : null}
          <div className="grid grid-cols-3 gap-4">
            <Figure
              label={t("runs")}
              value={summary.runs.toLocaleString()}
              caption={t("succeeded", { count: summary.succeeded })}
            />
            <Figure label={t("failed")} value={summary.failed.toLocaleString()} />
            <Figure label={t("cost")} value={formatUsd(summary.cost_usd)} />
          </div>
          <ul className="divide-border divide-y">
            {summary.workflows.map((workflow) => (
              <li key={workflow.id}>
                <Link
                  href={ROUTES.WORKFLOW_RUNS(workflow.id)}
                  className="hover:bg-accent flex items-center justify-between gap-3 py-1.5 text-sm"
                >
                  <span className="truncate">{workflow.name}</span>
                  <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
                    {workflow.failed > 0
                      ? t("rowFailed", { runs: workflow.runs, failed: workflow.failed })
                      : t("row", { runs: workflow.runs })}
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
