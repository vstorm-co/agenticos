"use client";

import { useId } from "react";
import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";

import type { PassRateLine, PassRatePoint } from "@/components/charts/pass-rate-lines.impl";
import { ChoiceGroup } from "@/components/settings/choice-group";
import { useUrlState } from "@/hooks/use-url-state";
import { ROUTES } from "@/lib/constants";
import { CHART_MIN_HEIGHT, LINE_WIDTH } from "@/lib/dashboard/system";
import { cn, formatDateTime } from "@/lib/utils";
import type { EvalRun, Verdict } from "@/types/eval-runs";
import { percent } from "./format";
import { sideName } from "./names";

const PassRateLinesImpl = dynamic(
  () => import("@/components/charts/pass-rate-lines.impl").then((m) => m.PassRateLinesImpl),
  {
    ssr: false,
    loading: () => <div className="bg-muted h-full w-full animate-pulse rounded-md" />,
  },
);

/** The ranges the trend offers, counted in runs back from the newest; the first is the default. */
const RANGES = [10, 30] as const;

type Range = (typeof RANGES)[number] | "all";

/** The range a `?runs=` names: thirty or every run, and the newest ten for anything else. */
export function trendRange(param: string | null): Range {
  return param === "all" ? "all" : param === "30" ? 30 : 10;
}

/**
 * A verdict worth a colour of its own: what the run did to the cases. These
 * three colours belong to verdicts alone, so lines are told apart by their dash
 * and a run with no verdict is drawn in the lines' own neutral ink.
 */
const VERDICT_COLOR: Partial<Record<Verdict, string>> = {
  worse: "var(--color-destructive)",
  better: "var(--color-success)",
  mixed: "var(--color-warning)",
};

/** The lines' ink, and a run's when it has no verdict to colour it. */
const NEUTRAL = "var(--color-muted-foreground)";

/** One dash per line, so a second dataset never borrows a verdict's colour. */
const DASHES = [undefined, "6 4", "2 3", "10 3 2 3", "1 5"];

type Translate = (key: string, values?: Record<string, string | number>) => string;

/** When a run started, as short as an axis has room for: the time today, the date before. */
function tickWhen(createdAt: string, locale: string, today: string): string {
  const at = new Date(createdAt);
  return at.toDateString() === today
    ? at.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" })
    : at.toLocaleDateString(locale, { month: "short", day: "numeric" });
}

/**
 * Finished runs as lines, one per group - a dataset on an agent's page, an
 * agent on a dataset's - each run one step along, oldest first. A point is the
 * candidate's pass rate, each case as it settled, which is the number the
 * run's own page shows, coloured by what the run's verdict says it did to the
 * cases; the rest of the run is in its tooltip.
 */
export function passRateLines(
  runs: EvalRun[],
  group: (run: EvalRun) => { key: string; name: string },
  t: Translate,
  locale: string,
): PassRateLine[] {
  const lines = new Map<string, PassRateLine>();
  const finished = runs
    .filter((run) => run.status === "completed")
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
  const today = new Date().toDateString();
  let index = 0;
  for (const run of finished) {
    const arm =
      run.arms.find((item) => item.id === run.outcome?.candidate_arm_id) ??
      run.arms.find((item) => item.role === "candidate");
    if (arm === undefined || arm.summary.pass_rate === null) continue;
    const { key, name } = group(run);
    const line = lines.get(key) ?? {
      key,
      name,
      color: NEUTRAL,
      dash: DASHES[lines.size % DASHES.length],
      points: [],
    };
    lines.set(key, line);
    const verdict = run.outcome?.verdict ?? null;
    const draft = arm.source !== "version";
    const baseline = run.outcome?.baseline ?? null;
    line.points.push({
      index: index++,
      rate: arm.summary.pass_rate,
      tick: tickWhen(run.created_at, locale, today),
      draft,
      color: (verdict && VERDICT_COLOR[verdict]) ?? NEUTRAL,
      href: `${ROUTES.AGENTS}/${run.agent_id}/evals/${run.id}`,
      title: t("sideModel", { name: sideName(arm, t), model: arm.model_label }),
      details: [
        ...(baseline ? [t("trend.comparedWith", { name: sideName(baseline, t) })] : []),
        t("trend.rate", { rate: percent(arm.summary.pass_rate, locale) }),
        t("trend.verdict", { verdict: verdict ?? "none" }),
        formatDateTime(run.created_at, locale),
      ],
    } satisfies PassRatePoint);
  }
  return [...lines.values()];
}

/**
 * The pass-rate trend: a key to its lines and colours, the newest runs over a
 * range picked above the chart - ten, thirty or every run, kept in `?<rangeKey>=`
 * so Back and a link return to it - and, with one run, what makes it a trend.
 * A page drawing several trends gives each its own `rangeKey`.
 */
export function PassRateChart({
  lines,
  compact = false,
  rangeKey = "runs",
}: {
  lines: PassRateLine[];
  compact?: boolean;
  rangeKey?: string;
}) {
  const t = useTranslations("evals");
  const rangeLabel = useId();
  const [param, setParam] = useUrlState(rangeKey);
  const points = lines.reduce((sum, line) => sum + line.points.length, 0);
  if (points === 0) return null;
  const options = [
    ...RANGES.filter((count) => points > count).map((count) => ({
      value: String(count),
      label: t("trend.last", { count }),
    })),
    ...(points > RANGES[0] ? [{ value: "all", label: t("trend.all") }] : []),
  ];
  const range = trendRange(param);
  const shown = range === "all" || points <= range ? points : range;
  const visible = lines
    .map((line) => ({ ...line, points: line.points.filter((p) => p.index >= points - shown) }))
    .filter((line) => line.points.length > 0);
  return (
    <div className="space-y-2" data-tour="evals-trend">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <ul className="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 pt-1.5 text-xs">
          {visible.length > 1 &&
            visible.map((line) => (
              <li key={line.key} className="flex items-center gap-1.5">
                <svg className="h-2 w-5 shrink-0" viewBox="0 0 20 8" aria-hidden>
                  <line
                    x1="0"
                    y1="4"
                    x2="20"
                    y2="4"
                    stroke={line.color}
                    strokeWidth={LINE_WIDTH}
                    strokeDasharray={line.dash}
                  />
                </svg>
                {line.name}
              </li>
            ))}
          {(["worse", "better", "mixed"] as const).map((verdict) => (
            <li key={verdict} className="flex items-center gap-1.5">
              <span
                className="size-2.5 shrink-0 rounded-full"
                style={{ background: VERDICT_COLOR[verdict] }}
                aria-hidden
              />
              {t(`trend.key.${verdict}`)}
            </li>
          ))}
          <li className="flex items-center gap-1.5">
            <span
              className="border-muted-foreground size-2.5 shrink-0 rounded-full border-2"
              aria-hidden
            />
            {t("trend.key.draft")}
          </li>
        </ul>
        {options.length > 0 && (
          <div>
            <span id={rangeLabel} className="sr-only">
              {t("trend.range")}
            </span>
            <ChoiceGroup
              labelledBy={rangeLabel}
              value={shown === points ? "all" : String(shown)}
              options={options}
              onChange={(value) => setParam(value === String(RANGES[0]) ? null : value)}
            />
          </div>
        )}
      </div>
      <div
        role="group"
        aria-label={t("trend.label")}
        className={cn(CHART_MIN_HEIGHT, compact ? "h-56" : "h-64")}
      >
        <PassRateLinesImpl lines={visible} />
      </div>
      <p className="text-muted-foreground text-xs">
        {points === 1 ? t("trend.single") : t("trend.legend")}
      </p>
    </div>
  );
}
