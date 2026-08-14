"use client";

import { useLocale, useTranslations } from "next-intl";
import { KeyRound } from "lucide-react";

import { getErrorMessage } from "@/lib/api-error";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import { ErrorState, LoadingState } from "@/components/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { SpendBreakdown } from "@/components/runs/spend-breakdown";
import { SpendByPerson } from "@/components/runs/spend-by-person";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { useSpend } from "@/hooks";
import { periodEnd, periodStart, type Period } from "@/lib/dashboard/period";
import { formatDate } from "@/lib/utils";
import type { CostSummary } from "@/types/runs";

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

/**
 * Where the money went, asked three ways.
 *
 * They are three different questions, not one answer sliced for presentation:
 * which agent is expensive, which vendor is being paid, and which key is being
 * spent through. Only the first existed, and it is the one that cannot be checked
 * against a bill - an invoice arrives from a vendor, and a leaked key is found by
 * what was spent through it.
 *
 * A failed request says so rather than reporting nothing spent. "Nothing spent
 * yet" for a 502 is the reassuring reading of the two, which is what makes it the
 * dangerous one on a page about money.
 */
export function SpendTab({ period }: { period: Period }) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.runs");
  const locale = useLocale();
  const { spend, isLoading, error, refetch } = useSpend({
    from: periodStart(period),
    to: periodEnd(period),
  });

  if (isLoading) return <LoadingState variant="stats" rows={2} />;
  if (error)
    return (
      <ErrorState
        title={t("spendCouldNotBeRead")}
        description={getErrorMessage(error, tErrors, t("theMoneyWasStill"))}
        cta={{ label: t("tryAgain"), onClick: () => void refetch() }}
      />
    );

  return (
    <div className="space-y-4">
      {/* The one caveat that governs every figure below: how many of the
          window's run trees could not be fully priced. Saying it once at
          the top is what stops a reader treating the totals as exact. It marks
          By provider and By key without measuring them, and measures By agent -
          see `CostSummary.partial_run_count` for which is which. */}
      {spend != null && spend.partial_run_count > 0 && (
        <p className="text-muted-foreground text-sm" role="note">
          {t("someRunsCouldNotBePriced", { count: spend.partial_run_count })}
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <SpendBreakdown
          title={t("byProvider")}
          description={t("whatEachVendorWas")}
          rows={(spend?.by_provider ?? []).map((entry) => ({
            key: entry.provider ?? "unrecorded",
            label: entry.provider ?? t("notRecorded"),
            muted: entry.provider === null,
            runs: entry.run_count,
            cost: entry.cost_usd,
            // The vendor's own mark, the same one the vault and the run table
            // draw - an invoice is checked against a brand, not a lowercase id.
            icon:
              entry.provider === null ? undefined : (
                <ProviderIcon provider={entry.provider} className="h-4 w-4" />
              ),
          }))}
        />
        <SpendBreakdown
          title={t("byKey")}
          description={t("whichStoredCredentialWas")}
          rows={(spend?.by_key ?? []).map((entry) => ({
            key: entry.secret_id ?? "deleted",
            label: entry.label ?? t("deletedKey"),
            muted: entry.label === null,
            runs: entry.run_count,
            cost: entry.cost_usd,
            icon: entry.label === null ? undefined : <KeyRound className="h-4 w-4" />,
          }))}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("spendByAgent")}</CardTitle>
          {/* The window the server chose, said the way it was chosen. There is no
              `?? 30` here on purpose: `period_days` is null the moment `from` is
              sent - `runs.py` refuses to answer "30 days" and a range at once -
              and a default in its place renders "Last 30 days" over a range that
              is nothing of the sort. Silently, which is what a fallback buys. */}
          <CardDescription>{windowLabel(spend, t, locale)}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {!spend || spend.by_agent.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("nothingSpentYet")}</p>
          ) : (
            // Labelled by the agent, which is what the row is - with the same
            // face every list of agents draws, initials when nobody uploaded a
            // picture. `model_label` is on the type but null on every row this
            // endpoint returns - it is the usage email's per-model field, not
            // this screen's.
            spend.by_agent.map((entry) => (
              <div
                key={entry.agent_id}
                className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm"
              >
                <span aria-hidden>
                  <AgentAvatar
                    agentId={entry.agent_id}
                    name={entry.agent_name ?? t("deletedAgent")}
                    size="sm"
                  />
                </span>
                <span
                  className={
                    entry.agent_name === null
                      ? "text-muted-foreground truncate italic"
                      : "truncate font-medium"
                  }
                >
                  {entry.agent_name ?? t("deletedAgent")}
                </span>
                <span className="text-muted-foreground ml-auto text-xs whitespace-nowrap">
                  {t("runCount", { count: entry.run_count })}
                </span>
                {entry.partial_run_count > 0 && (
                  <span className="text-muted-foreground text-xs" title={t("theCostIsAFloor")}>
                    {t("couldNotBePriced", { count: entry.partial_run_count })}
                  </span>
                )}
                <span className="font-mono tabular-nums">${Number(entry.cost_usd).toFixed(4)}</span>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {/* Who spent it, over the same window the breakdowns above read. The
          people rows come from `/stats/usage?group_by=user` rather than `/spend`,
          so the window is handed over as the period's own dates - the same pair
          everything on this page resolves from. Gated on runs:view inside the
          card, so it is absent for a caller without it rather than a refused
          request. */}
      <SpendByPerson from={period.from} to={period.to} />
    </div>
  );
}
