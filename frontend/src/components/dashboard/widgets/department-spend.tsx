"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { GroupIcon } from "@/components/groups/group-icon";
import { useGroupSpend } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { useOrgStore } from "@/stores";
import { formatUsd } from "../format";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import { HeadroomBar } from "./budget-headroom";
import type { DashboardWidgetProps } from "./types";

/** As many departments as an `r2` card holds without scrolling. */
const SHOWN = 5;

/**
 * What each department's people ran this month, against the department's cap
 * (#2072). Calendar month like the other budget card, whatever the period
 * filter says, because a cap is monthly. A person in two departments counts in
 * both, so the rows are not a split of the bill and no total is drawn.
 */
export function DepartmentSpendWidget({ title, hint, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.department-spend");
  const orgId = useOrgStore((state) => state.activeOrgId);
  const { spend, isLoading, error, refetch } = useGroupSpend(orgId);
  const rows = (spend?.items ?? []).slice(0, SHOWN);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={ROUTES.GROUPS} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : rows.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <ul className="space-y-2.5">
          {rows.map((row) => {
            const cap = row.monthly_budget_usd === null ? null : Number(row.monthly_budget_usd);
            const used = Number(row.spent_usd);
            return (
              <li key={row.group_id} className="text-xs">
                <div className="flex items-center justify-between gap-2">
                  <Link
                    href={ROUTES.GROUP_DETAIL(row.group_id)}
                    className="flex min-w-0 items-center gap-2 hover:underline"
                  >
                    <GroupIcon icon={row.icon} className="h-5 w-5 [&_svg]:h-3 [&_svg]:w-3" />
                    <span className="truncate">{row.name}</span>
                  </Link>
                  <span className="text-foreground shrink-0 tabular-nums">
                    {cap === null
                      ? formatUsd(used)
                      : t("ofCap", { spent: formatUsd(used), cap: formatUsd(cap) })}
                  </span>
                </div>
                {cap !== null && <HeadroomBar used={used} cap={cap} className="mt-1" />}
              </li>
            );
          })}
        </ul>
      )}
    </WidgetFrame>
  );
}
