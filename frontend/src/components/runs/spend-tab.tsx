"use client";

import type { ReactNode } from "react";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Activity, KeyRound } from "lucide-react";

import { getErrorMessage } from "@/lib/api-error";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  DataTable,
  FigureCard,
  ListCardControlsRow,
  type Column,
} from "@/components/ui";
import { CacheBustsCard } from "@/components/runs/cache-busts-card";
import { ExportMenu } from "@/components/runs/export-menu";
import { SpendByPerson } from "@/components/runs/spend-by-person";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { usePermissions, useSpend } from "@/hooks";
import { periodEnd, periodStart, type Period } from "@/lib/dashboard/period";
import { cn, formatDate } from "@/lib/utils";
import { dailySpend } from "@/lib/spend-series";
import { TrendChart } from "@/components/dashboard/primitives/trend-chart";
import { Perm } from "@/types/permissions";
import type { CostByAgent, CostByKey, CostByProvider, CostSummary } from "@/types/runs";

/** The four ways the same money is sliced, as one switch. */
const FACETS = [
  { id: "agent", labelKey: "byAgent" },
  { id: "provider", labelKey: "byProvider" },
  { id: "key", labelKey: "byKey" },
  { id: "person", labelKey: "byPerson" },
] as const;

type SpendFacet = (typeof FACETS)[number]["id"];

/**
 * What window these figures cover, in the terms it was asked for.
 *
 * This tab always sends an explicit `from`/`to` - the page's period control -
 * so `period_days` is always null here; the branch reads it anyway because the
 * label describes the *response*, and a cached answer from the days shape must
 * not be captioned as a range it is not.
 */
function windowLabel(
  spend: CostSummary | undefined,
  t: ReturnType<typeof useTranslations<"pages.runs">>,
  locale: string,
): string {
  if (spend?.period_days != null) return t("lastDays", { days: spend.period_days });
  const from = formatDate(spend?.from_date, locale);
  // Null means "up to now", which is a word rather than a date - and rendering
  // it through `formatDate` would put a bare dash where the end of the window
  // should be.
  return spend?.to_date == null
    ? t("fromDateToNow", { from })
    : t("fromDateToDate", { from, to: formatDate(spend.to_date, locale) });
}

/** A right-aligned money cell; `partial` marks a floor the way the run table does. */
function CostCell({ cost, partial, title }: { cost: string; partial?: boolean; title: string }) {
  return (
    <span className="font-mono text-xs tabular-nums">
      ${Number(cost).toFixed(4)}
      {partial && (
        <span className="text-muted-foreground" title={title}>
          {" +"}
        </span>
      )}
    </span>
  );
}

/**
 * Where the money went, asked four ways - one table, one switch.
 *
 * They are four different questions, not one answer sliced for presentation:
 * which agent is expensive, which vendor is being paid, which key is being
 * spent through, and who is spending. An invoice arrives from a vendor, a
 * leaked key is found by what was spent through it - so each facet keeps its
 * own subject column, and a row whose subject no longer exists (a vendor from
 * before it was recorded, a key since deleted, a deleted agent) is kept and
 * muted rather than dropped: the money was spent either way, and a breakdown
 * that silently stops adding up to the total is worse than one with an honest
 * "not recorded" line in it.
 *
 * The person facet is its own component: its rows come from
 * `/stats/usage?group_by=user` rather than `/spend`, with its own gate,
 * failure state and audience note.
 *
 * A failed request says so rather than reporting nothing spent. "Nothing spent
 * yet" for a 502 is the reassuring reading of the two, which is what makes it
 * the dangerous one on a page about money.
 */
/**
 * A row's part of the whole, as a track and a percentage.
 *
 * The question a breakdown is opened with is "who is most of it", and a column
 * of dollar figures makes the reader divide. Both, because the track alone
 * makes colour the message and the number alone is the division done for them
 * without the picture.
 */
function ShareCell({ cost, total }: { cost: string; total: number }) {
  const share = total > 0 ? (Number(cost) / total) * 100 : 0;
  return (
    <span className="flex items-center justify-end gap-2">
      <span className="bg-muted hidden h-1.5 w-20 overflow-hidden rounded-full sm:block">
        <span
          className="bg-foreground/60 block h-full rounded-full"
          style={{ width: `${Math.min(100, share)}%` }}
        />
      </span>
      <span className="text-muted-foreground w-10 text-right text-xs tabular-nums">
        {Math.round(share)}%
      </span>
    </span>
  );
}

/** A share column for one breakdown, the total being that breakdown's own sum. */
function shareColumn<T extends { cost_usd: string }>(
  header: string,
  rows: readonly T[],
): Column<T> {
  const total = rows.reduce((sum, row) => sum + Number(row.cost_usd), 0);
  return {
    key: "share",
    header,
    align: "right",
    cell: (row) => <ShareCell cost={row.cost_usd} total={total} />,
  };
}

export function SpendTab({
  period,
  periodControl,
}: {
  period: Period;
  /**
   * The page's window, drawn first among this tab's own filters: it narrows
   * the same table they do, so it sits with them rather than in a band above.
   */
  periodControl?: ReactNode;
}) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.runs");
  const locale = useLocale();
  const { can } = usePermissions();
  // `GET /spend` carries `runs:view` like the run list, so a caller without it
  // is not asked for - the 403 would be drawn as a failure on a tab that never
  // had anything to show them.
  const canView = can(Perm.runsView);
  const [facet, setFacet] = useState<SpendFacet>("agent");
  const range = { from: periodStart(period), to: periodEnd(period) };
  const { spend, isLoading, error, refetch } = useSpend(range, { enabled: canView });

  if (!canView) {
    return (
      <EmptyState
        icon={Activity}
        title={t("noAccessToRuns")}
        description={t("runsViewIsMissing")}
      />
    );
  }
  if (isLoading) return <LoadingState variant="stats" rows={2} />;
  // One guard for both absences: a failed request, and the body react-query
  // itself refuses (`undefined` data is an error there, so past this line the
  // answer exists - which is also what narrows the type for everything below).
  if (error || spend === undefined)
    return (
      <ErrorState
        title={t("spendCouldNotBeRead")}
        description={getErrorMessage(error, tErrors, t("theMoneyWasStill"))}
        cta={{ label: t("tryAgain"), onClick: () => void refetch() }}
      />
    );

  const agentColumns: Column<CostByAgent>[] = [
    {
      key: "agent",
      header: t("agentColumn"),
      className: "pl-5",
      cell: (row) => (
        <span className="flex items-center gap-2">
          <span aria-hidden>
            <AgentAvatar
              agentId={row.agent_id}
              slug={row.agent_slug}
              size="sm"
              className="h-5 w-5"
            />
          </span>
          <span className="min-w-0">
            <span
              className={cn("block", row.agent_name === null && "text-muted-foreground italic")}
            >
              {row.agent_name ?? t("deletedAgent")}
            </span>
            {/* Against the calendar month, the period a cap is a cap on - not
                the window on screen. */}
            {row.monthly_cap_usd !== null && (
              <span className="text-muted-foreground block text-xs">
                {t("monthAgainstCap", {
                  spent: Number(row.month_to_date_usd ?? 0).toFixed(2),
                  cap: Number(row.monthly_cap_usd).toFixed(2),
                })}
              </span>
            )}
          </span>
        </span>
      ),
    },
    {
      key: "runs",
      header: t("runs2"),
      align: "right",
      cell: (row) => <span className="font-mono text-xs tabular-nums">{row.run_count}</span>,
    },
    shareColumn<CostByAgent>(t("share"), spend.by_agent),
    {
      key: "cost",
      header: t("cost"),
      align: "right",
      className: "pr-5",
      cell: (row) => (
        <CostCell
          cost={row.cost_usd}
          partial={row.partial_run_count > 0}
          // The count, not just a marker: "3 unpriced" is actionable where a
          // bare figure a reader has to take on trust is not.
          title={t("unpricedRuns", { count: row.partial_run_count })}
        />
      ),
    },
  ];

  const providerColumns: Column<CostByProvider>[] = [
    {
      key: "provider",
      header: t("providerColumn"),
      className: "pl-5",
      cell: (row) =>
        row.provider === null ? (
          <span className="text-muted-foreground italic">{t("notRecorded")}</span>
        ) : (
          <span className="flex items-center gap-2">
            <ProviderIcon provider={row.provider} className="h-4 w-4" />
            {row.provider}
          </span>
        ),
    },
    {
      key: "runs",
      header: t("runs2"),
      align: "right",
      cell: (row) => <span className="font-mono text-xs tabular-nums">{row.run_count}</span>,
    },
    shareColumn<CostByProvider>(t("share"), spend.by_provider),
    {
      key: "cost",
      header: t("cost"),
      align: "right",
      className: "pr-5",
      cell: (row) => <CostCell cost={row.cost_usd} title={t("theCostIsAFloor")} />,
    },
  ];

  const keyColumns: Column<CostByKey>[] = [
    {
      key: "key",
      header: t("keyColumn"),
      className: "pl-5",
      cell: (row) =>
        row.label === null ? (
          <span className="text-muted-foreground italic">{t("deletedKey")}</span>
        ) : (
          <span className="flex items-center gap-2">
            <KeyRound className="text-muted-foreground h-4 w-4" aria-hidden />
            {row.label}
          </span>
        ),
    },
    {
      key: "runs",
      header: t("runs2"),
      align: "right",
      cell: (row) => <span className="font-mono text-xs tabular-nums">{row.run_count}</span>,
    },
    shareColumn<CostByKey>(t("share"), spend.by_key),
    {
      key: "cost",
      header: t("cost"),
      align: "right",
      className: "pr-5",
      cell: (row) => <CostCell cost={row.cost_usd} title={t("theCostIsAFloor")} />,
    },
  ];

  const windowTotal = spend.by_agent.reduce((sum, row) => sum + Number(row.cost_usd), 0);
  const runCount = spend.by_agent.reduce((sum, row) => sum + row.run_count, 0);
  const dearest = [...spend.by_agent].sort(
    (left, right) => Number(right.cost_usd) - Number(left.cost_usd),
  )[0];

  return (
    <div className="space-y-4">
      {/* The figures the tab was making a reader compute from its own table: what
          the window cost, what the month has cost so far, what one run costs on
          average, and which agent is spending the most. The last two are the ones
          worth a card - an average is the number a budget is set from, and the
          dearest agent is where a bill is questioned first. */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <FigureCard
          label={t("spendWindow")}
          caption={t("overTheWindowAbove")}
          value={`$${windowTotal.toFixed(2)}`}
        />
        <FigureCard
          label={t("monthToDate")}
          caption={t("calendarAligned")}
          value={`$${Number(spend.month_to_date_usd).toFixed(2)}`}
        />
        <FigureCard
          label={t("perRun")}
          caption={t("overRunsInWindow", { count: runCount })}
          value={runCount === 0 ? "\u2014" : `$${(windowTotal / runCount).toFixed(4)}`}
        />
        <FigureCard
          label={t("dearestAgent")}
          caption={
            dearest === undefined ? t("noAgentHasSpent") : `$${Number(dearest.cost_usd).toFixed(2)}`
          }
          value={dearest?.agent_name ?? "\u2014"}
        />
      </div>

      {/* The bill's shape over the window, a bar a day: when the money went,
          which the totals above cannot say - a spike on one afternoon and a
          steady drip read the same as a sum. */}
      <Card>
        <CardHeader className="space-y-1 px-5 pt-4 pb-2">
          <CardTitle className="text-sm">{t("spendOverTime")}</CardTitle>
          <CardDescription className="text-xs">{t("spendOverTimeHint")}</CardDescription>
        </CardHeader>
        <CardContent className="px-3 pb-4">
          <TrendChart
            variant="bars"
            money
            className="h-44"
            data={dailySpend(spend.by_day, spend.from_date, spend.to_date, new Date(), (day) =>
              day.toLocaleDateString(locale, { month: "short", day: "numeric", timeZone: "UTC" }),
            )}
          />
        </CardContent>
      </Card>

      {/* The one caveat that governs every figure below: how many of the
          window's run trees could not be fully priced. Saying it once at
          the top is what stops a reader treating the totals as exact. It marks
          the provider and key facets without measuring them, and measures the
          agent facet - see `CostSummary.partial_run_count` for which is which. */}
      {spend.partial_run_count > 0 && (
        <p className="text-muted-foreground text-sm" role="note">
          {t("someRunsCouldNotBePriced", { count: spend.partial_run_count })}
        </p>
      )}

      <Card>
        {/* The same header grammar as the history tab's: what the card is on
            the left, its export on the right, carrying the page's window. */}
        <CardHeader className="flex-row items-start justify-between space-y-0 border-b px-5 py-4">
          <div className="space-y-1">
            <CardTitle className="text-sm">{t("whereTheMoneyWent")}</CardTitle>
            {/* The window the server chose, said the way it was chosen. There is no
                `?? 30` here on purpose: `period_days` is null the moment `from` is
                sent - `runs.py` refuses to answer "30 days" and a range at once -
                and a default in its place renders "Last 30 days" over a range that
                is nothing of the sort. Silently, which is what a fallback buys. */}
            <CardDescription className="text-xs">{windowLabel(spend, t, locale)}</CardDescription>
          </div>
          <ExportMenu
            permission={Perm.runsView}
            endpoint="/spend/export"
            kind="spend"
            rangeParams={{ from: "from", to: "to" }}
            range={range}
          />
        </CardHeader>
        <CardContent className="p-0">
          {/* The facet switch lives inside the container it slices, like every
              list card's filters. One table below, four subjects. */}
          <ListCardControlsRow role="group" aria-label={t("spendFacet")}>
            {periodControl}
            {FACETS.map((entry) => (
              <Button
                key={entry.id}
                variant={facet === entry.id ? "secondary" : "outline"}
                size="sm"
                aria-pressed={facet === entry.id}
                onClick={() => setFacet(entry.id)}
              >
                {t(entry.labelKey)}
              </Button>
            ))}
          </ListCardControlsRow>
          {facet === "agent" && (
            <DataTable<CostByAgent>
              columns={agentColumns}
              rows={spend.by_agent}
              getRowKey={(row) => row.agent_id}
              empty={t("nothingSpentYet")}
              className="rounded-none border-0 bg-transparent"
            />
          )}
          {facet === "provider" && (
            <DataTable<CostByProvider>
              columns={providerColumns}
              rows={spend.by_provider}
              getRowKey={(row) => row.provider ?? "unrecorded"}
              empty={t("nothingSpentYet")}
              className="rounded-none border-0 bg-transparent"
            />
          )}
          {facet === "key" && (
            <DataTable<CostByKey>
              columns={keyColumns}
              rows={spend.by_key}
              getRowKey={(row) => row.secret_id ?? "deleted"}
              empty={t("nothingSpentYet")}
              className="rounded-none border-0 bg-transparent"
            />
          )}
          {facet === "person" && <SpendByPerson from={period.from} to={period.to} />}
        </CardContent>
      </Card>

      <CacheBustsCard rows={spend.cache_by_agent_model} />
    </div>
  );
}
