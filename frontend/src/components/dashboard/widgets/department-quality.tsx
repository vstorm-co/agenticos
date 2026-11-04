"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { ThumbsUp } from "lucide-react";

import { GroupIcon } from "@/components/groups/group-icon";
import { useGroupsQuality } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { useOrgStore } from "@/stores";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** As many departments as an `r3` card holds without scrolling. */
const SHOWN = 6;

/**
 * How each department's people rated answers in the period, least helpful first
 * (#2101) - the organization's quality card split the way its spend card is.
 * Green and red are the helpful and not-helpful shares - meaning, not decoration.
 */
export function DepartmentQualityWidget({ title, hint, period, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.department-quality");
  const orgId = useOrgStore((state) => state.activeOrgId);
  const { quality, isLoading, error, refetch } = useGroupsQuality(orgId, {
    from: period.from,
    to: period.to,
  });
  const rows = (quality?.items ?? []).slice(0, SHOWN);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={ROUTES.GROUPS} options={options}>
      {isLoading ? (
        <WidgetSkeleton variant="bars" />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : rows.length === 0 ? (
        <WidgetEmptyBody
          icon={ThumbsUp}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="space-y-2.5">
          {rows.map((row) => {
            const total = row.likes + row.dislikes;
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
                    {t("row", { percent: Math.round((row.likes / total) * 100), total })}
                  </span>
                </div>
                <SplitBar likes={row.likes} total={total} />
              </li>
            );
          })}
        </ul>
      )}
    </WidgetFrame>
  );
}

function SplitBar({ likes, total }: { likes: number; total: number }) {
  return (
    <div aria-hidden className="bg-destructive/70 mt-1 flex h-2 overflow-hidden rounded-sm">
      <div className="bg-success h-full" style={{ width: `${(likes / total) * 100}%` }} />
    </div>
  );
}
