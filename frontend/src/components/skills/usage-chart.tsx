"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import type { UsageDay, UsageLine } from "@/components/charts/usage-lines.impl";
import { CHART_MIN_HEIGHT } from "@/lib/dashboard/system";
import { cn } from "@/lib/utils";
import type { SkillUsageAgent } from "@/types/skill-versions";

const UsageLinesImpl = dynamic(
  () => import("@/components/charts/usage-lines.impl").then((m) => m.UsageLinesImpl),
  {
    ssr: false,
    loading: () => <div className="bg-muted h-full w-full animate-pulse rounded-md" />,
  },
);

/** How many agents the chart overlays before anyone picks: the ones that used it most. */
const FIRST_PICKED = 5;

/**
 * The days from the first one any picked agent loaded the skill on, through the last
 * day counted; none when the picked agents loaded it on no day at all.
 */
export function fromFirstLoad(days: UsageDay[], picked: ReadonlySet<string>): UsageDay[] {
  const first = days.findIndex((day) => [...picked].some((key) => Number(day[key]) > 0));
  return first === -1 ? [] : days.slice(first);
}

/** How an agent's face is drawn: its handle, and the picture or colour it chose. */
export interface Face {
  slug: string;
  hasAvatar?: boolean;
  colorSlot?: number | null;
}

/**
 * One line chart of loads per day, overlaying the agents picked from the list above
 * it - each agent in its own colour, the busiest few picked to start with.
 */
export function UsageChart({
  agents,
  lines,
  days,
  faceOf,
}: {
  agents: SkillUsageAgent[];
  lines: UsageLine[];
  days: UsageDay[];
  faceOf: (agent: SkillUsageAgent) => Face;
}) {
  const t = useTranslations("skills.page.usage");
  const [picked, setPicked] = useState<Set<string>>(
    () =>
      new Set(
        [...agents]
          .sort((a, b) => b.loads - a.loads)
          .slice(0, FIRST_PICKED)
          .map((agent) => agent.agent_id),
      ),
  );
  const lineOf = new Map(lines.map((line) => [line.key, line]));
  const shown = fromFirstLoad(days, picked);
  const toggle = (id: string) => {
    const next = new Set(picked);
    if (!next.delete(id)) next.add(id);
    setPicked(next);
  };
  return (
    <div className="space-y-3 px-4 pt-4">
      <div role="group" aria-label={t("pick")} className="flex flex-wrap gap-1.5">
        {agents.map((agent) => {
          const on = picked.has(agent.agent_id);
          const face = faceOf(agent);
          return (
            <button
              key={agent.agent_id}
              type="button"
              aria-pressed={on}
              className={cn(
                "flex items-center gap-1.5 rounded-full border py-0.5 pr-2.5 pl-0.5 text-xs transition",
                on ? "bg-card border-foreground/20" : "text-muted-foreground opacity-60",
              )}
              onClick={() => toggle(agent.agent_id)}
            >
              <AgentAvatar
                agentId={agent.agent_id}
                slug={face.slug}
                hasAvatar={face.hasAvatar}
                colorSlot={face.colorSlot}
                size="sm"
              />
              {agent.agent_name}
              <span
                aria-hidden
                className="h-0.5 w-3 rounded-full"
                style={{ background: on ? lineOf.get(agent.agent_id)!.color : "currentColor" }}
              />
            </button>
          );
        })}
      </div>
      <div className={cn("h-56", CHART_MIN_HEIGHT)} role="img" aria-label={t("chart")}>
        {picked.size === 0 || shown.length === 0 ? (
          <p className="text-muted-foreground flex h-full items-center justify-center text-sm">
            {picked.size === 0 ? t("pickNone") : t("noLoads")}
          </p>
        ) : (
          <UsageLinesImpl lines={lines.filter((line) => picked.has(line.key))} days={shown} />
        )}
      </div>
    </div>
  );
}
