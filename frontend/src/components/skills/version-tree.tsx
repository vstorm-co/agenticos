"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { ErrorState } from "@/components/states";
import { ListCard } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { versionTree, type TreeFork, type TreeRow } from "@/lib/skill-version-tree";
import { cn } from "@/lib/utils";
import type { SkillAgentUsage, SkillFork } from "@/types/skill-versions";
import { eachAgentOnce } from "./skill-lines";

const CHIPS = 3;

/**
 * The skill's versions as a branch diagram: main runs down from its newest, each
 * fork branches off the version it started from, and agents sit at the version
 * they are served. Stretches nobody uses fold, and unfold on request.
 */
export function VersionTree({
  mainLatest,
  forks,
  agents,
  error,
}: {
  mainLatest: number;
  forks: SkillFork[];
  agents: SkillAgentUsage[];
  /** Why the agents could not be read; the tree is not drawn without them. */
  error: unknown;
}) {
  const t = useTranslations("skills.page.tree");
  const tErrors = useTranslations("errors");
  const [expanded, setExpanded] = useState<Map<string, Set<number>>>(new Map());
  const unfold = (line: string, from: number, to: number) =>
    setExpanded((was) => {
      const next = new Map(was);
      const numbers = new Set(was.get(line));
      for (let number = to; number <= from; number += 1) numbers.add(number);
      next.set(line, numbers);
      return next;
    });
  const rows = versionTree({ mainLatest, forks, agents, expanded });
  return (
    <ListCard
      title={t("title")}
      counted={t("summary", { versions: mainLatest, forks: forks.length })}
      headerTour="skill-tree"
    >
      {error ? (
        <ErrorState description={getErrorMessage(error, tErrors)} />
      ) : (
        <div className="p-4">
          <Line rows={rows} line="main" onUnfold={unfold} />
        </div>
      )}
    </ListCard>
  );
}

function Line({
  rows,
  line,
  onUnfold,
}: {
  rows: TreeRow[];
  line: string;
  onUnfold: (line: string, from: number, to: number) => void;
}) {
  const t = useTranslations("skills.page.tree");
  return (
    <ol className="relative">
      {rows.map((row, index) => (
        <li key={row.kind === "gap" ? `gap-${row.from}` : row.number} className="relative pl-6">
          {index < rows.length - 1 && (
            <span
              aria-hidden
              className={cn(
                "bg-border absolute top-3 bottom-0 left-[5px] w-0.5",
                row.kind === "gap" && "border-border border-l-2 border-dashed bg-transparent",
              )}
            />
          )}
          {row.kind === "gap" ? (
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground py-1.5 text-xs underline-offset-4 hover:underline"
              onClick={() => onUnfold(line, row.from, row.to)}
            >
              {t("folded", { count: row.count, from: row.from, to: row.to })}
            </button>
          ) : (
            <>
              <span
                aria-hidden
                className={cn(
                  "absolute top-[0.45rem] left-0 size-3 rounded-full border-2",
                  row.latest
                    ? "bg-primary border-primary"
                    : "bg-background border-muted-foreground",
                )}
              />
              <div className="flex min-h-7 flex-wrap items-center gap-2 py-0.5">
                <span className="font-mono text-sm font-medium">
                  {t("number", { number: row.number })}
                </span>
                {row.latest && <span className="text-muted-foreground text-xs">{t("latest")}</span>}
                <Chips agents={row.agents} />
              </div>
              {row.forks.map((branch) => (
                <Branch key={branch.fork.id} branch={branch} onUnfold={onUnfold} />
              ))}
            </>
          )}
        </li>
      ))}
    </ol>
  );
}

/** A fork, drawn off its base version with its own line of versions. */
function Branch({
  branch,
  onUnfold,
}: {
  branch: TreeFork;
  onUnfold: (line: string, from: number, to: number) => void;
}) {
  const t = useTranslations("skills.page.tree");
  const { fork } = branch;
  return (
    <div className="relative mt-1 mb-2 pl-5">
      <span aria-hidden className="bg-border absolute top-3 left-[-18px] h-0.5 w-8" />
      <div className="flex flex-wrap items-center gap-2 py-0.5 text-sm">
        <span className="font-medium">{t("fork", { name: fork.name })}</span>
        <span className="text-muted-foreground text-xs">
          {t("forkFacts", { changes: fork.changes, behind: fork.behind_main })}
        </span>
        <Chips agents={branch.agents} />
      </div>
      {branch.rows.length > 0 && <Line rows={branch.rows} line={fork.id} onUnfold={onUnfold} />}
    </div>
  );
}

function Chips({ agents }: { agents: SkillAgentUsage[] }) {
  const t = useTranslations("skills.page.tree");
  const shown = eachAgentOnce(agents);
  if (shown.length === 0) return null;
  const rest = shown.slice(CHIPS);
  return (
    <span className="flex flex-wrap items-center gap-1">
      {shown.slice(0, CHIPS).map((usage) => (
        <span
          key={usage.agent.id}
          className="bg-muted inline-flex max-w-40 items-center gap-1 rounded-full py-0.5 pr-2 pl-0.5 text-xs"
        >
          <AgentAvatar
            agentId={usage.agent.id}
            slug={usage.agent.slug}
            hasAvatar={usage.agent.has_avatar}
            colorSlot={usage.agent.avatar_color}
            size="sm"
          />
          <span className="truncate">{usage.agent.name}</span>
        </span>
      ))}
      {rest.length > 0 && (
        <span
          className="text-muted-foreground text-xs"
          title={rest.map((usage) => usage.agent.name).join(", ")}
        >
          {t("moreAgents", { count: rest.length })}
        </span>
      )}
    </span>
  );
}
