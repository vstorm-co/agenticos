"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { StateBadge, type Tone } from "@/components/improvement/widgets";
import { ROUTES } from "@/lib/constants";
import type { AgentCheckState, SkillCheck, SkillCheckAgent } from "@/types/skill-checks";

const TONE: Record<AgentCheckState, Tone> = {
  queued: "neutral",
  running: "neutral",
  better: "good",
  no_change: "neutral",
  within_noise: "warn",
  worse: "bad",
  unknown: "warn",
};

/** The agent a person has to look at first leads: worse, then unknown, then the rest. */
const ORDER: AgentCheckState[] = [
  "worse",
  "unknown",
  "within_noise",
  "running",
  "queued",
  "no_change",
  "better",
];

/** The agents a check measured, worst first, each with what it fixed and broke. */
export function CheckAgents({ check }: { check: SkillCheck }) {
  const t = useTranslations("skillImprovement.agents");
  const rows = [...check.agents].sort((a, b) => ORDER.indexOf(a.state) - ORDER.indexOf(b.state));
  const hidden = check.hidden + check.hidden_unknown;
  return (
    <div className="space-y-2" data-tour="skill-improvement-agents">
      <ul className="divide-border divide-y rounded-xl border">
        {rows.map((row) => (
          <AgentRow key={`${row.agent.id}:${row.via_specialist ?? ""}`} row={row} />
        ))}
      </ul>
      {hidden > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("hidden", { count: check.hidden, unknown: check.hidden_unknown })}
        </p>
      )}
    </div>
  );
}

function AgentRow({ row }: { row: SkillCheckAgent }) {
  const t = useTranslations("skillImprovement.agents");
  const measured = !["queued", "running", "unknown"].includes(row.state);
  return (
    <li className="space-y-1.5 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <Link
            href={ROUTES.AGENT_DETAIL(row.agent.id)}
            className="block truncate text-sm font-medium hover:underline"
          >
            {row.agent.name}
          </Link>
          {row.via_specialist !== null && (
            <p className="text-muted-foreground text-xs">
              {t("viaSpecialist", { name: row.via_specialist })}
            </p>
          )}
        </div>
        <StateBadge tone={TONE[row.state]}>{t(`state.${row.state}`)}</StateBadge>
      </div>
      {measured && (
        <p className="text-sm">{t("fixedBroken", { fixed: row.fixed, broken: row.broken })}</p>
      )}
      {row.unknown_reason !== null && (
        <p className="text-muted-foreground text-sm">{t(`unknown.${row.unknown_reason}`)}</p>
      )}
      {row.sample === "skill_set_only" && (
        <p className="text-muted-foreground text-xs">{t("skillSetOnly")}</p>
      )}
      {row.stages.some((stage) => stage.eval_run_id !== null) && (
        <p className="flex flex-wrap gap-x-3 text-xs">
          {row.stages.map(
            (stage) =>
              stage.eval_run_id !== null && (
                <Link
                  key={stage.eval_run_id}
                  className="underline underline-offset-4"
                  href={`${ROUTES.AGENT_DETAIL(row.agent.id)}/evals/${stage.eval_run_id}`}
                >
                  {t(`stage.${stage.kind}`, {
                    name: stage.dataset_name ?? "",
                    named: stage.dataset_name === null ? "no" : "yes",
                  })}
                </Link>
              ),
          )}
        </p>
      )}
    </li>
  );
}
