"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, Eye } from "lucide-react";
import { useTranslations } from "next-intl";

import { StateBadge, type Tone } from "@/components/improvement/widgets";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { AgentCheckState, SkillCheck, SkillCheckAgent } from "@/types/skill-checks";
import { CheckSummary, FixBreakBar } from "./check-summary";

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

const keyOf = (row: SkillCheckAgent) => `${row.agent.id}:${row.via_specialist ?? ""}`;

/**
 * The agents whose details this reader has opened on one check. Kept in the browser:
 * it only marks what is left to look at, so losing it costs a second look.
 */
function useSeen(checkId: string): [Set<string>, (key: string) => void] {
  const storageKey = `skill-check-seen:${checkId}`;
  const [seen, setSeen] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem(storageKey) ?? "[]") as string[]);
    } catch {
      return new Set();
    }
  });
  const mark = (key: string) => {
    if (seen.has(key)) return;
    const next = new Set([...seen, key]);
    setSeen(next);
    try {
      localStorage.setItem(storageKey, JSON.stringify([...next]));
    } catch {
      // Private windows refuse storage; the marks then last as long as the page.
    }
  };
  return [seen, mark];
}

/**
 * The agents a check measured: how many came out each way, then one row per agent,
 * worst first, with what it fixed against what it broke. A row opens to its details
 * and is marked seen once opened, so ten agents read as a list of what is left.
 */
export function CheckAgents({ check }: { check: SkillCheck }) {
  const t = useTranslations("skillImprovement.agents");
  const rows = [...check.agents].sort((a, b) => ORDER.indexOf(a.state) - ORDER.indexOf(b.state));
  const hidden = check.hidden + check.hidden_unknown;
  const most = Math.max(0, ...rows.map((row) => row.fixed + row.broken));
  const [seen, mark] = useSeen(check.id);
  const looked = rows.filter((row) => seen.has(keyOf(row))).length;
  return (
    <div className="space-y-3" data-tour="skill-improvement-agents">
      <CheckSummary agents={rows} />
      {rows.length > 1 && (
        <p className="text-muted-foreground text-xs">
          {t("seenCount", { seen: looked, total: rows.length })}
        </p>
      )}
      <ul className="divide-border divide-y rounded-xl border">
        {rows.map((row) => (
          <AgentRow
            key={keyOf(row)}
            row={row}
            most={most}
            seen={seen.has(keyOf(row))}
            onOpen={() => mark(keyOf(row))}
          />
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

function AgentRow({
  row,
  most,
  seen,
  onOpen,
}: {
  row: SkillCheckAgent;
  most: number;
  seen: boolean;
  onOpen: () => void;
}) {
  const t = useTranslations("skillImprovement.agents");
  const [open, setOpen] = useState(false);
  const measured = !["queued", "running", "unknown"].includes(row.state);
  return (
    <li className="px-4 py-3">
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
        <div className="flex items-center gap-3">
          {measured && <FixBreakBar fixed={row.fixed} broken={row.broken} most={most} />}
          {seen && (
            <span className="text-muted-foreground flex items-center gap-1 text-xs">
              <Eye className="h-3.5 w-3.5" aria-hidden />
              {t("seen")}
            </span>
          )}
          <StateBadge tone={TONE[row.state]}>{t(`state.${row.state}`)}</StateBadge>
          <button
            type="button"
            aria-expanded={open}
            aria-label={t("details", { name: row.agent.name })}
            className="text-muted-foreground hover:text-foreground"
            onClick={() => {
              setOpen(!open);
              onOpen();
            }}
          >
            <ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
          </button>
        </div>
      </div>
      {open && <AgentDetails row={row} measured={measured} />}
    </li>
  );
}

function AgentDetails({ row, measured }: { row: SkillCheckAgent; measured: boolean }) {
  const t = useTranslations("skillImprovement.agents");
  return (
    <div className="mt-2 space-y-1.5">
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
    </div>
  );
}
