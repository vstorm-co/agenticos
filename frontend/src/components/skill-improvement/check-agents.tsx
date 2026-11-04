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
import { StageBreakdown } from "./stage-breakdown";

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
    <li>
      <button
        type="button"
        aria-expanded={open}
        aria-label={t("details", { name: row.agent.name })}
        className="hover:bg-muted/40 flex w-full flex-wrap items-center justify-between gap-2 px-4 py-3 text-left"
        onClick={() => {
          setOpen(!open);
          onOpen();
        }}
      >
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium">{row.agent.name}</span>
          {row.via_specialist !== null && (
            <span className="text-muted-foreground block text-xs">
              {t("viaSpecialist", { name: row.via_specialist })}
            </span>
          )}
        </span>
        <span className="flex items-center gap-3">
          {measured && <FixBreakBar fixed={row.fixed} broken={row.broken} most={most} />}
          {seen && (
            <span className="text-muted-foreground flex items-center gap-1 text-xs">
              <Eye className="h-3.5 w-3.5" aria-hidden />
              {t("seen")}
            </span>
          )}
          <StateBadge tone={TONE[row.state]}>{t(`state.${row.state}`)}</StateBadge>
          <ChevronDown
            aria-hidden
            className={cn(
              "text-muted-foreground h-4 w-4 transition-transform",
              open && "rotate-180",
            )}
          />
        </span>
      </button>
      {open && <AgentDetails row={row} measured={measured} />}
    </li>
  );
}

function AgentDetails({ row, measured }: { row: SkillCheckAgent; measured: boolean }) {
  const t = useTranslations("skillImprovement.agents");
  const ran = row.stages.filter((stage) => stage.eval_run_id !== null);
  return (
    <div className="space-y-2 px-4 pb-3">
      {measured && (
        <p className="text-sm">{t("fixedBroken", { fixed: row.fixed, broken: row.broken })}</p>
      )}
      {row.unknown_reason !== null && (
        <p className="text-muted-foreground text-sm">{t(`unknown.${row.unknown_reason}`)}</p>
      )}
      {row.sample === "skill_set_only" && (
        <p className="text-muted-foreground text-xs">{t("skillSetOnly")}</p>
      )}
      {ran.length > 0 && (
        <ul className="space-y-1 rounded-md border px-3 py-2">
          {ran.map((stage) => (
            <StageBreakdown key={stage.eval_run_id} agentId={row.agent.id} stage={stage} />
          ))}
        </ul>
      )}
      <Link
        href={ROUTES.AGENT_DETAIL(row.agent.id)}
        className="text-muted-foreground inline-block text-xs underline underline-offset-4"
      >
        {t("openAgent", { name: row.agent.name })}
      </Link>
    </div>
  );
}
