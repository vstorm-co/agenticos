"use client";

import dynamic from "next/dynamic";
import { useLocale, useTranslations } from "next-intl";

import type { PassRateLine, PassRatePoint } from "@/components/charts/pass-rate-lines.impl";
import { CHART_MIN_HEIGHT } from "@/lib/dashboard/system";
import { cn } from "@/lib/utils";
import type { EvalRun, EvalRunArm } from "@/types/eval-runs";
import { percent } from "./format";
import { sideName } from "./names";

const PassRateLinesImpl = dynamic(
  () => import("@/components/charts/pass-rate-lines.impl").then((m) => m.PassRateLinesImpl),
  {
    ssr: false,
    loading: () => <div className="bg-muted h-full w-full animate-pulse rounded-md" />,
  },
);

const SERIES = ["--series-1", "--series-2", "--series-3", "--series-4", "--series-5"];

type Translate = (key: string, values?: Record<string, string | number>) => string;

/**
 * Finished runs as lines over time, one per group - a dataset on an agent's
 * page, an agent on a dataset's. A point is the candidate's pass rate, each
 * case as it settled, which is the number the run's own page shows. Beside it,
 * dashed, the baseline each run was measured against - once per measurement:
 * a baseline several runs reused from one earlier run is one point, at the
 * time it was answered.
 */
export function passRateLines(
  runs: EvalRun[],
  group: (run: EvalRun) => { key: string; name: string },
  t: Translate,
  locale: string,
): PassRateLine[] {
  const lines = new Map<string, PassRateLine>();
  const lineOf = (key: string, name: string, dashed: boolean, color: string) => {
    const line = lines.get(key) ?? { key, name, color, dashed, points: [] };
    lines.set(key, line);
    return line;
  };
  const colors = new Map<string, string>();
  const measured = new Set<string>();
  const runOfArm = new Map(runs.flatMap((run) => run.arms.map((arm) => [arm.id, run] as const)));
  const finished = runs
    .filter((run) => run.status === "completed")
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
  for (const run of finished) {
    const arm =
      run.arms.find((item) => item.id === run.outcome?.candidate_arm_id) ??
      run.arms.find((item) => item.role === "candidate");
    if (arm === undefined || arm.summary.pass_rate === null) continue;
    const { key, name } = group(run);
    const color = colors.get(key) ?? `var(${SERIES[colors.size % SERIES.length]})`;
    colors.set(key, color);
    const at = Date.parse(run.created_at);
    const verdict = run.outcome?.verdict ?? "none";
    lineOf(key, name, false, color).points.push(
      point(arm, arm.summary.pass_rate, at, verdict, t, locale),
    );
    // What the candidate was measured against, the same run - so a drop on one
    // line reads beside whether the other moved too.
    const baseline = run.arms.find((item) => item.role === "baseline");
    const answered = baseline?.reused_from_arm_id ?? baseline?.id;
    if (baseline === undefined || answered === undefined || measured.has(answered)) continue;
    measured.add(answered);
    if (baseline.summary.pass_rate === null) continue;
    const original = runOfArm.get(answered)?.created_at ?? run.outcome?.baseline?.finished_at;
    lineOf(`${key}:baseline`, t("trend.baselineOf", { name }), true, color).points.push(
      point(
        baseline,
        baseline.summary.pass_rate,
        Date.parse(original ?? run.created_at),
        "none",
        t,
        locale,
        true,
      ),
    );
  }
  // A reused baseline is drawn when it was answered, which can be before the run reusing it.
  for (const line of lines.values()) line.points.sort((a, b) => a.at - b.at);
  return [...lines.values()];
}

/**
 * One run's side as a point: labelled with its version, or - for a draft, and
 * for a baseline, which is a measurement of a version at one time - with the
 * time it was answered.
 */
function point(
  arm: EvalRunArm,
  rate: number,
  at: number,
  verdict: string,
  t: Translate,
  locale: string,
  timed = false,
): PassRatePoint {
  const draft = arm.source !== "version";
  const time = new Date(at).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  const label = draft || timed ? t("trend.at", { name: sideName(arm, t), time }) : sideName(arm, t);
  return {
    at,
    rate,
    label,
    draft,
    detail: t("trend.point", {
      name: label,
      model: arm.model_label,
      rate: percent(rate, locale),
      verdict,
    }),
  };
}

/** The pass-rate trend, with its key and - with one run - what makes it a trend. */
export function PassRateChart({
  lines,
  compact = false,
}: {
  lines: PassRateLine[];
  compact?: boolean;
}) {
  const t = useTranslations("evals");
  const locale = useLocale();
  const points = lines.reduce((sum, line) => sum + line.points.length, 0);
  if (points === 0) return null;
  return (
    <div className="space-y-2" data-tour="evals-trend">
      {lines.length > 1 && (
        <ul className="text-muted-foreground flex flex-wrap items-center gap-3 text-xs">
          {lines.map((line) => (
            <li key={line.key} className="flex items-center gap-1.5">
              <span
                className="size-2.5 shrink-0 rounded-full"
                style={{ background: line.color }}
                aria-hidden
              />
              {line.name}
            </li>
          ))}
        </ul>
      )}
      <div
        role="img"
        aria-label={t("trend.label")}
        className={cn(CHART_MIN_HEIGHT, compact ? "h-32" : "h-48")}
      >
        <PassRateLinesImpl lines={lines} locale={locale} />
      </div>
      <p className="text-muted-foreground text-xs">
        {points === 1 ? t("trend.single") : t("trend.legend")}
      </p>
    </div>
  );
}
