"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import type { SkillCheckAgent } from "@/types/skill-checks";

const TONE = {
  better: "default",
  worse: "destructive",
} as const;

/**
 * One row per agent of the line: what it was asked and how it came out. Agents the
 * reader may not see are a count under the table, never a name.
 */
export function CheckAgents({ agents, hidden }: { agents: SkillCheckAgent[]; hidden: number }) {
  const t = useTranslations("skills.check");
  return (
    <div className="space-y-2">
      <ul className="divide-border divide-y rounded-md border text-sm">
        {agents.map((row) => (
          <li
            key={row.agent.id}
            className="flex flex-wrap items-center justify-between gap-2 px-3 py-2"
          >
            <div className="min-w-0 space-y-0.5">
              <p className="font-medium">{row.agent.name}</p>
              <p className="text-muted-foreground text-xs">
                {row.unknown_reason !== null
                  ? t(`reason.${row.unknown_reason}`)
                  : row.sample === "skill_set_only"
                    ? t("skillSetOnly")
                    : t("asked", {
                        count: row.stages.reduce((sum, stage) => sum + stage.cases, 0),
                      })}
              </p>
            </div>
            <Badge variant={row.state in TONE ? TONE[row.state as keyof typeof TONE] : "outline"}>
              {t(`state.${row.state}`)}
            </Badge>
          </li>
        ))}
      </ul>
      {hidden > 0 && (
        <p className="text-muted-foreground text-xs">{t("hidden", { count: hidden })}</p>
      )}
    </div>
  );
}
