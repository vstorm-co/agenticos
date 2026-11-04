"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { ClipboardCheck } from "lucide-react";

import { Figure } from "@/components/ui";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import { formatShare } from "../format";
import type { DashboardWidgetProps } from "./types";
import { useWorkflowApprovalsSummary } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { formatElapsed } from "@/lib/utils";

/**
 * How people decided what the workflows the reader may see asked them over the
 * page's window: the share approved as proposed, how many were edited and by how
 * much, how long deciding took, and the five workflows asked most. Figures only -
 * no request's text reaches this card.
 */
export function ApprovalOutcomesWidget({
  title,
  hint,
  period,
  seeAll,
  options,
}: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.approval-outcomes");
  const locale = useLocale();
  const { summary, isLoading, error, refetch } = useWorkflowApprovalsSummary(
    period.from,
    period.to,
  );

  const share = (value: number | null) => (value === null ? "-" : formatShare(value, locale));

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error || !summary ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : summary.requests === 0 ? (
        <WidgetEmptyBody
          icon={ClipboardCheck}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <div className="flex flex-1 flex-col gap-4">
          <div className="grid grid-cols-3 gap-4">
            <Figure label={t("unchanged")} value={share(summary.unchanged_rate)} />
            <Figure
              label={t("edited")}
              value={summary.approved_edited.toLocaleString(locale)}
              caption={
                summary.edit_ratio_median !== null
                  ? t("editedCaption", { ratio: formatShare(summary.edit_ratio_median, locale) })
                  : summary.approved_edited > 0
                    ? t("notMeasured")
                    : undefined
              }
            />
            <Figure
              label={t("decideTime")}
              value={
                summary.decide_p50_seconds === null
                  ? "-"
                  : formatElapsed(summary.decide_p50_seconds * 1000)
              }
            />
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
                    {workflow.unchanged_rate === null
                      ? t("rowRequests", { requests: workflow.requests })
                      : t("row", {
                          requests: workflow.requests,
                          rate: formatShare(workflow.unchanged_rate, locale),
                        })}
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
