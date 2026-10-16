"use client";

import { ArrowRight, Users } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Button, Card, CardContent } from "@/components/ui";
import { useUsageStats } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import type { Period } from "@/lib/dashboard/period";
import type { Group } from "@/types/groups";

/**
 * A group's dashboard, or one plain sentence when its members ran nothing.
 *
 * Every card on the group view narrows to the group, so a quiet group used to
 * be eight cards each saying "nothing ran" in its own words - a page of empty
 * frames that told the reader one thing eight times and nothing about what to
 * do. One card says it once, says how many people the group holds, and leads
 * to where an agent is put in front of them.
 *
 * Reads the same group usage the cards below do, so a group with runs costs no
 * request of its own.
 */
export function QuietGroup({
  group,
  period,
  onWiden,
  children,
}: {
  group: Group;
  period: Period;
  /** Opens a longer window, the other reason a group reads as quiet; none when it is already the longest. */
  onWiden?: () => void;
  children: ReactNode;
}) {
  const t = useTranslations("dashboard.quietGroup");
  const { usage } = useUsageStats(
    { from: period.from, to: period.to },
    { filter: { groupId: group.id } },
  );
  if (usage?.total_runs !== 0) return children;

  return (
    <Card className="mt-6">
      <CardContent className="flex flex-col items-center gap-3 px-6 py-12 text-center">
        <span className="bg-muted grid size-11 place-items-center rounded-full">
          <Users className="text-muted-foreground size-5" aria-hidden />
        </span>
        <div className="max-w-md space-y-1">
          <h2 className="text-base font-semibold">{t("title", { name: group.name })}</h2>
          <p className="text-muted-foreground text-sm">
            {t("body", { count: group.member_count })}
          </p>
        </div>
        <div className="flex flex-wrap justify-center gap-2 pt-1">
          <Button asChild size="sm">
            <Link href={ROUTES.GROUP_DETAIL(group.id)}>
              {t("openGroup")}
              <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          </Button>
          {onWiden && (
            <Button variant="outline" size="sm" onClick={onWiden}>
              {t("widen")}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
