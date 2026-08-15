"use client";

import { useTranslations } from "next-intl";

import { initialsOf } from "@/components/orgs/member-identity";
import { LoadingState } from "@/components/states";
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
  Button,
  DataTable,
  type Column,
} from "@/components/ui";
import { usePeopleUsage, usePermissions, useUsageStats } from "@/hooks";
import { Perm } from "@/types/permissions";
import type { PersonUsageRow } from "@/types/stats";

/** A slice, not a directory: the busiest few, with the disclosure under them. */
const ROWS = 10;

/**
 * Who spent the money - the Spend table's person facet.
 *
 * The one slice on this page that answers with people rather than vendors or
 * agents, so it carries its own audience note: the gate is `runs:view`, which
 * builder and operator hold as well as the two stewards, and somebody named here
 * deserves to know how far the list reaches. Absent entirely - never disabled or
 * refused after the fact - for a caller without it, and its request is not made.
 *
 * Its own query against `/stats/usage?group_by=user`, so it fails on its own
 * facet rather than taking the vendor and key slices down with it - which is why
 * a failed request says so here rather than reporting that nobody spent anything.
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
  if (isLoading) return <LoadingState variant="skeleton-panel" rows={3} className="m-5" />;
  if (error)
    return (
      <div className="m-5 space-y-2">
        <p className="text-muted-foreground text-sm">{t("whoIsSpendingCouldNotBeRead")}</p>
        <Button variant="outline" size="sm" onClick={() => void refetch()}>
          {t("tryAgain")}
        </Button>
      </div>
    );

  const columns: Column<PersonUsageRow>[] = [
    {
      key: "person",
      header: t("personColumn"),
      className: "pl-5",
      cell: (person) => (
        <span className="flex items-center gap-2">
          {/* The application's one way of drawing a person - the same face the
              member lists and the run filter show. */}
          <Avatar className="h-5 w-5 shrink-0" aria-hidden>
            <AvatarImage src={`/api/users/avatar/${person.user_id}`} alt="" />
            <AvatarFallback className="text-[9px]">
              {initialsOf(person.full_name || person.email)}
            </AvatarFallback>
          </Avatar>
          {person.full_name ?? person.email}
        </span>
      ),
    },
    {
      key: "runs",
      header: t("runs2"),
      align: "right",
      cell: (person) => <span className="font-mono text-xs tabular-nums">{person.runs}</span>,
    },
    {
      key: "cost",
      header: t("cost"),
      align: "right",
      className: "pr-5",
      cell: (person) => (
        <span className="font-mono text-xs tabular-nums">
          ${Number(person.cost_usd).toFixed(4)}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-2 pb-4">
      <DataTable<PersonUsageRow>
        columns={columns}
        rows={byUser}
        getRowKey={(person) => person.user_id}
        empty={t("nobodyHasRunAnything")}
        className="rounded-none border-0 bg-transparent"
      />
      {others > 0 ? (
        <p className="text-muted-foreground px-5 text-xs">
          {t("othersRanAgents", { count: others })}
        </p>
      ) : null}
      <p className="text-muted-foreground px-5 text-xs">{t("perPersonDisclosure")}</p>
    </div>
  );
}
