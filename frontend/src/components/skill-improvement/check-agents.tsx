"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, Eye } from "lucide-react";
import { useTranslations } from "next-intl";

import { CriteriaTable, verdictRows } from "@/components/improvement/criteria";
import { useReadOnly } from "@/components/improvement/read-only";
import { StateBadge, type Tone } from "@/components/improvement/widgets";
import { Checkbox, SearchInput, Label } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { SkillCheck, SkillCheckAgent, UnknownReason } from "@/types/skill-checks";
import { AddTestQuestions } from "./add-test-questions";
import { bucketOf, CheckSummary, shownState, type Bucket } from "./check-summary";
import { SetUpGrading } from "./set-up-grading";
import { StageBreakdown } from "./stage-breakdown";

const TONE: Record<ReturnType<typeof shownState>, Tone> = {
  queued: "neutral",
  running: "neutral",
  better: "good",
  criteria_better: "good",
  no_change: "neutral",
  criteria_worse: "bad",
  worse: "bad",
  unknown: "warn",
};

/** The groups in the order a person reads them: what blocks a decision first. */
const GROUPS: Bucket[] = ["worse", "unknown", "pending", "same", "better"];
const REASONS: (UnknownReason | "other" | null)[] = [
  "no_questions",
  "no_budget",
  "no_access",
  "no_published_version",
  "inconclusive",
  "failed",
  "unscorable",
  "all_evidence",
  "own_not_asked",
  "too_few_questions",
  "cancelled",
  "other",
  null,
];

/** A reason this page does not know by name is still a reason: it reads as "other". */
const reasonOf = (row: SkillCheckAgent): UnknownReason | "other" | null =>
  row.unknown_reason === null || REASONS.includes(row.unknown_reason)
    ? row.unknown_reason
    : "other";

const byName = (a: SkillCheckAgent, b: SkillCheckAgent) => a.agent.name.localeCompare(b.agent.name);

/** The worst-hit first among the worse, the most helped first among the better. */
function sortWithin(bucket: Bucket, rows: SkillCheckAgent[]): SkillCheckAgent[] {
  if (bucket === "worse") return [...rows].sort((a, b) => b.broken - a.broken || byName(a, b));
  if (bucket === "better") return [...rows].sort((a, b) => b.fixed - a.fixed || byName(a, b));
  return [...rows].sort(byName);
}

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
 * The agents a check measured, for a person deciding on ten agents or fifty: how
 * many came out each way, each count a filter; what is left to look at among the
 * worse and the unknown; then the agents grouped by how they came out. The worse
 * and the unknown are open, the unknown by why nobody could check them; the rest
 * are counted until somebody opens them. A row opens to its details and is marked
 * seen once opened.
 */
export function CheckAgents({ check }: { check: SkillCheck }) {
  const t = useTranslations("skillImprovement.agents");
  const rows = check.agents;
  const hidden = check.hidden + check.hidden_unknown;
  const [seen, mark] = useSeen(check.id);
  // Writing test questions edits the skill, which a reader who may only view cannot.
  const readOnly = useReadOnly();
  const [active, setActive] = useState<ReadonlySet<Bucket>>(new Set());
  // Who had been looked at when the filter went on: a row opened under the filter
  // stays, so its details can be read.
  const [unseenFrom, setUnseenFrom] = useState<ReadonlySet<string> | null>(null);
  const [query, setQuery] = useState("");
  const flip = (set: ReadonlySet<Bucket>, bucket: Bucket) => {
    const next = new Set(set);
    if (!next.delete(bucket)) next.add(bucket);
    return next;
  };
  const toLook = rows.filter((row) => ["worse", "unknown"].includes(bucketOf(row.state)));
  const left = toLook.filter((row) => !seen.has(keyOf(row))).length;
  const needle = query.trim().toLocaleLowerCase();
  const shown = rows.filter(
    (row) =>
      (active.size === 0 || active.has(bucketOf(row.state))) &&
      (unseenFrom === null || !unseenFrom.has(keyOf(row))) &&
      (needle === "" ||
        `${row.agent.name} ${row.via_specialist ?? ""}`.toLocaleLowerCase().includes(needle)),
  );
  const row = (item: SkillCheckAgent) => (
    <AgentRow
      key={keyOf(item)}
      row={item}
      seen={seen.has(keyOf(item))}
      onOpen={() => mark(keyOf(item))}
    />
  );
  return (
    <div className="space-y-3" data-tour="skill-improvement-agents">
      <CheckSummary
        agents={rows}
        active={active}
        onToggle={(bucket) => setActive(flip(active, bucket))}
      />
      {rows.length > 1 && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
          <p className="font-medium">
            {toLook.length > 0 ? t("left", { left, total: toLook.length }) : t("nothingLeft")}
          </p>
          <span className="flex items-center gap-1.5">
            <Checkbox
              id={`unseen-${check.id}`}
              checked={unseenFrom !== null}
              onCheckedChange={(value) => setUnseenFrom(value === true ? new Set(seen) : null)}
            />
            <Label htmlFor={`unseen-${check.id}`} className="text-xs font-normal">
              {t("onlyUnseen")}
            </Label>
          </span>
          <SearchInput
            value={query}
            onChange={setQuery}
            label={t("search")}
            placeholder={t("search")}
            className="sm:w-64"
          />
        </div>
      )}
      {shown.length === 0 && rows.length > 0 && (
        <p className="text-muted-foreground text-sm">{t("noMatch")}</p>
      )}
      {shown.some((item) => bucketOf(item.state) === "worse") && (
        <WhereItBroke worse={shown.filter((item) => bucketOf(item.state) === "worse")} />
      )}
      <ul className="bg-card divide-border divide-y rounded-xl border">
        {GROUPS.flatMap((bucket) =>
          sortWithin(
            bucket,
            shown.filter((item) => bucketOf(item.state) === bucket),
          ),
        ).map(row)}
      </ul>
      {!readOnly &&
        shown.some(
          (item) =>
            item.unknown_reason === "no_questions" || item.unknown_reason === "all_evidence",
        ) && <AddTestQuestions skillId={check.skill_id} />}
      {!readOnly && shown.some((item) => item.unknown_reason === "unscorable") && (
        <SetUpGrading agents={shown.filter((item) => item.unknown_reason === "unscorable")} />
      )}
      {hidden > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("hidden", { count: check.hidden, unknown: check.hidden_unknown })}
        </p>
      )}
    </div>
  );
}

/**
 * How many of the worse agents asked the skill's own questions broke on them. Every
 * agent shares those, so a regression there points at the skill; one on an agent's
 * own set points at that agent. Said only once each of them has its counts kept.
 */
function WhereItBroke({ worse }: { worse: SkillCheckAgent[] }) {
  const t = useTranslations("skillImprovement.agents");
  const asked = worse.flatMap((row) => row.stages.filter((stage) => stage.kind === "skill_set"));
  if (asked.length === 0 || asked.some((stage) => !stage.counts)) return null;
  const broke = asked.filter((stage) => stage.counts!.broken > 0).length;
  return (
    <p className="text-muted-foreground pl-5 text-xs">
      {t("brokeOnSkill", { broke, total: asked.length })}
    </p>
  );
}

function AgentRow({
  row,
  seen,
  onOpen,
}: {
  row: SkillCheckAgent;
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
        <span className="min-w-0 flex-1 basis-48">
          <span className="block truncate text-sm font-medium">{row.agent.name}</span>
          {row.unknown_reason !== null && (
            <span className="text-muted-foreground mt-1 block max-w-xl text-xs">
              {t(`unknown.${reasonOf(row)}`, {
                fixed: row.fixed,
                broken: row.broken,
                heldOut: row.held_out,
              })}
            </span>
          )}
          {row.via_specialist !== null && (
            <span className="text-muted-foreground block text-xs">
              {t("viaSpecialist", { name: row.via_specialist })}
            </span>
          )}
        </span>
        <span className="flex items-center gap-3">
          {measured && (
            <span className="text-muted-foreground text-xs tabular-nums">
              {t(row.state === "within_noise" ? "fixedBrokenUnconfirmed" : "fixedBroken", {
                fixed: row.fixed,
                broken: row.broken,
              })}
            </span>
          )}
          {seen && (
            <span className="text-muted-foreground flex items-center gap-1 text-xs">
              <Eye className="h-3.5 w-3.5" aria-hidden />
              {t("seen")}
            </span>
          )}
          <StateBadge tone={TONE[shownState(row.state)]}>
            {t(`state.${shownState(row.state)}`)}
          </StateBadge>
          <ChevronDown
            aria-hidden
            className={cn(
              "text-muted-foreground h-4 w-4 transition-transform",
              open && "rotate-180",
            )}
          />
        </span>
      </button>
      {open && <AgentDetails row={row} />}
    </li>
  );
}

function AgentDetails({ row }: { row: SkillCheckAgent }) {
  const t = useTranslations("skillImprovement.agents");
  const ran = row.stages.filter((stage) => stage.eval_run_id !== null);
  return (
    <div className="space-y-2 px-4 pb-3">
      <CriteriaTable criteria={verdictRows(row.criteria ?? [], row.families ?? [])} />
      {row.sample === "skill_set_only" && (
        <p className="text-muted-foreground text-xs">{t("skillSetOnly")}</p>
      )}
      {row.sample === "own_not_asked" && (
        <p className="text-muted-foreground text-xs">{t("ownNotAsked")}</p>
      )}
      {ran.length > 0 && (
        <ul className="space-y-1 rounded-md border px-3 py-2">
          {ran.map((stage) => (
            <StageBreakdown
              key={stage.eval_run_id}
              agentId={row.agent.id}
              stage={stage}
              unconfirmed={row.state === "within_noise"}
            />
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
