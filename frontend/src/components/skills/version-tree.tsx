"use client";

import { useCallback, useLayoutEffect, useState } from "react";
import { Columns2, GitBranch, GitCommitHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { MapZoomControls } from "@/components/agents/map-zoom-controls";
import { ErrorState } from "@/components/states";
import { ListCard } from "@/components/ui";
import { usePanZoom } from "@/hooks/use-pan-zoom";
import { getErrorMessage } from "@/lib/api-error";
import { NODE_WIDTH, versionDiagram, type DiagramBox } from "@/lib/skill-version-diagram";
import { versionTree } from "@/lib/skill-version-tree";
import { cn } from "@/lib/utils";
import type { SkillAgentUsage, SkillFork } from "@/types/skill-versions";
import { eachAgentOnce } from "./skill-lines";
import { VersionCompare, type Compared } from "./version-compare";

/** Room around the diagram inside its canvas. */
const PAD = 24;

/**
 * The skill's versions as a diagram: main runs left to right to its newest, each
 * fork branches off the version it started from on a lane of its own, and every
 * agent sits in the box of the version it is served. Stretches nobody uses fold,
 * and unfold on request. Any versions can be put side by side to compare.
 */
export function VersionTree({
  skillId,
  mainLatest,
  forks,
  agents,
  error,
}: {
  skillId: string;
  mainLatest: number;
  forks: SkillFork[];
  agents: SkillAgentUsage[];
  /** Why the agents could not be read; the tree is not drawn without them. */
  error: unknown;
}) {
  const t = useTranslations("skills.page.tree");
  const tErrors = useTranslations("errors");
  const [expanded, setExpanded] = useState<Map<string, Set<number>>>(new Map());
  const [compared, setCompared] = useState<Compared[]>([]);
  const unfold = (line: string, from: number, to: number) =>
    setExpanded((was) => {
      const next = new Map(was);
      const numbers = new Set(was.get(line));
      for (let number = to; number <= from; number += 1) numbers.add(number);
      next.set(line, numbers);
      return next;
    });
  const toggle = (item: Compared) =>
    setCompared((was) =>
      was.some((other) => other.key === item.key)
        ? was.filter((other) => other.key !== item.key)
        : [...was, item],
    );
  return (
    <div className="space-y-4">
      <ListCard
        title={t("title")}
        counted={t("summary", { versions: mainLatest, forks: forks.length })}
        headerTour="skill-tree"
      >
        {error ? (
          <ErrorState description={getErrorMessage(error, tErrors)} />
        ) : (
          <Diagram
            boxes={versionDiagram(versionTree({ mainLatest, forks, agents, expanded }))}
            compared={compared}
            onUnfold={unfold}
            onCompare={toggle}
          />
        )}
      </ListCard>
      {compared.length > 0 && (
        <VersionCompare
          skillId={skillId}
          compared={compared}
          onRemove={toggle}
          onClear={() => setCompared([])}
        />
      )}
    </div>
  );
}

function Diagram({
  boxes: diagram,
  compared,
  onUnfold,
  onCompare,
}: {
  boxes: ReturnType<typeof versionDiagram>;
  compared: Compared[];
  onUnfold: (line: string, from: number, to: number) => void;
  onCompare: (item: Compared) => void;
}) {
  const t = useTranslations("skills.page.tree");
  const { viewport, view, setView, zoomFromCentre, panHandlers } = usePanZoom();
  // The newest version is what a reader came for, and main ends on it at the right.
  const newest = useCallback(() => {
    const width = viewport.current!.getBoundingClientRect().width;
    setView({ x: Math.min(0, width - diagram.width - 2 * PAD), y: 0, scale: 1 });
  }, [viewport, setView, diagram.width]);
  useLayoutEffect(newest, [newest]);
  return (
    <div className="relative">
      <MapZoomControls
        onZoomIn={() => zoomFromCentre(1.25)}
        onZoomOut={() => zoomFromCentre(1 / 1.25)}
        onReset={newest}
      />
      <div
        ref={viewport}
        className="h-[28rem] cursor-grab touch-none overflow-hidden rounded-lg select-none active:cursor-grabbing"
        {...panHandlers}
      >
        <div
          className="relative origin-top-left"
          style={{
            width: diagram.width + 2 * PAD,
            height: diagram.height + 2 * PAD,
            padding: PAD,
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
          }}
        >
          <div className="relative" style={{ width: diagram.width, height: diagram.height }}>
            <svg
              className="pointer-events-none absolute inset-0"
              width={diagram.width}
              height={diagram.height}
              aria-hidden
            >
              {diagram.edges.map(({ key, path }) => (
                <path
                  key={key}
                  d={path}
                  fill="none"
                  strokeWidth={1.5}
                  strokeDasharray="4 4"
                  className="map-flow stroke-brand/50"
                />
              ))}
            </svg>
            {diagram.labels.map(({ fork, x, y }) => (
              <p
                key={fork.id}
                className="absolute flex items-center gap-1.5 text-xs whitespace-nowrap"
                style={{ left: x, top: y }}
              >
                <GitBranch className="text-primary size-3.5" aria-hidden />
                <span className="font-medium">{t("fork", { name: fork.name })}</span>
                <span className="text-muted-foreground">
                  {t("forkFacts", { changes: fork.changes, behind: fork.behind_main })}
                </span>
              </p>
            ))}
            <ol>
              {diagram.boxes.map(({ box, x, y, height }) => (
                <li
                  key={box.key}
                  className="absolute"
                  style={{ left: x, top: y, width: NODE_WIDTH, height }}
                >
                  <Box
                    box={box}
                    inComparison={compared.some((item) => item.key === box.key)}
                    onUnfold={onUnfold}
                    onCompare={onCompare}
                  />
                </li>
              ))}
            </ol>
          </div>
        </div>
      </div>
    </div>
  );
}

function Box({
  box,
  inComparison,
  onUnfold,
  onCompare,
}: {
  box: DiagramBox;
  inComparison: boolean;
  onUnfold: (line: string, from: number, to: number) => void;
  onCompare: (item: Compared) => void;
}) {
  const t = useTranslations("skills.page.tree");
  if (box.kind === "gap") {
    return (
      <button
        type="button"
        className="bg-card text-muted-foreground hover:text-foreground flex h-full w-full items-center justify-center rounded-xl border border-dashed text-xs"
        onClick={(event) => {
          event.stopPropagation();
          onUnfold(box.line, box.from, box.to);
        }}
      >
        {t("folded", { count: box.count, from: box.from, to: box.to })}
      </button>
    );
  }
  const name =
    box.kind === "empty-fork"
      ? t("noVersionYet")
      : box.fork === null
        ? t("number", { number: box.number })
        : t("forkNumber", { name: box.fork.name, number: box.number });
  return (
    <div
      className={cn(
        "bg-card h-full rounded-xl border",
        box.kind === "empty-fork" && "border-dashed",
        box.kind === "version" && box.latest && "border-brand/40 border-2",
        inComparison && "ring-brand ring-2",
      )}
    >
      <div className="flex h-11 items-center gap-1.5 px-3.5">
        <GitCommitHorizontal className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
        {/* The name is what the box is for, so the words around it give way first. */}
        <span
          title={name}
          className={cn(
            "min-w-0 truncate text-sm",
            box.kind === "version" && "font-mono font-medium",
          )}
        >
          {name}
        </span>
        {box.kind === "version" && box.latest && (
          <span className="text-muted-foreground min-w-0 shrink-[4] truncate text-xs">
            {t("latest")}
          </span>
        )}
        {box.kind === "version" && (
          <button
            type="button"
            aria-pressed={inComparison}
            aria-label={t("compare", { version: name })}
            title={inComparison ? t("comparing") : t("compareShort")}
            className={cn(
              "ml-auto flex shrink-0 items-center rounded-md p-1.5",
              inComparison
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
            onClick={(event) => {
              event.stopPropagation();
              onCompare({
                key: box.key,
                fork: box.fork?.id ?? null,
                number: box.number,
                newest: box.newest,
                name,
              });
            }}
          >
            <Columns2 className="size-3.5" aria-hidden />
          </button>
        )}
      </div>
      <Agents agents={box.agents} />
    </div>
  );
}

function Agents({ agents }: { agents: SkillAgentUsage[] }) {
  const shown = eachAgentOnce(agents);
  if (shown.length === 0) return null;
  return (
    <ul className="space-y-1 px-3.5 pb-2">
      {shown.map((usage, index) => (
        <li
          key={usage.agent.id}
          className="map-tile bg-muted/50 border-border/60 flex h-[26px] items-center gap-1.5 rounded-lg border px-1.5 text-xs"
          style={{ animationDelay: `${Math.min(index, 12) * 25}ms` }}
        >
          <AgentAvatar
            agentId={usage.agent.id}
            slug={usage.agent.slug}
            hasAvatar={usage.agent.has_avatar}
            colorSlot={usage.agent.avatar_color}
            size="sm"
            className="size-5"
          />
          <span className="truncate">{usage.agent.name}</span>
        </li>
      ))}
    </ul>
  );
}
