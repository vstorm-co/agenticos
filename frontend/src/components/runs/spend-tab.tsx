"use client";

import { useTranslations } from "next-intl";

import { ErrorState, LoadingState } from "@/components/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { SpendBreakdown } from "@/components/runs/spend-breakdown";
import { useSpend } from "@/hooks";
import { getErrorMessage } from "@/lib/utils";

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
          <CardDescription>{t("lastDays", { days: spend?.period_days ?? 30 })}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {!spend || spend.by_agent.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("nothingSpentYet")}</p>
          ) : (
            // Keyed and labelled by the agent, which is what the row is. It used
            // to render `model_label` - null on every row this endpoint returns,
            // so the column read "-" all the way down, and before the backend
            // grouped by agent it listed *model labels* where a reader expects
            // an agent, splitting one agent across two models into two rows.
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
