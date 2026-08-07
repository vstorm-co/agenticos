"use client";

import { useTranslations } from "next-intl";

import { ErrorState, LoadingState } from "@/components/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { SpendBreakdown } from "@/components/runs/spend-breakdown";
import { useSpend } from "@/hooks";
import { formatDate, getErrorMessage } from "@/lib/utils";
import type { CostSummary } from "@/types/runs";

/**
 * What window these figures cover, in the terms it was asked for.
 *
 * Two shapes because `GET /spend` takes two: `days` for the "last N days"
 * presets, `from`/`to` for a calendar range - and it answers `period_days: null`
 * for the second, because a count of days beside an explicit range is a second
 * answer to a question already answered. Reading that null as a number is how a
 * range came to be captioned "Last 30 days".
 */
function windowLabel(
  spend: CostSummary | undefined,
  t: ReturnType<typeof useTranslations<"pages.runs">>,
): string {
  if (spend?.period_days != null) return t("lastDays", { days: spend.period_days });
  const from = formatDate(spend?.from_date);
  // Null means "up to now", which is a word rather than a date - and rendering
  // it through `formatDate` would put a bare dash where the end of the window
  // should be.
  return spend?.to_date == null
    ? t("fromDateToNow", { from })
    : t("fromDateToDate", { from, to: formatDate(spend.to_date) });
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
export function SpendTab() {
  const t = useTranslations("pages.runs");
  const { spend, isLoading, error, refetch } = useSpend(30);

  if (isLoading) return <LoadingState variant="stats" rows={2} />;
  if (error)
    return (
      <ErrorState
        title={t("spendCouldNotBeRead")}
        description={getErrorMessage(error, t("theMoneyWasStill"))}
        cta={{ label: t("tryAgain"), onClick: () => void refetch() }}
      />
    );

  return (
    <div className="space-y-4">
      {/* The one caveat that governs every figure below: how many of the
          window's runs ran on a model with no price. The breakdowns are a floor
          by exactly that many, and saying so once at the top is what stops a
          reader treating the totals as exact. Summed server-side from the same
          rows, so the caveat and the breakdown cannot disagree about the count. */}
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
          <CardDescription>{windowLabel(spend, t)}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {!spend || spend.by_agent.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("nothingSpentYet")}</p>
          ) : (
            // Labelled by the agent, which is what the row is. `model_label` is
            // on the type but null on every row this endpoint returns - it is the
            // usage email's per-model field, not this screen's.
            spend.by_agent.map((entry) => (
              <div
                key={entry.agent_id}
                className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm"
              >
                <span className="font-medium">{entry.agent_name ?? t("deletedAgent")}</span>
                <span className="text-muted-foreground ml-auto text-xs">
                  {t("runCount", { count: entry.run_count })}
                </span>
                {entry.partial_run_count > 0 && (
                  <span className="text-muted-foreground text-xs" title={t("theCostIsAFloor")}>
                    {t("couldNotBePriced", { count: entry.partial_run_count })}
                  </span>
                )}
                <span className="font-mono">${Number(entry.cost_usd).toFixed(4)}</span>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
