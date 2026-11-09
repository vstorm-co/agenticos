"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { CircleHelp, Coins, Gauge, Hash, Timer } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import type { ArmSummary, ComparisonSide, EvalRunArm } from "@/types/eval-runs";
import { percent, seconds, usd } from "./format";
import { sideName, type SideCheck } from "./names";

function SideLabel({
  agentId,
  arm,
  baseline,
  check,
}: {
  agentId: string;
  arm: EvalRunArm;
  baseline: ComparisonSide | null;
  check: SideCheck | null | undefined;
}) {
  const t = useTranslations("evals");
  const locale = useLocale();
  const name = t("sideModel", { name: sideName(arm, t, check), model: arm.model_label });
  // A reused side answered nothing here: it is an earlier run's result, and
  // says which.
  if (arm.reused_from_arm_id === null || baseline === null) return <>{name}</>;
  return (
    <>
      {name}
      {" · "}
      <Link
        href={`${ROUTES.AGENTS}/${agentId}/evals/${baseline.run_id}`}
        className="text-muted-foreground underline underline-offset-4"
      >
        {baseline.finished_at
          ? t("arms.reusedFrom", { date: formatDateTime(baseline.finished_at, locale) })
          : t("arms.reused")}
      </Link>
    </>
  );
}

/** One side's numbers, a dash where it has none under the tag read. */
function SummaryCell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <td className="flex min-w-0 items-start justify-between gap-4 py-1.5 md:table-cell md:py-2 md:pr-3">
      <span className="text-muted-foreground text-xs md:hidden">{label}</span>
      <span className="min-w-0 text-right break-words md:text-left">{children}</span>
    </td>
  );
}

function SummaryCells({ summary, live }: { summary: ArmSummary | undefined; live: boolean }) {
  const t = useTranslations("evals.arms");
  const locale = useLocale();
  return (
    <>
      <SummaryCell label={t("passRate")}>{percent(summary?.pass_rate ?? null, locale)}</SummaryCell>
      <SummaryCell label={live ? t("pending") : t("undecided")}>
        {summary === undefined ? "—" : summary.incomplete + summary.ungraded}
      </SummaryCell>
      <SummaryCell label={t("costPerPass")}>
        {usd(summary?.cost_per_pass_usd ?? null, locale)}
      </SummaryCell>
      <SummaryCell label={t("tokens")}>
        {summary === undefined || summary.avg_tokens === null
          ? "—"
          : Math.round(summary.avg_tokens)}
      </SummaryCell>
      <SummaryCell label={t("latency")}>
        {t("p50p95", {
          p50: seconds(summary?.p50_ms ?? null, locale),
          p95: seconds(summary?.p95_ms ?? null, locale),
        })}
      </SummaryCell>
    </>
  );
}

/**
 * Every side of a run next to each other - the draft beside what is live, or
 * each model the candidate ran on - over every case, or over the cases
 * carrying `tag`. A run that measured itself against an earlier run without
 * keeping it as a side of its own still shows that run's numbers, from the
 * comparison.
 */
export function ArmsTable({
  agentId,
  arms,
  tag,
  live,
  baseline,
  check,
  baselineSummary,
}: {
  agentId: string;
  arms: EvalRunArm[];
  tag: string | null;
  /** Whether the run still answers, so an empty result is pending rather than undecided. */
  live: boolean;
  /** The side the candidate is compared with, to name the run a reused result came from. */
  baseline: ComparisonSide | null;
  /** What a check of a proposal measured, to name its candidate by what it adds. */
  check?: SideCheck | null;
  /** That side's numbers over the cases both answered, as the comparison read them. */
  baselineSummary: ArmSummary | null;
}) {
  const t = useTranslations("evals.arms");
  const tSide = useTranslations("evals");
  const locale = useLocale();
  const earlier =
    baseline !== null && baselineSummary !== null && !arms.some((arm) => arm.role === "baseline")
      ? baseline
      : null;
  const single = arms.length === 1 && earlier === null ? arms[0] : undefined;
  const summary =
    single?.failed_alike != null ? undefined : tag === null ? single?.summary : single?.by_tag[tag];
  const metrics = [
    { label: t("passRate"), value: percent(summary?.pass_rate ?? null, locale), icon: Gauge },
    {
      label: live ? t("pending") : t("undecided"),
      value: summary ? summary.incomplete + summary.ungraded : "—",
      icon: CircleHelp,
    },
    {
      label: t("costPerPass"),
      value: usd(summary?.cost_per_pass_usd ?? null, locale),
      icon: Coins,
    },
    {
      label: t("tokens"),
      value:
        summary?.avg_tokens == null
          ? "—"
          : new Intl.NumberFormat(locale).format(Math.round(summary.avg_tokens)),
      icon: Hash,
    },
    {
      label: t("latency"),
      value: t("p50p95", {
        p50: seconds(summary?.p50_ms ?? null, locale),
        p95: seconds(summary?.p95_ms ?? null, locale),
      }),
      icon: Timer,
    },
  ];
  if (single?.failed_alike != null) return null;
  if (single)
    return (
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
          <CardTitle>{tag === null ? t("singleTitle") : t("singleTitleTag", { tag })}</CardTitle>
          <p className="text-muted-foreground min-w-0 text-xs break-words">
            <SideLabel agentId={agentId} arm={single} baseline={baseline} check={check} />
          </p>
        </CardHeader>
        <CardContent className="border-t pt-4">
          <dl className="grid grid-cols-2 gap-3 xl:grid-cols-5">
            {metrics.map((metric) => (
              <div
                key={metric.label}
                className="bg-background/40 min-w-0 space-y-3 rounded-xl border p-4 last:col-span-2 xl:last:col-span-1"
              >
                <dt className="text-muted-foreground flex items-center gap-2 text-xs">
                  <metric.icon className="size-3.5 shrink-0" aria-hidden />
                  {metric.label}
                </dt>
                <dd className="text-xl font-semibold tracking-tight tabular-nums">
                  {metric.value}
                </dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>
    );
  return (
    <Card>
      <CardHeader>
        <CardTitle>{tag === null ? t("title") : t("titleTag", { tag })}</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0 overflow-x-auto">
        <table className="block w-full text-sm md:table">
          <thead className="text-muted-foreground hidden text-left text-xs md:table-header-group">
            <tr>
              <th className="py-1 pr-3 font-normal">{t("side")}</th>
              <th className="py-1 pr-3 font-normal">{t("passRate")}</th>
              <th className="py-1 pr-3 font-normal">{live ? t("pending") : t("undecided")}</th>
              <th className="py-1 pr-3 font-normal">{t("costPerPass")}</th>
              <th className="py-1 pr-3 font-normal">{t("tokens")}</th>
              <th className="py-1 pr-3 font-normal">{t("latency")}</th>
            </tr>
          </thead>
          <tbody className="block tabular-nums md:table-row-group">
            {arms.map((arm) => (
              <tr
                key={arm.id}
                className="block border-b py-3 last:border-b-0 md:table-row md:border-t md:border-b-0 md:py-0"
              >
                <td className="block py-2 font-medium break-words md:table-cell md:pr-3 md:font-normal">
                  <SideLabel agentId={agentId} arm={arm} baseline={baseline} check={check} />
                </td>
                {/* An arm with no case under the tag has no entry for it. */}
                <SummaryCells
                  summary={
                    arm.failed_alike != null
                      ? undefined
                      : tag === null
                        ? arm.summary
                        : arm.by_tag[tag]
                  }
                  live={live}
                />
              </tr>
            ))}
            {earlier !== null && (
              <tr className="block border-b py-3 last:border-b-0 md:table-row md:border-t md:border-b-0 md:py-0">
                <td className="block py-2 font-medium break-words md:table-cell md:pr-3 md:font-normal">
                  {tSide("sideModel", {
                    name: sideName(earlier, tSide),
                    model: earlier.model_label,
                  })}
                  {" · "}
                  <Link
                    href={`${ROUTES.AGENTS}/${agentId}/evals/${earlier.run_id}`}
                    className="text-muted-foreground underline underline-offset-4"
                  >
                    {earlier.finished_at
                      ? tSide("arms.reusedFrom", {
                          date: formatDateTime(earlier.finished_at, locale),
                        })
                      : tSide("arms.reused")}
                  </Link>
                </td>
                <SummaryCells
                  summary={tag === null ? (baselineSummary ?? undefined) : undefined}
                  live={live}
                />
              </tr>
            )}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
