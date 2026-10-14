"use client";

import { Check } from "lucide-react";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import type { DelegateRef } from "@/lib/delegations";
import { cn } from "@/lib/utils";
import type { DelegationStatus } from "@/types";

/** The catalog key for each status, translated at the point of use. */
export const STATUS_KEY: Record<DelegationStatus, string> = {
  running: "working",
  completed: "finished",
  failed: "failed",
  cancelled: "stopped",
  awaiting_approval: "awaiting",
};

/** One delegate on the strip: who, and where its work stands. */
export interface HandoffLane {
  key: string;
  delegate: DelegateRef;
  status: DelegationStatus;
}

function Face({
  who,
  className,
  thinking,
}: {
  who: DelegateRef;
  className?: string;
  thinking?: boolean;
}) {
  return (
    <AgentAvatar
      agentId={who.id ?? who.slug}
      slug={who.slug}
      hasAvatar={who.has_avatar}
      colorSlot={who.avatar_color}
      size="sm"
      thinking={thinking}
      className={className}
    />
  );
}

/**
 * The team at work: the agent that was asked on the left, a lane to each agent it
 * handed part of the job to, and the brief travelling out along it.
 *
 * Drawn while the work is out and gone once it is back - the "Asked …" steps keep
 * the record. A delegate that is working hops, each a beat after the one before,
 * so three at once read as a conversation; one that has answered sends a dot back
 * down its lane and settles with a check. The words beside each face say the same
 * thing for anybody who has motion turned off.
 */
export function DelegationHandoff({
  parent,
  lanes,
  selected = null,
  onSelect,
  named = true,
}: {
  parent?: DelegateRef;
  lanes: HandoffLane[];
  /**
   * Off over the live panels, which already name each delegate and say where it
   * stands: there the strip is the faces and the motion, and nothing twice.
   */
  named?: boolean;
  /** The lane opened below the strip, where the strip lets one be opened. */
  selected?: string | null;
  /** Makes each delegate a button that opens what it was asked and answered. */
  onSelect?: (key: string) => void;
}) {
  const t = useTranslations("chat.delegation");
  if (lanes.length === 0) return null;
  const working = lanes.some((lane) => lane.status === "running");

  return (
    <div role="group" aria-label={t("teamAtWork")} className="flex items-center gap-3 py-2">
      {parent && (
        <Face
          who={parent}
          thinking={working}
          className={cn("h-8 w-8 rounded-full", working && "handoff-pulse")}
        />
      )}
      <div className="min-w-0 flex-1 space-y-1.5">
        {lanes.map((lane, index) => {
          const running = lane.status === "running";
          const answered = lane.status === "completed";
          return (
            <div key={lane.key} className="flex items-center gap-2.5">
              {/* The lane: what was asked going out, the answer coming back. */}
              <div className="relative h-px w-16 shrink-0 sm:w-24">
                <div className="border-foreground/20 absolute inset-0 border-t border-dashed" />
                {running &&
                  [0, 0.5, 1].map((delay) => (
                    <span
                      key={delay}
                      aria-hidden
                      className="handoff-out bg-foreground/55 absolute top-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full opacity-0"
                      style={{ animationDelay: `${delay + index * 0.2}s` }}
                    />
                  ))}
                {answered && (
                  <span
                    aria-hidden
                    className="handoff-back bg-success absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full opacity-0"
                  />
                )}
              </div>
              <Lane
                lane={lane}
                beat={index}
                named={named}
                selected={selected === lane.key}
                onSelect={onSelect && (() => onSelect(lane.key))}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** A delegate at the end of its lane: its face, its name, where its work stands. */
function Lane({
  lane,
  beat,
  named,
  selected,
  onSelect,
}: {
  lane: HandoffLane;
  /** Its place in the team, which staggers its hop against the others'. */
  beat: number;
  named: boolean;
  selected: boolean;
  onSelect?: () => void;
}) {
  const t = useTranslations("chat.delegation");
  const running = lane.status === "running";
  const answered = lane.status === "completed";
  const body = (
    <>
      <span
        className={cn("relative shrink-0", running && "blob-hop")}
        style={running ? { animationDelay: `${beat * 0.18}s` } : undefined}
      >
        <span title={named ? undefined : lane.delegate.name}>
          <Face who={lane.delegate} thinking={running} className="h-7 w-7" />
        </span>
        {answered && (
          <span className="bg-success ring-background absolute -right-0.5 -bottom-0.5 grid size-3 place-items-center rounded-full ring-2">
            <Check className="text-background h-2 w-2" strokeWidth={3} aria-hidden />
          </span>
        )}
      </span>
      {named && (
        <>
          <span className="text-foreground/80 min-w-0 truncate text-[13px] font-medium">
            {lane.delegate.name}
          </span>
          <span
            className={cn(
              "shrink-0 text-xs",
              running ? "text-foreground/60" : "text-muted-foreground",
              lane.status === "failed" && "text-destructive",
            )}
          >
            {t(STATUS_KEY[lane.status])}
          </span>
        </>
      )}
    </>
  );
  if (!onSelect) return <span className="flex min-w-0 items-center gap-2.5">{body}</span>;
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-expanded={selected}
      className={cn(
        "hover:bg-foreground/[0.04] -my-0.5 flex min-w-0 items-center gap-2.5 rounded-full py-0.5 pr-2.5 pl-0.5 transition-colors",
        selected && "bg-foreground/[0.05]",
      )}
    >
      {body}
    </button>
  );
}
