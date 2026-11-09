"use client";

import { useTranslations } from "next-intl";

import type { SkillCheckAgent, UnknownReason } from "@/types/skill-checks";

const REASONS: readonly UnknownReason[] = [
  "no_questions",
  "no_access",
  "no_budget",
  "no_published_version",
  "inconclusive",
  "failed",
  "unscorable",
  "all_evidence",
  "cancelled",
  "own_not_asked",
];

/**
 * Before a check starts: one row per agent of the line and what it would be asked,
 * or why it cannot be checked. Agents the reader may not see are a count under the
 * list, never a name.
 */
export function CheckPlan({ agents, hidden }: { agents: SkillCheckAgent[]; hidden: number }) {
  const t = useTranslations("skills.check");
  return (
    <div className="space-y-2">
      {agents.length > 0 && (
        <ul className="divide-border divide-y rounded-md border text-sm">
          {agents.map((row) => (
            <li
              key={`${row.agent.id}:${row.via_specialist ?? ""}`}
              className="space-y-0.5 px-3 py-2"
            >
              <p className="font-medium">{row.agent.name}</p>
              <p className="text-muted-foreground text-xs">
                {row.unknown_reason !== null
                  ? REASONS.includes(row.unknown_reason)
                    ? t(`reason.${row.unknown_reason}`)
                    : t("reason.other")
                  : row.sample === "skill_set_only"
                    ? t("skillSetOnly")
                    : t("asked", {
                        count: row.stages.reduce((sum, stage) => sum + stage.cases, 0),
                      })}
              </p>
            </li>
          ))}
        </ul>
      )}
      {hidden > 0 && (
        <p className="text-muted-foreground text-xs">{t("hidden", { count: hidden })}</p>
      )}
    </div>
  );
}

/** While a check runs: how many of its agents are done, as words and as a bar. */
export function CheckProgress({ agents }: { agents: SkillCheckAgent[] }) {
  const t = useTranslations("skills.check");
  const done = agents.filter((row) => row.state !== "queued" && row.state !== "running").length;
  if (agents.length === 0) return null;
  return (
    <div className="space-y-1">
      <p className="text-muted-foreground text-xs">
        {t("progress", { done, total: agents.length })}
      </p>
      <div
        role="progressbar"
        aria-label={t("progressLabel")}
        aria-valuemin={0}
        aria-valuemax={agents.length}
        aria-valuenow={done}
        className="bg-muted h-1.5 overflow-hidden rounded-full"
      >
        <div
          className="bg-primary h-full animate-pulse transition-[width] duration-500 motion-reduce:animate-none"
          style={{ width: `${Math.max(4, (done / agents.length) * 100)}%` }}
        />
      </div>
    </div>
  );
}
