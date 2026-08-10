"use client";

import { useTranslations } from "next-intl";

import { LoadingState } from "@/components/states";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { usePeopleUsage, usePermissions, useUsageStats } from "@/hooks";
import { Perm } from "@/types/permissions";

/** A card, not a directory: the busiest few, with the disclosure under them. */
const ROWS = 10;

/**
 * Who spent the money, over the window the rest of the tab already shows.
 *
 * The one breakdown on this page that answers with people rather than vendors or
 * agents, so it carries its own audience note: the gate is `runs:view`, which
 * builder and operator hold as well as the two stewards, and somebody named here
 * deserves to know how far the list reaches. Absent entirely - never disabled or
 * refused after the fact - for a caller without it, and its request is not made.
 *
 * Its own query against `/stats/usage?group_by=user`, so it fails on its own card
 * rather than taking the vendor and key breakdowns down with it - which is why a
 * failed request says so here rather than reporting that nobody spent anything.
 * The rows exclude delegated runs, the same as every other figure on the page, so
 * a delegate's cost is counted once inside the run that started it.
 */
export function SpendByPerson({ from, to }: { from: string; to: string }) {
  const t = useTranslations("pages.runs");
  const { can } = usePermissions();
  const maySee = can(Perm.runsView);
  const { byUser, isLoading, error, refetch } = usePeopleUsage(
    { from, to },
    { scope: "org", limit: ROWS, enabled: maySee },
  );
  // The org headcount rides the composed usage answer for the same window, so a
  // top-N list can say how many people it leaves unnamed without a second request.
  const { usage } = useUsageStats({ from, to }, { scope: "org", enabled: maySee });
  const others = Math.max((usage?.active_users?.active ?? 0) - byUser.length, 0);

  if (!maySee) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("byPerson")}</CardTitle>
        <CardDescription>{t("whoRanAgentsAndWhatItCost")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {isLoading ? (
          <LoadingState variant="skeleton-panel" rows={3} />
        ) : error ? (
          <div className="space-y-2">
            <p className="text-muted-foreground text-sm">{t("whoIsSpendingCouldNotBeRead")}</p>
            <Button variant="outline" size="sm" onClick={() => void refetch()}>
              {t("tryAgain")}
            </Button>
          </div>
        ) : byUser.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("nobodyHasRunAnything")}</p>
        ) : (
          <>
            {byUser.map((person) => (
              <div
                key={person.user_id}
                className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm"
              >
                <span className="min-w-0 flex-1 truncate font-medium">
                  {person.full_name ?? person.email}
                </span>
                <span className="text-muted-foreground text-xs">
                  {t("runCount", { count: person.runs })}
                </span>
                <span className="font-mono">${Number(person.cost_usd).toFixed(4)}</span>
              </div>
            ))}
            {others > 0 ? (
              <p className="text-muted-foreground text-xs">
                {t("othersRanAgents", { count: others })}
              </p>
            ) : null}
            <p className="text-muted-foreground text-xs">{t("perPersonDisclosure")}</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
