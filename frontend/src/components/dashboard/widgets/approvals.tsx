"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { useApprovals } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * Tool calls parked on a person. Review links to the queue rather than
 * deciding inline - a decision deserves the arguments in full, which the
 * runs page shows and a dashboard row cannot. This card earns its place by
 * being empty.
 */
export function ApprovalsWidget({ title, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.approvals");
  const tTime = useTranslations("time");
  const { approvals, total, isLoading, error, refetch } = useApprovals();

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : approvals.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <div className="flex h-full flex-col justify-between gap-2">
          <ul className="space-y-2">
            {approvals.slice(0, 3).map((approval) => (
              <li key={approval.id} className="flex items-center gap-3 text-sm">
                <span className="min-w-0 flex-1">
                  <span className="text-foreground block truncate">
                    {t("wants", { tool: approval.tool_id })}
                  </span>
                  {approval.created_at ? (
                    <span className="text-muted-foreground block text-xs">
                      {t("waiting", { ago: timeAgo(approval.created_at, tTime) })}
                    </span>
                  ) : null}
                </span>
                <Button asChild size="sm">
                  <Link href={ROUTES.RUNS}>{t("review")}</Link>
                </Button>
              </li>
            ))}
          </ul>
          {total > 3 ? (
            <p className="text-muted-foreground text-xs">{t("more", { count: total - 3 })}</p>
          ) : null}
        </div>
      )}
    </WidgetFrame>
  );
}
