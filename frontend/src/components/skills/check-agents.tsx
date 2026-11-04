"use client";

import { CheckCircle2, Clock, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { SkillCheckAgent } from "@/types/skill-checks";

const TONE = {
  better: "default",
  worse: "destructive",
} as const;

const waiting = (row: SkillCheckAgent) => row.state === "queued" || row.state === "running";

/**
 * One row per agent of the line: what it was asked and how it came out. While the
 * check runs, a bar says how many agents are done and each row whether it waits,
 * runs or has its verdict. Agents the reader may not see are a count under the
 * table, never a name.
 */
export function CheckAgents({
  agents,
  hidden,
  running = false,
}: {
  agents: SkillCheckAgent[];
  hidden: number;
  /** The check has started and is not finished: rows show their progress. */
  running?: boolean;
}) {
  const t = useTranslations("skills.check");
  const done = agents.filter((row) => !waiting(row)).length;
  return (
    <div className="space-y-2">
      {running && agents.length > 0 && (
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
      )}
      <ul className="divide-border divide-y rounded-md border text-sm">
        {agents.map((row) => (
          <li
            key={`${row.agent.id}:${row.via_specialist ?? ""}`}
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
            <span className="flex items-center gap-1.5">
              {running && <Progress row={row} />}
              <Badge variant={row.state in TONE ? TONE[row.state as keyof typeof TONE] : "outline"}>
                {t(`state.${row.state}`)}
              </Badge>
            </span>
          </li>
        ))}
      </ul>
      {hidden > 0 && (
        <p className="text-muted-foreground text-xs">{t("hidden", { count: hidden })}</p>
      )}
    </div>
  );
}

function Progress({ row }: { row: SkillCheckAgent }) {
  const Icon = row.state === "running" ? Loader2 : row.state === "queued" ? Clock : CheckCircle2;
  return (
    <Icon
      aria-hidden
      className={cn(
        "size-4",
        row.state === "running" && "text-primary animate-spin motion-reduce:animate-none",
        row.state === "queued" && "text-muted-foreground",
        !waiting(row) && "text-success",
      )}
    />
  );
}
