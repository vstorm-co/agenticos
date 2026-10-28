"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { formatShare } from "@/components/dashboard/format";
import { Card, CardContent, FigureCard, Skeleton } from "@/components/ui";
import { useNodeCatalog, useWorkflowStats } from "@/hooks";
import { cn, formatElapsed } from "@/lib/utils";
import type { WorkflowStats as Stats } from "@/lib/workflows/types";

/** The windows the figures can cover, in days. */
const WINDOWS = [7, 30, 90] as const;

/** Dollars to the cent, or to a hundredth of a cent below a dollar - a step's cost is small. */
function usd(amount: number, locale: string): string {
  const digits = amount !== 0 && Math.abs(amount) < 1 ? 4 : 2;
  return `$${amount.toLocaleString(locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

function seconds(value: number | null): string {
  return value === null ? "-" : formatElapsed(value * 1000);
}

function share(value: number | null, locale: string): string {
  return value === null ? "-" : formatShare(value, locale);
}

/**
 * What a workflow's real runs did over the last week, month or quarter: how many
 * ran and how they ended, how long they took, what they cost against the month's
 * budget, and which steps the cost and the failures came from.
 *
 * Test runs are left out of every figure but the month's spend, because the
 * budget counts them: a draft tried twenty times is not twenty runs of the
 * workflow, but it is twenty runs somebody paid for.
 */
export function WorkflowStats({ workflowId }: { workflowId: string }) {
  const t = useTranslations("pages.workflows.stats");
  const locale = useLocale();
  const [days, setDays] = useState<(typeof WINDOWS)[number]>(30);
  const { stats, isLoading } = useWorkflowStats(workflowId, days);

  return (
    <section className="space-y-3" aria-label={t("heading")} data-tour="workflow-stats">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium">{t("heading")}</h2>
        <div
          className="bg-muted inline-flex rounded-lg p-0.5"
          role="group"
          aria-label={t("window")}
        >
          {WINDOWS.map((window) => (
            <button
              key={window}
              type="button"
              aria-pressed={window === days}
              onClick={() => setDays(window)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs",
                window === days ? "bg-background shadow-sm" : "text-muted-foreground",
              )}
            >
              {t("days", { days: window })}
            </button>
          ))}
        </div>
      </div>
      {isLoading || stats === null ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {["runs", "succeeded", "duration", "cost"].map((key) => (
            <Skeleton key={key} className="h-28 w-full" />
          ))}
        </div>
      ) : (
        <StatsBody stats={stats} locale={locale} />
      )}
    </section>
  );
}

function StatsBody({ stats, locale }: { stats: Stats; locale: string }) {
  const t = useTranslations("pages.workflows.stats");
  // A step taken out of the workflow keeps its past runs; its rows are hidden unless asked
  // for. An approval step is a step too, so this one switch covers both tables.
  const [showRemoved, setShowRemoved] = useState(false);
  const anyRemoved = [...stats.steps, ...stats.approvals.steps].some(
    (step) => step.definition_id === null,
  );
  const { nodes } = useNodeCatalog();
  // An unnamed step reads as what it is - "Manual" - not as its id.
  const typeName = (definitionId: string | null) =>
    nodes.find((definition) => definition.id === definitionId)?.name ?? definitionId;
  const shown = (step: { definition_id: string | null }) =>
    showRemoved || step.definition_id !== null;
  const steps = stats.steps
    .filter(shown)
    .sort((a, b) => b.cost_usd - a.cost_usd || b.failed - a.failed);
  const budget = stats.monthly_budget_usd;
  const over = budget !== null && stats.month_cost_usd >= budget;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <FigureCard
          label={t("runs")}
          value={stats.runs.toLocaleString(locale)}
          caption={t("runsCaption", { failed: stats.failed })}
          spark={stats.by_day.map((day) => day.succeeded + day.failed + day.other)}
        />
        <FigureCard
          label={t("succeeded")}
          value={stats.success_rate === null ? "-" : formatShare(stats.success_rate, locale)}
          caption={t("succeededCaption", { succeeded: stats.succeeded, ended: stats.ended })}
        />
        <FigureCard
          label={t("duration")}
          value={seconds(stats.duration_p50_seconds)}
          caption={t("durationCaption", { p95: seconds(stats.duration_p95_seconds) })}
        />
        <FigureCard
          label={t("cost")}
          value={`${usd(stats.cost_usd, locale)}${stats.cost_is_partial ? "+" : ""}`}
          caption={
            budget === null
              ? t("monthSpent", { amount: usd(stats.month_cost_usd, locale) })
              : t("monthOfBudget", {
                  amount: usd(stats.month_cost_usd, locale),
                  budget: usd(budget, locale),
                })
          }
          captionTone={over ? "destructive" : "muted"}
          spark={stats.by_day.map((day) => day.cost_usd)}
        />
      </div>
      <Card>
        <CardContent className="p-0">
          <div className="flex flex-wrap items-start justify-between gap-2 border-b px-4 py-3">
            <div>
              <h3 className="text-sm font-medium">{t("stepsHeading")}</h3>
              <p className="text-muted-foreground text-xs">{t("stepsHint")}</p>
            </div>
            {anyRemoved && (
              <button
                type="button"
                aria-pressed={showRemoved}
                onClick={() => setShowRemoved((shown) => !shown)}
                className={cn(
                  "rounded-md border px-2.5 py-1 text-xs",
                  showRemoved ? "bg-muted" : "text-muted-foreground",
                )}
              >
                {t("showRemoved")}
              </button>
            )}
          </div>
          {steps.length === 0 ? (
            <p className="text-muted-foreground px-4 py-6 text-center text-sm">{t("stepsNone")}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-muted-foreground text-xs">
                  <tr className="border-b">
                    <th className="px-4 py-2 text-left font-medium">{t("step")}</th>
                    <th className="px-4 py-2 text-right font-medium">{t("stepRuns")}</th>
                    <th className="px-4 py-2 text-right font-medium">{t("stepFailed")}</th>
                    <th className="px-4 py-2 text-right font-medium">{t("stepTime")}</th>
                    <th className="px-4 py-2 text-right font-medium">{t("stepCost")}</th>
                  </tr>
                </thead>
                <tbody>
                  {steps.map((step) => (
                    <tr key={step.node_instance_id} className="border-b last:border-0">
                      <td className="max-w-64 truncate px-4 py-2">
                        {step.label ?? typeName(step.definition_id) ?? t("stepGone")}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">{step.runs}</td>
                      <td
                        className={cn(
                          "px-4 py-2 text-right tabular-nums",
                          step.failed > 0 && "text-destructive",
                        )}
                      >
                        {step.failed}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {seconds(step.avg_seconds)}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {usd(step.cost_usd, locale)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
      {stats.approvals.requests > 0 && (
        <Approvals
          approvals={{ ...stats.approvals, steps: stats.approvals.steps.filter(shown) }}
          locale={locale}
          typeName={typeName}
        />
      )}
    </div>
  );
}

/**
 * How people decided the workflow's approval requests: how many went out as
 * proposed, how many were edited and by how much, how many were turned down,
 * and how long deciding took. Counts only what the figures hold - an expired
 * request was never decided, so it is not in the share approved.
 */
function Approvals({
  approvals,
  locale,
  typeName,
}: {
  approvals: Stats["approvals"];
  locale: string;
  typeName: (definitionId: string | null) => string | null;
}) {
  const t = useTranslations("pages.workflows.stats");
  const decided = approvals.approved_unchanged + approvals.approved_edited + approvals.rejected;

  return (
    <section aria-label={t("approvalsHeading")}>
      <Card>
        <CardContent className="p-0">
          <div className="border-b px-4 py-3">
            <h3 className="text-sm font-medium">{t("approvalsHeading")}</h3>
            <p className="text-muted-foreground text-xs">{t("approvalsHint")}</p>
          </div>
          <div className="grid grid-cols-2 gap-3 p-4 lg:grid-cols-4">
            <FigureCard
              label={t("approvalsUnchanged")}
              value={share(approvals.unchanged_rate, locale)}
              caption={t("approvalsUnchangedCaption", {
                approved: approvals.approved_unchanged,
                decided,
              })}
              spark={approvals.by_day.map((day) => day.approved_unchanged)}
            />
            <FigureCard
              label={t("approvalsEdited")}
              value={approvals.approved_edited.toLocaleString(locale)}
              caption={
                approvals.edit_ratio_median !== null
                  ? t("approvalsEditedCaption", {
                      ratio: formatShare(approvals.edit_ratio_median, locale),
                    })
                  : approvals.approved_edited > 0
                    ? t("approvalsNotMeasured")
                    : undefined
              }
            />
            <FigureCard
              label={t("approvalsRejected")}
              value={approvals.rejected.toLocaleString(locale)}
              caption={t("approvalsExpiredCaption", { count: approvals.expired })}
            />
            <FigureCard
              label={t("approvalsDecideTime")}
              value={seconds(approvals.decide_p50_seconds)}
              caption={t("approvalsDecideCaption", {
                p95: seconds(approvals.decide_p95_seconds),
              })}
            />
          </div>
          {approvals.steps.length > 0 && (
            <div className="overflow-x-auto border-t">
              <table className="w-full text-sm">
                <thead className="text-muted-foreground text-xs">
                  <tr className="border-b">
                    <th className="px-4 py-2 text-left font-medium">{t("step")}</th>
                    <th className="px-4 py-2 text-right font-medium">{t("approvalsRequests")}</th>
                    <th className="px-4 py-2 text-right font-medium">{t("approvalsUnchanged")}</th>
                    <th className="px-4 py-2 text-right font-medium">{t("approvalsEdited")}</th>
                    <th className="px-4 py-2 text-right font-medium">{t("approvalsRejected")}</th>
                    <th className="px-4 py-2 text-right font-medium">{t("approvalsExpired")}</th>
                    <th className="px-4 py-2 text-right font-medium">{t("approvalsMedianEdit")}</th>
                    <th className="px-4 py-2 text-right font-medium">{t("approvalsDecideTime")}</th>
                  </tr>
                </thead>
                <tbody>
                  {approvals.steps.map((step) => (
                    <tr key={step.node_instance_id} className="border-b last:border-0">
                      <td className="max-w-64 truncate px-4 py-2">
                        {step.label ?? typeName(step.definition_id) ?? t("stepGone")}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">{step.requests}</td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {share(step.unchanged_rate, locale)}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">{step.approved_edited}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{step.rejected}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{step.expired}</td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {share(step.edit_ratio_median, locale)}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {seconds(step.decide_p50_seconds)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
