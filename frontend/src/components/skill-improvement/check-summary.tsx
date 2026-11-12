"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { AgentCheckState, SkillCheckAgent } from "@/types/skill-checks";

/** The outcomes a check sorts its agents into, in the order the bar draws them. */
export const BUCKETS = ["worse", "unknown", "same", "better", "pending"] as const;
export type Bucket = (typeof BUCKETS)[number];

/** Within the test's noise is no change a person can act on, so it counts as the same. */
export function bucketOf(state: AgentCheckState): Bucket {
  if (state === "no_change" || state === "within_noise") return "same";
  if (state === "queued" || state === "running") return "pending";
  return state;
}

/** The state a row is shown as: within the test's noise reads as no change, like its group. */
export function shownState(state: AgentCheckState): Exclude<AgentCheckState, "within_noise"> {
  return state === "within_noise" ? "no_change" : state;
}

const FILL: Record<Bucket, string> = {
  worse: "bg-destructive",
  unknown: "bg-warning",
  same: "bg-muted-foreground/40",
  better: "bg-success",
  pending: "bg-muted",
};

/**
 * How many agents came out better, the same, worse or unknown, as one bar and its
 * counts. Agents still being checked are counted only while there are any. Each
 * count filters the list to its agents; pressed again, it lets them go.
 */
export function CheckSummary({
  agents,
  active,
  onToggle,
}: {
  agents: SkillCheckAgent[];
  active: ReadonlySet<Bucket>;
  onToggle: (bucket: Bucket) => void;
}) {
  const t = useTranslations("skillImprovement.agents.summary");
  const counts = new Map<Bucket, number>(BUCKETS.map((bucket) => [bucket, 0]));
  for (const row of agents) {
    const bucket = bucketOf(row.state);
    counts.set(bucket, counts.get(bucket)! + 1);
  }
  const shown = BUCKETS.filter((bucket) => bucket !== "pending" || counts.get("pending")! > 0);
  if (agents.length === 0) return null;
  return (
    <div className="space-y-1.5">
      <div className="bg-muted flex h-2.5 overflow-hidden rounded-full" aria-hidden>
        {shown.map((bucket) => (
          <div
            key={bucket}
            className={cn("h-full", FILL[bucket])}
            style={{ width: `${(counts.get(bucket)! / agents.length) * 100}%` }}
          />
        ))}
      </div>
      <div role="group" aria-label={t("filter")} className="flex flex-wrap gap-1.5 text-xs">
        {shown.map((bucket) => (
          <button
            key={bucket}
            type="button"
            aria-pressed={active.has(bucket)}
            disabled={counts.get(bucket) === 0}
            onClick={() => onToggle(bucket)}
            className={cn(
              "flex items-center gap-1.5 rounded-full border px-2 py-0.5 disabled:opacity-50",
              active.has(bucket) ? "bg-muted border-foreground/30" : "border-transparent",
            )}
          >
            <span className={cn("size-2 rounded-full", FILL[bucket])} aria-hidden />
            {t(bucket, { count: counts.get(bucket)! })}
          </button>
        ))}
      </div>
    </div>
  );
}

/** What one agent fixed against what it broke, on the scale of the agent with the most. */
export function FixBreakBar({
  fixed,
  broken,
  most,
}: {
  fixed: number;
  broken: number;
  most: number;
}) {
  if (most === 0) return null;
  return (
    <div className="bg-muted flex h-1.5 w-24 overflow-hidden rounded-full" aria-hidden>
      <div className="bg-success h-full" style={{ width: `${(fixed / most) * 100}%` }} />
      <div className="bg-destructive h-full" style={{ width: `${(broken / most) * 100}%` }} />
    </div>
  );
}
