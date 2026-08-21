"use client";

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
import { ExportMenu } from "@/components/runs/export-menu";
import { SpendByPerson } from "@/components/runs/spend-by-person";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { usePermissions, useSpend } from "@/hooks";
import { periodEnd, periodStart, type Period } from "@/lib/dashboard/period";
import { formatDate } from "@/lib/utils";
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
export function SpendTab({ period }: { period: Period }) {
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
  if (error)
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
              name={row.agent_name ?? t("deletedAgent")}
              size="sm"
              className="h-5 w-5"
            />
          </span>
          <span className={row.agent_name === null ? "text-muted-foreground italic" : ""}>
            {row.agent_name ?? t("deletedAgent")}
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
    {
      key: "cost",
      header: t("cost"),
      align: "right",
      className: "pr-5",
      cell: (row) => <CostCell cost={row.cost_usd} title={t("theCostIsAFloor")} />,
    },
  ];

  if (spend === undefined) return <ErrorState title={t("spendCouldNotBeRead")} />;

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
    </div>
  );
}
